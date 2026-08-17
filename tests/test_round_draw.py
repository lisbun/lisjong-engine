import unittest
from dataclasses import replace

from _round_fixtures import (
    INERT_HAND,
    action_of_type,
    advance_to_seat,
    capture,
    dealt_state,
    discard,
    discard_drawn_tile,
    draw_and_discard,
    has_action_of_type,
    play_quiet_turn,
    pon_action,
    resolve_all_pass,
    resolve_with,
    ron_action,
)

from lisjong_engine.furiten import FuritenReason
from lisjong_engine.legal_action import (
    AnkanLegalAction,
    DiscardDeclaration,
    KakanLegalAction,
    NineTerminalsLegalAction,
    RonLegalAction,
)
from lisjong_engine.round_event import RoundEndedEvent
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.round_result import (
    AbortiveDrawReason,
    AbortiveDrawResult,
    ExhaustiveDrawResult,
    WinResult,
)
from lisjong_engine.round_state import (
    IllegalActionError,
    IllegalOperationError,
    RoundInvariantError,
    RoundState,
    StaleActionError,
)
from lisjong_engine.rules import RuleSet
from lisjong_engine.seat import Seat

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
_EIGHT_TYPES_HAND = (
    "1m",
    "9m",
    "1p",
    "9p",
    "1s",
    "9s",
    "1z",
    "2z",
    "2m",
    "3m",
    "4m",
    "5m",
    "6m",
)


def _hands_with(seat: Seat, hand: tuple[str, ...]) -> dict[Seat, tuple[str, ...]]:
    hands = {other: INERT_HAND for other in Seat}
    hands[seat] = hand
    return hands


class NineTerminalsLegalActionTest(unittest.TestCase):
    def test_nine_distinct_types_offers_the_action(self) -> None:
        state = dealt_state(
            hands=_hands_with(Seat.EAST, _NINE_TERMINALS_HAND),
            draws=("2m",),
        )
        state.draw(Seat.EAST)

        self.assertTrue(has_action_of_type(state, Seat.EAST, NineTerminalsLegalAction))

    def test_eight_distinct_types_does_not_offer_the_action(self) -> None:
        state = dealt_state(
            hands=_hands_with(Seat.EAST, _EIGHT_TYPES_HAND),
            draws=("7m",),
        )
        state.draw(Seat.EAST)

        self.assertFalse(has_action_of_type(state, Seat.EAST, NineTerminalsLegalAction))

    def test_disabled_rule_does_not_offer_the_action(self) -> None:
        rules = replace(RuleSet.default(), nine_terminals_abortive_draw_enabled=False)
        state = dealt_state(
            hands=_hands_with(Seat.EAST, _NINE_TERMINALS_HAND),
            draws=("2m",),
            rules=rules,
        )
        state.draw(Seat.EAST)

        self.assertFalse(has_action_of_type(state, Seat.EAST, NineTerminalsLegalAction))

    def test_after_own_first_discard_the_action_disappears(self) -> None:
        state = dealt_state(
            hands=_hands_with(Seat.EAST, _NINE_TERMINALS_HAND),
            draws=("2m", "5m", "6m", "8m", "3m"),
        )
        draw_and_discard(state, Seat.EAST)
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)
        advance_to_seat(state, Seat.EAST)
        state.draw(Seat.EAST)

        self.assertFalse(has_action_of_type(state, Seat.EAST, NineTerminalsLegalAction))

    def test_meld_anywhere_before_first_turn_disqualifies_a_later_seat(self) -> None:
        east_hand = (
            "5m",
            "2m",
            "3m",
            "4m",
            "6m",
            "7m",
            "8m",
            "2p",
            "3p",
            "4p",
            "6p",
            "7p",
            "8p",
        )
        west_hand = (
            "5m",
            "5m",
            "2s",
            "3s",
            "4s",
            "6s",
            "7s",
            "8s",
            "2m",
            "3m",
            "4m",
            "6m",
            "7m",
        )
        state = dealt_state(
            hands={
                Seat.EAST: east_hand,
                Seat.SOUTH: _NINE_TERMINALS_HAND,
                Seat.WEST: west_hand,
                Seat.NORTH: INERT_HAND,
            },
            draws=("5s", "6s", "7s"),
        )
        draw_and_discard(state, Seat.EAST, "5m")
        self.assertIs(state.phase, RoundPhase.AWAITING_REACTIONS)
        resolve_with(state, {Seat.WEST: pon_action(state, Seat.WEST)})
        self.assertTrue(state.has_meld_occurred)
        discard(state, Seat.WEST, "2s")
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)
        play_quiet_turn(state)  # NORTH's first turn (draws "6s")
        play_quiet_turn(state)  # EAST's second turn (draws "7s")
        state.draw(Seat.SOUTH)

        self.assertFalse(
            has_action_of_type(state, Seat.SOUTH, NineTerminalsLegalAction)
        )

    def test_declaring_it_finishes_the_round_as_abortive(self) -> None:
        state = dealt_state(
            hands=_hands_with(Seat.EAST, _NINE_TERMINALS_HAND),
            draws=("2m",),
        )
        state.draw(Seat.EAST)
        snapshot = state.legal_actions(Seat.EAST)

        state.apply(
            Seat.EAST,
            NineTerminalsLegalAction(),
            expected_revision=snapshot.revision,
        )

        self.assertEqual(
            state.result, AbortiveDrawResult(AbortiveDrawReason.NINE_TERMINALS)
        )
        self.assertIs(state.phase, RoundPhase.FINISHED)

    def test_not_declaring_it_allows_a_normal_discard(self) -> None:
        state = dealt_state(
            hands=_hands_with(Seat.EAST, _NINE_TERMINALS_HAND),
            draws=("2m",),
        )

        draw_and_discard(state, Seat.EAST)

        self.assertIsNot(state.phase, RoundPhase.FINISHED)

    def test_apply_revalidates_and_rejects_a_no_longer_eligible_claim(self) -> None:
        """`apply()`の外側membership checkは、直前に`legal_actions()`を
        呼んでいなくても既にeligibility不成立を拒否してしまうため、この
        経路単体では`_apply_nine_terminals()`自身のstrict revalidationを
        public API経由で再現できない。ここだけprivate methodを直接呼び、
        内側の防御自体もfail closedであることを確認する。
        """
        state = dealt_state(
            hands=_hands_with(Seat.EAST, _NINE_TERMINALS_HAND),
            draws=("2m", "3m"),
        )
        draw_and_discard(state, Seat.EAST)
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)
        original = capture(state)

        with self.assertRaises(RoundInvariantError):
            state._apply_nine_terminals(Seat.EAST)

        self.assertEqual(capture(state), original)

    def test_stale_declaration_is_rejected_atomically(self) -> None:
        state = dealt_state(
            hands=_hands_with(Seat.EAST, _NINE_TERMINALS_HAND),
            draws=("2m",),
        )
        state.draw(Seat.EAST)
        snapshot = state.legal_actions(Seat.EAST)
        original = capture(state)

        with self.assertRaises(StaleActionError):
            state.apply(
                Seat.EAST,
                NineTerminalsLegalAction(),
                expected_revision=snapshot.revision - 1,
            )

        self.assertEqual(capture(state), original)

    def test_mismatched_action_is_rejected(self) -> None:
        state = dealt_state(
            hands=_hands_with(Seat.EAST, _EIGHT_TYPES_HAND),
            draws=("7m",),
        )
        state.draw(Seat.EAST)
        snapshot = state.legal_actions(Seat.EAST)
        original = capture(state)

        with self.assertRaises(IllegalActionError):
            state.apply(
                Seat.EAST,
                NineTerminalsLegalAction(),
                expected_revision=snapshot.revision,
            )

        self.assertEqual(capture(state), original)


