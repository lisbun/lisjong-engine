"""役の成立判定を担当するmodule。

`yaku.py`が「どの役か」という識別子だけを持つのに対し、本moduleは
和了時点の事実（`WinningContext`）と1つの和了解釈から、実際に成立する役と
その翻数・役満倍率を決める。

依存方向は次で固定する。

```text
yaku_evaluation -> yaku
yaku_evaluation -> rules
rules -X-> yaku_evaluation
```

面子のopen/concealed、ロンで完成した刻子、么九牌かどうか、雀頭の価値、
待ち形は`interpretation_analysis`が正規化済みの結果を使い、本moduleでは
再推測しない。これにより、役評価と符計算が同じ面子解釈を共有する。
"""

from collections import Counter
from dataclasses import dataclass

from lisjong_engine.interpretation_analysis import (
    GroupAnalysis,
    GroupKind,
    WinningInterpretationAnalysis,
    analyze_winning_interpretation,
)
from lisjong_engine.rules import RuleSet
from lisjong_engine.tile import TileCategory, TileType
from lisjong_engine.win_context import (
    RiichiStatus,
    WinMethod,
    WinningContext,
    WinOrigin,
)
from lisjong_engine.wind import Wind
from lisjong_engine.winning import (
    StandardWinningInterpretation,
    WaitType,
    WinningShape,
    find_standard_winning_interpretations,
    find_wait_types,
    find_winning_shapes,
)
from lisjong_engine.yaku import Yaku

_SUITED_CATEGORIES = (
    TileCategory.MANZU,
    TileCategory.PINZU,
    TileCategory.SOUZU,
)
_TRIPLET_KINDS = (GroupKind.TRIPLET, GroupKind.QUAD)


@dataclass(frozen=True)
class YakuDefinition:
    """1つの役の表示名と、門前・副露それぞれの翻数を表す。

    `closed_han`・`open_han`が`None`の役は、その状態では成立しない。
    役満は翻数を持たず、倍率は`RuleSet.double_yakuman_variants`で決まる。
    """

    japanese_name: str
    closed_han: int | None
    open_han: int | None
    is_yakuman: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.japanese_name, str):
            raise TypeError("japanese_name must be a str")
        if not self.japanese_name:
            raise ValueError("japanese_name must not be empty")
        for value in (self.closed_han, self.open_han):
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError("han values must be positive ints or None")
        if type(self.is_yakuman) is not bool:
            raise TypeError("is_yakuman must be a bool")
        if self.is_yakuman and (
            self.closed_han is not None or self.open_han is not None
        ):
            raise ValueError("yakuman must not have han values")


