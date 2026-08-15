import unittest
from dataclasses import FrozenInstanceError

from lisjong_engine.meld import Ankan, Chi, Daiminkan, Kakan, Pon
from lisjong_engine.seat import Seat
from lisjong_engine.tile import STANDARD_TILES, Tile, TileCategory, TileType


class PonTest(unittest.TestCase):
    def test_holds_called_tile_consumed_tiles_and_source_seat(self) -> None:
        source_tiles = list(STANDARD_TILES[1:3])

        pon = Pon(STANDARD_TILES[0], source_tiles, Seat.WEST)
        source_tiles.clear()

        self.assertEqual(pon.called_tile, STANDARD_TILES[0])
        self.assertEqual(pon.consumed_tiles, STANDARD_TILES[1:3])
        self.assertIsInstance(pon.consumed_tiles, tuple)
        self.assertIs(pon.source_seat, Seat.WEST)
        self.assertEqual(pon.tiles, STANDARD_TILES[:3])

    def test_accepts_red_five_as_one_of_three_same_type_tiles(self) -> None:
        pon = Pon(
            STANDARD_TILES[16],
            STANDARD_TILES[17:19],
            Seat.SOUTH,
        )

        self.assertTrue(pon.called_tile.is_red)
        self.assertEqual(
            tuple(tile.id for tile in pon.consumed_tiles),
            (17, 18),
        )

    def test_is_immutable(self) -> None:
        pon = Pon(STANDARD_TILES[0], STANDARD_TILES[1:3], Seat.SOUTH)

        with self.assertRaises(FrozenInstanceError):
            pon.source_seat = Seat.WEST

    def test_rejects_non_tile_called_tile(self) -> None:
        with self.assertRaises(TypeError):
            Pon("1m", STANDARD_TILES[1:3], Seat.SOUTH)

    def test_rejects_non_iterable_consumed_tiles(self) -> None:
        with self.assertRaises(TypeError):
            Pon(STANDARD_TILES[0], None, Seat.SOUTH)

    def test_rejects_non_tile_consumed_element(self) -> None:
        with self.assertRaises(TypeError):
            Pon(
                STANDARD_TILES[0],
                (STANDARD_TILES[1], "1m"),
                Seat.SOUTH,
            )

    def test_requires_exactly_two_consumed_tiles(self) -> None:
        cases = (
            STANDARD_TILES[1:2],
            STANDARD_TILES[1:4],
        )

        for consumed_tiles in cases:
            with self.subTest(count=len(consumed_tiles)), self.assertRaises(ValueError):
                Pon(STANDARD_TILES[0], consumed_tiles, Seat.SOUTH)

    def test_rejects_non_seat_source(self) -> None:
        with self.assertRaises(TypeError):
            Pon(STANDARD_TILES[0], STANDARD_TILES[1:3], "south")

    def test_rejects_different_tile_types(self) -> None:
        with self.assertRaises(ValueError):
            Pon(
                STANDARD_TILES[0],
                (STANDARD_TILES[1], STANDARD_TILES[4]),
                Seat.SOUTH,
            )

    def test_rejects_duplicate_physical_tile_id(self) -> None:
        tile_type = TileType(TileCategory.MANZU, 5)
        normal_five = Tile(tile_type, 0)
        red_five_with_same_id = Tile(tile_type, 0, is_red=True)

        with self.assertRaises(ValueError):
            Pon(
                normal_five,
                (red_five_with_same_id, Tile(tile_type, 1)),
                Seat.SOUTH,
            )


