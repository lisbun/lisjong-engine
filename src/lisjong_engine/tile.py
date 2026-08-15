from dataclasses import dataclass
from enum import Enum


class TileCategory(Enum):
    MANZU = "manzu"
    PINZU = "pinzu"
    SOUZU = "souzu"
    HONOR = "honor"


_CATEGORY_OFFSETS = {
    TileCategory.MANZU: 0,
    TileCategory.PINZU: 9,
    TileCategory.SOUZU: 18,
    TileCategory.HONOR: 27,
}


@dataclass(frozen=True)
class TileType:
    category: TileCategory
    rank: int

    def __post_init__(self) -> None:
        if not isinstance(self.category, TileCategory):
            raise TypeError("category must be a TileCategory")
        if type(self.rank) is not int:
            raise TypeError("rank must be an int")

        maximum_rank = 7 if self.category is TileCategory.HONOR else 9
        if not 1 <= self.rank <= maximum_rank:
            raise ValueError(f"rank must be between 1 and {maximum_rank}")

    @property
    def id(self) -> int:
        """広く使われる34種ID（0～33）を返す。"""
        return _CATEGORY_OFFSETS[self.category] + self.rank - 1


@dataclass(frozen=True)
class Tile:
    tile_type: TileType
    copy_index: int
    is_red: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.tile_type, TileType):
            raise TypeError("tile_type must be a TileType")
        if type(self.copy_index) is not int:
            raise TypeError("copy_index must be an int")
        if not 0 <= self.copy_index <= 3:
            raise ValueError("copy_index must be between 0 and 3")
        if type(self.is_red) is not bool:
            raise TypeError("is_red must be a bool")
        if self.is_red and (
            self.tile_type.category is TileCategory.HONOR or self.tile_type.rank != 5
        ):
            raise ValueError("only suited fives can be red")

    @property
    def id(self) -> int:
        """広く使われる136枚ID（0～135）を返す。"""
        return self.tile_type.id * 4 + self.copy_index


STANDARD_TILE_TYPES = tuple(
    TileType(category, rank)
    for category in TileCategory
    for rank in range(1, 8 if category is TileCategory.HONOR else 10)
)


def create_standard_tiles() -> tuple[Tile, ...]:
    """赤五を各色1枚含む、4人打ち用の標準136枚を生成する。"""
    return tuple(
        Tile(
            tile_type,
            copy_index,
            is_red=(
                tile_type.category is not TileCategory.HONOR
                and tile_type.rank == 5
                and copy_index == 0
            ),
        )
        for tile_type in STANDARD_TILE_TYPES
        for copy_index in range(4)
    )


STANDARD_TILES = create_standard_tiles()
