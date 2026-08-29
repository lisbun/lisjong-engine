"""round completion境界でのseat-relative evidence delivery（Issue #46）のtest。

`round_evidence.py`のprojection semantics自体は`test_round_evidence.py`で
個別に確認済みである。本moduleは、

- `RoundEvidenceCompletion` / `SeatRoundEvidence`のvalue contract
- 終局種別ごとに最終evidenceが欠落しないこと
- `run_hanchan()`のdelivery timing、exactly-once、determinism、failure semantics
- 新しいpayloadのhidden-information boundary

に焦点を当てる。
"""

import unittest
from dataclasses import fields, is_dataclass

from _round_fixtures import (
    INERT_HAND,
    action_of_type,
    dealt_state,
    draw_and_discard,
    has_action_of_type,
    play_quiet_turn,
    resolve_with,
    ron_action,
)

from lisjong_engine.action_descriptor import PassActionDescriptor
from lisjong_engine.driver import run_hanchan
from lisjong_engine.legal_action import (
    LegalAction,
    NineTerminalsLegalAction,
    RonLegalAction,
    TsumoLegalAction,
)
from lisjong_engine.match_state import (
    CompletedMatch,
    CompletedRound,
    MatchPhase,
    MatchState,
    RoundPosition,
)
from lisjong_engine.player_state import PlayerState
from lisjong_engine.reaction import ReactionResolution
from lisjong_engine.round_allocation import RoundRandomProvenance
from lisjong_engine.round_completion import RoundCompletionFact
from lisjong_engine.round_event import RoundEvent, RoundEventSnapshot
from lisjong_engine.round_evidence import (
    DrawEvidence,
    ResponseEpochClosedEvidence,
    ResponseOutcome,
    RoundEndedEvidence,
    RoundEndKind,
)
from lisjong_engine.round_evidence_builder import build_round_evidence
from lisjong_engine.round_evidence_completion import (
    RoundEvidenceCompletion,
    SeatRoundEvidence,
    build_round_evidence_completion,
)
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.round_result import AbortiveDrawReason, RoundResult
from lisjong_engine.round_state import RoundState
from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile
from lisjong_engine.win_context import WinMethod
from lisjong_engine.wind import Wind

_SEATS = tuple(Seat)

# `test_round_winning.py`と同じ待ち形。EASTが"7p"をツモって和了する。
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
# `test_round_winning.py`と同じ3人ロン形。EASTが打つ"1m"に対し、本testでは
# SOUTHだけがロンし、WEST / NORTHはロン可能なまま見逃す。ロン可能性・
# 見逃し・フリテンはいずれもhidden factであり、evidenceへ漏れてはならない。
_FIRST_RON_HAND = (
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
)
_SECOND_RON_HAND = (
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
)
_THIRD_RON_HAND = (
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

# `test_driver_delivery.py`と同じ方針で、型だけでなくfield名でも危険な値を拒否する。
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
        "ron_capable_seats",
        "ron_passed_seats",
        "capabilities",
        "candidates",
        "choices",
        "resolution",
        "events",
        "history",
    }
)
_FORBIDDEN_TYPES = (
    RoundEvent,
    RoundEventSnapshot,
    ReactionResolution,
    RoundRandomProvenance,
    Tile,
    RoundState,
    MatchState,
    CompletedMatch,
    CompletedRound,
    RoundResult,
    LegalAction,
    PlayerState,
)


def _hands_with(seat: Seat, hand: tuple[str, ...]) -> dict[Seat, tuple[str, ...]]:
    hands = {other: INERT_HAND for other in Seat}
    hands[seat] = hand
    return hands


def _selectors(fn):
    return {seat: fn for seat in Seat}


def _pass_or_first_selector(_observation, options):
    for option in options:
        if isinstance(option, PassActionDescriptor):
            return option
    return options[0]


def _first_option_selector(_observation, options):
    return options[0]


def _match_with_active_round(round_state: RoundState) -> MatchState:
    """終局済みfixture roundを、精算前のMatchStateとして観測できるようにする。

    `MatchState`は自前で山を作るため、決定的なterminal局面をfixtureから
    渡すにはtestからだけprivate attributeを差し替える必要がある。
    """
    match = MatchState(seed=99, rules=round_state.rules)
    match._phase = MatchPhase.ROUND_IN_PROGRESS
    match._active_round = round_state
    return match