_SAFE_FILLER = ("2m", "5m", "8m", "2p", "5p", "8p", "2s", "5s", "8s", "5z", "6z", "7z")


def _wind_hand(name: str, filler: tuple[str, ...] = _SAFE_FILLER) -> tuple[str, ...]:
    return (name, *filler)


class FourWindsAbortiveDrawTest(unittest.TestCase):
    def _play_four_first_discards(self, tile_name: str, *, rules=None) -> RoundState:
        hands = {seat: _wind_hand(tile_name) for seat in Seat}
        state = dealt_state(hands=hands, draws=("3m", "6m", "9m", "4p"), rules=rules)
        for seat in Seat:
            draw_and_discard(state, seat, tile_name)
            if state.phase is RoundPhase.AWAITING_REACTIONS:
                resolve_all_pass(state)
        return state

    def test_four_identical_first_east_wind_discards_end_the_round(self) -> None:
        state = self._play_four_first_discards("1z")

        self.assertEqual(
            state.result, AbortiveDrawResult(AbortiveDrawReason.FOUR_WINDS)
        )
        self.assertIs(state.phase, RoundPhase.FINISHED)

    def test_three_matching_first_discards_do_not_trigger(self) -> None:
        hands = {
            Seat.EAST: _wind_hand("1z"),
            Seat.SOUTH: _wind_hand("1z"),
            Seat.WEST: _wind_hand("1z"),
            Seat.NORTH: _wind_hand("2z"),
        }
        state = dealt_state(hands=hands, draws=("3m", "6m", "9m", "4p"))
        for seat, wind_name in (
            (Seat.EAST, "1z"),
            (Seat.SOUTH, "1z"),
            (Seat.WEST, "1z"),
            (Seat.NORTH, "2z"),
        ):
            draw_and_discard(state, seat, wind_name)
            if state.phase is RoundPhase.AWAITING_REACTIONS:
                resolve_all_pass(state)

        self.assertIsNone(state.result)
        self.assertIs(state.phase, RoundPhase.AWAITING_DRAW)

    def test_four_matching_non_wind_first_discards_do_not_trigger(self) -> None:
        state = self._play_four_first_discards("3s")

        self.assertIsNone(state.result)
        self.assertIs(state.phase, RoundPhase.AWAITING_DRAW)

    def test_disabled_rule_continues_to_next_draw(self) -> None:
        rules = replace(RuleSet.default(), four_winds_abortive_draw_enabled=False)
        state = self._play_four_first_discards("1z", rules=rules)

        self.assertIsNone(state.result)
        self.assertIs(state.phase, RoundPhase.AWAITING_DRAW)

    # 「4人全員の第一打が同一の風牌」という成立条件が成り立った時点で、
    # 4番目の打牌者以外の3席は全員すでにその風牌を自分の河へ捨てている。
    # したがって、その3席のうち誰かがその風牌を和了牌として待っていても、
    # `furiten.derive_furiten_reasons`が`waits & discarded_tile_types`から
    # 導く`FuritenReason.DISCARD`により、`ron_legality.can_declare_ron`は
    # 必ずFalseを返す（4番目の打牌者自身は自分の捨て牌へロンできない）。
    # つまり四風連打の成立条件を満たす4投目に対して合法なRonが成立しない
    # のは物理牌の存在数ではなく、既存のフリテン契約が構造的に保証する
    # ことである。Ronが`_apply_resolution`で四風連打判定より常に先に
    # 評価されることはcode上のif/elif分岐順序で保証されており、フリテン
    # 契約自体は`test_furiten.py`（`test_discard_furiten_when_the_river_
    # contains_a_wait`等）と`test_ron_legality.py`
    # （`test_a_furiten_seat_cannot_ron`）が別の起点から固定している。
    #
    # 以下は、その意味を四風連打の文脈で最小限固定する回帰test。4人分の
    # 一致した第一打を厳密に再現する必要はなく、「自分の河に和了牌がある
    # 状態で、同じ牌がもう一度捨てられても合法なRonにならない」という
    # 契約だけを、実際にlegal_actions()経由で確認する。
    def test_own_river_wait_tile_cannot_be_ronned_even_if_winning_shape_completes(
        self,
    ) -> None:
        tenpai_hand = (
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
            "7p",
            "1z",
        )
        quiet_hand = (
            "1m",
            "4m",
            "7m",
            "1p",
            "4p",
            "7p",
            "1s",
            "4s",
            "7s",
            "2z",
            "3z",
            "4z",
            "5z",
        )
        state = dealt_state(
            hands={
                Seat.EAST: tenpai_hand,
                Seat.SOUTH: quiet_hand,
                Seat.WEST: quiet_hand,
                Seat.NORTH: quiet_hand,
            },
            draws=("1z", "1z"),
        )
        draw_and_discard(state, Seat.EAST)
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)
        self.assertTrue(state.is_furiten(Seat.EAST))
        self.assertIn(FuritenReason.DISCARD, state.furiten_reasons(Seat.EAST))

        draw_and_discard(state, Seat.SOUTH)

        self.assertIs(state.phase, RoundPhase.AWAITING_REACTIONS)
        east_actions = state.legal_actions(Seat.EAST).actions
        self.assertFalse(any(isinstance(a, RonLegalAction) for a in east_actions))


