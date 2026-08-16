import unittest
from dataclasses import replace

from lisjong_engine.discard import Discard
from lisjong_engine.reaction import ReactionType
from lisjong_engine.riichi_event import (
    RiichiContribution,
    RiichiDeclaration,
    RiichiDeclarationFinalization,
    RiichiDeclarationOutcome,
    finalize_riichi_declaration,
)
from lisjong_engine.seat import Seat
from lisjong_engine.tile import STANDARD_TILES
from lisjong_engine.win_context import RiichiStatus

_DISCARD = Discard(STANDARD_TILES[0], is_tsumogiri=True)
_STICK_POINTS = 1_000


def _declaration(**overrides) -> RiichiDeclaration:
    fields = {
        "seat": Seat.EAST,
        "discard": _DISCARD,
        "discard_count": 1,
        "remaining_live_tiles": 60,
        "was_first_discard": True,
        "had_prior_call": False,
    }
    fields.update(overrides)
    return RiichiDeclaration(**fields)


class RiichiDeclarationTest(unittest.TestCase):
    def test_exposes_the_declared_tile(self) -> None:
        self.assertEqual(_declaration().tile, _DISCARD.tile)

    def test_the_first_uncalled_discard_declares_double_riichi(self) -> None:
        self.assertIs(_declaration().riichi_status, RiichiStatus.DOUBLE_RIICHI)

    def test_a_later_discard_declares_a_normal_riichi(self) -> None:
        self.assertIs(
            _declaration(was_first_discard=False, discard_count=4).riichi_status,
            RiichiStatus.RIICHI,
        )

    def test_a_prior_call_prevents_double_riichi(self) -> None:
        self.assertIs(
            _declaration(had_prior_call=True).riichi_status,
            RiichiStatus.RIICHI,
        )

    def test_rejects_invalid_fields(self) -> None:
        with self.assertRaises(TypeError):
            _declaration(seat="east")
        with self.assertRaises(TypeError):
            _declaration(discard=STANDARD_TILES[0])
        with self.assertRaises(TypeError):
            _declaration(discard_count="1")
        with self.assertRaises(ValueError):
            _declaration(discard_count=0)
        with self.assertRaises(ValueError):
            _declaration(remaining_live_tiles=0)
        with self.assertRaises(TypeError):
            _declaration(was_first_discard="yes")


class RiichiContributionTest(unittest.TestCase):
    def test_rejects_invalid_fields(self) -> None:
        with self.assertRaises(TypeError):
            RiichiContribution("east", _STICK_POINTS)
        with self.assertRaises(TypeError):
            RiichiContribution(Seat.EAST, "1000")
        with self.assertRaises(ValueError):
            RiichiContribution(Seat.EAST, 0)


