from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from lisjong_engine.meld import Meld
from lisjong_engine.tile import (
    STANDARD_TILE_TYPES,
    STANDARD_TILES,
    Tile,
    TileCategory,
    TileType,
)


class WinningShape(Enum):
    STANDARD = "standard"
    SEVEN_PAIRS = "seven_pairs"
    THIRTEEN_ORPHANS = "thirteen_orphans"


class WaitType(Enum):
    RYANMEN = "ryanmen"
    KANCHAN = "kanchan"
    PENCHAN = "penchan"
    SHANPON = "shanpon"
    TANKI = "tanki"
    KOKUSHI_SINGLE = "kokushi_single"
    KOKUSHI_THIRTEEN_SIDED = "kokushi_thirteen_sided"


_TILE_TYPE_COUNT = len(STANDARD_TILE_TYPES)
_COPIES_PER_TILE_TYPE = 4
_THIRTEEN_ORPHANS_TILE_TYPE_IDS = frozenset(
    tile_type.id
    for tile_type in STANDARD_TILE_TYPES
    if tile_type.category is TileCategory.HONOR or tile_type.rank in (1, 9)
)


@dataclass(frozen=True)
class SequenceGroup:
    start_tile_type: TileType

    def __post_init__(self) -> None:
        if not isinstance(self.start_tile_type, TileType):
            raise TypeError("start_tile_type must be a TileType")
        if (
            self.start_tile_type.category is TileCategory.HONOR
            or self.start_tile_type.rank > 7
        ):
            raise ValueError(
                "sequence must start with a suited tile ranked between 1 and 7"
            )

    @property
    def tile_types(self) -> tuple[TileType, TileType, TileType]:
        category = self.start_tile_type.category
        rank = self.start_tile_type.rank
        return (
            self.start_tile_type,
            TileType(category, rank + 1),
            TileType(category, rank + 2),
        )


@dataclass(frozen=True)
class TripletGroup:
    tile_type: TileType

    def __post_init__(self) -> None:
        if not isinstance(self.tile_type, TileType):
            raise TypeError("tile_type must be a TileType")

    @property
    def tile_types(self) -> tuple[TileType, TileType, TileType]:
        return (self.tile_type, self.tile_type, self.tile_type)


ConcealedGroup = SequenceGroup | TripletGroup


@dataclass(frozen=True)
class StandardWinningDecomposition:
    """通常形を雀頭・手牌内の面子・宣言済み副露へ分けた1候補。"""

    pair: TileType
    concealed_groups: tuple[ConcealedGroup, ...]
    declared_melds: tuple[Meld, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.pair, TileType):
            raise TypeError("pair must be a TileType")

        try:
            concealed_groups = tuple(self.concealed_groups)
        except TypeError:
            raise TypeError(
                "concealed_groups must be an iterable of group instances"
            ) from None
        if any(not isinstance(group, ConcealedGroup) for group in concealed_groups):
            raise TypeError(
                "concealed_groups must contain only SequenceGroup or "
                "TripletGroup instances"
            )

        declared_melds = _normalize_melds(self.declared_melds)
        if len(concealed_groups) + len(declared_melds) != 4:
            raise ValueError("standard decomposition must contain exactly four groups")

        object.__setattr__(self, "concealed_groups", concealed_groups)
        object.__setattr__(self, "declared_melds", declared_melds)


@dataclass(frozen=True)
class StandardWinningInterpretation:
    """通常形の1候補に、和了牌がどこへ属するかを加えた解釈。"""

    decomposition: StandardWinningDecomposition
    winning_tile_type: TileType
    completed_group: ConcealedGroup | None

    def __post_init__(self) -> None:
        if not isinstance(self.decomposition, StandardWinningDecomposition):
            raise TypeError("decomposition must be a StandardWinningDecomposition")
        if not isinstance(self.winning_tile_type, TileType):
            raise TypeError("winning_tile_type must be a TileType")
        if self.completed_group is None:
            if self.decomposition.pair != self.winning_tile_type:
                raise ValueError("winning tile must match the completed pair")
            return
        if not isinstance(self.completed_group, ConcealedGroup):
            raise TypeError(
                "completed_group must be a SequenceGroup, TripletGroup, or None"
            )
        if self.completed_group not in self.decomposition.concealed_groups:
            raise ValueError("completed_group must be in the decomposition")
        if self.winning_tile_type not in self.completed_group.tile_types:
            raise ValueError("winning tile must belong to the completed group")

    @property
    def wait_type(self) -> WaitType:
        if self.completed_group is None:
            return WaitType.TANKI
        if isinstance(self.completed_group, TripletGroup):
            return WaitType.SHANPON
        return _sequence_wait_type(
            self.completed_group,
            self.winning_tile_type,
        )