class FourRiichiAbortiveDrawTest(unittest.TestCase):
    _HANDS = {
        Seat.EAST: (
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
        Seat.SOUTH: (
            "2p",
            "3p",
            "4s",
            "5s",
            "6s",
            "7m",
            "8m",
            "9m",
            "3z",
            "3z",
            "3z",
            "4z",
            "4z",
        ),
        Seat.WEST: (
            "2s",
            "3s",
            "4m",
            "5m",
            "6m",
            "7p",
            "8p",
            "9p",
            "5z",
            "5z",
            "5z",
            "6z",
            "6z",
        ),
        Seat.NORTH: (
            "6m",
            "7m",
            "1p",
            "2p",
            "3p",
            "4s",
            "5s",
            "6s",
            "7z",
            "7z",
            "7z",
            "2z",
            "2z",
        ),
    }

    def _declare_riichi(self, state: RoundState, seat: Seat) -> None:
        drawn_tile = state.draw(seat)
        snapshot = state.legal_actions(seat)
        action = next(
            action
            for action in snapshot.actions
            if hasattr(action, "declaration")
            and action.declaration is DiscardDeclaration.RIICHI
            and action.tile_id == drawn_tile.id
        )
        state.apply(seat, action, expected_revision=snapshot.revision)
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)

    def test_fourth_established_riichi_finishes_the_round(self) -> None:
        state = dealt_state(hands=self._HANDS, draws=("9s", "1s", "1m", "4z"))
        for seat in Seat:
            self._declare_riichi(state, seat)

        self.assertEqual(
            state.result, AbortiveDrawResult(AbortiveDrawReason.FOUR_RIICHI)
        )
        self.assertIs(state.phase, RoundPhase.FINISHED)
        for seat in Seat:
            self.assertTrue(state.is_riichi_established(seat))

    def test_three_riichi_do_not_trigger(self) -> None:
        state = dealt_state(hands=self._HANDS, draws=("9s", "1s", "1m", "7z"))
        for seat in (Seat.EAST, Seat.SOUTH, Seat.WEST):
            self._declare_riichi(state, seat)
        draw_and_discard(state, Seat.NORTH, "7z")
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)

        self.assertIsNone(state.result)

    def test_fourth_riichi_discard_ron_prevents_establishment_and_four_riichi(
        self,
    ) -> None:
        """四家立直と異なり、fourth riichi宣言牌は共有の牌種一致を要求
        しないため、待つ側の予備牌を圧迫せずにロン局面を構成できる。
        """
        hands = {
            Seat.EAST: (
                "2p",
                "3p",
                "4p",
                "5p",
                "6p",
                "7p",
                "2s",
                "3s",
                "4s",
                "5s",
                "5s",
                "7m",
                "8m",
            ),
            Seat.SOUTH: (
                "1m",
                "2m",
                "3m",
                "4m",
                "5m",
                "6m",
                "7m",
                "8m",
                "9m",
                "1p",
                "2p",
                "3p",
                "9p",
            ),
            Seat.WEST: (
                "1s",
                "2s",
                "3s",
                "4s",
                "5s",
                "6s",
                "7s",
                "8s",
                "9s",
                "1z",
                "1z",
                "1z",
                "1p",
            ),
            Seat.NORTH: (
                "1m",
                "1m",
                "4m",
                "4m",
                "7m",
                "7m",
                "1p",
                "1p",
                "4p",
                "4p",
                "7p",
                "7p",
                "2z",
            ),
        }
        state = dealt_state(hands=hands, draws=("9s", "3z", "5z", "9m"))
        draw_and_discard(state, Seat.EAST, "9s")
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)
        for seat in (Seat.SOUTH, Seat.WEST):
            self._declare_riichi(state, seat)
        state.draw(Seat.NORTH)
        snapshot = state.legal_actions(Seat.NORTH)
        action = next(
            action
            for action in snapshot.actions
            if hasattr(action, "declaration")
            and action.declaration is DiscardDeclaration.RIICHI
        )
        state.apply(Seat.NORTH, action, expected_revision=snapshot.revision)
        self.assertIs(state.phase, RoundPhase.AWAITING_REACTIONS)
        resolve_with(state, {Seat.EAST: ron_action(state, Seat.EAST)})

        self.assertIs(state.phase, RoundPhase.AWAITING_WIN_FINALIZATION)
        result = state.finalize_pending_win(expected_revision=state.revision)
        self.assertIsInstance(result, WinResult)
        self.assertIs(state.result, result)
        self.assertFalse(state.is_riichi_established(Seat.NORTH))

    def test_disabled_rule_does_not_trigger(self) -> None:
        rules = replace(RuleSet.default(), four_riichi_abortive_draw_enabled=False)
        state = dealt_state(
            hands=self._HANDS, draws=("9s", "1s", "1m", "4z"), rules=rules
        )
        for seat in Seat:
            self._declare_riichi(state, seat)

        self.assertIsNone(state.result)
        self.assertTrue(all(state.is_riichi_established(seat) for seat in Seat))


