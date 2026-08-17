from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from lisjong_engine.meld import Ankan, Daiminkan, Kakan, Pon
from lisjong_engine.points import SeatPoints
from lisjong_engine.riichi_event import RiichiContribution
from lisjong_engine.round_result import (
    AbortiveDrawReason,
    AbortiveDrawResult,
    ExhaustiveDrawResult,
    RoundResult,
    WinningPlayerResult,
    WinResult,
)
from lisjong_engine.rules import (
    FinalRankTiePolicy,
    MultipleRonAwardPolicy,
    PaoCompoundYakumanPolicy,
    RonResolutionPolicy,
    RuleSet,
)
from lisjong_engine.score import calculate_score
from lisjong_engine.seat import Seat
from lisjong_engine.tile import TileCategory, TileType
from lisjong_engine.win_context import WinMethod
from lisjong_engine.wind import Wind
from lisjong_engine.yaku import Yaku

_SEAT_ORDER = tuple(Seat)


def _normalize_riichi_contributions(
    contributions: Iterable[RiichiContribution],
    rules: RuleSet,
) -> tuple[RiichiContribution, ...]:
    try:
        normalized = tuple(contributions)
    except TypeError:
        raise TypeError(
            "riichi_contributions must be an iterable of RiichiContribution values"
        ) from None

    if any(
        not isinstance(contribution, RiichiContribution) for contribution in normalized
    ):
        raise TypeError(
            "riichi_contributions must contain only RiichiContribution values"
        )

    seats = tuple(contribution.seat for contribution in normalized)
    if len(set(seats)) != len(seats):
        raise ValueError("riichi contribution seats must be unique within a round")

    if any(
        contribution.points != rules.riichi_stick_points for contribution in normalized
    ):
        raise ValueError(
            "riichi contribution points must match rules.riichi_stick_points"
        )

    return tuple(
        sorted(
            normalized,
            key=lambda item: _SEAT_ORDER.index(item.seat),
        )
    )


def _round_riichi_stick_awards(
    result: WinResult,
    *,
    riichi_sticks: int,
    rules: RuleSet,
) -> tuple[RiichiStickAward, ...]:
    if riichi_sticks == 0:
        return ()

    if len(result.winners) == 1:
        recipient = result.winners[0].seat
    else:
        recipient = _multiple_ron_riichi_stick_award_seat(
            result,
            rules,
        )

    return (
        RiichiStickAward(
            recipient,
            riichi_sticks * rules.riichi_stick_points,
        ),
    )


def _multiple_ron_riichi_stick_award_seat(
    result: WinResult,
    rules: RuleSet,
) -> Seat:
    if len(result.winners) == 1:
        return result.winners[0].seat

    if (
        rules.multiple_ron_riichi_stick_policy
        is not MultipleRonAwardPolicy.NEAREST_WINNER_TO_DISCARDER
    ):
        raise ValueError("unsupported multiple-ron riichi stick policy")

    source_seat = result.source_seat
    assert source_seat is not None

    winner_seats = frozenset(winner.seat for winner in result.winners)
    ordered_winners = _ordered_seats_after(
        source_seat,
        winner_seats,
    )
    if not ordered_winners:
        raise ValueError("multiple ron must have a riichi stick award recipient")

    return ordered_winners[0]


