import unittest
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, fields, is_dataclass
from unittest.mock import patch

from _round_fixtures import (
    QUIET_DRAWS,
    QUIET_HANDS,
    advance_to_seat,
    build_wall,
    capture,
    dealt_state,
    new_state,
    pon_action,
    quiet_state,
    resolve_all_pass,
    resolve_with,
    ron_action,
)
from test_driver import _match_at_position, _selectors, _winning_first_selector
from test_round_state import (
    _ANKAN_DRAWS,
    _ANKAN_HANDS,
    _KOKUSHI_CHANKAN_RULES,
    _declare_ankan,
    _double_ron_state,
    _kakan_declared_state,
    _reaction_state,
    _riichi_declaration_state,
    _riichi_state,
    _select_riichi,
)
from test_round_winning import _kakan_ron_state, _ron_state

from lisjong_engine.driver import run_hanchan
from lisjong_engine.furiten import FuritenReason
from lisjong_engine.legal_action import DiscardLegalAction
from lisjong_engine.match_state import MatchState, RoundPosition
from lisjong_engine.meld import Kakan, Pon
from lisjong_engine.riichi_event import RiichiDeclarationOutcome
from lisjong_engine.round_event import (
    DrawSource,
    KanConfirmedEvent,
    KanDeclaredEvent,
    MissedRonRecordedEvent,
    ReactionsResolvedEvent,
    RiichiFinalizedEvent,
    RoundEndedEvent,
    RoundStartedEvent,
    TileDiscardedEvent,
    TileDrawnEvent,
)
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.round_result import AbortiveDrawReason, AbortiveDrawResult
from lisjong_engine.round_state import (
    IllegalOperationError,
    RoundState,
    StaleActionError,
)
from lisjong_engine.seat import Seat
from lisjong_engine.transaction_observation import (
    RoundCheckpoint,
    SeatCheckpoint,
    TransactionObservation,
    TransactionStep,
)
from lisjong_engine.transaction_observation import TransactionStepKind as K
from lisjong_engine.win_context import RiichiStatus
from lisjong_engine.wind import Wind


def kinds(state) -> tuple[K, ...]:
    return tuple(step.kind for step in state.last_transaction_steps)


def last(state) -> RoundCheckpoint:
    return state.last_transaction_steps[-1].checkpoint


@contextmanager
def observing():
    """fixtureが内部で作るRoundStateを、作成直後から観測する。"""
    original = RoundState.__init__

    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.enable_transaction_observation()

    with patch.object(RoundState, "__init__", init):
        yield


def observed(state):
    state.enable_transaction_observation()
    return state


class OptInTest(unittest.TestCase):
    def test_disabled_observation_is_unavailable(self) -> None:
        state = quiet_state()
        with self.assertRaises(IllegalOperationError):
            state.last_transaction_steps

    def test_observation_does_not_change_transitions(self) -> None:
        plain, watched = quiet_state(), observed(quiet_state())
        for state in (plain, watched):
            for _ in range(4):
                tile = state.draw(state.current_seat)
                state.apply(
                    state.current_seat,
                    DiscardLegalAction(tile.id),
                    expected_revision=state.revision,
                )
        self.assertEqual(capture(plain), capture(watched))


