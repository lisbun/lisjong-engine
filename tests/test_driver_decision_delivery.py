"""transaction-committed selector decision delivery（Issue #56）のtest。"""

import unittest
from dataclasses import FrozenInstanceError, fields, is_dataclass
from unittest.mock import patch

from _round_fixtures import (
    INERT_HAND,
    capture,
    dealt_state,
    discard,
    draw_and_discard,
    play_quiet_turn,
    pon_action,
    resolve_with,
)

from lisjong_engine.action_descriptor import (
    ACTION_DESCRIPTOR_TYPES,
    AnkanActionDescriptor,
    ChiActionDescriptor,
    DiscardActionDescriptor,
    KakanActionDescriptor,
    NineTerminalsActionDescriptor,
    PassActionDescriptor,
    PonActionDescriptor,
    RiichiActionDescriptor,
    RonActionDescriptor,
    TsumoActionDescriptor,
)
from lisjong_engine.action_projection import ActionProjection
from lisjong_engine.driver import _advance_round, run_hanchan
from lisjong_engine.legal_action import LegalAction, LegalActionSnapshot
from lisjong_engine.match_state import CompletedMatch, MatchPhase, MatchState
from lisjong_engine.observation import ObservationDecisionKind
from lisjong_engine.player_state import PlayerState
from lisjong_engine.reaction import ReactionResolution
from lisjong_engine.round_allocation import RoundRandomProvenance
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.round_state import RoundState
from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile
from lisjong_engine.wall import Wall

_RIICHI_HANDS = {
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
        "5p",
        "6p",
        "2s",
        "2s",
    ),
    Seat.SOUTH: INERT_HAND,
    Seat.WEST: INERT_HAND,
    Seat.NORTH: INERT_HAND,
}

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

_PASS_ONLY_REACTION_HANDS = {
    Seat.EAST: _REACTION_HANDS[Seat.EAST],
    Seat.SOUTH: _REACTION_HANDS[Seat.SOUTH],
    Seat.WEST: INERT_HAND,
    Seat.NORTH: INERT_HAND,
}

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

_NINE_TERMINALS_HAND = (
    "1m",
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
)

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

_RON_HANDS = {
    Seat.EAST: INERT_HAND,
    Seat.SOUTH: (
        "2m",
        "3m",
        "4p",
        "5p",
        "6p",
        "7s",
        "8s",
        "9s",
        "1z",
        "1z",
        "1z",
        "2z",
        "2z",
    ),
    Seat.WEST: (
        "2m",
        "3m",
        "1p",
        "2p",
        "3p",
        "4s",
        "5s",
        "6s",
        "3z",
        "3z",
        "3z",
        "4z",
        "4z",
    ),
    Seat.NORTH: (
        "2m",
        "3m",
        "4p",
        "5p",
        "6p",
        "7s",
        "8s",
        "9s",
        "5z",
        "5z",
        "5z",
        "6z",
        "6z",
    ),
}

_FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "tile_id",
        "tile_ids",
        "consumed_tile_ids",
        "added_tile_id",
        "target_tile_id",
        "seed",
        "match_seed",
        "round_seed",
        "round_ordinal",
        "random_provenance",
        "wall",
        "dead_wall",
        "resolution",
        "reaction_resolution",
        "history",
    }
)
_FORBIDDEN_TYPES = (
    LegalAction,
    LegalActionSnapshot,
    ActionProjection,
    Tile,
    Wall,
    RoundState,
    MatchState,
    CompletedMatch,
    PlayerState,
    ReactionResolution,
    RoundRandomProvenance,
)


def _selectors(selector):
    return {seat: selector for seat in Seat}


def _choose(options, descriptor_type):
    return next(option for option in options if isinstance(option, descriptor_type))


def _hands_with(seat, hand):
    hands = {other: INERT_HAND for other in Seat}
    hands[seat] = hand
    return hands


def _match_with_active_round(round_state):
    match = MatchState(seed=99, rules=round_state.rules)
    match._phase = MatchPhase.ROUND_IN_PROGRESS
    match._active_round = round_state
    return match


def _quiet_turn_state():
    state = dealt_state(
        hands={seat: INERT_HAND for seat in Seat},
        draws=("5z",),
        with_dead_wall=True,
    )
    state.draw(Seat.EAST)
    return state


def _reaction_state(*, hands=_REACTION_HANDS, draw="8s", discarded="7p"):
    state = dealt_state(hands=hands, draws=(draw,), with_dead_wall=True)
    draw_and_discard(
        state,
        Seat.EAST,
        None if draw == discarded else discarded,
    )
    return state


def _kakan_turn_state():
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
    return state


