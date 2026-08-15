from collections.abc import Iterable

from lisjong_engine.tile import Tile

_MAX_TILE_COUNT = 14


class Hand:
    def __init__(self, tiles: Iterable[Tile] = ()) -> None:
        tile_sequence = tuple(tiles)
        if any(not isinstance(tile, Tile) for tile in tile_sequence):
            raise TypeError("tiles must contain only Tile instances")
        if len(tile_sequence) > _MAX_TILE_COUNT:
            raise ValueError("hand cannot contain more than 14 tiles")

        tile_ids = tuple(tile.id for tile in tile_sequence)
        if len(set(tile_ids)) != len(tile_ids):
            raise ValueError("tiles must not contain duplicate physical tile IDs")

        self._tiles = tile_sequence

    @property
    def count(self) -> int:
        return len(self._tiles)

    @property
    def tiles(self) -> tuple[Tile, ...]:
        return self._tiles

    def add(self, tile: Tile) -> None:
        if not isinstance(tile, Tile):
            raise TypeError("tile must be a Tile")
        if self.count >= _MAX_TILE_COUNT:
            raise ValueError("hand cannot contain more than 14 tiles")
        if any(existing_tile.id == tile.id for existing_tile in self._tiles):
            raise ValueError("hand must not contain duplicate physical tile IDs")

        self._tiles = (*self._tiles, tile)

    def remove(self, tile_id: int) -> Tile:
        if type(tile_id) is not int:
            raise TypeError("tile_id must be an int")

        for index, tile in enumerate(self._tiles):
            if tile.id == tile_id:
                self._tiles = self._tiles[:index] + self._tiles[index + 1 :]
                return tile

        raise ValueError("tile_id is not in hand")