_FOUR_KANS_DEAD_WALL = (
    "8m",
    "9m",
    "8s",
    "9s",
    "4m",
    "7m",
    "2p",
    "5p",
    "8p",
    "2s",
    "3s",
    "5s",
    "6s",
    "9s",
)


class FourKansAbortiveDrawTest(unittest.TestCase):
    _EAST_TWO_QUADS_HAND = (
        "2m",
        "2m",
        "2m",
        "2m",
        "3m",
        "3m",
        "3m",
        "3m",
        "2p",
        "3p",
        "5p",
        "6p",
        "8p",
    )
    _SOUTH_TWO_QUADS_HAND = (
        "5m",
        "5m",
        "5m",
        "5m",
        "6m",
        "6m",
        "6m",
        "6m",
        "2s",
        "3s",
        "5s",
        "6s",
        "8s",
    )

    def _declare_ankan(self, state: RoundState, seat: Seat) -> None:
        snapshot = state.legal_actions(seat)
        state.apply(
            seat,
            action_of_type(state, seat, AnkanLegalAction),
            expected_revision=snapshot.revision,
        )

    def test_four_kans_across_two_owners_finishes_immediately_on_the_fourth(
        self,
    ) -> None:
        state = dealt_state(
            hands={
                Seat.EAST: self._EAST_TWO_QUADS_HAND,
                Seat.SOUTH: self._SOUTH_TWO_QUADS_HAND,
                Seat.WEST: INERT_HAND,
                Seat.NORTH: INERT_HAND,
            },
            draws=("9p", "3p"),
            dead_wall=_FOUR_KANS_DEAD_WALL,
        )
        state.draw(Seat.EAST)
        self._declare_ankan(state, Seat.EAST)
        state.draw_rinshan(Seat.EAST)
        self._declare_ankan(state, Seat.EAST)
        state.draw_rinshan(Seat.EAST)
        discard_drawn_tile(state, Seat.EAST)
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)

        state.draw(Seat.SOUTH)
        self._declare_ankan(state, Seat.SOUTH)
        state.draw_rinshan(Seat.SOUTH)
        self._declare_ankan(state, Seat.SOUTH)

        self.assertEqual(state.result, AbortiveDrawResult(AbortiveDrawReason.FOUR_KANS))
        self.assertIs(state.phase, RoundPhase.FINISHED)
        # 第四槓の成立で直ちに終局するため、5つ目の槓ドラ表示牌の公開へは
        # 到達しない（`Wall.reveal_kan_dora()`のRuntimeErrorを回避する）。
        with self.assertRaises(IllegalOperationError):
            state.draw_rinshan(Seat.SOUTH)

    def test_four_kans_owned_by_a_single_player_is_not_abortive(self) -> None:
        east_four_quads_hand = (
            "2m",
            "2m",
            "2m",
            "2m",
            "3m",
            "3m",
            "3m",
            "3m",
            "5m",
            "5m",
            "5m",
            "5m",
            "9p",
        )
        dead_wall = (
            "6s",
            "8s",
            "9s",
            "6p",
            "1m",
            "4m",
            "7m",
            "1s",
            "4s",
            "7s",
            "1z",
            "2z",
            "3z",
            "4z",
        )
        state = dealt_state(
            hands={
                Seat.EAST: east_four_quads_hand,
                Seat.SOUTH: INERT_HAND,
                Seat.WEST: INERT_HAND,
                Seat.NORTH: INERT_HAND,
            },
            draws=("9p",),
            dead_wall=dead_wall,
        )
        state.draw(Seat.EAST)
        self._declare_ankan(state, Seat.EAST)
        state.draw_rinshan(Seat.EAST)
        self._declare_ankan(state, Seat.EAST)
        state.draw_rinshan(Seat.EAST)
        self._declare_ankan(state, Seat.EAST)
        state.draw_rinshan(Seat.EAST)

        self.assertIsNone(state.result)
        self.assertIs(state.phase, RoundPhase.AWAITING_DISCARD)
        self.assertEqual(len(state.melds(Seat.EAST)), 3)

    def test_chankan_of_the_fourth_kan_does_not_count_toward_four_kans(self) -> None:
        rules = replace(RuleSet.default(), kokushi_ankan_chankan_enabled=True)
        kokushi_hand = (
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
            "6z",
        )
        south_hand = (
            "7z",
            "7z",
            "7z",
            "7z",
            "2s",
            "3s",
            "5s",
            "6s",
            "8s",
            "6m",
            "7m",
            "8m",
            "9m",
        )
        dead_wall = (
            "4m",
            "4p",
            "4s",
            "7p",
            "7s",
            "9p",
            "9s",
            "1z",
            "2z",
            "3z",
            "4z",
            "5z",
            "1p",
            "1s",
        )
        state = dealt_state(
            hands={
                Seat.EAST: self._EAST_TWO_QUADS_HAND,
                Seat.SOUTH: south_hand,
                Seat.WEST: kokushi_hand,
                Seat.NORTH: INERT_HAND,
            },
            draws=("4p",),
            dead_wall=dead_wall,
            rules=rules,
        )
        state.draw(Seat.EAST)
        self._declare_ankan(state, Seat.EAST)
        state.draw_rinshan(Seat.EAST)
        self._declare_ankan(state, Seat.EAST)
        state.draw_rinshan(Seat.EAST)
        discard_drawn_tile(state, Seat.EAST)
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)
        state.draw(Seat.SOUTH)
        self._declare_ankan(state, Seat.SOUTH)
        self.assertIs(state.phase, RoundPhase.AWAITING_ANKAN_REACTIONS)
        resolve_with(state, {Seat.WEST: ron_action(state, Seat.WEST)})

        self.assertIs(state.phase, RoundPhase.AWAITING_WIN_FINALIZATION)
        self.assertNotIsInstance(state.result, AbortiveDrawResult)
        self.assertEqual(state.melds(Seat.SOUTH), ())

    def test_disabled_rule_continues_past_four_kans(self) -> None:
        rules = replace(RuleSet.default(), four_kans_abortive_draw_enabled=False)
        state = dealt_state(
            hands={
                Seat.EAST: self._EAST_TWO_QUADS_HAND,
                Seat.SOUTH: self._SOUTH_TWO_QUADS_HAND,
                Seat.WEST: INERT_HAND,
                Seat.NORTH: INERT_HAND,
            },
            draws=("9p", "3p"),
            dead_wall=_FOUR_KANS_DEAD_WALL,
            rules=rules,
        )
        state.draw(Seat.EAST)
        self._declare_ankan(state, Seat.EAST)
        state.draw_rinshan(Seat.EAST)
        self._declare_ankan(state, Seat.EAST)
        state.draw_rinshan(Seat.EAST)
        discard_drawn_tile(state, Seat.EAST)
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)
        state.draw(Seat.SOUTH)
        self._declare_ankan(state, Seat.SOUTH)
        state.draw_rinshan(Seat.SOUTH)
        self._declare_ankan(state, Seat.SOUTH)

        self.assertIsNone(state.result)
        self.assertIs(state.phase, RoundPhase.AWAITING_RINSHAN_DRAW)

    def test_a_fifth_kan_is_unreachable_even_with_a_quad_in_hand(self) -> None:
        """`Wall.can_draw_rinshan`は4回のrinshan drawで恒久的にFalseへなり、
        Ankan/Kakan/Daiminkanいずれの生成もこの1つのfactへ同じく従う
        （`legal_actions.py`の`derive_turn_actions`・`_derive_call_actions`、
        `reaction_boundary._may_call`）。したがって四槓散了が成立しない
        （1人が4槓、またはruleを無効化した）場合でも、5つ目の槓は
        legal actionとして提示され得ない。手牌上に槓子が実在していても
        提示されないことを、fabricateしたactionのapply()拒否まで含めて
        直接確認する。
        """
        rules = replace(RuleSet.default(), four_kans_abortive_draw_enabled=False)
        east_hand = (
            "2m",
            "2m",
            "2m",
            "2m",
            "3m",
            "3m",
            "3m",
            "3m",
            "2p",
            "3p",
            "5p",
            "6p",
            "8p",
        )
        south_hand = (
            "5m",
            "5m",
            "5m",
            "5m",
            "6m",
            "6m",
            "6m",
            "6m",
            "2s",
            "2s",
            "2s",
            "3s",
            "6s",
        )
        dead_wall = (
            "8m",
            "9m",
            "8s",
            "2s",
            "4m",
            "7m",
            "2p",
            "5p",
            "8p",
            "3p",
            "3s",
            "5s",
            "6s",
            "9s",
        )
        state = dealt_state(
            hands={
                Seat.EAST: east_hand,
                Seat.SOUTH: south_hand,
                Seat.WEST: INERT_HAND,
                Seat.NORTH: INERT_HAND,
            },
            draws=("9p", "3p"),
            dead_wall=dead_wall,
            rules=rules,
        )
        state.draw(Seat.EAST)
        self._declare_ankan(state, Seat.EAST)
        state.draw_rinshan(Seat.EAST)
        self._declare_ankan(state, Seat.EAST)
        state.draw_rinshan(Seat.EAST)
        discard_drawn_tile(state, Seat.EAST)
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)
        state.draw(Seat.SOUTH)
        self._declare_ankan(state, Seat.SOUTH)
        state.draw_rinshan(Seat.SOUTH)
        self._declare_ankan(state, Seat.SOUTH)  # the 4th kan overall
        self.assertEqual(state.remaining_rinshan_count, 1)
        state.draw_rinshan(Seat.SOUTH)  # consumes the last rinshan slot
        self.assertEqual(state.remaining_rinshan_count, 0)

        hand = state.hand_tiles(Seat.SOUTH)
        quad_tile_ids = tuple(
            sorted(
                tile.id
                for tile in hand
                if sum(1 for other in hand if other.tile_type == tile.tile_type) == 4
            )
        )
        # South genuinely holds a complete "2s" quad at this point.
        self.assertEqual(len(quad_tile_ids), 4)

        snapshot = state.legal_actions(Seat.SOUTH)
        self.assertFalse(
            any(isinstance(action, AnkanLegalAction) for action in snapshot.actions)
        )
        self.assertFalse(
            any(isinstance(action, KakanLegalAction) for action in snapshot.actions)
        )

        with self.assertRaises(IllegalActionError):
            state.apply(
                Seat.SOUTH,
                AnkanLegalAction(quad_tile_ids),
                expected_revision=state.revision,
            )