def _recursive_assert_safe(test_case, value, seen=None):
    if seen is None:
        seen = set()
    if id(value) in seen:
        return
    seen.add(id(value))

    test_case.assertNotIsInstance(value, _FORBIDDEN_TYPES)
    if is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            test_case.assertNotIn(field.name, _FORBIDDEN_FIELD_NAMES)
            _recursive_assert_safe(test_case, getattr(value, field.name), seen)
    elif isinstance(value, (tuple, list, frozenset, set)):
        for item in value:
            _recursive_assert_safe(test_case, item, seen)
    elif isinstance(value, dict):
        for key, item in value.items():
            _recursive_assert_safe(test_case, key, seen)
            _recursive_assert_safe(test_case, item, seen)


class TurnDecisionDeliveryTest(unittest.TestCase):
    def test_normal_discard_delivers_same_snapshot_after_transaction(self) -> None:
        state = _quiet_turn_state()
        match = _match_with_active_round(state)
        before_revision = state.revision
        selector_inputs = []
        commits = []
        ordering = []

        def selector(observation, options):
            selected = _choose(options, DiscardActionDescriptor)
            selector_inputs.append((observation, options, selected))
            return selected

        def on_decision(commit):
            ordering.append("decision")
            commits.append(commit)

        _advance_round(
            match,
            state,
            _selectors(selector),
            lambda _facts: ordering.append("delivery"),
            len(state.events),
            on_decision,
        )

        self.assertEqual(ordering, ["delivery", "decision"])
        self.assertEqual(len(commits), 1)
        decision = commits[0].decisions[0]
        observation, options, selected = selector_inputs[0]
        self.assertIs(decision.seat, Seat.EAST)
        self.assertEqual(decision.revision, before_revision)
        self.assertIs(decision.observation, observation)
        self.assertIs(decision.legal_actions, options)
        self.assertIs(decision.selected_action, selected)
        self.assertIn(decision.selected_action, decision.legal_actions)
        self.assertGreater(state.revision, decision.revision)

    def test_one_option_riichi_discard_is_a_separate_commit(self) -> None:
        state = dealt_state(
            hands=_RIICHI_HANDS,
            draws=("5z",),
            with_dead_wall=True,
        )
        state.draw(Seat.EAST)
        match = _match_with_active_round(state)
        commits = []
        progress = []

        def selector(observation, options):
            if observation.decision_kind is ObservationDecisionKind.TURN:
                return _choose(options, RiichiActionDescriptor)
            return options[0]

        cursor = len(state.events)
        cursor = _advance_round(
            match,
            state,
            _selectors(selector),
            progress.append,
            cursor,
            commits.append,
        )
        self.assertEqual(progress, [])
        _advance_round(
            match,
            state,
            _selectors(selector),
            progress.append,
            cursor,
            commits.append,
        )

        self.assertEqual(len(commits), 2)
        first, second = (commit.decisions[0] for commit in commits)
        self.assertIs(first.observation.decision_kind, ObservationDecisionKind.TURN)
        self.assertIsInstance(first.selected_action, RiichiActionDescriptor)
        self.assertIs(
            second.observation.decision_kind,
            ObservationDecisionKind.RIICHI_DISCARD,
        )
        self.assertEqual(len(second.legal_actions), 1)
        self.assertIsInstance(second.selected_action, DiscardActionDescriptor)
        self.assertGreater(second.revision, first.revision)

    def test_representative_turn_actions_are_delivered(self) -> None:
        cases = []

        tsumo = dealt_state(
            hands=_hands_with(Seat.EAST, _TSUMO_HAND),
            draws=("7p",),
            with_dead_wall=True,
        )
        tsumo.draw(Seat.EAST)
        cases.append((tsumo, TsumoActionDescriptor))

        ankan = dealt_state(
            hands=_ANKAN_HANDS,
            draws=("8s",),
            with_dead_wall=True,
        )
        ankan.draw(Seat.EAST)
        cases.append((ankan, AnkanActionDescriptor))

        cases.append((_kakan_turn_state(), KakanActionDescriptor))

        nine = dealt_state(
            hands=_hands_with(Seat.EAST, _NINE_TERMINALS_HAND),
            draws=("2m",),
            with_dead_wall=True,
        )
        nine.draw(Seat.EAST)
        cases.append((nine, NineTerminalsActionDescriptor))

        for state, descriptor_type in cases:
            match = _match_with_active_round(state)
            commits = []

            with self.subTest(descriptor_type=descriptor_type.__name__):
                _advance_round(
                    match,
                    state,
                    _selectors(
                        lambda _observation, options, kind=descriptor_type: _choose(
                            options, kind
                        )
                    ),
                    event_cursor=len(state.events),
                    on_selector_decision_commit=commits.append,
                )
                self.assertEqual(len(commits), 1)
                self.assertIsInstance(
                    commits[0].decisions[0].selected_action,
                    descriptor_type,
                )


