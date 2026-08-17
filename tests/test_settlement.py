import unittest
from dataclasses import FrozenInstanceError

from lisjong_engine.points import SeatPoints
from lisjong_engine.riichi_event import RiichiContribution
from lisjong_engine.seat import Seat
from lisjong_engine.settlement import (
    RiichiStickAward,
    RoundSettlement,
    SettlementTransfer,
    TransferReason,
)


class RiichiStickAwardTest(unittest.TestCase):
    def test_stores_recipient_and_amount(self) -> None:
        award = RiichiStickAward(Seat.SOUTH, 2_000)

        self.assertIs(award.recipient, Seat.SOUTH)
        self.assertEqual(award.amount, 2_000)

    def test_is_immutable(self) -> None:
        award = RiichiStickAward(Seat.SOUTH, 1_000)

        with self.assertRaises(FrozenInstanceError):
            setattr(award, "amount", 2_000)

    def test_rejects_invalid_values(self) -> None:
        with self.assertRaises(TypeError):
            RiichiStickAward("south", 1_000)  # type: ignore[arg-type]

        with self.assertRaises(TypeError):
            RiichiStickAward(Seat.SOUTH, True)

        with self.assertRaises(ValueError):
            RiichiStickAward(Seat.SOUTH, 0)


class RoundSettlementTest(unittest.TestCase):
    def test_derives_auditable_point_deltas(self) -> None:
        transfers = (
            SettlementTransfer(
                Seat.EAST,
                Seat.SOUTH,
                1_600,
                TransferReason.RON,
                Seat.SOUTH,
            ),
        )
        contributions = (RiichiContribution(Seat.WEST, 1_000),)
        awards = (RiichiStickAward(Seat.SOUTH, 2_000),)

        result = RoundSettlement(
            point_deltas=SeatPoints(
                -1_600,
                3_600,
                -1_000,
                0,
            ),
            transfers=transfers,
            riichi_contributions=contributions,
            riichi_stick_awards=awards,
            riichi_sticks_after=0,
        )

        self.assertEqual(result.transfers, transfers)
        self.assertEqual(
            result.riichi_contributions,
            contributions,
        )
        self.assertEqual(
            result.riichi_stick_awards,
            awards,
        )
        self.assertEqual(result.point_deltas.total, 1_000)
        self.assertEqual(result.riichi_sticks_after, 0)

    def test_defensively_copies_collections(self) -> None:
        transfers = [
            SettlementTransfer(
                Seat.EAST,
                Seat.SOUTH,
                1_600,
                TransferReason.RON,
                Seat.SOUTH,
            )
        ]
        contributions = [RiichiContribution(Seat.WEST, 1_000)]
        awards = [RiichiStickAward(Seat.SOUTH, 1_000)]

        result = RoundSettlement(
            point_deltas=SeatPoints(
                -1_600,
                2_600,
                -1_000,
                0,
            ),
            transfers=transfers,
            riichi_contributions=contributions,
            riichi_stick_awards=awards,
            riichi_sticks_after=0,
        )

        transfers.clear()
        contributions.clear()
        awards.clear()

        self.assertEqual(len(result.transfers), 1)
        self.assertEqual(len(result.riichi_contributions), 1)
        self.assertEqual(len(result.riichi_stick_awards), 1)

    def test_is_immutable(self) -> None:
        result = RoundSettlement(
            point_deltas=SeatPoints(0, 0, 0, 0),
        )

        with self.assertRaises(FrozenInstanceError):
            result.riichi_sticks_after = 1

    def test_rejects_point_deltas_inconsistent_with_audit_facts(self) -> None:
        transfer = SettlementTransfer(
            Seat.EAST,
            Seat.SOUTH,
            1_600,
            TransferReason.RON,
            Seat.SOUTH,
        )

        with self.assertRaisesRegex(
            ValueError,
            "point_deltas",
        ):
            RoundSettlement(
                point_deltas=SeatPoints(0, 0, 0, 0),
                transfers=(transfer,),
            )

    def test_rejects_duplicate_riichi_contribution_seats(self) -> None:
        contributions = (
            RiichiContribution(Seat.EAST, 1_000),
            RiichiContribution(Seat.EAST, 1_000),
        )

        with self.assertRaisesRegex(ValueError, "unique"):
            RoundSettlement(
                point_deltas=SeatPoints(-2_000, 0, 0, 0),
                riichi_contributions=contributions,
                riichi_sticks_after=2,
            )

    def test_rejects_invalid_collection_members(self) -> None:
        with self.assertRaises(TypeError):
            RoundSettlement(
                point_deltas=SeatPoints(0, 0, 0, 0),
                transfers=("transfer",),
            )

        with self.assertRaises(TypeError):
            RoundSettlement(
                point_deltas=SeatPoints(0, 0, 0, 0),
                riichi_contributions=("contribution",),
            )

        with self.assertRaises(TypeError):
            RoundSettlement(
                point_deltas=SeatPoints(0, 0, 0, 0),
                riichi_stick_awards=("award",),
            )

    def test_rejects_invalid_riichi_sticks_after(self) -> None:
        with self.assertRaises(TypeError):
            RoundSettlement(
                point_deltas=SeatPoints(0, 0, 0, 0),
                riichi_sticks_after=True,
            )

        with self.assertRaises(ValueError):
            RoundSettlement(
                point_deltas=SeatPoints(0, 0, 0, 0),
                riichi_sticks_after=-1,
            )