class KakanTest(unittest.TestCase):
    def test_holds_original_pon_added_tile_and_derived_properties(self) -> None:
        pon = Pon(
            STANDARD_TILES[0],
            STANDARD_TILES[1:3],
            Seat.WEST,
        )

        kakan = Kakan(pon, STANDARD_TILES[3])

        self.assertEqual(kakan.pon, pon)
        self.assertEqual(kakan.added_tile, STANDARD_TILES[3])
        self.assertEqual(kakan.called_tile, STANDARD_TILES[0])
        self.assertEqual(kakan.consumed_tiles, STANDARD_TILES[1:3])
        self.assertIs(kakan.source_seat, Seat.WEST)
        self.assertEqual(kakan.tiles, STANDARD_TILES[:4])

    def test_accepts_red_five_as_added_tile(self) -> None:
        pon = Pon(
            STANDARD_TILES[17],
            STANDARD_TILES[18:20],
            Seat.SOUTH,
        )

        kakan = Kakan(pon, STANDARD_TILES[16])

        self.assertTrue(kakan.added_tile.is_red)
        self.assertEqual(
            tuple(tile.id for tile in kakan.tiles),
            (17, 18, 19, 16),
        )

    def test_is_immutable(self) -> None:
        kakan = Kakan(
            Pon(
                STANDARD_TILES[0],
                STANDARD_TILES[1:3],
                Seat.SOUTH,
            ),
            STANDARD_TILES[3],
        )

        with self.assertRaises(FrozenInstanceError):
            kakan.added_tile = STANDARD_TILES[4]

    def test_rejects_non_pon(self) -> None:
        with self.assertRaises(TypeError):
            Kakan(STANDARD_TILES[:3], STANDARD_TILES[3])

    def test_rejects_non_tile_added_tile(self) -> None:
        pon = Pon(
            STANDARD_TILES[0],
            STANDARD_TILES[1:3],
            Seat.SOUTH,
        )

        with self.assertRaises(TypeError):
            Kakan(pon, "1m")

    def test_rejects_different_tile_type(self) -> None:
        pon = Pon(
            STANDARD_TILES[0],
            STANDARD_TILES[1:3],
            Seat.SOUTH,
        )

        with self.assertRaises(ValueError):
            Kakan(pon, STANDARD_TILES[4])

    def test_rejects_duplicate_physical_tile_id(self) -> None:
        pon = Pon(
            STANDARD_TILES[0],
            STANDARD_TILES[1:3],
            Seat.SOUTH,
        )

        with self.assertRaises(ValueError):
            Kakan(pon, STANDARD_TILES[0])