class ReactionDecisionDeliveryTest(unittest.TestCase):
    def test_all_pass_keeps_all_three_seats_in_canonical_order(self) -> None:
        state = _reaction_state(hands=_PASS_ONLY_REACTION_HANDS)
        match = _match_with_active_round(state)
        reacting_seats = state.reacting_seats
        revision = state.revision
        commits = []

        _advance_round(
            match,
            state,
            _selectors(
                lambda _observation, options: _choose(options, PassActionDescriptor)
            ),
            event_cursor=len(state.events),
            on_selector_decision_commit=commits.append,
        )

        self.assertEqual(len(commits), 1)
        decisions = commits[0].decisions
        self.assertEqual(tuple(item.seat for item in decisions), reacting_seats)
        self.assertEqual({item.revision for item in decisions}, {revision})
        self.assertTrue(
            all(
                isinstance(item.selected_action, PassActionDescriptor)
                for item in decisions
            )
        )
        self.assertTrue(any(len(item.legal_actions) == 1 for item in decisions))

    def test_chi_and_pon_choices_survive_pon_resolution(self) -> None:
        state = _reaction_state()
        match = _match_with_active_round(state)
        commits = []

        def selector(observation, options):
            if observation.viewer_seat is Seat.SOUTH:
                return _choose(options, ChiActionDescriptor)
            if observation.viewer_seat is Seat.NORTH:
                return _choose(options, PonActionDescriptor)
            return _choose(options, PassActionDescriptor)

        _advance_round(
            match,
            state,
            _selectors(selector),
            event_cursor=len(state.events),
            on_selector_decision_commit=commits.append,
        )

        selected = {
            decision.seat: type(decision.selected_action)
            for decision in commits[0].decisions
        }
        self.assertEqual(
            selected,
            {
                Seat.SOUTH: ChiActionDescriptor,
                Seat.WEST: PassActionDescriptor,
                Seat.NORTH: PonActionDescriptor,
            },
        )
        self.assertEqual(state.melds(Seat.SOUTH), ())
        self.assertEqual(len(state.melds(Seat.NORTH)), 1)

    def test_all_selected_ron_choices_survive_resolver_outcome(self) -> None:
        state = _reaction_state(hands=_RON_HANDS, draw="1m", discarded="1m")
        match = _match_with_active_round(state)
        commits = []

        _advance_round(
            match,
            state,
            _selectors(
                lambda _observation, options: _choose(options, RonActionDescriptor)
            ),
            event_cursor=len(state.events),
            on_selector_decision_commit=commits.append,
        )

        self.assertEqual(len(commits[0].decisions), 3)
        self.assertTrue(
            all(
                isinstance(decision.selected_action, RonActionDescriptor)
                for decision in commits[0].decisions
            )
        )
        self.assertIs(state.phase, RoundPhase.AWAITING_WIN_FINALIZATION)


