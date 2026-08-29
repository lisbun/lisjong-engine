import unittest
from dataclasses import replace
from unittest.mock import patch

from _round_fixtures import (
    INERT_HAND,
    action_of_type,
    capture,
    daiminkan_action,
    dealt_state,
    declare_riichi,
    discard,
    draw_and_discard,
    play_quiet_turn,
    pon_action,
    resolve_all_pass,
    resolve_with,
    ron_action,
)

from lisjong_engine.legal_action import (
    AnkanLegalAction,
    KakanLegalAction,
    TsumoLegalAction,
)
from lisjong_engine.legal_actions import derive_tsumo_claim, dora_indicator_state
from lisjong_engine.meld import Pon
from lisjong_engine.round_event import RoundEndedEvent
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.round_result import (
    AbortiveDrawReason,
    AbortiveDrawResult,
    WinResult,
)
from lisjong_engine.round_state import (
    IllegalActionError,
    IllegalOperationError,
    RoundInvariantError,
    RoundState,
    StaleActionError,
)
from lisjong_engine.rule_presets import MAHJONG_SOUL_RULES, PROJECT_STANDARD_RULES
from lisjong_engine.rules import RonResolutionPolicy, RuleSet
from lisjong_engine.seat import Seat
from lisjong_engine.win_context import RiichiStatus, WinMethod, WinOrigin
from lisjong_engine.wind import Wind
from lisjong_engine.winning_finalization import build_effective_dora_indicators

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
_DEAD_WALL = (
    "1m",
    "9m",
    "9p",
    "9s",
    "3m",
    "4m",
    "6p",
    "7p",
    "1s",
    "2s",
    "3s",
    "4s",
    "5s",
    "6s",
)


def _hands_with(seat: Seat, hand: tuple[str, ...]) -> dict[Seat, tuple[str, ...]]:
    hands = {other: INERT_HAND for other in Seat}
    hands[seat] = hand
    return hands


def _apply_tsumo(state: RoundState, seat: Seat) -> WinResult:
    snapshot = state.legal_actions(seat)
    action = action_of_type(state, seat, TsumoLegalAction)
    state.apply(seat, action, expected_revision=snapshot.revision)
    result = state.result
    assert isinstance(result, WinResult)
    return result


def _declare_riichi(state: RoundState, seat: Seat) -> None:
    state.draw(seat)
    declare_riichi(state, seat)
    snapshot = state.legal_actions(seat)
    state.apply(seat, snapshot.actions[0], expected_revision=snapshot.revision)
    if state.phase is RoundPhase.AWAITING_REACTIONS:
        resolve_all_pass(state)


def _ron_state(*, rules: RuleSet | None = None) -> RoundState:
    state = dealt_state(
        hands={
            Seat.EAST: INERT_HAND,
            Seat.SOUTH: _FIRST_RON_HAND,
            Seat.WEST: _SECOND_RON_HAND,
            Seat.NORTH: _THIRD_RON_HAND,
        },
        draws=("1m",),
        with_dead_wall=True,
        rules=rules,
    )
    draw_and_discard(state, Seat.EAST)
    return state


def _resolve_ron(state: RoundState, seats: tuple[Seat, ...]) -> tuple[Seat, ...]:
    resolution = resolve_with(
        state,
        {seat: ron_action(state, seat) for seat in seats},
    )
    return resolution.ron_awarded_seats


def _kakan_ron_state(*, riichi_winner: bool = False) -> RoundState:
    state = dealt_state(
        hands=_KAKAN_HANDS,
        draws=("5z", "4p", "6z", "5z", "3p"),
        with_dead_wall=True,
    )
    draw_and_discard(state, Seat.EAST, "3p")
    resolve_with(state, {Seat.SOUTH: pon_action(state, Seat.SOUTH)})
    discard(state, Seat.SOUTH, "1z")
    if riichi_winner:
        state.draw(Seat.WEST)
        discard(state, Seat.WEST, "9s", declares_riichi=True)
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)
    else:
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
    resolve_with(state, {Seat.WEST: ron_action(state, Seat.WEST)})
    return state


def _ankan_ron_state() -> RoundState:
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
    resolve_with(state, {Seat.NORTH: ron_action(state, Seat.NORTH)})
    return state


