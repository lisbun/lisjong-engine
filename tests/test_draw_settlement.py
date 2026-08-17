import unittest
from dataclasses import replace

from lisjong_engine.points import SeatPoints
from lisjong_engine.round_result import (
    AbortiveDrawReason,
    AbortiveDrawResult,
    ExhaustiveDrawResult,
)
from lisjong_engine.rules import RuleSet
from lisjong_engine.seat import Seat
from lisjong_engine.settlement import (
    SettlementTransfer,
    TransferReason,
    aggregate_settlement_transfers,
    calculate_abortive_draw_settlement_transfers,
    calculate_exhaustive_draw_settlement_transfers,
)


class ExhaustiveDrawSettlementTest(unittest.TestCase):
    def test_zero_one_two_three_and_four_tenpai_players(self) -> None:
        cases = (
            ((), SeatPoints(0, 0, 0, 0)),
            (
                (Seat.EAST,),
                SeatPoints(3_000, -1_000, -1_000, -1_000),
            ),
            (
                (Seat.EAST, Seat.WEST),
                SeatPoints(1_500, -1_500, 1_500, -1_500),
            ),
            (
                (Seat.EAST, Seat.SOUTH, Seat.WEST),
                SeatPoints(1_000, 1_000, 1_000, -3_000),
            ),
            (
                tuple(Seat),
                SeatPoints(0, 0, 0, 0),
            ),
        )

        for tenpai_seats, expected in cases:
            with self.subTest(tenpai_seats=tenpai_seats):
                result = ExhaustiveDrawResult(
                    tenpai_seats=tenpai_seats,
                )
                transfers = calculate_exhaustive_draw_settlement_transfers(result)

                self.assertEqual(
                    aggregate_settlement_transfers(transfers),
                    expected,
                )
                self.assertEqual(expected.total, 0)

    def test_custom_noten_remainder_is_deterministic_and_balanced(
        self,
    ) -> None:
        rules = replace(
            RuleSet.default(),
            noten_penalty_total=3_006,
        )
        result = ExhaustiveDrawResult(
            tenpai_seats=(Seat.EAST, Seat.SOUTH),
        )

        transfers = calculate_exhaustive_draw_settlement_transfers(
            result,
            rules=rules,
        )

        self.assertEqual(
            transfers,
            (
                SettlementTransfer(
                    Seat.WEST,
                    Seat.EAST,
                    752,
                    TransferReason.NOTEN_PENALTY,
                ),
                SettlementTransfer(
                    Seat.WEST,
                    Seat.SOUTH,
                    751,
                    TransferReason.NOTEN_PENALTY,
                ),
                SettlementTransfer(
                    Seat.NORTH,
                    Seat.EAST,
                    751,
                    TransferReason.NOTEN_PENALTY,
                ),
                SettlementTransfer(
                    Seat.NORTH,
                    Seat.SOUTH,
                    752,
                    TransferReason.NOTEN_PENALTY,
                ),
            ),
        )
        self.assertEqual(
            aggregate_settlement_transfers(transfers),
            SeatPoints(1_503, 1_503, -1_503, -1_503),
        )

    def test_nagashi_mangan_replaces_noten_penalty(self) -> None:
        result = ExhaustiveDrawResult(
            tenpai_seats=(Seat.EAST, Seat.WEST),
            nagashi_mangan_seats=(Seat.SOUTH,),
        )

        transfers = calculate_exhaustive_draw_settlement_transfers(
            result,
            dealer_seat=Seat.EAST,
        )

        self.assertTrue(
            all(
                transfer.reason is TransferReason.NAGASHI_MANGAN
                for transfer in transfers
            )
        )
        self.assertEqual(
            aggregate_settlement_transfers(transfers),
            SeatPoints(-4_000, 8_000, -2_000, -2_000),
        )

    def test_dealer_nagashi_mangan(self) -> None:
        result = ExhaustiveDrawResult(
            nagashi_mangan_seats=(Seat.EAST,),
        )

        transfers = calculate_exhaustive_draw_settlement_transfers(
            result,
            dealer_seat=Seat.EAST,
        )

        self.assertEqual(
            aggregate_settlement_transfers(transfers),
            SeatPoints(12_000, -4_000, -4_000, -4_000),
        )

    def test_multiple_nagashi_mangan(self) -> None:
        result = ExhaustiveDrawResult(
            nagashi_mangan_seats=(Seat.SOUTH, Seat.EAST),
        )

        transfers = calculate_exhaustive_draw_settlement_transfers(
            result,
            dealer_seat=Seat.EAST,
        )

        self.assertEqual(
            aggregate_settlement_transfers(transfers),
            SeatPoints(8_000, 4_000, -6_000, -6_000),
        )

    def test_rejects_nagashi_when_disabled(self) -> None:
        rules = replace(
            RuleSet.default(),
            nagashi_mangan_enabled=False,
        )
        result = ExhaustiveDrawResult(
            nagashi_mangan_seats=(Seat.SOUTH,),
        )

        with self.assertRaisesRegex(ValueError, "disabled"):
            calculate_exhaustive_draw_settlement_transfers(
                result,
                dealer_seat=Seat.EAST,
                rules=rules,
            )

    def test_nagashi_requires_dealer_seat(self) -> None:
        result = ExhaustiveDrawResult(
            nagashi_mangan_seats=(Seat.SOUTH,),
        )

        with self.assertRaisesRegex(ValueError, "dealer_seat"):
            calculate_exhaustive_draw_settlement_transfers(result)

    def test_rejects_invalid_inputs(self) -> None:
        with self.assertRaises(TypeError):
            calculate_exhaustive_draw_settlement_transfers("draw")

        with self.assertRaises(TypeError):
            calculate_exhaustive_draw_settlement_transfers(
                ExhaustiveDrawResult(),
                dealer_seat="east",
            )

        with self.assertRaises(TypeError):
            calculate_exhaustive_draw_settlement_transfers(
                ExhaustiveDrawResult(),
                rules="rules",
            )