def _finish_pending_win(state: RoundState) -> None:
    """終局commitが明示的なfinalizationを要求する場合だけ、それを適用する。"""
    if state.phase is RoundPhase.AWAITING_WIN_FINALIZATION:
        state.finalize_pending_win(expected_revision=state.revision)


def _tsumo_state() -> RoundState:
    state = dealt_state(
        hands=_hands_with(Seat.EAST, _TSUMO_HAND),
        draws=("7p",),
        with_dead_wall=True,
    )
    state.draw(Seat.EAST)
    snapshot = state.legal_actions(Seat.EAST)
    state.apply(
        Seat.EAST,
        action_of_type(state, Seat.EAST, TsumoLegalAction),
        expected_revision=snapshot.revision,
    )
    _finish_pending_win(state)
    return state


def _discarded_ron_state() -> RoundState:
    """EASTが"1m"を打ち、他3席がロン可能な反応windowが開いた状態。"""
    state = dealt_state(
        hands={
            Seat.EAST: INERT_HAND,
            Seat.SOUTH: _FIRST_RON_HAND,
            Seat.WEST: _SECOND_RON_HAND,
            Seat.NORTH: _THIRD_RON_HAND,
        },
        draws=("1m",),
        with_dead_wall=True,
    )
    draw_and_discard(state, Seat.EAST)
    return state


def _ron_state() -> RoundState:
    """SOUTHだけがロンし、WEST / NORTHはロン可能なまま見逃した終局。"""
    state = _discarded_ron_state()
    resolve_with(state, {Seat.SOUTH: ron_action(state, Seat.SOUTH)})
    _finish_pending_win(state)
    return state


def _exhaustive_draw_state() -> RoundState:
    state = dealt_state(
        hands={seat: INERT_HAND for seat in Seat},
        draws=("9m", "9p", "9s", "5z"),
        with_dead_wall=True,
        live_wall_size=56,
    )
    for _ in range(4):
        play_quiet_turn(state)
    _finish_pending_win(state)
    return state


def _abortive_draw_state() -> RoundState:
    """代表的なabortive draw（九種九牌）で終局した局。"""
    state = dealt_state(
        hands=_hands_with(Seat.EAST, _NINE_TERMINALS_HAND),
        draws=("2m",),
        with_dead_wall=True,
    )
    state.draw(Seat.EAST)
    snapshot = state.legal_actions(Seat.EAST)
    state.apply(
        Seat.EAST,
        NineTerminalsLegalAction(),
        expected_revision=snapshot.revision,
    )
    return state


def _evidence_of(completion: RoundEvidenceCompletion, viewer_seat: Seat) -> tuple:
    return next(
        projection.evidence
        for projection in completion.projections
        if projection.viewer_seat is viewer_seat
    )


def _kinds(evidence, evidence_type) -> tuple:
    return tuple(item for item in evidence if isinstance(item, evidence_type))


def _identity_of(completion: RoundEvidenceCompletion) -> tuple:
    return (
        completion.prevailing_wind,
        completion.hand_number,
        completion.dealer_seat,
        completion.honba,
    )


def _position_identity(position: RoundPosition) -> tuple:
    return (
        position.prevailing_wind,
        position.hand_number,
        position.dealer_seat,
        position.honba,
    )


def _match_at_terminal_position(*, seed: int) -> MatchState:
    """半荘の最終局から開始し、1局で完走するMatchStateを作る。

    delivery timing / determinism / backward compatibilityは1局でも確認でき、
    半荘完走のcostを各testへ重複させない。開始位置の上書きはtestからだけ
    行う。
    """
    match = MatchState(seed=seed)
    match._position = RoundPosition(
        prevailing_wind=Wind.WEST,
        hand_number=4,
        dealer_seat=Seat.NORTH,
        honba=0,
        riichi_sticks=0,
    )
    return match


def _run_terminal_round(*, seed: int) -> list:
    completions: list = []
    run_hanchan(
        _match_at_terminal_position(seed=seed),
        _selectors(_first_option_selector),
        on_round_evidence_complete=completions.append,
    )
    return completions


