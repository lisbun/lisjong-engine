import unittest
from collections import Counter
from dataclasses import FrozenInstanceError

from lisjong_engine.tile import (
    STANDARD_TILE_TYPES,
    STANDARD_TILES,
    Tile,
    TileCategory,
    TileType,
    create_standard_tiles,
)


class TileTypeTest(unittest.TestCase):
    def test_categories_have_standard_order(self) -> None:
        self.assertEqual(
            tuple(TileCategory),
            (
                TileCategory.MANZU,
                TileCategory.PINZU,
                TileCategory.SOUZU,
                TileCategory.HONOR,
            ),
        )

    def test_accepts_boundary_ranks(self) -> None:
        cases = (
            (TileCategory.MANZU, 1),
            (TileCategory.MANZU, 9),
            (TileCategory.PINZU, 1),
            (TileCategory.PINZU, 9),
            (TileCategory.SOUZU, 1),
            (TileCategory.SOUZU, 9),
            (TileCategory.HONOR, 1),
            (TileCategory.HONOR, 7),
        )
        for category, rank in cases:
            with self.subTest(category=category, rank=rank):
                self.assertEqual(TileType(category, rank).rank, rank)

    def test_rejects_numbered_tile_rank_out_of_range(self) -> None:
        for rank in (0, 10):
            with self.subTest(rank=rank), self.assertRaises(ValueError):
                TileType(TileCategory.MANZU, rank)

    def test_rejects_honor_rank_out_of_range(self) -> None:
        for rank in (0, 8):
            with self.subTest(rank=rank), self.assertRaises(ValueError):
                TileType(TileCategory.HONOR, rank)

    def test_rejects_non_integer_rank(self) -> None:
        for rank in ("1", 1.0, True):
            with self.subTest(rank=rank), self.assertRaises(TypeError):
                TileType(TileCategory.MANZU, rank)

    def test_rejects_non_category(self) -> None:
        with self.assertRaises(TypeError):
            TileType("manzu", 1)

    def test_is_immutable(self) -> None:
        tile_type = TileType(TileCategory.MANZU, 1)
        with self.assertRaises(FrozenInstanceError):
            tile_type.rank = 2

    def test_has_standard_34_type_id(self) -> None:
        cases = (
            (TileCategory.MANZU, 1, 0),
            (TileCategory.MANZU, 9, 8),
            (TileCategory.PINZU, 1, 9),
            (TileCategory.SOUZU, 1, 18),
            (TileCategory.HONOR, 1, 27),
            (TileCategory.HONOR, 7, 33),
        )
        for category, rank, expected_id in cases:
            with self.subTest(category=category, rank=rank):
                self.assertEqual(TileType(category, rank).id, expected_id)

    def test_equal_values_compare_equal_and_are_hashable(self) -> None:
        first = TileType(TileCategory.PINZU, 5)
        second = TileType(TileCategory.PINZU, 5)
        self.assertEqual(first, second)
        self.assertEqual(len({first, second}), 1)


class TileTest(unittest.TestCase):
    def test_copy_index_distinguishes_physical_tiles(self) -> None:
        tile_type = TileType(TileCategory.SOUZU, 3)
        self.assertNotEqual(Tile(tile_type, 0), Tile(tile_type, 1))

    def test_rejects_copy_index_out_of_range(self) -> None:
        tile_type = TileType(TileCategory.MANZU, 1)
        for copy_index in (-1, 4):
            with (
                self.subTest(copy_index=copy_index),
                self.assertRaises(ValueError),
            ):
                Tile(tile_type, copy_index)

    def test_rejects_non_integer_copy_index(self) -> None:
        tile_type = TileType(TileCategory.MANZU, 1)
        for copy_index in ("0", 0.0, False):
            with (
                self.subTest(copy_index=copy_index),
                self.assertRaises(TypeError),
            ):
                Tile(tile_type, copy_index)

    def test_rejects_non_tile_type(self) -> None:
        with self.assertRaises(TypeError):
            Tile("1m", 0)

    def test_rejects_non_boolean_red_flag(self) -> None:
        tile_type = TileType(TileCategory.MANZU, 5)
        with self.assertRaises(TypeError):
            Tile(tile_type, 0, is_red=1)

    def test_allows_only_suited_fives_to_be_red(self) -> None:
        for category in (
            TileCategory.MANZU,
            TileCategory.PINZU,
            TileCategory.SOUZU,
        ):
            with self.subTest(category=category):
                self.assertTrue(Tile(TileType(category, 5), 0, is_red=True).is_red)

        invalid_types = (
            TileType(TileCategory.MANZU, 4),
            TileType(TileCategory.HONOR, 5),
        )
        for tile_type in invalid_types:
            with (
                self.subTest(tile_type=tile_type),
                self.assertRaises(ValueError),
            ):
                Tile(tile_type, 0, is_red=True)

    def test_is_immutable(self) -> None:
        tile = Tile(TileType(TileCategory.MANZU, 1), 0)
        with self.assertRaises(FrozenInstanceError):
            tile.copy_index = 1

    def test_has_standard_136_tile_id(self) -> None:
        cases = (
            (TileType(TileCategory.MANZU, 1), 0, 0),
            (TileType(TileCategory.MANZU, 5), 0, 16),
            (TileType(TileCategory.PINZU, 1), 0, 36),
            (TileType(TileCategory.SOUZU, 1), 0, 72),
            (TileType(TileCategory.HONOR, 1), 0, 108),
            (TileType(TileCategory.HONOR, 7), 3, 135),
        )
        for tile_type, copy_index, expected_id in cases:
            with self.subTest(tile_type=tile_type, copy_index=copy_index):
                self.assertEqual(Tile(tile_type, copy_index).id, expected_id)


class StandardTilesTest(unittest.TestCase):
    def test_standard_tile_types_are_34_unique_types_in_order(self) -> None:
        self.assertEqual(len(STANDARD_TILE_TYPES), 34)
        self.assertEqual(len(set(STANDARD_TILE_TYPES)), 34)
        self.assertEqual(
            tuple(tile_type.id for tile_type in STANDARD_TILE_TYPES),
            tuple(range(34)),
        )

    def test_standard_tiles_are_136_unique_tiles_with_four_of_each_type(self) -> None:
        self.assertIsInstance(STANDARD_TILES, tuple)
        self.assertEqual(len(STANDARD_TILES), 136)
        self.assertEqual(len(set(STANDARD_TILES)), 136)
        self.assertEqual(
            Counter(tile.tile_type for tile in STANDARD_TILES),
            Counter({tile_type: 4 for tile_type in STANDARD_TILE_TYPES}),
        )
        self.assertEqual(tuple(tile.id for tile in STANDARD_TILES), tuple(range(136)))

    def test_standard_tiles_have_one_red_five_of_each_suit(self) -> None:
        red_tiles = tuple(tile for tile in STANDARD_TILES if tile.is_red)
        self.assertEqual(tuple(tile.id for tile in red_tiles), (16, 52, 88))
        self.assertEqual(create_standard_tiles(), STANDARD_TILES)


if __name__ == "__main__":
    unittest.main()