YAKU_DEFINITIONS = {
    Yaku.MENZEN_TSUMO: YakuDefinition("門前清自摸和", 1, None),
    Yaku.RIICHI: YakuDefinition("立直", 1, None),
    Yaku.IPPATSU: YakuDefinition("一発", 1, None),
    Yaku.DOUBLE_RIICHI: YakuDefinition("ダブル立直", 2, None),
    Yaku.CHANKAN: YakuDefinition("槍槓", 1, 1),
    Yaku.RINSHAN_KAIHOU: YakuDefinition("嶺上開花", 1, 1),
    Yaku.HAITEI: YakuDefinition("海底摸月", 1, 1),
    Yaku.HOUTEI: YakuDefinition("河底撈魚", 1, 1),
    Yaku.TANYAO: YakuDefinition("断么九", 1, 1),
    Yaku.SEAT_WIND: YakuDefinition("役牌・門風牌", 1, 1),
    Yaku.PREVAILING_WIND: YakuDefinition("役牌・場風牌", 1, 1),
    Yaku.WHITE_DRAGON: YakuDefinition("役牌・白", 1, 1),
    Yaku.GREEN_DRAGON: YakuDefinition("役牌・發", 1, 1),
    Yaku.RED_DRAGON: YakuDefinition("役牌・中", 1, 1),
    Yaku.PINFU: YakuDefinition("平和", 1, None),
    Yaku.IIPEIKOU: YakuDefinition("一盃口", 1, None),
    Yaku.CHANTA: YakuDefinition("混全帯幺九", 2, 1),
    Yaku.ITTSUU: YakuDefinition("一気通貫", 2, 1),
    Yaku.SANSHOKU_DOUJUN: YakuDefinition("三色同順", 2, 1),
    Yaku.SANSHOKU_DOUKOU: YakuDefinition("三色同刻", 2, 2),
    Yaku.SANKANTSU: YakuDefinition("三槓子", 2, 2),
    Yaku.TOITOI: YakuDefinition("対々和", 2, 2),
    Yaku.SANANKOU: YakuDefinition("三暗刻", 2, 2),
    Yaku.SHOUSANGEN: YakuDefinition("小三元", 2, 2),
    Yaku.HONROUTOU: YakuDefinition("混老頭", 2, 2),
    Yaku.CHIITOITSU: YakuDefinition("七対子", 2, None),
    Yaku.JUNCHAN: YakuDefinition("純全帯幺九", 3, 2),
    Yaku.HONITSU: YakuDefinition("混一色", 3, 2),
    Yaku.RYANPEIKOU: YakuDefinition("二盃口", 3, None),
    Yaku.CHINITSU: YakuDefinition("清一色", 6, 5),
    Yaku.TENHOU: YakuDefinition("天和", None, None, True),
    Yaku.CHIIHOU: YakuDefinition("地和", None, None, True),
    Yaku.DAISANGEN: YakuDefinition("大三元", None, None, True),
    Yaku.SUUANKOU: YakuDefinition("四暗刻", None, None, True),
    Yaku.SUUANKOU_TANKI: YakuDefinition("四暗刻単騎", None, None, True),
    Yaku.TSUUIISOU: YakuDefinition("字一色", None, None, True),
    Yaku.RYUUIISOU: YakuDefinition("緑一色", None, None, True),
    Yaku.CHINROUTOU: YakuDefinition("清老頭", None, None, True),
    Yaku.KOKUSHI_MUSOU: YakuDefinition("国士無双", None, None, True),
    Yaku.KOKUSHI_MUSOU_13_WAIT: YakuDefinition(
        "国士無双十三面待ち",
        None,
        None,
        True,
    ),
    Yaku.DAISUUSHII: YakuDefinition("大四喜", None, None, True),
    Yaku.SHOUSUUSHII: YakuDefinition("小四喜", None, None, True),
    Yaku.SUUKANTSU: YakuDefinition("四槓子", None, None, True),
    Yaku.CHUUREN_POUTOU: YakuDefinition("九蓮宝燈", None, None, True),
    Yaku.JUNSEI_CHUUREN_POUTOU: YakuDefinition(
        "純正九蓮宝燈",
        None,
        None,
        True,
    ),
}


@dataclass(frozen=True)
class YakuMatch:
    """成立した役1つと、その和了で得た翻数または役満倍率。"""

    yaku: Yaku
    han: int = 0
    yakuman_units: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.yaku, Yaku):
            raise TypeError("yaku must be a Yaku")
        if type(self.han) is not int or self.han < 0:
            raise ValueError("han must be a non-negative int")
        if type(self.yakuman_units) is not int or self.yakuman_units < 0:
            raise ValueError("yakuman_units must be a non-negative int")
        if (self.han > 0) == (self.yakuman_units > 0):
            raise ValueError("exactly one of han and yakuman_units must be positive")
        definition = YAKU_DEFINITIONS[self.yaku]
        if definition.is_yakuman is not (self.yakuman_units > 0):
            raise ValueError("match value kind must agree with the yaku definition")

    @property
    def japanese_name(self) -> str:
        return YAKU_DEFINITIONS[self.yaku].japanese_name


@dataclass(frozen=True)
class YakuEvaluation:
    """1つの和了解釈について成立した役の一覧。

    通常役と役満は混在させない。役満が成立した解釈では、通常役を数えずに
    役満だけを保持する。
    """

    shape: WinningShape
    wait_type: WaitType
    matches: tuple[YakuMatch, ...]
    standard_interpretation: StandardWinningInterpretation | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.shape, WinningShape):
            raise TypeError("shape must be a WinningShape")
        if not isinstance(self.wait_type, WaitType):
            raise TypeError("wait_type must be a WaitType")
        try:
            matches = tuple(self.matches)
        except TypeError:
            raise TypeError(
                "matches must be an iterable of YakuMatch instances"
            ) from None
        if any(not isinstance(match, YakuMatch) for match in matches):
            raise TypeError("matches must contain only YakuMatch instances")
        if not matches:
            raise ValueError("matches must not be empty")
        yakus = tuple(match.yaku for match in matches)
        if len(set(yakus)) != len(yakus):
            raise ValueError("matches must not contain duplicate yaku")
        has_yakuman = any(match.yakuman_units for match in matches)
        if has_yakuman and any(match.han for match in matches):
            raise ValueError("normal yaku and yakuman must not be mixed")

        if self.shape is WinningShape.STANDARD:
            if not isinstance(
                self.standard_interpretation,
                StandardWinningInterpretation,
            ):
                raise TypeError("standard shape requires a standard interpretation")
            if self.standard_interpretation.wait_type is not self.wait_type:
                raise ValueError("wait_type must match the standard interpretation")
        elif self.standard_interpretation is not None:
            raise ValueError("special shape must not have a standard interpretation")

        object.__setattr__(self, "matches", matches)

    @property
    def han(self) -> int:
        return sum(match.han for match in self.matches)

    @property
    def yakuman_units(self) -> int:
        return sum(match.yakuman_units for match in self.matches)

    @property
    def yakus(self) -> frozenset[Yaku]:
        return frozenset(match.yaku for match in self.matches)