class SettlementTransferTest(unittest.TestCase):
    def test_stores_winning_transfer(self) -> None:
        transfer = SettlementTransfer(
            payer=Seat.EAST,
            recipient=Seat.SOUTH,
            amount=8_000,
            reason=TransferReason.RON,
            winner_seat=Seat.SOUTH,
        )

        self.assertIs(transfer.payer, Seat.EAST)
        self.assertIs(transfer.recipient, Seat.SOUTH)
        self.assertEqual(transfer.amount, 8_000)
        self.assertIs(transfer.reason, TransferReason.RON)
        self.assertIs(transfer.winner_seat, Seat.SOUTH)

    def test_noten_penalty_has_no_winner(self) -> None:
        transfer = SettlementTransfer(
            payer=Seat.EAST,
            recipient=Seat.SOUTH,
            amount=1_000,
            reason=TransferReason.NOTEN_PENALTY,
        )

        self.assertIsNone(transfer.winner_seat)

    def test_rejects_same_payer_and_recipient(self) -> None:
        with self.assertRaises(ValueError):
            SettlementTransfer(
                payer=Seat.EAST,
                recipient=Seat.EAST,
                amount=1_000,
                reason=TransferReason.RON,
                winner_seat=Seat.EAST,
            )

    def test_rejects_non_positive_or_non_int_amount(self) -> None:
        with self.assertRaises(ValueError):
            SettlementTransfer(
                payer=Seat.EAST,
                recipient=Seat.SOUTH,
                amount=0,
                reason=TransferReason.RON,
                winner_seat=Seat.SOUTH,
            )

        with self.assertRaises(TypeError):
            SettlementTransfer(
                payer=Seat.EAST,
                recipient=Seat.SOUTH,
                amount=True,
                reason=TransferReason.RON,
                winner_seat=Seat.SOUTH,
            )

    def test_winning_transfer_requires_recipient_as_winner(self) -> None:
        with self.assertRaises(ValueError):
            SettlementTransfer(
                payer=Seat.EAST,
                recipient=Seat.SOUTH,
                amount=8_000,
                reason=TransferReason.RON,
                winner_seat=Seat.WEST,
            )

        with self.assertRaises(ValueError):
            SettlementTransfer(
                payer=Seat.EAST,
                recipient=Seat.SOUTH,
                amount=8_000,
                reason=TransferReason.RON,
            )

    def test_noten_penalty_rejects_winner(self) -> None:
        with self.assertRaises(ValueError):
            SettlementTransfer(
                payer=Seat.EAST,
                recipient=Seat.SOUTH,
                amount=1_000,
                reason=TransferReason.NOTEN_PENALTY,
                winner_seat=Seat.SOUTH,
            )


if __name__ == "__main__":
    unittest.main()