class FailureBoundaryTest(unittest.TestCase):
    def test_selector_and_projection_failures_do_not_publish(self) -> None:
        cases = (
            lambda _observation, _options: (_ for _ in ()).throw(
                LookupError("selector failed")
            ),
            lambda _observation, _options: object(),
            lambda _observation, _options: NineTerminalsActionDescriptor(),
        )
        for selector in cases:
            state = _quiet_turn_state()
            match = _match_with_active_round(state)
            before = capture(state)
            commits = []

            with (
                self.subTest(selector=selector),
                self.assertRaises((LookupError, TypeError, ValueError)),
            ):
                _advance_round(
                    match,
                    state,
                    _selectors(selector),
                    event_cursor=len(state.events),
                    on_selector_decision_commit=commits.append,
                )
            self.assertEqual(commits, [])
            self.assertEqual(capture(state), before)

        state = _quiet_turn_state()
        match = _match_with_active_round(state)
        commits = []
        with (
            patch.object(
                ActionProjection,
                "resolve",
                side_effect=RuntimeError("resolve failed"),
            ),
            self.assertRaisesRegex(RuntimeError, "resolve failed"),
        ):
            _advance_round(
                match,
                state,
                _selectors(lambda _observation, options: options[0]),
                event_cursor=len(state.events),
                on_selector_decision_commit=commits.append,
            )
        self.assertEqual(commits, [])

    def test_turn_apply_and_reaction_resolution_failures_do_not_publish(self) -> None:
        turn = _quiet_turn_state()
        turn_match = _match_with_active_round(turn)
        turn_commits = []
        with (
            patch.object(
                RoundState,
                "apply",
                side_effect=RuntimeError("apply failed"),
            ),
            self.assertRaisesRegex(RuntimeError, "apply failed"),
        ):
            _advance_round(
                turn_match,
                turn,
                _selectors(lambda _observation, options: options[0]),
                event_cursor=len(turn.events),
                on_selector_decision_commit=turn_commits.append,
            )
        self.assertEqual(turn_commits, [])

        reaction = _reaction_state()
        reaction_match = _match_with_active_round(reaction)
        reaction_commits = []
        with (
            patch.object(
                RoundState,
                "resolve_reactions",
                side_effect=RuntimeError("reaction failed"),
            ),
            self.assertRaisesRegex(RuntimeError, "reaction failed"),
        ):
            _advance_round(
                reaction_match,
                reaction,
                _selectors(
                    lambda _observation, options: _choose(options, PassActionDescriptor)
                ),
                event_cursor=len(reaction.events),
                on_selector_decision_commit=reaction_commits.append,
            )
        self.assertEqual(reaction_commits, [])

    def test_existing_delivery_failure_prevents_decision_publication(self) -> None:
        state = _quiet_turn_state()
        match = _match_with_active_round(state)
        commits = []

        with self.assertRaisesRegex(RuntimeError, "delivery failed"):
            run_hanchan(
                match,
                _selectors(lambda _observation, options: options[0]),
                on_delivery=lambda _facts: (_ for _ in ()).throw(
                    RuntimeError("delivery failed")
                ),
                on_selector_decision_commit=commits.append,
            )
        self.assertEqual(commits, [])

    def test_decision_callback_failure_is_fail_fast_after_commit(self) -> None:
        state = _quiet_turn_state()
        match = _match_with_active_round(state)
        before_revision = state.revision
        selector_calls = []
        ordering = []

        def selector(observation, options):
            selector_calls.append(observation.viewer_seat)
            return options[0]

        def fail_decision(_commit):
            ordering.append("decision")
            raise RuntimeError("decision failed")

        with self.assertRaisesRegex(RuntimeError, "decision failed"):
            run_hanchan(
                match,
                _selectors(selector),
                on_delivery=lambda _facts: ordering.append("delivery"),
                on_selector_decision_commit=fail_decision,
            )

        self.assertEqual(ordering, ["delivery", "decision"])
        self.assertEqual(selector_calls, [Seat.EAST])
        self.assertGreater(state.revision, before_revision)
        self.assertIs(state.current_seat, Seat.SOUTH)
        self.assertIs(state.phase, RoundPhase.AWAITING_DRAW)

    def test_rejects_non_callable_callback_before_transition(self) -> None:
        match = MatchState(seed=1)
        with self.assertRaises(TypeError):
            run_hanchan(
                match,
                _selectors(lambda _observation, options: options[0]),
                on_selector_decision_commit="not-callable",
            )
        self.assertIs(match.phase, MatchPhase.AWAITING_ROUND)


class SafetyAndRegressionTest(unittest.TestCase):
    def test_payload_is_immutable_and_recursively_excludes_internal_values(
        self,
    ) -> None:
        state = _reaction_state()
        match = _match_with_active_round(state)
        commits = []
        _advance_round(
            match,
            state,
            _selectors(
                lambda _observation, options: _choose(options, PassActionDescriptor)
            ),
            event_cursor=len(state.events),
            on_selector_decision_commit=commits.append,
        )
        commit = commits[0]

        _recursive_assert_safe(self, commit)
        self.assertTrue(
            all(
                isinstance(action, ACTION_DESCRIPTOR_TYPES)
                for action in commit.decisions[0].legal_actions
            )
        )
        with self.assertRaises(FrozenInstanceError):
            commit.decisions = ()
        with self.assertRaises(FrozenInstanceError):
            commit.decisions[0].revision = 0

    def test_same_seed_and_selectors_reproduce_first_public_commit(self) -> None:
        def run_once():
            commits = []

            def stop_after_first(commit):
                commits.append(commit)
                raise RuntimeError("stop after first commit")

            with self.assertRaisesRegex(RuntimeError, "stop after first commit"):
                run_hanchan(
                    MatchState(seed=12345),
                    _selectors(lambda _observation, options: options[0]),
                    on_selector_decision_commit=stop_after_first,
                )
            return commits[0]

        self.assertEqual(run_once(), run_once())

    def test_omitted_and_explicit_none_preserve_selector_order_and_state(self) -> None:
        def advance(explicit):
            state = _quiet_turn_state()
            match = _match_with_active_round(state)
            calls = []
            kwargs = {} if not explicit else {"on_selector_decision_commit": None}
            _advance_round(
                match,
                state,
                _selectors(
                    lambda observation, options: (
                        calls.append(observation.viewer_seat),
                        options[0],
                    )[1]
                ),
                event_cursor=len(state.events),
                **kwargs,
            )
            return calls, capture(state)

        self.assertEqual(advance(False), advance(True))


if __name__ == "__main__":
    unittest.main()
