from collections.abc import Iterable

from lisjong_engine.random_source import RandomSource
from lisjong_engine.tile import STANDARD_TILES, Tile

DEAD_WALL_SIZE = 14
RINSHAN_TILE_COUNT = 4
MAX_DORA_INDICATOR_COUNT = 5
_DORA_INDICATOR_INDICES = tuple(
    RINSHAN_TILE_COUNT + offset * 2 for offset in range(MAX_DORA_INDICATOR_COUNT)
)
_URA_DORA_INDICATOR_INDICES = tuple(index + 1 for index in _DORA_INDICATOR_INDICES)


class Wall:
    """通常の山と、任意の14枚の王牌を保持する。

    王牌を指定する場合、先頭4枚を嶺上牌の取得順として扱い、
    残り10枚は、表表示牌・対応する裏表示牌の順で5組保持する。
    """

    def __init__(
        self,
        tiles: Iterable[Tile],
        dead_wall_tiles: Iterable[Tile] = (),
    ) -> None:
        tile_sequence = tuple(tiles)
        dead_wall_sequence = tuple(dead_wall_tiles)
        all_tiles = (*tile_sequence, *dead_wall_sequence)
        if any(not isinstance(tile, Tile) for tile in all_tiles):
            raise TypeError("tiles must contain only Tile instances")
        if len(dead_wall_sequence) not in (0, DEAD_WALL_SIZE):
            raise ValueError(f"dead wall must contain exactly {DEAD_WALL_SIZE} tiles")

        tile_ids = tuple(tile.id for tile in all_tiles)
        if len(set(tile_ids)) != len(tile_ids):
            raise ValueError("tiles must not contain duplicate physical tile IDs")

        self._tiles = tile_sequence
        self._draw_index = 0
        self._draw_end_index = len(tile_sequence)
        self._dead_wall_tiles = dead_wall_sequence
        self._rinshan_draw_index = 0
        self._revealed_dora_indicator_count = 1 if dead_wall_sequence else 0

    @property
    def remaining_count(self) -> int:
        return self._draw_end_index - self._draw_index

    @property
    def remaining_tiles(self) -> tuple[Tile, ...]:
        return self._tiles[self._draw_index : self._draw_end_index]

    @property
    def dead_wall_tiles(self) -> tuple[Tile, ...]:
        return self._dead_wall_tiles

    @property
    def dora_indicator_tiles(self) -> tuple[Tile, ...]:
        if not self._dead_wall_tiles:
            return ()
        return tuple(self._dead_wall_tiles[index] for index in _DORA_INDICATOR_INDICES)

    @property
    def ura_dora_indicator_tiles(self) -> tuple[Tile, ...]:
        if not self._dead_wall_tiles:
            return ()
        return tuple(
            self._dead_wall_tiles[index] for index in _URA_DORA_INDICATOR_INDICES
        )

    @property
    def revealed_dora_indicator_count(self) -> int:
        return self._revealed_dora_indicator_count

    @property
    def revealed_dora_indicators(self) -> tuple[Tile, ...]:
        return self.dora_indicator_tiles[: self._revealed_dora_indicator_count]

    @property
    def corresponding_ura_dora_indicators(self) -> tuple[Tile, ...]:
        return self.ura_dora_indicator_tiles[: self._revealed_dora_indicator_count]

    @property
    def remaining_rinshan_count(self) -> int:
        if not self._dead_wall_tiles:
            return 0
        return RINSHAN_TILE_COUNT - self._rinshan_draw_index

    @property
    def remaining_rinshan_tiles(self) -> tuple[Tile, ...]:
        if not self._dead_wall_tiles:
            return ()
        return self._dead_wall_tiles[self._rinshan_draw_index : RINSHAN_TILE_COUNT]

    @property
    def can_draw_rinshan(self) -> bool:
        return self.remaining_rinshan_count > 0 and self.remaining_count > 0

    def draw(self) -> Tile:
        if self._draw_index >= self._draw_end_index:
            raise IndexError("cannot draw from an empty wall")

        tile = self._tiles[self._draw_index]
        self._draw_index += 1
        return tile

    def draw_rinshan(self) -> Tile:
        """嶺上牌を取り、通常の山末尾から王牌を補充する。"""
        if self.remaining_rinshan_count == 0:
            raise IndexError("cannot draw another rinshan tile")
        if self.remaining_count == 0:
            raise IndexError("cannot replenish dead wall from an empty live wall")

        tile = self._dead_wall_tiles[self._rinshan_draw_index]
        replacement_tile = self._tiles[self._draw_end_index - 1]
        updated_dead_wall = list(self._dead_wall_tiles)
        updated_dead_wall[self._rinshan_draw_index] = replacement_tile

        self._dead_wall_tiles = tuple(updated_dead_wall)
        self._draw_end_index -= 1
        self._rinshan_draw_index += 1
        return tile

    def reveal_kan_dora(self) -> Tile:
        if not self._dead_wall_tiles:
            raise RuntimeError("kan dora requires a dead wall")
        if self._revealed_dora_indicator_count >= MAX_DORA_INDICATOR_COUNT:
            raise RuntimeError("all dora indicators are already revealed")
        self._revealed_dora_indicator_count += 1
        return self.revealed_dora_indicators[-1]

    def copy(self) -> "Wall":
        wall = Wall(self.remaining_tiles, self._dead_wall_tiles)
        wall._rinshan_draw_index = self._rinshan_draw_index
        wall._revealed_dora_indicator_count = self._revealed_dora_indicator_count
        return wall


def create_shuffled_wall(random_source: RandomSource) -> Wall:
    """注入された乱数sourceだけを使い、標準136枚から決定的に山を生成する。"""
    if not isinstance(random_source, RandomSource):
        raise TypeError("random_source must be a RandomSource")

    tiles = list(STANDARD_TILES)
    random_source.shuffle(tiles)
    return Wall(
        tiles[:-DEAD_WALL_SIZE],
        tiles[-DEAD_WALL_SIZE:],
    )
