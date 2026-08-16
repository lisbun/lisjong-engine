"""槓の保留宣言factと、立直後暗槓の合法性判定をpureに扱うmodule。

加槓・暗槓は槍槓で成立しないことがあるため、宣言した時点で副露を
書き換えない。宣言はまず`PendingKakan` / `PendingAnkan`というimmutableな
事実として保持し、反応が解決してから初めて`PlayerState`へ確定させる。

この形にすることで、加槓宣言中も元のポンがそのまま残り、槍槓が成立した
場合にmeldをrollbackする必要がなくなる。
"""

from collections.abc import Iterable
from dataclasses import dataclass

from lisjong_engine.meld import Ankan, Daiminkan, Kakan, Meld, Pon
from lisjong_engine.rules import RiichiAnkanPolicy
from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile, TileType
from lisjong_engine.winning import (
    ConcealedGroup,
    StandardWinningDecomposition,
    TripletGroup,
    WinningShape,
    find_standard_decompositions,
    find_winning_shapes,
    find_winning_tile_types,
)

_QUAD_MELD_TYPES = (Ankan, Kakan, Daiminkan)


@dataclass(frozen=True)
class PendingKakan:
    """槍槓の解決を待っている、まだ確定していない加槓。"""

    seat: Seat
    kakan: Kakan

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.kakan, Kakan):
            raise TypeError("kakan must be a Kakan")

    @property
    def target_tile(self) -> Tile:
        return self.kakan.added_tile


@dataclass(frozen=True)
class PendingAnkan:
    """国士無双の槍槓の解決を待っている、まだ確定していない暗槓。"""

    seat: Seat
    ankan: Ankan

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.ankan, Ankan):
            raise TypeError("ankan must be an Ankan")

    @property
    def target_tile(self) -> Tile:
        return self.ankan.tiles[0]


def count_quads(melds: Iterable[Meld]) -> int:
    """副露のうち槓子の数を返す。暗槓・加槓・大明槓をまとめて数える。"""
    return sum(1 for meld in melds if isinstance(meld, _QUAD_MELD_TYPES))


def find_kakan_pon(melds: Iterable[Meld], added_tile: Tile) -> Pon | None:
    """`added_tile`で加槓できる、同じ牌種のポンを返す。"""
    if not isinstance(added_tile, Tile):
        raise TypeError("added_tile must be a Tile")
    for meld in melds:
        if isinstance(meld, Pon) and meld.called_tile.tile_type == added_tile.tile_type:
            return meld
    return None


def is_riichi_ankan_allowed(
    *,
    hand_tiles: Iterable[Tile],
    melds: Iterable[Meld],
    drawn_tile: Tile,
    tile_ids: tuple[int, int, int, int],
    policy: RiichiAnkanPolicy,
) -> bool:
    """立直後の暗槓が合法かどうかを返す。"""
    try:
        validate_riichi_ankan(
            hand_tiles=hand_tiles,
            melds=melds,
            drawn_tile=drawn_tile,
            tile_ids=tile_ids,
            policy=policy,
        )
    except ValueError:
        return False
    return True