class AbortiveDrawSettlementTest(unittest.TestCase):
    def test_enabled_abortive_draws_have_no_normal_transfer(self) -> None:
        for reason in AbortiveDrawReason:
            with self.subTest(reason=reason):
                transfers = calculate_abortive_draw_settlement_transfers(
                    AbortiveDrawResult(reason)
                )

                self.assertEqual(transfers, ())

    def test_rejects_reason_disabled_by_rules(self) -> None:
        cases = (
            (
                AbortiveDrawReason.NINE_TERMINALS,
                "nine_terminals_abortive_draw_enabled",
            ),
            (
                AbortiveDrawReason.FOUR_WINDS,
                "four_winds_abortive_draw_enabled",
            ),
            (
                AbortiveDrawReason.FOUR_KANS,
                "four_kans_abortive_draw_enabled",
            ),
            (
                AbortiveDrawReason.FOUR_RIICHI,
                "four_riichi_abortive_draw_enabled",
            ),
            (
                AbortiveDrawReason.TRIPLE_RON,
                "triple_ron_abortive_draw",
            ),
        )

        for reason, field_name in cases:
            with self.subTest(reason=reason):
                rules = replace(
                    RuleSet.default(),
                    **{field_name: False},
                )

                with self.assertRaisesRegex(ValueError, "disabled"):
                    calculate_abortive_draw_settlement_transfers(
                        AbortiveDrawResult(reason),
                        rules=rules,
                    )

    def test_rejects_invalid_inputs(self) -> None:
        with self.assertRaises(TypeError):
            calculate_abortive_draw_settlement_transfers("draw")

        with self.assertRaises(TypeError):
            calculate_abortive_draw_settlement_transfers(
                AbortiveDrawResult(AbortiveDrawReason.NINE_TERMINALS),
                rules="rules",
            )


if __name__ == "__main__":
    unittest.main()
