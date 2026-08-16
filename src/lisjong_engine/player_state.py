"""1局のあいだ席が持つ状態を保持する`PlayerState`を定義するmodule。

手牌・河・副露と、それらのownership不変条件に加えて、E2では立直・一発・
見逃しフリテンという局内の席stateを持つ。フリテンの理由そのものの導出は
`furiten`moduleへ委譲し、本moduleは状態の保持と遷移だけを責務とする。

外部からの参照はtuple等のimmutable viewだけを公開し、内部の`Hand` /
`River`を直接渡さない。core APIを迂回した状態書き換えを防ぐためである。

副露・打牌等のmutationは、更新後の値を先に組み立ててから自身へ代入する。
途中で検証に失敗した場合に、手牌だけ減って副露が増えていないといった
中途半端な状態を残さないためである。
"""

from collections.abc import Iterable

from lisjong_engine.discard import Discard, River
from lisjong_engine.furiten import (
    FuritenReason,
    cleared_temporary_reason,
    derive_furiten_reasons,
    next_missed_ron_reason,
    validate_missed_ron_reason,
)
from lisjong_engine.hand import Hand
from lisjong_engine.meld import Ankan, Chi, Daiminkan, Kakan, Meld, Pon
from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile, TileType
from lisjong_engine.win_context import RiichiStatus
from lisjong_engine.winning import find_winning_tile_types

_MELD_TYPES = (Pon, Kakan, Chi, Daiminkan, Ankan)
_OPEN_MELD_TYPES = (Pon, Kakan, Chi, Daiminkan)