class ExhaustiveDrawTest(unittest.TestCase):
    def test_wall_reaching_zero_alone_does_not_finish_the_round(self) -> None:
        state = dealt_state(
            hands={seat: INERT_HAND for seat in Seat},
            draws=("5z", "6z", "7z"),
            live_wall_size=55,
        )
        play_quiet_turn(state)
        play_quiet_turn(state)
        state.draw(Seat.WEST)

        self.assertEqual(state.remaining_count, 0)
        self.assertIsNot(state.phase, RoundPhase.FINISHED)
        self.assertIsNone(state.result)

    def test_fast_path_final_discard_without_reaction_is_exhaustive(self) -> None:
        tenpai_hand = (
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
            "7p",
            "9s",
        )
        state = dealt_state(
            hands={
                Seat.EAST: tenpai_hand,
                Seat.SOUTH: INERT_HAND,
                Seat.WEST: INERT_HAND,
                Seat.NORTH: INERT_HAND,
            },
            draws=("9m", "5p", "6s", "6z"),
            live_wall_size=56,
        )
        for _ in range(3):
            play_quiet_turn(state)
        self.assertEqual(state.remaining_count, 1)
        draw_and_discard(state, Seat.NORTH)

        self.assertIsInstance(state.result, ExhaustiveDrawResult)
        self.assertIs(state.phase, RoundPhase.FINISHED)
        self.assertEqual(state.result.tenpai_seats, (Seat.EAST,))
        self.assertIn(Seat.EAST, state.result.nagashi_mangan_seats)

    def test_yakuless_wait_still_counts_as_semantic_tenpai(self) -> None:
        """役なしのtanki待ちが、tenpai判定では和了形へ到達できることだけで
        tenpaiと認められることを確認する。

        この牌姿はツモなら門前清自摸和が付くため、役なしを確認するprobeは
        あえてRon側で行う（メンゼンツモは自摸限定であり、この待ち自体は
        平和の条件（両面待ち）もタンヤオ（9sを含む）も満たさない）。
        Ronとしては役が無いため`RonLegalAction`は提示されない一方、
        荒牌流局のtenpai_seatsは役の有無を問わない`winning_tile_types`の
        非空だけで判定するため、この牌姿はtenpai_seatsに含まれる。
        両者が別のgateであることを1つのtestで固定する。
        """
        yakuless_tanki_hand = (
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
            "7p",
            "9s",
        )
        probe_state = dealt_state(
            hands=_hands_with(Seat.EAST, yakuless_tanki_hand),
            draws=("2m", "9s"),
        )
        draw_and_discard(probe_state, Seat.EAST)
        if probe_state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(probe_state)
        draw_and_discard(probe_state, Seat.SOUTH)
        self.assertIs(probe_state.phase, RoundPhase.AWAITING_REACTIONS)
        self.assertFalse(
            any(
                isinstance(action, RonLegalAction)
                for action in probe_state.legal_actions(Seat.EAST).actions
            )
        )

        state = dealt_state(
            hands={
                Seat.EAST: yakuless_tanki_hand,
                Seat.SOUTH: INERT_HAND,
                Seat.WEST: INERT_HAND,
                Seat.NORTH: INERT_HAND,
            },
            draws=("5m", "5p", "6s", "6z"),
            live_wall_size=56,
        )
        for _ in range(3):
            play_quiet_turn(state)
        draw_and_discard(state, Seat.NORTH)

        self.assertIsInstance(state.result, ExhaustiveDrawResult)
        self.assertIn(Seat.EAST, state.result.tenpai_seats)

    def test_explicit_all_pass_on_final_discard_is_exhaustive(self) -> None:
        east_hand = (
            "2p",
            "3p",
            "4p",
            "5p",
            "6p",
            "7p",
            "2s",
            "3s",
            "4s",
            "5s",
            "5s",
            "7m",
            "8m",
        )
        state = dealt_state(
            hands={
                Seat.EAST: east_hand,
                Seat.SOUTH: INERT_HAND,
                Seat.WEST: INERT_HAND,
                Seat.NORTH: INERT_HAND,
            },
            draws=("9s", "5z", "6z", "9m"),
            live_wall_size=56,
        )
        for _ in range(3):
            play_quiet_turn(state)
        self.assertEqual(state.remaining_count, 1)
        draw_and_discard(state, Seat.NORTH)
        self.assertIs(state.phase, RoundPhase.AWAITING_REACTIONS)
        resolve_all_pass(state)

        self.assertIsInstance(state.result, ExhaustiveDrawResult)
        self.assertIs(state.phase, RoundPhase.FINISHED)
        self.assertEqual(state.result.tenpai_seats, (Seat.EAST,))
        self.assertTrue(state.is_furiten(Seat.EAST))

    def test_ron_on_the_final_discard_prevents_exhaustive_draw(self) -> None:
        east_hand = (
            "2p",
            "3p",
            "4p",
            "5p",
            "6p",
            "7p",
            "2s",
            "3s",
            "4s",
            "5s",
            "5s",
            "7m",
            "8m",
        )
        state = dealt_state(
            hands={
                Seat.EAST: east_hand,
                Seat.SOUTH: INERT_HAND,
                Seat.WEST: INERT_HAND,
                Seat.NORTH: INERT_HAND,
            },
            draws=("9s", "5z", "6z", "9m"),
            live_wall_size=56,
        )
        for _ in range(3):
            play_quiet_turn(state)
        draw_and_discard(state, Seat.NORTH)
        self.assertIs(state.phase, RoundPhase.AWAITING_REACTIONS)
        resolve_with(state, {Seat.EAST: ron_action(state, Seat.EAST)})

        self.assertIs(state.phase, RoundPhase.AWAITING_WIN_FINALIZATION)
        result = state.finalize_pending_win(expected_revision=state.revision)

        self.assertIsInstance(result, WinResult)
        self.assertTrue(result.is_last_tile)