class TurnStepTest(unittest.TestCase):
    def test_deal_is_one_started_step(self) -> None:
        state = observed(new_state(build_wall(hands=QUIET_HANDS, draws=QUIET_DRAWS)))
        state.deal()
        (step,) = state.last_transaction_steps
        self.assertIs(step.kind, K.ROUND_STARTED)
        self.assertIsInstance(step.events[0], RoundStartedEvent)
        self.assertEqual(len(step.events), 5)
        self.assertTrue(
            all(len(seat.hand_tiles) == 13 for seat in step.checkpoint.seats)
        )
        self.assertEqual(step.checkpoint, state.committed_checkpoint())

    def test_draw_records_the_drawn_tile_and_source(self) -> None:
        state = observed(quiet_state())
        tile = state.draw(Seat.EAST)
        (step,) = state.last_transaction_steps
        self.assertIs(step.kind, K.DRAW)
        self.assertEqual(
            step.events, (TileDrawnEvent(Seat.EAST, tile, DrawSource.LIVE_WALL),)
        )
        east = step.checkpoint.seats[0]
        self.assertEqual(east.drawn_tile, tile)
        self.assertIs(east.drawn_tile_source, DrawSource.LIVE_WALL)
        self.assertIn(tile, east.hand_tiles)

    def test_discard_without_reaction_window_records_no_opportunity(self) -> None:
        state = observed(quiet_state())
        tile = state.draw(Seat.EAST)
        state.apply(
            Seat.EAST, DiscardLegalAction(tile.id), expected_revision=state.revision
        )
        self.assertEqual(kinds(state), (K.TURN_CHOICE, K.REACTION_WINDOW_SKIPPED))
        choice, skipped = state.last_transaction_steps
        self.assertIsInstance(choice.events[0], TileDiscardedEvent)
        self.assertEqual(skipped.events, ())
        self.assertEqual(choice.checkpoint.seats[0].discards[-1].tile, tile)


class RiichiStepTest(unittest.TestCase):
    def test_selection_then_declaration_without_reaction_window(self) -> None:
        state = observed(_riichi_state())
        state.draw(Seat.EAST)
        before = state.committed_checkpoint()
        _select_riichi(state)
        self.assertEqual(kinds(state), (K.TURN_CHOICE,))
        self.assertEqual(last(state), before)
        self.assertIs(state.phase, RoundPhase.AWAITING_RIICHI_DISCARD)

        snapshot = state.legal_actions(Seat.EAST)
        state.apply(Seat.EAST, snapshot.actions[0], expected_revision=snapshot.revision)
        self.assertEqual(
            kinds(state),
            (K.TURN_CHOICE, K.REACTION_WINDOW_SKIPPED, K.RIICHI_FINALIZED),
        )
        choice = state.last_transaction_steps[0].checkpoint
        self.assertIsNotNone(choice.pending_riichi_declaration)
        self.assertIs(choice.seats[0].riichi_status, RiichiStatus.NONE)
        east = last(state).seats[0]
        self.assertIsNot(east.riichi_status, RiichiStatus.NONE)
        self.assertTrue(east.is_ippatsu)
        self.assertIsNone(last(state).pending_riichi_declaration)

    def test_declaration_tile_reactions_decide_establishment(self) -> None:
        with observing():
            state = _riichi_declaration_state()
        self.assertEqual(kinds(state), (K.TURN_CHOICE,))
        self.assertIsNotNone(last(state).pending_riichi_declaration)

        for overrides, status, ippatsu, outcome in (
            (
                {},
                RiichiStatus.DOUBLE_RIICHI,
                True,
                RiichiDeclarationOutcome.ESTABLISHED,
            ),
            (
                {Seat.NORTH: pon_action},
                RiichiStatus.DOUBLE_RIICHI,
                False,
                RiichiDeclarationOutcome.ESTABLISHED,
            ),
            (
                {Seat.WEST: ron_action},
                RiichiStatus.NONE,
                False,
                RiichiDeclarationOutcome.FAILED_BY_RON,
            ),
        ):
            with self.subTest(outcome=outcome, calls=tuple(overrides)), observing():
                state = _riichi_declaration_state()
                resolve_with(
                    state,
                    {seat: make(state, seat) for seat, make in overrides.items()},
                )
                self.assertEqual(
                    kinds(state), (K.REACTION_RESOLVED, K.RIICHI_FINALIZED)
                )
                finalized = state.last_transaction_steps[-1]
                self.assertIsInstance(finalized.events[0], RiichiFinalizedEvent)
                self.assertIs(finalized.events[0].finalization.outcome, outcome)
                east = finalized.checkpoint.seats[0]
                self.assertIs(east.riichi_status, status)
                self.assertIs(east.is_ippatsu, ippatsu)


