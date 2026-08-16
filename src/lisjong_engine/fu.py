"""符を計算するmodule。

最終的な符だけでなく、その符がどこから来たのかを`FuComponent`として保持し、
人間が計算根拠を監査できる形を維持する。

面子のopen/concealed、ロンで完成した刻子、么九牌かどうか、雀頭の価値、
待ち形は`interpretation_analysis`が正規化済みの結果を使い、本moduleでは
再推測しない。rule差分は単一の`RuleSet`から必要なfieldだけを参照する。
"""

from dataclasses import dataclass
from enum import Enum

from lisjong_engine.interpretation_analysis import (
    GroupAnalysis,
    GroupKind,
    PairAnalysis,
    WinningInterpretationAnalysis,
    analyze_winning_interpretation,
)
from lisjong_engine.rules import RuleSet
from lisjong_engine.win_context import WinMethod, WinningContext
from lisjong_engine.winning import (
    StandardWinningInterpretation,
    WaitType,
    WinningShape,
    find_winning_shapes,
)


class FuReason(Enum):
    """1つの符要素が、どの理由で加算されたかを表す。"""

    SEVEN_PAIRS = "seven_pairs"
    BASE = "base"
    MENZEN_RON = "menzen_ron"
    TSUMO = "tsumo"
    DRAGON_PAIR = "dragon_pair"
    SEAT_WIND_PAIR = "seat_wind_pair"
    PREVAILING_WIND_PAIR = "prevailing_wind_pair"
    DOUBLE_WIND_PAIR = "double_wind_pair"
    OPEN_SIMPLE_TRIPLET = "open_simple_triplet"
    OPEN_TERMINAL_OR_HONOR_TRIPLET = "open_terminal_or_honor_triplet"
    CLOSED_SIMPLE_TRIPLET = "closed_simple_triplet"
    CLOSED_TERMINAL_OR_HONOR_TRIPLET = "closed_terminal_or_honor_triplet"
    OPEN_SIMPLE_QUAD = "open_simple_quad"
    OPEN_TERMINAL_OR_HONOR_QUAD = "open_terminal_or_honor_quad"
    CLOSED_SIMPLE_QUAD = "closed_simple_quad"
    CLOSED_TERMINAL_OR_HONOR_QUAD = "closed_terminal_or_honor_quad"
    KANCHAN_WAIT = "kanchan_wait"
    PENCHAN_WAIT = "penchan_wait"
    TANKI_WAIT = "tanki_wait"


@dataclass(frozen=True)
class FuComponent:
    reason: FuReason
    fu: int

    def __post_init__(self) -> None:
        if not isinstance(self.reason, FuReason):
            raise TypeError("reason must be a FuReason")
        if type(self.fu) is not int or self.fu <= 0:
            raise ValueError("fu must be a positive int")
        if self.reason is FuReason.SEVEN_PAIRS:
            if self.fu != 25:
                raise ValueError("seven pairs must be exactly 25 fu")
        elif self.fu == 25:
            raise ValueError("25 fu is reserved for seven pairs")


@dataclass(frozen=True)
class FuCalculation:
    """符の内訳と、切り上げ後の最終符。"""

    components: tuple[FuComponent, ...]
    rounded_fu: int

    def __post_init__(self) -> None:
        try:
            components = tuple(self.components)
        except TypeError:
            raise TypeError(
                "components must be an iterable of FuComponent instances"
            ) from None
        if any(not isinstance(component, FuComponent) for component in components):
            raise TypeError("components must contain only FuComponent instances")
        if not components:
            raise ValueError("components must not be empty")
        if type(self.rounded_fu) is not int:
            raise TypeError("rounded_fu must be an int")
        is_seven_pairs = components == (_SEVEN_PAIRS_COMPONENT,)
        if (self.rounded_fu == 25) is not is_seven_pairs:
            raise ValueError("25 rounded fu is valid only for seven pairs")
        if self.rounded_fu not in (20, 25) and (
            self.rounded_fu < 30 or self.rounded_fu % 10 != 0
        ):
            raise ValueError(
                "rounded_fu must be 20, 25 for seven pairs, "
                "or a multiple of 10 at least 30"
            )
        if self.rounded_fu < sum(component.fu for component in components):
            raise ValueError("rounded_fu must not be less than raw_fu")

        object.__setattr__(self, "components", components)

    @property
    def raw_fu(self) -> int:
        return sum(component.fu for component in self.components)


