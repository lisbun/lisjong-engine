from enum import Enum


class Seat(Enum):
    """卓上の座席。場風・自風を表す`Wind`とは別概念として扱う。"""

    EAST = "east"
    SOUTH = "south"
    WEST = "west"
    NORTH = "north"
