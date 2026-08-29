"""`run_hanchan()`のdelivery境界（Issue #34）に関する回帰test。

`round_progress.py` / `round_completion.py`自体の射影ロジックは
`test_round_progress.py` / `test_round_completion.py`で個別に確認済み。
本moduleはdriver統合、すなわちevent cursorの追跡、delivery timing、
failure semantics、hidden-information boundary、backward compatibilityに
焦点を当てる。
"""

import unittest
from dataclasses import fields, is_dataclass

from _round_fixtures import (
    INERT_HAND,
    dealt_state,
)

from lisjong_engine.action_descriptor import (
    ActionDescriptor,
    AnkanActionDescriptor,
    ChiActionDescriptor,
    DiscardActionDescriptor,
    PassActionDescriptor,
    RiichiActionDescriptor,
    RonActionDescriptor,
)
from lisjong_engine.driver import _advance_round, _settle_round, run_hanchan
from lisjong_engine.legal_action import (
    LegalAction,
)
from lisjong_engine.match_state import (
    CompletedMatch,
    CompletedRound,
    MatchPhase,
    MatchState,
    RoundPosition,
)
from lisjong_engine.observation import ObservationDecisionKind
from lisjong_engine.player_state import PlayerState
from lisjong_engine.public_state import PublicTile
from lisjong_engine.reaction import ReactionResolution
from lisjong_engine.round_allocation import RoundRandomProvenance
from lisjong_engine.round_completion import MatchCompletionFact, RoundCompletionFact
from lisjong_engine.round_event import RoundEvent, RoundEventSnapshot
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.round_progress import (
    DiscardProgress,
    DoraIndicatorRevealedProgress,
    KanConfirmedProgress,
    KanDeclaredProgress,
    MeldCalledProgress,
    RiichiDeclaredProgress,
    RiichiEstablishedProgress,
    RiichiFailedProgress,
)
from lisjong_engine.round_result import (
    AbortiveDrawReason,
    AbortiveDrawResult,
    RoundResult,
)
from lisjong_engine.round_state import RoundState
from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile, TileCategory, TileType
from lisjong_engine.wind import Wind

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

