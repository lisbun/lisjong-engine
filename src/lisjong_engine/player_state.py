"""1局のあいだ席が持つ状態を保持する`PlayerState`を定義するmodule。

E1では手牌・河・副露と、それらのownership不変条件だけを責務とする。
立直・フリテン・一発等の状態機械はE2の責務であり、本moduleへ先行実装
しない。

外部からの参照はtuple等のimmutable viewだけを公開し、内部の`Hand` /
`River`を直接渡さない。core APIを迂回した状態書き換えを防ぐためである。
"""

from collections.abc import Iterable

from lisjong_engine.discard import Discard, River
from lisjong_engine.hand import Hand
from lisjong_engine.meld import Ankan, Chi, Daiminkan, Kakan, Meld, Pon
from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile

_MELD_TYPES = (Pon, Kakan, Chi, Daiminkan, Ankan)


class PlayerState:
    def __init__(
        self,
        seat: Seat,
        hand_tiles: Iterable[Tile] = (),
        discards: Iterable[Discard] = (),
        melds: Iterable[Meld] = (),
    ) -> None:
        if not isinstance(seat, Seat):
            raise TypeError("seat must be a Seat")

        hand = Hand(hand_tiles)
        river = River(discards)
        meld_sequence = tuple(melds)
        if any(not isinstance(meld, _MELD_TYPES) for meld in meld_sequence):
            raise TypeError(
                "melds must contain only Pon, Kakan, Chi, Daiminkan, or Ankan instances"
            )

        meld_tile_ids = tuple(tile.id for meld in meld_sequence for tile in meld.tiles)
        if len(set(meld_tile_ids)) != len(meld_tile_ids):
            raise ValueError("melds must not contain duplicate physical tile IDs")

        hand_tile_ids = {tile.id for tile in hand.tiles}
        river_tile_ids = {discard.tile.id for discard in river.discards}
        if hand_tile_ids & river_tile_ids:
            raise ValueError(
                "hand and river must not contain the same physical tile ID"
            )
        if hand_tile_ids & set(meld_tile_ids):
            raise ValueError(
                "hand and melds must not contain the same physical tile ID"
            )

        self._seat = seat
        self._hand = hand
        self._river = river
        self._melds = meld_sequence

    @property
    def seat(self) -> Seat:
        return self._seat

    @property
    def hand_tiles(self) -> tuple[Tile, ...]:
        return self._hand.tiles

    @property
    def discards(self) -> tuple[Discard, ...]:
        return self._river.discards

    @property
    def melds(self) -> tuple[Meld, ...]:
        return self._melds

    @property
    def is_menzen(self) -> bool:
        """暗槓だけは門前を崩さない。"""
        return not any(
            isinstance(meld, (Pon, Kakan, Chi, Daiminkan)) for meld in self._melds
        )

    @property
    def owned_tile_ids(self) -> tuple[int, ...]:
        """この席が所有している物理牌IDを返す。

        鳴かれた捨て牌は鳴いた席のmeldへ所有が移るため、河側では
        `called_by`が付いた捨て牌を所有から除く。E1では鳴きが発生
        しないが、E2で河のhistorical discardとmeldが同じ物理牌を
        参照しても保存則checkが破綻しないよう、最初からownershipで
        定義する。
        """
        return (
            *(tile.id for tile in self._hand.tiles),
            *(
                discard.tile.id
                for discard in self._river.discards
                if discard.called_by is None
            ),
            *(tile.id for meld in self._melds for tile in meld.tiles),
        )

    def add_tile(self, tile: Tile) -> None:
        if not isinstance(tile, Tile):
            raise TypeError("tile must be a Tile")
        if any(discard.tile.id == tile.id for discard in self._river.discards):
            raise ValueError(
                "hand and river must not contain the same physical tile ID"
            )
        if any(
            meld_tile.id == tile.id for meld in self._melds for meld_tile in meld.tiles
        ):
            raise ValueError(
                "hand and melds must not contain the same physical tile ID"
            )

        self._hand.add(tile)

    def discard_tile(self, tile_id: int, *, is_tsumogiri: bool) -> Discard:
        """手牌から`tile_id`を河へ移す。

        ツモ切りかどうかは局のturn状態から`RoundState`が導出する。
        `PlayerState`は席内のownership移動だけを責務とする。
        """
        if type(is_tsumogiri) is not bool:
            raise TypeError("is_tsumogiri must be a bool")

        hand = Hand(self._hand.tiles)
        river = River(self._river.discards)
        tile = hand.remove(tile_id)
        discard = Discard(tile, is_tsumogiri=is_tsumogiri)
        river.add(discard)

        self._hand = hand
        self._river = river
        return discard

    def copy(self) -> "PlayerState":
        return PlayerState(
            self._seat,
            self._hand.tiles,
            self._river.discards,
            self._melds,
        )