class NagashiManganTest(unittest.TestCase):
    def _play_to_exhaustion(
        self, hands: dict[Seat, tuple[str, ...]], draws
    ) -> RoundState:
        state = dealt_state(hands=hands, draws=draws, live_wall_size=56)
        for _ in range(3):
            play_quiet_turn(state)
        draw_and_discard(state, Seat.NORTH)
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)
        return state

    def test_all_terminal_or_honor_uncalled_river_is_nagashi(self) -> None:
        state = self._play_to_exhaustion(
            {seat: INERT_HAND for seat in Seat},
            draws=("9m", "9p", "9s", "5z"),
        )

        self.assertEqual(
            set(state.result.nagashi_mangan_seats),
            {Seat.EAST, Seat.SOUTH, Seat.WEST, Seat.NORTH},
        )

    def test_simple_tile_discard_disqualifies(self) -> None:
        state = self._play_to_exhaustion(
            {seat: INERT_HAND for seat in Seat},
            draws=("5m", "9p", "9s", "5z"),
        )

        self.assertNotIn(Seat.EAST, state.result.nagashi_mangan_seats)
        self.assertIn(Seat.SOUTH, state.result.nagashi_mangan_seats)

    def test_disabled_rule_yields_no_nagashi_seats(self) -> None:
        rules = replace(RuleSet.default(), nagashi_mangan_enabled=False)
        state = dealt_state(
            hands={seat: INERT_HAND for seat in Seat},
            draws=("9m", "9p", "9s", "5z"),
            live_wall_size=56,
            rules=rules,
        )
        for _ in range(3):
            play_quiet_turn(state)
        draw_and_discard(state, Seat.NORTH)
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)

        self.assertEqual(state.result.nagashi_mangan_seats, ())

    def test_called_discard_disqualifies_that_seat(self) -> None:
        """EASTの捨て牌がSOUTHにポンされる、実際に構成できる局面で確認する。

        EASTは自分の第一打が鳴かれるため、この局ではそれ以上打牌の機会を
        得ない。SOUTH/WEST/NORTHは通常どおり進行し、EASTだけがpending
        callによってnagashi mangan成立から除外されることを確認する。
        """
        hands = {
            Seat.EAST: (
                "9m",
                "4m",
                "7m",
                "1p",
                "4p",
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
                "9m",
                "9m",
                "1p",
                "2p",
                "5p",
                "8p",
                "2s",
                "3s",
                "5s",
                "8s",
                "6m",
                "7m",
                "8m",
            ),
            Seat.WEST: INERT_HAND,
            Seat.NORTH: INERT_HAND,
        }
        state = dealt_state(hands=hands, draws=("6z", "9s", "1z"), live_wall_size=55)
        draw_and_discard(state, Seat.EAST, "9m")
        self.assertIs(state.phase, RoundPhase.AWAITING_REACTIONS)
        resolve_with(state, {Seat.SOUTH: pon_action(state, Seat.SOUTH)})
        self.assertIs(state.discards(Seat.EAST)[0].called_by, Seat.SOUTH)
        discard(state, Seat.SOUTH, "1p")
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)
        self.assertIs(state.current_seat, Seat.WEST)
        draw_and_discard(state, Seat.WEST, "9s")
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)
        self.assertIs(state.current_seat, Seat.NORTH)
        draw_and_discard(state, Seat.NORTH, "1z")
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)
        self.assertEqual(state.remaining_count, 0)

        self.assertIsInstance(state.result, ExhaustiveDrawResult)
        self.assertNotIn(Seat.EAST, state.result.nagashi_mangan_seats)
        self.assertIn(Seat.SOUTH, state.result.nagashi_mangan_seats)
        self.assertIn(Seat.WEST, state.result.nagashi_mangan_seats)
        self.assertIn(Seat.NORTH, state.result.nagashi_mangan_seats)