# EASTが立直可能なtenpai形で"5z"を打つ配牌。WESTの手を差し替えることで、
# 誰も反応できずに立直が成立する場合と、WESTがロンして立直が不成立になる
# 場合の両方を同じEAST側配牌から作れる。
_RIICHI_EAST_HAND = (
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
_RIICHI_ESTABLISH_HANDS = {
    Seat.EAST: _RIICHI_EAST_HAND,
    Seat.SOUTH: INERT_HAND,
    Seat.WEST: INERT_HAND,
    Seat.NORTH: INERT_HAND,
}
# WESTは5z/6zのシャンポン待ち。EASTが打つ"5z"をロンすると白の役牌が成立する。
_RIICHI_FAIL_HANDS = {
    Seat.EAST: _RIICHI_EAST_HAND,
    Seat.SOUTH: INERT_HAND,
    Seat.WEST: (
        "1m",
        "2m",
        "3m",
        "4m",
        "5m",
        "6m",
        "7p",
        "8p",
        "9p",
        "5z",
        "5z",
        "6z",
        "6z",
    ),
    Seat.NORTH: INERT_HAND,
}

_7P = PublicTile(TileType(TileCategory.PINZU, 7))
_1M = PublicTile(TileType(TileCategory.MANZU, 1))

# whitelist projectionが将来regressionしても検出できるよう、型だけでなく
# field名でも危険な値を拒否する。tile_id等はintとして紛れ込み得るため、
# 型ベースのrecursive checkだけでは検出できない。
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
        "candidates",
        "choices",
        "resolution",
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


def _selectors(fn):
    return {seat: fn for seat in Seat}


def _match_with_active_round(round_state: RoundState) -> MatchState:
    match = MatchState(seed=99, rules=round_state.rules)
    match._phase = MatchPhase.ROUND_IN_PROGRESS
    match._active_round = round_state
    return match


def _match_at_position(seed: int, position: RoundPosition) -> MatchState:
    """`start_round()`をEast1以外のpositionから開始できるよう、
    testからだけprivate `_position`を上書きする。
    """
    match = MatchState(seed=seed)
    match._position = position
    return match


def _finish_with_result(round_state: RoundState, result) -> None:
    """testのためだけに、開始済みRoundStateを直接終局済みfactへ進める。

    delivery timing / ordering / failure semanticsはRoundStateの終局判定
    ロジックとは独立した関心事であり、実際の打牌進行を再現する必要はない。
    """
    round_state._phase = RoundPhase.FINISHED
    round_state._result = result


def _discard_tile_selector(target: PublicTile):
    def selector(
        _observation, options: tuple[ActionDescriptor, ...]
    ) -> ActionDescriptor:
        for option in options:
            if isinstance(option, DiscardActionDescriptor) and option.tile == target:
                return option
        for option in options:
            if isinstance(option, PassActionDescriptor):
                return option
        return options[0]

    return selector


def _chi_or_pass_selector(
    _observation, options: tuple[ActionDescriptor, ...]
) -> ActionDescriptor:
    for option in options:
        if isinstance(option, ChiActionDescriptor):
            return option
    for option in options:
        if isinstance(option, PassActionDescriptor):
            return option
    return options[0]


def _riichi_tsumogiri_or_pass_selector(
    observation, options: tuple[ActionDescriptor, ...]
) -> ActionDescriptor:
    """立直を選び、続く宣言牌decisionでツモ切りを選ぶ2段階selector。"""
    for option in options:
        if isinstance(option, RiichiActionDescriptor):
            return option
    if observation.decision_kind is ObservationDecisionKind.RIICHI_DISCARD:
        for option in options:
            if isinstance(option, DiscardActionDescriptor) and option.is_tsumogiri:
                return option
    for option in options:
        if isinstance(option, PassActionDescriptor):
            return option
    return options[0]


def _ron_or_pass_selector(ron_seat: Seat):
    def selector(
        observation, options: tuple[ActionDescriptor, ...]
    ) -> ActionDescriptor:
        if observation.viewer_seat is ron_seat:
            for option in options:
                if isinstance(option, RonActionDescriptor):
                    return option
        for option in options:
            if isinstance(option, PassActionDescriptor):
                return option
        return options[0]

    return selector


def _ankan_or_first_selector(
    _observation, options: tuple[ActionDescriptor, ...]
) -> ActionDescriptor:
    for option in options:
        if isinstance(option, AnkanActionDescriptor):
            return option
    return options[0]


class OnDeliveryValidationTest(unittest.TestCase):
    def test_rejects_non_callable_on_delivery(self) -> None:
        with self.assertRaises(TypeError):
            run_hanchan(
                MatchState(seed=1),
                _selectors(lambda _observation, options: options[0]),
                on_delivery="not-callable",
            )


class ProgressDeliveryOrderingTest(unittest.TestCase):
    def test_chi_then_discard_are_delivered_in_two_ordered_batches(self) -> None:
        state = dealt_state(hands=_REACTION_HANDS, draws=("8s",), with_dead_wall=True)
        match = _match_with_active_round(state)
        batches: list[tuple] = []

        selectors = {
            Seat.EAST: _discard_tile_selector(_7P),
            Seat.SOUTH: _chi_or_pass_selector,
            Seat.WEST: _discard_tile_selector(_7P),
            Seat.NORTH: _discard_tile_selector(_7P),
        }

        # EASTのdrawはprogress factを生じない（draw eventはwhitelist外）。

        cursor = _advance_round(match, state, selectors, batches.append, 0)
        self.assertEqual(batches, [])
        self.assertIs(state.phase, RoundPhase.AWAITING_DISCARD)

        # EASTの打牌 -> 1件目のbatch。
        cursor = _advance_round(match, state, selectors, batches.append, cursor)
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0]), 1)
        self.assertIsInstance(batches[0][0], DiscardProgress)
        self.assertIs(batches[0][0].seat, Seat.EAST)

        # SOUTHのチー成立 -> 2件目のbatch。1件目とは別呼び出しで届く。
        cursor = _advance_round(match, state, selectors, batches.append, cursor)
        self.assertEqual(len(batches), 2)
        self.assertEqual(len(batches[1]), 1)
        self.assertIsInstance(batches[1][0], MeldCalledProgress)
        self.assertIs(batches[1][0].seat, Seat.SOUTH)

        # SOUTHの打牌 -> 3件目のbatch。
        cursor = _advance_round(match, state, selectors, batches.append, cursor)
        self.assertEqual(len(batches), 3)
        self.assertIsInstance(batches[2][0], DiscardProgress)
        self.assertIs(batches[2][0].seat, Seat.SOUTH)

        # 各batchのfactはすべて欠落なく、重複なく届いている。
        delivered_kinds = [type(batch[0]) for batch in batches]
        self.assertEqual(
            delivered_kinds, [DiscardProgress, MeldCalledProgress, DiscardProgress]
        )

    def test_no_batch_is_delivered_when_a_transaction_has_no_public_fact(self) -> None:
        state = dealt_state(hands=_REACTION_HANDS, draws=("8s",), with_dead_wall=True)
        match = _match_with_active_round(state)
        batches: list[tuple] = []

        _advance_round(match, state, _selectors(lambda o, a: a[0]), batches.append, 0)

        self.assertEqual(batches, [])


