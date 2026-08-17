import unittest
from dataclasses import FrozenInstanceError, replace
from unittest.mock import PropertyMock, patch

from lisjong_engine.dora import DoraIndicators
from lisjong_engine.final_score import calculate_final_scores
from lisjong_engine.match_state import (
    CompletedMatch,
    CompletedRound,
    MatchEndReason,
    MatchPhase,
    MatchState,
    RoundPosition,
    _bankrupt_seats,
    _dealer_continues,
    _first_place_seat,
    _match_end_reason,
    _next_round_position,
)
from lisjong_engine.points import SeatPoints
from lisjong_engine.riichi_event import RiichiContribution
from lisjong_engine.round_allocation import create_round_random_provenance
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.round_result import (
    AbortiveDrawReason,
    AbortiveDrawResult,
    ExhaustiveDrawResult,
    WinningPlayerResult,
    WinResult,
)
from lisjong_engine.round_state import RoundState
from lisjong_engine.rules import FinalRankTiePolicy, MatchFormat, RuleSet
from lisjong_engine.seat import Seat
from lisjong_engine.settlement import calculate_round_settlement
from lisjong_engine.tile import STANDARD_TILES
from lisjong_engine.win_context import WinMethod, WinningContext, WinOrigin
from lisjong_engine.wind import Wind
from lisjong_engine.winning_score import evaluate_winning_scores


def _finish_round(round_state: RoundState, result) -> None:
    """testのためだけに、既に開始済みのRoundStateを終局済みfactへ直接進める。

    実際の対局進行（打牌・鳴き・立直・和了・流局判定）を再現するのは
    MatchState境界のtestとして過度に複雑なため、Issue #24第5段階の
    レビュー方針に従い、production APIへterminal専用のtest-only hookを
    追加する代わりにprivate fieldを直接書き換える。RoundState自身の
    終局contractは別途RoundState向けtestで検証済み。
    """
    round_state._phase = RoundPhase.FINISHED
    round_state._result = result


def _seat_wind(seat: Seat, dealer_seat: Seat) -> Wind:
    seats = tuple(Seat)
    distance = (seats.index(seat) - seats.index(dealer_seat)) % len(seats)
    return tuple(Wind)[distance]


def _winning_player(
    seat: Seat,
    *,
    method: WinMethod,
    dealer_seat: Seat = Seat.EAST,
    rules: RuleSet | None = None,
) -> WinningPlayerResult:
    concealed_tiles = tuple(
        STANDARD_TILES[tile_type_id * 4 + copy_index]
        for tile_type_id in (0, 3, 6, 10, 14, 16, 20)
        for copy_index in range(2)
    )
    winning_tile = concealed_tiles[-1]

    context = WinningContext(
        concealed_tiles=concealed_tiles,
        winning_tile=winning_tile,
        method=method,
        origin=(WinOrigin.DISCARD if method is WinMethod.RON else WinOrigin.LIVE_WALL),
        seat_wind=_seat_wind(seat, dealer_seat),
        prevailing_wind=Wind.EAST,
    )

    return WinningPlayerResult(
        seat=seat,
        context=context,
        score_selection=evaluate_winning_scores(
            context,
            dora_indicators=DoraIndicators(),
            rules=rules,
        ),
    )


def _win_result(
    winner_seats: tuple[Seat, ...],
    *,
    method: WinMethod,
    dealer_seat: Seat = Seat.EAST,
    source_seat: Seat | None = None,
    rules: RuleSet | None = None,
) -> WinResult:
    winners = tuple(
        _winning_player(seat, method=method, dealer_seat=dealer_seat, rules=rules)
        for seat in winner_seats
    )
    return WinResult(
        method=method,
        origin=(WinOrigin.DISCARD if method is WinMethod.RON else WinOrigin.LIVE_WALL),
        winning_tile=winners[0].context.winning_tile,
        winners=winners,
        dora_indicators=DoraIndicators(),
        source_seat=source_seat,
    )


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


class DealerContinuesTest(unittest.TestCase):
    def test_dealer_win_continues(self) -> None:
        result = _win_result(
            (Seat.EAST,),
            method=WinMethod.TSUMO,
            dealer_seat=Seat.EAST,
        )
        self.assertTrue(_dealer_continues(result, Seat.EAST))

    def test_child_win_does_not_continue(self) -> None:
        result = _win_result(
            (Seat.SOUTH,),
            method=WinMethod.RON,
            dealer_seat=Seat.EAST,
            source_seat=Seat.EAST,
        )
        self.assertFalse(_dealer_continues(result, Seat.EAST))

    def test_multiple_ron_with_dealer_among_winners_continues(self) -> None:
        result = _win_result(
            (Seat.EAST, Seat.SOUTH),
            method=WinMethod.RON,
            dealer_seat=Seat.EAST,
            source_seat=Seat.WEST,
        )
        self.assertTrue(_dealer_continues(result, Seat.EAST))

    def test_exhaustive_draw_dealer_tenpai_continues(self) -> None:
        result = ExhaustiveDrawResult(tenpai_seats=(Seat.EAST,))
        self.assertTrue(_dealer_continues(result, Seat.EAST))

    def test_exhaustive_draw_dealer_noten_does_not_continue(self) -> None:
        result = ExhaustiveDrawResult(tenpai_seats=(Seat.SOUTH,))
        self.assertFalse(_dealer_continues(result, Seat.EAST))

    def test_abortive_draw_always_continues(self) -> None:
        result = AbortiveDrawResult(AbortiveDrawReason.FOUR_KANS)
        self.assertTrue(_dealer_continues(result, Seat.EAST))

    def test_rejects_invalid_result(self) -> None:
        with self.assertRaises(TypeError):
            _dealer_continues("not-a-result", Seat.EAST)

    def test_rejects_invalid_dealer_seat(self) -> None:
        result = ExhaustiveDrawResult(tenpai_seats=(Seat.EAST,))
        with self.assertRaises(TypeError):
            _dealer_continues(result, "east")


