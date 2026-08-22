import unittest

from _round_fixtures import INERT_HAND, action_of_type, dealt_state, play_quiet_turn

from lisjong_engine.action_descriptor import (
    ActionDescriptor,
    RonActionDescriptor,
    TsumoActionDescriptor,
)
from lisjong_engine.driver import run_hanchan
from lisjong_engine.legal_action import TsumoLegalAction
from lisjong_engine.match_state import (
    CompletedMatch,
    CompletedRound,
    MatchEndReason,
    MatchState,
    RoundPosition,
)
from lisjong_engine.points import SeatPoints
from lisjong_engine.public_state import SeatPointDelta, SeatScore
from lisjong_engine.round_allocation import create_round_random_provenance
from lisjong_engine.round_completion import (
    MatchCompletionFact,
    RoundCompletionFact,
    RoundOutcomeKind,
    project_match_completion,
    project_round_completion,
)
from lisjong_engine.round_result import AbortiveDrawReason
from lisjong_engine.seat import Seat
from lisjong_engine.settlement import calculate_round_settlement
from lisjong_engine.win_context import WinMethod
from lisjong_engine.wind import Wind

_TSUMO_HAND = (
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
)


def _play_deterministic_hanchan(seed: int = 12345) -> tuple[MatchState, CompletedMatch]:
    """`test_driver.py`と同じ決定的selectorで半荘を完走させ、historyを得る。"""

    def winning_first_selector(
        _observation,
        options: tuple[ActionDescriptor, ...],
    ) -> ActionDescriptor:
        return next(
            (
                option
                for option in options
                if isinstance(option, (RonActionDescriptor, TsumoActionDescriptor))
            ),
            options[0],
        )

    match = MatchState(seed=seed)
    completed = run_hanchan(match, {seat: winning_first_selector for seat in Seat})
    return match, completed


def _build_non_dealer_tsumo_completed_round() -> CompletedRound:
    """South tsumoの`CompletedRound`を、乱数の運に頼らず決定的に組み立てる。"""
    hands = {seat: INERT_HAND for seat in Seat}
    hands[Seat.SOUTH] = _TSUMO_HAND
    state = dealt_state(hands=hands, draws=("5z", "7p"), with_dead_wall=True)
    play_quiet_turn(state)  # 親(EAST)がツモ切りし、Southの番へ進める。
    state.draw(Seat.SOUTH)
    snapshot = state.legal_actions(Seat.SOUTH)
    state.apply(
        Seat.SOUTH,
        action_of_type(state, Seat.SOUTH, TsumoLegalAction),
        expected_revision=snapshot.revision,
    )
    result = state.result

    position = RoundPosition(
        prevailing_wind=Wind.EAST,
        hand_number=1,
        dealer_seat=Seat.EAST,
        honba=0,
        riichi_sticks=0,
    )
    settlement = calculate_round_settlement(
        result,
        dealer_seat=Seat.EAST,
        honba=0,
        riichi_sticks_before=0,
        riichi_contributions=state.riichi_contributions,
        rules=state.rules,
    )
    scores_before = SeatPoints(25000, 25000, 25000, 25000)
    scores_after = scores_before.add(settlement.point_deltas)
    next_position = RoundPosition(
        prevailing_wind=Wind.EAST,
        hand_number=2,
        dealer_seat=Seat.SOUTH,
        honba=0,
        riichi_sticks=settlement.riichi_sticks_after,
    )
    return CompletedRound(
        random_provenance=create_round_random_provenance(1, 1),
        position_before=position,
        result=result,
        settlement=settlement,
        scores_after_settlement=scores_after,
        dealer_continues=False,
        next_position=next_position,
    )


class RoundCompletionProjectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _, cls.completed_match = _play_deterministic_hanchan()
        cls.history = cls.completed_match.history

    def test_rejects_non_completed_round(self) -> None:
        with self.assertRaises(TypeError):
            project_round_completion(object())

    def test_projects_every_round_in_history_without_error(self) -> None:
        for completed_round in self.history:
            with self.subTest(position=completed_round.position_before):
                fact = project_round_completion(completed_round)
                self.assertIsInstance(fact, RoundCompletionFact)

    def test_projected_position_matches_the_source_round(self) -> None:
        completed_round = self.history[0]
        fact = project_round_completion(completed_round)

        self.assertIs(
            fact.prevailing_wind, completed_round.position_before.prevailing_wind
        )
        self.assertEqual(fact.hand_number, completed_round.position_before.hand_number)
        self.assertIs(fact.dealer_seat, completed_round.position_before.dealer_seat)
        self.assertEqual(fact.honba, completed_round.position_before.honba)
        self.assertEqual(fact.dealer_continues, completed_round.dealer_continues)
        self.assertEqual(fact.has_next_round, completed_round.next_position is not None)

    def test_point_deltas_and_scores_after_match_the_settlement(self) -> None:
        completed_round = self.history[0]
        fact = project_round_completion(completed_round)

        for delta in fact.point_deltas:
            self.assertEqual(
                delta.delta,
                completed_round.settlement.point_deltas[delta.seat],
            )
        for score in fact.scores_after:
            self.assertEqual(
                score.points,
                completed_round.scores_after_settlement[score.seat],
            )

    def test_win_outcome_reports_winners_and_source_seat(self) -> None:
        win_round = _build_non_dealer_tsumo_completed_round()
        fact = project_round_completion(win_round)

        self.assertIs(fact.outcome, RoundOutcomeKind.WIN)
        self.assertEqual(len(fact.winners), 1)
        self.assertIs(fact.winners[0].seat, Seat.SOUTH)
        self.assertIs(fact.winners[0].win_method, WinMethod.TSUMO)
        self.assertIsNone(fact.source_seat)
        self.assertFalse(fact.dealer_continues)
        self.assertTrue(fact.has_next_round)


class MatchCompletionProjectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _, cls.completed_match = _play_deterministic_hanchan()

    def test_rejects_non_completed_match(self) -> None:
        with self.assertRaises(TypeError):
            project_match_completion(object())

    def test_projects_end_reason_and_final_scores(self) -> None:
        fact = project_match_completion(self.completed_match)

        self.assertIsInstance(fact, MatchCompletionFact)
        self.assertIsInstance(fact.end_reason, MatchEndReason)
        for score in fact.final_scores:
            self.assertEqual(
                score.points,
                self.completed_match.final_raw_scores[score.seat],
            )

    def test_final_results_cover_every_seat_with_a_valid_rank(self) -> None:
        fact = project_match_completion(self.completed_match)

        self.assertEqual({result.seat for result in fact.final_results}, set(Seat))
        for result in fact.final_results:
            self.assertTrue(1 <= result.rank <= 4)
            expected = self.completed_match.final_score.for_seat(result.seat)
            self.assertEqual(result.rank, expected.rank)
            self.assertEqual(result.final_points, expected.final_points)


class RoundCompletionFactValidationTest(unittest.TestCase):
    def _base_kwargs(self) -> dict:
        seats = tuple(Seat)
        return dict(
            prevailing_wind=Wind.EAST,
            hand_number=1,
            dealer_seat=Seat.EAST,
            honba=0,
            outcome=RoundOutcomeKind.ABORTIVE_DRAW,
            abortive_reason=AbortiveDrawReason.FOUR_WINDS,
            point_deltas=tuple(SeatPointDelta(seat, 0) for seat in seats),
            scores_after=tuple(SeatScore(seat, 25000) for seat in seats),
            dealer_continues=True,
            has_next_round=True,
        )

    def test_rejects_incomplete_seat_coverage(self) -> None:
        kwargs = self._base_kwargs()
        kwargs["point_deltas"] = (SeatPointDelta(Seat.EAST, 0),)
        with self.assertRaises(ValueError):
            RoundCompletionFact(**kwargs)

    def test_rejects_wrong_types(self) -> None:
        kwargs = self._base_kwargs()
        kwargs["dealer_seat"] = "east"
        with self.assertRaises(TypeError):
            RoundCompletionFact(**kwargs)


if __name__ == "__main__":
    unittest.main()