class FullOrderedSequenceTest(unittest.TestCase):
    """discard/kanのように複数transactionへまたがるfactの、完全なorderingを固定する。"""

    def test_riichi_discard_declaration_and_establishment_full_order(self) -> None:
        state = dealt_state(
            hands=_RIICHI_ESTABLISH_HANDS, draws=("5z",), with_dead_wall=True
        )
        match = _match_with_active_round(state)
        delivered: list = []
        selectors = _selectors(_riichi_tsumogiri_or_pass_selector)

        # 誰も反応できないため、宣言と成立は打牌と同じtransaction内で確定する。
        cursor = _advance_round(match, state, selectors, delivered.extend, 0)  # draw
        cursor = _advance_round(
            match, state, selectors, delivered.extend, cursor
        )  # riichi selection alone delivers nothing
        self.assertEqual(delivered, [])
        _advance_round(match, state, selectors, delivered.extend, cursor)  # discard

        self.assertEqual(
            [type(item) for item in delivered],
            [DiscardProgress, RiichiDeclaredProgress, RiichiEstablishedProgress],
        )
        self.assertTrue(all(item.seat is Seat.EAST for item in delivered))

    def test_riichi_discard_declaration_and_ron_failure_full_order(self) -> None:
        state = dealt_state(
            hands=_RIICHI_FAIL_HANDS, draws=("5z",), with_dead_wall=True
        )
        match = _match_with_active_round(state)
        delivered: list = []
        selectors = {
            Seat.EAST: _riichi_tsumogiri_or_pass_selector,
            Seat.SOUTH: _ron_or_pass_selector(Seat.WEST),
            Seat.WEST: _ron_or_pass_selector(Seat.WEST),
            Seat.NORTH: _ron_or_pass_selector(Seat.WEST),
        }

        cursor = _advance_round(match, state, selectors, delivered.extend, 0)  # draw
        cursor = _advance_round(
            match, state, selectors, delivered.extend, cursor
        )  # riichi selection alone delivers nothing
        self.assertEqual(delivered, [])
        cursor = _advance_round(
            match, state, selectors, delivered.extend, cursor
        )  # discard + declaration, opens the reaction window
        _advance_round(
            match, state, selectors, delivered.extend, cursor
        )  # West rons -> riichi fails

        self.assertEqual(
            [type(item) for item in delivered],
            [DiscardProgress, RiichiDeclaredProgress, RiichiFailedProgress],
        )
        self.assertTrue(
            all(item.seat is Seat.EAST for item in delivered),
            "riichi declaration and its outcome must stay attributed to the declarer",
        )

    def test_ankan_declaration_confirmation_and_dora_reveal_full_order(self) -> None:
        state = dealt_state(hands=_ANKAN_HANDS, draws=("8s",), with_dead_wall=True)
        match = _match_with_active_round(state)
        delivered: list = []
        selectors = _selectors(_ankan_or_first_selector)

        # kokushi_ankan_chankan_enabledを有効化していないため、槍槓windowを
        # 経由せず、宣言・成立・槓ドラ公開が1つのtransactionで確定する。
        cursor = _advance_round(match, state, selectors, delivered.extend, 0)  # draw
        _advance_round(match, state, selectors, delivered.extend, cursor)  # ankan

        self.assertEqual(
            [type(item) for item in delivered],
            [KanDeclaredProgress, KanConfirmedProgress, DoraIndicatorRevealedProgress],
        )
        self.assertTrue(all(item.seat is Seat.EAST for item in delivered))