_SEVEN_PAIRS_COMPONENT = FuComponent(FuReason.SEVEN_PAIRS, 25)


def calculate_seven_pairs_fu(context: WinningContext) -> FuCalculation:
    """七対子形について、切り上げない固定25符を返す。"""
    if not isinstance(context, WinningContext):
        raise TypeError("context must be a WinningContext")
    shapes = find_winning_shapes(
        context.concealed_tiles,
        context.declared_melds,
    )
    if WinningShape.SEVEN_PAIRS not in shapes:
        raise ValueError("context must have a seven pairs shape")
    return FuCalculation(
        components=(_SEVEN_PAIRS_COMPONENT,),
        rounded_fu=25,
    )


def calculate_fu(
    context: WinningContext,
    interpretation: StandardWinningInterpretation,
    rules: RuleSet | None = None,
) -> FuCalculation:
    """通常形の和了解釈について、生符と切り上げ後の符を返す。"""
    analysis, rules = _prepare(context, interpretation, rules)
    components = _enumerate_fu_components(context, analysis, rules)
    raw_fu = sum(component.fu for component in components)
    return FuCalculation(
        components=components,
        rounded_fu=round_fu(
            raw_fu,
            is_pinfu_tsumo=(
                context.method is WinMethod.TSUMO and _is_pinfu_shape(context, analysis)
            ),
        ),
    )


def enumerate_fu_components(
    context: WinningContext,
    interpretation: StandardWinningInterpretation,
    rules: RuleSet | None = None,
) -> tuple[FuComponent, ...]:
    """通常形の和了解釈について、符要素だけを列挙する。"""
    analysis, rules = _prepare(context, interpretation, rules)
    return _enumerate_fu_components(context, analysis, rules)


