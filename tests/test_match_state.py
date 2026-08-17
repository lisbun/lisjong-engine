import unittest
from dataclasses import FrozenInstanceError, replace

from lisjong_engine.final_score import calculate_final_scores
from lisjong_engine.match_state import (
    CompletedMatch,
    CompletedRound,
    MatchEndReason,
    MatchPhase,
    MatchState,
    RoundPosition,
)
from lisjong_engine.points import SeatPoints
from lisjong_engine.round_allocation import create_round_random_provenance
from lisjong_engine.round_result import ExhaustiveDrawResult
from lisjong_engine.rules import MatchFormat, RuleSet
from lisjong_engine.seat import Seat
from lisjong_engine.settlement import calculate_round_settlement
from lisjong_engine.wind import Wind


class RoundPositionTest(unittest.TestCase):
    def test_east_one_constructs(self) -> None:
        position = RoundPosition(
            prevailing_wind=Wind.EAST,
            hand_number=1,
            dealer_seat=Seat.EAST,
            honba=0,
            riichi_sticks=0,
        )

        self.assertEqual(position.prevailing_wind, Wind.EAST)
        self.assertEqual(position.hand_number, 1)
        self.assertEqual(position.dealer_seat, Seat.EAST)

    def test_south_and_west_positions_construct(self) -> None:
        RoundPosition(
            prevailing_wind=Wind.SOUTH,
            hand_number=2,
            dealer_seat=Seat.SOUTH,
            honba=0,
            riichi_sticks=0,
        )
        RoundPosition(
            prevailing_wind=Wind.WEST,
            hand_number=3,
            dealer_seat=Seat.WEST,
            honba=1,
            riichi_sticks=1,
        )

    def test_rejects_hand_number_out_of_range(self) -> None:
        for hand_number in (0, 5):
            with self.subTest(hand_number=hand_number):
                with self.assertRaises(ValueError):
                    RoundPosition(
                        prevailing_wind=Wind.EAST,
                        hand_number=hand_number,
                        dealer_seat=Seat.EAST,
                        honba=0,
                        riichi_sticks=0,
                    )

    def test_rejects_non_int_hand_number(self) -> None:
        for hand_number in (True, 1.0, "1"):
            with self.subTest(hand_number=hand_number):
                with self.assertRaises(TypeError):
                    RoundPosition(
                        prevailing_wind=Wind.EAST,
                        hand_number=hand_number,
                        dealer_seat=Seat.EAST,
                        honba=0,
                        riichi_sticks=0,
                    )

    def test_rejects_negative_honba(self) -> None:
        with self.assertRaises(ValueError):
            RoundPosition(
                prevailing_wind=Wind.EAST,
                hand_number=1,
                dealer_seat=Seat.EAST,
                honba=-1,
                riichi_sticks=0,
            )

    def test_rejects_negative_riichi_sticks(self) -> None:
        with self.assertRaises(ValueError):
            RoundPosition(
                prevailing_wind=Wind.EAST,
                hand_number=1,
                dealer_seat=Seat.EAST,
                honba=0,
                riichi_sticks=-1,
            )

    def test_rejects_north_prevailing_wind(self) -> None:
        with self.assertRaises(ValueError):
            RoundPosition(
                prevailing_wind=Wind.NORTH,
                hand_number=4,
                dealer_seat=Seat.NORTH,
                honba=0,
                riichi_sticks=0,
            )

    def test_rejects_dealer_seat_inconsistent_with_hand_number(self) -> None:
        with self.assertRaises(ValueError):
            RoundPosition(
                prevailing_wind=Wind.EAST,
                hand_number=2,
                dealer_seat=Seat.EAST,
                honba=0,
                riichi_sticks=0,
            )

    def test_is_immutable(self) -> None:
        position = RoundPosition(
            prevailing_wind=Wind.EAST,
            hand_number=1,
            dealer_seat=Seat.EAST,
            honba=0,
            riichi_sticks=0,
        )
        with self.assertRaises(FrozenInstanceError):
            position.honba = 1


class MatchPhaseAndEndReasonTest(unittest.TestCase):
    def test_match_phase_has_the_expected_members(self) -> None:
        self.assertEqual(
            {member.name for member in MatchPhase},
            {"AWAITING_ROUND", "ROUND_IN_PROGRESS", "FINISHED"},
        )

    def test_match_end_reason_has_the_expected_members(self) -> None:
        self.assertEqual(
            {member.name for member in MatchEndReason},
            {
                "BANKRUPTCY",
                "DEALER_WIN",
                "DEALER_TENPAI",
                "TARGET_REACHED",
                "FINAL_ROUND",
            },
        )

    def test_match_end_reason_does_not_include_legacy_members(self) -> None:
        member_names = {member.name for member in MatchEndReason}
        self.assertNotIn("RETURN_POINTS", member_names)
        self.assertNotIn("MANUAL", member_names)


