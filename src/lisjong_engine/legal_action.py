"""合法手を表す判別可能unionと、席別の合法手snapshotを定義するmodule。

`LegalAction`はengine内部のdomain値であり、外部protocolのaction idや
adapter都合の整数handleへは変換しない。actionの同一性はdomain data
（物理牌IDとaction種別）だけで判別できる。

立直は`RiichiLegalAction`という宣言牌を持たない独立actionであり、
宣言牌の選択は`AWAITING_RIICHI_DISCARD`での`DiscardLegalAction`という
別decisionで行う。したがって`DiscardLegalAction`は打牌そのものだけを
表し、立直宣言と結合しない。

古いsnapshotから取り出したactionが偶然現在も合法な場合を区別するため、
staleness判定は`LegalAction`自身ではなく`LegalActionSnapshot.revision`
（局内のstate revision）で行う。
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.seat import Seat


class ReactionOrigin(Enum):
    """反応の起点。どの宣言に対する反応かを区別する。"""

    DISCARD = "discard"
    KAKAN = "kakan"
    ANKAN = "ankan"


def _validate_tile_id(tile_id: int, name: str) -> None:
    if type(tile_id) is not int:
        raise TypeError(f"{name} must be an int")
    if tile_id < 0:
        raise ValueError(f"{name} must not be negative")


def _normalize_tile_ids(
    tile_ids: Iterable[int], expected_count: int, name: str
) -> tuple[int, ...]:
    try:
        values = tuple(tile_ids)
    except TypeError:
        raise TypeError(f"{name} must be an iterable of ints") from None
    if any(type(value) is not int for value in values):
        raise TypeError(f"{name} must contain only ints")
    if len(values) != expected_count:
        raise ValueError(f"{name} must contain exactly {expected_count} tile IDs")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must contain distinct tile IDs")
    if any(value < 0 for value in values):
        raise ValueError(f"{name} must not contain negative tile IDs")
    return tuple(sorted(values))


@dataclass(frozen=True)
class DiscardLegalAction:
    tile_id: int

    def __post_init__(self) -> None:
        _validate_tile_id(self.tile_id, "tile_id")


@dataclass(frozen=True)
class RiichiLegalAction:
    """current seatが立直を選択することだけを表すaction。

    宣言牌は持たない。適用後の`AWAITING_RIICHI_DISCARD`で、宣言牌を
    選ぶ独立したdecisionを行う。
    """


@dataclass(frozen=True)
class AnkanLegalAction:
    tile_ids: tuple[int, int, int, int]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tile_ids",
            _normalize_tile_ids(self.tile_ids, 4, "tile_ids"),
        )


@dataclass(frozen=True)
class KakanLegalAction:
    added_tile_id: int

    def __post_init__(self) -> None:
        _validate_tile_id(self.added_tile_id, "added_tile_id")


@dataclass(frozen=True)
class TsumoLegalAction:
    pass


@dataclass(frozen=True)
class NineTerminalsLegalAction:
    pass


@dataclass(frozen=True)
class PassLegalAction:
    origin: ReactionOrigin
    target_tile_id: int

    def __post_init__(self) -> None:
        if not isinstance(self.origin, ReactionOrigin):
            raise TypeError("origin must be a ReactionOrigin")
        _validate_tile_id(self.target_tile_id, "target_tile_id")


@dataclass(frozen=True)
class RonLegalAction:
    origin: ReactionOrigin
    target_tile_id: int

    def __post_init__(self) -> None:
        if not isinstance(self.origin, ReactionOrigin):
            raise TypeError("origin must be a ReactionOrigin")
        _validate_tile_id(self.target_tile_id, "target_tile_id")


@dataclass(frozen=True)
class ChiLegalAction:
    target_tile_id: int
    consumed_tile_ids: tuple[int, int]

    def __post_init__(self) -> None:
        _validate_tile_id(self.target_tile_id, "target_tile_id")
        object.__setattr__(
            self,
            "consumed_tile_ids",
            _normalize_tile_ids(self.consumed_tile_ids, 2, "consumed_tile_ids"),
        )


@dataclass(frozen=True)
class PonLegalAction:
    target_tile_id: int
    consumed_tile_ids: tuple[int, int]

    def __post_init__(self) -> None:
        _validate_tile_id(self.target_tile_id, "target_tile_id")
        object.__setattr__(
            self,
            "consumed_tile_ids",
            _normalize_tile_ids(self.consumed_tile_ids, 2, "consumed_tile_ids"),
        )


@dataclass(frozen=True)
class DaiminkanLegalAction:
    target_tile_id: int
    consumed_tile_ids: tuple[int, int, int]

    def __post_init__(self) -> None:
        _validate_tile_id(self.target_tile_id, "target_tile_id")
        object.__setattr__(
            self,
            "consumed_tile_ids",
            _normalize_tile_ids(self.consumed_tile_ids, 3, "consumed_tile_ids"),
        )


# 値型はE2/E3でpublic契約を作り直さずに済むよう先行して定義する。
# 実際に生成・適用できるbehaviorはE1 scope（通常turnの打牌）に限定し、
# 未実装actionを渡された場合はfallbackせずillegalとして拒否する。
LegalAction: TypeAlias = (
    DiscardLegalAction
    | RiichiLegalAction
    | AnkanLegalAction
    | KakanLegalAction
    | TsumoLegalAction
    | NineTerminalsLegalAction
    | PassLegalAction
    | RonLegalAction
    | ChiLegalAction
    | PonLegalAction
    | DaiminkanLegalAction
)


def is_legal_action(value: object) -> bool:
    """`value`が`LegalAction` unionのいずれかであるかを返す。"""
    return isinstance(value, LegalAction)


@dataclass(frozen=True)
class LegalActionSnapshot:
    """ある時点・ある席の合法手を表すimmutableなsnapshot。

    `revision`はsnapshotを取得した時点の局内state revisionであり、
    `RoundState.apply()`へ`expected_revision`として渡す。局の状態が
    1つでも進むとrevisionが変わるため、古いsnapshotから取り出した
    actionは、現在も同じdomain valueが合法かどうかに関わらずstaleと
    して拒否できる。
    """

    seat: Seat
    phase: RoundPhase
    revision: int
    actions: tuple[LegalAction, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.phase, RoundPhase):
            raise TypeError("phase must be a RoundPhase")
        if type(self.revision) is not int:
            raise TypeError("revision must be an int")
        if self.revision < 0:
            raise ValueError("revision must not be negative")

        try:
            actions = tuple(self.actions)
        except TypeError:
            raise TypeError("actions must be an iterable of legal actions") from None
        if any(not is_legal_action(action) for action in actions):
            raise TypeError("actions must contain only legal actions")
        if len(set(actions)) != len(actions):
            raise ValueError("actions must not contain duplicates")

        object.__setattr__(self, "actions", actions)

    def __contains__(self, action: object) -> bool:
        return action in self.actions

    def __len__(self) -> int:
        return len(self.actions)