class ReactionStepTest(unittest.TestCase):
    def test_explicit_pass_records_missed_ron_and_resolution(self) -> None:
        state = observed(_reaction_state())
        resolve_all_pass(state)
        self.assertEqual(kinds(state), (K.REACTION_RESOLVED,))
        (step,) = state.last_transaction_steps
        self.assertIsInstance(step.events[0], ReactionsResolvedEvent)
        self.assertIsInstance(step.events[1], MissedRonRecordedEvent)
        west = step.checkpoint.seats[2]
        self.assertIs(west.missed_ron_furiten, FuritenReason.TEMPORARY)

    def test_own_draw_clears_temporary_missed_ron(self) -> None:
        state = _reaction_state()
        resolve_all_pass(state)
        advance_to_seat(state, Seat.WEST)
        state.enable_transaction_observation()
        before = state.committed_checkpoint()
        state.draw(Seat.WEST)
        self.assertIs(before.seats[2].missed_ron_furiten, FuritenReason.TEMPORARY)
        self.assertIsNone(last(state).seats[2].missed_ron_furiten)

    def test_call_is_applied_inside_the_resolution_step(self) -> None:
        state = observed(_reaction_state())
        resolve_with(state, {Seat.NORTH: pon_action(state, Seat.NORTH)})
        self.assertEqual(kinds(state), (K.REACTION_RESOLVED,))
        self.assertIsInstance(last(state).seats[3].melds[-1], Pon)
        self.assertIs(state.phase, RoundPhase.AWAITING_DISCARD)

    def test_ron_then_finalization_ends_the_round(self) -> None:
        state = observed(_double_ron_state())
        resolve_with(state, {Seat.WEST: ron_action(state, Seat.WEST)})
        self.assertEqual(kinds(state), (K.REACTION_RESOLVED,))
        self.assertIs(last(state).seats[3].missed_ron_furiten, FuritenReason.TEMPORARY)
        state.finalize_pending_win(expected_revision=state.revision)
        self.assertEqual(kinds(state), (K.ROUND_ENDED,))
        self.assertIsInstance(
            state.last_transaction_steps[0].events[-1], RoundEndedEvent
        )

    def test_triple_ron_ends_as_abortive_draw(self) -> None:
        state = observed(_ron_state())
        resolve_with(
            state,
            {
                seat: ron_action(state, seat)
                for seat in (Seat.SOUTH, Seat.WEST, Seat.NORTH)
            },
        )
        state.finalize_pending_win(expected_revision=state.revision)
        (step,) = state.last_transaction_steps
        self.assertIs(step.kind, K.ROUND_ENDED)
        self.assertEqual(
            step.events[-1].result,
            AbortiveDrawResult(AbortiveDrawReason.TRIPLE_RON),
        )


