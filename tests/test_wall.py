import random
import unittest

from lisjong_engine.random_source import RandomSource
from lisjong_engine.tile import STANDARD_TILES, Tile, TileCategory, TileType
from lisjong_engine.wall import (
    DEAD_WALL_SIZE,
    MAX_DORA_INDICATOR_COUNT,
    RINSHAN_TILE_COUNT,
    Wall,
    create_shuffled_wall,
)


class WallTest(unittest.TestCase):
    def test_keeps_initial_order_and_reports_remaining_tiles(self) -> None:
        tiles = STANDARD_TILES[:3]

        wall = Wall(tiles)

        self.assertEqual(wall.remaining_count, 3)
        self.assertEqual(wall.remaining_tiles, tiles)
        self.assertIsInstance(wall.remaining_tiles, tuple)

    def test_draws_tiles_from_the_front_in_order(self) -> None:
        tiles = STANDARD_TILES[:3]
        wall = Wall(tiles)

        self.assertEqual(wall.draw(), tiles[0])
        self.assertEqual(wall.draw(), tiles[1])
        self.assertEqual(wall.remaining_count, 1)
        self.assertEqual(wall.remaining_tiles, tiles[2:])

    def test_rejects_draw_from_empty_wall(self) -> None:
        wall = Wall(())

        with self.assertRaises(IndexError):
            wall.draw()

        self.assertEqual(wall.remaining_count, 0)
        self.assertEqual(wall.remaining_tiles, ())

    def test_rejects_draw_after_last_tile(self) -> None:
        wall = Wall(STANDARD_TILES[:1])

        self.assertEqual(wall.draw(), STANDARD_TILES[0])
        with self.assertRaises(IndexError):
            wall.draw()

        self.assertEqual(wall.remaining_count, 0)

    def test_rejects_non_tile_element(self) -> None:
        with self.assertRaises(TypeError):
            Wall((STANDARD_TILES[0], "1m"))

    def test_rejects_duplicate_physical_tile_id(self) -> None:
        tile_type = TileType(TileCategory.MANZU, 5)
        normal_five = Tile(tile_type, 0)
        red_five_with_same_id = Tile(tile_type, 0, is_red=True)

        with self.assertRaises(ValueError):
            Wall((normal_five, red_five_with_same_id))

    def test_copies_input_sequence(self) -> None:
        source_tiles = list(STANDARD_TILES[:2])
        wall = Wall(source_tiles)

        source_tiles.clear()

        self.assertEqual(wall.remaining_tiles, STANDARD_TILES[:2])

    def test_keeps_four_rinshan_tiles_in_fourteen_tile_dead_wall(
        self,
    ) -> None:
        source_dead_wall = list(STANDARD_TILES[3:17])

        wall = Wall(STANDARD_TILES[:3], source_dead_wall)
        source_dead_wall.clear()

        self.assertEqual(wall.remaining_count, 3)
        self.assertEqual(wall.dead_wall_tiles, STANDARD_TILES[3:17])
        self.assertEqual(wall.remaining_rinshan_count, RINSHAN_TILE_COUNT)
        self.assertEqual(
            wall.remaining_rinshan_tiles,
            STANDARD_TILES[3:7],
        )
        self.assertTrue(wall.can_draw_rinshan)

    def test_assigns_five_corresponding_dora_and_ura_indicator_pairs(
        self,
    ) -> None:
        wall = Wall(STANDARD_TILES[:3], STANDARD_TILES[3:17])

        self.assertEqual(
            wall.dora_indicator_tiles,
            STANDARD_TILES[7:17:2],
        )
        self.assertEqual(
            wall.ura_dora_indicator_tiles,
            STANDARD_TILES[8:17:2],
        )
        self.assertEqual(wall.revealed_dora_indicator_count, 1)
        self.assertEqual(wall.revealed_dora_indicators, STANDARD_TILES[7:8])
        self.assertEqual(
            wall.corresponding_ura_dora_indicators,
            STANDARD_TILES[8:9],
        )

    def test_reveals_one_corresponding_indicator_for_each_kan(self) -> None:
        wall = Wall(STANDARD_TILES[:3], STANDARD_TILES[3:17])

        revealed = tuple(
            wall.reveal_kan_dora() for _ in range(MAX_DORA_INDICATOR_COUNT - 1)
        )

        self.assertEqual(revealed, STANDARD_TILES[9:17:2])
        self.assertEqual(
            wall.revealed_dora_indicators,
            STANDARD_TILES[7:17:2],
        )
        self.assertEqual(
            wall.corresponding_ura_dora_indicators,
            STANDARD_TILES[8:17:2],
        )
        with self.assertRaises(RuntimeError):
            wall.reveal_kan_dora()

    def test_wall_without_dead_wall_has_no_indicators(self) -> None:
        wall = Wall(STANDARD_TILES[:3])

        self.assertEqual(wall.dora_indicator_tiles, ())
        self.assertEqual(wall.ura_dora_indicator_tiles, ())
        self.assertEqual(wall.revealed_dora_indicator_count, 0)
        with self.assertRaises(RuntimeError):
            wall.reveal_kan_dora()

    def test_rejects_invalid_dead_wall_size(self) -> None:
        for dead_wall_tiles in (
            STANDARD_TILES[3:16],
            STANDARD_TILES[3:18],
        ):
            with (
                self.subTest(count=len(dead_wall_tiles)),
                self.assertRaises(ValueError),
            ):
                Wall(STANDARD_TILES[:3], dead_wall_tiles)

    def test_rejects_duplicate_tile_across_live_and_dead_walls(self) -> None:
        dead_wall_tiles = (
            STANDARD_TILES[0],
            *STANDARD_TILES[1:14],
        )

        with self.assertRaises(ValueError):
            Wall(STANDARD_TILES[:1], dead_wall_tiles)

    def test_draw_rinshan_replenishes_dead_wall_from_live_wall_end(
        self,
    ) -> None:
        wall = Wall(
            STANDARD_TILES[:3],
            STANDARD_TILES[3:17],
        )

        tile = wall.draw_rinshan()

        self.assertEqual(tile, STANDARD_TILES[3])
        self.assertEqual(wall.remaining_tiles, STANDARD_TILES[:2])
        self.assertEqual(
            wall.dead_wall_tiles,
            (STANDARD_TILES[2], *STANDARD_TILES[4:17]),
        )
        self.assertEqual(wall.remaining_rinshan_count, 3)
        self.assertEqual(
            wall.remaining_rinshan_tiles,
            STANDARD_TILES[4:7],
        )

    def test_draws_at_most_four_rinshan_tiles(self) -> None:
        wall = Wall(
            STANDARD_TILES[:5],
            STANDARD_TILES[5:19],
        )

        drawn_tiles = tuple(wall.draw_rinshan() for _ in range(RINSHAN_TILE_COUNT))
        state_after_four_draws = (
            wall.remaining_tiles,
            wall.dead_wall_tiles,
            wall.remaining_rinshan_count,
        )

        self.assertEqual(drawn_tiles, STANDARD_TILES[5:9])
        self.assertEqual(wall.remaining_tiles, STANDARD_TILES[:1])
        self.assertEqual(
            wall.dead_wall_tiles[:4],
            (
                STANDARD_TILES[4],
                STANDARD_TILES[3],
                STANDARD_TILES[2],
                STANDARD_TILES[1],
            ),
        )
        self.assertEqual(wall.remaining_rinshan_count, 0)
        self.assertEqual(wall.remaining_rinshan_tiles, ())
        self.assertFalse(wall.can_draw_rinshan)

        with self.assertRaises(IndexError):
            wall.draw_rinshan()

        self.assertEqual(
            (
                wall.remaining_tiles,
                wall.dead_wall_tiles,
                wall.remaining_rinshan_count,
            ),
            state_after_four_draws,
        )

    def test_rejects_rinshan_draw_without_dead_wall(self) -> None:
        wall = Wall(STANDARD_TILES[:3])
        original_state = (
            wall.remaining_tiles,
            wall.dead_wall_tiles,
            wall.remaining_rinshan_count,
        )

        with self.assertRaises(IndexError):
            wall.draw_rinshan()

        self.assertEqual(
            (
                wall.remaining_tiles,
                wall.dead_wall_tiles,
                wall.remaining_rinshan_count,
            ),
            original_state,
        )

    def test_rejects_rinshan_draw_without_live_wall_replacement(
        self,
    ) -> None:
        wall = Wall((), STANDARD_TILES[:DEAD_WALL_SIZE])
        original_state = (
            wall.remaining_tiles,
            wall.dead_wall_tiles,
            wall.remaining_rinshan_count,
        )

        with self.assertRaises(IndexError):
            wall.draw_rinshan()

        self.assertEqual(
            (
                wall.remaining_tiles,
                wall.dead_wall_tiles,
                wall.remaining_rinshan_count,
            ),
            original_state,
        )

    def test_copy_preserves_state_without_sharing_future_changes(self) -> None:
        wall = Wall(
            STANDARD_TILES[:6],
            STANDARD_TILES[6:20],
        )
        wall.draw()
        wall.draw_rinshan()
        wall.reveal_kan_dora()

        copied_wall = wall.copy()
        copied_state = (
            copied_wall.remaining_tiles,
            copied_wall.dead_wall_tiles,
            copied_wall.remaining_rinshan_count,
        )
        wall.draw()
        wall.draw_rinshan()

        self.assertEqual(
            (
                copied_wall.remaining_tiles,
                copied_wall.dead_wall_tiles,
                copied_wall.remaining_rinshan_count,
            ),
            copied_state,
        )
        self.assertEqual(copied_wall.revealed_dora_indicator_count, 2)


