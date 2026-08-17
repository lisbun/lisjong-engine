from dataclasses import dataclass
from enum import Enum

from lisjong_engine.seat import Seat


class TransferReason(Enum):
    RON = "ron"
    TSUMO = "tsumo"
    PAO_RON = "pao_ron"
    PAO_TSUMO = "pao_tsumo"
    HONBA = "honba"
    NOTEN_PENALTY = "noten_penalty"
    NAGASHI_MANGAN = "nagashi_mangan"


@dataclass(frozen=True)
class RiichiStickAward:
    """局終了時に卓上の供託がプレイヤーへ渡された結果。"""

    recipient: Seat
    amount: int

    def __post_init__(self) -> None:
        if not isinstance(self.recipient, Seat):
            raise TypeError("recipient must be a Seat")
        if type(self.amount) is not int:
            raise TypeError("amount must be an int")
        if self.amount <= 0:
            raise ValueError("amount must be positive")


@dataclass(frozen=True)
class SettlementTransfer:
    """プレイヤー間で発生した点数移動を表す監査可能な値型。"""

    payer: Seat
    recipient: Seat
    amount: int
    reason: TransferReason
    winner_seat: Seat | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.payer, Seat):
            raise TypeError("payer must be a Seat")
        if not isinstance(self.recipient, Seat):
            raise TypeError("recipient must be a Seat")
        if self.payer is self.recipient:
            raise ValueError("payer and recipient must be different seats")
        if type(self.amount) is not int:
            raise TypeError("amount must be an int")
        if self.amount <= 0:
            raise ValueError("amount must be positive")
        if not isinstance(self.reason, TransferReason):
            raise TypeError("reason must be a TransferReason")
        if self.winner_seat is not None and not isinstance(self.winner_seat, Seat):
            raise TypeError("winner_seat must be a Seat or None")

        if self.reason is TransferReason.NOTEN_PENALTY:
            if self.winner_seat is not None:
                raise ValueError("noten penalty transfers cannot have a winner")
        elif self.winner_seat is not self.recipient:
            raise ValueError(
                "winning transfers must identify their recipient as winner"
            )