def find_winning_shapes(
    concealed_tiles: Iterable[Tile],
    declared_melds: Iterable[Meld] = (),
) -> frozenset[WinningShape]:
    """役の有無を考慮せず、完成している和了形の種類を返す。"""
    tiles, melds = _prepare_tiles_and_melds(
        concealed_tiles,
        declared_melds,
    )

    meld_count = len(melds)
    if meld_count > 4 or len(tiles) + meld_count * 3 != 14:
        return frozenset()

    counts = _tile_type_counts(tiles)
    shapes: set[WinningShape] = set()

    if _find_standard_components(counts, 4 - meld_count):
        shapes.add(WinningShape.STANDARD)
    if meld_count == 0 and _is_seven_pairs_shape(counts):
        shapes.add(WinningShape.SEVEN_PAIRS)
    if meld_count == 0 and _is_thirteen_orphans_shape(counts):
        shapes.add(WinningShape.THIRTEEN_ORPHANS)

    return frozenset(shapes)


def find_standard_decompositions(
    concealed_tiles: Iterable[Tile],
    declared_melds: Iterable[Meld] = (),
) -> frozenset[StandardWinningDecomposition]:
    """通常形を雀頭、手牌内の面子、宣言済み副露へ分解する。"""
    tiles, melds = _prepare_tiles_and_melds(
        concealed_tiles,
        declared_melds,
    )

    meld_count = len(melds)
    if meld_count > 4 or len(tiles) + meld_count * 3 != 14:
        return frozenset()

    components = _find_standard_components(
        _tile_type_counts(tiles),
        4 - meld_count,
    )
    return frozenset(
        StandardWinningDecomposition(
            pair=pair,
            concealed_groups=groups,
            declared_melds=melds,
        )
        for pair, groups in components
    )


def find_standard_winning_interpretations(
    concealed_tiles: Iterable[Tile],
    winning_tile: Tile,
    declared_melds: Iterable[Meld] = (),
) -> frozenset[StandardWinningInterpretation]:
    """通常形の和了牌の所属と待ち形を返す。"""
    tiles, melds = _prepare_tiles_and_melds(
        concealed_tiles,
        declared_melds,
    )
    _validate_winning_tile(tiles, winning_tile)

    interpretations: set[StandardWinningInterpretation] = set()
    for decomposition in find_standard_decompositions(tiles, melds):
        if decomposition.pair == winning_tile.tile_type:
            interpretations.add(
                StandardWinningInterpretation(
                    decomposition=decomposition,
                    winning_tile_type=winning_tile.tile_type,
                    completed_group=None,
                )
            )

        for group in frozenset(decomposition.concealed_groups):
            if winning_tile.tile_type not in group.tile_types:
                continue
            interpretations.add(
                StandardWinningInterpretation(
                    decomposition=decomposition,
                    winning_tile_type=winning_tile.tile_type,
                    completed_group=group,
                )
            )

    return frozenset(interpretations)