class CreateShuffledWallTest(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(random.setstate, random.getstate())

    def test_same_seed_creates_same_order(self) -> None:
        first = create_shuffled_wall(RandomSource(1234))
        second = create_shuffled_wall(RandomSource(1234))

        self.assertEqual(first.remaining_tiles, second.remaining_tiles)
        self.assertEqual(first.dead_wall_tiles, second.dead_wall_tiles)
        self.assertNotEqual(first.remaining_tiles, STANDARD_TILES)

    def test_different_seeds_typically_create_different_orders(self) -> None:
        """seedが実際に山へ届いていることの回帰test。

        136枚のshuffleでは偶然の一致は無視できるが、異なるseedが常に異なる山に
        なることをengineの公開契約として保証するものではない。
        """
        first = create_shuffled_wall(RandomSource(1234))
        second = create_shuffled_wall(RandomSource(5678))

        self.assertNotEqual(first.remaining_tiles, second.remaining_tiles)

    def test_is_independent_of_global_random_state(self) -> None:
        random.seed(0)
        first = create_shuffled_wall(RandomSource(1234))

        random.seed(9999)
        for _ in range(10):
            random.random()
        second = create_shuffled_wall(RandomSource(1234))

        self.assertEqual(first.remaining_tiles, second.remaining_tiles)
        self.assertEqual(first.dead_wall_tiles, second.dead_wall_tiles)

    def test_partitions_all_standard_tiles_into_live_and_dead_walls(
        self,
    ) -> None:
        wall = create_shuffled_wall(RandomSource(1234))
        all_tiles = (*wall.remaining_tiles, *wall.dead_wall_tiles)

        self.assertEqual(wall.remaining_count, 136 - DEAD_WALL_SIZE)
        self.assertEqual(len(wall.dead_wall_tiles), DEAD_WALL_SIZE)
        self.assertEqual(wall.remaining_rinshan_count, RINSHAN_TILE_COUNT)
        self.assertEqual(
            {tile.id for tile in all_tiles},
            set(range(136)),
        )
        self.assertEqual(
            {tile.id for tile in all_tiles if tile.is_red},
            {16, 52, 88},
        )

    def test_preserves_every_physical_tile_identity(self) -> None:
        wall = create_shuffled_wall(RandomSource(1234))
        all_tiles = (*wall.remaining_tiles, *wall.dead_wall_tiles)

        self.assertEqual(len(all_tiles), 136)
        self.assertEqual(
            tuple(sorted(all_tiles, key=lambda tile: tile.id)),
            STANDARD_TILES,
        )

    def test_does_not_modify_standard_tiles(self) -> None:
        original_tiles = STANDARD_TILES
        original_ids = tuple(tile.id for tile in STANDARD_TILES)

        create_shuffled_wall(RandomSource(1234))

        self.assertIs(STANDARD_TILES, original_tiles)
        self.assertEqual(
            tuple(tile.id for tile in STANDARD_TILES),
            original_ids,
        )

    def test_rejects_non_random_source(self) -> None:
        for random_source in (1234, random.Random(1234), None):
            with (
                self.subTest(random_source=type(random_source).__name__),
                self.assertRaises(TypeError),
            ):
                create_shuffled_wall(random_source)


if __name__ == "__main__":
    unittest.main()