class RoundTsumoFinalizationTest(unittest.TestCase):
    def test_ordinary_dealer_and_non_dealer_tsumo(self) -> None:
        dealer = dealt_state(
            hands=_hands_with(Seat.EAST, _TSUMO_HAND),
            draws=("5z", "6z", "6z", "6z", "7p"),
            with_dead_wall=True,
        )
        for _ in range(4):
            play_quiet_turn(dealer)
        dealer.draw(Seat.EAST)

        nondealer = dealt_state(
            hands=_hands_with(Seat.SOUTH, _TSUMO_HAND),
            draws=("5z", "7p"),
            with_dead_wall=True,
        )
        play_quiet_turn(nondealer)
        nondealer.draw(Seat.SOUTH)

        dealer_result = _apply_tsumo(dealer, Seat.EAST)
        nondealer_result = _apply_tsumo(nondealer, Seat.SOUTH)

        self.assertIs(dealer_result.method, WinMethod.TSUMO)
        self.assertIs(dealer_result.origin, WinOrigin.LIVE_WALL)
        self.assertIs(nondealer_result.method, WinMethod.TSUMO)
        self.assertIs(nondealer_result.origin, WinOrigin.LIVE_WALL)
        self.assertTrue(
            all(
                candidate.score.is_dealer
                for candidate in dealer_result.winners[0].score_selection.candidates
            )
        )
        self.assertTrue(
            all(
                not candidate.score.is_dealer
                for candidate in nondealer_result.winners[0].score_selection.candidates
            )
        )
        self.assertTrue(nondealer_result.winners[0].context.is_first_uninterrupted_turn)

    def test_dealer_tenhou_context_on_the_very_first_draw(self) -> None:
        """親が配牌直後の最初のツモで和了する天和相当のcontextを確認する。

        既存のdealer/non-dealer比較testは親を4巡進めてから和了させており、
        親自身の最初のツモでの`is_first_uninterrupted_turn`（天和相当）は
        確認していなかった。子の地和相当は既に確認済みのため、親側の
        対称なcontextをここで固定する。
        """
        state = dealt_state(
            hands=_hands_with(Seat.EAST, _TSUMO_HAND),
            draws=("7p",),
            with_dead_wall=True,
        )
        state.draw(Seat.EAST)

        result = _apply_tsumo(state, Seat.EAST)

        self.assertTrue(result.winners[0].context.is_first_uninterrupted_turn)
        self.assertTrue(
            all(
                candidate.score.is_dealer
                for candidate in result.winners[0].score_selection.candidates
            )
        )

    def test_riichi_double_riichi_and_ippatsu_facts_reach_context(self) -> None:
        double = dealt_state(
            hands=_hands_with(Seat.EAST, _TSUMO_HAND),
            draws=("5z", "6z", "6z", "6z", "7p"),
            with_dead_wall=True,
        )
        _declare_riichi(double, Seat.EAST)
        for _ in range(3):
            play_quiet_turn(double)
        double.draw(Seat.EAST)

        ordinary = dealt_state(
            hands=_hands_with(Seat.EAST, _TSUMO_HAND),
            draws=("5z", "6z", "6z", "6z", "5z", "7z", "7z", "7z", "7p"),
            with_dead_wall=True,
        )
        for _ in range(4):
            play_quiet_turn(ordinary)
        _declare_riichi(ordinary, Seat.EAST)
        for _ in range(3):
            play_quiet_turn(ordinary)
        ordinary.draw(Seat.EAST)

        double_context = _apply_tsumo(double, Seat.EAST).winners[0].context
        ordinary_context = _apply_tsumo(ordinary, Seat.EAST).winners[0].context

        self.assertIs(double_context.riichi_status, RiichiStatus.DOUBLE_RIICHI)
        self.assertTrue(double_context.is_ippatsu)
        self.assertIs(ordinary_context.riichi_status, RiichiStatus.RIICHI)
        self.assertTrue(ordinary_context.is_ippatsu)

    def test_haitei_tsumo_sets_last_tile(self) -> None:
        state = dealt_state(
            hands=_hands_with(Seat.EAST, _TSUMO_HAND),
            draws=("5z", "5z", "5z", "5z", "7p"),
            live_wall_size=57,
            with_dead_wall=True,
        )
        for _ in range(4):
            play_quiet_turn(state)
        state.draw(Seat.EAST)

        result = _apply_tsumo(state, Seat.EAST)

        self.assertTrue(result.is_last_tile)
        self.assertTrue(result.winners[0].context.is_last_tile)

    def test_failed_strict_tsumo_evaluation_is_atomic(self) -> None:
        state = dealt_state(
            hands=_hands_with(Seat.EAST, _TSUMO_HAND),
            draws=("7p",),
            with_dead_wall=True,
        )
        state.draw(Seat.EAST)
        snapshot = state.legal_actions(Seat.EAST)
        action = action_of_type(state, Seat.EAST, TsumoLegalAction)
        original = capture(state)

        with patch(
            "lisjong_engine.winning_finalization.evaluate_winning_scores",
            side_effect=RuntimeError("scoring failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "scoring failed"):
                state.apply(
                    Seat.EAST,
                    action,
                    expected_revision=snapshot.revision,
                )

        self.assertEqual(capture(state), original)


class RoundRonFinalizationTest(unittest.TestCase):
    def test_ordinary_ron_uses_awarded_seats_and_does_not_mutate_hands(self) -> None:
        state = _ron_state()
        awarded = _resolve_ron(state, (Seat.SOUTH, Seat.WEST))
        hands_before = {seat: state.hand_tiles(seat) for seat in awarded}
        revision = state.revision

        result = state.finalize_pending_win(expected_revision=revision)

        self.assertIsInstance(result, WinResult)
        self.assertIs(result.method, WinMethod.RON)
        self.assertIs(result.origin, WinOrigin.DISCARD)
        self.assertIs(result.source_seat, Seat.EAST)
        self.assertEqual(tuple(winner.seat for winner in result.winners), awarded)
        self.assertEqual(
            tuple(winner.context.seat_wind for winner in result.winners),
            (Wind.SOUTH, Wind.WEST),
        )
        self.assertEqual(
            {seat: state.hand_tiles(seat) for seat in awarded},
            hands_before,
        )
        self.assertEqual(state.revision, revision + 1)

    def test_head_bump_uses_the_single_e2_award(self) -> None:
        rules = replace(
            RuleSet.default(),
            ron_resolution_policy=RonResolutionPolicy.HEAD_BUMP,
            triple_ron_abortive_draw=False,
        )
        state = _ron_state(rules=rules)
        awarded = _resolve_ron(state, (Seat.SOUTH, Seat.WEST, Seat.NORTH))

        result = state.finalize_pending_win(expected_revision=state.revision)

        self.assertEqual(awarded, (Seat.SOUTH,))
        self.assertEqual(tuple(winner.seat for winner in result.winners), awarded)

    def test_triple_ron_uses_selected_fact_for_abortive_draw(self) -> None:
        state = _ron_state()
        _resolve_ron(state, (Seat.SOUTH, Seat.WEST, Seat.NORTH))

        result = state.finalize_pending_win(expected_revision=state.revision)

        self.assertEqual(
            result,
            AbortiveDrawResult(AbortiveDrawReason.TRIPLE_RON),
        )

    def test_triple_ron_can_keep_all_e2_awards_when_abort_is_disabled(self) -> None:
        rules = replace(RuleSet.default(), triple_ron_abortive_draw=False)
        state = _ron_state(rules=rules)
        awarded = _resolve_ron(state, (Seat.SOUTH, Seat.WEST, Seat.NORTH))

        result = state.finalize_pending_win(expected_revision=state.revision)

        self.assertEqual(tuple(winner.seat for winner in result.winners), awarded)

    def test_triple_ron_abortive_draw_follows_the_injected_preset(self) -> None:
        """同じ3人ロンの結末が、注入したpresetの設定だけで分かれる。

        雀魂presetは三家和を途中流局にせず通常のwin finalizationへ進み、
        project標準presetは`AbortiveDrawReason.TRIPLE_RON`で流局する。
        """
        mahjong_soul = _ron_state(rules=MAHJONG_SOUL_RULES)
        awarded = _resolve_ron(mahjong_soul, (Seat.SOUTH, Seat.WEST, Seat.NORTH))
        project_standard = _ron_state(rules=PROJECT_STANDARD_RULES)
        _resolve_ron(project_standard, (Seat.SOUTH, Seat.WEST, Seat.NORTH))

        mahjong_soul_result = mahjong_soul.finalize_pending_win(
            expected_revision=mahjong_soul.revision,
        )
        project_standard_result = project_standard.finalize_pending_win(
            expected_revision=project_standard.revision,
        )

        self.assertIsInstance(mahjong_soul_result, WinResult)
        self.assertEqual(
            tuple(winner.seat for winner in mahjong_soul_result.winners),
            awarded,
        )
        self.assertEqual(
            project_standard_result,
            AbortiveDrawResult(AbortiveDrawReason.TRIPLE_RON),
        )

    def test_houtei_ron_preserves_last_tile_fact(self) -> None:
        state = dealt_state(
            hands={
                Seat.EAST: INERT_HAND,
                Seat.SOUTH: _FIRST_RON_HAND,
                Seat.WEST: _SECOND_RON_HAND,
                Seat.NORTH: _THIRD_RON_HAND,
            },
            draws=("7z", "7z", "7z", "7z", "1m"),
            live_wall_size=57,
            with_dead_wall=True,
        )
        for _ in range(4):
            play_quiet_turn(state)
        draw_and_discard(state, Seat.EAST)
        _resolve_ron(state, (Seat.SOUTH,))

        result = state.finalize_pending_win(expected_revision=state.revision)

        self.assertTrue(result.is_last_tile)
        self.assertTrue(result.winners[0].context.is_last_tile)

    def test_kakan_and_ankan_chankan_keep_distinct_origins(self) -> None:
        kakan = _kakan_ron_state(riichi_winner=True)
        kakan_result = kakan.finalize_pending_win(expected_revision=kakan.revision)
        ankan = _ankan_ron_state()
        ankan_result = ankan.finalize_pending_win(expected_revision=ankan.revision)

        self.assertIs(kakan_result.origin, WinOrigin.KAKAN)
        self.assertIs(kakan_result.source_seat, Seat.SOUTH)
        self.assertIs(
            kakan_result.winners[0].context.riichi_status,
            RiichiStatus.RIICHI,
        )
        self.assertTrue(kakan_result.winners[0].context.is_ippatsu)
        self.assertEqual([type(meld) for meld in kakan.melds(Seat.SOUTH)], [Pon])
        self.assertIs(ankan_result.origin, WinOrigin.ANKAN)
        self.assertIs(ankan_result.source_seat, Seat.EAST)
        self.assertEqual(ankan.melds(Seat.EAST), ())

    def test_failed_strict_ron_evaluation_is_atomic(self) -> None:
        state = _ron_state()
        _resolve_ron(state, (Seat.SOUTH,))
        original = capture(state)

        with patch(
            "lisjong_engine.winning_finalization.evaluate_winning_scores",
            side_effect=RuntimeError("scoring failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "scoring failed"):
                state.finalize_pending_win(expected_revision=state.revision)

        self.assertEqual(capture(state), original)

    def test_forced_operation_rejects_stale_wrong_phase_missing_and_duplicate(
        self,
    ) -> None:
        state = _ron_state()
        _resolve_ron(state, (Seat.SOUTH,))
        original = capture(state)
        with self.assertRaises(StaleActionError):
            state.finalize_pending_win(expected_revision=state.revision - 1)
        self.assertEqual(capture(state), original)

        missing = _ron_state()
        _resolve_ron(missing, (Seat.SOUTH,))
        missing._pending_ron_resolution = None
        missing_original = capture(missing)
        with self.assertRaises(RoundInvariantError):
            missing.finalize_pending_win(expected_revision=missing.revision)
        self.assertEqual(capture(missing), missing_original)

        wrong_phase = dealt_state(
            hands=_hands_with(Seat.EAST, _TSUMO_HAND),
            draws=("7p",),
        )
        with self.assertRaises(IllegalOperationError):
            wrong_phase.finalize_pending_win(expected_revision=wrong_phase.revision)

        result = state.finalize_pending_win(expected_revision=state.revision)
        self.assertIs(state.result, result)
        with self.assertRaises(IllegalOperationError):
            state.finalize_pending_win(expected_revision=state.revision)


class DelayedDaiminkanDoraTest(unittest.TestCase):
    def test_rinshan_tsumo_includes_pending_daiminkan_dora_without_reveal(
        self,
    ) -> None:
        state = dealt_state(
            hands={
                Seat.EAST: (
                    "7z",
                    "7z",
                    "7z",
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
                ),
                Seat.SOUTH: (
                    "7z",
                    "1p",
                    "2p",
                    "3p",
                    "7p",
                    "8p",
                    "9p",
                    "4s",
                    "5s",
                    "6s",
                    "3z",
                    "3z",
                    "4z",
                ),
                Seat.WEST: INERT_HAND,
                Seat.NORTH: INERT_HAND,
            },
            draws=("6z", "5z"),
            dead_wall=_DEAD_WALL,
        )
        play_quiet_turn(state)
        state.draw(Seat.SOUTH)
        discard(state, Seat.SOUTH, "7z")
        resolve_with(state, {Seat.EAST: daiminkan_action(state, Seat.EAST)})
        state.draw_rinshan(Seat.EAST)
        revealed_before = state.revealed_dora_indicators

        result = _apply_tsumo(state, Seat.EAST)

        self.assertIs(result.origin, WinOrigin.RINSHAN)
        self.assertEqual(result.dora_indicators.visible, revealed_before)
        self.assertEqual(result.dora_indicators.kan, (state.dead_wall_tiles[6],))
        self.assertEqual(state.revealed_dora_indicators, revealed_before)
        self.assertEqual(state.pending_kan_dora_reveals, ())

    def test_following_discard_ron_excludes_pending_daiminkan_dora(self) -> None:
        state = dealt_state(
            hands={
                Seat.EAST: (
                    "7z",
                    "7z",
                    "7z",
                    "4m",
                    "5m",
                    "6m",
                    "1s",
                    "2s",
                    "3s",
                    "4s",
                    "5s",
                    "6s",
                    "9p",
                ),
                Seat.SOUTH: _FIRST_RON_HAND,
                Seat.WEST: (
                    "7z",
                    "1p",
                    "2p",
                    "3p",
                    "7p",
                    "8p",
                    "9p",
                    "3z",
                    "3z",
                    "4z",
                    "4z",
                    "5z",
                    "6z",
                ),
                Seat.NORTH: INERT_HAND,
            },
            draws=("6z", "6z", "5z"),
            dead_wall=_DEAD_WALL,
        )
        play_quiet_turn(state)
        play_quiet_turn(state)
        state.draw(Seat.WEST)
        discard(state, Seat.WEST, "7z")
        resolve_with(state, {Seat.EAST: daiminkan_action(state, Seat.EAST)})
        state.draw_rinshan(Seat.EAST)
        discard(state, Seat.EAST, "1m")
        resolve_with(state, {Seat.SOUTH: ron_action(state, Seat.SOUTH)})
        revealed_before = state.revealed_dora_indicators

        result = state.finalize_pending_win(expected_revision=state.revision)

        self.assertEqual(result.dora_indicators.visible, revealed_before)
        self.assertEqual(result.dora_indicators.kan, ())
        self.assertEqual(state.revealed_dora_indicators, revealed_before)

    def test_self_ankan_after_pending_daiminkan_does_not_lose_or_double_count(
        self,
    ) -> None:
        """daiminkan -> rinshan -> ankan -> rinshanという多重槓chainで、
        保留中のdaiminkanのkan-doraが失われず、確定済みankanのkan-doraと
        二重計上もされないことを確認する。
        """
        state = dealt_state(
            hands={
                Seat.EAST: (
                    "7z",
                    "7z",
                    "7z",
                    "2m",
                    "2m",
                    "2m",
                    "2m",
                    "5m",
                    "6m",
                    "8m",
                    "5p",
                    "8s",
                    "6s",
                ),
                Seat.SOUTH: (
                    "7z",
                    "1p",
                    "2p",
                    "3p",
                    "7p",
                    "8p",
                    "9p",
                    "4s",
                    "5s",
                    "6s",
                    "3z",
                    "3z",
                    "4z",
                ),
                Seat.WEST: INERT_HAND,
                Seat.NORTH: INERT_HAND,
            },
            draws=("6z", "5z"),
            dead_wall=_DEAD_WALL,
        )
        play_quiet_turn(state)
        state.draw(Seat.SOUTH)
        discard(state, Seat.SOUTH, "7z")
        resolve_with(state, {Seat.EAST: daiminkan_action(state, Seat.EAST)})
        self.assertEqual(state.pending_kan_dora_reveals, (Seat.EAST,))

        # 大明槓のrinshan tileはankanの対象にせず、既に手牌にある"2m"の
        # 暗刻4枚だけでankanを宣言し、pendingとconfirmedの槓ドラを混同
        # しないことを確認する。
        state.draw_rinshan(Seat.EAST)
        revealed_before_ankan = state.revealed_dora_indicators

        snapshot = state.legal_actions(Seat.EAST)
        state.apply(
            Seat.EAST,
            action_of_type(state, Seat.EAST, AnkanLegalAction),
            expected_revision=snapshot.revision,
        )

        # 確定した暗槓自身の槓ドラはpolicyに関わらず即座に公開されるが、
        # まだ解決していない大明槓分のpending entryは失われても複製されても
        # ならない。
        self.assertEqual(state.pending_kan_dora_reveals, (Seat.EAST,))
        self.assertEqual(
            len(state.revealed_dora_indicators),
            len(revealed_before_ankan) + 1,
        )

        state.draw_rinshan(Seat.EAST)
        view = state._committed_view()
        claim = derive_tsumo_claim(view, Seat.EAST)
        indicators = build_effective_dora_indicators(claim, dora_indicator_state(view))

        # この時点でEAST自身が起こした槓は2つ（保留中の大明槓、確定済みの
        # 暗槓）であり、EAST自身の嶺上ツモではその両方が有効になる。
        self.assertEqual(
            indicators.kan,
            (state.dead_wall_tiles[6], state.dead_wall_tiles[8]),
        )
        self.assertEqual(state.pending_kan_dora_reveals, (Seat.EAST,))


class FinishedWinInvariantTest(unittest.TestCase):
    def test_win_terminal_commit_cleans_state_and_blocks_restart(self) -> None:
        state = dealt_state(
            hands=_hands_with(Seat.EAST, _TSUMO_HAND),
            draws=("7p",),
            with_dead_wall=True,
        )
        state.draw(Seat.EAST)
        action = action_of_type(state, Seat.EAST, TsumoLegalAction)
        result = _apply_tsumo(state, Seat.EAST)

        self.assertIs(state.phase, RoundPhase.FINISHED)
        self.assertIs(state.result, result)
        terminal_events = tuple(
            event for event in state.events if isinstance(event, RoundEndedEvent)
        )
        self.assertEqual(len(terminal_events), 1)
        self.assertIs(terminal_events[0].result, result)
        self.assertIs(state.events[-1], terminal_events[0])
        self.assertIsNone(state.current_seat)
        self.assertIsNone(state.drawn_tile)
        self.assertIsNone(state.pending_ron_resolution)
        self.assertEqual(state.pending_kan_dora_reveals, ())
        for seat in Seat:
            self.assertEqual(state.legal_actions(seat).actions, ())

        with self.assertRaises(IllegalOperationError):
            state.draw(Seat.EAST)
        with self.assertRaises(IllegalOperationError):
            state.draw_rinshan(Seat.EAST)
        with self.assertRaises(IllegalActionError):
            state.apply(Seat.EAST, action, expected_revision=state.revision)
        with self.assertRaises(IllegalOperationError):
            state.resolve_reactions({}, expected_revision=state.revision)
        with self.assertRaises(IllegalOperationError):
            state.finalize_pending_win(expected_revision=state.revision)

    def test_non_finished_and_finished_terminal_invariants_fail_closed(self) -> None:
        state = dealt_state(
            hands=_hands_with(Seat.EAST, _TSUMO_HAND),
            draws=("7p",),
        )
        transition = state._begin()
        transition.result = AbortiveDrawResult(AbortiveDrawReason.TRIPLE_RON)
        with self.assertRaises(RoundInvariantError):
            state._commit(transition)

        transition = state._begin()
        transition.phase = RoundPhase.FINISHED
        transition.current_seat = None
        with self.assertRaises(RoundInvariantError):
            state._commit(transition)


if __name__ == "__main__":
    unittest.main()
