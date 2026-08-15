import unittest

from lisjong_engine.hand import MAX_TILE_COUNT, Hand
from lisjong_engine.tile import STANDARD_TILES, Tile, TileCategory, TileType


class HandTest(unittest.TestCase):
    def test_initializes_empty_hand(self) -> None:
        hand = Hand()

        self.assertEqual(hand.count, 0)
        self.assertEqual(hand.tiles, ())
        self.assertIsInstance(hand.tiles, tuple)

    def test_keeps_initial_order_and_copies_input_sequence(self) -> None:
        source_tiles = list(STANDARD_TILES[:3])
        hand = Hand(source_tiles)

        source_tiles.clear()

        self.assertEqual(hand.count, 3)
        self.assertEqual(hand.tiles, STANDARD_TILES[:3])

    def test_accepts_maximum_fourteen_tiles(self) -> None:
        self.assertEqual(MAX_TILE_COUNT, 14)

        hand = Hand(STANDARD_TILES[:14])

        self.assertEqual(hand.count, 14)
        self.assertEqual(hand.tiles, STANDARD_TILES[:14])

    def test_rejects_more_than_fourteen_tiles(self) -> None:
        with self.assertRaises(ValueError):
            Hand(STANDARD_TILES[:15])

    def test_rejects_non_tile_element(self) -> None:
        with self.assertRaises(TypeError):
            Hand((STANDARD_TILES[0], "1m"))

    def test_rejects_duplicate_physical_tile_id(self) -> None:
        tile_type = TileType(TileCategory.MANZU, 5)
        normal_five = Tile(tile_type, 0)
        red_five_with_same_id = Tile(tile_type, 0, is_red=True)

        with self.assertRaises(ValueError):
            Hand((normal_five, red_five_with_same_id))

    def test_add_appends_tile(self) -> None:
        hand = Hand(STANDARD_TILES[:2])

        hand.add(STANDARD_TILES[2])

        self.assertEqual(hand.count, 3)
        self.assertEqual(hand.tiles, STANDARD_TILES[:3])

    def test_add_rejects_non_tile_without_changing_state(self) -> None:
        hand = Hand(STANDARD_TILES[:2])
        original_tiles = hand.tiles

        with self.assertRaises(TypeError):
            hand.add("1m")

        self.assertEqual(hand.tiles, original_tiles)

    def test_add_rejects_duplicate_id_without_changing_state(self) -> None:
        hand = Hand(STANDARD_TILES[:2])
        original_tiles = hand.tiles

        with self.assertRaises(ValueError):
            hand.add(STANDARD_TILES[0])

        self.assertEqual(hand.tiles, original_tiles)

    def test_add_rejects_fifteenth_tile_without_changing_state(self) -> None:
        hand = Hand(STANDARD_TILES[:14])
        original_tiles = hand.tiles

        with self.assertRaises(ValueError):
            hand.add(STANDARD_TILES[14])

        self.assertEqual(hand.tiles, original_tiles)

    def test_remove_returns_requested_physical_tile_and_keeps_order(self) -> None:
        hand = Hand(STANDARD_TILES[:4])
        removed_tile = STANDARD_TILES[1]

        result = hand.remove(removed_tile.id)

        self.assertEqual(result, removed_tile)
        self.assertEqual(hand.count, 3)
        self.assertEqual(
            hand.tiles,
            (STANDARD_TILES[0], STANDARD_TILES[2], STANDARD_TILES[3]),
        )

    def test_remove_rejects_non_integer_id_without_changing_state(self) -> None:
        hand = Hand(STANDARD_TILES[:2])
        original_tiles = hand.tiles

        for tile_id in ("0", 0.0, False):
            with self.subTest(tile_id=tile_id), self.assertRaises(TypeError):
                hand.remove(tile_id)

            self.assertEqual(hand.tiles, original_tiles)

    def test_remove_rejects_missing_id_without_changing_state(self) -> None:
        hand = Hand(STANDARD_TILES[:2])
        original_tiles = hand.tiles

        with self.assertRaises(ValueError):
            hand.remove(STANDARD_TILES[2].id)

        self.assertEqual(hand.tiles, original_tiles)


if __name__ == "__main__":
    unittest.main()
