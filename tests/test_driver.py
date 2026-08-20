import unittest
from dataclasses import replace
from unittest.mock import patch

from _round_fixtures import (
    INERT_HAND,
    action_of_type,
    capture,
    dealt_state,
    discard,
    draw_and_discard,
    play_quiet_turn,
    pon_action,
    resolve_with,
)

from lisjong_engine.action_descriptor import (
    ActionDescriptor,
    ChiActionDescriptor,
    NineTerminalsActionDescriptor,
    PassActionDescriptor,
    PonActionDescriptor,
    RiichiDiscardActionDescriptor,
    RonActionDescriptor,
    TsumoActionDescriptor,
)
from lisjong_engine.driver import (
    DriverStateError,
    _advance_round,
    _apply_turn_choice,
    _resolve_reaction_choices,
    run_hanchan,
)
from lisjong_engine.legal_action import AnkanLegalAction, KakanLegalAction
from lisjong_engine.match_state import MatchPhase, MatchState
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.rules import RonResolutionPolicy, RuleSet
from lisjong_engine.seat import Seat

_REACTION_HANDS = {
    Seat.EAST: (
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
        "6z",
        "7z",
        "1p",
    ),
    Seat.SOUTH: (
        "5p",
        "6p",
        "1m",
        "9m",
        "1s",
        "9s",
        "1z",
        "2z",
        "3z",
        "4z",
        "5z",
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
        "6z",
    ),
}

_DOUBLE_RON_HANDS = {
    Seat.EAST: _REACTION_HANDS[Seat.EAST],
    Seat.SOUTH: INERT_HAND,
    Seat.WEST: _REACTION_HANDS[Seat.WEST],
    Seat.NORTH: (
        "2m",
        "3m",
        "4m",
        "5m",
        "6m",
        "7m",
        "2p",
        "3p",
        "4p",
        "6p",
        "8p",
        "3s",
        "3s",
    ),
}

_KAKAN_HANDS = {
    Seat.EAST: (
        "3p",
        "1m",
        "4m",
        "7m",
        "1p",
        "7p",
        "1s",
        "4s",
        "7s",
        "1z",
        "2z",
        "3z",
        "4z",
    ),
    Seat.SOUTH: (
        "3p",
        "3p",
        "1m",
        "4m",
        "7m",
        "1p",
        "7p",
        "1s",
        "4s",
        "7s",
        "1z",
        "2z",
        "3z",
    ),
    Seat.WEST: (
        "2m",
        "3m",
        "4m",
        "5m",
        "6m",
        "7m",
        "7p",
        "8p",
        "9p",
        "5p",
        "2s",
        "2s",
        "9s",
    ),
    Seat.NORTH: INERT_HAND,
}

_ANKAN_HANDS = {
    Seat.EAST: (
        "1m",
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
        "2p",
        "3p",
    ),
    Seat.SOUTH: (
        "1z",
        "2z",
        "3z",
        "4z",
        "5z",
        "6z",
        "7z",
        "4p",
        "7p",
        "4s",
        "7s",
        "2s",
        "5s",
    ),
    Seat.WEST: (
        "1z",
        "2z",
        "3z",
        "4z",
        "5z",
        "6z",
        "7z",
        "5p",
        "8p",
        "3s",
        "6s",
        "9s",
        "9m",
    ),
    Seat.NORTH: (
        "9m",
        "9m",
        "1p",
        "9p",
        "1s",
        "9s",
        "1z",
        "2z",
        "3z",
        "4z",
        "5z",
        "6z",
        "7z",
    ),
}

_RIICHI_HANDS = {
    Seat.EAST: _REACTION_HANDS[Seat.WEST],
    Seat.SOUTH: INERT_HAND,
    Seat.WEST: INERT_HAND,
    Seat.NORTH: INERT_HAND,
}


def _selectors(selector):
    return {seat: selector for seat in Seat}