class ValueContractTest(unittest.TestCase):
    def test_seat_round_evidence_rejects_invalid_inputs(self) -> None:
        with self.assertRaises(TypeError):
            SeatRoundEvidence("east", ())
        with self.assertRaises(TypeError):
            SeatRoundEvidence(Seat.EAST, 3)
        with self.assertRaises(TypeError):
            SeatRoundEvidence(Seat.EAST, ("not-evidence",))

    def test_seat_round_evidence_normalizes_evidence_to_a_tuple(self) -> None:
        evidence = [RoundEndedEvidence(kind=RoundEndKind.EXHAUSTIVE_DRAW)]

        projection = SeatRoundEvidence(Seat.WEST, evidence)

        self.assertEqual(projection.evidence, tuple(evidence))
        self.assertIsInstance(projection.evidence, tuple)

    def test_completion_requires_all_four_viewer_seats_in_order(self) -> None:
        projections = tuple(SeatRoundEvidence(seat, ()) for seat in _SEATS)
        identity = {
            "prevailing_wind": Wind.EAST,
            "hand_number": 1,
            "dealer_seat": Seat.EAST,
            "honba": 0,
        }

        RoundEvidenceCompletion(projections=projections, **identity)

        with self.assertRaises(ValueError):
            RoundEvidenceCompletion(projections=projections[:3], **identity)
        with self.assertRaises(ValueError):
            RoundEvidenceCompletion(
                projections=tuple(reversed(projections)), **identity
            )
        with self.assertRaises(ValueError):
            RoundEvidenceCompletion(
                projections=(projections[0],) * 4,
                **identity,
            )

    def test_completion_rejects_invalid_identity_and_projections(self) -> None:
        projections = tuple(SeatRoundEvidence(seat, ()) for seat in _SEATS)

        with self.assertRaises(TypeError):
            RoundEvidenceCompletion(
                prevailing_wind="east",
                hand_number=1,
                dealer_seat=Seat.EAST,
                honba=0,
                projections=projections,
            )
        with self.assertRaises(TypeError):
            RoundEvidenceCompletion(
                prevailing_wind=Wind.EAST,
                hand_number=1,
                dealer_seat=Seat.EAST,
                honba=0,
                projections=("not-a-projection",),
            )


class BuilderContractTest(unittest.TestCase):
    def test_rejects_a_non_match_state(self) -> None:
        with self.assertRaises(TypeError):
            build_round_evidence_completion("not-a-match")

    def test_rejects_a_match_without_an_active_round(self) -> None:
        with self.assertRaises(ValueError):
            build_round_evidence_completion(MatchState(seed=5))

    def test_rejects_an_unfinished_round(self) -> None:
        match = MatchState(seed=5)
        match.start_round()

        with self.assertRaises(ValueError):
            build_round_evidence_completion(match)

    def test_identity_comes_from_the_current_match_position(self) -> None:
        match = _match_with_active_round(_tsumo_state())
        position = match.position

        completion = build_round_evidence_completion(match)

        self.assertIs(completion.prevailing_wind, position.prevailing_wind)
        self.assertEqual(completion.hand_number, position.hand_number)
        self.assertIs(completion.dealer_seat, position.dealer_seat)
        self.assertEqual(completion.honba, position.honba)

    def test_viewer_order_is_the_deterministic_seat_order(self) -> None:
        completion = build_round_evidence_completion(
            _match_with_active_round(_tsumo_state())
        )

        self.assertEqual(
            tuple(projection.viewer_seat for projection in completion.projections),
            _SEATS,
        )

    def test_each_viewer_projection_matches_build_round_evidence(self) -> None:
        round_state = _ron_state()
        match = _match_with_active_round(round_state)

        completion = build_round_evidence_completion(match)

        for projection in completion.projections:
            self.assertEqual(
                projection.evidence,
                build_round_evidence(round_state, projection.viewer_seat),
            )

    def test_the_same_finished_round_yields_equal_completions(self) -> None:
        match = _match_with_active_round(_ron_state())

        self.assertEqual(
            build_round_evidence_completion(match),
            build_round_evidence_completion(match),
        )


