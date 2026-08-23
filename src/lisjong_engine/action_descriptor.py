"""Selectorへ公開する、物理牌identityを持たないaction descriptor。

立直は`RiichiActionDescriptor`という宣言牌を持たないchoiceであり、
宣言牌はそれが選択された後のfollow-up decisionで、通常の
`DiscardActionDescriptor`として選ぶ。engineがselectorの代わりに
宣言牌を選ぶことはない。
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TypeAlias

from lisjong_engine.public_state import PublicTile
from lisjong_engine.seat import Seat


def _public_tile_sort_key(tile: PublicTile) -> tuple[int, bool]:
    return (tile.tile_type.id, tile.is_red)


def _normalize_public_tiles(
    tiles: Iterable[PublicTile],
    expected_count: int,
    field_name: str,
) -> tuple[PublicTile, ...]:
    try:
        values = tuple(tiles)
    except TypeError:
        raise TypeError(
            f"{field_name} must be an iterable of PublicTile values"
        ) from None
    if any(not isinstance(tile, PublicTile) for tile in values):
        raise TypeError(f"{field_name} must contain only PublicTile values")
    if len(values) != expected_count:
        raise ValueError(f"{field_name} must contain exactly {expected_count} tiles")
    return tuple(sorted(values, key=_public_tile_sort_key))


@dataclass(frozen=True)
class DiscardActionDescriptor:
    tile: PublicTile
    is_tsumogiri: bool

    def __post_init__(self) -> None:
        _validate_tile_and_tsumogiri(self.tile, self.is_tsumogiri)


@dataclass(frozen=True)
class RiichiActionDescriptor:
    """立直を選択するというsemantic choiceだけを表すdescriptor。

    宣言牌は持たない。宣言牌は、これが選択された後のfollow-up decision
    で通常の`DiscardActionDescriptor`として選ぶ。
    """


@dataclass(frozen=True)
class AnkanActionDescriptor:
    tiles: tuple[PublicTile, PublicTile, PublicTile, PublicTile]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tiles",
            _normalize_public_tiles(self.tiles, 4, "tiles"),
        )


@dataclass(frozen=True)
class KakanActionDescriptor:
    tile: PublicTile

    def __post_init__(self) -> None:
        _validate_public_tile(self.tile, "tile")


@dataclass(frozen=True)
class TsumoActionDescriptor:
    tile: PublicTile

    def __post_init__(self) -> None:
        _validate_public_tile(self.tile, "tile")


@dataclass(frozen=True)
class NineTerminalsActionDescriptor:
    pass


@dataclass(frozen=True)
class PassActionDescriptor:
    tile: PublicTile
    from_seat: Seat

    def __post_init__(self) -> None:
        _validate_reaction_target(self.tile, self.from_seat)


@dataclass(frozen=True)
class RonActionDescriptor:
    tile: PublicTile
    from_seat: Seat

    def __post_init__(self) -> None:
        _validate_reaction_target(self.tile, self.from_seat)


@dataclass(frozen=True)
class ChiActionDescriptor:
    tile: PublicTile
    consumed_tiles: tuple[PublicTile, PublicTile]
    from_seat: Seat

    def __post_init__(self) -> None:
        _validate_public_tile(self.tile, "tile")
        object.__setattr__(
            self,
            "consumed_tiles",
            _normalize_public_tiles(self.consumed_tiles, 2, "consumed_tiles"),
        )
        _validate_seat(self.from_seat, "from_seat")


@dataclass(frozen=True)
class PonActionDescriptor:
    tile: PublicTile
    consumed_tiles: tuple[PublicTile, PublicTile]
    from_seat: Seat

    def __post_init__(self) -> None:
        _validate_public_tile(self.tile, "tile")
        object.__setattr__(
            self,
            "consumed_tiles",
            _normalize_public_tiles(self.consumed_tiles, 2, "consumed_tiles"),
        )
        _validate_seat(self.from_seat, "from_seat")


@dataclass(frozen=True)
class DaiminkanActionDescriptor:
    tile: PublicTile
    consumed_tiles: tuple[PublicTile, PublicTile, PublicTile]
    from_seat: Seat

    def __post_init__(self) -> None:
        _validate_public_tile(self.tile, "tile")
        object.__setattr__(
            self,
            "consumed_tiles",
            _normalize_public_tiles(self.consumed_tiles, 3, "consumed_tiles"),
        )
        _validate_seat(self.from_seat, "from_seat")


ActionDescriptor: TypeAlias = (
    DiscardActionDescriptor
    | RiichiActionDescriptor
    | AnkanActionDescriptor
    | KakanActionDescriptor
    | TsumoActionDescriptor
    | NineTerminalsActionDescriptor
    | PassActionDescriptor
    | RonActionDescriptor
    | ChiActionDescriptor
    | PonActionDescriptor
    | DaiminkanActionDescriptor
)

ACTION_DESCRIPTOR_TYPES = (
    DiscardActionDescriptor,
    RiichiActionDescriptor,
    AnkanActionDescriptor,
    KakanActionDescriptor,
    TsumoActionDescriptor,
    NineTerminalsActionDescriptor,
    PassActionDescriptor,
    RonActionDescriptor,
    ChiActionDescriptor,
    PonActionDescriptor,
    DaiminkanActionDescriptor,
)


def is_action_descriptor(value: object) -> bool:
    return isinstance(value, ACTION_DESCRIPTOR_TYPES)


def _validate_public_tile(tile: PublicTile, field_name: str) -> None:
    if not isinstance(tile, PublicTile):
        raise TypeError(f"{field_name} must be a PublicTile")


def _validate_seat(seat: Seat, field_name: str) -> None:
    if not isinstance(seat, Seat):
        raise TypeError(f"{field_name} must be a Seat")


def _validate_tile_and_tsumogiri(tile: PublicTile, is_tsumogiri: bool) -> None:
    _validate_public_tile(tile, "tile")
    if type(is_tsumogiri) is not bool:
        raise TypeError("is_tsumogiri must be a bool")


def _validate_reaction_target(tile: PublicTile, from_seat: Seat) -> None:
    _validate_public_tile(tile, "tile")
    _validate_seat(from_seat, "from_seat")
