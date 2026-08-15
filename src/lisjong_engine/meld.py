from dataclasses import dataclass

from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile, TileCategory


@dataclass(frozen=True)
class Pon:
    called_tile: Tile
    consumed_tiles: tuple[Tile, Tile]
    source_seat: Seat

    def __post_init__(self) -> None:
        if not isinstance(self.called_tile, Tile):
            raise TypeError("called_tile must be a Tile")

        try:
            consumed_tiles = tuple(self.consumed_tiles)
        except TypeError:
            raise TypeError(
                "consumed_tiles must be an iterable of Tile instances"
            ) from None

        if any(not isinstance(tile, Tile) for tile in consumed_tiles):
            raise TypeError("consumed_tiles must contain only Tile instances")
        if len(consumed_tiles) != 2:
            raise ValueError("pon must consume exactly two tiles")
        if not isinstance(self.source_seat, Seat):
            raise TypeError("source_seat must be a Seat")

        tiles = (self.called_tile, *consumed_tiles)
        if any(tile.tile_type != self.called_tile.tile_type for tile in consumed_tiles):
            raise ValueError("all pon tiles must have the same tile type")

        tile_ids = tuple(tile.id for tile in tiles)
        if len(set(tile_ids)) != len(tile_ids):
            raise ValueError("pon tiles must not contain duplicate physical tile IDs")

        object.__setattr__(self, "consumed_tiles", consumed_tiles)

    @property
    def tiles(self) -> tuple[Tile, Tile, Tile]:
        return (self.called_tile, *self.consumed_tiles)


@dataclass(frozen=True)
class Kakan:
    """元のポンと追加牌の関係を保持する。符計算・槍槓のため平坦化しない。"""

    pon: Pon
    added_tile: Tile

    def __post_init__(self) -> None:
        if not isinstance(self.pon, Pon):
            raise TypeError("pon must be a Pon")
        if not isinstance(self.added_tile, Tile):
            raise TypeError("added_tile must be a Tile")
        if self.added_tile.tile_type != self.pon.called_tile.tile_type:
            raise ValueError("added tile must have the same tile type as the pon")
        if self.added_tile.id in {tile.id for tile in self.pon.tiles}:
            raise ValueError("kakan tiles must not contain duplicate physical tile IDs")

    @property
    def called_tile(self) -> Tile:
        return self.pon.called_tile

    @property
    def consumed_tiles(self) -> tuple[Tile, Tile]:
        return self.pon.consumed_tiles

    @property
    def source_seat(self) -> Seat:
        return self.pon.source_seat

    @property
    def tiles(self) -> tuple[Tile, Tile, Tile, Tile]:
        return (*self.pon.tiles, self.added_tile)


@dataclass(frozen=True)
class Chi:
    called_tile: Tile
    consumed_tiles: tuple[Tile, Tile]
    source_seat: Seat

    def __post_init__(self) -> None:
        if not isinstance(self.called_tile, Tile):
            raise TypeError("called_tile must be a Tile")

        try:
            consumed_tiles = tuple(self.consumed_tiles)
        except TypeError:
            raise TypeError(
                "consumed_tiles must be an iterable of Tile instances"
            ) from None

        if any(not isinstance(tile, Tile) for tile in consumed_tiles):
            raise TypeError("consumed_tiles must contain only Tile instances")
        if len(consumed_tiles) != 2:
            raise ValueError("chi must consume exactly two tiles")
        if not isinstance(self.source_seat, Seat):
            raise TypeError("source_seat must be a Seat")

        tiles = (self.called_tile, *consumed_tiles)
        tile_ids = tuple(tile.id for tile in tiles)
        if len(set(tile_ids)) != len(tile_ids):
            raise ValueError("chi tiles must not contain duplicate physical tile IDs")

        category = self.called_tile.tile_type.category
        if category is TileCategory.HONOR or any(
            tile.tile_type.category is not category for tile in consumed_tiles
        ):
            raise ValueError("chi tiles must be suited tiles in the same category")

        ranks = tuple(sorted(tile.tile_type.rank for tile in tiles))
        if ranks != tuple(range(ranks[0], ranks[0] + 3)):
            raise ValueError("chi tiles must have three consecutive ranks")

        object.__setattr__(self, "consumed_tiles", consumed_tiles)

    @property
    def tiles(self) -> tuple[Tile, Tile, Tile]:
        return (self.called_tile, *self.consumed_tiles)


@dataclass(frozen=True)
class Daiminkan:
    called_tile: Tile
    consumed_tiles: tuple[Tile, Tile, Tile]
    source_seat: Seat

    def __post_init__(self) -> None:
        if not isinstance(self.called_tile, Tile):
            raise TypeError("called_tile must be a Tile")

        try:
            consumed_tiles = tuple(self.consumed_tiles)
        except TypeError:
            raise TypeError(
                "consumed_tiles must be an iterable of Tile instances"
            ) from None

        if any(not isinstance(tile, Tile) for tile in consumed_tiles):
            raise TypeError("consumed_tiles must contain only Tile instances")
        if len(consumed_tiles) != 3:
            raise ValueError("daiminkan must consume exactly three tiles")
        if not isinstance(self.source_seat, Seat):
            raise TypeError("source_seat must be a Seat")

        tiles = (self.called_tile, *consumed_tiles)
        if any(tile.tile_type != self.called_tile.tile_type for tile in consumed_tiles):
            raise ValueError("all daiminkan tiles must have the same tile type")

        tile_ids = tuple(tile.id for tile in tiles)
        if len(set(tile_ids)) != len(tile_ids):
            raise ValueError(
                "daiminkan tiles must not contain duplicate physical tile IDs"
            )

        object.__setattr__(self, "consumed_tiles", consumed_tiles)

    @property
    def tiles(self) -> tuple[Tile, Tile, Tile, Tile]:
        return (self.called_tile, *self.consumed_tiles)


@dataclass(frozen=True)
class Ankan:
    tiles: tuple[Tile, Tile, Tile, Tile]

    def __post_init__(self) -> None:
        try:
            tiles = tuple(self.tiles)
        except TypeError:
            raise TypeError("tiles must be an iterable of Tile instances") from None

        if any(not isinstance(tile, Tile) for tile in tiles):
            raise TypeError("tiles must contain only Tile instances")
        if len(tiles) != 4:
            raise ValueError("ankan must contain exactly four tiles")
        if any(tile.tile_type != tiles[0].tile_type for tile in tiles[1:]):
            raise ValueError("all ankan tiles must have the same tile type")

        tile_ids = tuple(tile.id for tile in tiles)
        if len(set(tile_ids)) != len(tile_ids):
            raise ValueError("ankan tiles must not contain duplicate physical tile IDs")

        object.__setattr__(self, "tiles", tiles)


Meld = Pon | Kakan | Chi | Daiminkan | Ankan
Kan = Ankan | Kakan | Daiminkan