def find_wait_types(
    concealed_tiles: Iterable[Tile],
    winning_tile: Tile,
    declared_melds: Iterable[Meld] = (),
) -> frozenset[WaitType]:
    """完成した牌姿について成立する待ち形を返す。"""
    tiles, melds = _prepare_tiles_and_melds(
        concealed_tiles,
        declared_melds,
    )
    _validate_winning_tile(tiles, winning_tile)

    waits = {
        interpretation.wait_type
        for interpretation in find_standard_winning_interpretations(
            tiles,
            winning_tile,
            melds,
        )
    }
    if melds:
        return frozenset(waits)

    counts = _tile_type_counts(tiles)
    if _is_seven_pairs_shape(counts):
        waits.add(WaitType.TANKI)
    if _is_thirteen_orphans_shape(counts):
        counts_before_win = list(counts)
        counts_before_win[winning_tile.tile_type.id] -= 1
        if all(
            counts_before_win[tile_type_id] == 1
            for tile_type_id in _THIRTEEN_ORPHANS_TILE_TYPE_IDS
        ):
            waits.add(WaitType.KOKUSHI_THIRTEEN_SIDED)
        else:
            waits.add(WaitType.KOKUSHI_SINGLE)

    return frozenset(waits)


def find_winning_tile_types(
    concealed_tiles: Iterable[Tile],
    declared_melds: Iterable[Meld] = (),
) -> frozenset[TileType]:
    """13枚相当の牌姿を完成させる牌種を返す。"""
    tiles, melds = _prepare_tiles_and_melds(
        concealed_tiles,
        declared_melds,
    )
    if len(melds) > 4 or len(tiles) + len(melds) * 3 != 13:
        return frozenset()

    used_tile_ids = {tile.id for tile in tiles} | {
        tile.id for meld in melds for tile in meld.tiles
    }
    winning_tile_types: set[TileType] = set()
    for tile_type in STANDARD_TILE_TYPES:
        candidate = _find_unused_tile(tile_type, used_tile_ids)
        if candidate is not None and is_winning_shape(
            (*tiles, candidate),
            melds,
        ):
            winning_tile_types.add(tile_type)

    return frozenset(winning_tile_types)


def is_winning_shape(
    concealed_tiles: Iterable[Tile],
    declared_melds: Iterable[Meld] = (),
) -> bool:
    """役の有無を考慮せず、牌構成が和了形かを返す。"""
    return bool(find_winning_shapes(concealed_tiles, declared_melds))


def _find_unused_tile(
    tile_type: TileType,
    used_tile_ids: set[int],
) -> Tile | None:
    """まだ使われていない実在可能な同種牌を1枚返す。"""
    first_copy_index = tile_type.id * _COPIES_PER_TILE_TYPE
    return next(
        (
            tile
            for tile in STANDARD_TILES[
                first_copy_index : first_copy_index + _COPIES_PER_TILE_TYPE
            ]
            if tile.id not in used_tile_ids
        ),
        None,
    )


def _prepare_tiles_and_melds(
    concealed_tiles: Iterable[Tile],
    declared_melds: Iterable[Meld],
) -> tuple[tuple[Tile, ...], tuple[Meld, ...]]:
    tiles = _normalize_tiles(concealed_tiles)
    melds = _normalize_melds(declared_melds)
    _validate_unique_physical_tiles(tiles, melds)
    return tiles, melds


def _validate_winning_tile(
    concealed_tiles: tuple[Tile, ...],
    winning_tile: Tile,
) -> None:
    if not isinstance(winning_tile, Tile):
        raise TypeError("winning_tile must be a Tile")
    if all(tile.id != winning_tile.id for tile in concealed_tiles):
        raise ValueError("winning_tile must be in concealed_tiles")


def _sequence_wait_type(
    group: SequenceGroup,
    winning_tile_type: TileType,
) -> WaitType:
    start_rank = group.start_tile_type.rank
    winning_rank = winning_tile_type.rank
    if winning_rank == start_rank + 1:
        return WaitType.KANCHAN
    if (start_rank, winning_rank) in ((1, 3), (7, 7)):
        return WaitType.PENCHAN
    return WaitType.RYANMEN


def _normalize_tiles(tiles: Iterable[Tile]) -> tuple[Tile, ...]:
    try:
        tile_sequence = tuple(tiles)
    except TypeError:
        raise TypeError(
            "concealed_tiles must be an iterable of Tile instances"
        ) from None

    if any(not isinstance(tile, Tile) for tile in tile_sequence):
        raise TypeError("concealed_tiles must contain only Tile instances")
    return tile_sequence


