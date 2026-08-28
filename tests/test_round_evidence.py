"""ordered player-safe round evidence projectionのtargeted contract test。

population self-playを増やさず、deterministicなengineered stateだけで、
公開してよい事実の順序と、hidden情報が漏れないことを固定する。
"""

import unittest
from dataclasses import replace

from _round_fixtures import (
    INERT_HAND,
    QUIET_HANDS,
    action_of_type,
    chi_action,
    daiminkan_action,
    dealt_state,
    discard,
    discard_drawn_tile,
    draw_and_discard,
    play_quiet_turn,
    pon_action,
    resolve_all_pass,
    resolve_with,
    ron_action,
    tiles,
)

from lisjong_engine.discard import Discard
from lisjong_engine.legal_action import (
    AnkanLegalAction,
    KakanLegalAction,
    RonLegalAction,
)
from lisjong_engine.public_state import PublicMeldType, PublicTile, public_tile
from lisjong_engine.reaction import ReactionType
from lisjong_engine.riichi_event import (
    RiichiDeclaration,
    RiichiDeclarationFinalization,
    RiichiDeclarationOutcome,
)
from lisjong_engine.round_event import (
    DrawSource,
    MissedRonRecordedEvent,
    ReactionsResolvedEvent,
    RiichiFinalizedEvent,
    TileDrawnEvent,
    TilesDealtEvent,
)
from lisjong_engine.round_evidence import (
    DiscardEvidence,
    DoraIndicatorRevealedEvidence,
    DrawEvidence,
    KanConfirmedEvidence,
    KanDeclaredEvidence,
    MeldCalledEvidence,
    ResponseEpochClosedEvidence,
    ResponseEpochOpenedEvidence,
    ResponseOutcome,
    ResponseTrigger,
    RiichiDeclaredEvidence,
    RiichiEstablishedEvidence,
    RiichiFailedEvidence,
    RoundEndedEvidence,
    RoundEndKind,
    RoundStartedEvidence,
    project_round_evidence,
)
from lisjong_engine.round_evidence_builder import build_round_evidence
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.rules import KanDoraRevealPolicy, RuleSet
from lisjong_engine.seat import Seat
from lisjong_engine.tile import TileCategory, TileType
from lisjong_engine.win_context import WinMethod

_SEATS = tuple(Seat)
_KOKUSHI_CHANKAN_RULES = replace(
    RuleSet.default(),
    kokushi_ankan_chankan_enabled=True,
)
_IMMEDIATE_KAN_DORA_RULES = replace(
    RuleSet.default(),
    kan_dora_reveal_policy=KanDoraRevealPolicy.IMMEDIATE_ON_KAN_CONFIRMATION,
)

# EASTが5zをツモ切りするだけの、誰も反応できない局面。
_SILENT_DRAWS = ("5z", "6z", "6z", "6z")
# 同じ公開打牌に対し、SOUTHだけがポンの必要条件を満たす隠れ手牌。
_PON_CAPABLE_SOUTH_HAND = (
    "2m",
    "5m",
    "8m",
    "2p",
    "5p",
    "8p",
    "2s",
    "5s",
    "8s",
    "5z",
    "5z",
    "3z",
    "4z",
)

# EASTが3pを手出しし、SOUTHがチーできる局面。
_CHI_HANDS = {
    Seat.EAST: (
        "1m",
        "4m",
        "7m",
        "3p",
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
        "1m",
        "4m",
        "7m",
        "1p",
        "4p",
        "5p",
        "1s",
        "4s",
        "7s",
        "1z",
        "2z",
        "3z",
        "4z",
    ),
    Seat.WEST: INERT_HAND,
    Seat.NORTH: INERT_HAND,
}
# 同じ3pへ、WESTがポンできる局面。
_PON_HANDS = {
    **_CHI_HANDS,
    Seat.SOUTH: INERT_HAND,
    Seat.WEST: (
        "1m",
        "4m",
        "7m",
        "3p",
        "3p",
        "7p",
        "1s",
        "4s",
        "7s",
        "1z",
        "2z",
        "3z",
        "4z",
    ),
}
# 同じ3pへ、NORTHが大明槓できる局面。
_DAIMINKAN_HANDS = {
    **_CHI_HANDS,
    Seat.SOUTH: INERT_HAND,
    Seat.NORTH: (
        "1m",
        "4m",
        "7m",
        "3p",
        "3p",
        "3p",
        "1s",
        "4s",
        "7s",
        "1z",
        "2z",
        "3z",
        "4z",
    ),
}
_CALL_DRAWS = ("5z", "6z", "5z", "6z", "5z", "6z")