def _noten_penalty_transfers(
    result: ExhaustiveDrawResult,
    rules: RuleSet,
) -> tuple[SettlementTransfer, ...]:
    tenpai_seats = frozenset(result.tenpai_seats)
    tenpai_count = len(tenpai_seats)

    if tenpai_count in (0, rules.player_count):
        return ()

    noten_seats = tuple(seat for seat in _SEAT_ORDER if seat not in tenpai_seats)
    recipients = tuple(seat for seat in _SEAT_ORDER if seat in tenpai_seats)

    total = rules.noten_penalty_total

    if total % len(noten_seats):
        raise ValueError("noten penalty total must be divisible among noten seats")
    if total % len(recipients):
        raise ValueError("noten penalty total must be divisible among tenpai seats")

    payer_total = total // len(noten_seats)
    recipient_total = total // len(recipients)

    base_amount, remainder_per_payer = divmod(
        payer_total,
        len(recipients),
    )

    amounts = {
        (payer, recipient): base_amount
        for payer in noten_seats
        for recipient in recipients
    }

    remaining_by_recipient = {
        recipient: recipient_total - base_amount * len(noten_seats)
        for recipient in recipients
    }

    for payer in noten_seats:
        remainder = remainder_per_payer
        for recipient in _ordered_seats_after(
            payer,
            tenpai_seats,
        ):
            if remainder == 0:
                break
            if remaining_by_recipient[recipient] == 0:
                continue

            amounts[(payer, recipient)] += 1
            remaining_by_recipient[recipient] -= 1
            remainder -= 1

        if remainder:
            raise ValueError("noten penalty remainder cannot be distributed")

    if any(remaining_by_recipient.values()):
        raise ValueError("noten penalty recipient totals are inconsistent")

    transfers = []
    for payer in noten_seats:
        for recipient in _ordered_seats_after(
            payer,
            tenpai_seats,
        ):
            amount = amounts[(payer, recipient)]
            if amount:
                transfers.append(
                    SettlementTransfer(
                        payer,
                        recipient,
                        amount,
                        TransferReason.NOTEN_PENALTY,
                    )
                )

    return tuple(transfers)


def _nagashi_mangan_transfers(
    result: ExhaustiveDrawResult,
    *,
    dealer_seat: Seat,
    rules: RuleSet,
) -> tuple[SettlementTransfer, ...]:
    transfers = []

    for winner_seat in _SEAT_ORDER:
        if winner_seat not in result.nagashi_mangan_seats:
            continue

        score = calculate_score(
            han=5,
            fu=20,
            method=WinMethod.TSUMO,
            is_dealer=winner_seat is dealer_seat,
            rules=rules,
        )

        for payer_seat in _SEAT_ORDER:
            if payer_seat is winner_seat:
                continue

            payment = (
                score.tsumo_dealer_payment
                if payer_seat is dealer_seat
                else score.tsumo_non_dealer_payment
            )
            assert payment is not None

            transfers.append(
                SettlementTransfer(
                    payer_seat,
                    winner_seat,
                    payment,
                    TransferReason.NAGASHI_MANGAN,
                    winner_seat,
                )
            )

    return tuple(transfers)


def _ordered_seats_after(
    origin: Seat,
    target_seats: frozenset[Seat],
) -> tuple[Seat, ...]:
    origin_index = _SEAT_ORDER.index(origin)

    return tuple(
        seat
        for distance in range(1, len(_SEAT_ORDER))
        if (seat := _SEAT_ORDER[(origin_index + distance) % len(_SEAT_ORDER)])
        in target_seats
    )


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
    """和了のplayer間transferをパオを含めて計算する。"""
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
        dealer_seat=dealer_seat,
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
    """single-winner和了のplayer間transferを計算する。"""
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


def calculate_exhaustive_draw_settlement_transfers(
    result: ExhaustiveDrawResult,
    *,
    dealer_seat: Seat | None = None,
    rules: RuleSet | None = None,
) -> tuple[SettlementTransfer, ...]:
    """通常流局のnoten penaltyまたは流し満貫transferを計算する。"""
    if not isinstance(result, ExhaustiveDrawResult):
        raise TypeError("result must be an ExhaustiveDrawResult")
    if dealer_seat is not None and not isinstance(dealer_seat, Seat):
        raise TypeError("dealer_seat must be a Seat or None")

    if rules is None:
        rules = RuleSet.default()
    elif not isinstance(rules, RuleSet):
        raise TypeError("rules must be a RuleSet")

    if result.nagashi_mangan_seats:
        if not rules.nagashi_mangan_enabled:
            raise ValueError("nagashi mangan is disabled by the rules")
        if dealer_seat is None:
            raise ValueError("dealer_seat is required for nagashi mangan settlement")
        return _nagashi_mangan_transfers(
            result,
            dealer_seat=dealer_seat,
            rules=rules,
        )

    return _noten_penalty_transfers(result, rules)