class TerminalEvidenceTest(unittest.TestCase):
    def _completion(self, round_state: RoundState) -> RoundEvidenceCompletion:
        self.assertIs(round_state.phase, RoundPhase.FINISHED)
        return build_round_evidence_completion(_match_with_active_round(round_state))

    def test_ron_keeps_the_closing_response_epoch_and_the_round_end(self) -> None:
        completion = self._completion(_ron_state())

        for projection in completion.projections:
            closed = _kinds(projection.evidence, ResponseEpochClosedEvidence)
            self.assertTrue(closed, f"{projection.viewer_seat} lost the closed epoch")
            self.assertIs(closed[-1].outcome, ResponseOutcome.RON)

            ended = _kinds(projection.evidence, RoundEndedEvidence)
            self.assertEqual(len(ended), 1)
            self.assertIs(ended[0].kind, RoundEndKind.WIN)
            self.assertIs(ended[0].win_method, WinMethod.RON)
            self.assertEqual(ended[0].winner_seats, (Seat.SOUTH,))
            self.assertIs(ended[0].source_seat, Seat.EAST)
            self.assertIsInstance(projection.evidence[-1], RoundEndedEvidence)

    def test_tsumo_keeps_the_round_end(self) -> None:
        completion = self._completion(_tsumo_state())

        for projection in completion.projections:
            ended = _kinds(projection.evidence, RoundEndedEvidence)
            self.assertEqual(len(ended), 1)
            self.assertIs(ended[0].kind, RoundEndKind.WIN)
            self.assertIs(ended[0].win_method, WinMethod.TSUMO)
            self.assertEqual(ended[0].winner_seats, (Seat.EAST,))
            self.assertIsNone(ended[0].source_seat)

    def test_exhaustive_draw_keeps_the_round_end(self) -> None:
        completion = self._completion(_exhaustive_draw_state())

        for projection in completion.projections:
            ended = _kinds(projection.evidence, RoundEndedEvidence)
            self.assertEqual(len(ended), 1)
            self.assertIs(ended[0].kind, RoundEndKind.EXHAUSTIVE_DRAW)
            self.assertIsNone(ended[0].abortive_reason)

    def test_abortive_draw_keeps_the_round_end_and_its_reason(self) -> None:
        completion = self._completion(_abortive_draw_state())

        for projection in completion.projections:
            ended = _kinds(projection.evidence, RoundEndedEvidence)
            self.assertEqual(len(ended), 1)
            self.assertIs(ended[0].kind, RoundEndKind.ABORTIVE_DRAW)
            self.assertIs(ended[0].abortive_reason, AbortiveDrawReason.NINE_TERMINALS)


