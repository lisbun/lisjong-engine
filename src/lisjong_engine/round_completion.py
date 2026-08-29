"""局・半荘の終了時点で公開してよいfactだけを保持する、player-safeなcontract。

`CompletedRound` / `CompletedMatch`（`match_state.py`）は監査可能なengine
内部recordであり、`RoundRandomProvenance`やmatch全体の`history`等、
player-facing frontendへそのまま渡すべきでない情報を含む。本moduleは、
その内部recordから必要最小限のplayer-visible factだけをwhitelist方式で
射影する。

内部型の構造を無理にすべて再現せず、Human Play consumerが安全に表示・
session orchestrationできるfactに絞る。和了詳細は確定済み得点候補を
player-safeな値へ射影し、同点の最高得点候補を欠落させずdeterministicな
順序で公開する。未公開の裏表示牌や物理牌identityは公開しない。
"""

from dataclasses import dataclass
from enum import Enum

from lisjong_engine.match_state import CompletedMatch, CompletedRound, MatchEndReason
from lisjong_engine.public_state import (
    PublicMeld,
    PublicTile,
    SeatPointDelta,
    SeatScore,
    public_meld,
    public_tile,
)
from lisjong_engine.round_result import (
    AbortiveDrawReason,
    AbortiveDrawResult,
    ExhaustiveDrawResult,
    WinningPlayerResult,
    WinResult,
)
from lisjong_engine.score import ScoreLimit
from lisjong_engine.seat import Seat
from lisjong_engine.settlement import TransferReason
from lisjong_engine.win_context import RiichiStatus, WinMethod
from lisjong_engine.wind import Wind
from lisjong_engine.winning_score import WinningScoreCandidate
from lisjong_engine.yaku import Yaku

_SEAT_ORDER = tuple(Seat)


class RoundOutcomeKind(Enum):
    WIN = "win"
    EXHAUSTIVE_DRAW = "exhaustive_draw"
    ABORTIVE_DRAW = "abortive_draw"


@dataclass(frozen=True)
class RoundCompletionYaku:
    """成立済み役のplayer-safeな表示metadata。"""

    yaku: Yaku
    japanese_name: str
    han: int | None = None
    yakuman_units: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.yaku, Yaku):
            raise TypeError("yaku must be a Yaku")
        if not isinstance(self.japanese_name, str):
            raise TypeError("japanese_name must be a str")
        if not self.japanese_name:
            raise ValueError("japanese_name must not be empty")
        for name in ("han", "yakuman_units"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError(f"{name} must be a positive int or None")
        if (self.han is None) == (self.yakuman_units is None):
            raise ValueError("exactly one of han and yakuman_units must be present")


@dataclass(frozen=True)
class RoundCompletionDoraCount:
    """確定済みドラ内訳のplayer-safeな値。"""

    visible: int = 0
    ura: int = 0
    red: int = 0
    kan: int = 0
    kan_ura: int = 0

    def __post_init__(self) -> None:
        for name in ("visible", "ura", "red", "kan", "kan_ura"):
            value = getattr(self, name)
            if type(value) is not int:
                raise TypeError(f"{name} must be an int")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True, kw_only=True)
