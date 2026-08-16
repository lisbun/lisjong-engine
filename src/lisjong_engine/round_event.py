"""局の進行をengine内部で記録するdomain eventを定義するmodule。

eventはengine内部のaudit、test、後続の`RoundResult`構築のためだけに
使う。mjai等の外部牌譜形式、Player配送用の差分event、席別の可視情報
射影はengineの本moduleの責務としない。

E2では反応解決・鳴き・立直・槓・フリテン遷移のeventを追加する。和了確定・
流局・局終了のeventはE3で追加する。
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from lisjong_engine.furiten import FuritenReason, validate_missed_ron_reason
from lisjong_engine.meld import Kan, Meld
from lisjong_engine.reaction import ReactionResolution
from lisjong_engine.riichi_event import (
    RiichiDeclaration,
    RiichiDeclarationFinalization,
)
from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile
from lisjong_engine.wind import Wind


class DrawSource(Enum):
    """ツモ牌の取得元。嶺上牌は通常の山からのツモと区別する。"""

    LIVE_WALL = "live_wall"
    RINSHAN = "rinshan"


@dataclass(frozen=True)
class RoundEvent:
    """外部形式に依存しない局eventの基底型。"""


@dataclass(frozen=True)
class RoundStartedEvent(RoundEvent):
    dealer_seat: Seat
    prevailing_wind: Wind

    def __post_init__(self) -> None:
        if not isinstance(self.dealer_seat, Seat):
            raise TypeError("dealer_seat must be a Seat")
        if not isinstance(self.prevailing_wind, Wind):
            raise TypeError("prevailing_wind must be a Wind")


@dataclass(frozen=True)
class TilesDealtEvent(RoundEvent):
    seat: Seat
    tiles: tuple[Tile, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")

        try:
            tiles = tuple(self.tiles)
        except TypeError:
            raise TypeError("tiles must be an iterable of Tile instances") from None
        if any(not isinstance(tile, Tile) for tile in tiles):
            raise TypeError("tiles must contain only Tile instances")

        object.__setattr__(self, "tiles", tiles)


@dataclass(frozen=True)
class TileDrawnEvent(RoundEvent):
    seat: Seat
    tile: Tile
    source: DrawSource

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.tile, Tile):
            raise TypeError("tile must be a Tile")
        if not isinstance(self.source, DrawSource):
            raise TypeError("source must be a DrawSource")


@dataclass(frozen=True)
class TileDiscardedEvent(RoundEvent):
    seat: Seat
    tile: Tile
    is_tsumogiri: bool

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.tile, Tile):
            raise TypeError("tile must be a Tile")
        if type(self.is_tsumogiri) is not bool:
            raise TypeError("is_tsumogiri must be a bool")


@dataclass(frozen=True)
class ReactionsResolvedEvent(RoundEvent):
    """1つの反応windowが、engine側の優先順位解決で確定したことを表す。

    ロン可能・ロン選択・ロン成立・ロン見逃しの区別は`resolution`が保持
    する。頭ハネで成立しなかったロン選択者を見逃しとして扱わないため、
    eventでもこの区別を潰さない。
    """

    resolution: ReactionResolution

    def __post_init__(self) -> None:
        if not isinstance(self.resolution, ReactionResolution):
            raise TypeError("resolution must be a ReactionResolution")


@dataclass(frozen=True)
class MeldCalledEvent(RoundEvent):
    """打牌に対するチー・ポン・大明槓が成立したことを表す。"""

    seat: Seat
    meld: Meld

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.meld, Meld):
            raise TypeError("meld must be a meld instance")


@dataclass(frozen=True)
class KanDeclaredEvent(RoundEvent):
    """加槓・暗槓が宣言され、槍槓の反応待ちに入ったことを表す。

    この時点では副露へ確定していない。成立は`KanConfirmedEvent`が表す。
    """

    seat: Seat
    kan: Kan

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.kan, Kan):
            raise TypeError("kan must be an Ankan, Kakan, or Daiminkan")


@dataclass(frozen=True)
class KanConfirmedEvent(RoundEvent):
    """槓が副露として確定し、嶺上ツモへ進めるようになったことを表す。"""

    seat: Seat
    kan: Kan

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.kan, Kan):
            raise TypeError("kan must be an Ankan, Kakan, or Daiminkan")


@dataclass(frozen=True)
class DoraIndicatorRevealedEvent(RoundEvent):
    """槓ドラ表示牌を公開したことを表す。

    `seat`は公開の原因となった槓の宣言者である。公開タイミングは
    `RuleSet.kan_dora_reveal_policy`が決めるため、槓の成立と同じevent
    位置になるとは限らない。
    """

    seat: Seat
    indicator: Tile

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.indicator, Tile):
            raise TypeError("indicator must be a Tile")


@dataclass(frozen=True)
class RiichiDeclaredEvent(RoundEvent):
    declaration: RiichiDeclaration

    def __post_init__(self) -> None:
        if not isinstance(self.declaration, RiichiDeclaration):
            raise TypeError("declaration must be a RiichiDeclaration")


@dataclass(frozen=True)
class RiichiFinalizedEvent(RoundEvent):
    """宣言牌への反応が解決し、立直の成立可否が確定したことを表す。"""

    finalization: RiichiDeclarationFinalization

    def __post_init__(self) -> None:
        if not isinstance(self.finalization, RiichiDeclarationFinalization):
            raise TypeError("finalization must be a RiichiDeclarationFinalization")


@dataclass(frozen=True)
class MissedRonRecordedEvent(RoundEvent):
    """ロンできた牌を見逃した席のフリテン遷移を表す。"""

    seat: Seat
    reason: FuritenReason

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.reason, FuritenReason):
            raise TypeError("reason must be a FuritenReason")
        validate_missed_ron_reason(self.reason)


@dataclass(frozen=True)
class RoundEventSnapshot:
    """局eventの、副作用のないimmutableな読み出し用view。"""

    events: tuple[RoundEvent, ...] = ()

    def __post_init__(self) -> None:
        try:
            events = tuple(self.events)
        except TypeError:
            raise TypeError(
                "events must be an iterable of RoundEvent instances"
            ) from None
        if any(not isinstance(event, RoundEvent) for event in events):
            raise TypeError("events must contain only RoundEvent instances")

        object.__setattr__(self, "events", events)

    def __iter__(self):
        return iter(self.events)

    def __len__(self) -> int:
        return len(self.events)

    def __getitem__(self, index: int) -> RoundEvent:
        return self.events[index]

    def appended(self, events: Iterable[RoundEvent]) -> "RoundEventSnapshot":
        """既存eventを保ったまま、新しいeventを足したsnapshotを返す。"""
        try:
            values = tuple(events)
        except TypeError:
            raise TypeError(
                "events must be an iterable of RoundEvent instances"
            ) from None
        return RoundEventSnapshot((*self.events, *values))