class HiddenInformationTest(unittest.TestCase):
    def test_a_viewer_private_draw_tile_never_reaches_another_viewer(self) -> None:
        completion = build_round_evidence_completion(
            _match_with_active_round(_tsumo_state())
        )

        for projection in completion.projections:
            for evidence in _kinds(projection.evidence, DrawEvidence):
                if evidence.seat is projection.viewer_seat:
                    self.assertIsNotNone(evidence.tile)
                else:
                    self.assertIsNone(
                        evidence.tile,
                        f"{projection.viewer_seat} saw {evidence.seat}'s draw",
                    )

    def test_two_seats_that_missed_a_hidden_ron_receive_identical_evidence(
        self,
    ) -> None:
        pending = _discarded_ron_state()
        self.assertTrue(has_action_of_type(pending, Seat.WEST, RonLegalAction))
        self.assertTrue(has_action_of_type(pending, Seat.NORTH, RonLegalAction))

        completion = build_round_evidence_completion(
            _match_with_active_round(_ron_state())
        )

        # WEST / NORTHはhidden handが異なり、どちらもロン可能なまま見逃した
        # 席である。両者のevidenceが完全に一致することは、reaction capability、
        # hidden pass、見逃しフリテン、`ReactionResolution`がviewer projectionへ
        # 漏れていないことを示す。
        self.assertEqual(
            _evidence_of(completion, Seat.WEST),
            _evidence_of(completion, Seat.NORTH),
        )

    def test_a_ron_completion_exposes_no_internal_object_or_provenance(self) -> None:
        round_state = _ron_state()
        # 反応windowを実際に解決した局であり、internal historyは
        # ReactionResolutionとron capabilityを保持している。
        self.assertTrue(round_state.events)

        completion = build_round_evidence_completion(
            _match_with_active_round(round_state)
        )

        self._assert_no_forbidden_reference(completion)

    def test_each_terminal_kind_exposes_no_internal_object(self) -> None:
        for label, factory in (
            ("tsumo", _tsumo_state),
            ("exhaustive", _exhaustive_draw_state),
            ("abortive", _abortive_draw_state),
        ):
            with self.subTest(terminal=label):
                self._assert_no_forbidden_reference(
                    build_round_evidence_completion(_match_with_active_round(factory()))
                )

    def _assert_no_forbidden_reference(self, value, *, seen=None) -> None:
        if seen is None:
            seen = set()
        if id(value) in seen:
            return
        seen.add(id(value))

        for forbidden in _FORBIDDEN_TYPES:
            self.assertNotIsInstance(
                value,
                forbidden,
                f"{value!r} exposes forbidden internal type {forbidden.__name__}",
            )

        if is_dataclass(value) and not isinstance(value, type):
            for field in fields(value):
                self.assertNotIn(
                    field.name,
                    _FORBIDDEN_FIELD_NAMES,
                    f"{type(value).__name__}.{field.name} is a forbidden field name "
                    "(hidden-identity/provenance leak)",
                )
                self._assert_no_forbidden_reference(
                    getattr(value, field.name), seen=seen
                )
        elif isinstance(value, (tuple, list, frozenset, set)):
            for item in value:
                self._assert_no_forbidden_reference(item, seen=seen)


class DriverDeliveryTest(unittest.TestCase):
    """`run_hanchan()`のdelivery境界そのものを固定する。

    半荘完走は1 testへまとめ、そこでexactly-once / timing / 値の一致 /
    既存`on_delivery`との順序をまとめて確認する。他のtestはterminal
    positionから1局だけ実行する。
    """

    def test_a_full_hanchan_delivers_each_completed_round_exactly_once(self) -> None:
        match = MatchState(seed=321)
        completions: list[RoundEvidenceCompletion] = []
        identities: list[tuple] = []
        history_sizes: list[int] = []
        order: list[str] = []

        def on_round_evidence_complete(completion):
            # 精算前なので、対象のactive roundはまだ失われていない。
            round_state = match.active_round
            self.assertIsNotNone(round_state)
            self.assertIs(round_state.phase, RoundPhase.FINISHED)
            self.assertIs(match.phase, MatchPhase.ROUND_IN_PROGRESS)

            # 最後の成功transactionまで反映された、既存projectorと同じ値である。
            for projection in completion.projections:
                self.assertEqual(
                    projection.evidence,
                    build_round_evidence(round_state, projection.viewer_seat),
                )
                self.assertIsInstance(projection.evidence[-1], RoundEndedEvidence)

            completions.append(completion)
            identities.append(_identity_of(completion))
            history_sizes.append(len(match.history))
            order.append("evidence")

        def on_delivery(items):
            if any(isinstance(item, RoundCompletionFact) for item in items):
                order.append("completion")

        run_hanchan(
            match,
            _selectors(_first_option_selector),
            on_delivery=on_delivery,
            on_round_evidence_complete=on_round_evidence_complete,
        )

        rounds = len(match.history)
        self.assertGreater(rounds, 1)
        self.assertEqual(len(completions), rounds)
        self.assertEqual(
            identities,
            [
                _position_identity(completed.position_before)
                for completed in match.history
            ],
        )
        # n局目のdeliveryの時点で、精算済みhistoryはn-1件だけである。
        self.assertEqual(history_sizes, list(range(rounds)))
        # evidenceは常に、その局のround completion factより前に届く。
        self.assertEqual(order, ["evidence", "completion"] * rounds)

    def test_viewer_order_is_deterministic_for_every_delivery(self) -> None:
        completions = _run_terminal_round(seed=11)

        self.assertTrue(completions)
        for completion in completions:
            self.assertEqual(
                tuple(projection.viewer_seat for projection in completion.projections),
                _SEATS,
            )

    def test_the_same_seed_and_selectors_yield_the_same_delivered_values(self) -> None:
        first = _run_terminal_round(seed=11)
        second = _run_terminal_round(seed=11)

        self.assertTrue(first)
        self.assertEqual(first, second)

    def test_rejects_a_non_callable_callback(self) -> None:
        with self.assertRaises(TypeError):
            run_hanchan(
                MatchState(seed=1),
                _selectors(_first_option_selector),
                on_round_evidence_complete="not-callable",
            )


