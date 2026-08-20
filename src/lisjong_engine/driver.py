"""Seat別の外部selectorでMatchStateを完走させる薄いdriver。"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TypeAlias

from lisjong_engine.action_descriptor import ActionDescriptor
from lisjong_engine.action_projection import ActionProjection, project_legal_actions
from lisjong_engine.match_state import CompletedMatch, MatchPhase, MatchState
from lisjong_engine.observation import SeatObservation
from lisjong_engine.observation_builder import build_seat_observation
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.round_state import RoundState
from lisjong_engine.seat import Seat

ActionSelector: TypeAlias = Callable[
    [SeatObservation, tuple[ActionDescriptor, ...]],
    ActionDescriptor,
]
SeatSelectors: TypeAlias = Mapping[Seat, ActionSelector]

_SEATS = tuple(Seat)
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
) -> CompletedMatch:
    """現在のvalidなMatchStateから再開し、CompletedMatchまで進める。"""
    if not isinstance(match_state, MatchState):
        raise TypeError("match_state must be a MatchState")
    selectors_by_seat = _validate_selectors(selectors)

    while True:
        phase = match_state.phase
        if phase is MatchPhase.FINISHED:
            return _completed_match(match_state)
        if phase is MatchPhase.AWAITING_ROUND:
            _require_match_shape(match_state, active_round=False, completed=False)
            match_state.start_round()
            continue
        if phase is MatchPhase.ROUND_IN_PROGRESS:
            _require_match_shape(match_state, active_round=True, completed=False)
            round_state = match_state.active_round
            if round_state is None:
                raise DriverStateError("a round in progress requires an active round")
            _advance_round(match_state, round_state, selectors_by_seat)
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
) -> None:
    phase = round_state.phase
    if phase is RoundPhase.AWAITING_DRAW:
        round_state.draw(_current_seat(round_state))
        return
    if phase is RoundPhase.AWAITING_RINSHAN_DRAW:
        round_state.draw_rinshan(_current_seat(round_state))
        return
    if phase is RoundPhase.AWAITING_DISCARD:
        _apply_turn_choice(match_state, round_state, selectors)
        return
    if phase in _REACTION_PHASES:
        _resolve_reaction_choices(match_state, round_state, selectors)
        return
    if phase is RoundPhase.AWAITING_WIN_FINALIZATION:
        round_state.finalize_pending_win(expected_revision=round_state.revision)
        return
    if phase is RoundPhase.FINISHED:
        match_state.settle_active_round()
        return
    if phase is RoundPhase.UNDEALT:
        raise DriverStateError(
            "driver cannot infer how to repair an undealt active round"
        )
    raise DriverStateError("unsupported round phase")


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
