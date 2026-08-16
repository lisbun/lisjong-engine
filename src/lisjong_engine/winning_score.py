"""和了得点候補の列挙と、最高得点候補の選択を担当するmodule。

得点評価層の最上位境界であり、次を入力とする純粋な評価層である。

```text
WinningContext + DoraIndicators + winning interpretations + RuleSet
    -> WinningScoreSelection
```

複数の和了解釈をすべて個別に評価し、途中で代表候補へ絞らない。候補の比較は
翻数ではなく最終的な`winner_points`で行い、同点の最良候補は1つへ潰さずに
すべて保持する。候補の集合順序に意味は持たせない。

本場・供託・複数ロンの配分・パオの最終精算は後続のRound / Match層の責務で
あり、ここでは扱わない。
"""

from collections.abc import Iterable
from dataclasses import dataclass

from lisjong_engine.dora import DoraCount, DoraIndicators, count_dora
from lisjong_engine.hand_value import HandValueEvaluation, evaluate_hand_value
from lisjong_engine.rules import RuleSet
from lisjong_engine.score import ScoreCalculation, calculate_score
from lisjong_engine.win_context import WinningContext
from lisjong_engine.wind import Wind


@dataclass(frozen=True)
class WinningScoreCandidate:
    """1つの和了解釈について、役・符・ドラ評価と支払点を結び付ける。"""

    hand_value: HandValueEvaluation
    score: ScoreCalculation

    def __post_init__(self) -> None:
        if not isinstance(self.hand_value, HandValueEvaluation):
            raise TypeError("hand_value must be a HandValueEvaluation")
        if not isinstance(self.score, ScoreCalculation):
            raise TypeError("score must be a ScoreCalculation")

    @property
    def winner_points(self) -> int:
        return self.score.winner_points


@dataclass(frozen=True)
class WinningScoreSelection:
    """全得点候補と、同点を保持した最高得点候補の集合。"""

    candidates: frozenset[WinningScoreCandidate]
    max_score_candidates: frozenset[WinningScoreCandidate]

    def __post_init__(self) -> None:
        try:
            candidates = frozenset(self.candidates)
            max_score_candidates = frozenset(self.max_score_candidates)
        except TypeError:
            raise TypeError(
                "candidate collections must be iterables of WinningScoreCandidate"
            ) from None
        if any(
            not isinstance(candidate, WinningScoreCandidate)
            for candidate in candidates | max_score_candidates
        ):
            raise TypeError(
                "candidate collections must contain only "
                "WinningScoreCandidate instances"
            )
        if not candidates:
            raise ValueError("candidates must not be empty")
        if not max_score_candidates:
            raise ValueError("max_score_candidates must not be empty")
        if not max_score_candidates <= candidates:
            raise ValueError("max_score_candidates must be a subset of candidates")
        if max_score_candidates != select_max_score_candidates(candidates):
            raise ValueError(
                "max_score_candidates must contain every maximum-score candidate"
            )
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "max_score_candidates", max_score_candidates)


def enumerate_winning_score_candidates(
    context: WinningContext,
    *,
    dora_indicators: DoraIndicators | None = None,
    rules: RuleSet | None = None,
) -> frozenset[WinningScoreCandidate]:
    """成立した各和了解釈を、それぞれの符を保ったまま得点候補へ変換する。

    役が1つも成立しなければ空集合を返す。構造上の和了形と、得点付きの
    有効な和了はここで分離される。
    """
    if rules is None:
        rules = RuleSet.default()
    elif not isinstance(rules, RuleSet):
        raise TypeError("rules must be a RuleSet")
    dora_count = _dora_count(context, dora_indicators)
    hand_values = evaluate_hand_value(
        context,
        dora_count=dora_count,
        rules=rules,
    )

    is_dealer = context.seat_wind is Wind.EAST
    candidates = set()
    for hand_value in hand_values:
        yakuman_units = hand_value.yaku_evaluation.yakuman_units
        if yakuman_units:
            han = 0
            fu = None
        else:
            fu_calculation = hand_value.fu_calculation
            assert fu_calculation is not None
            han = hand_value.total_han
            fu = fu_calculation.rounded_fu
        score = calculate_score(
            han=han,
            fu=fu,
            method=context.method,
            is_dealer=is_dealer,
            yakuman_units=yakuman_units,
            rules=rules,
        )
        candidates.add(WinningScoreCandidate(hand_value, score))
    return frozenset(candidates)


def select_max_score_candidates(
    candidates: Iterable[WinningScoreCandidate],
) -> frozenset[WinningScoreCandidate]:
    """和了者の獲得点が最大の候補を、同点を失わずに返す。"""
    candidate_tuple = tuple(candidates)
    if any(
        not isinstance(candidate, WinningScoreCandidate)
        for candidate in candidate_tuple
    ):
        raise TypeError("candidates must contain only WinningScoreCandidate instances")
    if not candidate_tuple:
        raise ValueError("candidates must not be empty")

    maximum = max(candidate.winner_points for candidate in candidate_tuple)
    return frozenset(
        candidate for candidate in candidate_tuple if candidate.winner_points == maximum
    )


def evaluate_winning_scores(
    context: WinningContext,
    *,
    dora_indicators: DoraIndicators | None = None,
    rules: RuleSet | None = None,
) -> WinningScoreSelection:
    """全得点候補と、同点を保持した最高得点候補を返す。

    役なしで候補が1つもない場合は`ValueError`を送出する。和了形の有無だけを
    知りたい場合は`winning.is_winning_shape()`を使う。
    """
    candidates = enumerate_winning_score_candidates(
        context,
        dora_indicators=dora_indicators,
        rules=rules,
    )
    return WinningScoreSelection(
        candidates,
        select_max_score_candidates(candidates),
    )


def _dora_count(
    context: WinningContext,
    dora_indicators: DoraIndicators | None,
) -> DoraCount | None:
    if dora_indicators is None:
        return None
    return count_dora(context, dora_indicators)