class KanStepTest(unittest.TestCase):
    def test_ankan_without_window_is_declared_skipped_and_confirmed(self) -> None:
        state = observed(
            dealt_state(hands=_ANKAN_HANDS, draws=_ANKAN_DRAWS, with_dead_wall=True)
        )
        state.draw(Seat.EAST)
        _declare_ankan(state)
        self.assertEqual(
            kinds(state),
            (K.TURN_CHOICE, K.REACTION_WINDOW_SKIPPED, K.KAN_CONFIRMED),
        )
        choice, skipped, confirmed = state.last_transaction_steps
        self.assertIsInstance(choice.events[0], KanDeclaredEvent)
        self.assertIsNotNone(choice.checkpoint.pending_ankan)
        self.assertEqual(choice.checkpoint.seats[0].melds, ())
        self.assertIsNone(skipped.checkpoint.pending_ankan)
        self.assertIsInstance(confirmed.events[0], KanConfirmedEvent)
        self.assertEqual(len(confirmed.checkpoint.revealed_dora_indicators), 2)
        self.assertIsNone(confirmed.checkpoint.seats[0].drawn_tile)

        tile = state.draw_rinshan(Seat.EAST)
        self.assertEqual(kinds(state), (K.DRAW,))
        self.assertEqual(last(state).seats[0].drawn_tile, tile)
        self.assertIs(last(state).seats[0].drawn_tile_source, DrawSource.RINSHAN)

    def test_enabled_ankan_chankan_window_then_confirmation(self) -> None:
        state = observed(
            dealt_state(
                hands=_ANKAN_HANDS,
                draws=_ANKAN_DRAWS,
                with_dead_wall=True,
                rules=_KOKUSHI_CHANKAN_RULES,
            )
        )
        state.draw(Seat.EAST)
        _declare_ankan(state)
        self.assertEqual(kinds(state), (K.TURN_CHOICE,))
        self.assertIs(state.phase, RoundPhase.AWAITING_ANKAN_REACTIONS)
        resolve_all_pass(state)
        self.assertEqual(kinds(state), (K.REACTION_RESOLVED, K.KAN_CONFIRMED))

    def test_kakan_waits_for_chankan_then_confirms(self) -> None:
        with observing():
            state = _kakan_declared_state()
        self.assertEqual(kinds(state), (K.TURN_CHOICE,))
        declared = last(state)
        self.assertIsNotNone(declared.pending_kakan)
        self.assertIsInstance(declared.seats[1].melds[0], Pon)

        resolve_all_pass(state)
        self.assertEqual(kinds(state), (K.REACTION_RESOLVED, K.KAN_CONFIRMED))
        resolved, confirmed = state.last_transaction_steps
        self.assertIsNone(resolved.checkpoint.pending_kakan)
        self.assertIsInstance(resolved.checkpoint.seats[1].melds[0], Pon)
        self.assertIsInstance(confirmed.checkpoint.seats[1].melds[0], Kakan)
        self.assertIs(state.phase, RoundPhase.AWAITING_RINSHAN_DRAW)

    def test_chankan_ron_does_not_confirm_the_kakan(self) -> None:
        with observing():
            state = _kakan_ron_state()
        self.assertEqual(kinds(state), (K.REACTION_RESOLVED,))
        self.assertIsInstance(last(state).seats[1].melds[0], Pon)
        self.assertIsNone(last(state).pending_kakan)
        self.assertIs(state.phase, RoundPhase.AWAITING_WIN_FINALIZATION)


class FailureAndValueTest(unittest.TestCase):
    def test_failed_transactions_do_not_replace_the_last_steps(self) -> None:
        state = observed(quiet_state())
        tile = state.draw(Seat.EAST)
        steps = state.last_transaction_steps
        with self.assertRaises(StaleActionError):
            state.apply(
                Seat.EAST,
                DiscardLegalAction(tile.id),
                expected_revision=state.revision - 1,
            )
        with (
            patch.object(
                RoundState, "_validate_invariants", side_effect=RuntimeError("boom")
            ),
            self.assertRaises(RuntimeError),
        ):
            state.apply(
                Seat.EAST, DiscardLegalAction(tile.id), expected_revision=state.revision
            )
        self.assertIs(state.last_transaction_steps, steps)

    def test_steps_cover_every_event_and_end_at_the_committed_state(self) -> None:
        state = observed(_reaction_state())
        before = len(state.events)
        resolve_with(state, {Seat.NORTH: pon_action(state, Seat.NORTH)})
        stepped = tuple(e for step in state.last_transaction_steps for e in step.events)
        self.assertEqual(stepped, tuple(state.events)[before:])
        self.assertEqual(last(state), state.committed_checkpoint())

    def test_values_are_immutable(self) -> None:
        state = observed(quiet_state())
        state.draw(Seat.EAST)
        step = state.last_transaction_steps[0]
        with self.assertRaises(FrozenInstanceError):
            step.kind = K.ROUND_ENDED
        with self.assertRaises(FrozenInstanceError):
            step.checkpoint.seats[0].hand_tiles = ()
        self.assertIsInstance(step.checkpoint.seats, tuple)
        self.assertIsInstance(step.checkpoint.seats[0].hand_tiles, tuple)
        self.assertFalse(
            any(
                hasattr(step.checkpoint, name)
                for name in ("wall", "remaining_tiles", "dead_wall_tiles", "players")
            )
        )


