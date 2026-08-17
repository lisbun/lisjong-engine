import unittest
from dataclasses import FrozenInstanceError, replace
from unittest.mock import patch

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
from lisjong_engine.round_phase import RoundPhase
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


class StartRoundTest(unittest.TestCase):
    def test_returns_a_dealt_round_state_and_transitions_phase(self) -> None:
        match = MatchState(seed=1)

        round_state = match.start_round()

        self.assertIs(round_state.phase, RoundPhase.AWAITING_DRAW)
        self.assertIs(round_state.current_seat, Seat.EAST)
        self.assertIs(match.phase, MatchPhase.ROUND_IN_PROGRESS)
        self.assertIs(match.active_round, round_state)

    def test_first_start_sets_round_ordinal_to_one(self) -> None:
        match = MatchState(seed=1)
        match.start_round()

        self.assertEqual(match._started_round_count, 1)
        self.assertIsNotNone(match._active_round_random_provenance)
        self.assertEqual(match._active_round_random_provenance.round_ordinal, 1)
        self.assertEqual(match._active_round_random_provenance.match_seed, 1)

    def test_does_not_mutate_scores_position_history_or_completed_match(
        self,
    ) -> None:
        match = MatchState(seed=1)
        scores_before = match.scores
        position_before = match.position

        match.start_round()

        self.assertEqual(match.scores, scores_before)
        self.assertEqual(match.position, position_before)
        self.assertEqual(match.history, ())
        self.assertIsNone(match.completed_match)

    def test_rejects_second_start_while_round_in_progress(self) -> None:
        match = MatchState(seed=1)
        first_round = match.start_round()

        with self.assertRaises(RuntimeError):
            match.start_round()

        self.assertIs(match.active_round, first_round)
        self.assertEqual(match._started_round_count, 1)

    def test_rejects_start_when_finished(self) -> None:
        match = MatchState(seed=1)
        match._phase = MatchPhase.FINISHED

        with self.assertRaises(RuntimeError):
            match.start_round()

    def test_same_seed_produces_identical_deal(self) -> None:
        first = MatchState(seed=123)
        second = MatchState(seed=123)

        first_round = first.start_round()
        second_round = second.start_round()

        for seat in Seat:
            self.assertEqual(
                first_round.hand_tiles(seat),
                second_round.hand_tiles(seat),
            )
        self.assertEqual(
            first_round.remaining_tiles,
            second_round.remaining_tiles,
        )
        self.assertEqual(
            first_round.dead_wall_tiles,
            second_round.dead_wall_tiles,
        )

    def test_different_seed_produces_a_different_deal(self) -> None:
        first = MatchState(seed=1)
        second = MatchState(seed=2)

        first_round = first.start_round()
        second_round = second.start_round()

        self.assertNotEqual(
            tuple(first_round.hand_tiles(seat) for seat in Seat),
            tuple(second_round.hand_tiles(seat) for seat in Seat),
        )

    def test_round_start_points_snapshot_matches_starting_scores(self) -> None:
        starting_scores = {
            Seat.EAST: 30_000,
            Seat.SOUTH: 25_000,
            Seat.WEST: 25_000,
            Seat.NORTH: 20_000,
        }
        match = MatchState(seed=1, starting_scores=starting_scores)

        round_state = match.start_round()

        self.assertEqual(dict(round_state.round_start_points), starting_scores)
        self.assertEqual(
            match.scores,
            SeatPoints(30_000, 25_000, 25_000, 20_000),
        )

    def test_dealer_prevailing_wind_and_rules_propagate_to_the_active_round(
        self,
    ) -> None:
        rules = RuleSet.default()
        match = MatchState(seed=1, rules=rules)

        round_state = match.start_round()

        self.assertIs(round_state.dealer_seat, Seat.EAST)
        self.assertIs(round_state.prevailing_wind, Wind.EAST)
        self.assertEqual(round_state.rules, rules)

    def test_failed_wall_creation_leaves_match_state_untouched(self) -> None:
        match = MatchState(seed=1)

        with patch(
            "lisjong_engine.match_state.create_round_wall",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                match.start_round()

        self.assertIs(match.phase, MatchPhase.AWAITING_ROUND)
        self.assertIsNone(match.active_round)
        self.assertEqual(match.history, ())
        self.assertEqual(
            match.scores,
            SeatPoints(
                match.rules.starting_points,
                match.rules.starting_points,
                match.rules.starting_points,
                match.rules.starting_points,
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
        self.assertEqual(match._started_round_count, 0)
        self.assertIsNone(match._active_round_random_provenance)

    def test_failed_deal_leaves_match_state_untouched(self) -> None:
        match = MatchState(seed=1)

        with patch(
            "lisjong_engine.round_state.RoundState.deal",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                match.start_round()

        self.assertIs(match.phase, MatchPhase.AWAITING_ROUND)
        self.assertIsNone(match.active_round)
        self.assertEqual(match.history, ())
        self.assertEqual(match._started_round_count, 0)
        self.assertIsNone(match._active_round_random_provenance)


if __name__ == "__main__":
    unittest.main()