# SOUTHが3pをポンし、4枚目で加槓する局面。WESTは4pをツモった時点で
# 3p/6p待ちになり、加槓へ槍槓できる。
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
    Seat.NORTH: (
        "1m",
        "4m",
        "7m",
        "9m",
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
}
# 公開進行は同じまま、WESTだけが槍槓できない隠れ手牌。
_KAKAN_HANDS_WITHOUT_CANDIDATE = {
    **_KAKAN_HANDS,
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
        "1z",
        "2s",
        "2s",
        "9s",
    ),
}
_KAKAN_DRAWS = ("5z", "4p", "6z", "5z", "3p")

# EASTが1mを暗槓し、NORTHが1m単騎の国士無双で待つ局面。
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
# 公開情報は同じまま、NORTHだけが暗槓へ槍槓できない隠れ手牌。
_ANKAN_HANDS_WITHOUT_CANDIDATE = {
    **_ANKAN_HANDS,
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
        "6z",
    ),
}
_ANKAN_DRAWS = ("8s",)

# EASTだけが門前聴牌で立直でき、SOUTHが宣言牌をポンできる局面。
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
    Seat.SOUTH: (
        "1m",
        "4m",
        "7m",
        "1p",
        "4p",
        "7p",
        "1s",
        "4s",
        "7s",
        "5z",
        "5z",
        "3z",
        "4z",
    ),
    Seat.WEST: INERT_HAND,
    Seat.NORTH: INERT_HAND,
}
_RIICHI_DRAWS = ("5z", "6z", "6z", "6z")


def _public_tile(name: str) -> PublicTile:
    tile = tiles(name)[0]
    return PublicTile(tile.tile_type, tile.is_red)


def _evidence(state, viewer_seat: Seat = Seat.WEST) -> tuple:
    return build_round_evidence(state, viewer_seat)


def _all_viewer_evidence(state) -> dict:
    return {seat: build_round_evidence(state, seat) for seat in _SEATS}


def _silent_discard_state(**kwargs):
    """誰もEASTの打牌へ反応できない局面で、EASTが5zをツモ切りした状態。"""
    state = dealt_state(
        hands=QUIET_HANDS,
        draws=_SILENT_DRAWS,
        with_dead_wall=True,
        **kwargs,
    )
    draw_and_discard(state, Seat.EAST)
    return state


def _pon_capable_discard_state(**kwargs):
    """同じ公開打牌に対し、SOUTHだけがポン候補を持つ状態。"""
    state = dealt_state(
        hands={**QUIET_HANDS, Seat.SOUTH: _PON_CAPABLE_SOUTH_HAND},
        draws=_SILENT_DRAWS,
        with_dead_wall=True,
        **kwargs,
    )
    draw_and_discard(state, Seat.EAST)
    return state


def _call_state(hands, **kwargs):
    """EASTが3pを手出しし、反応windowが開いた状態。"""
    state = dealt_state(
        hands=hands,
        draws=_CALL_DRAWS,
        with_dead_wall=True,
        **kwargs,
    )
    draw_and_discard(state, Seat.EAST, "3p")
    return state


