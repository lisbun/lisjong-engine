"""席別Observationへ公開できる麻雀盤面のimmutableな値型。"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from lisjong_engine.seat import Seat
from lisjong_engine.tile import TileCategory, TileType


@dataclass(frozen=True)
class PublicTile:
    """物理copyを識別しない、牌種と赤情報だけの公開牌。"""

    tile_type: TileType
    is_red: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.tile_type, TileType):
            raise TypeError("tile_type must be a TileType")
        if type(self.is_red) is not bool:
            raise TypeError("is_red must be a bool")
        if self.is_red and (
            self.tile_type.category is TileCategory.HONOR or self.tile_type.rank != 5
        ):
            raise ValueError("only suited fives can be red")


class PublicMeldType(Enum):
    CHI = "chi"
    PON = "pon"
    DAIMINKAN = "daiminkan"
    ANKAN = "ankan"
    KAKAN = "kakan"


@dataclass(frozen=True)
class PublicDiscard:
    tile: PublicTile
    is_tsumogiri: bool
    is_riichi_declaration: bool
    called_by: Seat | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.tile, PublicTile):
            raise TypeError("tile must be a PublicTile")
        if type(self.is_tsumogiri) is not bool:
            raise TypeError("is_tsumogiri must be a bool")
        if type(self.is_riichi_declaration) is not bool:
            raise TypeError("is_riichi_declaration must be a bool")
        if self.called_by is not None and not isinstance(self.called_by, Seat):
            raise TypeError("called_by must be a Seat or None")


@dataclass(frozen=True)
class PublicMeld:
    meld_type: PublicMeldType
    tiles: tuple[PublicTile, ...]
    from_seat: Seat | None

    def __post_init__(self) -> None:
        if not isinstance(self.meld_type, PublicMeldType):
            raise TypeError("meld_type must be a PublicMeldType")
        tiles = tuple(
            sorted(
                _public_tile_tuple(self.tiles, field_name="tiles"),
                key=lambda tile: (tile.tile_type.id, tile.is_red),
            )
        )
        expected_count = (
            3 if self.meld_type in (PublicMeldType.CHI, PublicMeldType.PON) else 4
        )
        if len(tiles) != expected_count:
            raise ValueError(
                f"{self.meld_type.value} must contain exactly {expected_count} tiles"
            )
        if self.meld_type is PublicMeldType.ANKAN:
            if self.from_seat is not None:
                raise ValueError("ankan must not have a source seat")
        elif not isinstance(self.from_seat, Seat):
            raise TypeError("open meld source must be a Seat")
        object.__setattr__(self, "tiles", tiles)


@dataclass(frozen=True)
class SeatDiscards:
    seat: Seat
    discards: tuple[PublicDiscard, ...]

    def __post_init__(self) -> None:
        _validate_seat(self.seat)
        discards = _typed_tuple(
            self.discards,
            PublicDiscard,
            field_name="discards",
        )
        object.__setattr__(self, "discards", discards)


@dataclass(frozen=True)
class SeatMelds:
    seat: Seat
    melds: tuple[PublicMeld, ...]

    def __post_init__(self) -> None:
        _validate_seat(self.seat)
        melds = _typed_tuple(self.melds, PublicMeld, field_name="melds")
        object.__setattr__(self, "melds", melds)


@dataclass(frozen=True)
class SeatScore:
    seat: Seat
    points: int

    def __post_init__(self) -> None:
        _validate_seat(self.seat)
        if type(self.points) is not int:
            raise TypeError("points must be an int")


@dataclass(frozen=True)
class SeatRiichiState:
    seat: Seat
    is_established: bool

    def __post_init__(self) -> None:
        _validate_seat(self.seat)
        if type(self.is_established) is not bool:
            raise TypeError("is_established must be a bool")


def _validate_seat(seat: Seat) -> None:
    if not isinstance(seat, Seat):
        raise TypeError("seat must be a Seat")


def _typed_tuple(values: Iterable, expected_type: type, *, field_name: str) -> tuple:
    try:
        normalized = tuple(values)
    except TypeError:
        raise TypeError(f"{field_name} must be an iterable") from None
    if any(not isinstance(value, expected_type) for value in normalized):
        raise TypeError(
            f"{field_name} must contain only {expected_type.__name__} values"
        )
    return normalized


def _public_tile_tuple(
    values: Iterable[PublicTile],
    *,
    field_name: str,
) -> tuple[PublicTile, ...]:
    return _typed_tuple(values, PublicTile, field_name=field_name)