def evaluate_yaku(
    context: WinningContext,
    rules: RuleSet | None = None,
) -> frozenset[YakuEvaluation]:
    """成立する和了形・和了解釈ごとに、成立した役を評価して返す。

    役が1つも成立しない解釈は結果へ含めない。したがって、構造上は和了形でも
    役がなければ空集合になる。ドラは役ではないため、本moduleは扱わない。
    """
    if not isinstance(context, WinningContext):
        raise TypeError("context must be a WinningContext")
    rules = _resolve_rules(rules)

    shapes = find_winning_shapes(
        context.concealed_tiles,
        context.declared_melds,
    )
    evaluations: set[YakuEvaluation] = set()
    situational_yakuman = _situational_yakuman(context)

    if WinningShape.STANDARD in shapes:
        for interpretation in find_standard_winning_interpretations(
            context.concealed_tiles,
            context.winning_tile,
            context.declared_melds,
        ):
            analysis = analyze_winning_interpretation(context, interpretation)
            yakuman = situational_yakuman | _standard_yakuman(context, analysis)
            if yakuman:
                matches = _create_yakuman_matches(yakuman, rules)
            else:
                yakus = _situational_yaku(context)
                yakus.update(_normal_standard_yaku(context, analysis))
                matches = _create_matches(yakus, context.is_menzen)
            if matches:
                evaluations.add(
                    YakuEvaluation(
                        shape=WinningShape.STANDARD,
                        wait_type=interpretation.wait_type,
                        matches=matches,
                        standard_interpretation=interpretation,
                    )
                )

    if WinningShape.SEVEN_PAIRS in shapes:
        yakuman = situational_yakuman | _tile_set_yakuman(context)
        if yakuman:
            matches = _create_yakuman_matches(yakuman, rules)
        else:
            yakus = _situational_yaku(context)
            yakus.update(_tile_set_yaku(context))
            yakus.add(Yaku.CHIITOITSU)
            matches = _create_matches(yakus, context.is_menzen)
        if matches:
            evaluations.add(
                YakuEvaluation(
                    shape=WinningShape.SEVEN_PAIRS,
                    wait_type=WaitType.TANKI,
                    matches=matches,
                )
            )

    if WinningShape.THIRTEEN_ORPHANS in shapes:
        wait_types = find_wait_types(
            context.concealed_tiles,
            context.winning_tile,
            context.declared_melds,
        )
        wait_type = (
            WaitType.KOKUSHI_THIRTEEN_SIDED
            if WaitType.KOKUSHI_THIRTEEN_SIDED in wait_types
            else WaitType.KOKUSHI_SINGLE
        )
        kokushi = (
            Yaku.KOKUSHI_MUSOU_13_WAIT
            if wait_type is WaitType.KOKUSHI_THIRTEEN_SIDED
            else Yaku.KOKUSHI_MUSOU
        )
        evaluations.add(
            YakuEvaluation(
                shape=WinningShape.THIRTEEN_ORPHANS,
                wait_type=wait_type,
                matches=_create_yakuman_matches(
                    situational_yakuman | {kokushi},
                    rules,
                ),
            )
        )

    return frozenset(evaluations)


def _resolve_rules(rules: RuleSet | None) -> RuleSet:
    """`None`を標準ルールセットへ解決する。"""
    if rules is None:
        return RuleSet.default()
    if not isinstance(rules, RuleSet):
        raise TypeError("rules must be a RuleSet")
    return rules


