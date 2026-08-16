import unittest

from lisjong_engine.furiten import (
    FuritenReason,
    cleared_temporary_reason,
    derive_furiten_reasons,
    next_missed_ron_reason,
    validate_missed_ron_reason,
)
from lisjong_engine.tile import TileCategory, TileType

_ONE_MAN = TileType(TileCategory.MANZU, 1)
_NINE_SOU = TileType(TileCategory.SOUZU, 9)
_EAST_WIND = TileType(TileCategory.HONOR, 1)


class FuritenReasonTest(unittest.TestCase):
    def test_covers_the_expected_reasons(self) -> None:
        self.assertEqual(
            tuple((reason.name, reason.value) for reason in FuritenReason),
            (
                ("DISCARD", "discard"),
                ("TEMPORARY", "temporary"),
                ("RIICHI", "riichi"),
            ),
        )


class ValidateMissedRonReasonTest(unittest.TestCase):
    def test_accepts_the_missed_ron_reasons_and_none(self) -> None:
        for reason in (None, FuritenReason.TEMPORARY, FuritenReason.RIICHI):
            with self.subTest(reason=reason):
                validate_missed_ron_reason(reason)

    def test_rejects_discard_furiten_as_a_recorded_reason(self) -> None:
        """河由来のフリテンは河から導出するものであり、記録として持たない。"""
        with self.assertRaises(ValueError):
            validate_missed_ron_reason(FuritenReason.DISCARD)

    def test_rejects_a_value_that_is_not_a_reason(self) -> None:
        with self.assertRaises(TypeError):
            validate_missed_ron_reason("temporary")


class DeriveFuritenReasonsTest(unittest.TestCase):
    def _derive(
        self,
        *,
        discarded=(),
        waits=(),
        missed=None,
    ) -> frozenset[FuritenReason]:
        return derive_furiten_reasons(
            discarded_tile_types=discarded,
            winning_tile_types=waits,
            missed_ron_reason=missed,
        )

    def test_no_reason_when_the_river_misses_the_waits(self) -> None:
        self.assertEqual(
            self._derive(discarded=(_NINE_SOU,), waits=(_ONE_MAN,)),
            frozenset(),
        )

    def test_discard_furiten_when_the_river_contains_a_wait(self) -> None:
        self.assertEqual(
            self._derive(discarded=(_NINE_SOU, _ONE_MAN), waits=(_ONE_MAN,)),
            frozenset({FuritenReason.DISCARD}),
        )

    def test_discard_furiten_covers_every_wait_of_a_multi_sided_hand(self) -> None:
        self.assertEqual(
            self._derive(
                discarded=(_EAST_WIND,),
                waits=(_ONE_MAN, _EAST_WIND),
            ),
            frozenset({FuritenReason.DISCARD}),
        )

    def test_missed_ron_reason_is_reported_on_its_own(self) -> None:
        self.assertEqual(
            self._derive(waits=(_ONE_MAN,), missed=FuritenReason.TEMPORARY),
            frozenset({FuritenReason.TEMPORARY}),
        )

    def test_discard_and_missed_ron_reasons_coexist(self) -> None:
        self.assertEqual(
            self._derive(
                discarded=(_ONE_MAN,),
                waits=(_ONE_MAN,),
                missed=FuritenReason.RIICHI,
            ),
            frozenset({FuritenReason.DISCARD, FuritenReason.RIICHI}),
        )

    def test_rejects_a_recorded_discard_reason(self) -> None:
        with self.assertRaises(ValueError):
            self._derive(missed=FuritenReason.DISCARD)


class NextMissedRonReasonTest(unittest.TestCase):
    def test_a_seat_without_riichi_becomes_temporarily_furiten(self) -> None:
        self.assertIs(
            next_missed_ron_reason(None, is_riichi_established=False),
            FuritenReason.TEMPORARY,
        )

    def test_a_riichi_seat_becomes_furiten_for_the_rest_of_the_round(self) -> None:
        self.assertIs(
            next_missed_ron_reason(None, is_riichi_established=True),
            FuritenReason.RIICHI,
        )

    def test_a_temporary_reason_is_upgraded_after_riichi(self) -> None:
        self.assertIs(
            next_missed_ron_reason(
                FuritenReason.TEMPORARY,
                is_riichi_established=True,
            ),
            FuritenReason.RIICHI,
        )

    def test_a_riichi_reason_is_never_weakened(self) -> None:
        self.assertIs(
            next_missed_ron_reason(
                FuritenReason.RIICHI,
                is_riichi_established=False,
            ),
            FuritenReason.RIICHI,
        )

    def test_rejects_invalid_arguments(self) -> None:
        with self.assertRaises(ValueError):
            next_missed_ron_reason(FuritenReason.DISCARD, is_riichi_established=False)
        with self.assertRaises(TypeError):
            next_missed_ron_reason(None, is_riichi_established="yes")


class ClearedTemporaryReasonTest(unittest.TestCase):
    def test_clears_only_the_temporary_reason(self) -> None:
        self.assertIsNone(cleared_temporary_reason(FuritenReason.TEMPORARY))

    def test_keeps_the_riichi_reason(self) -> None:
        self.assertIs(
            cleared_temporary_reason(FuritenReason.RIICHI),
            FuritenReason.RIICHI,
        )

    def test_keeps_none(self) -> None:
        self.assertIsNone(cleared_temporary_reason(None))

    def test_rejects_a_recorded_discard_reason(self) -> None:
        with self.assertRaises(ValueError):
            cleared_temporary_reason(FuritenReason.DISCARD)


if __name__ == "__main__":
    unittest.main()
