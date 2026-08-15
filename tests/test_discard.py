import unittest
from dataclasses import FrozenInstanceError

from lisjong_engine.discard import Discard, River
from lisjong_engine.seat import Seat
from lisjong_engine.tile import STANDARD_TILES, Tile, TileCategory, TileType


class DiscardTest(unittest.TestCase):
    def test_holds_tile_and_tsumogiri_state(self) -> None:
        discard = Discard(STANDARD_TILES[0], is_tsumogiri=True)

        self.assertEqual(discard.tile, STANDARD_TILES[0])
        self.assertTrue(discard.is_tsumogiri)
        self.assertIsNone(discard.called_by)

    def test_holds_calling_seat(self) -> None:
        discard = Discard(
            STANDARD_TILES[0],
            is_tsumogiri=False,
            called_by=Seat.SOUTH,
        )

        self.assertIs(discard.called_by, Seat.SOUTH)

    def test_is_immutable(self) -> None:
        discard = Discard(STANDARD_TILES[0], is_tsumogiri=False)

        with self.assertRaises(FrozenInstanceError):
            discard.is_tsumogiri = True

    def test_rejects_non_tile(self) -> None:
        with self.assertRaises(TypeError):
            Discard("1m", is_tsumogiri=False)

    def test_rejects_non_boolean_tsumogiri_state(self) -> None:
        for is_tsumogiri in (0, 1, "false", None):
            with self.subTest(is_tsumogiri=is_tsumogiri), self.assertRaises(TypeError):
                Discard(STANDARD_TILES[0], is_tsumogiri=is_tsumogiri)

    def test_rejects_non_seat_caller(self) -> None:
        for called_by in ("south", 1, False):
            with self.subTest(called_by=called_by), self.assertRaises(TypeError):
                Discard(
                    STANDARD_TILES[0],
                    is_tsumogiri=False,
                    called_by=called_by,
                )


class RiverTest(unittest.TestCase):
    def test_initializes_empty_river(self) -> None:
        river = River()

        self.assertEqual(river.count, 0)
        self.assertEqual(river.discards, ())
        self.assertIsInstance(river.discards, tuple)

    def test_keeps_initial_order_and_copies_input_sequence(self) -> None:
        source_discards = [
            Discard(STANDARD_TILES[0], is_tsumogiri=False),
            Discard(STANDARD_TILES[1], is_tsumogiri=True),
        ]
        river = River(source_discards)

        source_discards.clear()

        self.assertEqual(river.count, 2)
        self.assertEqual(
            river.discards,
            (
                Discard(STANDARD_TILES[0], is_tsumogiri=False),
                Discard(STANDARD_TILES[1], is_tsumogiri=True),
            ),
        )

    def test_does_not_impose_turn_based_tile_count_limit(self) -> None:
        discards = tuple(
            Discard(tile, is_tsumogiri=False) for tile in STANDARD_TILES[:25]
        )

        river = River(discards)

        self.assertEqual(river.count, 25)
        self.assertEqual(river.discards, discards)

    def test_rejects_non_discard_element(self) -> None:
        with self.assertRaises(TypeError):
            River((Discard(STANDARD_TILES[0], is_tsumogiri=False), STANDARD_TILES[1]))

    def test_rejects_duplicate_physical_tile_id(self) -> None:
        tile_type = TileType(TileCategory.MANZU, 5)
        normal_five = Tile(tile_type, 0)
        red_five_with_same_id = Tile(tile_type, 0, is_red=True)

        with self.assertRaises(ValueError):
            River(
                (
                    Discard(normal_five, is_tsumogiri=False),
                    Discard(red_five_with_same_id, is_tsumogiri=True),
                )
            )

    def test_add_appends_discard(self) -> None:
        first = Discard(STANDARD_TILES[0], is_tsumogiri=False)
        second = Discard(STANDARD_TILES[1], is_tsumogiri=True)
        river = River((first,))

        river.add(second)

        self.assertEqual(river.count, 2)
        self.assertEqual(river.discards, (first, second))

    def test_add_rejects_non_discard_without_changing_state(self) -> None:
        first = Discard(STANDARD_TILES[0], is_tsumogiri=False)
        river = River((first,))
        original_discards = river.discards

        with self.assertRaises(TypeError):
            river.add(STANDARD_TILES[1])

        self.assertEqual(river.discards, original_discards)

    def test_add_rejects_duplicate_id_without_changing_state(self) -> None:
        first = Discard(STANDARD_TILES[0], is_tsumogiri=False)
        river = River((first,))
        original_discards = river.discards

        with self.assertRaises(ValueError):
            river.add(Discard(STANDARD_TILES[0], is_tsumogiri=True))

        self.assertEqual(river.discards, original_discards)

    def test_mark_called_records_caller_without_removing_discard(self) -> None:
        first = Discard(STANDARD_TILES[0], is_tsumogiri=False)
        second = Discard(STANDARD_TILES[4], is_tsumogiri=True)
        river = River((first, second))

        called_discard = river.mark_called(first.tile.id, Seat.SOUTH)

        self.assertEqual(
            called_discard,
            Discard(
                first.tile,
                is_tsumogiri=False,
                called_by=Seat.SOUTH,
            ),
        )
        self.assertEqual(river.discards, (called_discard, second))

    def test_mark_called_rejects_invalid_arguments_without_changing_state(
        self,
    ) -> None:
        river = River((Discard(STANDARD_TILES[0], is_tsumogiri=False),))
        original_discards = river.discards

        invalid_cases = (
            ("0", Seat.SOUTH, TypeError),
            (STANDARD_TILES[0].id, "south", TypeError),
            (STANDARD_TILES[1].id, Seat.SOUTH, ValueError),
        )
        for tile_id, caller, expected_error in invalid_cases:
            with (
                self.subTest(tile_id=tile_id, caller=caller),
                self.assertRaises(expected_error),
            ):
                river.mark_called(tile_id, caller)

            self.assertEqual(river.discards, original_discards)

    def test_mark_called_rejects_second_call_without_changing_state(self) -> None:
        called_discard = Discard(
            STANDARD_TILES[0],
            is_tsumogiri=False,
            called_by=Seat.SOUTH,
        )
        river = River((called_discard,))

        with self.assertRaises(ValueError):
            river.mark_called(called_discard.tile.id, Seat.WEST)

        self.assertEqual(river.discards, (called_discard,))


if __name__ == "__main__":
    unittest.main()