def _create_yakuman_matches(
    yakus: set[Yaku],
    rules: RuleSet,
) -> tuple[YakuMatch, ...]:
    """`Yaku`の定義順で役満matchを作り、ダブル役満設定を適用する。"""
    return tuple(
        YakuMatch(
            yaku=yaku,
            yakuman_units=(2 if yaku in rules.double_yakuman_variants else 1),
        )
        for yaku in Yaku
        if yaku in yakus
    )


def _create_matches(
    yakus: set[Yaku],
    is_menzen: bool,
) -> tuple[YakuMatch, ...]:
    """門前・副露に応じた翻数で通常役matchを作る。

    その状態では成立しない役（門前限定役を副露しているなど）は落とす。
    """
    matches = []
    for yaku in Yaku:
        if yaku not in yakus:
            continue
        definition = YAKU_DEFINITIONS[yaku]
        han = definition.closed_han if is_menzen else definition.open_han
        if han is not None:
            matches.append(YakuMatch(yaku=yaku, han=han))
    return tuple(matches)


def _situational_yakuman(context: WinningContext) -> set[Yaku]:
    if not context.is_first_uninterrupted_turn:
        return set()
    return {Yaku.TENHOU if context.seat_wind is Wind.EAST else Yaku.CHIIHOU}


def _situational_yaku(context: WinningContext) -> set[Yaku]:
    """牌の構成ではなく、和了時点の状況だけで決まる役を返す。"""
    yakus: set[Yaku] = set()

    if context.method is WinMethod.TSUMO and context.is_menzen:
        yakus.add(Yaku.MENZEN_TSUMO)
    if context.riichi_status is RiichiStatus.DOUBLE_RIICHI:
        yakus.add(Yaku.DOUBLE_RIICHI)
    elif context.riichi_status is RiichiStatus.RIICHI:
        yakus.add(Yaku.RIICHI)
    if context.is_ippatsu:
        yakus.add(Yaku.IPPATSU)

    if context.origin is WinOrigin.KAKAN:
        yakus.add(Yaku.CHANKAN)
    elif context.origin is WinOrigin.RINSHAN:
        yakus.add(Yaku.RINSHAN_KAIHOU)

    if context.is_last_tile:
        yakus.add(Yaku.HAITEI if context.method is WinMethod.TSUMO else Yaku.HOUTEI)

    return yakus


def _standard_yakuman(
    context: WinningContext,
    analysis: WinningInterpretationAnalysis,
) -> set[Yaku]:
    yakuman = _tile_set_yakuman(context)
    triplet_types = frozenset(_triplet_tile_types(analysis))

    if _DRAGON_TILE_TYPES <= triplet_types:
        yakuman.add(Yaku.DAISANGEN)

    if _concealed_triplet_count(analysis) == 4:
        yakuman.add(
            Yaku.SUUANKOU_TANKI
            if analysis.wait_type is WaitType.TANKI
            else Yaku.SUUANKOU
        )

    wind_triplets = triplet_types & _WIND_TILE_TYPES
    if len(wind_triplets) == 4:
        yakuman.add(Yaku.DAISUUSHII)
    elif (
        len(wind_triplets) == 3
        and analysis.pair.tile_type in _WIND_TILE_TYPES - wind_triplets
    ):
        yakuman.add(Yaku.SHOUSUUSHII)

    if _quad_count(analysis) == 4:
        yakuman.add(Yaku.SUUKANTSU)

    chuuren = _chuuren_yaku(context)
    if chuuren is not None:
        yakuman.add(chuuren)

    return yakuman


def _tile_set_yakuman(context: WinningContext) -> set[Yaku]:
    """面子解釈に依存せず、使用牌の集合だけで決まる役満を返す。"""
    tile_types = tuple(tile.tile_type for tile in context.all_tiles)
    yakuman: set[Yaku] = set()

    if all(tile_type.category is TileCategory.HONOR for tile_type in tile_types):
        yakuman.add(Yaku.TSUUIISOU)
    if all(tile_type in _GREEN_TILE_TYPES for tile_type in tile_types):
        yakuman.add(Yaku.RYUUIISOU)
    if all(_is_terminal(tile_type) for tile_type in tile_types):
        yakuman.add(Yaku.CHINROUTOU)

    return yakuman