_PRIVILEGED_TYPES = (
    TransactionObservation,
    TransactionStep,
    RoundCheckpoint,
    SeatCheckpoint,
)


def _contains_privileged(value, seen=None) -> bool:
    seen = set() if seen is None else seen
    if id(value) in seen:
        return False
    seen.add(id(value))
    if isinstance(value, _PRIVILEGED_TYPES):
        return True
    if is_dataclass(value) and not isinstance(value, type):
        return any(
            _contains_privileged(getattr(value, item.name), seen)
            for item in fields(value)
        )
    if isinstance(value, (tuple, list, frozenset, set)):
        return any(_contains_privileged(item, seen) for item in value)
    return False


class DriverObservationTest(unittest.TestCase):
    POSITION = RoundPosition(
        prevailing_wind=Wind.WEST,
        hand_number=4,
        dealer_seat=Seat.NORTH,
        honba=0,
        riichi_sticks=0,
    )

    def run_match(self, **callbacks):
        calls = []

        def selector(observation, options):
            calls.append((observation, options))
            return _winning_first_selector(observation, options)

        match = _match_at_position(555, self.POSITION)
        return match, run_hanchan(match, _selectors(selector), **callbacks), calls

    def test_every_transaction_is_observed_without_changing_the_run(self) -> None:
        observations, delivered = [], []
        rounds: dict[int, list] = {}
        holder = {}

        def on_observation(observation):
            active = holder["match"].active_round
            events = rounds.setdefault(observation.round_ordinal, [])
            if not events:
                self.assertIs(observation.steps[0].kind, K.ROUND_STARTED)
            events.extend(e for step in observation.steps for e in step.events)
            self.assertEqual(tuple(events), tuple(active.events))
            self.assertEqual(observation.revision, active.revision)
            self.assertIs(observation.phase, active.phase)
            self.assertEqual(
                observation.steps[-1].checkpoint, active.committed_checkpoint()
            )
            observations.append(observation)

        def on_decision(commit):
            delivered.append(commit)

        plain_match, plain, plain_calls = self.run_match()
        original_start = MatchState.start_round

        def start_round(match):
            holder["match"] = match
            return original_start(match)

        with patch.object(MatchState, "start_round", start_round):
            match, watched, calls = self.run_match(
                on_transaction_observation=on_observation,
                on_selector_decision_commit=on_decision,
                on_delivery=delivered.append,
            )
        self.assertEqual(plain, watched)
        self.assertEqual(plain_match.history, match.history)
        self.assertEqual(plain_calls, calls)
        self.assertGreater(len(observations), 4)
        self.assertEqual(
            [o.selector_decision for o in observations if o.selector_decision],
            [item for item in delivered if not isinstance(item, tuple)],
        )
        self.assertFalse(_contains_privileged(delivered))
        self.assertFalse(_contains_privileged(calls))

    def test_callback_failure_is_fail_fast(self) -> None:
        def boom(_observation):
            raise RuntimeError("stop")

        match = _match_at_position(555, self.POSITION)

        def unexpected(_observation, _options):
            self.fail("no selector may run after the observation callback fails")

        with self.assertRaisesRegex(RuntimeError, "stop"):
            run_hanchan(match, _selectors(unexpected), on_transaction_observation=boom)
        self.assertEqual(match.active_round.revision, 1)

    def test_rejects_a_non_callable_callback(self) -> None:
        with self.assertRaises(TypeError):
            run_hanchan(
                MatchState(seed=1),
                _selectors(_winning_first_selector),
                on_transaction_observation=object(),
            )