def calculate_abortive_draw_settlement_transfers(
    result: AbortiveDrawResult,
    *,
    rules: RuleSet | None = None,
) -> tuple[SettlementTransfer, ...]:
    """途中流局のplayer間transferを返す。

    途中流局そのものには通常のplayer間点数移動はない。
    成立済みriichi contributionは上位RoundSettlementで別途扱う。
    """
    if not isinstance(result, AbortiveDrawResult):
        raise TypeError("result must be an AbortiveDrawResult")

    if rules is None:
        rules = RuleSet.default()
    elif not isinstance(rules, RuleSet):
        raise TypeError("rules must be a RuleSet")

    enabled = {
        AbortiveDrawReason.NINE_TERMINALS: (rules.nine_terminals_abortive_draw_enabled),
        AbortiveDrawReason.FOUR_WINDS: (rules.four_winds_abortive_draw_enabled),
        AbortiveDrawReason.FOUR_KANS: (rules.four_kans_abortive_draw_enabled),
        AbortiveDrawReason.FOUR_RIICHI: (rules.four_riichi_abortive_draw_enabled),
        AbortiveDrawReason.TRIPLE_RON: rules.triple_ron_abortive_draw,
    }[result.reason]

    if not enabled:
        raise ValueError("abortive draw reason is disabled by the rules")

    return ()


def calculate_round_settlement(
    result: RoundResult,
    *,
    dealer_seat: Seat,
    honba: int = 0,
    riichi_sticks_before: int = 0,
    riichi_contributions: Iterable[RiichiContribution] = (),
    rules: RuleSet | None = None,
) -> RoundSettlement:
    """終了した1局のfactから完全な局精算をpureに計算する。"""
    if not isinstance(
        result,
        (WinResult, ExhaustiveDrawResult, AbortiveDrawResult),
    ):
        raise TypeError("result must be a RoundResult")
    if not isinstance(dealer_seat, Seat):
        raise TypeError("dealer_seat must be a Seat")
    if type(honba) is not int:
        raise TypeError("honba must be an int")
    if honba < 0:
        raise ValueError("honba must be non-negative")
    if type(riichi_sticks_before) is not int:
        raise TypeError("riichi_sticks_before must be an int")
    if riichi_sticks_before < 0:
        raise ValueError("riichi_sticks_before must be non-negative")

    if rules is None:
        rules = RuleSet.default()
    elif not isinstance(rules, RuleSet):
        raise TypeError("rules must be a RuleSet")

    contributions = _normalize_riichi_contributions(
        riichi_contributions,
        rules,
    )
    available_riichi_sticks = riichi_sticks_before + len(contributions)

    if isinstance(result, WinResult):
        transfers = calculate_win_settlement_transfers(
            result,
            dealer_seat=dealer_seat,
            honba=honba,
            rules=rules,
        )
        awards = _round_riichi_stick_awards(
            result,
            riichi_sticks=available_riichi_sticks,
            rules=rules,
        )
        riichi_sticks_after = 0
    elif isinstance(result, ExhaustiveDrawResult):
        transfers = calculate_exhaustive_draw_settlement_transfers(
            result,
            dealer_seat=dealer_seat,
            rules=rules,
        )
        awards = ()
        riichi_sticks_after = available_riichi_sticks
    else:
        transfers = calculate_abortive_draw_settlement_transfers(
            result,
            rules=rules,
        )
        awards = ()
        riichi_sticks_after = available_riichi_sticks

    point_deltas = _derive_round_point_deltas(
        transfers,
        contributions,
        awards,
    )

    settlement = RoundSettlement(
        point_deltas=point_deltas,
        transfers=transfers,
        riichi_contributions=contributions,
        riichi_stick_awards=awards,
        riichi_sticks_after=riichi_sticks_after,
    )

    pot_value_delta = (
        riichi_sticks_after - riichi_sticks_before
    ) * rules.riichi_stick_points

    if settlement.point_deltas.total + pot_value_delta != 0:
        raise ValueError(
            "round settlement must preserve player points plus riichi pot value"
        )

    return settlement


