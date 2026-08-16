"""立直の「宣言」と「成立」を別の事実として扱うmodule。

立直宣言牌を打った瞬間に立直が成立するわけではない。宣言牌がロンされた
場合、その局に立直は成立せず供託も発生しない。

```text
declaration -> discard reaction -> finalization
```

宣言牌がポン・チー・大明槓で鳴かれた場合は、ロンではないため立直自体は
成立する。ただし一発は付かない。立直の成立と一発の成立を混同しない。

成立時に`RoundState`が記録するのは「供託が必要になったという事実」まで
であり、持ち点の減算は行わない。Match側の点数はRoundStateの責務ではなく、
`RiichiContribution`を後続のMatch精算が消費する。
"""

from dataclasses import dataclass
from enum import Enum

from lisjong_engine.discard import Discard
from lisjong_engine.reaction import ReactionType
from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile
from lisjong_engine.win_context import RiichiStatus

# 宣言牌がこれらの反応で解決した場合、立直は成立するが一発は付かない。
_CALL_REACTION_TYPES = (
    ReactionType.PON,
    ReactionType.CHI,
    ReactionType.DAIMINKAN,
)


class RiichiDeclarationOutcome(Enum):
    ESTABLISHED = "established"
    FAILED_BY_RON = "failed_by_ron"


@dataclass(frozen=True)
class RiichiDeclaration:
    """宣言牌を打った時点で確定している、立直宣言の事実。"""

    seat: Seat
    discard: Discard
    discard_count: int
    remaining_live_tiles: int
    was_first_discard: bool
    had_prior_call: bool

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.discard, Discard):
            raise TypeError("discard must be a Discard")
        for name in ("discard_count", "remaining_live_tiles"):
            value = getattr(self, name)
            if type(value) is not int:
                raise TypeError(f"{name} must be an int")
            if value < 1:
                raise ValueError(f"{name} must be positive")
        for name in ("was_first_discard", "had_prior_call"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a bool")

    @property
    def tile(self) -> Tile:
        return self.discard.tile

    @property
    def riichi_status(self) -> RiichiStatus:
        """成立した場合に付く立直の種別。

        鳴きが一度も入っていない第一打での宣言だけがダブル立直になる。
        """
        if self.was_first_discard and not self.had_prior_call:
            return RiichiStatus.DOUBLE_RIICHI
        return RiichiStatus.RIICHI


@dataclass(frozen=True)
class RiichiContribution:
    """立直成立により供託が必要になったという、局内の事実。

    ここでの`points`は`RuleSet.riichi_stick_points`であり、立直可能条件で
    ある`riichi_minimum_points`とは別の設定値である。両方が既定で1,000点
    であることに依存しない。
    """

    seat: Seat
    points: int

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if type(self.points) is not int:
            raise TypeError("points must be an int")
        if self.points <= 0:
            raise ValueError("points must be positive")


@dataclass(frozen=True)
class RiichiDeclarationFinalization:
    """宣言牌への反応が解決した時点で確定する、立直成立の可否。"""

    declaration: RiichiDeclaration
    reaction_type: ReactionType
    outcome: RiichiDeclarationOutcome
    contribution: RiichiContribution | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.declaration, RiichiDeclaration):
            raise TypeError("declaration must be a RiichiDeclaration")
        if not isinstance(self.reaction_type, ReactionType):
            raise TypeError("reaction_type must be a ReactionType")
        if not isinstance(self.outcome, RiichiDeclarationOutcome):
            raise TypeError("outcome must be a RiichiDeclarationOutcome")

        expected_outcome = (
            RiichiDeclarationOutcome.FAILED_BY_RON
            if self.reaction_type is ReactionType.RON
            else RiichiDeclarationOutcome.ESTABLISHED
        )
        if self.outcome is not expected_outcome:
            raise ValueError("outcome must match the resolved reaction")

        if self.contribution is None:
            if self.is_established:
                raise ValueError("an established riichi requires a contribution")
            return
        if not isinstance(self.contribution, RiichiContribution):
            raise TypeError("contribution must be a RiichiContribution or None")
        if not self.is_established:
            raise ValueError("a failed riichi must not require a contribution")
        if self.contribution.seat is not self.declaration.seat:
            raise ValueError("contribution must be owed by the declaring seat")

    @property
    def seat(self) -> Seat:
        return self.declaration.seat

    @property
    def is_established(self) -> bool:
        return self.outcome is RiichiDeclarationOutcome.ESTABLISHED

    @property
    def established_after_call(self) -> bool:
        return self.is_established and self.reaction_type in _CALL_REACTION_TYPES

    @property
    def grants_ippatsu(self) -> bool:
        """一発windowが開くかどうか。鳴きが入った場合は開かない。"""
        return self.is_established and not self.established_after_call

    @property
    def riichi_status(self) -> RiichiStatus:
        if not self.is_established:
            return RiichiStatus.NONE
        return self.declaration.riichi_status


def finalize_riichi_declaration(
    declaration: RiichiDeclaration,
    *,
    reaction_type: ReactionType,
    riichi_stick_points: int,
) -> RiichiDeclarationFinalization:
    """宣言と反応の解決結果から、立直成立の可否をpureに決める。"""
    if not isinstance(declaration, RiichiDeclaration):
        raise TypeError("declaration must be a RiichiDeclaration")
    if not isinstance(reaction_type, ReactionType):
        raise TypeError("reaction_type must be a ReactionType")
    if type(riichi_stick_points) is not int:
        raise TypeError("riichi_stick_points must be an int")

    if reaction_type is ReactionType.RON:
        return RiichiDeclarationFinalization(
            declaration,
            reaction_type,
            RiichiDeclarationOutcome.FAILED_BY_RON,
        )
    return RiichiDeclarationFinalization(
        declaration,
        reaction_type,
        RiichiDeclarationOutcome.ESTABLISHED,
        RiichiContribution(declaration.seat, riichi_stick_points),
    )