class MatchStateDefaultInitializationTest(unittest.TestCase):
    def test_initializes_with_default_rules_and_starting_points(self) -> None:
        match = MatchState(seed=1)
        rules = RuleSet.default()

        self.assertEqual(
            match.scores,
            SeatPoints(
                rules.starting_points,
                rules.starting_points,
                rules.starting_points,
                rules.starting_points,
            ),
        )
        self.assertEqual(
            match.position,
            RoundPosition(
                prevailing_wind=Wind.EAST,
                hand_number=1,
                dealer_seat=Seat.EAST,
                honba=0,
                riichi_sticks=0,
            ),
        )
        self.assertIs(match.phase, MatchPhase.AWAITING_ROUND)
        self.assertIsNone(match.active_round)
        self.assertEqual(match.history, ())
        self.assertIsNone(match.completed_match)
        self.assertEqual(match.match_seed, 1)
        self.assertEqual(match.rules, rules)


class MatchStateValidationTest(unittest.TestCase):
    def test_rejects_bool_seed(self) -> None:
        with self.assertRaises(TypeError):
            MatchState(seed=True)

    def test_rejects_non_int_seed(self) -> None:
        for seed in (1.0, "1", None):
            with self.subTest(seed=seed):
                with self.assertRaises(TypeError):
                    MatchState(seed=seed)

    def test_unsupported_player_count_and_match_format_cannot_be_constructed(
        self,
    ) -> None:
        # `RuleSet.__post_init__`自体が既に`player_count != 4`を拒否し、
        # `MatchFormat`は現時点でHANCHANしか定義していない。既存`RuleSet`
        # contractを壊してまでunsupportedなfixtureを注入する手段がないため、
        # ここではその前提（MatchState側の同種checkが到達しない理由）だけを
        # 固定する。
        with self.assertRaises(ValueError):
            replace(RuleSet.default(), player_count=3, uma=(30, 10, -40))
        self.assertEqual(tuple(MatchFormat), (MatchFormat.HANCHAN,))

    def test_rejects_incomplete_starting_score_mapping(self) -> None:
        with self.assertRaises(ValueError):
            MatchState(
                seed=1,
                starting_scores={
                    Seat.EAST: 25_000,
                    Seat.SOUTH: 25_000,
                    Seat.WEST: 25_000,
                },
            )

    def test_rejects_invalid_score_mapping_value_type(self) -> None:
        with self.assertRaises(TypeError):
            MatchState(
                seed=1,
                starting_scores={
                    Seat.EAST: 25_000,
                    Seat.SOUTH: 25_000,
                    Seat.WEST: 25_000,
                    Seat.NORTH: True,
                },
            )


class MatchStateExplicitStartingScoresTest(unittest.TestCase):
    def test_explicit_starting_scores_become_authoritative_scores(self) -> None:
        scores = {
            Seat.EAST: 30_000,
            Seat.SOUTH: 25_000,
            Seat.WEST: 25_000,
            Seat.NORTH: 20_000,
        }
        match = MatchState(seed=1, starting_scores=scores)

        self.assertEqual(
            match.scores,
            SeatPoints(30_000, 25_000, 25_000, 20_000),
        )

    def test_accepts_a_seat_points_instance_directly(self) -> None:
        scores = SeatPoints(30_000, 25_000, 25_000, 20_000)
        match = MatchState(seed=1, starting_scores=scores)

        self.assertEqual(match.scores, scores)


class CompletedRoundAndCompletedMatchTest(unittest.TestCase):
    def _completed_round(
        self, *, next_position: RoundPosition | None
    ) -> CompletedRound:
        rules = RuleSet.default()
        position_before = RoundPosition(
            prevailing_wind=Wind.EAST,
            hand_number=1,
            dealer_seat=Seat.EAST,
            honba=0,
            riichi_sticks=0,
        )
        result = ExhaustiveDrawResult()
        settlement = calculate_round_settlement(
            result,
            dealer_seat=Seat.EAST,
            rules=rules,
        )
        return CompletedRound(
            random_provenance=create_round_random_provenance(1, 1),
            position_before=position_before,
            result=result,
            settlement=settlement,
            scores_after_settlement=SeatPoints(
                rules.starting_points,
                rules.starting_points,
                rules.starting_points,
                rules.starting_points,
            ),
            dealer_continues=True,
            next_position=next_position,
        )

    def test_completed_round_accepts_none_next_position(self) -> None:
        completed_round = self._completed_round(next_position=None)
        self.assertIsNone(completed_round.next_position)

    def test_completed_round_is_immutable(self) -> None:
        completed_round = self._completed_round(next_position=None)
        with self.assertRaises(FrozenInstanceError):
            completed_round.dealer_continues = False

    def test_completed_match_holds_history_as_a_tuple(self) -> None:
        completed_round = self._completed_round(
            next_position=RoundPosition(
                prevailing_wind=Wind.EAST,
                hand_number=2,
                dealer_seat=Seat.SOUTH,
                honba=1,
                riichi_sticks=0,
            )
        )
        rules = RuleSet.default()
        final_raw_scores = SeatPoints(
            rules.starting_points,
            rules.starting_points,
            rules.starting_points,
            rules.starting_points,
        )
        final_score = calculate_final_scores(
            final_raw_scores.as_dict(),
            rules=rules,
        )

        completed_match = CompletedMatch(
            end_reason=MatchEndReason.FINAL_ROUND,
            final_riichi_stick_awards=(),
            final_raw_scores=final_raw_scores,
            final_score=final_score,
            history=[completed_round],
        )

        self.assertIsInstance(completed_match.history, tuple)
        self.assertEqual(completed_match.history, (completed_round,))


if __name__ == "__main__":
    unittest.main()