class PublicBoundaryCompletionTest(unittest.TestCase):
    """`run_hanchan(..., on_delivery=...)`という公開境界そのものでtiming / failureを確認する。

    他のtestは実装の詳細である`_settle_round()` / `_advance_round()`を直接
    呼んでいるが、Issue #34が実際に保証したcontractはこのpublic driver関数
    である。
    """

    def test_completion_callback_timing_and_failure_via_public_boundary(self) -> None:
        match = MatchState(seed=7)
        round_state = match.start_round()
        _finish_with_result(
            round_state, AbortiveDrawResult(AbortiveDrawReason.FOUR_WINDS)
        )

        probe: dict = {}

        def probing_delivery(items):
            probe["items"] = items
            probe["phase"] = match.phase
            probe["active_round"] = match.active_round
            probe["started_round_count"] = match._started_round_count
            raise RuntimeError("stop before the next round starts")

        def unexpected(_observation, _options):
            self.fail("no selector should be called before the completion callback")

        with self.assertRaisesRegex(RuntimeError, "stop before the next round starts"):
            run_hanchan(match, _selectors(unexpected), on_delivery=probing_delivery)

        # settle_active_round()は既にcommitされているが、次のstart_round()は
        # callback呼び出しの時点でまだ呼ばれていない。
        self.assertIsInstance(probe["items"][0], RoundCompletionFact)
        self.assertIs(probe["phase"], MatchPhase.AWAITING_ROUND)
        self.assertIsNone(probe["active_round"])
        self.assertEqual(probe["started_round_count"], 1)
        self.assertEqual(len(match.history), 1)

        # callback例外の後も、driverは次のstart_round()へ進んでいない。
        self.assertIs(match.phase, MatchPhase.AWAITING_ROUND)
        self.assertIsNone(match.active_round)
        self.assertEqual(match._started_round_count, 1)

    def test_run_hanchan_returns_completed_match_after_terminal_completion(
        self,
    ) -> None:
        position = RoundPosition(
            prevailing_wind=Wind.WEST,
            hand_number=4,
            dealer_seat=Seat.NORTH,
            honba=0,
            riichi_sticks=0,
        )
        match = _match_at_position(1, position)
        round_state = match.start_round()
        _finish_with_result(
            round_state, AbortiveDrawResult(AbortiveDrawReason.FOUR_WINDS)
        )

        received: list = []

        def unexpected(_observation, _options):
            self.fail(
                "no selector should be called for an already-finished terminal round"
            )

        completed = run_hanchan(
            match, _selectors(unexpected), on_delivery=received.append
        )

        self.assertIsInstance(completed, CompletedMatch)
        self.assertIs(match.completed_match, completed)
        self.assertEqual(len(received), 1)
        self.assertEqual(len(received[0]), 2)
        self.assertIsInstance(received[0][0], RoundCompletionFact)
        self.assertIsInstance(received[0][1], MatchCompletionFact)


class RoundTransitionTimingTest(unittest.TestCase):
    def test_completion_callback_fires_after_settlement_and_before_next_start(
        self,
    ) -> None:
        match = MatchState(seed=7)
        round_state = match.start_round()
        _finish_with_result(
            round_state, AbortiveDrawResult(AbortiveDrawReason.FOUR_WINDS)
        )

        observed: list[tuple] = []

        def on_delivery(items):
            # settle_active_round()は既にcommitされているため、
            # active_roundはこの時点で既にNoneであり、次のstart_round()は
            # まだ呼ばれていない。
            self.assertIsNone(match.active_round)
            self.assertIs(match.phase, MatchPhase.AWAITING_ROUND)
            observed.append(items)

        def quiet_selector(_observation, options):
            for option in options:
                if isinstance(option, PassActionDescriptor):
                    return option
            return options[0]

        # 半荘完走まで進めず、settlementの1呼び出し分だけを確認する。

        _settle_round(match, on_delivery)

        self.assertEqual(len(observed), 1)
        self.assertIsInstance(observed[0][0], RoundCompletionFact)
        self.assertIs(match.phase, MatchPhase.AWAITING_ROUND)
        self.assertIsNone(match.active_round)


class TerminalOrderingTest(unittest.TestCase):
    def test_round_and_match_completion_arrive_together_once_and_in_order(
        self,
    ) -> None:
        position = RoundPosition(
            prevailing_wind=Wind.WEST,
            hand_number=4,
            dealer_seat=Seat.NORTH,
            honba=0,
            riichi_sticks=0,
        )
        match = _match_at_position(1, position)
        round_state = match.start_round()
        _finish_with_result(
            round_state, AbortiveDrawResult(AbortiveDrawReason.FOUR_WINDS)
        )

        batches: list[tuple] = []

        _settle_round(match, batches.append)

        self.assertEqual(len(batches), 1)
        items = batches[0]
        self.assertEqual(len(items), 2)
        self.assertIsInstance(items[0], RoundCompletionFact)
        self.assertIsInstance(items[1], MatchCompletionFact)
        self.assertIs(match.phase, MatchPhase.FINISHED)