def validate_riichi_ankan(
    *,
    hand_tiles: Iterable[Tile],
    melds: Iterable[Meld],
    drawn_tile: Tile,
    tile_ids: tuple[int, int, int, int],
    policy: RiichiAnkanPolicy,
) -> None:
    """立直後暗槓の合法性判定の正本。

    送り槓の禁止（暗槓にツモ牌を含むこと）と待ち牌種類の不変は、policyに
    関わらず必須である。`PRESERVE_WAIT_AND_DECOMPOSITION`のときだけ、
    さらに和了時の面子分解の維持まで要求する。

    合法手生成と適用時の再検証は、どちらもこの関数を通す。
    """
    if not isinstance(drawn_tile, Tile):
        raise TypeError("drawn_tile must be a Tile")
    if not isinstance(policy, RiichiAnkanPolicy):
        raise TypeError("policy must be a RiichiAnkanPolicy")

    hand = tuple(hand_tiles)
    declared_melds = tuple(melds)
    quad_tile_ids = frozenset(tile_ids)
    if drawn_tile.id not in quad_tile_ids:
        raise ValueError("riichi ankan must use the drawn tile")

    quad_tiles = tuple(tile for tile in hand if tile.id in quad_tile_ids)
    if len(quad_tiles) != len(quad_tile_ids):
        raise ValueError("riichi ankan must use four tiles from the hand")
    ankan = Ankan(quad_tiles)

    hand_before_draw = tuple(tile for tile in hand if tile.id != drawn_tile.id)
    hand_after = tuple(tile for tile in hand if tile.id not in quad_tile_ids)
    melds_after = (*declared_melds, ankan)

    waits_before = find_winning_tile_types(hand_before_draw, declared_melds)
    waits_after = find_winning_tile_types(hand_after, melds_after)
    if waits_after != waits_before:
        raise ValueError("riichi ankan must not change winning tile types")
    if policy is RiichiAnkanPolicy.PRESERVE_WAIT_ONLY:
        return

    if not _preserves_decompositions(
        hand_before=hand_before_draw,
        melds_before=declared_melds,
        hand_after=hand_after,
        melds_after=melds_after,
        owned_tiles=(*hand, *(tile for meld in declared_melds for tile in meld.tiles)),
        winning_tile_types=waits_before,
        quad_tile_type=ankan.tiles[0].tile_type,
    ):
        raise ValueError("riichi ankan must not change group decompositions")


def _preserves_decompositions(
    *,
    hand_before: tuple[Tile, ...],
    melds_before: tuple[Meld, ...],
    hand_after: tuple[Tile, ...],
    melds_after: tuple[Meld, ...],
    owned_tiles: tuple[Tile, ...],
    winning_tile_types: frozenset[TileType],
    quad_tile_type: TileType,
) -> bool:
    """待ちごとに、槓の前後で標準形の面子分解が一致するかを判定する。

    対象の待ちが`WinningShape.STANDARD`以外の解釈（七対子・国士無双等）を
    含む場合もFalseとする。暗槓で刻子を固定すると、それらの解釈が失われる
    ためである。
    """
    for winning_tile_type in winning_tile_types:
        winning_tile = _unused_tile(winning_tile_type, owned_tiles)
        completed_before = (*hand_before, winning_tile)
        completed_after = (*hand_after, winning_tile)
        if find_winning_shapes(completed_before, melds_before) != frozenset(
            {WinningShape.STANDARD}
        ):
            return False

        before_signatures = set()
        for decomposition in find_standard_decompositions(
            completed_before,
            melds_before,
        ):
            signature = _signature_without_triplet(decomposition, quad_tile_type)
            if signature is None:
                return False
            before_signatures.add(signature)
        after_signatures = {
            _decomposition_signature(decomposition)
            for decomposition in find_standard_decompositions(
                completed_after,
                melds_after,
            )
        }
        if before_signatures != after_signatures:
            return False
    return True


def _unused_tile(tile_type: TileType, owned_tiles: tuple[Tile, ...]) -> Tile:
    used_copy_indexes = {
        tile.copy_index for tile in owned_tiles if tile.tile_type == tile_type
    }
    return Tile(
        tile_type,
        next(index for index in range(4) if index not in used_copy_indexes),
    )


def _signature_without_triplet(
    decomposition: StandardWinningDecomposition,
    tile_type: TileType,
) -> tuple[int, tuple[tuple[str, int], ...]] | None:
    groups = list(decomposition.concealed_groups)
    target = TripletGroup(tile_type)
    if target not in groups:
        return None
    groups.remove(target)
    return decomposition.pair.id, _group_signature(groups)


def _decomposition_signature(
    decomposition: StandardWinningDecomposition,
) -> tuple[int, tuple[tuple[str, int], ...]]:
    return decomposition.pair.id, _group_signature(decomposition.concealed_groups)


def _group_signature(
    groups: Iterable[ConcealedGroup],
) -> tuple[tuple[str, int], ...]:
    return tuple(
        sorted(
            (
                "triplet" if isinstance(group, TripletGroup) else "sequence",
                (
                    group.tile_type.id
                    if isinstance(group, TripletGroup)
                    else group.start_tile_type.id
                ),
            )
            for group in groups
        )
    )