def _kakan_declared_state(hands=None, **kwargs):
    """SOUTHが3pをポンし、4枚目で加槓を宣言した状態。"""
    state = dealt_state(
        hands=_KAKAN_HANDS if hands is None else hands,
        draws=_KAKAN_DRAWS,
        with_dead_wall=True,
        **kwargs,
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


def _ankan_declared_state(hands=None, **kwargs):
    """EASTがツモ後に1mを暗槓宣言した状態。"""
    state = dealt_state(
        hands=_ANKAN_HANDS if hands is None else hands,
        draws=_ANKAN_DRAWS,
        with_dead_wall=True,
        **kwargs,
    )
    state.draw(Seat.EAST)
    snapshot = state.legal_actions(Seat.EAST)
    state.apply(
        Seat.EAST,
        action_of_type(state, Seat.EAST, AnkanLegalAction),
        expected_revision=snapshot.revision,
    )
    return state


def _riichi_declared_state(**kwargs):
    """EASTが5zを宣言牌として立直を宣言した状態。"""
    state = dealt_state(
        hands=_RIICHI_HANDS,
        draws=_RIICHI_DRAWS,
        with_dead_wall=True,
        **kwargs,
    )
    draw_and_discard(state, Seat.EAST, "5z", declares_riichi=True)
    return state


def _has_event(state, event_type) -> bool:
    return any(isinstance(event, event_type) for event in state.events)


def _public_round_state(state) -> tuple:
    """evidence contractの外側にあるpublic盤面。fixture差がhiddenだけであること
    を確かめるために使う。"""
    return (
        tuple(public_tile(tile) for tile in state.revealed_dora_indicators),
        state.remaining_count,
        tuple(
            tuple(
                (public_tile(entry.tile), entry.is_tsumogiri, entry.called_by)
                for entry in state.discards(seat)
            )
            for seat in _SEATS
        ),
        tuple(tuple(state.melds(seat)) for seat in _SEATS),
        tuple(state.riichi_status(seat) for seat in _SEATS),
    )


def _can_ron(state, seat: Seat) -> bool:
    return any(
        isinstance(action, RonLegalAction)
        for action in state.legal_actions(seat).actions
    )


class SamePublicDifferentHiddenDiscardTest(unittest.TestCase):
    """本Issueの中心regression。

    公開された打牌が同じなら、hidden handによってengineのreaction window
    が開いたかどうかが変わっても、player-safe evidenceは同一になる。
    """

    def test_runtime_reaction_activation_actually_differs(self) -> None:
        silent = _silent_discard_state()
        pon_capable = _pon_capable_discard_state()

        self.assertIs(silent.phase, RoundPhase.AWAITING_DRAW)
        self.assertIs(pon_capable.phase, RoundPhase.AWAITING_REACTIONS)

    def test_the_two_fixtures_differ_only_in_hidden_hands(self) -> None:
        silent = _silent_discard_state()
        pon_capable = _pon_capable_discard_state()

        self.assertEqual(_public_round_state(silent), _public_round_state(pon_capable))
        self.assertNotEqual(
            silent.hand_tiles(Seat.SOUTH),
            pon_capable.hand_tiles(Seat.SOUTH),
        )

    def test_structural_evidence_is_identical_before_any_resolution(self) -> None:
        silent = _silent_discard_state()
        pon_capable = _pon_capable_discard_state()

        for seat in _SEATS:
            with self.subTest(viewer=seat):
                self.assertEqual(
                    build_round_evidence(silent, seat),
                    build_round_evidence(pon_capable, seat),
                )

    def test_structural_evidence_is_identical_after_the_same_progression(self) -> None:
        silent = _silent_discard_state()
        pon_capable = _pon_capable_discard_state()
        resolve_all_pass(pon_capable)
        self.assertTrue(_has_event(pon_capable, ReactionsResolvedEvent))
        self.assertFalse(_has_event(silent, ReactionsResolvedEvent))

        silent.draw(Seat.SOUTH)
        pon_capable.draw(Seat.SOUTH)

        self.assertEqual(
            _all_viewer_evidence(silent), _all_viewer_evidence(pon_capable)
        )

    def test_the_discard_opens_a_full_responder_topology(self) -> None:
        silent = _silent_discard_state()
        silent.draw(Seat.SOUTH)

        evidence = _evidence(silent)

        self.assertEqual(
            evidence,
            (
                RoundStartedEvidence(Seat.EAST, silent.prevailing_wind),
                DrawEvidence(Seat.EAST, DrawSource.LIVE_WALL),
                DiscardEvidence(
                    seat=Seat.EAST,
                    tile=_public_tile("5z"),
                    is_tsumogiri=True,
                    order=0,
                    is_riichi_declaration=False,
                ),
                ResponseEpochOpenedEvidence(
                    trigger=ResponseTrigger.DISCARD,
                    source_seat=Seat.EAST,
                    responder_seats=(Seat.SOUTH, Seat.WEST, Seat.NORTH),
                ),
                ResponseEpochClosedEvidence(
                    trigger=ResponseTrigger.DISCARD,
                    source_seat=Seat.EAST,
                    outcome=ResponseOutcome.NO_PUBLIC_RESPONSE,
                ),
                DrawEvidence(Seat.SOUTH, DrawSource.LIVE_WALL),
            ),
        )


class CallEvidenceTest(unittest.TestCase):
    """チー・ポン・大明槓のordered public evidenceを固定する。"""

    def _called_meld_evidence(self, state) -> MeldCalledEvidence:
        called = [
            evidence
            for evidence in _evidence(state, Seat.EAST)
            if isinstance(evidence, MeldCalledEvidence)
        ]
        self.assertEqual(len(called), 1)
        return called[0]

    def test_chi_is_ordered_after_the_response_epoch(self) -> None:
        state = _call_state(_CHI_HANDS)

        resolve_with(state, {Seat.SOUTH: chi_action(state, Seat.SOUTH)})

        evidence = _evidence(state, Seat.EAST)
        self.assertEqual(
            evidence[2:],
            (
                DiscardEvidence(
                    seat=Seat.EAST,
                    tile=_public_tile("3p"),
                    is_tsumogiri=False,
                    order=0,
                    is_riichi_declaration=False,
                ),
                ResponseEpochOpenedEvidence(
                    trigger=ResponseTrigger.DISCARD,
                    source_seat=Seat.EAST,
                    responder_seats=(Seat.SOUTH, Seat.WEST, Seat.NORTH),
                ),
                ResponseEpochClosedEvidence(
                    trigger=ResponseTrigger.DISCARD,
                    source_seat=Seat.EAST,
                    outcome=ResponseOutcome.CALL,
                ),
                self._called_meld_evidence(state),
            ),
        )

    def test_chi_keeps_the_public_meld_and_called_discard(self) -> None:
        state = _call_state(_CHI_HANDS)

        resolve_with(state, {Seat.SOUTH: chi_action(state, Seat.SOUTH)})

        called = self._called_meld_evidence(state)
        self.assertIs(called.seat, Seat.SOUTH)
        self.assertIs(called.meld.meld_type, PublicMeldType.CHI)
        self.assertIs(called.meld.from_seat, Seat.EAST)
        self.assertEqual(called.meld.called_tile, _public_tile("3p"))
        self.assertEqual(called.called_discard_order, 0)

    def test_pon_keeps_the_public_meld_and_called_discard(self) -> None:
        state = _call_state(_PON_HANDS)

        resolve_with(state, {Seat.WEST: pon_action(state, Seat.WEST)})

        called = self._called_meld_evidence(state)
        self.assertIs(called.seat, Seat.WEST)
        self.assertIs(called.meld.meld_type, PublicMeldType.PON)
        self.assertIs(called.meld.from_seat, Seat.EAST)
        self.assertEqual(called.called_discard_order, 0)

    def test_daiminkan_keeps_the_public_meld_and_leads_to_a_rinshan_draw(self) -> None:
        state = _call_state(_DAIMINKAN_HANDS)

        resolve_with(state, {Seat.NORTH: daiminkan_action(state, Seat.NORTH)})
        state.draw_rinshan(Seat.NORTH)

        called = self._called_meld_evidence(state)
        self.assertIs(called.meld.meld_type, PublicMeldType.DAIMINKAN)
        self.assertIs(called.seat, Seat.NORTH)
        self.assertEqual(
            _evidence(state, Seat.EAST)[-1],
            DrawEvidence(Seat.NORTH, DrawSource.RINSHAN),
        )


class KakanEvidenceTest(unittest.TestCase):
    def _kakan_tail(self, state) -> tuple:
        evidence = _evidence(state, Seat.EAST)
        start = next(
            index
            for index, value in enumerate(evidence)
            if isinstance(value, KanDeclaredEvidence)
        )
        return evidence[start:]

    def test_a_kakan_declaration_opens_a_structural_chankan_epoch(self) -> None:
        state = _kakan_declared_state()

        tail = self._kakan_tail(state)

        self.assertIsInstance(tail[0], KanDeclaredEvidence)
        self.assertIs(tail[0].meld.meld_type, PublicMeldType.KAKAN)
        self.assertEqual(
            tail[1],
            ResponseEpochOpenedEvidence(
                trigger=ResponseTrigger.KAKAN,
                source_seat=Seat.SOUTH,
                responder_seats=(Seat.WEST, Seat.NORTH, Seat.EAST),
            ),
        )

    def test_a_structural_chankan_epoch_ignores_hidden_ron_candidates(self) -> None:
        with_candidate = _kakan_declared_state()
        without_candidate = _kakan_declared_state(_KAKAN_HANDS_WITHOUT_CANDIDATE)

        self.assertTrue(_can_ron(with_candidate, Seat.WEST))
        self.assertFalse(_can_ron(without_candidate, Seat.WEST))
        self.assertEqual(
            _public_round_state(with_candidate),
            _public_round_state(without_candidate),
        )
        for seat in _SEATS:
            with self.subTest(viewer=seat):
                self.assertEqual(
                    build_round_evidence(with_candidate, seat),
                    build_round_evidence(without_candidate, seat),
                )

    def test_no_public_response_confirms_the_kakan_and_reveals_kan_dora(self) -> None:
        state = _kakan_declared_state()

        resolve_all_pass(state)

        tail = self._kakan_tail(state)
        self.assertEqual(
            tail[2],
            ResponseEpochClosedEvidence(
                trigger=ResponseTrigger.KAKAN,
                source_seat=Seat.SOUTH,
                outcome=ResponseOutcome.NO_PUBLIC_RESPONSE,
            ),
        )
        self.assertIsInstance(tail[3], KanConfirmedEvidence)
        self.assertIs(tail[3].meld.meld_type, PublicMeldType.KAKAN)
        self.assertIsInstance(tail[4], DoraIndicatorRevealedEvidence)
        self.assertEqual(len(tail), 5)

    def test_a_chankan_ron_closes_the_epoch_without_a_confirmation(self) -> None:
        state = _kakan_declared_state()

        resolve_with(state, {Seat.WEST: ron_action(state, Seat.WEST)})
        state.finalize_pending_win(expected_revision=state.revision)

        tail = self._kakan_tail(state)
        self.assertEqual(
            tail[2],
            ResponseEpochClosedEvidence(
                trigger=ResponseTrigger.KAKAN,
                source_seat=Seat.SOUTH,
                outcome=ResponseOutcome.RON,
            ),
        )
        self.assertEqual(
            tail[3],
            RoundEndedEvidence(
                kind=RoundEndKind.WIN,
                win_method=WinMethod.RON,
                winner_seats=(Seat.WEST,),
                source_seat=Seat.SOUTH,
            ),
        )
        self.assertEqual(len(tail), 4)


class AnkanEvidenceTest(unittest.TestCase):
    def _ankan_tail(self, state) -> tuple:
        evidence = _evidence(state, Seat.SOUTH)
        start = next(
            index
            for index, value in enumerate(evidence)
            if isinstance(value, KanDeclaredEvidence)
        )
        return evidence[start:]

    def test_a_disabled_rule_has_no_structural_response_epoch(self) -> None:
        state = _ankan_declared_state()

        tail = self._ankan_tail(state)

        self.assertIsInstance(tail[0], KanDeclaredEvidence)
        self.assertIs(tail[0].meld.meld_type, PublicMeldType.ANKAN)
        self.assertIsInstance(tail[1], KanConfirmedEvidence)
        self.assertIsInstance(tail[2], DoraIndicatorRevealedEvidence)
        self.assertEqual(len(tail), 3)

    def test_runtime_ankan_reaction_activation_depends_on_hidden_hands(self) -> None:
        with_candidate = _ankan_declared_state(rules=_KOKUSHI_CHANKAN_RULES)
        without_candidate = _ankan_declared_state(
            _ANKAN_HANDS_WITHOUT_CANDIDATE,
            rules=_KOKUSHI_CHANKAN_RULES,
        )

        self.assertIs(with_candidate.phase, RoundPhase.AWAITING_ANKAN_REACTIONS)
        self.assertTrue(_can_ron(with_candidate, Seat.NORTH))
        self.assertIs(without_candidate.phase, RoundPhase.AWAITING_RINSHAN_DRAW)
        self.assertEqual(
            tuple(
                public_tile(tile) for tile in with_candidate.revealed_dora_indicators
            )[:1],
            tuple(
                public_tile(tile) for tile in without_candidate.revealed_dora_indicators
            )[:1],
        )

    def test_an_enabled_rule_opens_the_same_epoch_without_a_candidate(self) -> None:
        with_candidate = _ankan_declared_state(rules=_KOKUSHI_CHANKAN_RULES)
        without_candidate = _ankan_declared_state(
            _ANKAN_HANDS_WITHOUT_CANDIDATE,
            rules=_KOKUSHI_CHANKAN_RULES,
        )

        expected_epoch = ResponseEpochOpenedEvidence(
            trigger=ResponseTrigger.ANKAN,
            source_seat=Seat.EAST,
            responder_seats=(Seat.SOUTH, Seat.WEST, Seat.NORTH),
        )
        self.assertEqual(self._ankan_tail(with_candidate)[1], expected_epoch)
        self.assertEqual(self._ankan_tail(without_candidate)[1], expected_epoch)

    def test_the_same_public_progression_yields_the_same_evidence(self) -> None:
        with_candidate = _ankan_declared_state(rules=_KOKUSHI_CHANKAN_RULES)
        without_candidate = _ankan_declared_state(
            _ANKAN_HANDS_WITHOUT_CANDIDATE,
            rules=_KOKUSHI_CHANKAN_RULES,
        )
        resolve_all_pass(with_candidate)

        for seat in _SEATS:
            with self.subTest(viewer=seat):
                self.assertEqual(
                    build_round_evidence(with_candidate, seat),
                    build_round_evidence(without_candidate, seat),
                )

    def test_an_ankan_chankan_ron_closes_the_epoch_without_a_confirmation(self) -> None:
        state = _ankan_declared_state(rules=_KOKUSHI_CHANKAN_RULES)

        resolve_with(state, {Seat.NORTH: ron_action(state, Seat.NORTH)})
        state.finalize_pending_win(expected_revision=state.revision)

        tail = self._ankan_tail(state)
        self.assertEqual(
            tail[1:],
            (
                ResponseEpochOpenedEvidence(
                    trigger=ResponseTrigger.ANKAN,
                    source_seat=Seat.EAST,
                    responder_seats=(Seat.SOUTH, Seat.WEST, Seat.NORTH),
                ),
                ResponseEpochClosedEvidence(
                    trigger=ResponseTrigger.ANKAN,
                    source_seat=Seat.EAST,
                    outcome=ResponseOutcome.RON,
                ),
                RoundEndedEvidence(
                    kind=RoundEndKind.WIN,
                    win_method=WinMethod.RON,
                    winner_seats=(Seat.NORTH,),
                    source_seat=Seat.EAST,
                ),
            ),
        )


class RiichiEvidenceTest(unittest.TestCase):
    def test_the_declaration_discard_identity_is_preserved(self) -> None:
        state = _riichi_declared_state()

        evidence = _evidence(state, Seat.NORTH)

        self.assertEqual(
            evidence[2:],
            (
                DiscardEvidence(
                    seat=Seat.EAST,
                    tile=_public_tile("5z"),
                    is_tsumogiri=True,
                    order=0,
                    is_riichi_declaration=True,
                ),
                RiichiDeclaredEvidence(Seat.EAST, _public_tile("5z"), 0),
                ResponseEpochOpenedEvidence(
                    trigger=ResponseTrigger.DISCARD,
                    source_seat=Seat.EAST,
                    responder_seats=(Seat.SOUTH, Seat.WEST, Seat.NORTH),
                ),
            ),
        )

    def test_finalization_waits_for_the_public_response_outcome(self) -> None:
        state = _riichi_declared_state()
        resolve_all_pass(state)

        # 立直の成立はresponse epochの解決を意味するため、その解決が
        # publicな進行として現れるまで公開しない。
        self.assertNotIn(
            RiichiEstablishedEvidence(Seat.EAST),
            _evidence(state, Seat.NORTH),
        )

        state.draw(Seat.SOUTH)

        self.assertEqual(
            _evidence(state, Seat.NORTH)[5:],
            (
                ResponseEpochClosedEvidence(
                    trigger=ResponseTrigger.DISCARD,
                    source_seat=Seat.EAST,
                    outcome=ResponseOutcome.NO_PUBLIC_RESPONSE,
                ),
                RiichiEstablishedEvidence(Seat.EAST),
                DrawEvidence(Seat.SOUTH, DrawSource.LIVE_WALL),
            ),
        )

    def test_a_called_declaration_discard_still_establishes_riichi(self) -> None:
        state = _riichi_declared_state()

        resolve_with(state, {Seat.SOUTH: pon_action(state, Seat.SOUTH)})

        evidence = _evidence(state, Seat.NORTH)
        self.assertEqual(
            evidence[5],
            ResponseEpochClosedEvidence(
                trigger=ResponseTrigger.DISCARD,
                source_seat=Seat.EAST,
                outcome=ResponseOutcome.CALL,
            ),
        )
        self.assertIsInstance(evidence[6], MeldCalledEvidence)
        self.assertEqual(evidence[7], RiichiEstablishedEvidence(Seat.EAST))


class KanDoraOrderingTest(unittest.TestCase):
    """槓ドラ公開の順序が`RuleSet.kan_dora_reveal_policy`に従う。"""

    def _dora_indices(self, evidence: tuple) -> tuple[int, ...]:
        return tuple(
            index
            for index, value in enumerate(evidence)
            if isinstance(value, DoraIndicatorRevealedEvidence)
        )

    def test_an_immediate_policy_reveals_kan_dora_with_the_daiminkan(self) -> None:
        state = _call_state(_DAIMINKAN_HANDS, rules=_IMMEDIATE_KAN_DORA_RULES)

        resolve_with(state, {Seat.NORTH: daiminkan_action(state, Seat.NORTH)})

        evidence = _evidence(state, Seat.EAST)
        self.assertIsInstance(evidence[-2], MeldCalledEvidence)
        self.assertIsInstance(evidence[-1], DoraIndicatorRevealedEvidence)

    def test_a_delayed_policy_reveals_kan_dora_after_the_next_discard(self) -> None:
        state = _call_state(_DAIMINKAN_HANDS)

        resolve_with(state, {Seat.NORTH: daiminkan_action(state, Seat.NORTH)})
        state.draw_rinshan(Seat.NORTH)
        self.assertEqual(self._dora_indices(_evidence(state, Seat.EAST)), ())

        discard_drawn_tile(state, Seat.NORTH)
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)
        state.draw(Seat.EAST)

        evidence = _evidence(state, Seat.EAST)
        dora_index = self._dora_indices(evidence)
        self.assertEqual(len(dora_index), 1)
        self.assertIsInstance(
            evidence[dora_index[0] - 1],
            ResponseEpochClosedEvidence,
        )
        self.assertIs(evidence[dora_index[0]].seat, Seat.NORTH)


