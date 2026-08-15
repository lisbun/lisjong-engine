from enum import Enum


class Wind(Enum):
    """場風・自風。座席そのものを表す`Seat`とは別概念として扱う。"""

    EAST = "east"
    SOUTH = "south"
    WEST = "west"
    NORTH = "north"

    def next(self) -> "Wind":
        winds = tuple(Wind)
        index = winds.index(self)
        return winds[(index + 1) % len(winds)]
