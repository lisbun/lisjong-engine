import unittest

from lisjong_engine.round_phase import RoundPhase


class RoundPhaseTest(unittest.TestCase):
    def test_covers_the_expected_round_phases(self) -> None:
        self.assertEqual(
            tuple((phase.name, phase.value) for phase in RoundPhase),
            (
                ("UNDEALT", "undealt"),
                ("AWAITING_DRAW", "awaiting_draw"),
                ("AWAITING_DISCARD", "awaiting_discard"),
                ("AWAITING_RIICHI_DISCARD", "awaiting_riichi_discard"),
                ("AWAITING_RINSHAN_DRAW", "awaiting_rinshan_draw"),
                ("AWAITING_REACTIONS", "awaiting_reactions"),
                ("AWAITING_KAKAN_REACTIONS", "awaiting_kakan_reactions"),
                ("AWAITING_ANKAN_REACTIONS", "awaiting_ankan_reactions"),
                ("AWAITING_WIN_FINALIZATION", "awaiting_win_finalization"),
                ("FINISHED", "finished"),
            ),
        )

    def test_values_are_unique(self) -> None:
        values = tuple(phase.value for phase in RoundPhase)

        self.assertEqual(len(set(values)), len(values))


if __name__ == "__main__":
    unittest.main()