def calculate_final_riichi_stick_awards(
    scores: SeatPoints,
    riichi_sticks: int,
    *,
    rules: RuleSet | None = None,
) -> tuple[RiichiStickAward, ...]:
    """半荘終了確定後に残存riichi sticksを最終1位席群へ配分する。"""
    if not isinstance(scores, SeatPoints):
        raise TypeError("scores must be SeatPoints")
    if type(riichi_sticks) is not int:
        raise TypeError("riichi_sticks must be an int")
    if riichi_sticks < 0:
        raise ValueError("riichi_sticks must be non-negative")

    if rules is None:
        rules = RuleSet.default()
    elif not isinstance(rules, RuleSet):
        raise TypeError("rules must be a RuleSet")

    if riichi_sticks == 0:
        return ()

    top_seats = _final_top_seats(scores, rules)
    total_amount = riichi_sticks * rules.riichi_stick_points

    if len(top_seats) == 1:
        return (
            RiichiStickAward(
                top_seats[0],
                total_amount,
            ),
        )

    if total_amount % 100:
        raise ValueError("riichi stick amount must be expressible in 100-point units")

    total_units = total_amount // 100
    quotient, remainder = divmod(
        total_units,
        len(top_seats),
    )

    return tuple(
        RiichiStickAward(
            seat,
            (quotient + (1 if index < remainder else 0)) * 100,
        )
        for index, seat in enumerate(top_seats)
    )


def _final_top_seats(
    scores: SeatPoints,
    rules: RuleSet,
) -> tuple[Seat, ...]:
    top_score = max(scores[seat] for seat in Seat)

    if rules.final_rank_tie_policy is FinalRankTiePolicy.SEAT_ORDER:
        return (next(seat for seat in _SEAT_ORDER if scores[seat] == top_score),)

    if rules.final_rank_tie_policy is FinalRankTiePolicy.SPLIT_RANK_POINTS:
        return tuple(seat for seat in _SEAT_ORDER if scores[seat] == top_score)

    raise ValueError("unsupported final rank tie policy")


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


@dataclass(frozen=True)
class _PaoResponsibility:
    seat: Seat
    yaku: Yaku
    responsible_units: int
    total_units: int

    @property
    def other_units(self) -> int:
        return self.total_units - self.responsible_units


def _winner_points(winner: WinningPlayerResult) -> int:
    points = {
        candidate.winner_points
        for candidate in winner.score_selection.max_score_candidates
    }
    if len(points) != 1:
        raise ValueError("maximum score candidates must have identical winner points")
    return next(iter(points))


def _meld_tile_type(
    meld: Pon | Daiminkan | Kakan | Ankan,
) -> TileType:
    if isinstance(meld, Ankan):
        return meld.tiles[0].tile_type
    return meld.called_tile.tile_type


def _pao_trigger_seat(
    target_yaku: Yaku,
    winner: WinningPlayerResult,
) -> Seat | None:
    context = winner.context
    declared_melds = context.declared_melds

    if target_yaku is Yaku.SUUKANTSU:
        kan_melds = tuple(
            meld
            for meld in declared_melds
            if isinstance(meld, (Ankan, Daiminkan, Kakan))
        )
        if len(kan_melds) != 4:
            return None
        return context.suukantsu_pao_seat

    if target_yaku is Yaku.DAISANGEN:
        target_ranks = frozenset({5, 6, 7})
        required_meld_count = 3
    elif target_yaku is Yaku.DAISUUSHII:
        target_ranks = frozenset({1, 2, 3, 4})
        required_meld_count = 4
    else:
        raise ValueError("unsupported pao yaku")

    completed_groups = tuple(
        meld
        for meld in declared_melds
        if isinstance(meld, (Pon, Daiminkan, Kakan, Ankan))
        and _meld_tile_type(meld).category is TileCategory.HONOR
        and _meld_tile_type(meld).rank in target_ranks
    )

    if len(completed_groups) != required_meld_count:
        return None

    last_group = completed_groups[-1]
    if isinstance(last_group, Ankan):
        return None

    return last_group.source_seat