class DriverFailureSemanticsTest(unittest.TestCase):
    def test_a_callback_exception_stops_before_settlement_and_the_next_round(
        self,
    ) -> None:
        match = _match_with_active_round(_ron_state())
        probe: dict = {}

        def failing_callback(completion):
            probe["completion"] = completion
            probe["history"] = len(match.history)
            probe["active_round"] = match.active_round
            raise RuntimeError("stop before settlement")

        def unexpected(_observation, _options):
            self.fail("no selector runs for an already finished round")

        with self.assertRaisesRegex(RuntimeError, "stop before settlement"):
            run_hanchan(
                match,
                _selectors(unexpected),
                on_round_evidence_complete=failing_callback,
            )

        # callbackはterminal evidenceを受け取っており、その時点で精算前である。
        completion = probe["completion"]
        self.assertIsInstance(completion, RoundEvidenceCompletion)
        self.assertIs(
            _kinds(_evidence_of(completion, Seat.WEST), RoundEndedEvidence)[0].kind,
            RoundEndKind.WIN,
        )
        self.assertEqual(probe["history"], 0)
        self.assertIsNotNone(probe["active_round"])

        # 例外の後もretry / silent skipせず、精算も次局開始も起きていない。
        self.assertEqual(len(match.history), 0)
        self.assertIsNotNone(match.active_round)
        self.assertIs(match.active_round.phase, RoundPhase.FINISHED)
        self.assertIs(match.phase, MatchPhase.ROUND_IN_PROGRESS)

    def test_no_round_completion_fact_is_delivered_when_the_callback_fails(
        self,
    ) -> None:
        match = _match_with_active_round(_ron_state())
        delivered: list = []

        def raising_callback(_completion):
            raise RuntimeError("boom")

        with self.assertRaisesRegex(RuntimeError, "boom"):
            run_hanchan(
                match,
                _selectors(_pass_or_first_selector),
                on_delivery=delivered.extend,
                on_round_evidence_complete=raising_callback,
            )

        self.assertEqual(delivered, [])


class BackwardCompatibilityTest(unittest.TestCase):
    def _run(self, **kwargs) -> tuple:
        match = _match_at_terminal_position(seed=11)
        calls: list = []

        def recording_selector(observation, options):
            calls.append((observation.viewer_seat, observation.decision_kind))
            return options[0]

        batches: list = []
        completed = run_hanchan(
            match,
            _selectors(recording_selector),
            on_delivery=batches.append,
            **kwargs,
        )
        return match, completed, calls, batches

    def test_the_new_callback_changes_no_existing_observable_behavior(self) -> None:
        baseline_match, baseline, baseline_calls, baseline_batches = self._run()
        completions: list = []
        match, completed, calls, batches = self._run(
            on_round_evidence_complete=completions.append
        )

        self.assertEqual(baseline, completed)
        self.assertEqual(baseline_match.history, match.history)
        self.assertEqual(baseline_calls, calls)
        self.assertEqual(baseline_batches, batches)
        self.assertTrue(completions)

    def test_without_any_callback_the_result_is_unchanged(self) -> None:
        baseline_match = _match_at_terminal_position(seed=11)
        baseline = run_hanchan(baseline_match, _selectors(_first_option_selector))

        match = _match_at_terminal_position(seed=11)
        completions: list = []
        completed = run_hanchan(
            match,
            _selectors(_first_option_selector),
            on_round_evidence_complete=completions.append,
        )

        self.assertEqual(baseline, completed)
        self.assertEqual(baseline_match.history, match.history)
        self.assertTrue(completions)


if __name__ == "__main__":
    unittest.main()