class TerminalInvariantForDrawTest(unittest.TestCase):
    def test_abortive_terminal_commit_matches_event_and_blocks_restart(self) -> None:
        state = dealt_state(
            hands=_hands_with(Seat.EAST, _NINE_TERMINALS_HAND),
            draws=("2m",),
        )
        state.draw(Seat.EAST)
        snapshot = state.legal_actions(Seat.EAST)
        state.apply(
            Seat.EAST,
            NineTerminalsLegalAction(),
            expected_revision=snapshot.revision,
        )
        result = state.result

        self.assertIs(state.phase, RoundPhase.FINISHED)
        terminal_events = tuple(
            event for event in state.events if isinstance(event, RoundEndedEvent)
        )
        self.assertEqual(len(terminal_events), 1)
        self.assertIs(terminal_events[0].result, result)
        self.assertIs(state.events[-1], terminal_events[0])
        self.assertIsNone(state.current_seat)
        for seat in Seat:
            self.assertEqual(state.legal_actions(seat).actions, ())

        with self.assertRaises(IllegalOperationError):
            state.draw(Seat.SOUTH)
        with self.assertRaises(IllegalOperationError):
            state.resolve_reactions({}, expected_revision=state.revision)

    def test_exhaustive_terminal_commit_matches_event_and_blocks_restart(self) -> None:
        state = dealt_state(
            hands={seat: INERT_HAND for seat in Seat},
            draws=("5z", "6z", "7z", "9m"),
            live_wall_size=56,
        )
        for _ in range(3):
            play_quiet_turn(state)
        draw_and_discard(state, Seat.NORTH)
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)
        result = state.result

        self.assertIsInstance(result, ExhaustiveDrawResult)
        self.assertIs(state.phase, RoundPhase.FINISHED)
        terminal_events = tuple(
            event for event in state.events if isinstance(event, RoundEndedEvent)
        )
        self.assertEqual(len(terminal_events), 1)
        self.assertIs(terminal_events[0].result, result)
        self.assertIs(state.events[-1], terminal_events[0])
        for seat in Seat:
            self.assertEqual(state.legal_actions(seat).actions, ())
        with self.assertRaises(IllegalOperationError):
            state.apply(
                Seat.EAST,
                NineTerminalsLegalAction(),
                expected_revision=state.revision,
            )


if __name__ == "__main__":
    unittest.main()