class ViewerPrivateDrawTest(unittest.TestCase):
    def test_only_the_drawing_viewer_sees_the_drawn_tile(self) -> None:
        state = _call_state(_CHI_HANDS)

        own = _evidence(state, Seat.EAST)[1]
        other = _evidence(state, Seat.SOUTH)[1]

        self.assertEqual(
            own, DrawEvidence(Seat.EAST, DrawSource.LIVE_WALL, _public_tile("5z"))
        )
        self.assertEqual(other, DrawEvidence(Seat.EAST, DrawSource.LIVE_WALL))

    def test_a_hidden_drawn_tile_never_appears_for_another_viewer(self) -> None:
        state = _call_state(_CHI_HANDS)
        drawn = _public_tile("5z")

        evidence = _evidence(state, Seat.SOUTH)

        self.assertNotIn(
            drawn,
            tuple(getattr(value, "tile", None) for value in evidence),
        )


class ProjectionContractTest(unittest.TestCase):
    """pure projectionの入力validationとwhitelist境界。"""

    def test_omniscient_events_are_never_projected(self) -> None:
        state = _pon_capable_discard_state()
        resolve_all_pass(state)
        omniscient = tuple(
            event
            for event in state.events
            if isinstance(
                event,
                (TilesDealtEvent, ReactionsResolvedEvent, MissedRonRecordedEvent),
            )
        )
        self.assertTrue(omniscient)

        self.assertEqual(
            project_round_evidence(
                omniscient,
                viewer_seat=Seat.EAST,
                rules=RuleSet.default(),
            ),
            (),
        )

    def test_a_failed_riichi_is_projected_after_the_epoch_closes(self) -> None:
        declaration = RiichiDeclaration(
            seat=Seat.EAST,
            discard=Discard(tiles("5z")[0], is_tsumogiri=True),
            discard_count=1,
            remaining_live_tiles=60,
            was_first_discard=True,
            had_prior_call=False,
        )
        finalization = RiichiDeclarationFinalization(
            declaration,
            ReactionType.RON,
            RiichiDeclarationOutcome.FAILED_BY_RON,
        )

        evidence = project_round_evidence(
            (RiichiFinalizedEvent(finalization),),
            viewer_seat=Seat.SOUTH,
            rules=RuleSet.default(),
        )

        self.assertEqual(evidence, (RiichiFailedEvidence(Seat.EAST),))

    def test_rejects_invalid_inputs(self) -> None:
        with self.assertRaises(TypeError):
            project_round_evidence((), viewer_seat="east", rules=RuleSet.default())
        with self.assertRaises(TypeError):
            project_round_evidence((), viewer_seat=Seat.EAST, rules=None)
        with self.assertRaises(TypeError):
            project_round_evidence(
                ("not an event",),
                viewer_seat=Seat.EAST,
                rules=RuleSet.default(),
            )
        with self.assertRaises(TypeError):
            build_round_evidence("not a round state", Seat.EAST)

    def test_an_unknown_draw_keeps_the_viewer_boundary(self) -> None:
        drawn = TileDrawnEvent(
            Seat.WEST,
            tiles("3s")[0],
            DrawSource.RINSHAN,
        )

        self.assertEqual(
            project_round_evidence(
                (drawn,),
                viewer_seat=Seat.WEST,
                rules=RuleSet.default(),
            ),
            (
                DrawEvidence(
                    Seat.WEST,
                    DrawSource.RINSHAN,
                    PublicTile(TileType(TileCategory.SOUZU, 3)),
                ),
            ),
        )
        self.assertEqual(
            project_round_evidence(
                (drawn,),
                viewer_seat=Seat.EAST,
                rules=RuleSet.default(),
            ),
            (DrawEvidence(Seat.WEST, DrawSource.RINSHAN),),
        )


if __name__ == "__main__":
    unittest.main()