class PlayerState:
    def __init__(
        self,
        seat: Seat,
        hand_tiles: Iterable[Tile] = (),
        discards: Iterable[Discard] = (),
        melds: Iterable[Meld] = (),
        *,
        riichi_status: RiichiStatus = RiichiStatus.NONE,
        is_ippatsu: bool = False,
        missed_ron_furiten: FuritenReason | None = None,
    ) -> None:
        if not isinstance(seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(riichi_status, RiichiStatus):
            raise TypeError("riichi_status must be a RiichiStatus")
        if type(is_ippatsu) is not bool:
            raise TypeError("is_ippatsu must be a bool")
        validate_missed_ron_reason(missed_ron_furiten)
        if is_ippatsu and riichi_status is RiichiStatus.NONE:
            raise ValueError("ippatsu requires established riichi")
        if (
            missed_ron_furiten is FuritenReason.RIICHI
            and riichi_status is RiichiStatus.NONE
        ):
            raise ValueError("riichi furiten requires established riichi")

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
        # 自分の河にある牌を自分で鳴くことはできないため、同じ席の河と
        # 副露が同じ物理牌を持つ状態は不正である。一方、他家の河に残る
        # 鳴かれた捨て牌の記録と、鳴いた側のmeldが同じ物理牌を指すのは
        # 正常なownership移動であり、席をまたぐ重複は禁止しない。
        if river_tile_ids & set(meld_tile_ids):
            raise ValueError(
                "river and melds must not contain the same physical tile ID"
            )

        self._seat = seat
        self._hand = hand
        self._river = river
        self._melds = meld_sequence
        self._riichi_status = riichi_status
        self._is_ippatsu = is_ippatsu
        self._missed_ron_furiten = missed_ron_furiten

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
        return not any(isinstance(meld, _OPEN_MELD_TYPES) for meld in self._melds)

    @property
    def discard_count(self) -> int:
        return len(self._river.discards)

    @property
    def has_discarded(self) -> bool:
        return self.discard_count > 0

    @property
    def discarded_tile_types(self) -> tuple[TileType, ...]:
        """フリテン判定に使う、順序付きの全捨て牌種。

        鳴かれた捨て牌もフリテンの対象として残るため、`called_by`の有無で
        絞り込まない。
        """
        return tuple(discard.tile.tile_type for discard in self._river.discards)

    @property
    def winning_tile_types(self) -> frozenset[TileType]:
        return find_winning_tile_types(self._hand.tiles, self._melds)

    @property
    def riichi_status(self) -> RiichiStatus:
        return self._riichi_status

    @property
    def is_riichi_established(self) -> bool:
        return self._riichi_status is not RiichiStatus.NONE

    @property
    def is_double_riichi(self) -> bool:
        return self._riichi_status is RiichiStatus.DOUBLE_RIICHI

    @property
    def is_ippatsu(self) -> bool:
        return self._is_ippatsu

    @property
    def missed_ron_furiten(self) -> FuritenReason | None:
        return self._missed_ron_furiten

    @property
    def furiten_reasons(self) -> frozenset[FuritenReason]:
        return derive_furiten_reasons(
            discarded_tile_types=self.discarded_tile_types,
            winning_tile_types=self.winning_tile_types,
            missed_ron_reason=self._missed_ron_furiten,
        )

    @property
    def is_furiten(self) -> bool:
        return bool(self.furiten_reasons)

    @property
    def is_temporary_furiten(self) -> bool:
        return self._missed_ron_furiten is FuritenReason.TEMPORARY

    @property
    def is_riichi_furiten(self) -> bool:
        return self._missed_ron_furiten is FuritenReason.RIICHI

    @property
    def owned_tile_ids(self) -> tuple[int, ...]:
        """この席が所有している物理牌IDを返す。

        鳴かれた捨て牌は鳴いた席のmeldへ所有が移るため、河側では
        `called_by`が付いた捨て牌を所有から除く。これにより、河の
        historical discardとmeldが同じ物理牌を参照しても、局全体の
        保存則checkが破綻しない。
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

    def call_pon(
        self,
        called_tile: Tile,
        consumed_tile_ids: Iterable[int],
        source_seat: Seat,
    ) -> Pon:
        hand, consumed_tiles = self._take_from_hand(consumed_tile_ids)
        pon = Pon(called_tile, consumed_tiles, source_seat)
        self._replace_hand_and_melds(hand, (*self._melds, pon))
        return pon

    def call_chi(
        self,
        called_tile: Tile,
        consumed_tile_ids: Iterable[int],
        source_seat: Seat,
    ) -> Chi:
        hand, consumed_tiles = self._take_from_hand(consumed_tile_ids)
        chi = Chi(called_tile, consumed_tiles, source_seat)
        self._replace_hand_and_melds(hand, (*self._melds, chi))
        return chi

    def call_daiminkan(
        self,
        called_tile: Tile,
        consumed_tile_ids: Iterable[int],
        source_seat: Seat,
    ) -> Daiminkan:
        hand, consumed_tiles = self._take_from_hand(consumed_tile_ids)
        daiminkan = Daiminkan(called_tile, consumed_tiles, source_seat)
        self._replace_hand_and_melds(hand, (*self._melds, daiminkan))
        return daiminkan

    def declare_ankan(self, tile_ids: Iterable[int]) -> Ankan:
        hand, tiles = self._take_from_hand(tile_ids)
        ankan = Ankan(tiles)
        self._replace_hand_and_melds(hand, (*self._melds, ankan))
        return ankan

    def declare_kakan(self, tile_id: int) -> Kakan:
        """既存のポンを加槓へ差し替える。

        元のポンと追加牌の対応を`Kakan`が保持するため、副露の位置も
        入れ替えずその場で差し替える。符計算と槍槓の判定で、どのポンが
        加槓されたかを後から復元できるようにするためである。
        """
        hand, tiles = self._take_from_hand((tile_id,))
        added_tile = tiles[0]
        matching_index = next(
            (
                index
                for index, meld in enumerate(self._melds)
                if isinstance(meld, Pon)
                and meld.called_tile.tile_type == added_tile.tile_type
            ),
            None,
        )
        if matching_index is None:
            raise ValueError("matching pon is not in melds")

        kakan = Kakan(self._melds[matching_index], added_tile)
        melds = (
            *self._melds[:matching_index],
            kakan,
            *self._melds[matching_index + 1 :],
        )
        self._replace_hand_and_melds(hand, melds)
        return kakan

    def mark_discard_called(self, tile_id: int, caller: Seat) -> Discard:
        river = River(self._river.discards)
        called_discard = river.mark_called(tile_id, caller)

        self._river = river
        return called_discard

    def establish_riichi(self, status: RiichiStatus, *, ippatsu: bool) -> None:
        if not isinstance(status, RiichiStatus):
            raise TypeError("status must be a RiichiStatus")
        if status is RiichiStatus.NONE:
            raise ValueError("established riichi status cannot be none")
        if type(ippatsu) is not bool:
            raise TypeError("ippatsu must be a bool")
        if self.is_riichi_established:
            raise ValueError("riichi is already established")

        self._riichi_status = status
        self._is_ippatsu = ippatsu

    def cancel_ippatsu(self) -> None:
        self._is_ippatsu = False

    def record_missed_ron(self) -> None:
        """ロンできた牌を見逃した事実を、フリテン状態へ反映する。"""
        self._missed_ron_furiten = next_missed_ron_reason(
            self._missed_ron_furiten,
            is_riichi_established=self.is_riichi_established,
        )

    def clear_temporary_furiten(self) -> None:
        """自分のツモ番が来たことによる、同巡内フリテンの解除。"""
        self._missed_ron_furiten = cleared_temporary_reason(self._missed_ron_furiten)

    def copy(self) -> "PlayerState":
        return PlayerState(
            self._seat,
            self._hand.tiles,
            self._river.discards,
            self._melds,
            riichi_status=self._riichi_status,
            is_ippatsu=self._is_ippatsu,
            missed_ron_furiten=self._missed_ron_furiten,
        )

    def _take_from_hand(
        self,
        tile_ids: Iterable[int],
    ) -> tuple[Hand, tuple[Tile, ...]]:
        try:
            requested_ids = tuple(tile_ids)
        except TypeError:
            raise TypeError("tile_ids must be an iterable of ints") from None
        if any(type(tile_id) is not int for tile_id in requested_ids):
            raise TypeError("tile_ids must contain only ints")
        if len(set(requested_ids)) != len(requested_ids):
            raise ValueError("tile_ids must contain distinct physical tile IDs")

        hand = Hand(self._hand.tiles)
        return hand, tuple(hand.remove(tile_id) for tile_id in requested_ids)

    def _replace_hand_and_melds(self, hand: Hand, melds: tuple[Meld, ...]) -> None:
        updated = PlayerState(
            self._seat,
            hand.tiles,
            self._river.discards,
            melds,
            riichi_status=self._riichi_status,
            is_ippatsu=self._is_ippatsu,
            missed_ron_furiten=self._missed_ron_furiten,
        )

        self._hand = updated._hand
        self._melds = updated._melds
