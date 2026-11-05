"""立直後の見逃しが、同じ待ち・別の待ちへのロンを継続して禁じる。"""

import unittest

from _round_fixtures import (
    QUIET_HANDS,
    dealt_state,
    draw_and_discard,
    has_action_of_type,
    resolve_all_pass,
)

from lisjong_engine.furiten import FuritenReason
from lisjong_engine.legal_action import RonLegalAction
from lisjong_engine.seat import Seat


class RiichiPassedTileRulesTest(unittest.TestCase):
    def test_missed_ron_blocks_both_waits_after_own_draw(self) -> None:
        for first, later in (("5s", "5s"), ("5s", "8s"), ("8s", "5s")):
            with self.subTest(first=first, later=later):
                # 234m 567m 234p 99p 67s: 5s/8s待ち。河フリテンはない。
                hands = {
                    **QUIET_HANDS,
                    Seat.EAST: (
                        "2m",
                        "3m",
                        "4m",
                        "5m",
                        "6m",
                        "7m",
                        "2p",
                        "3p",
                        "4p",
                        "9p",
                        "9p",
                        "6s",
                        "7s",
                    ),
                }
                state = dealt_state(
                    hands=hands,
                    draws=("5z", first, "6z", "6z", "6z", later),
                    with_dead_wall=True,
                )
                draw_and_discard(state, Seat.EAST, declares_riichi=True)
                if state.reacting_seats:
                    resolve_all_pass(state)
                self.assertTrue(state.is_riichi_established(Seat.EAST))

                draw_and_discard(state, Seat.SOUTH)
                # 各待ちが見逃し前には実際にロン可能であることも確認する。
                self.assertTrue(has_action_of_type(state, Seat.EAST, RonLegalAction))
                resolve_all_pass(state)
                self.assertEqual(
                    state.furiten_reasons(Seat.EAST),
                    frozenset({FuritenReason.RIICHI}),
                )

                for seat in (Seat.WEST, Seat.NORTH, Seat.EAST):
                    draw_and_discard(state, seat)
                    if state.reacting_seats:
                        resolve_all_pass(state)
                self.assertEqual(
                    state.furiten_reasons(Seat.EAST),
                    frozenset({FuritenReason.RIICHI}),
                )
                draw_and_discard(state, Seat.SOUTH)
                self.assertFalse(has_action_of_type(state, Seat.EAST, RonLegalAction))


if __name__ == "__main__":
    unittest.main()
