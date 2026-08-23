import unittest
from dataclasses import FrozenInstanceError

from lisjong_engine.legal_action import (
    AnkanLegalAction,
    ChiLegalAction,
    DaiminkanLegalAction,
    DiscardLegalAction,
    KakanLegalAction,
    LegalActionSnapshot,
    NineTerminalsLegalAction,
    PassLegalAction,
    PonLegalAction,
    ReactionOrigin,
    RiichiLegalAction,
    RonLegalAction,
    TsumoLegalAction,
    is_legal_action,
)
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.seat import Seat


class LegalActionValueTest(unittest.TestCase):
    def test_covers_the_discriminated_union_members(self) -> None:
        actions = (
            DiscardLegalAction(0),
            RiichiLegalAction(),
            AnkanLegalAction((3, 2, 1, 0)),
            KakanLegalAction(4),
            TsumoLegalAction(),
            NineTerminalsLegalAction(),
            PassLegalAction(ReactionOrigin.DISCARD, 5),
            RonLegalAction(ReactionOrigin.KAKAN, 6),
            ChiLegalAction(7, (9, 8)),
            PonLegalAction(10, (12, 11)),
            DaiminkanLegalAction(13, (16, 15, 14)),
        )

        for action in actions:
            with self.subTest(action=action):
                self.assertTrue(is_legal_action(action))

    def test_rejects_values_outside_the_union(self) -> None:
        for value in (None, 0, "discard", (DiscardLegalAction(0),)):
            with self.subTest(value=value):
                self.assertFalse(is_legal_action(value))

    def test_actions_are_frozen_value_objects(self) -> None:
        action = DiscardLegalAction(3)

        with self.assertRaises(FrozenInstanceError):
            action.tile_id = 4

    def test_identity_is_derived_from_domain_data(self) -> None:
        self.assertEqual(DiscardLegalAction(3), DiscardLegalAction(3))
        self.assertEqual(hash(DiscardLegalAction(3)), hash(DiscardLegalAction(3)))
        self.assertNotEqual(DiscardLegalAction(3), DiscardLegalAction(4))

    def test_discard_carries_no_riichi_declaration(self) -> None:
        """打牌actionは打牌そのものだけを表し、立直宣言と結合しない。"""
        self.assertEqual(
            tuple(DiscardLegalAction(3).__dataclass_fields__),
            ("tile_id",),
        )

    def test_riichi_is_an_action_without_a_declaration_tile(self) -> None:
        """立直は宣言牌を持たない独立actionであり、値としても一意である。"""
        self.assertEqual(RiichiLegalAction(), RiichiLegalAction())
        self.assertEqual(hash(RiichiLegalAction()), hash(RiichiLegalAction()))
        self.assertEqual(tuple(RiichiLegalAction().__dataclass_fields__), ())

    def test_normalizes_consumed_tile_ids_into_sorted_tuples(self) -> None:
        self.assertEqual(ChiLegalAction(7, (9, 8)).consumed_tile_ids, (8, 9))
        self.assertEqual(PonLegalAction(10, (12, 11)).consumed_tile_ids, (11, 12))
        self.assertEqual(
            DaiminkanLegalAction(13, (16, 15, 14)).consumed_tile_ids,
            (14, 15, 16),
        )
        self.assertEqual(AnkanLegalAction((3, 1, 2, 0)).tile_ids, (0, 1, 2, 3))

    def test_uses_physical_tile_ids(self) -> None:
        first_five_manzu = 16
        second_five_manzu = 17

        self.assertNotEqual(
            DiscardLegalAction(first_five_manzu),
            DiscardLegalAction(second_five_manzu),
        )

    def test_rejects_non_integer_tile_ids(self) -> None:
        for factory in (
            lambda: DiscardLegalAction("0"),
            lambda: KakanLegalAction(None),
            lambda: ChiLegalAction(7, (8, "9")),
            lambda: AnkanLegalAction((0, 1, 2, "3")),
        ):
            with self.subTest(factory=factory):
                with self.assertRaises(TypeError):
                    factory()

    def test_rejects_negative_tile_ids(self) -> None:
        for factory in (
            lambda: DiscardLegalAction(-1),
            lambda: KakanLegalAction(-1),
            lambda: PassLegalAction(ReactionOrigin.DISCARD, -1),
            lambda: RonLegalAction(ReactionOrigin.DISCARD, -1),
            lambda: PonLegalAction(10, (-1, 11)),
        ):
            with self.subTest(factory=factory):
                with self.assertRaises(ValueError):
                    factory()

    def test_rejects_duplicate_consumed_tile_ids(self) -> None:
        for factory in (
            lambda: ChiLegalAction(7, (8, 8)),
            lambda: PonLegalAction(10, (11, 11)),
            lambda: DaiminkanLegalAction(13, (14, 14, 15)),
            lambda: AnkanLegalAction((0, 1, 2, 2)),
        ):
            with self.subTest(factory=factory):
                with self.assertRaises(ValueError):
                    factory()

    def test_rejects_wrong_consumed_tile_counts(self) -> None:
        for factory in (
            lambda: ChiLegalAction(7, (8, 9, 10)),
            lambda: PonLegalAction(10, (11,)),
            lambda: DaiminkanLegalAction(13, (14, 15)),
            lambda: AnkanLegalAction((0, 1, 2)),
        ):
            with self.subTest(factory=factory):
                with self.assertRaises(ValueError):
                    factory()

    def test_rejects_invalid_enum_members(self) -> None:
        with self.assertRaises(TypeError):
            DiscardLegalAction(0, "riichi")
        with self.assertRaises(TypeError):
            RonLegalAction("discard", 0)
        with self.assertRaises(TypeError):
            PassLegalAction("discard", 0)

    def test_reaction_origin_distinguishes_declaration_sources(self) -> None:
        self.assertEqual(
            tuple(origin.value for origin in ReactionOrigin),
            ("discard", "kakan", "ankan"),
        )


