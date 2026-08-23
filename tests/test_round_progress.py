import unittest

from _round_fixtures import (
    INERT_HAND,
    action_of_type,
    dealt_state,
    discard,
    draw_and_discard,
    play_quiet_turn,
    pon_action,
    resolve_with,
    ron_action,
)

from lisjong_engine.legal_action import (
    AnkanLegalAction,
    ChiLegalAction,
    DaiminkanLegalAction,
    KakanLegalAction,
    PonLegalAction,
)
from lisjong_engine.public_state import PublicMeldType
from lisjong_engine.round_progress import (
    DiscardProgress,
    DoraIndicatorRevealedProgress,
    KanConfirmedProgress,
    KanDeclaredProgress,
    MeldCalledProgress,
    RiichiDeclaredProgress,
    RiichiEstablishedProgress,
    RiichiFailedProgress,
    RoundProgressFact,
    project_round_progress,
)
from lisjong_engine.round_state import RoundState
from lisjong_engine.seat import Seat

# チー・ポン・大明槓のどれもが成立し得る、決定的な既存fixture相当の配牌。
# EASTが"7p"を打ち、SOUTHはチー（5p+6p）、NORTHはポン／大明槓
# （7p,7p,7pのうち2枚または3枚）のどちらも選べる。
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

# EASTが立直可能なtenpai形で"5z"を打ち、WESTがそれをロンできる配牌
# （5z/6zのシャンポン待ちで、5zロンにより白の役牌が成立する）。
_RIICHI_FAIL_HANDS = {
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

# EASTが"5z"を宣言牌としてtenpaiのまま立直宣言できる配牌（誰も反応できない）。
_RIICHI_ESTABLISH_HANDS = {
    Seat.EAST: _RIICHI_FAIL_HANDS[Seat.EAST],
    Seat.SOUTH: INERT_HAND,
    Seat.WEST: INERT_HAND,
    Seat.NORTH: INERT_HAND,
}


class ProjectionUnitTest(unittest.TestCase):
    """internal eventの列から、期待通りのfact種別・順序が構築されることを確認する。"""

    def test_unknown_events_are_dropped(self) -> None:
        self.assertEqual(project_round_progress(("not-an-event",)), ())

    def test_empty_slice_projects_to_empty_batch(self) -> None:
        self.assertEqual(project_round_progress(()), ())


class DiscardProgressTest(unittest.TestCase):
    def test_discard_yields_discard_progress_in_order(self) -> None:
        state = dealt_state(hands=_REACTION_HANDS, draws=("8s",), with_dead_wall=True)
        before = len(state.events)
        draw_and_discard(state, Seat.EAST, "7p")

        facts = project_round_progress(tuple(state.events)[before:])

        self.assertEqual(len(facts), 1)
        self.assertIsInstance(facts[0], DiscardProgress)
        self.assertIs(facts[0].seat, Seat.EAST)
        self.assertFalse(facts[0].is_tsumogiri)


class ChiCallProgressTest(unittest.TestCase):
    def test_chi_call_yields_a_single_meld_called_progress(self) -> None:
        state = dealt_state(hands=_REACTION_HANDS, draws=("8s",), with_dead_wall=True)
        draw_and_discard(state, Seat.EAST, "7p")
        before = len(state.events)

        resolve_with(
            state, {Seat.SOUTH: action_of_type(state, Seat.SOUTH, ChiLegalAction)}
        )

        facts = project_round_progress(tuple(state.events)[before:])

        self.assertEqual(len(facts), 1)
        self.assertIsInstance(facts[0], MeldCalledProgress)
        self.assertIs(facts[0].seat, Seat.SOUTH)
        self.assertIs(facts[0].meld.meld_type, PublicMeldType.CHI)

    def test_chi_then_discard_arrive_both_and_in_order(self) -> None:
        state = dealt_state(hands=_REACTION_HANDS, draws=("8s",), with_dead_wall=True)
        draw_and_discard(state, Seat.EAST, "7p")
        before = len(state.events)

        resolve_with(
            state, {Seat.SOUTH: action_of_type(state, Seat.SOUTH, ChiLegalAction)}
        )
        discard(state, Seat.SOUTH, "1m")

        facts = project_round_progress(tuple(state.events)[before:])

        self.assertEqual(len(facts), 2)
        self.assertIsInstance(facts[0], MeldCalledProgress)
        self.assertIsInstance(facts[1], DiscardProgress)
        self.assertIs(facts[1].seat, Seat.SOUTH)


class PonCallProgressTest(unittest.TestCase):
    def test_pon_call_is_not_lost_and_not_duplicated(self) -> None:
        state = dealt_state(hands=_REACTION_HANDS, draws=("8s",), with_dead_wall=True)
        draw_and_discard(state, Seat.EAST, "7p")
        before = len(state.events)

        resolve_with(
            state, {Seat.NORTH: action_of_type(state, Seat.NORTH, PonLegalAction)}
        )

        facts = project_round_progress(tuple(state.events)[before:])

        self.assertEqual(len(facts), 1)
        self.assertIsInstance(facts[0], MeldCalledProgress)
        self.assertIs(facts[0].seat, Seat.NORTH)
        self.assertIs(facts[0].meld.meld_type, PublicMeldType.PON)


class DaiminkanCallProgressTest(unittest.TestCase):
    def test_daiminkan_call_is_reported_exactly_once(self) -> None:
        state = dealt_state(hands=_REACTION_HANDS, draws=("8s",), with_dead_wall=True)
        draw_and_discard(state, Seat.EAST, "7p")
        before = len(state.events)

        resolve_with(
            state, {Seat.NORTH: action_of_type(state, Seat.NORTH, DaiminkanLegalAction)}
        )

        facts = project_round_progress(tuple(state.events)[before:])

        # 大明槓成立はMeldCalledEventだけをsourceにし、同じtransactionの
        # KanConfirmedEventからは重複してprogress factを生成しない。
        self.assertEqual(len(facts), 1)
        self.assertIsInstance(facts[0], MeldCalledProgress)
        self.assertIs(facts[0].seat, Seat.NORTH)
        self.assertIs(facts[0].meld.meld_type, PublicMeldType.DAIMINKAN)


class KakanProgressTest(unittest.TestCase):
    def _kakan_state(self) -> RoundState:
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

    def test_kakan_declaration_and_confirmation_are_distinct_ordered_facts(
        self,
    ) -> None:
        state = self._kakan_state()
        before = len(state.events)
        snapshot = state.legal_actions(Seat.SOUTH)
        state.apply(
            Seat.SOUTH,
            action_of_type(state, Seat.SOUTH, KakanLegalAction),
            expected_revision=snapshot.revision,
        )

        declaration_facts = project_round_progress(tuple(state.events)[before:])
        self.assertEqual(len(declaration_facts), 1)
        self.assertIsInstance(declaration_facts[0], KanDeclaredProgress)
        self.assertIs(declaration_facts[0].meld.meld_type, PublicMeldType.KAKAN)

        before_confirmation = len(state.events)
        resolve_with(state, {})

        confirmation_facts = project_round_progress(
            tuple(state.events)[before_confirmation:]
        )
        kan_confirmed = [
            fact
            for fact in confirmation_facts
            if isinstance(fact, KanConfirmedProgress)
        ]
        self.assertEqual(len(kan_confirmed), 1)
        self.assertIs(kan_confirmed[0].meld.meld_type, PublicMeldType.KAKAN)
        # 宣言と成立は別のtransactionから届き、混同されない。
        self.assertNotIsInstance(declaration_facts[0], KanConfirmedProgress)


class AnkanProgressTest(unittest.TestCase):
    def test_ankan_declaration_and_confirmation_are_distinct_ordered_facts(
        self,
    ) -> None:
        state = dealt_state(hands=_ANKAN_HANDS, draws=("8s",), with_dead_wall=True)
        state.draw(Seat.EAST)
        before = len(state.events)

        snapshot = state.legal_actions(Seat.EAST)
        state.apply(
            Seat.EAST,
            action_of_type(state, Seat.EAST, AnkanLegalAction),
            expected_revision=snapshot.revision,
        )

        facts = project_round_progress(tuple(state.events)[before:])

        declared = [fact for fact in facts if isinstance(fact, KanDeclaredProgress)]
        confirmed = [fact for fact in facts if isinstance(fact, KanConfirmedProgress)]
        self.assertEqual(len(declared), 1)
        self.assertIs(declared[0].meld.meld_type, PublicMeldType.ANKAN)
        # kokushi_ankan_chankan_enabledを有効化していないため、槍槓windowを
        # 経由せず宣言と同じtransactionでankanが成立し、両方のfactが届く。
        self.assertEqual(len(confirmed), 1)
        self.assertIs(confirmed[0].meld.meld_type, PublicMeldType.ANKAN)
        self.assertEqual(facts.index(declared[0]), 0)
        self.assertLess(facts.index(declared[0]), facts.index(confirmed[0]))


class RiichiProgressTest(unittest.TestCase):
    def test_riichi_declaration_then_establishment_are_ordered_and_distinct(
        self,
    ) -> None:
        state = dealt_state(
            hands=_RIICHI_ESTABLISH_HANDS, draws=("5z",), with_dead_wall=True
        )
        before = len(state.events)

        # 誰も反応できないため、宣言と成立は同じtransaction内で確定する。
        draw_and_discard(state, Seat.EAST, declares_riichi=True)

        facts = project_round_progress(tuple(state.events)[before:])

        declared_index = next(
            index
            for index, fact in enumerate(facts)
            if isinstance(fact, RiichiDeclaredProgress)
        )
        established_index = next(
            index
            for index, fact in enumerate(facts)
            if isinstance(fact, RiichiEstablishedProgress)
        )
        self.assertLess(declared_index, established_index)
        self.assertIs(facts[declared_index].seat, Seat.EAST)
        self.assertIs(facts[established_index].seat, Seat.EAST)
        self.assertFalse(any(isinstance(fact, RiichiFailedProgress) for fact in facts))

    def test_riichi_declaration_failed_by_ron_is_reported_as_failure(self) -> None:
        state = dealt_state(
            hands=_RIICHI_FAIL_HANDS, draws=("5z",), with_dead_wall=True
        )
        before = len(state.events)

        draw_and_discard(state, Seat.EAST, declares_riichi=True)
        resolve_with(state, {Seat.WEST: ron_action(state, Seat.WEST)})

        facts = project_round_progress(tuple(state.events)[before:])
        failed = [fact for fact in facts if isinstance(fact, RiichiFailedProgress)]
        established = [
            fact for fact in facts if isinstance(fact, RiichiEstablishedProgress)
        ]
        self.assertEqual(len(failed), 1)
        self.assertIs(failed[0].seat, Seat.EAST)
        self.assertEqual(established, [])


class DoraIndicatorProgressTest(unittest.TestCase):
    def test_dora_indicator_reveal_from_ankan_is_reported(self) -> None:
        state = dealt_state(hands=_ANKAN_HANDS, draws=("8s",), with_dead_wall=True)
        state.draw(Seat.EAST)
        before = len(state.events)

        snapshot = state.legal_actions(Seat.EAST)
        state.apply(
            Seat.EAST,
            action_of_type(state, Seat.EAST, AnkanLegalAction),
            expected_revision=snapshot.revision,
        )

        facts = project_round_progress(tuple(state.events)[before:])
        reveals = [
            fact for fact in facts if isinstance(fact, DoraIndicatorRevealedProgress)
        ]
        self.assertEqual(len(reveals), 1)
        self.assertIs(reveals[0].seat, Seat.EAST)


class RoundProgressFactBaseTest(unittest.TestCase):
    def test_all_fact_types_derive_from_the_common_base(self) -> None:
        state = dealt_state(hands=_REACTION_HANDS, draws=("8s",), with_dead_wall=True)
        draw_and_discard(state, Seat.EAST, "7p")
        facts = project_round_progress(state.events)
        self.assertTrue(facts)
        for fact in facts:
            self.assertIsInstance(fact, RoundProgressFact)


if __name__ == "__main__":
    unittest.main()
