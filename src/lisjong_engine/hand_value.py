"""1つの和了解釈について、役・符・ドラを結合した価値を評価するmodule。

結果は最終翻数へ潰さず、成立役、役ごとの翻数・役満倍率、符の内訳、
ドラの内訳をすべて保持する。これにより、なぜその点数になったのかを
後から監査できる。

旧`python-study`にあった汎用の`bonus_han`は持たない。実戦上のbonus翻は
ドラだけであり、`DoraCount`として根拠を保持したほうが監査可能性が高い。
"""

from dataclasses import dataclass

from lisjong_engine.dora import DoraCount
from lisjong_engine.fu import (
    FuCalculation,
    FuComponent,
    FuReason,
    calculate_fu,
    calculate_seven_pairs_fu,
)
from lisjong_engine.rules import RuleSet
from lisjong_engine.win_context import WinningContext
from lisjong_engine.winning import WinningShape
from lisjong_engine.yaku_evaluation import YakuEvaluation, evaluate_yaku

_SEVEN_PAIRS_COMPONENT = FuComponent(FuReason.SEVEN_PAIRS, 25)


@dataclass(frozen=True)
class HandValueEvaluation:
    """1つの和了解釈の役評価と、対応する符・ドラ。

    役満の解釈では符を持たず、ドラも加算しない。役満は翻数の積み上げでは
    なく倍率で決まるため、通常翻と混ぜない。
    """

    yaku_evaluation: YakuEvaluation
    fu_calculation: FuCalculation | None
    dora_count: DoraCount | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.yaku_evaluation, YakuEvaluation):
            raise TypeError("yaku_evaluation must be a YakuEvaluation")
        if self.fu_calculation is not None and not isinstance(
            self.fu_calculation, FuCalculation
        ):
            raise TypeError("fu_calculation must be a FuCalculation or None")
        if self.dora_count is not None and not isinstance(self.dora_count, DoraCount):
            raise TypeError("dora_count must be a DoraCount or None")

        evaluation = self.yaku_evaluation
        if evaluation.yakuman_units:
            if self.fu_calculation is not None:
                raise ValueError("yakuman evaluation must not have fu calculation")
            object.__setattr__(self, "dora_count", None)
            return
        if self.fu_calculation is None:
            raise ValueError("non-yakuman evaluation must have fu calculation")

        is_seven_pairs_fu = self.fu_calculation.components == (_SEVEN_PAIRS_COMPONENT,)
        if evaluation.shape is WinningShape.STANDARD and is_seven_pairs_fu:
            raise ValueError("standard evaluation must use standard fu calculation")
        if evaluation.shape is WinningShape.SEVEN_PAIRS:
            if not is_seven_pairs_fu:
                raise ValueError(
                    "seven pairs evaluation must use seven pairs fu calculation"
                )
        elif evaluation.shape is not WinningShape.STANDARD:
            raise ValueError("non-yakuman shape does not support fu calculation")

    @property
    def dora_han(self) -> int:
        """ドラによるbonus翻。役満では常に0。"""
        return 0 if self.dora_count is None else self.dora_count.total

    @property
    def total_han(self) -> int:
        return self.yaku_evaluation.han + self.dora_han


def evaluate_hand_value(
    context: WinningContext,
    *,
    dora_count: DoraCount | None = None,
    rules: RuleSet | None = None,
) -> frozenset[HandValueEvaluation]:
    """成立した各和了解釈の役評価と、対応する符・ドラを結び付けて返す。

    役が1つも成立しなければ空集合を返す。ドラは役ではないため、ドラだけで
    和了候補が生まれることはない。
    """
    if not isinstance(context, WinningContext):
        raise TypeError("context must be a WinningContext")
    if dora_count is not None and not isinstance(dora_count, DoraCount):
        raise TypeError("dora_count must be a DoraCount or None")
    if rules is None:
        rules = RuleSet.default()
    elif not isinstance(rules, RuleSet):
        raise TypeError("rules must be a RuleSet")

    return frozenset(
        HandValueEvaluation(
            yaku_evaluation=yaku_evaluation,
            fu_calculation=_fu_for_evaluation(context, yaku_evaluation, rules),
            dora_count=dora_count,
        )
        for yaku_evaluation in evaluate_yaku(context, rules)
    )


def _fu_for_evaluation(
    context: WinningContext,
    evaluation: YakuEvaluation,
    rules: RuleSet,
) -> FuCalculation | None:
    if evaluation.yakuman_units:
        return None
    if evaluation.shape is WinningShape.STANDARD:
        interpretation = evaluation.standard_interpretation
        if interpretation is None:
            raise ValueError("standard evaluation must have an interpretation")
        return calculate_fu(context, interpretation, rules)
    if evaluation.shape is WinningShape.SEVEN_PAIRS:
        return calculate_seven_pairs_fu(context)
    raise ValueError("non-yakuman shape does not support fu calculation")
