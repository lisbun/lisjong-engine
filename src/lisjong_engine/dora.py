"""ドラを計数するmodule。

ドラは役ではない。本moduleは「何枚のドラを持っているか」だけを数え、
和了が成立するかどうかは判断しない。役なしの手がドラだけで得点付き和了に
なることはない。

`DoraIndicators`は和了時点で **既に確定している** 表示牌のsnapshotである。
どの槓ドラ表示牌が和了時点で有効だったかを決めるのは局進行の責務であり、
本moduleは`RuleSet`の槓ドラ公開ポリシーを解釈しない。表示牌は和了そのものの
事実ではないため`WinningContext`へは持たせず、別入力として受け取る。
"""

from collections.abc import Iterable
from dataclasses import dataclass

from lisjong_engine.tile import Tile, TileCategory, TileType
from lisjong_engine.win_context import RiichiStatus, WinningContext


@dataclass(frozen=True)
class DoraIndicators:
    """和了時点で有効な表系表示牌と、それらに対応する裏表示牌。"""

    visible: tuple[Tile, ...] = ()
    ura: tuple[Tile, ...] = ()
    kan: tuple[Tile, ...] = ()
    kan_ura: tuple[Tile, ...] = ()

    def __post_init__(self) -> None:
        visible = _normalize_tiles(self.visible, "visible")
        ura = _normalize_tiles(self.ura, "ura")
        kan = _normalize_tiles(self.kan, "kan")
        kan_ura = _normalize_tiles(self.kan_ura, "kan_ura")
        if len(visible) > 1:
            raise ValueError("visible must contain at most one normal indicator")
        if len(kan) > 4:
            raise ValueError("kan must contain at most four indicators")
        if len(ura) != len(visible):
            raise ValueError("ura indicators must correspond to visible indicators")
        if len(kan_ura) != len(kan):
            raise ValueError("kan ura indicators must correspond to kan indicators")
        all_indicators = (*visible, *ura, *kan, *kan_ura)
        if len({tile.id for tile in all_indicators}) != len(all_indicators):
            raise ValueError("indicator regions must not share physical tiles")
        object.__setattr__(self, "visible", visible)
        object.__setattr__(self, "ura", ura)
        object.__setattr__(self, "kan", kan)
        object.__setattr__(self, "kan_ura", kan_ura)

    @property
    def all_tiles(self) -> tuple[Tile, ...]:
        return (*self.visible, *self.ura, *self.kan, *self.kan_ura)


@dataclass(frozen=True)
class DoraCount:
    """ドラの内訳。翻数へ潰さず、どの種類が何枚かを保持する。"""

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

    @property
    def total(self) -> int:
        return self.visible + self.ura + self.red + self.kan + self.kan_ura


def dora_tile_type(indicator: Tile | TileType) -> TileType:
    """表示牌から、対応するドラの牌種を返す。

    数牌は9の次が1へ戻り、風牌は北の次が東、三元牌は中の次が白へ戻る。
    赤五は物理牌の識別が違うだけで、表示牌としては通常の五と同じ。
    """
    if isinstance(indicator, Tile):
        indicator_type = indicator.tile_type
    elif isinstance(indicator, TileType):
        indicator_type = indicator
    else:
        raise TypeError("indicator must be a Tile or TileType")

    category = indicator_type.category
    rank = indicator_type.rank
    if category is not TileCategory.HONOR:
        return TileType(category, rank % 9 + 1)
    if rank <= 4:
        return TileType(category, rank % 4 + 1)
    return TileType(category, 5 + (rank - 4) % 3)


def count_dora(
    context: WinningContext,
    indicators: DoraIndicators,
) -> DoraCount:
    """確定した和了情報と表示牌snapshotからドラを集計する。

    裏ドラ・槓裏ドラは立直が成立している場合だけ数える。
    """
    if not isinstance(context, WinningContext):
        raise TypeError("context must be a WinningContext")
    if not isinstance(indicators, DoraIndicators):
        raise TypeError("indicators must be DoraIndicators")

    owned_tiles = context.all_tiles
    if {tile.id for tile in owned_tiles} & {tile.id for tile in indicators.all_tiles}:
        raise ValueError("owned tiles and indicators must not share physical tiles")

    has_ura = context.riichi_status in (
        RiichiStatus.RIICHI,
        RiichiStatus.DOUBLE_RIICHI,
    )
    return DoraCount(
        visible=_count_indicator_dora(owned_tiles, indicators.visible),
        ura=_count_indicator_dora(owned_tiles, indicators.ura) if has_ura else 0,
        red=sum(tile.is_red for tile in owned_tiles),
        kan=_count_indicator_dora(owned_tiles, indicators.kan),
        kan_ura=(
            _count_indicator_dora(owned_tiles, indicators.kan_ura) if has_ura else 0
        ),
    )


def _normalize_tiles(tiles: Iterable[Tile], name: str) -> tuple[Tile, ...]:
    try:
        normalized = tuple(tiles)
    except TypeError:
        raise TypeError(f"{name} must be an iterable of Tile instances") from None
    if any(not isinstance(tile, Tile) for tile in normalized):
        raise TypeError(f"{name} must contain only Tile instances")
    return normalized


def _count_indicator_dora(
    owned_tiles: tuple[Tile, ...],
    indicators: tuple[Tile, ...],
) -> int:
    """同じ牌種の表示牌が複数あれば、その枚数だけ重ねて数える。"""
    return sum(
        sum(tile.tile_type == dora_tile_type(indicator) for tile in owned_tiles)
        for indicator in indicators
    )
