"""局の進行をengine内部で記録するdomain eventを定義するmodule。

eventはengine内部のaudit、test、後続の`RoundResult`構築のためだけに
使う。mjai等の外部牌譜形式、Player配送用の差分event、席別の可視情報
射影はengineの本moduleの責務としない。

E1では実装済み遷移（局開始・配牌・ツモ・打牌）に対応するeventだけを
定義する。反応解決・和了・流局のeventはE2/E3で追加する。
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile
from lisjong_engine.wind import Wind


class DrawSource(Enum):
    """ツモ牌の取得元。嶺上牌はE2の槓と合わせて追加する。"""

    LIVE_WALL = "live_wall"


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
