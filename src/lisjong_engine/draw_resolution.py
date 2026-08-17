"""九種九牌・途中流局・荒牌流局・流し満貫をpureに判定するmodule。

`RoundState` / `PlayerState` / `Wall`のmutable objectは受け取らない。
orchestration層が確定済みfactを最小限のimmutable値へコピーし、本moduleが
麻雀ルール上の成立可否とterminal factの構築を一貫して行う。

判定は`RuleSet`の具体的なfieldだけを見て行い、preset名では分岐しない。
"""

from collections.abc import Iterable, Mapping

from lisjong_engine.discard import Discard
from lisjong_engine.round_result import (
    AbortiveDrawReason,
    AbortiveDrawResult,
    ExhaustiveDrawResult,
)
from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile, TileCategory, TileType


def nine_terminals_eligible(hand_tiles: Iterable[Tile]) -> bool:
    """手牌が九種九牌の必要条件（么九牌9種類以上）を満たすかを返す。

    役・立直等の判定は行わない。呼び出し側が、ルール有効・第一巡条件を
    別途確認したうえで利用する。
    """
    terminal_or_honor_types = {
        tile.tile_type
        for tile in hand_tiles
        if tile.tile_type.category is TileCategory.HONOR
        or tile.tile_type.rank in (1, 9)
    }
    return len(terminal_or_honor_types) >= 9


def first_discard_abortive_draw(
    *,
    four_winds_enabled: bool,
    four_riichi_enabled: bool,
    has_meld_occurred: bool,
    discard_tile_types_by_seat: Mapping[Seat, tuple[TileType, ...]],
    riichi_established_by_seat: Mapping[Seat, bool],
) -> AbortiveDrawResult | None:
    """打牌がロン・鳴きなしで解決した直後に判定する途中流局。

    四風連打を四家立直より先に判定する。この優先順位は`python-study`の
    `_first_discard_abortive_draw()`が持つ既存契約をそのまま引き継いだ
    ものであり、本moduleが新たに考案したものではない。
    """
    if (
        four_winds_enabled
        and not has_meld_occurred
        and len(discard_tile_types_by_seat) == 4
        and all(len(types) == 1 for types in discard_tile_types_by_seat.values())
    ):
        first_types = {types[0] for types in discard_tile_types_by_seat.values()}
        if len(first_types) == 1:
            tile_type = next(iter(first_types))
            if tile_type.category is TileCategory.HONOR and tile_type.rank <= 4:
                return AbortiveDrawResult(AbortiveDrawReason.FOUR_WINDS)

    if (
        four_riichi_enabled
        and len(riichi_established_by_seat) == 4
        and all(riichi_established_by_seat.values())
    ):
        return AbortiveDrawResult(AbortiveDrawReason.FOUR_RIICHI)

    return None


def four_kans_abortive_draw(
    *,
    enabled: bool,
    quad_counts_by_seat: Mapping[Seat, int],
) -> AbortiveDrawResult | None:
    """槓が実際に確定した直後に判定する四槓散了。

    複数playerの合計槓子数が4に達した場合だけ成立する。1playerが単独で
    4つの槓子を持つ場合は、四槓子の役の目があるため対象にしない。
    """
    total_quads = sum(quad_counts_by_seat.values())
    owners_with_quads = sum(1 for count in quad_counts_by_seat.values() if count > 0)
    if enabled and total_quads == 4 and owners_with_quads > 1:
        return AbortiveDrawResult(AbortiveDrawReason.FOUR_KANS)
    return None


def is_nagashi_mangan_river(discards: Iterable[Discard]) -> bool:
    """河がすべて么九牌かつ一枚も鳴かれていないかを返す。

    空の河は流し満貫として扱わない。
    """
    discards = tuple(discards)
    return bool(discards) and all(
        discard.called_by is None
        and (
            discard.tile.tile_type.category is TileCategory.HONOR
            or discard.tile.tile_type.rank in (1, 9)
        )
        for discard in discards
    )


def build_exhaustive_draw_result(
    *,
    tenpai_by_seat: Mapping[Seat, bool],
    discards_by_seat: Mapping[Seat, tuple[Discard, ...]],
    nagashi_mangan_enabled: bool,
) -> ExhaustiveDrawResult:
    """荒牌流局のterminal factを、席別のtenpai・河のfactから構築する。

    tenpaiはルール上のsemantic tenpai（和了形へ到達できる待ちの有無）を
    表す既に確定済みの真偽値を受け取るだけであり、本関数自体は向聴・
    受け入れ等を計算しない。
    """
    tenpai_seats = tuple(seat for seat in Seat if tenpai_by_seat.get(seat, False))
    nagashi_mangan_seats = tuple(
        seat
        for seat in Seat
        if nagashi_mangan_enabled
        and is_nagashi_mangan_river(discards_by_seat.get(seat, ()))
    )
    return ExhaustiveDrawResult(
        tenpai_seats=tenpai_seats,
        nagashi_mangan_seats=nagashi_mangan_seats,
    )