def _pao_responsibility(
    winner: WinningPlayerResult,
    rules: RuleSet,
) -> _PaoResponsibility | None:
    if not rules.pao_enabled:
        return None

    facts: set[tuple[Yaku | None, Seat | None, int, int]] = set()

    for candidate in winner.score_selection.max_score_candidates:
        evaluation = candidate.hand_value.yaku_evaluation
        pao_matches = tuple(
            match for match in evaluation.matches if match.yaku in rules.pao_yaku
        )

        target_yakus = frozenset(match.yaku for match in pao_matches)

        if len(target_yakus) > 1:
            raise ValueError("a winner cannot have multiple pao responsibilities")

        if not target_yakus:
            facts.add((None, None, 0, 0))
            continue

        target_yaku = next(iter(target_yakus))
        responsible_units = sum(
            match.yakuman_units for match in pao_matches if match.yaku is target_yaku
        )
        total_units = evaluation.yakuman_units
        responsible_seat = _pao_trigger_seat(
            target_yaku,
            winner,
        )

        facts.add(
            (
                target_yaku,
                responsible_seat,
                responsible_units,
                total_units,
            )
        )

    if len(facts) != 1:
        raise ValueError(
            "maximum score candidates must have identical "
            "pao target, responsibility, and yakuman split"
        )

    (
        target_yaku,
        responsible_seat,
        responsible_units,
        total_units,
    ) = next(iter(facts))

    if target_yaku is None or responsible_seat is None:
        return None

    if responsible_seat is winner.seat:
        raise ValueError("a winner cannot be their own pao payer")
    if responsible_units <= 0:
        raise ValueError("pao responsibility must contain yakuman units")
    if total_units < responsible_units:
        raise ValueError("pao yakuman split is inconsistent")

    other_units = total_units - responsible_units
    if (
        rules.pao_compound_yakuman_policy
        is PaoCompoundYakumanPolicy.RESPONSIBLE_YAKUMAN_ONLY
        and other_units
        and not rules.multiple_yakuman_enabled
    ):
        raise ValueError(
            "cannot split compound pao yakuman when multiple yakuman is disabled"
        )

    return _PaoResponsibility(
        responsible_seat,
        target_yaku,
        responsible_units,
        total_units,
    )


def _pao_ron_component_transfers(
    *,
    source_seat: Seat,
    pao_seat: Seat,
    winner_seat: Seat,
    amount: int,
) -> tuple[SettlementTransfer, ...]:
    if pao_seat is source_seat:
        return (
            SettlementTransfer(
                source_seat,
                winner_seat,
                amount,
                TransferReason.PAO_RON,
                winner_seat,
            ),
        )

    if amount % 2:
        raise ValueError("pao ron payment must be divisible by two")

    half = amount // 2
    return (
        SettlementTransfer(
            source_seat,
            winner_seat,
            half,
            TransferReason.RON,
            winner_seat,
        ),
        SettlementTransfer(
            pao_seat,
            winner_seat,
            half,
            TransferReason.PAO_RON,
            winner_seat,
        ),
    )


def _pao_ron_base_transfers(
    winner: WinningPlayerResult,
    *,
    source_seat: Seat,
    dealer_seat: Seat,
    responsibility: _PaoResponsibility,
    rules: RuleSet,
) -> tuple[SettlementTransfer, ...]:
    ron_payment, _, _ = _score_payments(winner)
    assert ron_payment is not None

    if (
        rules.pao_compound_yakuman_policy is PaoCompoundYakumanPolicy.FULL_HAND
        or responsibility.other_units == 0
    ):
        return _pao_ron_component_transfers(
            source_seat=source_seat,
            pao_seat=responsibility.seat,
            winner_seat=winner.seat,
            amount=ron_payment,
        )

    responsible_score = calculate_score(
        han=0,
        fu=None,
        method=WinMethod.RON,
        is_dealer=winner.seat is dealer_seat,
        yakuman_units=responsibility.responsible_units,
        rules=rules,
    )
    other_score = calculate_score(
        han=0,
        fu=None,
        method=WinMethod.RON,
        is_dealer=winner.seat is dealer_seat,
        yakuman_units=responsibility.other_units,
        rules=rules,
    )

    responsible_payment = responsible_score.ron_payment
    other_payment = other_score.ron_payment
    assert responsible_payment is not None
    assert other_payment is not None

    if responsible_payment + other_payment != ron_payment:
        raise ValueError("split pao ron payments must match evaluated score")

    transfers = list(
        _pao_ron_component_transfers(
            source_seat=source_seat,
            pao_seat=responsibility.seat,
            winner_seat=winner.seat,
            amount=responsible_payment,
        )
    )
    transfers.append(
        SettlementTransfer(
            source_seat,
            winner.seat,
            other_payment,
            TransferReason.RON,
            winner.seat,
        )
    )
    return tuple(transfers)


