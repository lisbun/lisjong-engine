"""局・半荘の終了時点で公開してよいfactだけを保持する、player-safeなcontract。

`CompletedRound` / `CompletedMatch`（`match_state.py`）は監査可能なengine
内部recordであり、`RoundRandomProvenance`やmatch全体の`history`等、
player-facing frontendへそのまま渡すべきでない情報を含む。本moduleは、
その内部recordから必要最小限のplayer-visible factだけをwhitelist方式で
射影する。

内部型の構造を無理にすべて再現せず、Human Play consumerが安全に表示・
session orchestrationできる最小factに絞る。役・符・ドラ等の得点内訳は、
複数の最高得点候補（`WinningScoreSelection.max_score_candidates`）が
frozensetで同点を保持する契約と衝突しかねないため、本Issueのminimum
scopeには含めない。
"""

from dataclasses import dataclass
from enum import Enum

from lisjong_engine.match_state import CompletedMatch, CompletedRound, MatchEndReason
from lisjong_engine.public_state import SeatPointDelta, SeatScore
from lisjong_engine.round_result import (
    AbortiveDrawReason,
    AbortiveDrawResult,
    ExhaustiveDrawResult,
    WinResult,
)
from lisjong_engine.seat import Seat
from lisjong_engine.win_context import WinMethod
from lisjong_engine.wind import Wind

_SEAT_ORDER = tuple(Seat)


class RoundOutcomeKind(Enum):
    WIN = "win"
    EXHAUSTIVE_DRAW = "exhaustive_draw"
    ABORTIVE_DRAW = "abortive_draw"


@dataclass(frozen=True)
class RoundCompletionWinner:
    seat: Seat
    win_method: WinMethod

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.win_method, WinMethod):
            raise TypeError("win_method must be a WinMethod")


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

        object.__setattr__(self, "winners", winners)
        object.__setattr__(self, "tenpai_seats", tenpai_seats)
        object.__setattr__(self, "nagashi_mangan_seats", nagashi_mangan_seats)
        object.__setattr__(self, "point_deltas", point_deltas)
        object.__setattr__(self, "scores_after", scores_after)


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
                (
                    RoundCompletionWinner(winner.seat, result.method)
                    for winner in result.winners
                ),
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