class FailureSemanticsTest(unittest.TestCase):
    def test_progress_callback_exception_propagates_without_rollback(self) -> None:
        state = dealt_state(hands=_REACTION_HANDS, draws=("8s",), with_dead_wall=True)
        match = _match_with_active_round(state)

        cursor = _advance_round(
            match, state, _selectors(lambda o, a: a[0]), None, 0
        )  # draw, no delivery needed

        def raising_delivery(_items):
            raise RuntimeError("boom")

        selectors = {seat: _discard_tile_selector(_7P) for seat in Seat}
        revision_before = state.revision

        with self.assertRaisesRegex(RuntimeError, "boom"):
            _advance_round(match, state, selectors, raising_delivery, cursor)

        # transactionはfail-fastの前に既に成功commitされており、rollbackしない。
        self.assertEqual(state.revision, revision_before + 1)
        self.assertIs(state.phase, RoundPhase.AWAITING_REACTIONS)

    def test_completion_callback_exception_propagates_without_rollback(self) -> None:
        match = MatchState(seed=7)
        round_state = match.start_round()
        _finish_with_result(
            round_state, AbortiveDrawResult(AbortiveDrawReason.FOUR_WINDS)
        )

        def raising_delivery(_items):
            raise RuntimeError("boom")

        with self.assertRaisesRegex(RuntimeError, "boom"):
            _settle_round(match, raising_delivery)

        # settle_active_round()は既にcommitされているため、settlement結果は
        # 保持されたままである。callback失敗後にdriverは次のstart_round()へ
        # 進んでいない（本testはrun_hanchan()を呼んでいないため、次の
        # transitionが実際に起きないことは_settle_round単体呼び出しの
        # 事実そのものが示す）。
        self.assertEqual(len(match.history), 1)
        self.assertIsNone(match.active_round)
        self.assertIs(match.phase, MatchPhase.AWAITING_ROUND)


class HiddenInformationTest(unittest.TestCase):
    def test_progress_and_completion_items_never_expose_forbidden_types(self) -> None:
        state = dealt_state(hands=_REACTION_HANDS, draws=("8s",), with_dead_wall=True)
        match = _match_with_active_round(state)
        delivered: list = []

        selectors = {
            Seat.EAST: _discard_tile_selector(_7P),
            Seat.SOUTH: _chi_or_pass_selector,
            Seat.WEST: _discard_tile_selector(_7P),
            Seat.NORTH: _discard_tile_selector(_7P),
        }

        cursor = 0
        for _ in range(4):
            cursor = _advance_round(match, state, selectors, delivered.extend, cursor)

        self.assertTrue(delivered)
        for item in delivered:
            self._assert_no_forbidden_reference(item)

    def test_completion_items_never_expose_forbidden_types(self) -> None:
        match = MatchState(seed=7)
        round_state = match.start_round()
        _finish_with_result(
            round_state, AbortiveDrawResult(AbortiveDrawReason.FOUR_WINDS)
        )
        delivered: list = []

        _settle_round(match, delivered.extend)

        self.assertTrue(delivered)
        for item in delivered:
            self._assert_no_forbidden_reference(item)

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


class BackwardCompatibilityTest(unittest.TestCase):
    """`on_delivery`省略時とexplicit `None`が既存挙動を変えないことを、
    deterministic terminal position（West 4, dealer NORTH）からの短い
    実行で確認する。半荘完走はIssue #34の他のtestとround-evidence側で
    独立にcoverされているため、ここでは1局分の終局のみを再現すれば足りる。
    """

    def _terminal_match(self, seed: int) -> MatchState:
        position = RoundPosition(
            prevailing_wind=Wind.WEST,
            hand_number=4,
            dealer_seat=Seat.NORTH,
            honba=0,
            riichi_sticks=0,
        )
        match = _match_at_position(seed, position)
        round_state = match.start_round()
        _finish_with_result(
            round_state, AbortiveDrawResult(AbortiveDrawReason.FOUR_WINDS)
        )
        return match

    def test_on_delivery_none_matches_pre_existing_behavior(self) -> None:
        def unexpected(_observation, _options):
            self.fail(
                "no selector should be called for an already-finished terminal round"
            )

        omitted_match = self._terminal_match(321)
        omitted = run_hanchan(omitted_match, _selectors(unexpected))

        explicit_none_match = self._terminal_match(321)
        explicit_none = run_hanchan(
            explicit_none_match, _selectors(unexpected), on_delivery=None
        )

        recorded: list = []
        with_delivery_match = self._terminal_match(321)
        with_delivery = run_hanchan(
            with_delivery_match,
            _selectors(unexpected),
            on_delivery=recorded.extend,
        )

        self.assertEqual(omitted, explicit_none)
        self.assertEqual(omitted, with_delivery)
        self.assertEqual(omitted_match.history, explicit_none_match.history)
        self.assertEqual(omitted_match.history, with_delivery_match.history)
        self.assertTrue(recorded)


if __name__ == "__main__":
    unittest.main()
