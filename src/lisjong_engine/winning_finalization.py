"""和了claimをimmutableなscoring inputとterminal resultへ変換するpure module。

``RoundState`` / ``PlayerState`` / ``Wall``のmutable objectは受け取らない。
orchestration層が確定済みfactを``WinningClaim``と``DoraIndicatorState``へ
コピーし、本moduleが``WinningContext``・得点評価・``WinResult``を一貫して
構築する。
"""

from collections.abc import Iterable
from dataclasses import dataclass

from lisjong_engine.dora import DoraIndicators
from lisjong_engine.meld import Meld
from lisjong_engine.round_result import WinningPlayerResult, WinResult
from lisjong_engine.rules import RuleSet
from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile
from lisjong_engine.win_context import (
    RiichiStatus,
    WinMethod,
    WinningContext,
    WinOrigin,
)
from lisjong_engine.wind import Wind
from lisjong_engine.winning_score import (
    enumerate_winning_score_candidates,
    evaluate_winning_scores,
)


@dataclass(frozen=True)
class WinningClaim:
    """1席の和了評価に必要な、局進行側で確定済みの最小fact。"""

    seat: Seat
    concealed_tiles: tuple[Tile, ...]
    winning_tile: Tile
    method: WinMethod
    origin: WinOrigin
    seat_wind: Wind
    prevailing_wind: Wind
    declared_melds: tuple[Meld, ...] = ()
    riichi_status: RiichiStatus = RiichiStatus.NONE
    is_ippatsu: bool = False
    is_last_tile: bool = False
    is_first_uninterrupted_turn: bool = False
    suukantsu_pao_seat: Seat | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        try:
            concealed_tiles = tuple(self.concealed_tiles)
            declared_melds = tuple(self.declared_melds)
        except TypeError:
            raise TypeError("claim tile and meld fields must be iterable") from None
        if any(not isinstance(tile, Tile) for tile in concealed_tiles):
            raise TypeError("concealed_tiles must contain only Tile values")
        if any(not isinstance(meld, Meld) for meld in declared_melds):
            raise TypeError("declared_melds must contain only Meld values")
        object.__setattr__(self, "concealed_tiles", concealed_tiles)
        object.__setattr__(self, "declared_melds", declared_melds)

        if not isinstance(self.winning_tile, Tile):
            raise TypeError("winning_tile must be a Tile")
        if not isinstance(self.method, WinMethod):
            raise TypeError("method must be a WinMethod")
        if not isinstance(self.origin, WinOrigin):
            raise TypeError("origin must be a WinOrigin")
        if not isinstance(self.seat_wind, Wind):
            raise TypeError("seat_wind must be a Wind")
        if not isinstance(self.prevailing_wind, Wind):
            raise TypeError("prevailing_wind must be a Wind")
        if not isinstance(self.riichi_status, RiichiStatus):
            raise TypeError("riichi_status must be a RiichiStatus")
        if any(
            type(value) is not bool
            for value in (
                self.is_ippatsu,
                self.is_last_tile,
                self.is_first_uninterrupted_turn,
            )
        ):
            raise TypeError("winning claim flags must be bools")
        if self.suukantsu_pao_seat is not None and not isinstance(
            self.suukantsu_pao_seat, Seat
        ):
            raise TypeError("suukantsu_pao_seat must be a Seat or None")
        winning_tile_is_held = any(
            tile.id == self.winning_tile.id for tile in concealed_tiles
        )
        if self.method is WinMethod.TSUMO and not winning_tile_is_held:
            raise ValueError("a tsumo winning tile must be in concealed_tiles")
        if self.method is WinMethod.RON and winning_tile_is_held:
            raise ValueError(
                "a ron winning tile must not already be in concealed_tiles"
            )


@dataclass(frozen=True)
class DoraIndicatorState:
    """scoring用snapshotを作るための、Wallからコピーしたindicator fact。"""

    dora_indicator_tiles: tuple[Tile, ...] = ()
    ura_dora_indicator_tiles: tuple[Tile, ...] = ()
    revealed_dora_indicator_count: int = 0
    pending_kan_dora_reveal_seats: tuple[Seat, ...] = ()

    def __post_init__(self) -> None:
        try:
            dora = tuple(self.dora_indicator_tiles)
            ura = tuple(self.ura_dora_indicator_tiles)
            pending = tuple(self.pending_kan_dora_reveal_seats)
        except TypeError:
            raise TypeError("indicator state collections must be iterable") from None
        if any(not isinstance(tile, Tile) for tile in (*dora, *ura)):
            raise TypeError("indicator collections must contain only Tile values")
        if len(dora) != len(ura):
            raise ValueError("dora and ura indicator regions must correspond")
        if any(not isinstance(seat, Seat) for seat in pending):
            raise TypeError("pending reveal seats must contain only Seat values")
        if type(self.revealed_dora_indicator_count) is not int:
            raise TypeError("revealed_dora_indicator_count must be an int")
        if not 0 <= self.revealed_dora_indicator_count <= len(dora):
            raise ValueError("revealed dora indicator count is outside the wall region")
        if bool(dora) is not bool(self.revealed_dora_indicator_count):
            raise ValueError("a dead wall starts with exactly one revealed indicator")

        object.__setattr__(self, "dora_indicator_tiles", dora)
        object.__setattr__(self, "ura_dora_indicator_tiles", ura)
        object.__setattr__(self, "pending_kan_dora_reveal_seats", pending)


