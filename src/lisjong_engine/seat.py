from enum import Enum


class Seat(Enum):
    """卓上の座席。場風・自風を表す`Wind`とは別概念として扱う。"""

    EAST = "east"
    SOUTH = "south"
    WEST = "west"
    NORTH = "north"

    def next(self) -> "Seat":
        """反時計回りの次の席を返す。turn進行と下家判定に使う。"""
        seats = tuple(Seat)
        index = seats.index(self)
        return seats[(index + 1) % len(seats)]
