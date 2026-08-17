from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from lisjong_engine.points import SeatPoints
from lisjong_engine.round_result import WinningPlayerResult, WinResult
from lisjong_engine.rules import RuleSet
from lisjong_engine.seat import Seat
from lisjong_engine.win_context import WinMethod
from lisjong_engine.wind import Wind


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


def calculate_single_win_settlement_transfers(
    result: WinResult,
    *,
    dealer_seat: Seat,
    honba: int = 0,
    rules: RuleSet | None = None,
) -> tuple[SettlementTransfer, ...]:
    """パオを伴わないsingle-winner和了のplayer間transferを計算する。

    本関数はRoundSettlement構築前のlower-level pure calculationであり、
    riichi stickの授与は扱わない。
    """
    if not isinstance(result, WinResult):
        raise TypeError("result must be a WinResult")
    if not isinstance(dealer_seat, Seat):
        raise TypeError("dealer_seat must be a Seat")
    if type(honba) is not int:
        raise TypeError("honba must be an int")
    if honba < 0:
        raise ValueError("honba must be non-negative")

    if rules is None:
        rules = RuleSet.default()
    elif not isinstance(rules, RuleSet):
        raise TypeError("rules must be a RuleSet")

    if len(result.winners) != 1:
        raise ValueError("single win settlement requires exactly one winner")

    winner = result.winners[0]
    _validate_winner_settlement_context(
        winner,
        dealer_seat=dealer_seat,
        rules=rules,
    )

    if result.method is WinMethod.RON:
        return _single_ron_transfers(
            result,
            winner,
            honba=honba,
            rules=rules,
        )

    return _single_tsumo_transfers(
        winner,
        dealer_seat=dealer_seat,
        honba=honba,
        rules=rules,
    )


def aggregate_settlement_transfers(
    transfers: Iterable[SettlementTransfer],
) -> SeatPoints:
    """player間transferを4席のpoint deltaへ集約する。"""
    try:
        transfer_tuple = tuple(transfers)
    except TypeError:
        raise TypeError(
            "transfers must be an iterable of SettlementTransfer values"
        ) from None

    if any(not isinstance(transfer, SettlementTransfer) for transfer in transfer_tuple):
        raise TypeError("transfers must contain only SettlementTransfer values")

    deltas = {seat: 0 for seat in Seat}
    for transfer in transfer_tuple:
        deltas[transfer.payer] -= transfer.amount
        deltas[transfer.recipient] += transfer.amount

    return SeatPoints.from_mapping(deltas)


def _validate_winner_settlement_context(
    winner: WinningPlayerResult,
    *,
    dealer_seat: Seat,
    rules: RuleSet,
) -> None:
    expected_seat_wind = _seat_wind(winner.seat, dealer_seat)
    if winner.context.seat_wind is not expected_seat_wind:
        raise ValueError("dealer_seat must match winner context seat_wind")

    if any(
        candidate.score.rules != rules
        for candidate in winner.score_selection.candidates
    ):
        raise ValueError(
            "every score candidate must have been evaluated with settlement rules"
        )


def _seat_wind(seat: Seat, dealer_seat: Seat) -> Wind:
    seats = tuple(Seat)
    winds = tuple(Wind)
    distance = (seats.index(seat) - seats.index(dealer_seat)) % len(seats)
    return winds[distance]


def _score_payments(
    winner: WinningPlayerResult,
) -> tuple[int | None, int | None, int | None]:
    payments = {
        (
            candidate.score.ron_payment,
            candidate.score.tsumo_dealer_payment,
            candidate.score.tsumo_non_dealer_payment,
        )
        for candidate in winner.score_selection.max_score_candidates
    }
    if len(payments) != 1:
        raise ValueError("maximum score candidates must have identical payments")
    return next(iter(payments))


def _single_ron_transfers(
    result: WinResult,
    winner: WinningPlayerResult,
    *,
    honba: int,
    rules: RuleSet,
) -> tuple[SettlementTransfer, ...]:
    source_seat = result.source_seat
    assert source_seat is not None

    ron_payment, _, _ = _score_payments(winner)
    assert ron_payment is not None

    transfers = [
        SettlementTransfer(
            source_seat,
            winner.seat,
            ron_payment,
            TransferReason.RON,
            winner.seat,
        )
    ]

    honba_points = honba * rules.ron_honba_points
    if honba_points:
        transfers.append(
            SettlementTransfer(
                source_seat,
                winner.seat,
                honba_points,
                TransferReason.HONBA,
                winner.seat,
            )
        )

    return tuple(transfers)


def _single_tsumo_transfers(
    winner: WinningPlayerResult,
    *,
    dealer_seat: Seat,
    honba: int,
    rules: RuleSet,
) -> tuple[SettlementTransfer, ...]:
    _, dealer_payment, non_dealer_payment = _score_payments(winner)

    honba_payment = honba * rules.tsumo_honba_points_per_payer
    transfers = []

    for payer in Seat:
        if payer is winner.seat:
            continue

        payment = dealer_payment if payer is dealer_seat else non_dealer_payment
        assert payment is not None

        transfers.append(
            SettlementTransfer(
                payer,
                winner.seat,
                payment,
                TransferReason.TSUMO,
                winner.seat,
            )
        )

        if honba_payment:
            transfers.append(
                SettlementTransfer(
                    payer,
                    winner.seat,
                    honba_payment,
                    TransferReason.HONBA,
                    winner.seat,
                )
            )

    return tuple(transfers)
