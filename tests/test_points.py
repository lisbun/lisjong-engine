import unittest
from dataclasses import FrozenInstanceError

from lisjong_engine.points import SeatPoints
from lisjong_engine.seat import Seat


class SeatPointsTest(unittest.TestCase):
    def test_stores_points_for_all_four_seats(self) -> None:
        points = SeatPoints(
            east=25_000,
            south=26_000,
            west=24_000,
            north=25_000,
        )

        self.assertEqual(points[Seat.EAST], 25_000)
        self.assertEqual(points[Seat.SOUTH], 26_000)
        self.assertEqual(points[Seat.WEST], 24_000)
        self.assertEqual(points[Seat.NORTH], 25_000)

    def test_total_returns_sum_of_all_seats(self) -> None:
        points = SeatPoints(
            east=25_000,
            south=26_000,
            west=24_000,
            north=25_000,
        )

        self.assertEqual(points.total, 100_000)

    def test_as_dict_returns_all_four_seats(self) -> None:
        points = SeatPoints(
            east=25_000,
            south=26_000,
            west=24_000,
            north=25_000,
        )

        self.assertEqual(
            points.as_dict(),
            {
                Seat.EAST: 25_000,
                Seat.SOUTH: 26_000,
                Seat.WEST: 24_000,
                Seat.NORTH: 25_000,
            },
        )

    def test_from_mapping_constructs_seat_points(self) -> None:
        points = SeatPoints.from_mapping(
            {
                Seat.EAST: 25_000,
                Seat.SOUTH: 26_000,
                Seat.WEST: 24_000,
                Seat.NORTH: 25_000,
            }
        )

        self.assertEqual(
            points,
            SeatPoints(
                east=25_000,
                south=26_000,
                west=24_000,
                north=25_000,
            ),
        )

    def test_add_returns_new_seat_points(self) -> None:
        scores = SeatPoints(25_000, 25_000, 25_000, 25_000)
        deltas = SeatPoints(-1_000, 2_000, -500, -500)

        result = scores.add(deltas)

        self.assertEqual(
            result,
            SeatPoints(24_000, 27_000, 24_500, 24_500),
        )
        self.assertEqual(scores, SeatPoints(25_000, 25_000, 25_000, 25_000))

    def test_is_immutable(self) -> None:
        points = SeatPoints(25_000, 25_000, 25_000, 25_000)

        with self.assertRaises(FrozenInstanceError):
            setattr(points, "east", 30_000)

    def test_rejects_non_int_values_including_bool(self) -> None:
        with self.assertRaises(TypeError):
            SeatPoints(True, 25_000, 25_000, 25_000)

        with self.assertRaises(TypeError):
            SeatPoints(25_000, 25_000.0, 25_000, 25_000)

    def test_from_mapping_requires_exactly_all_four_seats(self) -> None:
        with self.assertRaises(ValueError):
            SeatPoints.from_mapping(
                {
                    Seat.EAST: 25_000,
                    Seat.SOUTH: 25_000,
                    Seat.WEST: 25_000,
                }
            )

    def test_rejects_invalid_seat_lookup(self) -> None:
        points = SeatPoints(25_000, 25_000, 25_000, 25_000)

        with self.assertRaises(TypeError):
            points["east"]  # type: ignore[index]

    def test_add_requires_seat_points(self) -> None:
        points = SeatPoints(25_000, 25_000, 25_000, 25_000)

        with self.assertRaises(TypeError):
            points.add("invalid")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