class NextRoundPositionTest(unittest.TestCase):
    def test_dealer_win_keeps_hand_and_increments_honba(self) -> None:
        position = RoundPosition(
            prevailing_wind=Wind.EAST,
            hand_number=1,
            dealer_seat=Seat.EAST,
            honba=2,
            riichi_sticks=3,
        )
        result = _win_result(
            (Seat.EAST,),
            method=WinMethod.TSUMO,
            dealer_seat=Seat.EAST,
        )

        next_position = _next_round_position(
            position,
            result,
            True,
            riichi_sticks=5,
        )

        self.assertEqual(
            next_position,
            RoundPosition(
                prevailing_wind=Wind.EAST,
                hand_number=1,
                dealer_seat=Seat.EAST,
                honba=3,
                riichi_sticks=5,
            ),
        )

    def test_dealer_tenpai_draw_keeps_hand_and_increments_honba(self) -> None:
        position = RoundPosition(
            prevailing_wind=Wind.EAST,
            hand_number=1,
            dealer_seat=Seat.EAST,
            honba=0,
            riichi_sticks=0,
        )
        result = ExhaustiveDrawResult(tenpai_seats=(Seat.EAST,))

        next_position = _next_round_position(
            position,
            result,
            True,
            riichi_sticks=0,
        )

        self.assertEqual(
            next_position,
            RoundPosition(
                prevailing_wind=Wind.EAST,
                hand_number=1,
                dealer_seat=Seat.EAST,
                honba=1,
                riichi_sticks=0,
            ),
        )

    def test_abortive_draw_keeps_hand_and_increments_honba(self) -> None:
        position = RoundPosition(
            prevailing_wind=Wind.EAST,
            hand_number=1,
            dealer_seat=Seat.EAST,
            honba=0,
            riichi_sticks=1,
        )
        result = AbortiveDrawResult(AbortiveDrawReason.FOUR_KANS)

        next_position = _next_round_position(
            position,
            result,
            True,
            riichi_sticks=1,
        )

        self.assertEqual(
            next_position,
            RoundPosition(
                prevailing_wind=Wind.EAST,
                hand_number=1,
                dealer_seat=Seat.EAST,
                honba=1,
                riichi_sticks=1,
            ),
        )

    def test_child_win_rotates_dealer_and_resets_honba(self) -> None:
        position = RoundPosition(
            prevailing_wind=Wind.EAST,
            hand_number=1,
            dealer_seat=Seat.EAST,
            honba=3,
            riichi_sticks=0,
        )
        result = _win_result(
            (Seat.SOUTH,),
            method=WinMethod.RON,
            dealer_seat=Seat.EAST,
            source_seat=Seat.EAST,
        )

        next_position = _next_round_position(
            position,
            result,
            False,
            riichi_sticks=0,
        )

        self.assertEqual(
            next_position,
            RoundPosition(
                prevailing_wind=Wind.EAST,
                hand_number=2,
                dealer_seat=Seat.SOUTH,
                honba=0,
                riichi_sticks=0,
            ),
        )

    def test_dealer_noten_draw_rotates_dealer_and_increments_honba(self) -> None:
        position = RoundPosition(
            prevailing_wind=Wind.EAST,
            hand_number=1,
            dealer_seat=Seat.EAST,
            honba=3,
            riichi_sticks=0,
        )
        result = ExhaustiveDrawResult(tenpai_seats=(Seat.SOUTH,))

        next_position = _next_round_position(
            position,
            result,
            False,
            riichi_sticks=0,
        )

        self.assertEqual(
            next_position,
            RoundPosition(
                prevailing_wind=Wind.EAST,
                hand_number=2,
                dealer_seat=Seat.SOUTH,
                honba=4,
                riichi_sticks=0,
            ),
        )

    def test_east_four_flows_into_south_one(self) -> None:
        position = RoundPosition(
            prevailing_wind=Wind.EAST,
            hand_number=4,
            dealer_seat=Seat.NORTH,
            honba=0,
            riichi_sticks=0,
        )

        child_win = _win_result(
            (Seat.EAST,),
            method=WinMethod.RON,
            dealer_seat=Seat.NORTH,
            source_seat=Seat.SOUTH,
        )
        next_after_win = _next_round_position(
            position,
            child_win,
            False,
            riichi_sticks=0,
        )
        self.assertEqual(
            next_after_win,
            RoundPosition(
                prevailing_wind=Wind.SOUTH,
                hand_number=1,
                dealer_seat=Seat.EAST,
                honba=0,
                riichi_sticks=0,
            ),
        )

        dealer_noten_draw = ExhaustiveDrawResult(tenpai_seats=(Seat.EAST,))
        next_after_draw = _next_round_position(
            position,
            dealer_noten_draw,
            False,
            riichi_sticks=0,
        )
        self.assertEqual(
            next_after_draw,
            RoundPosition(
                prevailing_wind=Wind.SOUTH,
                hand_number=1,
                dealer_seat=Seat.EAST,
                honba=1,
                riichi_sticks=0,
            ),
        )

    def test_south_four_flows_into_west_one(self) -> None:
        position = RoundPosition(
            prevailing_wind=Wind.SOUTH,
            hand_number=4,
            dealer_seat=Seat.NORTH,
            honba=0,
            riichi_sticks=0,
        )
        result = _win_result(
            (Seat.EAST,),
            method=WinMethod.RON,
            dealer_seat=Seat.NORTH,
            source_seat=Seat.SOUTH,
        )

        next_position = _next_round_position(
            position,
            result,
            False,
            riichi_sticks=0,
        )

        self.assertEqual(
            next_position,
            RoundPosition(
                prevailing_wind=Wind.WEST,
                hand_number=1,
                dealer_seat=Seat.EAST,
                honba=0,
                riichi_sticks=0,
            ),
        )

    def test_west_four_dealer_continuation_stays_on_west_four(self) -> None:
        position = RoundPosition(
            prevailing_wind=Wind.WEST,
            hand_number=4,
            dealer_seat=Seat.NORTH,
            honba=1,
            riichi_sticks=0,
        )
        result = _win_result(
            (Seat.NORTH,),
            method=WinMethod.TSUMO,
            dealer_seat=Seat.NORTH,
        )

        next_position = _next_round_position(
            position,
            result,
            True,
            riichi_sticks=0,
        )

        self.assertEqual(
            next_position,
            RoundPosition(
                prevailing_wind=Wind.WEST,
                hand_number=4,
                dealer_seat=Seat.NORTH,
                honba=2,
                riichi_sticks=0,
            ),
        )

    def test_west_four_dealer_flow_rejects_next_position(self) -> None:
        position = RoundPosition(
            prevailing_wind=Wind.WEST,
            hand_number=4,
            dealer_seat=Seat.NORTH,
            honba=0,
            riichi_sticks=0,
        )
        result = _win_result(
            (Seat.EAST,),
            method=WinMethod.RON,
            dealer_seat=Seat.NORTH,
            source_seat=Seat.SOUTH,
        )

        with self.assertRaises(ValueError):
            _next_round_position(
                position,
                result,
                False,
                riichi_sticks=0,
            )

    def test_riichi_sticks_are_carried_verbatim(self) -> None:
        position = RoundPosition(
            prevailing_wind=Wind.EAST,
            hand_number=1,
            dealer_seat=Seat.EAST,
            honba=0,
            riichi_sticks=0,
        )
        result = _win_result(
            (Seat.EAST,),
            method=WinMethod.TSUMO,
            dealer_seat=Seat.EAST,
        )

        next_position = _next_round_position(
            position,
            result,
            True,
            riichi_sticks=3,
        )

        self.assertEqual(next_position.riichi_sticks, 3)

    def test_rejects_invalid_position(self) -> None:
        result = ExhaustiveDrawResult(tenpai_seats=(Seat.EAST,))
        with self.assertRaises(TypeError):
            _next_round_position(
                "not-a-position",
                result,
                True,
                riichi_sticks=0,
            )

    def test_rejects_invalid_result(self) -> None:
        position = RoundPosition(
            prevailing_wind=Wind.EAST,
            hand_number=1,
            dealer_seat=Seat.EAST,
            honba=0,
            riichi_sticks=0,
        )
        with self.assertRaises(TypeError):
            _next_round_position(
                position,
                "not-a-result",
                True,
                riichi_sticks=0,
            )

    def test_rejects_non_bool_dealer_continues(self) -> None:
        position = RoundPosition(
            prevailing_wind=Wind.EAST,
            hand_number=1,
            dealer_seat=Seat.EAST,
            honba=0,
            riichi_sticks=0,
        )
        result = ExhaustiveDrawResult(tenpai_seats=(Seat.EAST,))
        with self.assertRaises(TypeError):
            _next_round_position(
                position,
                result,
                1,
                riichi_sticks=0,
            )

    def test_rejects_invalid_riichi_sticks(self) -> None:
        position = RoundPosition(
            prevailing_wind=Wind.EAST,
            hand_number=1,
            dealer_seat=Seat.EAST,
            honba=0,
            riichi_sticks=0,
        )
        result = ExhaustiveDrawResult(tenpai_seats=(Seat.EAST,))

        with self.assertRaises(TypeError):
            _next_round_position(
                position,
                result,
                True,
                riichi_sticks=True,
            )
        with self.assertRaises(ValueError):
            _next_round_position(
                position,
                result,
                True,
                riichi_sticks=-1,
            )