class FinalizeRiichiDeclarationTest(unittest.TestCase):
    def test_an_unclaimed_declaration_establishes_riichi_with_ippatsu(self) -> None:
        finalization = finalize_riichi_declaration(
            _declaration(),
            reaction_type=ReactionType.PASS,
            riichi_stick_points=_STICK_POINTS,
        )

        self.assertIs(finalization.outcome, RiichiDeclarationOutcome.ESTABLISHED)
        self.assertTrue(finalization.is_established)
        self.assertTrue(finalization.grants_ippatsu)
        self.assertFalse(finalization.established_after_call)
        self.assertEqual(
            finalization.contribution,
            RiichiContribution(Seat.EAST, _STICK_POINTS),
        )
        self.assertIs(finalization.riichi_status, RiichiStatus.DOUBLE_RIICHI)

    def test_a_ron_on_the_declaration_tile_fails_the_riichi(self) -> None:
        finalization = finalize_riichi_declaration(
            _declaration(),
            reaction_type=ReactionType.RON,
            riichi_stick_points=_STICK_POINTS,
        )

        self.assertIs(finalization.outcome, RiichiDeclarationOutcome.FAILED_BY_RON)
        self.assertFalse(finalization.is_established)
        self.assertIsNone(finalization.contribution)
        self.assertFalse(finalization.grants_ippatsu)
        self.assertIs(finalization.riichi_status, RiichiStatus.NONE)

    def test_a_call_on_the_declaration_tile_establishes_riichi_without_ippatsu(
        self,
    ) -> None:
        for reaction_type in (
            ReactionType.PON,
            ReactionType.CHI,
            ReactionType.DAIMINKAN,
        ):
            with self.subTest(reaction_type=reaction_type):
                finalization = finalize_riichi_declaration(
                    _declaration(),
                    reaction_type=reaction_type,
                    riichi_stick_points=_STICK_POINTS,
                )

                self.assertTrue(finalization.is_established)
                self.assertTrue(finalization.established_after_call)
                self.assertFalse(finalization.grants_ippatsu)
                self.assertEqual(
                    finalization.contribution,
                    RiichiContribution(Seat.EAST, _STICK_POINTS),
                )

    def test_the_contribution_uses_the_configured_stick_points(self) -> None:
        """供託額は`riichi_stick_points`であり、1,000点をhardcodeしない。"""
        finalization = finalize_riichi_declaration(
            _declaration(),
            reaction_type=ReactionType.PASS,
            riichi_stick_points=1_500,
        )

        self.assertEqual(finalization.contribution.points, 1_500)

    def test_rejects_invalid_arguments(self) -> None:
        with self.assertRaises(TypeError):
            finalize_riichi_declaration(
                "declaration",
                reaction_type=ReactionType.PASS,
                riichi_stick_points=_STICK_POINTS,
            )
        with self.assertRaises(TypeError):
            finalize_riichi_declaration(
                _declaration(),
                reaction_type="pass",
                riichi_stick_points=_STICK_POINTS,
            )
        with self.assertRaises(TypeError):
            finalize_riichi_declaration(
                _declaration(),
                reaction_type=ReactionType.PASS,
                riichi_stick_points="1000",
            )


class RiichiDeclarationFinalizationValidationTest(unittest.TestCase):
    def _established(self) -> RiichiDeclarationFinalization:
        return finalize_riichi_declaration(
            _declaration(),
            reaction_type=ReactionType.PASS,
            riichi_stick_points=_STICK_POINTS,
        )

    def test_exposes_the_declaring_seat(self) -> None:
        self.assertIs(self._established().seat, Seat.EAST)

    def test_rejects_an_outcome_that_contradicts_the_reaction(self) -> None:
        with self.assertRaises(ValueError):
            replace(
                self._established(),
                outcome=RiichiDeclarationOutcome.FAILED_BY_RON,
            )

    def test_rejects_an_established_riichi_without_a_contribution(self) -> None:
        with self.assertRaises(ValueError):
            replace(self._established(), contribution=None)

    def test_rejects_a_failed_riichi_that_owes_a_contribution(self) -> None:
        failed = finalize_riichi_declaration(
            _declaration(),
            reaction_type=ReactionType.RON,
            riichi_stick_points=_STICK_POINTS,
        )

        with self.assertRaises(ValueError):
            replace(
                failed,
                contribution=RiichiContribution(Seat.EAST, _STICK_POINTS),
            )

    def test_rejects_a_contribution_owed_by_another_seat(self) -> None:
        with self.assertRaises(ValueError):
            replace(
                self._established(),
                contribution=RiichiContribution(Seat.SOUTH, _STICK_POINTS),
            )

    def test_rejects_invalid_field_types(self) -> None:
        with self.assertRaises(TypeError):
            replace(self._established(), declaration="declaration")
        with self.assertRaises(TypeError):
            replace(self._established(), reaction_type="pass")
        with self.assertRaises(TypeError):
            replace(self._established(), outcome="established")
        with self.assertRaises(TypeError):
            replace(self._established(), contribution=1_000)


if __name__ == "__main__":
    unittest.main()
