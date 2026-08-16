import unittest

from lisjong_engine.legal_action import DiscardLegalAction
from lisjong_engine.legal_actions import derive_discard_actions, derive_legal_actions
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.seat import Seat
from lisjong_engine.tile import STANDARD_TILES, Tile, TileCategory, TileType

_TILE_CATEGORIES = {
    "m": TileCategory.MANZU,
    "p": TileCategory.PINZU,
    "s": TileCategory.SOUZU,
    "z": TileCategory.HONOR,
}


def _tile_type(name: str) -> TileType:
    return TileType(_TILE_CATEGORIES[name[-1]], int(name[:-1]))


def _tiles(*names: str) -> tuple[Tile, ...]:
    copy_counts: dict[TileType, int] = {}
    tiles = []

    for name in names:
        tile_type = _tile_type(name)
        copy_index = copy_counts.get(tile_type, 0)
        tiles.append(STANDARD_TILES[tile_type.id * 4 + copy_index])
        copy_counts[tile_type] = copy_index + 1

    return tuple(tiles)


class DeriveLegalActionsTest(unittest.TestCase):
    def _derive(
        self,
        *,
        phase: RoundPhase = RoundPhase.AWAITING_DISCARD,
        seat: Seat = Seat.EAST,
        current_seat: Seat | None = Seat.EAST,
        hand_tiles: tuple[Tile, ...] = (),
    ) -> tuple:
        return derive_legal_actions(
            phase=phase,
            seat=seat,
            current_seat=current_seat,
            hand_tiles=hand_tiles,
        )

    def test_lists_every_hand_tile_as_a_discard_candidate(self) -> None:
        hand_tiles = _tiles("1m", "2m", "3m")

        actions = self._derive(hand_tiles=hand_tiles)

        self.assertEqual(
            actions,
            tuple(DiscardLegalAction(tile.id) for tile in hand_tiles),
        )

    def test_keeps_physical_identity_for_tiles_of_the_same_type(self) -> None:
        hand_tiles = _tiles("5m", "5m")

        actions = self._derive(hand_tiles=hand_tiles)

        self.assertEqual(len(actions), 2)
        self.assertEqual(
            tuple(action.tile_id for action in actions),
            (hand_tiles[0].id, hand_tiles[1].id),
        )

    def test_only_candidates_from_the_hand_are_generated(self) -> None:
        hand_tiles = _tiles("1m", "2m")

        actions = self._derive(hand_tiles=hand_tiles)

        self.assertNotIn(DiscardLegalAction(_tiles("9s")[0].id), actions)

    def test_ordering_is_deterministic_by_physical_tile_id(self) -> None:
        hand_tiles = _tiles("9s", "1m", "5p")
        reversed_hand_tiles = tuple(reversed(hand_tiles))

        actions = self._derive(hand_tiles=hand_tiles)
        reversed_actions = self._derive(hand_tiles=reversed_hand_tiles)

        expected_tile_ids = tuple(sorted(tile.id for tile in hand_tiles))
        self.assertEqual(
            tuple(action.tile_id for action in actions),
            expected_tile_ids,
        )
        self.assertEqual(actions, reversed_actions)

    def test_does_not_generate_duplicate_actions(self) -> None:
        hand_tiles = _tiles("1m", "1m", "1m", "1m")

        actions = self._derive(hand_tiles=hand_tiles)

        self.assertEqual(len(set(actions)), len(actions))

    def test_returns_nothing_for_a_seat_that_is_not_the_current_seat(self) -> None:
        actions = self._derive(
            seat=Seat.SOUTH,
            current_seat=Seat.EAST,
            hand_tiles=_tiles("1m", "2m"),
        )

        self.assertEqual(actions, ())

    def test_returns_nothing_outside_the_discard_phase(self) -> None:
        for phase in RoundPhase:
            if phase is RoundPhase.AWAITING_DISCARD:
                continue
            with self.subTest(phase=phase):
                self.assertEqual(
                    self._derive(phase=phase, hand_tiles=_tiles("1m")),
                    (),
                )

    def test_does_not_generate_reaction_or_special_actions(self) -> None:
        actions = self._derive(hand_tiles=_tiles("1m", "1m", "1m", "1m"))

        self.assertTrue(
            all(isinstance(action, DiscardLegalAction) for action in actions)
        )

    def test_never_declares_riichi_in_this_scope(self) -> None:
        tenpai_hand = _tiles(
            "1m",
            "1m",
            "1m",
            "2m",
            "3m",
            "4m",
            "5m",
            "6m",
            "7m",
            "8m",
            "9m",
            "9m",
            "9m",
            "1p",
        )

        actions = self._derive(hand_tiles=tenpai_hand)

        self.assertTrue(all(action.declaration.value == "none" for action in actions))

    def test_rejects_invalid_argument_types(self) -> None:
        with self.assertRaises(TypeError):
            self._derive(phase="awaiting_discard")
        with self.assertRaises(TypeError):
            self._derive(seat="east")
        with self.assertRaises(TypeError):
            self._derive(current_seat="east")
        with self.assertRaises(TypeError):
            self._derive(hand_tiles=("1m",))

    def test_derive_discard_actions_is_side_effect_free(self) -> None:
        hand_tiles = _tiles("1m", "2m")

        first = derive_discard_actions(hand_tiles)
        second = derive_discard_actions(hand_tiles)

        self.assertEqual(first, second)
        self.assertEqual(hand_tiles, _tiles("1m", "2m"))


if __name__ == "__main__":
    unittest.main()
