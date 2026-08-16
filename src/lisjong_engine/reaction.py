"""反応windowのvalue modelと、優先順位解決をpureに行うmodule。

反応の選択は席ごとに`RoundState`へ逐次commitしない。callerは席ごとの
合法手snapshotからchoiceを選び、reaction window全体を1回のbatchとして
engineへ渡す。本moduleはそのbatchを、状態mutationから独立した値だけで
解決する。

```text
candidates + choices + RonResolutionPolicy -> ReactionResolution
```

choiceは`Mapping`のiteration順ではなく席identityで識別し、優先順位は
麻雀ルールと放銃者・宣言者からの席距離だけで決める。callerの入力順序を
結果へ持ち込まないため、`ReactionResolution`は候補・選択の双方を席距離
順のtupleへ正規化して保持する。

反応window自体にprocess-globalなIDやUUIDは持たせない。どのwindowを
解決しているかは、`RoundState`のrevision・phase・保留中の打牌／加槓／
暗槓によって局内で一意に決まる。
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from lisjong_engine.legal_action import (
    ChiLegalAction,
    DaiminkanLegalAction,
    LegalAction,
    PassLegalAction,
    PonLegalAction,
    ReactionOrigin,
    RonLegalAction,
    is_legal_action,
)
from lisjong_engine.rules import RonResolutionPolicy
from lisjong_engine.seat import Seat

_SEAT_ORDER = tuple(Seat)
_REACTION_SEAT_OFFSETS = (1, 2, 3)


class ReactionType(Enum):
    PASS = "pass"
    RON = "ron"
    PON = "pon"
    CHI = "chi"
    DAIMINKAN = "daiminkan"


_REACTION_TYPES_BY_ACTION_TYPE: tuple[tuple[type, ReactionType], ...] = (
    (PassLegalAction, ReactionType.PASS),
    (RonLegalAction, ReactionType.RON),
    (PonLegalAction, ReactionType.PON),
    (ChiLegalAction, ReactionType.CHI),
    (DaiminkanLegalAction, ReactionType.DAIMINKAN),
)

# 同じ牌へ複数席が反応したときの成立順位。値が小さいほど強い。ポンと
# 大明槓は同順位であり、同じ牌に対して両方が選ばれることは物理牌の
# 枚数から起こり得ない。
_PRIORITY = {
    ReactionType.RON: 0,
    ReactionType.PON: 1,
    ReactionType.DAIMINKAN: 1,
    ReactionType.CHI: 2,
    ReactionType.PASS: 3,
}

# 合法手snapshotの表示順。成立順位（`_PRIORITY`）とは別の関心事であり、
# ポンと大明槓を混ぜずに読めるよう独立して定義する。
_DISPLAY_RANK = {
    ReactionType.PASS: 0,
    ReactionType.RON: 1,
    ReactionType.PON: 2,
    ReactionType.DAIMINKAN: 3,
    ReactionType.CHI: 4,
}

# 打牌以外（加槓・暗槓）の反応windowで選べる反応。槍槓はロンとパスだけで
# あり、鳴きは発生しない。
_RON_ONLY_ORIGINS = (ReactionOrigin.KAKAN, ReactionOrigin.ANKAN)


def reaction_type_of(action: LegalAction) -> ReactionType:
    """反応actionの種別を返す。反応でないactionは受け付けない。"""
    for action_type, reaction_type in _REACTION_TYPES_BY_ACTION_TYPE:
        if isinstance(action, action_type):
            return reaction_type
    raise TypeError(f"{type(action).__name__} is not a reaction action")


def is_reaction_action(value: object) -> bool:
    """`value`が反応actionのいずれかであるかを返す。"""
    return isinstance(
        value,
        tuple(action_type for action_type, _ in _REACTION_TYPES_BY_ACTION_TYPE),
    )


def reaction_seat_order(source_seat: Seat) -> tuple[Seat, Seat, Seat]:
    """放銃者・宣言者から近い順に、反応できる3席を返す。

    優先順位のtie-breakと、resolutionの正規化順序の双方で使う唯一の
    席順である。callerが渡すMappingのiteration順は使わない。
    """
    if not isinstance(source_seat, Seat):
        raise TypeError("source_seat must be a Seat")
    index = _SEAT_ORDER.index(source_seat)
    return tuple(
        _SEAT_ORDER[(index + offset) % len(_SEAT_ORDER)]
        for offset in _REACTION_SEAT_OFFSETS
    )


def reaction_action_sort_key(action: LegalAction) -> tuple[int, tuple[int, ...]]:
    """反応actionのdeterministicな表示順を返す。

    パスを先頭に固定し、同じ種別のなかでは消費する物理牌IDの昇順にする。
    成立順位とは別概念であり、この順序は解決結果へ影響しない。
    """
    reaction_type = reaction_type_of(action)
    consumed = getattr(action, "consumed_tile_ids", ())
    return (_DISPLAY_RANK[reaction_type], tuple(consumed))


@dataclass(frozen=True)
class ReactionCandidate:
    """1席分の、実際に適用可能な反応actionの集合。

    反応できない席でもパスは常に含む。「非パスの反応がある席だけが
    候補になる」という意味にはしない。
    """

    seat: Seat
    actions: tuple[LegalAction, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")

        try:
            actions = tuple(self.actions)
        except TypeError:
            raise TypeError("actions must be an iterable of legal actions") from None
        if any(not is_reaction_action(action) for action in actions):
            raise TypeError("actions must contain only reaction actions")
        if len(set(actions)) != len(actions):
            raise ValueError("actions must not contain duplicates")
        if not any(isinstance(action, PassLegalAction) for action in actions):
            raise ValueError("reaction actions must include pass")

        object.__setattr__(self, "actions", actions)

    @property
    def can_ron(self) -> bool:
        return any(isinstance(action, RonLegalAction) for action in self.actions)


@dataclass(frozen=True)
class ReactionChoice:
    seat: Seat
    action: LegalAction

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not is_reaction_action(self.action):
            raise TypeError("action must be a reaction action")

    @property
    def reaction_type(self) -> ReactionType:
        return reaction_type_of(self.action)


@dataclass(frozen=True)
class ReactionResolution:
    """1つの反応windowの解決結果を表すimmutableな事実。

    ロンについては「和了できた」「選択した」「成立した」「見逃した」を
    別々に保持する。頭ハネで成立しなかったロン選択者は見逃しではない
    ため、`ron_passed_seats`へは含めない。この区別はフリテン更新と、
    E3の複数ロン・三家和判定の双方に必要である。
    """

    origin: ReactionOrigin
    source_seat: Seat
    target_tile_id: int
    candidates: tuple[ReactionCandidate, ...]
    choices: tuple[ReactionChoice, ...]
    resolved_type: ReactionType
    resolved_seat: Seat | None = None
    resolved_action: LegalAction | None = None
    ron_capable_seats: frozenset[Seat] = frozenset()
    ron_selected_seats: tuple[Seat, ...] = ()
    ron_awarded_seats: tuple[Seat, ...] = ()
    ron_passed_seats: frozenset[Seat] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.origin, ReactionOrigin):
            raise TypeError("origin must be a ReactionOrigin")
        if not isinstance(self.source_seat, Seat):
            raise TypeError("source_seat must be a Seat")
        if type(self.target_tile_id) is not int:
            raise TypeError("target_tile_id must be an int")
        if not isinstance(self.resolved_type, ReactionType):
            raise TypeError("resolved_type must be a ReactionType")

        candidates = _normalize_candidates(self.candidates, self.source_seat)
        choices = _normalize_choices(self.choices, self.source_seat)
        if tuple(choice.seat for choice in choices) != tuple(
            candidate.seat for candidate in candidates
        ):
            raise ValueError("exactly one choice is required for every candidate seat")

        actions_by_seat = {
            candidate.seat: candidate.actions for candidate in candidates
        }
        for choice in choices:
            if choice.action not in actions_by_seat[choice.seat]:
                raise ValueError("choice must be one of the seat's reaction actions")

        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "choices", choices)
        self._validate_ron_facts(candidates, choices)
        self._validate_resolved_call(choices)

    def _validate_ron_facts(
        self,
        candidates: tuple[ReactionCandidate, ...],
        choices: tuple[ReactionChoice, ...],
    ) -> None:
        capable = frozenset(self.ron_capable_seats)
        selected = tuple(self.ron_selected_seats)
        awarded = tuple(self.ron_awarded_seats)
        passed = frozenset(self.ron_passed_seats)
        if any(
            not isinstance(seat, Seat)
            for seat in (*capable, *selected, *awarded, *passed)
        ):
            raise TypeError("resolution seat fields must contain only Seat values")

        expected_capable = frozenset(
            candidate.seat for candidate in candidates if candidate.can_ron
        )
        if capable != expected_capable:
            raise ValueError("ron_capable_seats must match the candidates")

        expected_selected = tuple(
            choice.seat
            for choice in choices
            if choice.reaction_type is ReactionType.RON
        )
        if selected != expected_selected:
            raise ValueError("ron_selected_seats must match the ron choices")
        if passed != capable - frozenset(selected):
            raise ValueError("ron_passed_seats must be the capable seats that passed")
        if awarded != selected[: len(awarded)] or bool(awarded) is not bool(selected):
            raise ValueError("ron_awarded_seats must be a prefix of ron_selected_seats")

        object.__setattr__(self, "ron_capable_seats", capable)
        object.__setattr__(self, "ron_selected_seats", selected)
        object.__setattr__(self, "ron_awarded_seats", awarded)
        object.__setattr__(self, "ron_passed_seats", passed)

    def _validate_resolved_call(self, choices: tuple[ReactionChoice, ...]) -> None:
        if self.resolved_action is not None and not is_reaction_action(
            self.resolved_action
        ):
            raise TypeError("resolved_action must be a reaction action or None")
        if self.resolved_seat is not None and not isinstance(self.resolved_seat, Seat):
            raise TypeError("resolved_seat must be a Seat or None")

        if self.resolved_type is ReactionType.RON:
            if not self.ron_selected_seats:
                raise ValueError("a ron resolution requires a ron choice")
            if self.resolved_seat is not None or self.resolved_action is not None:
                raise ValueError("a ron resolution is described by its ron seat fields")
            return

        if self.ron_selected_seats:
            raise ValueError("a ron choice must resolve as ron")

        if self.resolved_type is ReactionType.PASS:
            if self.resolved_seat is not None or self.resolved_action is not None:
                raise ValueError("an all-pass resolution must not have a caller")
            if any(choice.reaction_type is not ReactionType.PASS for choice in choices):
                raise ValueError("an all-pass resolution requires every seat to pass")
            return

        if self.resolved_seat is None or self.resolved_action is None:
            raise ValueError("a call resolution requires the calling seat and action")
        if reaction_type_of(self.resolved_action) is not self.resolved_type:
            raise ValueError("resolved_action must match the resolved type")
        if ReactionChoice(self.resolved_seat, self.resolved_action) not in choices:
            raise ValueError("a call resolution must accept one of the choices")

    @property
    def is_ron(self) -> bool:
        return self.resolved_type is ReactionType.RON

    @property
    def all_passed(self) -> bool:
        return self.resolved_type is ReactionType.PASS

    @property
    def is_call(self) -> bool:
        return self.resolved_type in (
            ReactionType.PON,
            ReactionType.CHI,
            ReactionType.DAIMINKAN,
        )

    @property
    def reacting_seats(self) -> tuple[Seat, ...]:
        return tuple(candidate.seat for candidate in self.candidates)

    def choice_for(self, seat: Seat) -> LegalAction:
        for choice in self.choices:
            if choice.seat is seat:
                return choice.action
        raise ValueError("seat did not react to this window")


def resolve_reaction_choices(
    *,
    origin: ReactionOrigin,
    source_seat: Seat,
    target_tile_id: int,
    candidates: Mapping[Seat, Sequence[LegalAction]],
    choices: Mapping[Seat, LegalAction],
    ron_resolution_policy: RonResolutionPolicy,
) -> ReactionResolution:
    """反応windowを、席距離とルールだけからdeterministicに解決する。

    `candidates`は反応できる3席すべてを含む必要がある。反応できない席も
    パスだけの候補として含める。`choices`はその3席とちょうど一致しなければ
    ならず、不足・余分・非合法のいずれもwindow全体の拒否になる。
    """
    if not isinstance(origin, ReactionOrigin):
        raise TypeError("origin must be a ReactionOrigin")
    if type(target_tile_id) is not int:
        raise TypeError("target_tile_id must be an int")
    if not isinstance(ron_resolution_policy, RonResolutionPolicy):
        raise TypeError("ron_resolution_policy must be a RonResolutionPolicy")

    seat_order = reaction_seat_order(source_seat)
    _validate_reacting_seats(candidates, seat_order, "candidates")
    _validate_reacting_seats(choices, seat_order, "choices")

    candidate_values = tuple(
        ReactionCandidate(seat, tuple(candidates[seat])) for seat in seat_order
    )
    choice_values = tuple(ReactionChoice(seat, choices[seat]) for seat in seat_order)
    for choice in choice_values:
        _validate_action_target(choice.action, origin, target_tile_id)

    ron_selected = tuple(
        choice.seat
        for choice in choice_values
        if choice.reaction_type is ReactionType.RON
    )
    ron_capable = frozenset(
        candidate.seat for candidate in candidate_values if candidate.can_ron
    )
    if ron_selected:
        awarded = (
            ron_selected[:1]
            if ron_resolution_policy is RonResolutionPolicy.HEAD_BUMP
            else ron_selected
        )
        return ReactionResolution(
            origin=origin,
            source_seat=source_seat,
            target_tile_id=target_tile_id,
            candidates=candidate_values,
            choices=choice_values,
            resolved_type=ReactionType.RON,
            ron_capable_seats=ron_capable,
            ron_selected_seats=ron_selected,
            ron_awarded_seats=awarded,
            ron_passed_seats=ron_capable - frozenset(ron_selected),
        )

    accepted = _select_call(choice_values)
    return ReactionResolution(
        origin=origin,
        source_seat=source_seat,
        target_tile_id=target_tile_id,
        candidates=candidate_values,
        choices=choice_values,
        resolved_type=(
            ReactionType.PASS if accepted is None else accepted.reaction_type
        ),
        resolved_seat=None if accepted is None else accepted.seat,
        resolved_action=None if accepted is None else accepted.action,
        ron_capable_seats=ron_capable,
        ron_passed_seats=ron_capable,
    )


def _select_call(choices: tuple[ReactionChoice, ...]) -> ReactionChoice | None:
    """鳴きの選択から、優先順位と席距離で成立する1つを選ぶ。

    `choices`は既に席距離順へ正規化されているため、同順位の鳴きが複数
    あった場合は放銃者に最も近い席が選ばれる。
    """
    call_choices = tuple(
        choice for choice in choices if choice.reaction_type is not ReactionType.PASS
    )
    if not call_choices:
        return None
    return min(call_choices, key=lambda choice: _PRIORITY[choice.reaction_type])


def _validate_reacting_seats(
    values: Mapping[Seat, object],
    seat_order: tuple[Seat, ...],
    name: str,
) -> None:
    if not isinstance(values, Mapping):
        raise TypeError(f"{name} must be a mapping keyed by seat")
    if any(not isinstance(seat, Seat) for seat in values):
        raise TypeError(f"{name} must be keyed by Seat values")
    missing = tuple(seat for seat in seat_order if seat not in values)
    if missing:
        raise ValueError(f"{name} is missing the reacting seats {missing}")
    extra = frozenset(values) - frozenset(seat_order)
    if extra:
        raise ValueError(f"{name} contains seats that cannot react")


def _validate_action_target(
    action: LegalAction,
    origin: ReactionOrigin,
    target_tile_id: int,
) -> None:
    if not is_legal_action(action):
        raise TypeError("action must be a legal action")
    reaction_type = reaction_type_of(action)
    if reaction_type in (ReactionType.PASS, ReactionType.RON):
        if action.origin is not origin:
            raise ValueError("reaction action origin does not match this window")
    elif origin in _RON_ONLY_ORIGINS:
        raise ValueError("kakan and ankan reactions can only be pass or ron")
    if action.target_tile_id != target_tile_id:
        raise ValueError("reaction action target does not match this window")


def _normalize_candidates(
    candidates: Sequence[ReactionCandidate],
    source_seat: Seat,
) -> tuple[ReactionCandidate, ...]:
    try:
        values = tuple(candidates)
    except TypeError:
        raise TypeError("candidates must be an iterable of ReactionCandidate") from None
    if any(not isinstance(candidate, ReactionCandidate) for candidate in values):
        raise TypeError("candidates must contain only ReactionCandidate instances")
    if tuple(candidate.seat for candidate in values) != reaction_seat_order(
        source_seat
    ):
        raise ValueError("candidates must cover the reacting seats in seat order")
    return values


def _normalize_choices(
    choices: Sequence[ReactionChoice],
    source_seat: Seat,
) -> tuple[ReactionChoice, ...]:
    try:
        values = tuple(choices)
    except TypeError:
        raise TypeError("choices must be an iterable of ReactionChoice") from None
    if any(not isinstance(choice, ReactionChoice) for choice in values):
        raise TypeError("choices must contain only ReactionChoice instances")
    if tuple(choice.seat for choice in values) != reaction_seat_order(source_seat):
        raise ValueError("choices must cover the reacting seats in seat order")
    return values