def _normalize_melds(melds: Iterable[Meld]) -> tuple[Meld, ...]:
    try:
        meld_sequence = tuple(melds)
    except TypeError:
        raise TypeError(
            "declared_melds must be an iterable of meld instances"
        ) from None

    if any(not isinstance(meld, Meld) for meld in meld_sequence):
        raise TypeError(
            "declared_melds must contain only Pon, Kakan, Chi, "
            "Daiminkan, or Ankan instances"
        )
    return meld_sequence


def _validate_unique_physical_tiles(
    concealed_tiles: tuple[Tile, ...],
    declared_melds: tuple[Meld, ...],
) -> None:
    tile_ids = tuple(tile.id for tile in concealed_tiles) + tuple(
        tile.id for meld in declared_melds for tile in meld.tiles
    )
    if len(set(tile_ids)) != len(tile_ids):
        raise ValueError(
            "concealed tiles and declared melds must not contain "
            "duplicate physical tile IDs"
        )


def _tile_type_counts(tiles: tuple[Tile, ...]) -> tuple[int, ...]:
    counts = [0] * _TILE_TYPE_COUNT
    for tile in tiles:
        counts[tile.tile_type.id] += 1
    return tuple(counts)


def _find_standard_components(
    counts: tuple[int, ...],
    required_group_count: int,
) -> frozenset[tuple[TileType, tuple[ConcealedGroup, ...]]]:
    """雀頭候補ごとに、残りを面子へ分ける全通りを列挙する。"""
    if sum(counts) != required_group_count * 3 + 2:
        return frozenset()

    components: set[tuple[TileType, tuple[ConcealedGroup, ...]]] = set()
    for tile_type_id, count in enumerate(counts):
        if count < 2:
            continue

        remaining_counts = list(counts)
        remaining_counts[tile_type_id] -= 2
        for groups in _find_group_combinations(
            tuple(remaining_counts),
            required_group_count,
        ):
            components.add((STANDARD_TILE_TYPES[tile_type_id], groups))

    return frozenset(components)


def _find_group_combinations(
    counts: tuple[int, ...],
    remaining_group_count: int,
) -> frozenset[tuple[ConcealedGroup, ...]]:
    """最小の牌種から順に、刻子と順子の両方を試して全分解を列挙する。"""
    if remaining_group_count == 0:
        if any(counts):
            return frozenset()
        return frozenset({()})
    if sum(counts) != remaining_group_count * 3:
        return frozenset()

    first_tile_type_id = next(
        tile_type_id for tile_type_id, count in enumerate(counts) if count
    )
    first_tile_type = STANDARD_TILE_TYPES[first_tile_type_id]

    combinations: set[tuple[ConcealedGroup, ...]] = set()
    if counts[first_tile_type_id] >= 3:
        remaining_counts = list(counts)
        remaining_counts[first_tile_type_id] -= 3
        triplet = TripletGroup(first_tile_type)
        for remaining_groups in _find_group_combinations(
            tuple(remaining_counts),
            remaining_group_count - 1,
        ):
            combinations.add((triplet, *remaining_groups))

    can_start_sequence = (
        first_tile_type.category is not TileCategory.HONOR
        and first_tile_type.rank <= 7
        and counts[first_tile_type_id + 1] > 0
        and counts[first_tile_type_id + 2] > 0
    )
    if can_start_sequence:
        remaining_counts = list(counts)
        for tile_type_id in range(
            first_tile_type_id,
            first_tile_type_id + 3,
        ):
            remaining_counts[tile_type_id] -= 1
        sequence = SequenceGroup(first_tile_type)
        for remaining_groups in _find_group_combinations(
            tuple(remaining_counts),
            remaining_group_count - 1,
        ):
            combinations.add((sequence, *remaining_groups))

    return frozenset(combinations)


def _is_seven_pairs_shape(counts: tuple[int, ...]) -> bool:
    """同一牌4枚は2対子として数えない。"""
    return sum(count == 2 for count in counts) == 7


def _is_thirteen_orphans_shape(counts: tuple[int, ...]) -> bool:
    present_tile_type_ids = {
        tile_type_id for tile_type_id, count in enumerate(counts) if count
    }
    return (
        present_tile_type_ids == _THIRTEEN_ORPHANS_TILE_TYPE_IDS
        and sum(count == 2 for count in counts) == 1
    )