class SettleActiveRoundTest(unittest.TestCase):
    def _match_with_finished_round(self, result):
        match = MatchState(seed=1)
        round_state = match.start_round()
        _finish_round(round_state, result)
        return match, round_state

    def test_dealer_noten_exhaustive_draw_flows_dealer_and_increments_honba(
        self,
    ) -> None:
        match, round_state = self._match_with_finished_round(ExhaustiveDrawResult())
        starting_scores = match.scores
        provenance_before = match._active_round_random_provenance

        completed = match.settle_active_round()

        expected_settlement = calculate_round_settlement(
            ExhaustiveDrawResult(),
            dealer_seat=Seat.EAST,
            honba=0,
            riichi_sticks_before=0,
            rules=match.rules,
        )
        self.assertEqual(completed.settlement, expected_settlement)
        self.assertEqual(
            completed.scores_after_settlement,
            starting_scores.add(expected_settlement.point_deltas),
        )
        self.assertFalse(completed.dealer_continues)
        self.assertEqual(
            completed.next_position,
            RoundPosition(
                prevailing_wind=Wind.EAST,
                hand_number=2,
                dealer_seat=Seat.SOUTH,
                honba=1,
                riichi_sticks=0,
            ),
        )
        self.assertIs(completed.random_provenance, provenance_before)
        self.assertEqual(
            completed.position_before,
            RoundPosition(
                prevailing_wind=Wind.EAST,
                hand_number=1,
                dealer_seat=Seat.EAST,
                honba=0,
                riichi_sticks=0,
            ),
        )
        self.assertIs(completed.result, round_state.result)

        self.assertEqual(match.scores, completed.scores_after_settlement)
        self.assertEqual(match.position, completed.next_position)
        self.assertEqual(match.history, (completed,))
        self.assertIs(match.phase, MatchPhase.AWAITING_ROUND)
        self.assertIsNone(match.active_round)
        self.assertIsNone(match._active_round_random_provenance)
        self.assertIsNone(match.completed_match)
        self.assertEqual(match._started_round_count, 1)

    def test_dealer_tenpai_exhaustive_draw_keeps_same_hand_and_increments_honba(
        self,
    ) -> None:
        match, _ = self._match_with_finished_round(
            ExhaustiveDrawResult(tenpai_seats=(Seat.EAST,))
        )

        completed = match.settle_active_round()

        self.assertTrue(completed.dealer_continues)
        self.assertEqual(
            completed.next_position,
            RoundPosition(
                prevailing_wind=Wind.EAST,
                hand_number=1,
                dealer_seat=Seat.EAST,
                honba=1,
                riichi_sticks=0,
            ),
        )
        self.assertEqual(match.position, completed.next_position)

    def test_abortive_draw_keeps_same_hand_and_increments_honba(self) -> None:
        match, _ = self._match_with_finished_round(
            AbortiveDrawResult(AbortiveDrawReason.FOUR_KANS)
        )

        completed = match.settle_active_round()

        self.assertTrue(completed.dealer_continues)
        self.assertEqual(
            completed.next_position,
            RoundPosition(
                prevailing_wind=Wind.EAST,
                hand_number=1,
                dealer_seat=Seat.EAST,
                honba=1,
                riichi_sticks=0,
            ),
        )
        self.assertEqual(
            completed.scores_after_settlement,
            match.scores,
        )

    def test_nondealer_win_flows_dealer_and_resets_honba(self) -> None:
        result = _win_result(
            (Seat.SOUTH,),
            method=WinMethod.RON,
            dealer_seat=Seat.EAST,
            source_seat=Seat.EAST,
        )
        match, _ = self._match_with_finished_round(result)
        starting_scores = match.scores

        completed = match.settle_active_round()

        self.assertFalse(completed.dealer_continues)
        self.assertEqual(
            completed.next_position,
            RoundPosition(
                prevailing_wind=Wind.EAST,
                hand_number=2,
                dealer_seat=Seat.SOUTH,
                honba=0,
                riichi_sticks=0,
            ),
        )
        self.assertEqual(
            completed.scores_after_settlement,
            starting_scores.add(completed.settlement.point_deltas),
        )
        self.assertNotEqual(match.scores, starting_scores)

    def test_riichi_contribution_is_forwarded_and_reflected_in_settlement(
        self,
    ) -> None:
        match, round_state = self._match_with_finished_round(ExhaustiveDrawResult())
        rules = match.rules
        contribution = RiichiContribution(Seat.SOUTH, rules.riichi_stick_points)

        with patch.object(
            RoundState,
            "riichi_contributions",
            new_callable=PropertyMock,
            return_value=(contribution,),
        ):
            completed = match.settle_active_round()

        self.assertEqual(completed.settlement.riichi_contributions, (contribution,))
        self.assertEqual(
            completed.scores_after_settlement[Seat.SOUTH],
            25_000 - rules.riichi_stick_points,
        )
        self.assertEqual(
            completed.settlement.riichi_sticks_after,
            1,
        )
        self.assertEqual(completed.next_position.riichi_sticks, 1)
        self.assertEqual(match.position.riichi_sticks, 1)

    def test_second_round_uses_ordinal_two(self) -> None:
        match = MatchState(seed=42)
        first_round = match.start_round()
        _finish_round(first_round, ExhaustiveDrawResult(tenpai_seats=(Seat.EAST,)))
        match.settle_active_round()

        second_round = match.start_round()

        self.assertEqual(match._started_round_count, 2)
        self.assertEqual(match._active_round_random_provenance.round_ordinal, 2)
        self.assertEqual(match._active_round_random_provenance.match_seed, 42)
        self.assertIs(match.active_round, second_round)

    def test_rejects_second_settle_after_success(self) -> None:
        match, _ = self._match_with_finished_round(ExhaustiveDrawResult())
        match.settle_active_round()

        with self.assertRaises(RuntimeError):
            match.settle_active_round()

        self.assertEqual(len(match.history), 1)

    def test_rejects_settle_of_unfinished_round(self) -> None:
        match = MatchState(seed=1)
        round_state = match.start_round()
        scores_before = match.scores
        position_before = match.position

        with self.assertRaises(RuntimeError):
            match.settle_active_round()

        self.assertIs(match.phase, MatchPhase.ROUND_IN_PROGRESS)
        self.assertIs(match.active_round, round_state)
        self.assertEqual(match.scores, scores_before)
        self.assertEqual(match.position, position_before)
        self.assertEqual(match.history, ())

    def test_rejects_settle_when_provenance_missing(self) -> None:
        match, round_state = self._match_with_finished_round(ExhaustiveDrawResult())
        match._active_round_random_provenance = None

        with self.assertRaises(RuntimeError):
            match.settle_active_round()

        self.assertIs(match.active_round, round_state)
        self.assertEqual(match.history, ())

    def test_rejects_settle_when_context_is_inconsistent(self) -> None:
        match, round_state = self._match_with_finished_round(ExhaustiveDrawResult())
        round_state._dealer_seat = Seat.SOUTH

        with self.assertRaises(ValueError):
            match.settle_active_round()

        self.assertIs(match.active_round, round_state)
        self.assertIs(match.phase, MatchPhase.ROUND_IN_PROGRESS)
        self.assertEqual(match.history, ())

    def test_settlement_failure_leaves_match_state_untouched(self) -> None:
        match, round_state = self._match_with_finished_round(ExhaustiveDrawResult())
        provenance_before = match._active_round_random_provenance
        scores_before = match.scores
        position_before = match.position

        with patch(
            "lisjong_engine.match_state.calculate_round_settlement",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                match.settle_active_round()

        self.assertIs(match.phase, MatchPhase.ROUND_IN_PROGRESS)
        self.assertIs(match.active_round, round_state)
        self.assertIs(match._active_round_random_provenance, provenance_before)
        self.assertEqual(match.scores, scores_before)
        self.assertEqual(match.position, position_before)
        self.assertEqual(match.history, ())
        self.assertEqual(match._started_round_count, 1)

    def test_next_position_failure_leaves_match_state_untouched(self) -> None:
        match, round_state = self._match_with_finished_round(ExhaustiveDrawResult())
        provenance_before = match._active_round_random_provenance
        scores_before = match.scores
        position_before = match.position

        with patch(
            "lisjong_engine.match_state._next_round_position",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                match.settle_active_round()

        self.assertIs(match.phase, MatchPhase.ROUND_IN_PROGRESS)
        self.assertIs(match.active_round, round_state)
        self.assertIs(match._active_round_random_provenance, provenance_before)
        self.assertEqual(match.scores, scores_before)
        self.assertEqual(match.position, position_before)
        self.assertEqual(match.history, ())
        self.assertEqual(match._started_round_count, 1)


_DEALER_SEAT_BY_HAND_NUMBER = {
    1: Seat.EAST,
    2: Seat.SOUTH,
    3: Seat.WEST,
    4: Seat.NORTH,
}


def _position(
    prevailing_wind: Wind,
    hand_number: int,
    *,
    honba: int = 0,
    riichi_sticks: int = 0,
) -> RoundPosition:
    return RoundPosition(
        prevailing_wind=prevailing_wind,
        hand_number=hand_number,
        dealer_seat=_DEALER_SEAT_BY_HAND_NUMBER[hand_number],
        honba=honba,
        riichi_sticks=riichi_sticks,
    )


class FirstPlaceSeatTest(unittest.TestCase):
    def test_clear_top(self) -> None:
        self.assertIs(
            _first_place_seat(SeatPoints(20_000, 40_000, 20_000, 20_000)),
            Seat.SOUTH,
        )

    def test_east_south_tie_favors_east(self) -> None:
        self.assertIs(
            _first_place_seat(SeatPoints(30_000, 30_000, 20_000, 20_000)),
            Seat.EAST,
        )

    def test_south_west_tie_with_lower_east_favors_south(self) -> None:
        self.assertIs(
            _first_place_seat(SeatPoints(10_000, 30_000, 30_000, 20_000)),
            Seat.SOUTH,
        )

    def test_four_way_tie_favors_east(self) -> None:
        self.assertIs(
            _first_place_seat(SeatPoints(25_000, 25_000, 25_000, 25_000)),
            Seat.EAST,
        )

    def test_rejects_invalid_type(self) -> None:
        with self.assertRaises(TypeError):
            _first_place_seat("not-seat-points")


class BankruptSeatsTest(unittest.TestCase):
    def test_score_below_threshold_is_bankrupt(self) -> None:
        rules = RuleSet.default()
        scores = SeatPoints(-1, 25_000, 25_000, 25_000)
        self.assertEqual(_bankrupt_seats(scores, rules), (Seat.EAST,))

    def test_score_equal_to_threshold_is_not_bankrupt(self) -> None:
        rules = RuleSet.default()
        scores = SeatPoints(0, 25_000, 25_000, 25_000)
        self.assertEqual(_bankrupt_seats(scores, rules), ())

    def test_positive_score_is_not_bankrupt(self) -> None:
        rules = RuleSet.default()
        scores = SeatPoints(25_000, 25_000, 25_000, 25_000)
        self.assertEqual(_bankrupt_seats(scores, rules), ())

    def test_bankruptcy_disabled_returns_empty(self) -> None:
        rules = replace(RuleSet.default(), bankruptcy_enabled=False)
        scores = SeatPoints(-1, -1, -1, -1)
        self.assertEqual(_bankrupt_seats(scores, rules), ())

    def test_multiple_bankrupt_seats_are_returned_in_fixed_seat_order(self) -> None:
        rules = RuleSet.default()
        scores = SeatPoints(-1, 25_000, -1, 25_000)
        self.assertEqual(_bankrupt_seats(scores, rules), (Seat.EAST, Seat.WEST))

    def test_rejects_invalid_scores_type(self) -> None:
        with self.assertRaises(TypeError):
            _bankrupt_seats("not-seat-points", RuleSet.default())

    def test_rejects_invalid_rules_type(self) -> None:
        with self.assertRaises(TypeError):
            _bankrupt_seats(SeatPoints(0, 0, 0, 0), "not-rules")


class MatchEndReasonBankruptcyTest(unittest.TestCase):
    def test_east_one_bankruptcy_ends_the_match(self) -> None:
        position = _position(Wind.EAST, 1)
        result = _win_result(
            (Seat.EAST,),
            method=WinMethod.TSUMO,
            dealer_seat=Seat.EAST,
        )
        scores_after = SeatPoints(-1, 25_000, 25_000, 25_000)

        self.assertIs(
            _match_end_reason(
                position,
                result,
                scores_after,
                True,
                RuleSet.default(),
            ),
            MatchEndReason.BANKRUPTCY,
        )

    def test_west_four_bankruptcy_takes_priority_over_final_round(self) -> None:
        position = _position(Wind.WEST, 4)
        result = _win_result(
            (Seat.NORTH,),
            method=WinMethod.TSUMO,
            dealer_seat=Seat.NORTH,
        )
        scores_after = SeatPoints(-1, 25_000, 25_000, 25_000)

        self.assertIs(
            _match_end_reason(
                position,
                result,
                scores_after,
                True,
                RuleSet.default(),
            ),
            MatchEndReason.BANKRUPTCY,
        )


class MatchEndReasonEarlyStageTest(unittest.TestCase):
    def test_east_four_dealer_win_top_and_target_reached_does_not_end(self) -> None:
        position = _position(Wind.EAST, 4)
        result = _win_result(
            (Seat.NORTH,),
            method=WinMethod.TSUMO,
            dealer_seat=Seat.NORTH,
        )
        scores_after = SeatPoints(20_000, 20_000, 20_000, 35_000)

        self.assertIsNone(
            _match_end_reason(
                position,
                result,
                scores_after,
                True,
                RuleSet.default(),
            )
        )

    def test_south_three_never_ends_without_bankruptcy(self) -> None:
        position = _position(Wind.SOUTH, 3)
        result = _win_result(
            (Seat.WEST,),
            method=WinMethod.TSUMO,
            dealer_seat=Seat.WEST,
        )
        scores_after = SeatPoints(10_000, 10_000, 60_000, 10_000)

        self.assertIsNone(
            _match_end_reason(
                position,
                result,
                scores_after,
                True,
                RuleSet.default(),
            )
        )


class MatchEndReasonSouthFourDealerStopTest(unittest.TestCase):
    def _south_four_win(self) -> WinResult:
        return _win_result(
            (Seat.NORTH,),
            method=WinMethod.TSUMO,
            dealer_seat=Seat.NORTH,
        )

    def _south_four_draw(self) -> ExhaustiveDrawResult:
        return ExhaustiveDrawResult(tenpai_seats=(Seat.NORTH,))

    def test_dealer_win_top_and_target_reached_ends_the_match(self) -> None:
        position = _position(Wind.SOUTH, 4)
        scores_after = SeatPoints(20_000, 20_000, 20_000, 35_000)

        self.assertIs(
            _match_end_reason(
                position,
                self._south_four_win(),
                scores_after,
                True,
                RuleSet.default(),
            ),
            MatchEndReason.DEALER_WIN,
        )

    def test_dealer_top_but_target_not_reached_continues(self) -> None:
        position = _position(Wind.SOUTH, 4)
        scores_after = SeatPoints(20_000, 20_000, 20_000, 25_000)

        self.assertIsNone(
            _match_end_reason(
                position,
                self._south_four_win(),
                scores_after,
                True,
                RuleSet.default(),
            )
        )

    def test_dealer_target_reached_but_not_top_continues(self) -> None:
        position = _position(Wind.SOUTH, 4)
        scores_after = SeatPoints(35_000, 20_000, 15_000, 30_000)

        self.assertIsNone(
            _match_end_reason(
                position,
                self._south_four_win(),
                scores_after,
                True,
                RuleSet.default(),
            )
        )

    def test_dealer_win_end_disabled_continues(self) -> None:
        position = _position(Wind.SOUTH, 4)
        scores_after = SeatPoints(20_000, 20_000, 20_000, 35_000)
        rules = replace(RuleSet.default(), dealer_win_end_enabled=False)

        self.assertIsNone(
            _match_end_reason(
                position,
                self._south_four_win(),
                scores_after,
                True,
                rules,
            )
        )

    def test_dealer_tenpai_top_and_target_reached_ends_the_match(self) -> None:
        position = _position(Wind.SOUTH, 4)
        scores_after = SeatPoints(20_000, 20_000, 20_000, 35_000)

        self.assertIs(
            _match_end_reason(
                position,
                self._south_four_draw(),
                scores_after,
                True,
                RuleSet.default(),
            ),
            MatchEndReason.DEALER_TENPAI,
        )

    def test_dealer_tenpai_target_not_reached_continues(self) -> None:
        position = _position(Wind.SOUTH, 4)
        scores_after = SeatPoints(20_000, 20_000, 20_000, 25_000)

        self.assertIsNone(
            _match_end_reason(
                position,
                self._south_four_draw(),
                scores_after,
                True,
                RuleSet.default(),
            )
        )

    def test_dealer_tenpai_not_top_continues(self) -> None:
        position = _position(Wind.SOUTH, 4)
        scores_after = SeatPoints(35_000, 20_000, 15_000, 30_000)

        self.assertIsNone(
            _match_end_reason(
                position,
                self._south_four_draw(),
                scores_after,
                True,
                RuleSet.default(),
            )
        )

    def test_dealer_tenpai_end_disabled_continues(self) -> None:
        position = _position(Wind.SOUTH, 4)
        scores_after = SeatPoints(20_000, 20_000, 20_000, 35_000)
        rules = replace(RuleSet.default(), dealer_tenpai_end_enabled=False)

        self.assertIsNone(
            _match_end_reason(
                position,
                self._south_four_draw(),
                scores_after,
                True,
                rules,
            )
        )


class MatchEndReasonTieBreakTest(unittest.TestCase):
    def test_west_one_dealer_east_wins_tie_break_and_ends(self) -> None:
        position = _position(Wind.WEST, 1)
        result = _win_result(
            (Seat.EAST,),
            method=WinMethod.TSUMO,
            dealer_seat=Seat.EAST,
        )
        scores_after = SeatPoints(30_000, 30_000, 20_000, 20_000)

        self.assertIs(
            _match_end_reason(
                position,
                result,
                scores_after,
                True,
                RuleSet.default(),
            ),
            MatchEndReason.DEALER_WIN,
        )

    def test_west_two_dealer_south_loses_tie_break_and_continues(self) -> None:
        position = _position(Wind.WEST, 2)
        result = _win_result(
            (Seat.SOUTH,),
            method=WinMethod.TSUMO,
            dealer_seat=Seat.SOUTH,
        )
        scores_after = SeatPoints(30_000, 30_000, 20_000, 20_000)

        self.assertIsNone(
            _match_end_reason(
                position,
                result,
                scores_after,
                True,
                RuleSet.default(),
            )
        )


class MatchEndReasonSouthFourDealerFlowTest(unittest.TestCase):
    def _south_four_child_win(self) -> WinResult:
        return _win_result(
            (Seat.EAST,),
            method=WinMethod.RON,
            dealer_seat=Seat.NORTH,
            source_seat=Seat.NORTH,
        )

    def test_target_reached_ends_with_target_reached(self) -> None:
        position = _position(Wind.SOUTH, 4)
        scores_after = SeatPoints(35_000, 20_000, 20_000, 25_000)

        self.assertIs(
            _match_end_reason(
                position,
                self._south_four_child_win(),
                scores_after,
                False,
                RuleSet.default(),
            ),
            MatchEndReason.TARGET_REACHED,
        )

    def test_target_not_reached_with_west_round_enabled_continues(self) -> None:
        position = _position(Wind.SOUTH, 4)
        scores_after = SeatPoints(25_000, 25_000, 25_000, 25_000)

        self.assertIsNone(
            _match_end_reason(
                position,
                self._south_four_child_win(),
                scores_after,
                False,
                RuleSet.default(),
            )
        )

    def test_target_not_reached_with_west_round_disabled_ends(self) -> None:
        position = _position(Wind.SOUTH, 4)
        scores_after = SeatPoints(25_000, 25_000, 25_000, 25_000)
        rules = replace(RuleSet.default(), west_round_enabled=False)

        self.assertIs(
            _match_end_reason(
                position,
                self._south_four_child_win(),
                scores_after,
                False,
                rules,
            ),
            MatchEndReason.FINAL_ROUND,
        )


class MatchEndReasonWestOneThroughThreeTest(unittest.TestCase):
    def test_dealer_flow_target_reached_ends_with_target_reached(self) -> None:
        position = _position(Wind.WEST, 2)
        result = _win_result(
            (Seat.WEST,),
            method=WinMethod.RON,
            dealer_seat=Seat.SOUTH,
            source_seat=Seat.SOUTH,
        )
        scores_after = SeatPoints(20_000, 20_000, 35_000, 25_000)

        self.assertIs(
            _match_end_reason(
                position,
                result,
                scores_after,
                False,
                RuleSet.default(),
            ),
            MatchEndReason.TARGET_REACHED,
        )

    def test_dealer_flow_target_not_reached_continues(self) -> None:
        position = _position(Wind.WEST, 2)
        result = _win_result(
            (Seat.WEST,),
            method=WinMethod.RON,
            dealer_seat=Seat.SOUTH,
            source_seat=Seat.SOUTH,
        )
        scores_after = SeatPoints(25_000, 25_000, 25_000, 25_000)

        self.assertIsNone(
            _match_end_reason(
                position,
                result,
                scores_after,
                False,
                RuleSet.default(),
            )
        )

    def test_dealer_stop_ends_west_one(self) -> None:
        position = _position(Wind.WEST, 1)
        result = _win_result(
            (Seat.EAST,),
            method=WinMethod.TSUMO,
            dealer_seat=Seat.EAST,
        )
        scores_after = SeatPoints(35_000, 20_000, 20_000, 25_000)

        self.assertIs(
            _match_end_reason(
                position,
                result,
                scores_after,
                True,
                RuleSet.default(),
            ),
            MatchEndReason.DEALER_WIN,
        )


class MatchEndReasonWestFourTest(unittest.TestCase):
    def test_dealer_win_stop_conditions_still_yield_final_round(self) -> None:
        position = _position(Wind.WEST, 4)
        result = _win_result(
            (Seat.NORTH,),
            method=WinMethod.TSUMO,
            dealer_seat=Seat.NORTH,
        )
        scores_after = SeatPoints(20_000, 20_000, 20_000, 35_000)

        self.assertIs(
            _match_end_reason(
                position,
                result,
                scores_after,
                True,
                RuleSet.default(),
            ),
            MatchEndReason.FINAL_ROUND,
        )

    def test_dealer_tenpai_stop_conditions_still_yield_final_round(self) -> None:
        position = _position(Wind.WEST, 4)
        result = ExhaustiveDrawResult(tenpai_seats=(Seat.NORTH,))
        scores_after = SeatPoints(20_000, 20_000, 20_000, 35_000)

        self.assertIs(
            _match_end_reason(
                position,
                result,
                scores_after,
                True,
                RuleSet.default(),
            ),
            MatchEndReason.FINAL_ROUND,
        )

    def test_dealer_flow_yields_final_round(self) -> None:
        position = _position(Wind.WEST, 4)
        result = _win_result(
            (Seat.EAST,),
            method=WinMethod.RON,
            dealer_seat=Seat.NORTH,
            source_seat=Seat.NORTH,
        )
        scores_after = SeatPoints(25_000, 25_000, 25_000, 25_000)

        self.assertIs(
            _match_end_reason(
                position,
                result,
                scores_after,
                False,
                RuleSet.default(),
            ),
            MatchEndReason.FINAL_ROUND,
        )

    def test_abortive_draw_dealer_continuation_yields_final_round(self) -> None:
        position = _position(Wind.WEST, 4)
        result = AbortiveDrawResult(AbortiveDrawReason.FOUR_KANS)
        scores_after = SeatPoints(25_000, 25_000, 25_000, 25_000)

        self.assertIs(
            _match_end_reason(
                position,
                result,
                scores_after,
                True,
                RuleSet.default(),
            ),
            MatchEndReason.FINAL_ROUND,
        )


class MatchEndReasonAbortiveDrawTest(unittest.TestCase):
    def test_south_four_abortive_draw_does_not_end(self) -> None:
        position = _position(Wind.SOUTH, 4)
        result = AbortiveDrawResult(AbortiveDrawReason.FOUR_KANS)
        scores_after = SeatPoints(20_000, 20_000, 20_000, 35_000)

        self.assertIsNone(
            _match_end_reason(
                position,
                result,
                scores_after,
                True,
                RuleSet.default(),
            )
        )

    def test_west_two_abortive_draw_does_not_end(self) -> None:
        position = _position(Wind.WEST, 2)
        result = AbortiveDrawResult(AbortiveDrawReason.FOUR_KANS)
        scores_after = SeatPoints(20_000, 35_000, 20_000, 20_000)

        self.assertIsNone(
            _match_end_reason(
                position,
                result,
                scores_after,
                True,
                RuleSet.default(),
            )
        )


class MatchEndReasonDealerContinuesConsistencyTest(unittest.TestCase):
    def test_rejects_inconsistent_dealer_continues(self) -> None:
        position = _position(Wind.SOUTH, 4)
        result = _win_result(
            (Seat.EAST,),
            method=WinMethod.RON,
            dealer_seat=Seat.NORTH,
            source_seat=Seat.NORTH,
        )
        scores_after = SeatPoints(25_000, 25_000, 25_000, 25_000)

        with self.assertRaises(ValueError):
            _match_end_reason(
                position,
                result,
                scores_after,
                True,
                RuleSet.default(),
            )

    def test_accepts_consistent_dealer_continues(self) -> None:
        position = _position(Wind.SOUTH, 4)
        result = _win_result(
            (Seat.NORTH,),
            method=WinMethod.TSUMO,
            dealer_seat=Seat.NORTH,
        )
        scores_after = SeatPoints(20_000, 20_000, 20_000, 25_000)

        self.assertIsNone(
            _match_end_reason(
                position,
                result,
                scores_after,
                True,
                RuleSet.default(),
            )
        )


class MatchEndReasonReturnPointsIndependenceTest(unittest.TestCase):
    def test_return_points_does_not_affect_the_decision(self) -> None:
        position = _position(Wind.SOUTH, 4)
        result = _win_result(
            (Seat.EAST,),
            method=WinMethod.RON,
            dealer_seat=Seat.NORTH,
            source_seat=Seat.NORTH,
        )
        scores_after = SeatPoints(35_000, 20_000, 20_000, 25_000)

        rules_a = RuleSet.default()
        rules_b = replace(rules_a, return_points=35_000)
        self.assertNotEqual(rules_a.return_points, rules_b.return_points)

        self.assertEqual(
            _match_end_reason(position, result, scores_after, False, rules_a),
            _match_end_reason(position, result, scores_after, False, rules_b),
        )
        self.assertIs(
            _match_end_reason(position, result, scores_after, False, rules_b),
            MatchEndReason.TARGET_REACHED,
        )


class MatchEndReasonValidationTest(unittest.TestCase):
    def _valid_arguments(self):
        position = _position(Wind.EAST, 1)
        result = ExhaustiveDrawResult(tenpai_seats=(Seat.EAST,))
        scores_after = SeatPoints(25_000, 25_000, 25_000, 25_000)
        return position, result, scores_after, True, RuleSet.default()

    def test_rejects_invalid_position(self) -> None:
        _, result, scores_after, dealer_continues, rules = self._valid_arguments()
        with self.assertRaises(TypeError):
            _match_end_reason(
                "not-a-position", result, scores_after, dealer_continues, rules
            )

    def test_rejects_invalid_result(self) -> None:
        position, _, scores_after, dealer_continues, rules = self._valid_arguments()
        with self.assertRaises(TypeError):
            _match_end_reason(
                position, "not-a-result", scores_after, dealer_continues, rules
            )

    def test_rejects_invalid_scores_after(self) -> None:
        position, result, _, dealer_continues, rules = self._valid_arguments()
        with self.assertRaises(TypeError):
            _match_end_reason(
                position, result, "not-seat-points", dealer_continues, rules
            )

    def test_rejects_non_bool_dealer_continues(self) -> None:
        position, result, scores_after, _, rules = self._valid_arguments()
        with self.assertRaises(TypeError):
            _match_end_reason(position, result, scores_after, 1, rules)

    def test_rejects_invalid_rules(self) -> None:
        position, result, scores_after, dealer_continues, _ = self._valid_arguments()
        with self.assertRaises(TypeError):
            _match_end_reason(
                position, result, scores_after, dealer_continues, "not-rules"
            )


def _match_at_position(
    seed: int,
    position: RoundPosition,
    *,
    starting_scores=None,
    rules=None,
) -> MatchState:
    """testのためだけに、MatchStateを任意のRoundPositionから開始させる。

    productionのpublic constructorは常にEast1で初期化する（East1固定は
    Issue #24第2段階のcontract）。terminal integration testでは
    South4/West1〜4等のend-stage positionを直接検証する必要があるため、
    private field `_position`をtest側から直接上書きする。production側に
    position注入APIは追加しない。
    """
    match = MatchState(seed=seed, rules=rules, starting_scores=starting_scores)
    match._position = position
    return match


class SettleActiveRoundTerminalFinalRoundTest(unittest.TestCase):
    def test_west_four_dealer_flow_ends_with_final_round(self) -> None:
        position = _position(Wind.WEST, 4)
        match = _match_at_position(1, position)
        round_state = match.start_round()
        result = _win_result(
            (Seat.EAST,),
            method=WinMethod.RON,
            dealer_seat=Seat.NORTH,
            source_seat=Seat.NORTH,
        )
        _finish_round(round_state, result)

        completed = match.settle_active_round()

        self.assertIsNone(completed.next_position)
        self.assertIs(match.phase, MatchPhase.FINISHED)
        self.assertIsNotNone(match.completed_match)
        self.assertIs(match.completed_match.end_reason, MatchEndReason.FINAL_ROUND)
        self.assertEqual(match.position, position)
        self.assertIsNone(match.active_round)
        self.assertIsNone(match._active_round_random_provenance)
        self.assertEqual(match.scores, match.completed_match.final_raw_scores)
        self.assertEqual(match.history, match.completed_match.history)
        self.assertIs(match.completed_match.history[-1], completed)
        self.assertIsNone(match.completed_match.history[-1].next_position)
        self.assertEqual(match.completed_match.final_riichi_stick_awards, ())

    def test_west_four_dealer_continuation_ends_with_final_round(self) -> None:
        position = _position(Wind.WEST, 4)
        match = _match_at_position(1, position)
        round_state = match.start_round()
        result = _win_result(
            (Seat.NORTH,),
            method=WinMethod.TSUMO,
            dealer_seat=Seat.NORTH,
        )
        _finish_round(round_state, result)

        completed = match.settle_active_round()

        self.assertIsNone(completed.next_position)
        self.assertIs(match.phase, MatchPhase.FINISHED)
        self.assertIs(match.completed_match.end_reason, MatchEndReason.FINAL_ROUND)

    def test_next_round_position_is_never_called_on_the_terminal_path(self) -> None:
        position = _position(Wind.WEST, 4)
        match = _match_at_position(1, position)
        round_state = match.start_round()
        result = _win_result(
            (Seat.EAST,),
            method=WinMethod.RON,
            dealer_seat=Seat.NORTH,
            source_seat=Seat.NORTH,
        )
        _finish_round(round_state, result)

        with patch(
            "lisjong_engine.match_state._next_round_position",
            side_effect=AssertionError(
                "_next_round_position() must not be called on the terminal path"
            ),
        ):
            completed = match.settle_active_round()

        self.assertIsNone(completed.next_position)
        self.assertIs(match.phase, MatchPhase.FINISHED)


class SettleActiveRoundTerminalDealerStopTest(unittest.TestCase):
    def test_south_four_dealer_win_top_and_target_ends_with_dealer_win(self) -> None:
        position = _position(Wind.SOUTH, 4)
        starting_scores = {
            Seat.EAST: 20_000,
            Seat.SOUTH: 20_000,
            Seat.WEST: 20_000,
            Seat.NORTH: 40_000,
        }
        match = _match_at_position(1, position, starting_scores=starting_scores)
        round_state = match.start_round()
        result = _win_result(
            (Seat.NORTH,),
            method=WinMethod.TSUMO,
            dealer_seat=Seat.NORTH,
        )
        _finish_round(round_state, result)

        completed = match.settle_active_round()

        self.assertIsNone(completed.next_position)
        self.assertIs(match.phase, MatchPhase.FINISHED)
        self.assertIs(match.completed_match.end_reason, MatchEndReason.DEALER_WIN)
        self.assertEqual(match.completed_match.final_riichi_stick_awards, ())
        self.assertEqual(match.completed_match.final_raw_scores, match.scores)
        self.assertEqual(match.completed_match.history, (completed,))

    def test_south_four_dealer_tenpai_top_and_target_ends_with_dealer_tenpai(
        self,
    ) -> None:
        position = _position(Wind.SOUTH, 4)
        starting_scores = {
            Seat.EAST: 20_000,
            Seat.SOUTH: 20_000,
            Seat.WEST: 20_000,
            Seat.NORTH: 40_000,
        }
        match = _match_at_position(1, position, starting_scores=starting_scores)
        round_state = match.start_round()
        result = ExhaustiveDrawResult(tenpai_seats=(Seat.NORTH,))
        _finish_round(round_state, result)

        completed = match.settle_active_round()

        self.assertIsNone(completed.next_position)
        self.assertIs(match.phase, MatchPhase.FINISHED)
        self.assertIs(match.completed_match.end_reason, MatchEndReason.DEALER_TENPAI)


class SettleActiveRoundTerminalTargetReachedTest(unittest.TestCase):
    def test_south_four_dealer_flow_target_reached_ends(self) -> None:
        position = _position(Wind.SOUTH, 4)
        starting_scores = {
            Seat.EAST: 28_500,
            Seat.SOUTH: 24_000,
            Seat.WEST: 24_000,
            Seat.NORTH: 23_500,
        }
        match = _match_at_position(1, position, starting_scores=starting_scores)
        round_state = match.start_round()
        result = _win_result(
            (Seat.EAST,),
            method=WinMethod.RON,
            dealer_seat=Seat.NORTH,
            source_seat=Seat.NORTH,
        )
        _finish_round(round_state, result)

        completed = match.settle_active_round()

        self.assertIsNone(completed.next_position)
        self.assertIs(match.phase, MatchPhase.FINISHED)
        self.assertIs(match.completed_match.end_reason, MatchEndReason.TARGET_REACHED)


class SettleActiveRoundTerminalSouthFourFlowTest(unittest.TestCase):
    def _south_four_child_win(self, *, rules: RuleSet | None = None) -> WinResult:
        return _win_result(
            (Seat.EAST,),
            method=WinMethod.RON,
            dealer_seat=Seat.NORTH,
            source_seat=Seat.NORTH,
            rules=rules,
        )

    def test_west_round_enabled_flows_to_west_one_non_terminally(self) -> None:
        position = _position(Wind.SOUTH, 4)
        match = _match_at_position(1, position)
        round_state = match.start_round()
        _finish_round(round_state, self._south_four_child_win())

        completed = match.settle_active_round()

        self.assertIsNotNone(completed.next_position)
        self.assertEqual(
            completed.next_position,
            _position(Wind.WEST, 1),
        )
        self.assertIs(match.phase, MatchPhase.AWAITING_ROUND)
        self.assertIsNone(match.completed_match)
        self.assertEqual(match.position, completed.next_position)

    def test_west_round_disabled_ends_with_final_round(self) -> None:
        position = _position(Wind.SOUTH, 4)
        rules = replace(RuleSet.default(), west_round_enabled=False)
        match = _match_at_position(1, position, rules=rules)
        round_state = match.start_round()
        _finish_round(round_state, self._south_four_child_win(rules=rules))

        completed = match.settle_active_round()

        self.assertIsNone(completed.next_position)
        self.assertIs(match.phase, MatchPhase.FINISHED)
        self.assertIs(match.completed_match.end_reason, MatchEndReason.FINAL_ROUND)


class SettleActiveRoundTerminalBankruptcyTest(unittest.TestCase):
    def test_bankruptcy_ends_the_match_with_bankruptcy_adjustment(self) -> None:
        position = _position(Wind.EAST, 1)
        starting_scores = {
            Seat.EAST: 25_000,
            Seat.SOUTH: 25_000,
            Seat.WEST: 1_000,
            Seat.NORTH: 25_000,
        }
        match = _match_at_position(1, position, starting_scores=starting_scores)
        round_state = match.start_round()
        result = _win_result(
            (Seat.SOUTH,),
            method=WinMethod.RON,
            dealer_seat=Seat.EAST,
            source_seat=Seat.WEST,
        )
        _finish_round(round_state, result)

        completed = match.settle_active_round()

        self.assertIsNone(completed.next_position)
        self.assertIs(match.phase, MatchPhase.FINISHED)
        self.assertIs(match.completed_match.end_reason, MatchEndReason.BANKRUPTCY)

        self.assertLess(completed.scores_after_settlement[Seat.WEST], 0)
        # bankruptcy adjustmentはfinal raw scoresへ直接加算されない。
        self.assertEqual(
            match.completed_match.final_raw_scores[Seat.WEST],
            completed.scores_after_settlement[Seat.WEST],
        )
        # 一方、FinalScoreCalculation側にはadjustmentが反映される。
        west_final = match.completed_match.final_score.for_seat(Seat.WEST)
        south_final = match.completed_match.final_score.for_seat(Seat.SOUTH)
        self.assertNotEqual(west_final.bankruptcy_points, 0)
        self.assertNotEqual(south_final.bankruptcy_points, 0)

    def test_bankruptcy_recipient_ambiguity_is_fail_closed_and_atomic(self) -> None:
        # WESTはこの局でtenpaiとしてnoten penaltyのrecipientになるだけで、
        # 誰への支払いもしていない（settlement.transfersにpayerとして
        # 一度も現れない）。それでも精算後になお破産している場合、F1の
        # `calculate_bankruptcy_points_from_transfers()`はrecipientを
        # 一意に導出できずfail closedする。
        position = _position(Wind.EAST, 1)
        starting_scores = {
            Seat.EAST: 25_000,
            Seat.SOUTH: 25_000,
            Seat.WEST: -20_000,
            Seat.NORTH: 25_000,
        }
        match = _match_at_position(1, position, starting_scores=starting_scores)
        round_state = match.start_round()
        result = ExhaustiveDrawResult(tenpai_seats=(Seat.WEST,))
        _finish_round(round_state, result)
        scores_before = match.scores
        provenance_before = match._active_round_random_provenance

        with self.assertRaises(ValueError):
            match.settle_active_round()

        self.assertIs(match.phase, MatchPhase.ROUND_IN_PROGRESS)
        self.assertIs(match.active_round, round_state)
        self.assertIs(match._active_round_random_provenance, provenance_before)
        self.assertEqual(match.scores, scores_before)
        self.assertEqual(match.history, ())
        self.assertIsNone(match.completed_match)


class SettleActiveRoundTerminalFinalRiichiAwardTest(unittest.TestCase):
    def test_remaining_riichi_sticks_are_awarded_and_kept_out_of_round_settlement(
        self,
    ) -> None:
        position = _position(Wind.WEST, 4, riichi_sticks=2)
        match = _match_at_position(1, position)
        round_state = match.start_round()
        result = ExhaustiveDrawResult()
        _finish_round(round_state, result)

        completed = match.settle_active_round()

        self.assertEqual(completed.settlement.riichi_stick_awards, ())
        self.assertEqual(completed.settlement.riichi_sticks_after, 2)

        self.assertEqual(len(match.completed_match.final_riichi_stick_awards), 1)
        award = match.completed_match.final_riichi_stick_awards[0]
        self.assertEqual(award.amount, 2_000)
        self.assertEqual(
            match.completed_match.final_raw_scores[award.recipient],
            completed.scores_after_settlement[award.recipient] + 2_000,
        )
        self.assertEqual(match.scores, match.completed_match.final_raw_scores)

    def test_no_remaining_riichi_sticks_yields_no_final_awards(self) -> None:
        position = _position(Wind.WEST, 4)
        match = _match_at_position(1, position)
        round_state = match.start_round()
        result = _win_result(
            (Seat.NORTH,),
            method=WinMethod.TSUMO,
            dealer_seat=Seat.NORTH,
        )
        _finish_round(round_state, result)

        match.settle_active_round()

        self.assertEqual(match.completed_match.final_riichi_stick_awards, ())

    def test_split_rank_points_tie_produces_multiple_final_awards(self) -> None:
        position = _position(Wind.WEST, 4, riichi_sticks=2)
        rules = replace(
            RuleSet.default(),
            final_rank_tie_policy=FinalRankTiePolicy.SPLIT_RANK_POINTS,
        )
        starting_scores = {
            Seat.EAST: 30_000,
            Seat.SOUTH: 30_000,
            Seat.WEST: 20_000,
            Seat.NORTH: 20_000,
        }
        match = _match_at_position(
            1, position, starting_scores=starting_scores, rules=rules
        )
        round_state = match.start_round()
        result = ExhaustiveDrawResult()
        _finish_round(round_state, result)

        match.settle_active_round()

        awards = match.completed_match.final_riichi_stick_awards
        self.assertEqual(len(awards), 2)
        self.assertEqual(sum(award.amount for award in awards), 2_000)
        self.assertEqual({award.recipient for award in awards}, {Seat.EAST, Seat.SOUTH})


class SettleActiveRoundTerminalDoubleOperationTest(unittest.TestCase):
    def _finished_match(self) -> MatchState:
        position = _position(Wind.WEST, 4)
        match = _match_at_position(1, position)
        round_state = match.start_round()
        result = _win_result(
            (Seat.NORTH,),
            method=WinMethod.TSUMO,
            dealer_seat=Seat.NORTH,
        )
        _finish_round(round_state, result)
        match.settle_active_round()
        return match

    def test_rejects_start_round_after_terminal_settlement(self) -> None:
        match = self._finished_match()

        with self.assertRaises(RuntimeError):
            match.start_round()

    def test_rejects_settle_active_round_after_terminal_settlement(self) -> None:
        match = self._finished_match()
        history_before = match.history
        completed_match_before = match.completed_match

        with self.assertRaises(RuntimeError):
            match.settle_active_round()

        self.assertEqual(match.history, history_before)
        self.assertIs(match.completed_match, completed_match_before)


class SettleActiveRoundTerminalTransactionalityTest(unittest.TestCase):
    def _prepare(self):
        position = _position(Wind.WEST, 4)
        match = _match_at_position(1, position)
        round_state = match.start_round()
        result = _win_result(
            (Seat.NORTH,),
            method=WinMethod.TSUMO,
            dealer_seat=Seat.NORTH,
        )
        _finish_round(round_state, result)
        return match, round_state

    def _assert_untouched(self, match, round_state, provenance_before, scores_before):
        self.assertIs(match.phase, MatchPhase.ROUND_IN_PROGRESS)
        self.assertIs(match.active_round, round_state)
        self.assertIs(match._active_round_random_provenance, provenance_before)
        self.assertEqual(match.scores, scores_before)
        self.assertEqual(match.history, ())
        self.assertIsNone(match.completed_match)
        self.assertEqual(match._started_round_count, 1)

    def test_bankruptcy_points_failure_leaves_match_state_untouched(self) -> None:
        position = _position(Wind.EAST, 1)
        starting_scores = {
            Seat.EAST: 25_000,
            Seat.SOUTH: 25_000,
            Seat.WEST: -1,
            Seat.NORTH: 25_000,
        }
        match = _match_at_position(1, position, starting_scores=starting_scores)
        round_state = match.start_round()
        result = ExhaustiveDrawResult(tenpai_seats=(Seat.EAST, Seat.SOUTH, Seat.NORTH))
        _finish_round(round_state, result)
        provenance_before = match._active_round_random_provenance
        scores_before = match.scores

        with patch(
            "lisjong_engine.match_state.calculate_bankruptcy_points_from_transfers",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                match.settle_active_round()

        self._assert_untouched(match, round_state, provenance_before, scores_before)

    def test_final_riichi_award_failure_leaves_match_state_untouched(self) -> None:
        match, round_state = self._prepare()
        provenance_before = match._active_round_random_provenance
        scores_before = match.scores

        with patch(
            "lisjong_engine.match_state.calculate_final_riichi_stick_awards",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                match.settle_active_round()

        self._assert_untouched(match, round_state, provenance_before, scores_before)

    def test_final_scores_failure_leaves_match_state_untouched(self) -> None:
        match, round_state = self._prepare()
        provenance_before = match._active_round_random_provenance
        scores_before = match.scores

        with patch(
            "lisjong_engine.match_state.calculate_final_scores",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                match.settle_active_round()

        self._assert_untouched(match, round_state, provenance_before, scores_before)


class DeterministicMatchLifecycleTest(unittest.TestCase):
    def test_same_seed_and_result_sequence_produce_identical_terminal_facts(
        self,
    ) -> None:
        position = _position(Wind.WEST, 4)

        def _run() -> MatchState:
            match = _match_at_position(777, position)
            round_state = match.start_round()
            result = _win_result(
                (Seat.NORTH,),
                method=WinMethod.TSUMO,
                dealer_seat=Seat.NORTH,
            )
            _finish_round(round_state, result)
            match.settle_active_round()
            return match

        first = _run()
        second = _run()

        self.assertEqual(
            first.history[0].random_provenance,
            second.history[0].random_provenance,
        )
        self.assertIs(
            first.completed_match.end_reason,
            second.completed_match.end_reason,
        )
        self.assertEqual(
            first.completed_match.final_raw_scores,
            second.completed_match.final_raw_scores,
        )
        self.assertEqual(first.scores, second.scores)
        self.assertEqual(
            first.completed_match.final_score,
            second.completed_match.final_score,
        )


if __name__ == "__main__":
    unittest.main()
