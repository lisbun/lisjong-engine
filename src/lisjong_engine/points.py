from collections.abc import Mapping
from dataclasses import dataclass

from lisjong_engine.seat import Seat


@dataclass(frozen=True)
class SeatPoints:
    """4席分の点数snapshotまたはpoint deltaを表すimmutable値型。"""

    east: int
    south: int
    west: int
    north: int

    def __post_init__(self) -> None:
        values = (self.east, self.south, self.west, self.north)
        if any(type(value) is not int for value in values):
            raise TypeError("seat points must be ints")

    @classmethod
    def from_mapping(cls, points: Mapping[Seat, int]) -> "SeatPoints":
        if not isinstance(points, Mapping):
            raise TypeError("points must be a mapping")
        if set(points) != set(Seat):
            raise ValueError("points must contain exactly all four seats")
        return cls(*(points[seat] for seat in Seat))

    def __getitem__(self, seat: Seat) -> int:
        if not isinstance(seat, Seat):
            raise TypeError("seat must be a Seat")
        return {
            Seat.EAST: self.east,
            Seat.SOUTH: self.south,
            Seat.WEST: self.west,
            Seat.NORTH: self.north,
        }[seat]

    @property
    def total(self) -> int:
        return self.east + self.south + self.west + self.north

    def as_dict(self) -> dict[Seat, int]:
        return {seat: self[seat] for seat in Seat}

    def add(self, other: "SeatPoints") -> "SeatPoints":
        if not isinstance(other, SeatPoints):
            raise TypeError("other must be SeatPoints")
        return SeatPoints(*(self[seat] + other[seat] for seat in Seat))
