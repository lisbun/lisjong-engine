import unittest

from _round_fixtures import (
    daiminkan_action,
    dealt_state,
    draw_and_discard,
    has_action_of_type,
    resolve_all_pass,
    resolve_with,
    tile_type,
)

from lisjong_engine.legal_action import (
    DaiminkanLegalAction,
    DiscardDeclaration,
    DiscardLegalAction,
)
from lisjong_engine.meld import Daiminkan
from lisjong_engine.reaction import ReactionType
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.seat import Seat

_HANDS = {
    Seat.EAST: (
        "7p",
        "2m",
        "3m",
        "4m",
        "5m",
        "6m",
        "7m",
        "2p",
        "3p",
        "4p",
        "5s",
        "6s",
        "7s",
    ),
    Seat.SOUTH: (
        "7p",
        "8s",
        "8m",
        "8m",
        "8m",
        "8m",
        "1z",
        "2z",
        "3z",
        "4z",
        "9p",
        "6z",
        "7z",
    ),
    Seat.WEST: (
        "2m",
        "3m",
        "4m",
        "5m",
        "6m",
        "7m",
        "2p",
        "3p",
        "4p",
        "5p",
        "6p",
        "2s",
        "2s",
    ),
    Seat.NORTH: (
        "7p",
        "7p",
        "1m",
        "9m",
        "1s",
        "9s",
        "1z",
        "2z",
        "3z",
        "4z",
        "5z",
        "5z",
        "5z",
    ),
}
_DRAWS = ("8s", "5z")


def _ippatsu_before_daiminkan_state():
    """EASTの立直一発中にSOUTHが5zを捨て、NORTHが大明槓できる局面。"""
    state = dealt_state(hands=_HANDS, draws=_DRAWS, with_dead_wall=True)

    state.draw(Seat.EAST)
    snapshot = state.legal_actions(Seat.EAST)
    seven_pin = next(
        tile
        for tile in state.hand_tiles(Seat.EAST)
        if tile.tile_type == tile_type("7p")
    )
    state.apply(
        Seat.EAST,
        DiscardLegalAction(seven_pin.id, DiscardDeclaration.RIICHI),
        expected_revision=snapshot.revision,
    )
    resolve_all_pass(state)

    draw_and_discard(state, Seat.SOUTH, "5z")
    return state


class RoundStateDaiminkanIppatsuRegressionTest(unittest.TestCase):
    def test_a_daiminkan_cancels_ippatsu_on_confirmation(self) -> None:
        state = _ippatsu_before_daiminkan_state()

        self.assertTrue(state.is_riichi_established(Seat.EAST))
        self.assertTrue(state.is_ippatsu(Seat.EAST))
        self.assertIs(state.phase, RoundPhase.AWAITING_REACTIONS)
        self.assertTrue(has_action_of_type(state, Seat.NORTH, DaiminkanLegalAction))
        revision = state.revision

        resolution = resolve_with(
            state,
            {Seat.NORTH: daiminkan_action(state, Seat.NORTH)},
        )

        self.assertIs(resolution.resolved_type, ReactionType.DAIMINKAN)
        self.assertFalse(state.is_ippatsu(Seat.EAST))
        self.assertIs(state.phase, RoundPhase.AWAITING_RINSHAN_DRAW)
        self.assertIs(state.current_seat, Seat.NORTH)
        self.assertEqual(len(state.melds(Seat.NORTH)), 1)
        self.assertIsInstance(state.melds(Seat.NORTH)[0], Daiminkan)
        self.assertEqual(state.revision, revision + 1)


if __name__ == "__main__":
    unittest.main()
