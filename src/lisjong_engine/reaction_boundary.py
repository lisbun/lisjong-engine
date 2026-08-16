"""打牌後に反応windowが必要かどうかを安全に検知するpure moduleである。

E1は反応の解決を実装しない。しかし、反応が起こり得る局面を無視して
次turnへ進めることもしない。本moduleは「反応候補が存在し得るか」だけを
判定し、存在し得る場合は`RoundState`を`AWAITING_REACTIONS`で停止させる。

判定はfail-safeな過大評価とする。役の有無、フリテン、立直中の制限等は
検査せず、必要条件だけを見る。したがって、

- 実際には成立しない反応を存在と判定する（false positive）ことはある
- 成立し得る反応を見落とす（false negative）ことはない

という非対称な安全性を持つ。反応候補の完全な生成、選択、priority解決、
複数反応の解決はE2の責務であり、本moduleでは扱わない。
"""

from collections.abc import Mapping

from lisjong_engine.meld import Meld
from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile, TileCategory
from lisjong_engine.winning import is_winning_shape

_CHI_RANK_OFFSETS = ((-2, -1), (-1, 1), (1, 2))


def has_possible_reaction(
    *,
    discarder: Seat,
    discarded_tile: Tile,
    hand_tiles_by_seat: Mapping[Seat, tuple[Tile, ...]],
    melds_by_seat: Mapping[Seat, tuple[Meld, ...]],
    remaining_count: int,
    can_draw_rinshan: bool,
) -> bool:
    """打牌に対する反応候補が存在し得るかを返す。"""
    if not isinstance(discarder, Seat):
        raise TypeError("discarder must be a Seat")
    if not isinstance(discarded_tile, Tile):
        raise TypeError("discarded_tile must be a Tile")
    if type(remaining_count) is not int:
        raise TypeError("remaining_count must be an int")
    if remaining_count < 0:
        raise ValueError("remaining_count must not be negative")
    if type(can_draw_rinshan) is not bool:
        raise TypeError("can_draw_rinshan must be a bool")

    next_seat = discarder.next()
    for seat in Seat:
        if seat is discarder:
            continue

        hand_tiles = tuple(hand_tiles_by_seat.get(seat, ()))
        melds = tuple(melds_by_seat.get(seat, ()))
        if _may_ron(hand_tiles, melds, discarded_tile):
            return True
        if _may_call(
            hand_tiles,
            discarded_tile,
            is_next_seat=(seat is next_seat),
            remaining_count=remaining_count,
            can_draw_rinshan=can_draw_rinshan,
        ):
            return True

    return False


def _may_ron(
    hand_tiles: tuple[Tile, ...],
    melds: tuple[Meld, ...],
    discarded_tile: Tile,
) -> bool:
    """ロンの必要条件である和了形の完成だけを検査する。

    役・フリテン・立直中の制限は検査しないため、実際に成立するロンの
    集合を必ず含む過大評価になる。
    """
    return is_winning_shape((*hand_tiles, discarded_tile), melds)


def _may_call(
    hand_tiles: tuple[Tile, ...],
    discarded_tile: Tile,
    *,
    is_next_seat: bool,
    remaining_count: int,
    can_draw_rinshan: bool,
) -> bool:
    """ポン・大明槓・チーの必要条件を検査する。"""
    same_type_count = sum(
        1 for tile in hand_tiles if tile.tile_type == discarded_tile.tile_type
    )
    if remaining_count > 0 and same_type_count >= 2:
        return True
    if can_draw_rinshan and same_type_count >= 3:
        return True
    if is_next_seat and remaining_count > 0 and _may_chi(hand_tiles, discarded_tile):
        return True
    return False


def _may_chi(hand_tiles: tuple[Tile, ...], discarded_tile: Tile) -> bool:
    category = discarded_tile.tile_type.category
    if category is TileCategory.HONOR:
        return False

    rank = discarded_tile.tile_type.rank
    available_ranks = {
        tile.tile_type.rank
        for tile in hand_tiles
        if tile.tile_type.category is category
    }
    return any(
        rank + first in available_ranks and rank + second in available_ranks
        for first, second in _CHI_RANK_OFFSETS
    )