def round_fu(raw_fu: int, *, is_pinfu_tsumo: bool = False) -> int:
    """生符を通常形の最終符へ切り上げる。

    通常形は10符単位で切り上げ、最低30符とする。平和ツモだけは例外で、
    ツモ符を加えず20符のままとする。
    """
    if type(raw_fu) is not int or raw_fu <= 0:
        raise ValueError("raw_fu must be a positive int")
    if type(is_pinfu_tsumo) is not bool:
        raise TypeError("is_pinfu_tsumo must be a bool")
    if is_pinfu_tsumo:
        if raw_fu != 20:
            raise ValueError("pinfu tsumo must have exactly 20 raw fu")
        return 20
    return max(30, ((raw_fu + 9) // 10) * 10)


def fu_component_for_group(group: GroupAnalysis) -> FuComponent | None:
    """解析済み面子に対応する刻子・槓子符を返す。順子は符を持たない。

    ロンで完成した刻子は手牌内にあっても明刻として数える。
    """
    if not isinstance(group, GroupAnalysis):
        raise TypeError("group must be a GroupAnalysis")
    if group.kind is GroupKind.SEQUENCE:
        return None

    is_open = not group.is_concealed_for_scoring
    if group.kind is GroupKind.TRIPLET:
        if is_open and not group.is_terminal_or_honor:
            return FuComponent(FuReason.OPEN_SIMPLE_TRIPLET, 2)
        if is_open:
            return FuComponent(FuReason.OPEN_TERMINAL_OR_HONOR_TRIPLET, 4)
        if not group.is_terminal_or_honor:
            return FuComponent(FuReason.CLOSED_SIMPLE_TRIPLET, 4)
        return FuComponent(FuReason.CLOSED_TERMINAL_OR_HONOR_TRIPLET, 8)

    if group.kind is GroupKind.QUAD:
        if is_open and not group.is_terminal_or_honor:
            return FuComponent(FuReason.OPEN_SIMPLE_QUAD, 8)
        if is_open:
            return FuComponent(FuReason.OPEN_TERMINAL_OR_HONOR_QUAD, 16)
        if not group.is_terminal_or_honor:
            return FuComponent(FuReason.CLOSED_SIMPLE_QUAD, 16)
        return FuComponent(FuReason.CLOSED_TERMINAL_OR_HONOR_QUAD, 32)

    raise ValueError(f"unsupported group kind: {group.kind!r}")


def fu_component_for_wait(wait_type: WaitType) -> FuComponent | None:
    """待ち形に対応する符を返す。両面・双碰待ちは符を持たない。"""
    if not isinstance(wait_type, WaitType):
        raise TypeError("wait_type must be a WaitType")
    reason = _WAIT_FU_REASONS.get(wait_type)
    if reason is None:
        return None
    return FuComponent(reason, 2)


_WAIT_FU_REASONS = {
    WaitType.KANCHAN: FuReason.KANCHAN_WAIT,
    WaitType.PENCHAN: FuReason.PENCHAN_WAIT,
    WaitType.TANKI: FuReason.TANKI_WAIT,
}


def _prepare(
    context: WinningContext,
    interpretation: StandardWinningInterpretation,
    rules: RuleSet | None,
) -> tuple[WinningInterpretationAnalysis, RuleSet]:
    if rules is None:
        rules = RuleSet.default()
    elif not isinstance(rules, RuleSet):
        raise TypeError("rules must be a RuleSet")
    return analyze_winning_interpretation(context, interpretation), rules


def _enumerate_fu_components(
    context: WinningContext,
    analysis: WinningInterpretationAnalysis,
    rules: RuleSet,
) -> tuple[FuComponent, ...]:
    components = [FuComponent(FuReason.BASE, 20)]

    if context.method is WinMethod.RON and context.is_menzen:
        components.append(FuComponent(FuReason.MENZEN_RON, 10))
    elif context.method is WinMethod.TSUMO and not _is_pinfu_shape(context, analysis):
        components.append(FuComponent(FuReason.TSUMO, 2))

    components.extend(_pair_fu_components(analysis.pair, rules))
    components.extend(
        component
        for group in analysis.groups
        if (component := fu_component_for_group(group)) is not None
    )
    wait_component = fu_component_for_wait(analysis.wait_type)
    if wait_component is not None:
        components.append(wait_component)
    return tuple(components)


def _is_pinfu_shape(
    context: WinningContext,
    analysis: WinningInterpretationAnalysis,
) -> bool:
    return (
        context.is_menzen
        and all(group.kind is GroupKind.SEQUENCE for group in analysis.groups)
        and not analysis.pair.is_value_pair
        and analysis.wait_type is WaitType.RYANMEN
    )


def _pair_fu_components(
    pair: PairAnalysis,
    rules: RuleSet,
) -> tuple[FuComponent, ...]:
    """雀頭符を返す。連風牌雀頭の符は`RuleSet`の設定に従う。"""
    if pair.is_dragon:
        return (FuComponent(FuReason.DRAGON_PAIR, 2),)
    if pair.is_double_wind:
        return (
            FuComponent(
                FuReason.DOUBLE_WIND_PAIR,
                rules.double_wind_pair_fu,
            ),
        )

    components = []
    if pair.is_seat_wind:
        components.append(FuComponent(FuReason.SEAT_WIND_PAIR, 2))
    if pair.is_prevailing_wind:
        components.append(FuComponent(FuReason.PREVAILING_WIND_PAIR, 2))
    return tuple(components)
