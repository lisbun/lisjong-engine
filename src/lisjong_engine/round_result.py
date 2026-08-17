"""Immutable facts describing how one round ended.

This module deliberately does not perform point settlement or mutate match state.
It records the terminal facts that later settlement logic needs without asking it
to reinterpret the completed round.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from lisjong_engine.dora import DoraIndicators
from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile
from lisjong_engine.win_context import WinMethod, WinningContext, WinOrigin
from lisjong_engine.wind import Wind
from lisjong_engine.winning_score import WinningScoreSelection


@dataclass(frozen=True)
class WinningPlayerResult:
    """The immutable winning evaluation selected for one player."""

    seat: Seat
    context: WinningContext
    score_selection: WinningScoreSelection

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.context, WinningContext):
            raise TypeError("context must be a WinningContext")
        if not isinstance(self.score_selection, WinningScoreSelection):
            raise TypeError("score_selection must be a WinningScoreSelection")

        expected_is_dealer = self.context.seat_wind is Wind.EAST
        for candidate in self.score_selection.candidates:
            if candidate.score.method is not self.context.method:
                raise ValueError("score candidate method must match context.method")
            if candidate.score.is_dealer is not expected_is_dealer:
                raise ValueError(
                    "score candidate dealer status must match context.seat_wind"
                )


@dataclass(frozen=True)
class WinResult:
    """Terminal facts for a tsumo or one-or-more-winner ron result.

    ``dora_indicators`` is the effective indicator snapshot used to evaluate this
    win. Constructing that snapshot is intentionally outside this value object.
    """

    method: WinMethod
    origin: WinOrigin
    winning_tile: Tile
    winners: tuple[WinningPlayerResult, ...]
    dora_indicators: DoraIndicators
    source_seat: Seat | None = None
    is_last_tile: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.method, WinMethod):
            raise TypeError("method must be a WinMethod")
        if not isinstance(self.origin, WinOrigin):
            raise TypeError("origin must be a WinOrigin")
        if not isinstance(self.winning_tile, Tile):
            raise TypeError("winning_tile must be a Tile")

        try:
            winners = tuple(self.winners)
        except TypeError:
            raise TypeError("winners must be iterable") from None
        if not winners:
            raise ValueError("winners must not be empty")
        if any(not isinstance(winner, WinningPlayerResult) for winner in winners):
            raise TypeError("winners must contain only WinningPlayerResult values")
        winner_seats = tuple(winner.seat for winner in winners)
        if len(set(winner_seats)) != len(winner_seats):
            raise ValueError("winner seats must be unique")
        object.__setattr__(self, "winners", winners)

        if self.source_seat is not None and not isinstance(self.source_seat, Seat):
            raise TypeError("source_seat must be a Seat or None")
        if not isinstance(self.dora_indicators, DoraIndicators):
            raise TypeError("dora_indicators must be a DoraIndicators")
        if not isinstance(self.is_last_tile, bool):
            raise TypeError("is_last_tile must be a bool")

        if self.method is WinMethod.TSUMO:
            if self.origin not in (WinOrigin.LIVE_WALL, WinOrigin.RINSHAN):
                raise ValueError("tsumo origin must be LIVE_WALL or RINSHAN")
            if len(winners) != 1:
                raise ValueError("tsumo must have exactly one winner")
            if self.source_seat is not None:
                raise ValueError("tsumo must not have a source_seat")
        else:
            if self.origin not in (
                WinOrigin.DISCARD,
                WinOrigin.KAKAN,
                WinOrigin.ANKAN,
            ):
                raise ValueError("ron origin must be DISCARD, KAKAN, or ANKAN")
            if self.source_seat is None:
                raise ValueError("ron must have a source_seat")
            if self.source_seat in winner_seats:
                raise ValueError("source_seat must not be a winning seat")

        for winner in winners:
            context = winner.context
            if context.method is not self.method:
                raise ValueError("winner context method must match result method")
            if context.origin is not self.origin:
                raise ValueError("winner context origin must match result origin")
            if context.winning_tile != self.winning_tile:
                raise ValueError("winner context winning_tile must match result")
            if context.is_last_tile is not self.is_last_tile:
                raise ValueError("winner context is_last_tile must match result")


def _normalized_seats(name: str, values: Iterable[Seat]) -> tuple[Seat, ...]:
    try:
        seats = tuple(values)
    except TypeError:
        raise TypeError(f"{name} must be iterable") from None
    if any(not isinstance(seat, Seat) for seat in seats):
        raise TypeError(f"{name} must contain only Seat values")
    if len(set(seats)) != len(seats):
        raise ValueError(f"{name} must not contain duplicate seats")
    return seats


@dataclass(frozen=True)
class ExhaustiveDrawResult:
    """Terminal facts for an exhaustive draw, including nagashi mangan seats."""

    tenpai_seats: tuple[Seat, ...] = ()
    nagashi_mangan_seats: tuple[Seat, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tenpai_seats",
            _normalized_seats("tenpai_seats", self.tenpai_seats),
        )
        object.__setattr__(
            self,
            "nagashi_mangan_seats",
            _normalized_seats("nagashi_mangan_seats", self.nagashi_mangan_seats),
        )


class AbortiveDrawReason(Enum):
    """Typed reasons for an abortive draw supported by the engine rules."""

    NINE_TERMINALS = "nine_terminals"
    FOUR_WINDS = "four_winds"
    FOUR_KANS = "four_kans"
    FOUR_RIICHI = "four_riichi"
    TRIPLE_RON = "triple_ron"


@dataclass(frozen=True)
class AbortiveDrawResult:
    """Terminal facts for an abortive draw."""

    reason: AbortiveDrawReason

    def __post_init__(self) -> None:
        if not isinstance(self.reason, AbortiveDrawReason):
            raise TypeError("reason must be an AbortiveDrawReason")


RoundResult: TypeAlias = WinResult | ExhaustiveDrawResult | AbortiveDrawResult
