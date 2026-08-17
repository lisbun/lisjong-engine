import unittest
from dataclasses import FrozenInstanceError

from lisjong_engine.seat import Seat
from lisjong_engine.settlement import (
    RiichiStickAward,
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
