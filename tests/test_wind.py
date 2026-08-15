import unittest

from lisjong_engine.seat import Seat
from lisjong_engine.wind import Wind


class WindTest(unittest.TestCase):
    def test_has_four_winds_in_standard_order(self) -> None:
        self.assertEqual(
            tuple(Wind),
            (Wind.EAST, Wind.SOUTH, Wind.WEST, Wind.NORTH),
        )

    def test_values_are_stable_identifiers(self) -> None:
        self.assertEqual(
            tuple(wind.value for wind in Wind),
            ("east", "south", "west", "north"),
        )

    def test_next_advances_in_standard_order(self) -> None:
        cases = (
            (Wind.EAST, Wind.SOUTH),
            (Wind.SOUTH, Wind.WEST),
            (Wind.WEST, Wind.NORTH),
            (Wind.NORTH, Wind.EAST),
        )
        for wind, expected in cases:
            with self.subTest(wind=wind):
                self.assertIs(wind.next(), expected)

    def test_next_returns_to_the_starting_wind_after_four_steps(self) -> None:
        for wind in Wind:
            with self.subTest(wind=wind):
                current = wind
                for _ in range(len(Wind)):
                    current = current.next()

                self.assertIs(current, wind)

    def test_is_a_distinct_type_from_seat(self) -> None:
        self.assertNotEqual(Wind.EAST, Seat.EAST)
        self.assertNotIsInstance(Wind.EAST, Seat)


if __name__ == "__main__":
    unittest.main()