def _ron_transfers(
    result: WinResult,
    *,
    dealer_seat: Seat,
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
        responsibility = _pao_responsibility(
            winner,
            rules,
        )

        if responsibility is None:
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
        else:
            transfers.extend(
                _pao_ron_base_transfers(
                    winner,
                    source_seat=source_seat,
                    dealer_seat=dealer_seat,
                    responsibility=responsibility,
                    rules=rules,
                )
            )

    honba_points = honba * rules.ron_honba_points
    if honba_points:
        award_seat = _multiple_ron_honba_award_seat(
            result,
            rules,
        )
        award_winner = next(
            winner for winner in result.winners if winner.seat is award_seat
        )
        responsibility = _pao_responsibility(
            award_winner,
            rules,
        )
        honba_payer = responsibility.seat if responsibility is not None else source_seat

        transfers.append(
            SettlementTransfer(
                honba_payer,
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


def _pao_tsumo_transfers(
    winner: WinningPlayerResult,
    *,
    dealer_seat: Seat,
    honba: int,
    responsibility: _PaoResponsibility,
    rules: RuleSet,
) -> tuple[SettlementTransfer, ...]:
    winner_points = _winner_points(winner)

    honba_points = honba * rules.tsumo_honba_points_per_payer * (rules.player_count - 1)

    if (
        rules.pao_compound_yakuman_policy is PaoCompoundYakumanPolicy.FULL_HAND
        or responsibility.other_units == 0
    ):
        transfers = [
            SettlementTransfer(
                responsibility.seat,
                winner.seat,
                winner_points,
                TransferReason.PAO_TSUMO,
                winner.seat,
            )
        ]

        if honba_points:
            transfers.append(
                SettlementTransfer(
                    responsibility.seat,
                    winner.seat,
                    honba_points,
                    TransferReason.HONBA,
                    winner.seat,
                )
            )

        return tuple(transfers)

    responsible_score = calculate_score(
        han=0,
        fu=None,
        method=WinMethod.TSUMO,
        is_dealer=winner.seat is dealer_seat,
        yakuman_units=responsibility.responsible_units,
        rules=rules,
    )
    other_score = calculate_score(
        han=0,
        fu=None,
        method=WinMethod.TSUMO,
        is_dealer=winner.seat is dealer_seat,
        yakuman_units=responsibility.other_units,
        rules=rules,
    )

    if responsible_score.winner_points + other_score.winner_points != winner_points:
        raise ValueError("split pao tsumo payments must match evaluated score")

    transfers = [
        SettlementTransfer(
            responsibility.seat,
            winner.seat,
            responsible_score.winner_points,
            TransferReason.PAO_TSUMO,
            winner.seat,
        )
    ]

    if honba_points:
        transfers.append(
            SettlementTransfer(
                responsibility.seat,
                winner.seat,
                honba_points,
                TransferReason.HONBA,
                winner.seat,
            )
        )

    for payer in _SEAT_ORDER:
        if payer is winner.seat:
            continue

        payment = (
            other_score.tsumo_dealer_payment
            if payer is dealer_seat
            else other_score.tsumo_non_dealer_payment
        )
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

    return tuple(transfers)


def _single_tsumo_transfers(
    winner: WinningPlayerResult,
    *,
    dealer_seat: Seat,
    honba: int,
    rules: RuleSet,
) -> tuple[SettlementTransfer, ...]:
    responsibility = _pao_responsibility(
        winner,
        rules,
    )
    if responsibility is not None:
        return _pao_tsumo_transfers(
            winner,
            dealer_seat=dealer_seat,
            honba=honba,
            responsibility=responsibility,
            rules=rules,
        )

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