def _chuuren_yaku(context: WinningContext) -> Yaku | None:
    """門前の14枚が九蓮宝燈形なら、純正かどうかを区別して返す。"""
    if context.declared_melds or len(context.concealed_tiles) != 14:
        return None

    tile_types = tuple(tile.tile_type for tile in context.concealed_tiles)
    categories = {tile_type.category for tile_type in tile_types}
    if len(categories) != 1 or TileCategory.HONOR in categories:
        return None

    counts = tuple(
        sum(tile_type.rank == rank for tile_type in tile_types) for rank in range(1, 10)
    )
    if any(
        count < required
        for count, required in zip(counts, _CHUUREN_BASE_COUNTS, strict=True)
    ):
        return None

    counts_before_win = list(counts)
    counts_before_win[context.winning_tile.tile_type.rank - 1] -= 1
    return (
        Yaku.JUNSEI_CHUUREN_POUTOU
        if tuple(counts_before_win) == _CHUUREN_BASE_COUNTS
        else Yaku.CHUUREN_POUTOU
    )


def _normal_standard_yaku(
    context: WinningContext,
    analysis: WinningInterpretationAnalysis,
) -> set[Yaku]:
    yakus = _tile_set_yaku(context)
    triplet_types = frozenset(_triplet_tile_types(analysis))
    sequence_starts = _sequence_start_tile_types(analysis)

    wind_yaku = (
        (_wind_tile_type(context.seat_wind), Yaku.SEAT_WIND),
        (_wind_tile_type(context.prevailing_wind), Yaku.PREVAILING_WIND),
        (_honor_tile_type(5), Yaku.WHITE_DRAGON),
        (_honor_tile_type(6), Yaku.GREEN_DRAGON),
        (_honor_tile_type(7), Yaku.RED_DRAGON),
    )
    yakus.update(yaku for tile_type, yaku in wind_yaku if tile_type in triplet_types)

    if _is_pinfu(context, analysis):
        yakus.add(Yaku.PINFU)

    if context.is_menzen:
        sequence_counts = Counter(sequence_starts)
        identical_pairs = sum(count // 2 for count in sequence_counts.values())
        if len(sequence_starts) == len(analysis.groups) and identical_pairs == 2:
            yakus.add(Yaku.RYANPEIKOU)
        elif identical_pairs:
            yakus.add(Yaku.IIPEIKOU)

    if _is_junchan(context, analysis):
        yakus.add(Yaku.JUNCHAN)
    elif _is_chanta(context, analysis):
        yakus.add(Yaku.CHANTA)

    if _has_ittsuu(sequence_starts):
        yakus.add(Yaku.ITTSUU)
    if _has_three_colour_set(sequence_starts, range(1, 8)):
        yakus.add(Yaku.SANSHOKU_DOUJUN)
    if _has_three_colour_set(triplet_types, range(1, 10)):
        yakus.add(Yaku.SANSHOKU_DOUKOU)

    if _quad_count(analysis) == 3:
        yakus.add(Yaku.SANKANTSU)
    if not sequence_starts:
        yakus.add(Yaku.TOITOI)
    if _concealed_triplet_count(analysis) >= 3:
        yakus.add(Yaku.SANANKOU)

    dragon_triplets = triplet_types & _DRAGON_TILE_TYPES
    if (
        len(dragon_triplets) == 2
        and analysis.pair.tile_type in _DRAGON_TILE_TYPES - dragon_triplets
    ):
        yakus.add(Yaku.SHOUSANGEN)

    return yakus


def _tile_set_yaku(context: WinningContext) -> set[Yaku]:
    """面子解釈に依存せず、使用牌の集合だけで決まる通常役を返す。"""
    tile_types = tuple(tile.tile_type for tile in context.all_tiles)
    yakus: set[Yaku] = set()

    if all(_is_simple(tile_type) for tile_type in tile_types):
        yakus.add(Yaku.TANYAO)
    if all(_is_terminal_or_honor(tile_type) for tile_type in tile_types):
        yakus.add(Yaku.HONROUTOU)

    suited_categories = {
        tile_type.category
        for tile_type in tile_types
        if tile_type.category is not TileCategory.HONOR
    }
    has_honor = any(
        tile_type.category is TileCategory.HONOR for tile_type in tile_types
    )
    if len(suited_categories) == 1:
        yakus.add(Yaku.HONITSU if has_honor else Yaku.CHINITSU)

    return yakus


def _is_pinfu(
    context: WinningContext,
    analysis: WinningInterpretationAnalysis,
) -> bool:
    return (
        context.is_menzen
        and all(group.kind is GroupKind.SEQUENCE for group in analysis.groups)
        and not analysis.pair.is_value_pair
        and analysis.wait_type is WaitType.RYANMEN
    )


def _is_chanta(
    context: WinningContext,
    analysis: WinningInterpretationAnalysis,
) -> bool:
    """順子を含み、全面子と雀頭が么九牌を含み、字牌を1枚以上使う。"""
    return (
        any(group.kind is GroupKind.SEQUENCE for group in analysis.groups)
        and all(_contains_terminal_or_honor(group) for group in analysis.groups)
        and _is_terminal_or_honor(analysis.pair.tile_type)
        and any(
            tile.tile_type.category is TileCategory.HONOR for tile in context.all_tiles
        )
    )


def _is_junchan(
    context: WinningContext,
    analysis: WinningInterpretationAnalysis,
) -> bool:
    """順子を含み、全面子と雀頭が老頭牌を含み、字牌を一切使わない。"""
    return (
        any(group.kind is GroupKind.SEQUENCE for group in analysis.groups)
        and all(_contains_terminal(group) for group in analysis.groups)
        and _is_terminal(analysis.pair.tile_type)
        and all(
            tile.tile_type.category is not TileCategory.HONOR
            for tile in context.all_tiles
        )
    )


def _has_ittsuu(sequence_starts: tuple[TileType, ...]) -> bool:
    starts = {(start.category, start.rank) for start in sequence_starts}
    return any(
        all((category, rank) in starts for rank in (1, 4, 7))
        for category in _SUITED_CATEGORIES
    )


def _has_three_colour_set(
    tile_types: tuple[TileType, ...] | frozenset[TileType],
    ranks: range,
) -> bool:
    """同じ数字の面子が三色そろっているかを返す。"""
    present = {(tile_type.category, tile_type.rank) for tile_type in tile_types}
    return any(
        all((category, rank) in present for category in _SUITED_CATEGORIES)
        for rank in ranks
    )


def _triplet_tile_types(
    analysis: WinningInterpretationAnalysis,
) -> tuple[TileType, ...]:
    """刻子・槓子の牌種を返す。槓子も刻子系の役では同じ扱いにする。"""
    return tuple(
        group.tile_type for group in analysis.groups if group.kind in _TRIPLET_KINDS
    )


def _sequence_start_tile_types(
    analysis: WinningInterpretationAnalysis,
) -> tuple[TileType, ...]:
    return tuple(
        group.tile_type for group in analysis.groups if group.kind is GroupKind.SEQUENCE
    )


def _concealed_triplet_count(analysis: WinningInterpretationAnalysis) -> int:
    """暗刻・暗槓の数を返す。ロンで完成した刻子は暗刻として数えない。"""
    return sum(
        group.kind in _TRIPLET_KINDS and group.is_concealed_for_scoring
        for group in analysis.groups
    )


def _quad_count(analysis: WinningInterpretationAnalysis) -> int:
    return sum(group.kind is GroupKind.QUAD for group in analysis.groups)


def _contains_terminal_or_honor(group: GroupAnalysis) -> bool:
    if group.kind is GroupKind.SEQUENCE:
        return group.tile_type.rank in (1, 7)
    return group.is_terminal_or_honor


def _contains_terminal(group: GroupAnalysis) -> bool:
    if group.kind is GroupKind.SEQUENCE:
        return group.tile_type.rank in (1, 7)
    return _is_terminal(group.tile_type)


def _is_simple(tile_type: TileType) -> bool:
    return tile_type.category is not TileCategory.HONOR and 2 <= tile_type.rank <= 8


def _is_terminal(tile_type: TileType) -> bool:
    return tile_type.category is not TileCategory.HONOR and tile_type.rank in (1, 9)


def _is_terminal_or_honor(tile_type: TileType) -> bool:
    return tile_type.category is TileCategory.HONOR or _is_terminal(tile_type)


def _wind_tile_type(wind: Wind) -> TileType:
    return _honor_tile_type(tuple(Wind).index(wind) + 1)


def _honor_tile_type(rank: int) -> TileType:
    return TileType(TileCategory.HONOR, rank)


_WIND_TILE_TYPES = frozenset(_honor_tile_type(rank) for rank in range(1, 5))
_DRAGON_TILE_TYPES = frozenset(_honor_tile_type(rank) for rank in range(5, 8))
_GREEN_TILE_TYPES = frozenset(
    {
        *(TileType(TileCategory.SOUZU, rank) for rank in (2, 3, 4, 6, 8)),
        _honor_tile_type(6),
    }
)
_CHUUREN_BASE_COUNTS = (3, 1, 1, 1, 1, 1, 1, 1, 3)