class RoundCompletionScoreCandidate:
    """最高得点となる1つの和了解釈を表示するplayer-safeな値。"""

    yaku: tuple[RoundCompletionYaku, ...]
    total_han: int | None
    rounded_fu: int | None
    yakuman_units: int | None
    dora_count: RoundCompletionDoraCount | None
    score_limit: ScoreLimit
    ron_payment: int | None
    tsumo_dealer_payment: int | None
    tsumo_non_dealer_payment: int | None

    def __post_init__(self) -> None:
        yaku = _typed_tuple(self.yaku, RoundCompletionYaku, "yaku")
        if not yaku:
            raise ValueError("yaku must not be empty")
        for name in ("total_han", "rounded_fu", "yakuman_units"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError(f"{name} must be a positive int or None")
        if self.dora_count is not None and not isinstance(
            self.dora_count, RoundCompletionDoraCount
        ):
            raise TypeError("dora_count must be a RoundCompletionDoraCount or None")
        if not isinstance(self.score_limit, ScoreLimit):
            raise TypeError("score_limit must be a ScoreLimit")
        for name in (
            "ron_payment",
            "tsumo_dealer_payment",
            "tsumo_non_dealer_payment",
        ):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError(f"{name} must be a positive int or None")

        is_yakuman = self.yakuman_units is not None
        if is_yakuman:
            if self.total_han is not None or self.rounded_fu is not None:
                raise ValueError("yakuman candidates must not carry han or fu")
            if self.dora_count is not None:
                raise ValueError("yakuman candidates must not carry dora counts")
            if any(item.yakuman_units is None for item in yaku):
                raise ValueError("yakuman candidates must contain only yakuman yaku")
            if sum(item.yakuman_units or 0 for item in yaku) != self.yakuman_units:
                raise ValueError("yaku units must match candidate yakuman_units")
            if self.score_limit is not ScoreLimit.YAKUMAN:
                raise ValueError("explicit yakuman candidates require YAKUMAN limit")
        else:
            if self.total_han is None or self.rounded_fu is None:
                raise ValueError("normal candidates require total_han and rounded_fu")
            if any(item.han is None for item in yaku):
                raise ValueError("normal candidates must contain only normal yaku")
            dora_han = (
                0
                if self.dora_count is None
                else sum(
                    getattr(self.dora_count, name)
                    for name in ("visible", "ura", "red", "kan", "kan_ura")
                )
            )
            expected_han = sum(item.han or 0 for item in yaku) + dora_han
            if expected_han != self.total_han:
                raise ValueError("yaku and dora must match total_han")

        if self.ron_payment is not None:
            if (
                self.tsumo_dealer_payment is not None
                or self.tsumo_non_dealer_payment is not None
            ):
                raise ValueError("ron candidates must not carry tsumo payments")
        elif self.tsumo_non_dealer_payment is None:
            raise ValueError("tsumo candidates require a non-dealer payment")

        object.__setattr__(self, "yaku", yaku)


@dataclass(frozen=True)
class RoundCompletionWinner:
    seat: Seat
    win_method: WinMethod
    winning_tile: PublicTile | None = None
    concealed_tiles: tuple[PublicTile, ...] = ()
    declared_melds: tuple[PublicMeld, ...] = ()
    max_score_candidates: tuple[RoundCompletionScoreCandidate, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.win_method, WinMethod):
            raise TypeError("win_method must be a WinMethod")
        concealed_tiles = _typed_tuple(
            self.concealed_tiles, PublicTile, "concealed_tiles"
        )
        declared_melds = _typed_tuple(self.declared_melds, PublicMeld, "declared_melds")
        max_score_candidates = _typed_tuple(
            self.max_score_candidates,
            RoundCompletionScoreCandidate,
            "max_score_candidates",
        )
        if self.winning_tile is not None and not isinstance(
            self.winning_tile, PublicTile
        ):
            raise TypeError("winning_tile must be a PublicTile or None")
        if self.winning_tile is None:
            if concealed_tiles or declared_melds or max_score_candidates:
                raise ValueError("legacy winners must not carry partial detail")
        else:
            if not concealed_tiles:
                raise ValueError("detailed winners require concealed_tiles")
            if self.winning_tile not in concealed_tiles:
                raise ValueError("winning_tile must be present in concealed_tiles")
            if not max_score_candidates:
                raise ValueError("detailed winners require max_score_candidates")
            for candidate in max_score_candidates:
                if self.win_method is WinMethod.RON and candidate.ron_payment is None:
                    raise ValueError("ron winners require ron candidate payments")
                if (
                    self.win_method is WinMethod.TSUMO
                    and candidate.ron_payment is not None
                ):
                    raise ValueError("tsumo winners require tsumo candidate payments")
        object.__setattr__(self, "concealed_tiles", concealed_tiles)
        object.__setattr__(self, "declared_melds", declared_melds)
        object.__setattr__(self, "max_score_candidates", max_score_candidates)


@dataclass(frozen=True)
class RoundCompletionDoraIndicators:
    """局終了時にtable-publicとなった表示牌だけのsnapshot。"""

    visible: tuple[PublicTile, ...] = ()
    kan: tuple[PublicTile, ...] = ()
    ura: tuple[PublicTile, ...] = ()
    kan_ura: tuple[PublicTile, ...] = ()

    def __post_init__(self) -> None:
        for name in ("visible", "kan", "ura", "kan_ura"):
            object.__setattr__(
                self,
                name,
                _typed_tuple(getattr(self, name), PublicTile, name),
            )


@dataclass(frozen=True)
class RoundCompletionSettlementTransfer:
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
        if type(self.amount) is not int or self.amount <= 0:
            raise ValueError("amount must be a positive int")
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
class RoundCompletionRiichiStickAward:
    recipient: Seat
    amount: int

    def __post_init__(self) -> None:
        if not isinstance(self.recipient, Seat):
            raise TypeError("recipient must be a Seat")
        if type(self.amount) is not int or self.amount <= 0:
            raise ValueError("amount must be a positive int")


@dataclass(frozen=True, kw_only=True)
class RoundCompletionFact:
    """1局が終了し精算が確定した後の、player-safeなimmutable記録。"""

    prevailing_wind: Wind
    hand_number: int
    dealer_seat: Seat
    honba: int
    outcome: RoundOutcomeKind
    winners: tuple[RoundCompletionWinner, ...] = ()
    source_seat: Seat | None = None
    tenpai_seats: tuple[Seat, ...] = ()
    nagashi_mangan_seats: tuple[Seat, ...] = ()
    abortive_reason: AbortiveDrawReason | None = None
    revealed_dora_indicators: RoundCompletionDoraIndicators | None = None
    settlement_transfers: tuple[RoundCompletionSettlementTransfer, ...] = ()
    riichi_stick_awards: tuple[RoundCompletionRiichiStickAward, ...] = ()
    point_deltas: tuple[SeatPointDelta, ...]
    scores_after: tuple[SeatScore, ...]
    dealer_continues: bool
    has_next_round: bool

    def __post_init__(self) -> None:
        if not isinstance(self.prevailing_wind, Wind):
            raise TypeError("prevailing_wind must be a Wind")
        if type(self.hand_number) is not int:
            raise TypeError("hand_number must be an int")
        if not isinstance(self.dealer_seat, Seat):
            raise TypeError("dealer_seat must be a Seat")
        if type(self.honba) is not int:
            raise TypeError("honba must be an int")
        if not isinstance(self.outcome, RoundOutcomeKind):
            raise TypeError("outcome must be a RoundOutcomeKind")

        winners = _typed_tuple(self.winners, RoundCompletionWinner, "winners")
        tenpai_seats = _typed_seat_tuple(self.tenpai_seats, "tenpai_seats")
        nagashi_mangan_seats = _typed_seat_tuple(
            self.nagashi_mangan_seats, "nagashi_mangan_seats"
        )
        point_deltas = _typed_tuple(self.point_deltas, SeatPointDelta, "point_deltas")
        scores_after = _typed_tuple(self.scores_after, SeatScore, "scores_after")
        settlement_transfers = _typed_tuple(
            self.settlement_transfers,
            RoundCompletionSettlementTransfer,
            "settlement_transfers",
        )
        riichi_stick_awards = _typed_tuple(
            self.riichi_stick_awards,
            RoundCompletionRiichiStickAward,
            "riichi_stick_awards",
        )

        if self.source_seat is not None and not isinstance(self.source_seat, Seat):
            raise TypeError("source_seat must be a Seat or None")
        if self.abortive_reason is not None and not isinstance(
            self.abortive_reason, AbortiveDrawReason
        ):
            raise TypeError("abortive_reason must be an AbortiveDrawReason or None")
        if type(self.dealer_continues) is not bool:
            raise TypeError("dealer_continues must be a bool")
        if type(self.has_next_round) is not bool:
            raise TypeError("has_next_round must be a bool")
        if self.revealed_dora_indicators is not None and not isinstance(
            self.revealed_dora_indicators, RoundCompletionDoraIndicators
        ):
            raise TypeError(
                "revealed_dora_indicators must be a "
                "RoundCompletionDoraIndicators or None"
            )

        if tuple(delta.seat for delta in point_deltas) != _SEAT_ORDER:
            raise ValueError(
                "point_deltas must contain exactly all four seats in order"
            )
        if tuple(score.seat for score in scores_after) != _SEAT_ORDER:
            raise ValueError(
                "scores_after must contain exactly all four seats in order"
            )

        winner_seats = tuple(winner.seat for winner in winners)
        if len(set(winner_seats)) != len(winner_seats):
            raise ValueError("winners must not contain duplicate seats")

        if self.outcome is RoundOutcomeKind.WIN:
            if not winners:
                raise ValueError("a win outcome requires at least one winner")
            if tenpai_seats or nagashi_mangan_seats:
                raise ValueError("a win outcome must not carry exhaustive draw seats")
            if self.abortive_reason is not None:
                raise ValueError("a win outcome must not carry an abortive_reason")
        else:
            if winners:
                raise ValueError("only a win outcome may carry winners")
            if self.source_seat is not None:
                raise ValueError("only a win outcome may carry a source_seat")
            if self.outcome is RoundOutcomeKind.EXHAUSTIVE_DRAW:
                if self.abortive_reason is not None:
                    raise ValueError(
                        "an exhaustive draw outcome must not carry an abortive_reason"
                    )
            else:
                if tenpai_seats or nagashi_mangan_seats:
                    raise ValueError(
                        "an abortive draw outcome must not carry exhaustive draw seats"
                    )
                if self.abortive_reason is None:
                    raise ValueError(
                        "an abortive draw outcome requires an abortive_reason"
                    )
            if self.revealed_dora_indicators is not None:
                raise ValueError("only a win outcome may carry dora indicators")

        object.__setattr__(self, "winners", winners)
        object.__setattr__(self, "tenpai_seats", tenpai_seats)
        object.__setattr__(self, "nagashi_mangan_seats", nagashi_mangan_seats)
        object.__setattr__(self, "point_deltas", point_deltas)
        object.__setattr__(self, "scores_after", scores_after)
        object.__setattr__(self, "settlement_transfers", settlement_transfers)
        object.__setattr__(self, "riichi_stick_awards", riichi_stick_awards)


@dataclass(frozen=True)
class SeatFinalResult:
    """半荘終了時の1席分の、player-visibleな最終結果。"""

    seat: Seat
    rank: int
    final_points: int

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if type(self.rank) is not int:
            raise TypeError("rank must be an int")
        if not 1 <= self.rank <= 4:
            raise ValueError("rank must be between 1 and 4")
        if type(self.final_points) is not int:
            raise TypeError("final_points must be an int")


@dataclass(frozen=True, kw_only=True)
class MatchCompletionFact:
    """半荘終了時の、player-safeなimmutable最終結果。"""

    end_reason: MatchEndReason
    final_scores: tuple[SeatScore, ...]
    final_results: tuple[SeatFinalResult, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.end_reason, MatchEndReason):
            raise TypeError("end_reason must be a MatchEndReason")

        final_scores = _typed_tuple(self.final_scores, SeatScore, "final_scores")
        final_results = _typed_tuple(
            self.final_results, SeatFinalResult, "final_results"
        )
        if tuple(score.seat for score in final_scores) != _SEAT_ORDER:
            raise ValueError(
                "final_scores must contain exactly all four seats in order"
            )
        result_seats = tuple(result.seat for result in final_results)
        if len(set(result_seats)) != len(result_seats):
            raise ValueError("final_results must not contain duplicate seats")
        if frozenset(result_seats) != frozenset(_SEAT_ORDER):
            raise ValueError("final_results must contain exactly all four seats")

        object.__setattr__(self, "final_scores", final_scores)
        object.__setattr__(self, "final_results", final_results)


def project_round_completion(completed_round: CompletedRound) -> RoundCompletionFact:
    """`CompletedRound`から、player-safeな`RoundCompletionFact`を構築する。"""
    if not isinstance(completed_round, CompletedRound):
        raise TypeError("completed_round must be a CompletedRound")

    position = completed_round.position_before
    result = completed_round.result

    (
        outcome,
        winners,
        source_seat,
        tenpai_seats,
        nagashi_mangan_seats,
        abortive_reason,
    ) = _decompose_result(result)

    point_deltas = tuple(
        SeatPointDelta(seat, completed_round.settlement.point_deltas[seat])
        for seat in _SEAT_ORDER
    )
    scores_after = tuple(
        SeatScore(seat, completed_round.scores_after_settlement[seat])
        for seat in _SEAT_ORDER
    )
    revealed_dora_indicators = (
        _project_revealed_dora_indicators(result)
        if isinstance(result, WinResult)
        else None
    )
    settlement_transfers = tuple(
        RoundCompletionSettlementTransfer(
            transfer.payer,
            transfer.recipient,
            transfer.amount,
            transfer.reason,
            transfer.winner_seat,
        )
        for transfer in completed_round.settlement.transfers
    )
    riichi_stick_awards = tuple(
        RoundCompletionRiichiStickAward(award.recipient, award.amount)
        for award in completed_round.settlement.riichi_stick_awards
    )

    return RoundCompletionFact(
        prevailing_wind=position.prevailing_wind,
        hand_number=position.hand_number,
        dealer_seat=position.dealer_seat,
        honba=position.honba,
        outcome=outcome,
        winners=winners,
        source_seat=source_seat,
        tenpai_seats=tenpai_seats,
        nagashi_mangan_seats=nagashi_mangan_seats,
        abortive_reason=abortive_reason,
        revealed_dora_indicators=revealed_dora_indicators,
        settlement_transfers=settlement_transfers,
        riichi_stick_awards=riichi_stick_awards,
        point_deltas=point_deltas,
        scores_after=scores_after,
        dealer_continues=completed_round.dealer_continues,
        has_next_round=completed_round.next_position is not None,
    )


def project_match_completion(completed_match: CompletedMatch) -> MatchCompletionFact:
    """`CompletedMatch`から、player-safeな`MatchCompletionFact`を構築する。"""
    if not isinstance(completed_match, CompletedMatch):
        raise TypeError("completed_match must be a CompletedMatch")

    final_scores = tuple(
        SeatScore(seat, completed_match.final_raw_scores[seat]) for seat in _SEAT_ORDER
    )
    # `FinalScoreCalculation.players`は標準競技順位で既に検証済みの
    # deterministicな順序を持つため、そのまま踏襲する。
    final_results = tuple(
        SeatFinalResult(
            seat=player.seat,
            rank=player.rank,
            final_points=player.final_points,
        )
        for player in completed_match.final_score.players
    )

    return MatchCompletionFact(
        end_reason=completed_match.end_reason,
        final_scores=final_scores,
        final_results=final_results,
    )


def _decompose_result(
    result: object,
) -> tuple[
    RoundOutcomeKind,
    tuple[RoundCompletionWinner, ...],
    Seat | None,
    tuple[Seat, ...],
    tuple[Seat, ...],
    AbortiveDrawReason | None,
]:
    if isinstance(result, WinResult):
        winners = tuple(
            sorted(
                (_project_winner(winner, result.method) for winner in result.winners),
                key=lambda winner: _SEAT_ORDER.index(winner.seat),
            )
        )
        return (RoundOutcomeKind.WIN, winners, result.source_seat, (), (), None)
    if isinstance(result, ExhaustiveDrawResult):
        tenpai_seats = tuple(
            seat for seat in _SEAT_ORDER if seat in result.tenpai_seats
        )
        nagashi_mangan_seats = tuple(
            seat for seat in _SEAT_ORDER if seat in result.nagashi_mangan_seats
        )
        return (
            RoundOutcomeKind.EXHAUSTIVE_DRAW,
            (),
            None,
            tenpai_seats,
            nagashi_mangan_seats,
            None,
        )
    if isinstance(result, AbortiveDrawResult):
        return (RoundOutcomeKind.ABORTIVE_DRAW, (), None, (), (), result.reason)
    raise TypeError("result must be a RoundResult")


def _project_winner(
    winner: WinningPlayerResult,
    win_method: WinMethod,
) -> RoundCompletionWinner:
    context = winner.context
    concealed_tiles = tuple(
        sorted(
            (public_tile(tile) for tile in context.concealed_tiles),
            key=_public_tile_sort_key,
        )
    )
    candidates = tuple(
        sorted(
            (
                _project_score_candidate(candidate)
                for candidate in winner.score_selection.max_score_candidates
            ),
            key=_score_candidate_sort_key,
        )
    )
    return RoundCompletionWinner(
        seat=winner.seat,
        win_method=win_method,
        winning_tile=public_tile(context.winning_tile),
        concealed_tiles=concealed_tiles,
        declared_melds=tuple(public_meld(meld) for meld in context.declared_melds),
        max_score_candidates=candidates,
    )


def _project_score_candidate(
    candidate: WinningScoreCandidate,
) -> RoundCompletionScoreCandidate:
    hand_value = candidate.hand_value
    score = candidate.score
    evaluation = hand_value.yaku_evaluation
    if score.yakuman_units:
        if evaluation.yakuman_units != score.yakuman_units:
            raise ValueError("score yakuman_units must match yaku evaluation")
    else:
        fu = hand_value.fu_calculation
        if hand_value.total_han != score.han:
            raise ValueError("score han must match hand value total_han")
        if fu is None or fu.rounded_fu != score.fu:
            raise ValueError("score fu must match hand value rounded_fu")

    dora = hand_value.dora_count
    return RoundCompletionScoreCandidate(
        yaku=tuple(
            sorted(
                (
                    RoundCompletionYaku(
                        yaku=match.yaku,
                        japanese_name=match.japanese_name,
                        han=match.han or None,
                        yakuman_units=match.yakuman_units or None,
                    )
                    for match in evaluation.matches
                ),
                key=lambda item: tuple(Yaku).index(item.yaku),
            )
        ),
        total_han=None if score.yakuman_units else score.han,
        rounded_fu=score.fu,
        yakuman_units=score.yakuman_units or None,
        dora_count=(
            None
            if dora is None
            else RoundCompletionDoraCount(
                visible=dora.visible,
                ura=dora.ura,
                red=dora.red,
                kan=dora.kan,
                kan_ura=dora.kan_ura,
            )
        ),
        score_limit=score.limit,
        ron_payment=score.ron_payment,
        tsumo_dealer_payment=score.tsumo_dealer_payment,
        tsumo_non_dealer_payment=score.tsumo_non_dealer_payment,
    )


def _project_revealed_dora_indicators(
    result: WinResult,
) -> RoundCompletionDoraIndicators:
    indicators = result.dora_indicators
    reveal_ura = any(
        winner.context.riichi_status
        in (RiichiStatus.RIICHI, RiichiStatus.DOUBLE_RIICHI)
        for winner in result.winners
    )
    return RoundCompletionDoraIndicators(
        visible=tuple(public_tile(tile) for tile in indicators.visible),
        kan=tuple(public_tile(tile) for tile in indicators.kan),
        ura=(tuple(public_tile(tile) for tile in indicators.ura) if reveal_ura else ()),
        kan_ura=(
            tuple(public_tile(tile) for tile in indicators.kan_ura)
            if reveal_ura
            else ()
        ),
    )


def _public_tile_sort_key(tile: PublicTile) -> tuple[int, bool]:
    return (tile.tile_type.id, tile.is_red)


def _score_candidate_sort_key(candidate: RoundCompletionScoreCandidate) -> tuple:
    dora = candidate.dora_count
    return (
        tuple(
            (
                item.yaku.value,
                item.japanese_name,
                item.han or 0,
                item.yakuman_units or 0,
            )
            for item in candidate.yaku
        ),
        candidate.total_han or 0,
        candidate.rounded_fu or 0,
        candidate.yakuman_units or 0,
        (
            (-1, -1, -1, -1, -1)
            if dora is None
            else (dora.visible, dora.ura, dora.red, dora.kan, dora.kan_ura)
        ),
        candidate.score_limit.value,
        candidate.ron_payment or 0,
        candidate.tsumo_dealer_payment or 0,
        candidate.tsumo_non_dealer_payment or 0,
    )


def _typed_tuple(values, expected_type: type, field_name: str) -> tuple:
    try:
        normalized = tuple(values)
    except TypeError:
        raise TypeError(f"{field_name} must be an iterable") from None
    if any(not isinstance(value, expected_type) for value in normalized):
        raise TypeError(
            f"{field_name} must contain only {expected_type.__name__} values"
        )
    return normalized


def _typed_seat_tuple(values, field_name: str) -> tuple[Seat, ...]:
    normalized = _typed_tuple(values, Seat, field_name)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must not contain duplicate seats")
    return normalized