class LegalActionSnapshotTest(unittest.TestCase):
    def _snapshot(
        self, actions: tuple = (DiscardLegalAction(0),)
    ) -> LegalActionSnapshot:
        return LegalActionSnapshot(
            seat=Seat.EAST,
            phase=RoundPhase.AWAITING_DISCARD,
            revision=2,
            actions=actions,
        )

    def test_exposes_seat_phase_revision_and_actions(self) -> None:
        snapshot = self._snapshot((DiscardLegalAction(0), DiscardLegalAction(1)))

        self.assertIs(snapshot.seat, Seat.EAST)
        self.assertIs(snapshot.phase, RoundPhase.AWAITING_DISCARD)
        self.assertEqual(snapshot.revision, 2)
        self.assertEqual(
            snapshot.actions,
            (DiscardLegalAction(0), DiscardLegalAction(1)),
        )

    def test_actions_are_normalized_into_an_immutable_tuple(self) -> None:
        actions = [DiscardLegalAction(0)]

        snapshot = self._snapshot(actions)
        actions.append(DiscardLegalAction(1))

        self.assertIsInstance(snapshot.actions, tuple)
        self.assertEqual(snapshot.actions, (DiscardLegalAction(0),))

    def test_snapshot_is_frozen(self) -> None:
        snapshot = self._snapshot()

        with self.assertRaises(FrozenInstanceError):
            snapshot.revision = 3

    def test_supports_membership_and_length(self) -> None:
        snapshot = self._snapshot((DiscardLegalAction(0), DiscardLegalAction(1)))

        self.assertIn(DiscardLegalAction(0), snapshot)
        self.assertNotIn(DiscardLegalAction(2), snapshot)
        self.assertEqual(len(snapshot), 2)

    def test_allows_an_empty_action_set(self) -> None:
        snapshot = LegalActionSnapshot(
            seat=Seat.SOUTH,
            phase=RoundPhase.AWAITING_DRAW,
            revision=0,
        )

        self.assertEqual(snapshot.actions, ())
        self.assertEqual(len(snapshot), 0)

    def test_rejects_duplicate_actions(self) -> None:
        with self.assertRaises(ValueError):
            self._snapshot((DiscardLegalAction(0), DiscardLegalAction(0)))

    def test_rejects_values_that_are_not_legal_actions(self) -> None:
        with self.assertRaises(TypeError):
            self._snapshot((DiscardLegalAction(0), "discard 1m"))

    def test_rejects_invalid_seat_phase_and_revision(self) -> None:
        with self.assertRaises(TypeError):
            LegalActionSnapshot(
                seat="east",
                phase=RoundPhase.AWAITING_DISCARD,
                revision=0,
            )
        with self.assertRaises(TypeError):
            LegalActionSnapshot(
                seat=Seat.EAST,
                phase="awaiting_discard",
                revision=0,
            )
        with self.assertRaises(TypeError):
            LegalActionSnapshot(
                seat=Seat.EAST,
                phase=RoundPhase.AWAITING_DISCARD,
                revision="0",
            )
        with self.assertRaises(ValueError):
            LegalActionSnapshot(
                seat=Seat.EAST,
                phase=RoundPhase.AWAITING_DISCARD,
                revision=-1,
            )


if __name__ == "__main__":
    unittest.main()