class ChiTest(unittest.TestCase):
    def test_holds_called_tile_consumed_tiles_and_source_seat(self) -> None:
        source_tiles = [STANDARD_TILES[0], STANDARD_TILES[4]]

        chi = Chi(STANDARD_TILES[8], source_tiles, Seat.EAST)
        source_tiles.clear()

        self.assertEqual(chi.called_tile, STANDARD_TILES[8])
        self.assertEqual(
            chi.consumed_tiles,
            (STANDARD_TILES[0], STANDARD_TILES[4]),
        )
        self.assertIsInstance(chi.consumed_tiles, tuple)
        self.assertIs(chi.source_seat, Seat.EAST)
        self.assertEqual(
            chi.tiles,
            (STANDARD_TILES[8], STANDARD_TILES[0], STANDARD_TILES[4]),
        )

    def test_accepts_red_five_in_sequence(self) -> None:
        chi = Chi(
            STANDARD_TILES[16],
            (STANDARD_TILES[12], STANDARD_TILES[20]),
            Seat.NORTH,
        )

        self.assertTrue(chi.called_tile.is_red)
        self.assertEqual(
            tuple(tile.tile_type.rank for tile in chi.consumed_tiles),
            (4, 6),
        )

    def test_accepts_consumed_tiles_in_non_rank_order(self) -> None:
        chi = Chi(
            STANDARD_TILES[4],
            (STANDARD_TILES[8], STANDARD_TILES[0]),
            Seat.EAST,
        )

        self.assertEqual(
            chi.consumed_tiles,
            (STANDARD_TILES[8], STANDARD_TILES[0]),
        )

    def test_is_immutable(self) -> None:
        chi = Chi(
            STANDARD_TILES[8],
            (STANDARD_TILES[0], STANDARD_TILES[4]),
            Seat.EAST,
        )

        with self.assertRaises(FrozenInstanceError):
            chi.source_seat = Seat.SOUTH

    def test_rejects_non_tile_called_tile(self) -> None:
        with self.assertRaises(TypeError):
            Chi(
                "3m",
                (STANDARD_TILES[0], STANDARD_TILES[4]),
                Seat.EAST,
            )

    def test_rejects_non_iterable_consumed_tiles(self) -> None:
        with self.assertRaises(TypeError):
            Chi(STANDARD_TILES[8], None, Seat.EAST)

    def test_rejects_non_tile_consumed_element(self) -> None:
        with self.assertRaises(TypeError):
            Chi(
                STANDARD_TILES[8],
                (STANDARD_TILES[0], "2m"),
                Seat.EAST,
            )

    def test_requires_exactly_two_consumed_tiles(self) -> None:
        cases = (
            (STANDARD_TILES[0],),
            (
                STANDARD_TILES[0],
                STANDARD_TILES[4],
                STANDARD_TILES[12],
            ),
        )

        for consumed_tiles in cases:
            with self.subTest(count=len(consumed_tiles)), self.assertRaises(ValueError):
                Chi(STANDARD_TILES[8], consumed_tiles, Seat.EAST)

    def test_rejects_non_seat_source(self) -> None:
        with self.assertRaises(TypeError):
            Chi(
                STANDARD_TILES[8],
                (STANDARD_TILES[0], STANDARD_TILES[4]),
                "east",
            )

    def test_rejects_honor_tiles(self) -> None:
        with self.assertRaises(ValueError):
            Chi(
                STANDARD_TILES[116],
                (STANDARD_TILES[108], STANDARD_TILES[112]),
                Seat.EAST,
            )

    def test_rejects_different_suited_categories(self) -> None:
        with self.assertRaises(ValueError):
            Chi(
                STANDARD_TILES[44],
                (STANDARD_TILES[0], STANDARD_TILES[4]),
                Seat.EAST,
            )

    def test_rejects_non_consecutive_ranks(self) -> None:
        with self.assertRaises(ValueError):
            Chi(
                STANDARD_TILES[12],
                (STANDARD_TILES[0], STANDARD_TILES[4]),
                Seat.EAST,
            )

    def test_rejects_duplicate_physical_tile_id(self) -> None:
        with self.assertRaises(ValueError):
            Chi(
                STANDARD_TILES[4],
                (STANDARD_TILES[0], STANDARD_TILES[0]),
                Seat.EAST,
            )


