"""Seat別の外部selectorでMatchStateを完走させる薄いdriver。"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TypeAlias

from lisjong_engine.action_descriptor import ActionDescriptor
from lisjong_engine.action_projection import ActionProjection, project_legal_actions
from lisjong_engine.match_state import CompletedMatch, MatchPhase, MatchState
from lisjong_engine.observation import SeatObservation
from lisjong_engine.observation_builder import build_seat_observation
from lisjong_engine.round_completion import (
    MatchCompletionFact,
    RoundCompletionFact,
    project_match_completion,
    project_round_completion,
)
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.round_progress import RoundProgressFact, project_round_progress
from lisjong_engine.round_state import RoundState
from lisjong_engine.seat import Seat

ActionSelector: TypeAlias = Callable[
    [SeatObservation, tuple[ActionDescriptor, ...]],
    ActionDescriptor,
]
SeatSelectors: TypeAlias = Mapping[Seat, ActionSelector]

# 局内progressの順序付きfactと、局・半荘のplayer-safe completion factを、
# 同じordered batch abstractionで扱うdelivery境界。1つの成功したengine
# transactionにつき、そのtransactionが生じさせたfactだけを1回のbatchとして
# 渡す。progress facts / round completion / match completionのいずれも
# 生のinternal object（`RoundEvent`、`CompletedRound`等）を含まない。
DeliveryItem: TypeAlias = RoundProgressFact | RoundCompletionFact | MatchCompletionFact
DeliveryCallback: TypeAlias = Callable[[tuple[DeliveryItem, ...]], None]

_SEATS = tuple(Seat)
# current seatだけが選ぶdecision phase。立直選択後の宣言牌decisionも、
# 同じseatへ改めてselectorを呼ぶ独立decisionとして扱う。driverが宣言牌を
# 自動選択することはなく、候補が1件しかない場合も必ずselectorを呼ぶ。
_CURRENT_SEAT_DECISION_PHASES = frozenset(
    {
        RoundPhase.AWAITING_DISCARD,
        RoundPhase.AWAITING_RIICHI_DISCARD,
    }
)
_REACTION_PHASES = frozenset(
    {
        RoundPhase.AWAITING_REACTIONS,
        RoundPhase.AWAITING_KAKAN_REACTIONS,
        RoundPhase.AWAITING_ANKAN_REACTIONS,
    }
)


class DriverStateError(RuntimeError):
    """Match / Roundの内部phase contractが不整合であることを表す。"""


@dataclass(frozen=True)
class _DecisionSnapshot:
    observation: SeatObservation
    projection: ActionProjection


def run_hanchan(
    match_state: MatchState,
    selectors: SeatSelectors,
    *,
    on_delivery: DeliveryCallback | None = None,
) -> CompletedMatch:
    """現在のvalidなMatchStateから再開し、CompletedMatchまで進める。

    `on_delivery`を指定した場合、成功した各engine transaction直後に、その
    transactionが生じさせたordered progress fact、または局・半荘の
    completion factを、生のinternal objectを含まない1つのtupleとして
    同期的に渡す。callbackはtransactionの成功commit後にだけ呼ばれ、
    callback returnより前に次のtransition（次局の`start_round()`を含む）
    へは進まない。callbackが例外を送出した場合はfail-fastでそのまま
    呼び出し元へ伝播し、既に成功したengine transactionをrollbackしない。
    自動retry・自動replayは行わない。

    `on_delivery`を指定しない場合、既存の`run_hanchan()`のselector呼出
    順序・決定的進行・戻り値は変化しない。
    """
    if not isinstance(match_state, MatchState):
        raise TypeError("match_state must be a MatchState")
    selectors_by_seat = _validate_selectors(selectors)
    if on_delivery is not None and not callable(on_delivery):
        raise TypeError("on_delivery must be callable or None")

    event_cursor = (
        len(match_state.active_round.events)
        if match_state.active_round is not None
        else 0
    )

    while True:
        phase = match_state.phase
        if phase is MatchPhase.FINISHED:
            return _completed_match(match_state)
        if phase is MatchPhase.AWAITING_ROUND:
            _require_match_shape(match_state, active_round=False, completed=False)
            match_state.start_round()
            event_cursor = 0
            continue
        if phase is MatchPhase.ROUND_IN_PROGRESS:
            _require_match_shape(match_state, active_round=True, completed=False)
            round_state = match_state.active_round
            if round_state is None:
                raise DriverStateError("a round in progress requires an active round")
            if round_state.phase is RoundPhase.FINISHED:
                _settle_round(match_state, on_delivery)
                event_cursor = 0
                continue
            event_cursor = _advance_round(
                match_state,
                round_state,
                selectors_by_seat,
                on_delivery,
                event_cursor,
            )
            continue
        raise DriverStateError("unsupported match phase")


def _validate_selectors(selectors: SeatSelectors) -> dict[Seat, ActionSelector]:
    if not isinstance(selectors, Mapping):
        raise TypeError("selectors must be a mapping keyed by Seat")
    if set(selectors) != set(_SEATS):
        raise ValueError("selectors must contain exactly all four seats")
    if any(not callable(selectors[seat]) for seat in _SEATS):
        raise TypeError("every selector value must be callable")
    return {seat: selectors[seat] for seat in _SEATS}


def _require_match_shape(
    match_state: MatchState,
    *,
    active_round: bool,
    completed: bool,
) -> None:
    if (match_state.active_round is not None) is not active_round:
        raise DriverStateError("match phase and active round are inconsistent")
    if (match_state.completed_match is not None) is not completed:
        raise DriverStateError("match phase and completed match are inconsistent")


def _completed_match(match_state: MatchState) -> CompletedMatch:
    _require_match_shape(match_state, active_round=False, completed=True)
    completed = match_state.completed_match
    if completed is None:
        raise DriverStateError("a finished match requires a completed result")
    return completed


def _advance_round(
    match_state: MatchState,
    round_state: RoundState,
    selectors: dict[Seat, ActionSelector],
    on_delivery: DeliveryCallback | None = None,
    event_cursor: int = 0,
) -> int:
    """1つのround transactionを適用し、新しく確定したevent数を返す。

    `on_delivery`が指定されている場合、このtransactionが追加した
    `RoundEvent`のslice（`event_cursor`以降）だけをplayer-safe progress
    factへ射影し、空でなければ1回のbatchとして同期的にdeliveryする。
    `RoundState.revision`だけをevent cursorとして扱わず、実際に追加された
    event数で欠落なくsliceを取得する。
    """
    phase = round_state.phase
    if phase is RoundPhase.AWAITING_DRAW:
        round_state.draw(_current_seat(round_state))
    elif phase is RoundPhase.AWAITING_RINSHAN_DRAW:
        round_state.draw_rinshan(_current_seat(round_state))
    elif phase in _CURRENT_SEAT_DECISION_PHASES:
        _apply_turn_choice(match_state, round_state, selectors)
    elif phase in _REACTION_PHASES:
        _resolve_reaction_choices(match_state, round_state, selectors)
    elif phase is RoundPhase.AWAITING_WIN_FINALIZATION:
        round_state.finalize_pending_win(expected_revision=round_state.revision)
    elif phase is RoundPhase.UNDEALT:
        raise DriverStateError(
            "driver cannot infer how to repair an undealt active round"
        )
    else:
        raise DriverStateError("unsupported round phase")

    if on_delivery is None:
        return event_cursor
    return _deliver_new_progress(round_state, on_delivery, event_cursor)


def _deliver_new_progress(
    round_state: RoundState,
    on_delivery: DeliveryCallback,
    event_cursor: int,
) -> int:
    events = tuple(round_state.events)
    new_events = events[event_cursor:]
    facts = project_round_progress(new_events)
    if facts:
        on_delivery(facts)
    return len(events)


def _settle_round(
    match_state: MatchState,
    on_delivery: DeliveryCallback | None,
) -> None:
    """終了済みroundを精算し、成立していればcompletion factをdeliveryする。

    round completionとmatch completion（terminal局のみ）は、同じbatchで
    順序どおりに1回だけdeliveryする。callbackがreturnするまで、この関数の
    呼び出し元は次のtransition（次局の`start_round()`を含む）へ進まない。
    """
    completed_round = match_state.settle_active_round()
    if on_delivery is None:
        return

    items: list[DeliveryItem] = [project_round_completion(completed_round)]
    completed_match = match_state.completed_match
    if completed_match is not None:
        items.append(project_match_completion(completed_match))
    on_delivery(tuple(items))


def _current_seat(round_state: RoundState) -> Seat:
    seat = round_state.current_seat
    if seat is None:
        raise DriverStateError("the current round phase requires a current seat")
    return seat


def _build_decision_snapshot(
    match_state: MatchState,
    round_state: RoundState,
    seat: Seat,
) -> _DecisionSnapshot:
    legal_snapshot = round_state.legal_actions(seat)
    observation = build_seat_observation(match_state, seat)
    projection = project_legal_actions(legal_snapshot, round_state)
    return _DecisionSnapshot(observation, projection)


def _apply_turn_choice(
    match_state: MatchState,
    round_state: RoundState,
    selectors: dict[Seat, ActionSelector],
) -> None:
    seat = _current_seat(round_state)
    decision = _build_decision_snapshot(match_state, round_state, seat)
    public_choice = selectors[seat](
        decision.observation,
        decision.projection.options,
    )
    internal_action = decision.projection.resolve(public_choice)
    round_state.apply(
        seat,
        internal_action,
        expected_revision=decision.projection.revision,
    )


def _resolve_reaction_choices(
    match_state: MatchState,
    round_state: RoundState,
    selectors: dict[Seat, ActionSelector],
) -> None:
    shared_revision = round_state.revision
    reacting_seats = round_state.reacting_seats
    if len(reacting_seats) != 3:
        raise DriverStateError(
            "a reaction window requires exactly three reacting seats"
        )

    # 全seatのimmutable inputとlocal mappingを先に確定し、callback中は構築しない。
    decisions = tuple(
        _build_decision_snapshot(match_state, round_state, seat)
        for seat in reacting_seats
    )
    if any(decision.projection.revision != shared_revision for decision in decisions):
        raise DriverStateError("reaction decisions must share one state revision")

    public_choices = tuple(
        selectors[seat](decision.observation, decision.projection.options)
        for seat, decision in zip(reacting_seats, decisions, strict=True)
    )
    internal_choices = {
        seat: decision.projection.resolve(choice)
        for seat, decision, choice in zip(
            reacting_seats,
            decisions,
            public_choices,
            strict=True,
        )
    }
    round_state.resolve_reactions(
        internal_choices,
        expected_revision=shared_revision,
    )
