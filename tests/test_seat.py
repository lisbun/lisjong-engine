import unittest

from lisjong_engine.seat import Seat
from lisjong_engine.wind import Wind


class SeatTest(unittest.TestCase):
    def test_has_four_seats_in_turn_order(self) -> None:
        self.assertEqual(
            tuple(Seat),
            (Seat.EAST, Seat.SOUTH, Seat.WEST, Seat.NORTH),
        )

    def test_values_are_stable_identifiers(self) -> None:
        self.assertEqual(
            tuple(seat.value for seat in Seat),
            ("east", "south", "west", "north"),
        )

    def test_next_returns_the_following_seat_and_wraps_around(self) -> None:
        self.assertIs(Seat.EAST.next(), Seat.SOUTH)
        self.assertIs(Seat.SOUTH.next(), Seat.WEST)
        self.assertIs(Seat.WEST.next(), Seat.NORTH)
        self.assertIs(Seat.NORTH.next(), Seat.EAST)

    def test_is_a_distinct_type_from_wind(self) -> None:
        for seat, wind in zip(Seat, Wind, strict=True):
            with self.subTest(seat=seat, wind=wind):
                self.assertEqual(seat.value, wind.value)
                self.assertNotEqual(seat, wind)
                self.assertNotIsInstance(seat, Wind)


if __name__ == "__main__":
    unittest.main()
