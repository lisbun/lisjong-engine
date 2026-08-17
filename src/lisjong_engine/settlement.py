from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from lisjong_engine.points import SeatPoints
from lisjong_engine.riichi_event import RiichiContribution
from lisjong_engine.round_result import WinningPlayerResult, WinResult
from lisjong_engine.rules import (
    MultipleRonAwardPolicy,
    RonResolutionPolicy,
    RuleSet,
)
from lisjong_engine.seat import Seat
from lisjong_engine.win_context import WinMethod
from lisjong_engine.wind import Wind

_SEAT_ORDER = tuple(Seat)


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


@dataclass(frozen=True)
class RoundSettlement:
    """1局終了時の点数精算を表すimmutableかつ監査可能な結果。

    ``point_deltas`` はplayer間transfer、成立した立直供託、
    riichi stick awardから導出できる値でなければならない。

    ``riichi_sticks_after`` は精算後に卓上へ残る供託棒の本数。
    供託棒の増減そのものの保存則は、精算前本数とRuleSetを入力に持つ
    上位のcalculate_round_settlement()で検証する。
    """

    point_deltas: SeatPoints
    transfers: tuple[SettlementTransfer, ...] = ()
    riichi_contributions: tuple[RiichiContribution, ...] = ()
    riichi_stick_awards: tuple[RiichiStickAward, ...] = ()
    riichi_sticks_after: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.point_deltas, SeatPoints):
            raise TypeError("point_deltas must be SeatPoints")

        try:
            transfers = tuple(self.transfers)
        except TypeError:
            raise TypeError(
                "transfers must be an iterable of SettlementTransfer values"
            ) from None
        if any(not isinstance(item, SettlementTransfer) for item in transfers):
            raise TypeError("transfers must contain only SettlementTransfer values")

        try:
            contributions = tuple(self.riichi_contributions)
        except TypeError:
            raise TypeError(
                "riichi_contributions must be an iterable of RiichiContribution values"
            ) from None
        if any(not isinstance(item, RiichiContribution) for item in contributions):
            raise TypeError(
                "riichi_contributions must contain only RiichiContribution values"
            )
        contribution_seats = tuple(contribution.seat for contribution in contributions)
        if len(set(contribution_seats)) != len(contribution_seats):
            raise ValueError("riichi contribution seats must be unique within a round")

        try:
            awards = tuple(self.riichi_stick_awards)
        except TypeError:
            raise TypeError(
                "riichi_stick_awards must be an iterable of RiichiStickAward values"
            ) from None
        if any(not isinstance(item, RiichiStickAward) for item in awards):
            raise TypeError(
                "riichi_stick_awards must contain only RiichiStickAward values"
            )

        if type(self.riichi_sticks_after) is not int:
            raise TypeError("riichi_sticks_after must be an int")
        if self.riichi_sticks_after < 0:
            raise ValueError("riichi_sticks_after must be non-negative")

        expected_deltas = _derive_round_point_deltas(
            transfers,
            contributions,
            awards,
        )
        if self.point_deltas != expected_deltas:
            raise ValueError(
                "point_deltas must match transfers, "
                "riichi contributions, and riichi stick awards"
            )

        object.__setattr__(self, "transfers", transfers)
        object.__setattr__(
            self,
            "riichi_contributions",
            contributions,
        )
        object.__setattr__(
            self,
            "riichi_stick_awards",
            awards,
        )


def calculate_win_settlement_transfers(
    result: WinResult,
    *,
    dealer_seat: Seat,
    honba: int = 0,
    rules: RuleSet | None = None,
) -> tuple[SettlementTransfer, ...]:
    """通常（パオなし）の和了player間transferを計算する。"""
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

    winner_count = len(result.winners)
    if winner_count > 3:
        raise ValueError("ron cannot have more than three winners")

    if winner_count > 1:
        if result.method is not WinMethod.RON:
            raise ValueError("multiple winners require ron")
        if rules.ron_resolution_policy is not RonResolutionPolicy.MULTIPLE_RON:
            raise ValueError("multiple ron result contradicts ron resolution policy")
        if not rules.double_ron_enabled:
            raise ValueError("multiple ron is disabled by the rules")
        if winner_count == 3 and rules.triple_ron_abortive_draw:
            raise ValueError("triple ron must be an abortive draw under these rules")

    for winner in result.winners:
        _validate_winner_settlement_context(
            winner,
            dealer_seat=dealer_seat,
            rules=rules,
        )

    if result.method is WinMethod.TSUMO:
        return _single_tsumo_transfers(
            result.winners[0],
            dealer_seat=dealer_seat,
            honba=honba,
            rules=rules,
        )

    return _ron_transfers(
        result,
        honba=honba,
        rules=rules,
    )


def calculate_single_win_settlement_transfers(
    result: WinResult,
    *,
    dealer_seat: Seat,
    honba: int = 0,
    rules: RuleSet | None = None,
) -> tuple[SettlementTransfer, ...]:
    """パオを伴わないsingle-winner和了のplayer間transferを計算する。"""
    if not isinstance(result, WinResult):
        raise TypeError("result must be a WinResult")
    if len(result.winners) != 1:
        raise ValueError("single win settlement requires exactly one winner")

    return calculate_win_settlement_transfers(
        result,
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


def _derive_round_point_deltas(
    transfers: tuple[SettlementTransfer, ...],
    riichi_contributions: tuple[RiichiContribution, ...],
    riichi_stick_awards: tuple[RiichiStickAward, ...],
) -> SeatPoints:
    deltas = aggregate_settlement_transfers(transfers).as_dict()

    for contribution in riichi_contributions:
        deltas[contribution.seat] -= contribution.points

    for award in riichi_stick_awards:
        deltas[award.recipient] += award.amount

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


def _ron_transfers(
    result: WinResult,
    *,
    honba: int,
    rules: RuleSet,
) -> tuple[SettlementTransfer, ...]:
    source_seat = result.source_seat
    assert source_seat is not None

    transfers = []

    for winner in sorted(
        result.winners,
        key=lambda item: _SEAT_ORDER.index(item.seat),
    ):
        ron_payment, _, _ = _score_payments(winner)
        assert ron_payment is not None

        transfers.append(
            SettlementTransfer(
                source_seat,
                winner.seat,
                ron_payment,
                TransferReason.RON,
                winner.seat,
            )
        )

    honba_points = honba * rules.ron_honba_points
    if honba_points:
        award_seat = _multiple_ron_honba_award_seat(
            result,
            rules,
        )
        transfers.append(
            SettlementTransfer(
                source_seat,
                award_seat,
                honba_points,
                TransferReason.HONBA,
                award_seat,
            )
        )

    return tuple(transfers)


def _multiple_ron_honba_award_seat(
    result: WinResult,
    rules: RuleSet,
) -> Seat:
    if len(result.winners) == 1:
        return result.winners[0].seat

    if (
        rules.multiple_ron_honba_policy
        is not MultipleRonAwardPolicy.NEAREST_WINNER_TO_DISCARDER
    ):
        raise ValueError("unsupported multiple-ron honba policy")

    source_seat = result.source_seat
    assert source_seat is not None

    winner_seats = {winner.seat for winner in result.winners}
    source_index = _SEAT_ORDER.index(source_seat)

    return next(
        _SEAT_ORDER[(source_index + distance) % len(_SEAT_ORDER)]
        for distance in range(1, len(_SEAT_ORDER))
        if _SEAT_ORDER[(source_index + distance) % len(_SEAT_ORDER)] in winner_seats
    )


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