def _winning_first_selector(
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


def _choose_type(options, descriptor_type):
    return next(option for option in options if isinstance(option, descriptor_type))


def _reaction_state(*, hands=_REACTION_HANDS, rules=None):
    state = dealt_state(
        hands=hands,
        draws=("8s",),
        with_dead_wall=True,
        rules=rules,
    )
    draw_and_discard(state, Seat.EAST, "7p")
    return state


def _pass_only_reaction_state():
    hands = {
        Seat.EAST: _REACTION_HANDS[Seat.EAST],
        Seat.SOUTH: _REACTION_HANDS[Seat.SOUTH],
        Seat.WEST: INERT_HAND,
        Seat.NORTH: INERT_HAND,
    }
    return _reaction_state(hands=hands)


def _kakan_state():
    state = dealt_state(
        hands=_KAKAN_HANDS,
        draws=("5z", "4p", "6z", "5z", "3p"),
        with_dead_wall=True,
    )
    draw_and_discard(state, Seat.EAST, "3p")
    resolve_with(state, {Seat.SOUTH: pon_action(state, Seat.SOUTH)})
    discard(state, Seat.SOUTH, "1z")
    draw_and_discard(state, Seat.WEST, "9s")
    play_quiet_turn(state)
    play_quiet_turn(state)
    state.draw(Seat.SOUTH)
    snapshot = state.legal_actions(Seat.SOUTH)
    state.apply(
        Seat.SOUTH,
        action_of_type(state, Seat.SOUTH, KakanLegalAction),
        expected_revision=snapshot.revision,
    )
    return state


def _ankan_state():
    rules = replace(RuleSet.default(), kokushi_ankan_chankan_enabled=True)
    state = dealt_state(
        hands=_ANKAN_HANDS,
        draws=("8s",),
        with_dead_wall=True,
        rules=rules,
    )
    state.draw(Seat.EAST)
    snapshot = state.legal_actions(Seat.EAST)
    state.apply(
        Seat.EAST,
        action_of_type(state, Seat.EAST, AnkanLegalAction),
        expected_revision=snapshot.revision,
    )
    return state


def _match_with_active_round(round_state):
    match = MatchState(seed=99, rules=round_state.rules)
    match._phase = MatchPhase.ROUND_IN_PROGRESS
    match._active_round = round_state
    return match


class SelectorValidationTest(unittest.TestCase):
    def test_requires_a_match_state_before_validating_selectors(self) -> None:
        with self.assertRaises(TypeError):
            run_hanchan(object(), {})

    def test_requires_exactly_four_callable_selectors(self) -> None:
        valid = _selectors(_winning_first_selector)
        cases = (
            {Seat.EAST: _winning_first_selector},
            {**valid, "extra": _winning_first_selector},
            {**valid, Seat.NORTH: None},
        )

        for selectors in cases:
            with self.subTest(selectors=selectors):
                with self.assertRaises((TypeError, ValueError)):
                    run_hanchan(MatchState(seed=1), selectors)

    def test_selector_exception_wrong_type_and_unoffered_choice_are_atomic(
        self,
    ) -> None:
        def fail(_observation, _options):
            raise LookupError("selector failed")

        bad_selectors = (
            fail,
            lambda _observation, _options: object(),
            lambda _observation, _options: PassActionDescriptor(
                _options[0].tile,
                Seat.SOUTH,
            ),
        )
        for selector in bad_selectors:
            match = MatchState(seed=7)
            round_state = match.start_round()
            round_state.draw(round_state.current_seat)
            before = capture(round_state)

            with self.subTest(selector=selector):
                with self.assertRaises((LookupError, TypeError, ValueError)) as raised:
                    run_hanchan(match, _selectors(selector))
                self.assertEqual(capture(round_state), before)
                message = str(raised.exception)
                self.assertNotIn("LegalAction", message)
                self.assertNotIn("tile_id", message)
                self.assertNotIn("seed", message)


class ReactionDriverTest(unittest.TestCase):
    def test_builds_all_inputs_before_callbacks_and_calls_pass_only_seats(self) -> None:
        round_state = _pass_only_reaction_state()
        match = _match_with_active_round(round_state)
        before = capture(round_state)
        built = []
        called = []

        from lisjong_engine import driver

        original = driver._build_decision_snapshot

        def recording_builder(*args):
            decision = original(*args)
            built.append(decision)
            return decision

        def selector(observation, options):
            self.assertEqual(len(built), 3)
            self.assertEqual(capture(round_state), before)
            called.append((observation.viewer_seat, options))
            return _choose_type(options, PassActionDescriptor)

        with patch(
            "lisjong_engine.driver._build_decision_snapshot",
            side_effect=recording_builder,
        ):
            _resolve_reaction_choices(match, round_state, _selectors(selector))

        self.assertEqual(
            tuple(seat for seat, _options in called),
            (Seat.SOUTH, Seat.WEST, Seat.NORTH),
        )
        self.assertEqual(
            {decision.projection.revision for decision in built},
            {before[2]},
        )
        self.assertTrue(any(len(options) == 1 for _seat, options in called))
        self.assertIs(round_state.phase, RoundPhase.AWAITING_DRAW)
        self.assertEqual(round_state.revision, before[2] + 1)

    def test_selector_exception_and_invalid_choice_leave_entire_window_unchanged(
        self,
    ) -> None:
        for invalid_choice in (False, True):
            round_state = _reaction_state()
            match = _match_with_active_round(round_state)
            before = capture(round_state)
            calls = []

            def selector(observation, options):
                calls.append(observation.viewer_seat)
                if observation.viewer_seat is Seat.NORTH:
                    if invalid_choice:
                        return NineTerminalsActionDescriptor()
                    raise LookupError("reaction selector failed")
                return _choose_type(options, PassActionDescriptor)

            with self.subTest(invalid_choice=invalid_choice):
                with self.assertRaises((LookupError, ValueError)):
                    _resolve_reaction_choices(
                        match,
                        round_state,
                        _selectors(selector),
                    )
                self.assertEqual(capture(round_state), before)
                self.assertEqual(calls, [Seat.SOUTH, Seat.WEST, Seat.NORTH])

    def test_existing_resolver_decides_pon_over_chi(self) -> None:
        round_state = _reaction_state()
        match = _match_with_active_round(round_state)

        def selector(observation, options):
            if observation.viewer_seat is Seat.SOUTH:
                return _choose_type(options, ChiActionDescriptor)
            if observation.viewer_seat is Seat.NORTH:
                return _choose_type(options, PonActionDescriptor)
            return _choose_type(options, PassActionDescriptor)

        _resolve_reaction_choices(match, round_state, _selectors(selector))

        self.assertIs(round_state.current_seat, Seat.NORTH)
        self.assertEqual(len(round_state.melds(Seat.NORTH)), 1)
        self.assertEqual(round_state.melds(Seat.SOUTH), ())

    def test_double_ron_and_head_bump_follow_rule_set(self) -> None:
        cases = (
            (RuleSet.default(), (Seat.WEST, Seat.NORTH)),
            (
                replace(
                    RuleSet.default(),
                    ron_resolution_policy=RonResolutionPolicy.HEAD_BUMP,
                    triple_ron_abortive_draw=False,
                ),
                (Seat.WEST,),
            ),
        )
        for rules, expected_winners in cases:
            round_state = _reaction_state(hands=_DOUBLE_RON_HANDS, rules=rules)
            match = _match_with_active_round(round_state)

            def selector(observation, options):
                if observation.viewer_seat in (Seat.WEST, Seat.NORTH):
                    return _choose_type(options, RonActionDescriptor)
                return _choose_type(options, PassActionDescriptor)

            with self.subTest(policy=rules.ron_resolution_policy):
                _resolve_reaction_choices(match, round_state, _selectors(selector))
                self.assertEqual(
                    round_state.pending_ron_resolution.winner_seats,
                    expected_winners,
                )

    def test_kakan_and_ankan_chankan_use_the_declarer_as_public_source(self) -> None:
        cases = (
            (_kakan_state(), Seat.WEST, Seat.SOUTH),
            (_ankan_state(), Seat.NORTH, Seat.EAST),
        )
        for round_state, winning_seat, declarer in cases:
            match = _match_with_active_round(round_state)
            seen_source = []

            def selector(observation, options):
                ron = next(
                    (
                        option
                        for option in options
                        if isinstance(option, RonActionDescriptor)
                    ),
                    None,
                )
                if observation.viewer_seat is winning_seat and ron is not None:
                    seen_source.append(ron.from_seat)
                    return ron
                return _choose_type(options, PassActionDescriptor)

            with self.subTest(phase=round_state.phase):
                _resolve_reaction_choices(match, round_state, _selectors(selector))
                self.assertEqual(seen_source, [declarer])
                self.assertIs(round_state.phase, RoundPhase.AWAITING_WIN_FINALIZATION)
                self.assertEqual(
                    round_state.pending_ron_resolution.winner_seats,
                    (winning_seat,),
                )


class ForcedTransitionAndRiichiTest(unittest.TestCase):
    def test_kakan_all_pass_then_rinshan_draw_does_not_call_selector(self) -> None:
        round_state = _kakan_state()
        match = _match_with_active_round(round_state)

        def choose_pass(_observation, options):
            return _choose_type(options, PassActionDescriptor)

        _resolve_reaction_choices(match, round_state, _selectors(choose_pass))
        rinshan_before = round_state.remaining_rinshan_count

        def unexpected(_observation, _options):
            self.fail("forced rinshan draw must not call a selector")

        _advance_round(match, round_state, _selectors(unexpected))

        self.assertIs(round_state.phase, RoundPhase.AWAITING_DISCARD)
        self.assertEqual(round_state.remaining_rinshan_count, rinshan_before - 1)

    def test_pending_ron_finalization_does_not_call_selector(self) -> None:
        round_state = _reaction_state()
        match = _match_with_active_round(round_state)

        def choose_ron(observation, options):
            if observation.viewer_seat is Seat.WEST:
                return _choose_type(options, RonActionDescriptor)
            return _choose_type(options, PassActionDescriptor)

        _resolve_reaction_choices(match, round_state, _selectors(choose_ron))

        def unexpected(_observation, _options):
            self.fail("win finalization must not call a selector")

        _advance_round(match, round_state, _selectors(unexpected))

        self.assertIs(round_state.phase, RoundPhase.FINISHED)
        self.assertIsNotNone(round_state.result)

    def test_riichi_discard_progresses_through_the_public_descriptor(self) -> None:
        round_state = dealt_state(
            hands=_RIICHI_HANDS,
            draws=("5z",),
            with_dead_wall=True,
        )
        round_state.draw(Seat.EAST)
        match = _match_with_active_round(round_state)

        def choose_riichi(_observation, options):
            return _choose_type(options, RiichiDiscardActionDescriptor)

        _apply_turn_choice(match, round_state, _selectors(choose_riichi))
        if round_state.phase is RoundPhase.AWAITING_REACTIONS:
            _resolve_reaction_choices(
                match,
                round_state,
                _selectors(
                    lambda _observation, options: _choose_type(
                        options,
                        PassActionDescriptor,
                    )
                ),
            )

        self.assertTrue(round_state.is_riichi_established(Seat.EAST))


class DriverResumeAndEndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.from_awaiting_round = MatchState(seed=12345)
        cls.first_result = run_hanchan(
            cls.from_awaiting_round,
            _selectors(_winning_first_selector),
        )

        cls.from_round_in_progress = MatchState(seed=12345)
        cls.from_round_in_progress.start_round()
        cls.second_result = run_hanchan(
            cls.from_round_in_progress,
            _selectors(_winning_first_selector),
        )

    def test_completes_a_deterministic_multi_round_hanchan(self) -> None:
        match = self.from_awaiting_round
        completed = self.first_result

        self.assertIs(match.phase, MatchPhase.FINISHED)
        self.assertIs(match.completed_match, completed)
        self.assertGreater(len(completed.history), 1)
        self.assertTrue(all(item.result is not None for item in completed.history))
        self.assertTrue(all(item.settlement is not None for item in completed.history))
        self.assertIsNotNone(completed.final_raw_scores)
        self.assertIsNotNone(completed.final_score)

    def test_same_seed_selectors_and_resume_point_produce_same_result(self) -> None:
        self.assertEqual(self.first_result, self.second_result)
        self.assertEqual(
            self.from_awaiting_round.history,
            self.from_round_in_progress.history,
        )

    def test_finished_match_returns_existing_result_without_callback(self) -> None:
        def unexpected(_observation, _options):
            self.fail("selector must not be called for a finished match")

        returned = run_hanchan(
            self.from_awaiting_round,
            _selectors(unexpected),
        )

        self.assertIs(returned, self.first_result)

    def test_finished_match_still_validates_selector_mapping(self) -> None:
        with self.assertRaises(ValueError):
            run_hanchan(
                self.from_awaiting_round,
                {Seat.EAST: _winning_first_selector},
            )

    def test_invalid_match_phase_shape_fails_closed(self) -> None:
        match = MatchState(seed=1)
        match._active_round = _reaction_state()

        with self.assertRaises(DriverStateError):
            run_hanchan(match, _selectors(_winning_first_selector))


if __name__ == "__main__":
    unittest.main()
