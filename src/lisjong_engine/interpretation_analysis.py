from dataclasses import dataclass
from enum import Enum

from lisjong_engine.meld import Ankan, Chi, Kan, Meld
from lisjong_engine.tile import TileCategory, TileType
from lisjong_engine.win_context import WinMethod, WinningContext
from lisjong_engine.wind import Wind
from lisjong_engine.winning import (
    SequenceGroup,
    StandardWinningInterpretation,
    TripletGroup,
    WaitType,
)


class GroupKind(Enum):
    SEQUENCE = "sequence"
    TRIPLET = "triplet"
    QUAD = "quad"


@dataclass(frozen=True)
class GroupAnalysis:
    """1面子を、役・符が共通で必要とする観点へ正規化した結果。"""

    kind: GroupKind
    tile_type: TileType
    is_open: bool
    is_terminal_or_honor: bool
    is_completed_by_ron: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.kind, GroupKind):
            raise TypeError("kind must be a GroupKind")
        if not isinstance(self.tile_type, TileType):
            raise TypeError("tile_type must be a TileType")
        for field_name in (
            "is_open",
            "is_terminal_or_honor",
            "is_completed_by_ron",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise TypeError(f"{field_name} must be a bool")
        if self.is_completed_by_ron and self.kind is not GroupKind.TRIPLET:
            raise ValueError("only a triplet can be completed by ron")
        if self.is_open and self.is_completed_by_ron:
            raise ValueError("an open group cannot be completed by ron")

    @property
    def is_concealed_for_scoring(self) -> bool:
        """ロンで完成した刻子は、手牌内にあっても暗刻として扱わない。"""
        return not self.is_open and not self.is_completed_by_ron


@dataclass(frozen=True)
class PairAnalysis:
    tile_type: TileType
    is_dragon: bool
    is_seat_wind: bool
    is_prevailing_wind: bool

    @property
    def is_double_wind(self) -> bool:
        return self.is_seat_wind and self.is_prevailing_wind

    @property
    def is_value_pair(self) -> bool:
        return self.is_dragon or self.is_seat_wind or self.is_prevailing_wind


@dataclass(frozen=True)
class WinningInterpretationAnalysis:
    """1つの和了解釈を、役・符判定の共通入力へ正規化した結果。"""

    groups: tuple[GroupAnalysis, ...]
    pair: PairAnalysis
    wait_type: WaitType


def analyze_winning_interpretation(
    context: WinningContext,
    interpretation: StandardWinningInterpretation,
) -> WinningInterpretationAnalysis:
    """和了解釈1候補を、役・符が共通で使う観点へ正規化する。"""
    if not isinstance(context, WinningContext):
        raise TypeError("context must be a WinningContext")
    if not isinstance(interpretation, StandardWinningInterpretation):
        raise TypeError("interpretation must be a StandardWinningInterpretation")
    if interpretation.winning_tile_type != context.winning_tile.tile_type:
        raise ValueError("interpretation must use the context winning tile type")
    if interpretation.decomposition.declared_melds != context.declared_melds:
        raise ValueError("interpretation and context must use the same declared melds")

    groups = tuple(
        _analyze_concealed_group(context, interpretation, group)
        for group in interpretation.decomposition.concealed_groups
    ) + tuple(_analyze_declared_meld(meld) for meld in context.declared_melds)
    return WinningInterpretationAnalysis(
        groups=groups,
        pair=_analyze_pair(
            interpretation.decomposition.pair,
            context.seat_wind,
            context.prevailing_wind,
        ),
        wait_type=interpretation.wait_type,
    )


def _analyze_concealed_group(
    context: WinningContext,
    interpretation: StandardWinningInterpretation,
    group: SequenceGroup | TripletGroup,
) -> GroupAnalysis:
    if isinstance(group, SequenceGroup):
        return GroupAnalysis(
            kind=GroupKind.SEQUENCE,
            tile_type=group.start_tile_type,
            is_open=False,
            is_terminal_or_honor=False,
        )

    return GroupAnalysis(
        kind=GroupKind.TRIPLET,
        tile_type=group.tile_type,
        is_open=False,
        is_terminal_or_honor=_is_terminal_or_honor(group.tile_type),
        is_completed_by_ron=(
            context.method is WinMethod.RON and interpretation.completed_group == group
        ),
    )


def _analyze_declared_meld(meld: Meld) -> GroupAnalysis:
    tile_type = meld.tiles[0].tile_type
    if isinstance(meld, Chi):
        return GroupAnalysis(
            kind=GroupKind.SEQUENCE,
            tile_type=min(meld.tiles, key=lambda tile: tile.tile_type.rank).tile_type,
            is_open=True,
            is_terminal_or_honor=False,
        )
    return GroupAnalysis(
        kind=GroupKind.QUAD if isinstance(meld, Kan) else GroupKind.TRIPLET,
        tile_type=tile_type,
        is_open=not isinstance(meld, Ankan),
        is_terminal_or_honor=_is_terminal_or_honor(tile_type),
    )


def _analyze_pair(
    tile_type: TileType,
    seat_wind: Wind,
    prevailing_wind: Wind,
) -> PairAnalysis:
    return PairAnalysis(
        tile_type=tile_type,
        is_dragon=(tile_type.category is TileCategory.HONOR and tile_type.rank >= 5),
        is_seat_wind=tile_type == _wind_tile_type(seat_wind),
        is_prevailing_wind=tile_type == _wind_tile_type(prevailing_wind),
    )


def _wind_tile_type(wind: Wind) -> TileType:
    return TileType(TileCategory.HONOR, tuple(Wind).index(wind) + 1)


def _is_terminal_or_honor(tile_type: TileType) -> bool:
    return tile_type.category is TileCategory.HONOR or tile_type.rank in (1, 9)