def build_winning_context(claim: WinningClaim) -> WinningContext:
    """claimからscoring layerの正本である``WinningContext``を構築する。"""
    if not isinstance(claim, WinningClaim):
        raise TypeError("claim must be a WinningClaim")
    concealed_tiles = (
        (*claim.concealed_tiles, claim.winning_tile)
        if claim.method is WinMethod.RON
        else claim.concealed_tiles
    )
    return WinningContext(
        concealed_tiles=concealed_tiles,
        winning_tile=claim.winning_tile,
        method=claim.method,
        origin=claim.origin,
        seat_wind=claim.seat_wind,
        prevailing_wind=claim.prevailing_wind,
        declared_melds=claim.declared_melds,
        riichi_status=claim.riichi_status,
        is_ippatsu=claim.is_ippatsu,
        is_last_tile=claim.is_last_tile,
        is_first_uninterrupted_turn=claim.is_first_uninterrupted_turn,
        suukantsu_pao_seat=claim.suukantsu_pao_seat,
    )


def build_effective_dora_indicators(
    claim: WinningClaim,
    indicator_state: DoraIndicatorState,
) -> DoraIndicators:
    """claimのoriginに対して得点上有効なindicator領域を意味的に構築する。

    公開済み槓ドラは全claimで有効である。未公開の遅延大明槓ドラは、
    その大明槓を行った席自身の嶺上ツモだけへ追加し、Ronへは追加しない。
    Wallの公開数やpending factは変更しない。
    """
    if not isinstance(claim, WinningClaim):
        raise TypeError("claim must be a WinningClaim")
    if not isinstance(indicator_state, DoraIndicatorState):
        raise TypeError("indicator_state must be a DoraIndicatorState")

    if not indicator_state.dora_indicator_tiles:
        return DoraIndicators()

    kan_stop = indicator_state.revealed_dora_indicator_count
    if claim.method is WinMethod.TSUMO and claim.origin is WinOrigin.RINSHAN:
        kan_stop += sum(
            seat is claim.seat for seat in indicator_state.pending_kan_dora_reveal_seats
        )
    if kan_stop > len(indicator_state.dora_indicator_tiles):
        raise ValueError("effective kan dora indicators exceed the wall region")

    return DoraIndicators(
        visible=indicator_state.dora_indicator_tiles[:1],
        ura=indicator_state.ura_dora_indicator_tiles[:1],
        kan=indicator_state.dora_indicator_tiles[1:kan_stop],
        kan_ura=indicator_state.ura_dora_indicator_tiles[1:kan_stop],
    )


def has_winning_score(
    claim: WinningClaim,
    indicator_state: DoraIndicatorState,
    rules: RuleSet,
) -> bool:
    """合法手probe用。得点候補が無い・入力が不整合ならFalseを返す。"""
    try:
        context = build_winning_context(claim)
        indicators = build_effective_dora_indicators(claim, indicator_state)
        return bool(
            enumerate_winning_score_candidates(
                context,
                dora_indicators=indicators,
                rules=rules,
            )
        )
    except TypeError, ValueError:
        return False


def build_win_result(
    claims: Iterable[WinningClaim],
    indicator_state: DoraIndicatorState,
    rules: RuleSet,
    *,
    source_seat: Seat | None = None,
) -> WinResult:
    """claim群をstrictに再評価し、immutableな``WinResult``を返す。"""
    try:
        claim_values = tuple(claims)
    except TypeError:
        raise TypeError("claims must be iterable") from None
    if not claim_values:
        raise ValueError("claims must not be empty")
    if any(not isinstance(claim, WinningClaim) for claim in claim_values):
        raise TypeError("claims must contain only WinningClaim values")
    if not isinstance(rules, RuleSet):
        raise TypeError("rules must be a RuleSet")

    first = claim_values[0]
    indicators = build_effective_dora_indicators(first, indicator_state)
    winners = []
    for claim in claim_values:
        claim_indicators = build_effective_dora_indicators(claim, indicator_state)
        if claim_indicators != indicators:
            raise ValueError("all winners in one result must share indicator facts")
        context = build_winning_context(claim)
        winners.append(
            WinningPlayerResult(
                seat=claim.seat,
                context=context,
                score_selection=evaluate_winning_scores(
                    context,
                    dora_indicators=indicators,
                    rules=rules,
                ),
            )
        )

    return WinResult(
        method=first.method,
        origin=first.origin,
        winning_tile=first.winning_tile,
        winners=tuple(winners),
        source_seat=source_seat,
        dora_indicators=indicators,
        is_last_tile=first.is_last_tile,
    )