class DaiminkanTest(unittest.TestCase):
    def test_holds_called_tile_consumed_tiles_and_source_seat(self) -> None:
        source_tiles = list(STANDARD_TILES[1:4])

        daiminkan = Daiminkan(
            STANDARD_TILES[0],
            source_tiles,
            Seat.WEST,
        )
        source_tiles.clear()

        self.assertEqual(daiminkan.called_tile, STANDARD_TILES[0])
        self.assertEqual(daiminkan.consumed_tiles, STANDARD_TILES[1:4])
        self.assertIsInstance(daiminkan.consumed_tiles, tuple)
        self.assertIs(daiminkan.source_seat, Seat.WEST)
        self.assertEqual(daiminkan.tiles, STANDARD_TILES[:4])

    def test_accepts_red_five_with_three_normal_fives(self) -> None:
        daiminkan = Daiminkan(
            STANDARD_TILES[16],
            STANDARD_TILES[17:20],
            Seat.SOUTH,
        )

        self.assertTrue(daiminkan.called_tile.is_red)
        self.assertEqual(
            tuple(tile.id for tile in daiminkan.tiles),
            (16, 17, 18, 19),
        )

    def test_is_immutable(self) -> None:
        daiminkan = Daiminkan(
            STANDARD_TILES[0],
            STANDARD_TILES[1:4],
            Seat.SOUTH,
        )

        with self.assertRaises(FrozenInstanceError):
            daiminkan.source_seat = Seat.WEST

    def test_rejects_non_tile_called_tile(self) -> None:
        with self.assertRaises(TypeError):
            Daiminkan("1m", STANDARD_TILES[1:4], Seat.SOUTH)

    def test_rejects_non_iterable_consumed_tiles(self) -> None:
        with self.assertRaises(TypeError):
            Daiminkan(STANDARD_TILES[0], None, Seat.SOUTH)

    def test_rejects_non_tile_consumed_element(self) -> None:
        with self.assertRaises(TypeError):
            Daiminkan(
                STANDARD_TILES[0],
                (*STANDARD_TILES[1:3], "1m"),
                Seat.SOUTH,
            )

    def test_requires_exactly_three_consumed_tiles(self) -> None:
        cases = (
            STANDARD_TILES[1:3],
            STANDARD_TILES[1:5],
        )

        for consumed_tiles in cases:
            with (
                self.subTest(count=len(consumed_tiles)),
                self.assertRaises(ValueError),
            ):
                Daiminkan(
                    STANDARD_TILES[0],
                    consumed_tiles,
                    Seat.SOUTH,
                )

    def test_rejects_non_seat_source(self) -> None:
        with self.assertRaises(TypeError):
            Daiminkan(
                STANDARD_TILES[0],
                STANDARD_TILES[1:4],
                "south",
            )

    def test_rejects_different_tile_types(self) -> None:
        with self.assertRaises(ValueError):
            Daiminkan(
                STANDARD_TILES[0],
                (
                    STANDARD_TILES[1],
                    STANDARD_TILES[2],
                    STANDARD_TILES[4],
                ),
                Seat.SOUTH,
            )

    def test_rejects_duplicate_physical_tile_id(self) -> None:
        tile_type = TileType(TileCategory.MANZU, 5)
        normal_five = Tile(tile_type, 0)
        red_five_with_same_id = Tile(tile_type, 0, is_red=True)

        with self.assertRaises(ValueError):
            Daiminkan(
                normal_five,
                (
                    red_five_with_same_id,
                    Tile(tile_type, 1),
                    Tile(tile_type, 2),
                ),
                Seat.SOUTH,
            )


class AnkanTest(unittest.TestCase):
    def test_holds_four_tiles_as_an_immutable_tuple(self) -> None:
        source_tiles = list(STANDARD_TILES[:4])

        ankan = Ankan(source_tiles)
        source_tiles.clear()

        self.assertEqual(ankan.tiles, STANDARD_TILES[:4])
        self.assertIsInstance(ankan.tiles, tuple)

        with self.assertRaises(FrozenInstanceError):
            ankan.tiles = STANDARD_TILES[4:8]

    def test_accepts_red_five_with_three_normal_fives(self) -> None:
        ankan = Ankan(STANDARD_TILES[16:20])

        self.assertTrue(ankan.tiles[0].is_red)
        self.assertEqual(
            tuple(tile.id for tile in ankan.tiles),
            (16, 17, 18, 19),
        )

    def test_rejects_non_iterable_tiles(self) -> None:
        with self.assertRaises(TypeError):
            Ankan(None)

    def test_rejects_non_tile_element(self) -> None:
        with self.assertRaises(TypeError):
            Ankan((*STANDARD_TILES[:3], "1m"))

    def test_requires_exactly_four_tiles(self) -> None:
        cases = (
            STANDARD_TILES[:3],
            STANDARD_TILES[:5],
        )

        for tiles in cases:
            with self.subTest(count=len(tiles)), self.assertRaises(ValueError):
                Ankan(tiles)

    def test_rejects_different_tile_types(self) -> None:
        with self.assertRaises(ValueError):
            Ankan(
                (
                    *STANDARD_TILES[:3],
                    STANDARD_TILES[4],
                )
            )

    def test_rejects_duplicate_physical_tile_id(self) -> None:
        tile_type = TileType(TileCategory.MANZU, 5)

        with self.assertRaises(ValueError):
            Ankan(
                (
                    Tile(tile_type, 0),
                    Tile(tile_type, 0, is_red=True),
                    Tile(tile_type, 1),
                    Tile(tile_type, 2),
                )
            )


if __name__ == "__main__":
    unittest.main()
