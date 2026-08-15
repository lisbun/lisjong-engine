from collections.abc import Iterable
from dataclasses import dataclass

from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile


@dataclass(frozen=True)
class Discard:
    tile: Tile
    is_tsumogiri: bool
    called_by: Seat | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.tile, Tile):
            raise TypeError("tile must be a Tile")
        if type(self.is_tsumogiri) is not bool:
            raise TypeError("is_tsumogiri must be a bool")
        if self.called_by is not None and not isinstance(self.called_by, Seat):
            raise TypeError("called_by must be a Seat or None")


class River:
    def __init__(self, discards: Iterable[Discard] = ()) -> None:
        discard_sequence = tuple(discards)
        if any(not isinstance(discard, Discard) for discard in discard_sequence):
            raise TypeError("discards must contain only Discard instances")

        tile_ids = tuple(discard.tile.id for discard in discard_sequence)
        if len(set(tile_ids)) != len(tile_ids):
            raise ValueError("discards must not contain duplicate physical tile IDs")

        self._discards = discard_sequence

    @property
    def count(self) -> int:
        return len(self._discards)

    @property
    def discards(self) -> tuple[Discard, ...]:
        return self._discards

    def add(self, discard: Discard) -> None:
        if not isinstance(discard, Discard):
            raise TypeError("discard must be a Discard")
        if any(
            existing_discard.tile.id == discard.tile.id
            for existing_discard in self._discards
        ):
            raise ValueError("river must not contain duplicate physical tile IDs")

        self._discards = (*self._discards, discard)

    def mark_called(self, tile_id: int, caller: Seat) -> Discard:
        if type(tile_id) is not int:
            raise TypeError("tile_id must be an int")
        if not isinstance(caller, Seat):
            raise TypeError("caller must be a Seat")

        for index, discard in enumerate(self._discards):
            if discard.tile.id != tile_id:
                continue
            if discard.called_by is not None:
                raise ValueError("discard has already been called")

            called_discard = Discard(
                discard.tile,
                discard.is_tsumogiri,
                called_by=caller,
            )
            self._discards = (
                *self._discards[:index],
                called_discard,
                *self._discards[index + 1 :],
            )
            return called_discard

        raise ValueError("tile_id is not in river")
