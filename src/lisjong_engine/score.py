"""翻・符・役満倍率から支払点を計算するmodule。

本moduleが扱うのは、1人の和了そのものに対する基本支払点だけである。
本場、供託、複数ロンの配分、パオの最終精算、流し満貫の局精算は後続の
Round / Match層の責務であり、ここでは扱わない。
"""

from dataclasses import dataclass
from enum import Enum

from lisjong_engine.rules import RuleSet
from lisjong_engine.win_context import WinMethod


class ScoreLimit(Enum):
    """基本点の上限区分。`NONE`は上限に達していない通常計算を表す。"""

    NONE = "none"
    MANGAN = "mangan"
    HANEMAN = "haneman"
    BAIMAN = "baiman"
    SANBAIMAN = "sanbaiman"
    YAKUMAN = "yakuman"


@dataclass(frozen=True)
class ScoreCalculation:
    """1人の和了に対する支払点と、その根拠となる入力。

    どのruleで計算した結果かを後から確認できるよう、適用した`RuleSet`も
    保持する。
    """

    han: int
    fu: int | None
    yakuman_units: int
    method: WinMethod
    is_dealer: bool
    base_points: int
    limit: ScoreLimit
    ron_payment: int | None
    tsumo_dealer_payment: int | None
    tsumo_non_dealer_payment: int | None
    rules: RuleSet

    def __post_init__(self) -> None:
        _validate_inputs(
            han=self.han,
            fu=self.fu,
            method=self.method,
            is_dealer=self.is_dealer,
            yakuman_units=self.yakuman_units,
            rules=self.rules,
        )
        if type(self.base_points) is not int or self.base_points <= 0:
            raise ValueError("base_points must be a positive int")
        if not isinstance(self.limit, ScoreLimit):
            raise TypeError("limit must be a ScoreLimit")
        for name in (
            "ron_payment",
            "tsumo_dealer_payment",
            "tsumo_non_dealer_payment",
        ):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError(f"{name} must be a positive int or None")

        expected_base_points, expected_limit = _base_points_and_limit(
            self.han,
            self.fu,
            self.yakuman_units,
            self.rules,
        )
        if self.base_points != expected_base_points or self.limit is not expected_limit:
            raise ValueError("base_points and limit must match the score inputs")
        expected_payments = _payments(
            expected_base_points,
            self.method,
            self.is_dealer,
        )
        actual_payments = (
            self.ron_payment,
            self.tsumo_dealer_payment,
            self.tsumo_non_dealer_payment,
        )
        if actual_payments != expected_payments:
            raise ValueError("payment fields must match the score inputs")

    @property
    def winner_points(self) -> int:
        """和了者が本場・供託を除いて受け取る合計点。"""
        if self.method is WinMethod.RON:
            assert self.ron_payment is not None
            return self.ron_payment
        if self.is_dealer:
            assert self.tsumo_non_dealer_payment is not None
            return self.tsumo_non_dealer_payment * 3
        assert self.tsumo_dealer_payment is not None
        assert self.tsumo_non_dealer_payment is not None
        return self.tsumo_dealer_payment + self.tsumo_non_dealer_payment * 2


def calculate_score(
    *,
    han: int,
    fu: int | None,
    method: WinMethod,
    is_dealer: bool,
    yakuman_units: int = 0,
    rules: RuleSet | None = None,
) -> ScoreCalculation:
    """翻・符または役満倍率から、本場を含まない支払点を計算する。"""
    if rules is None:
        rules = RuleSet.default()
    _validate_inputs(
        han=han,
        fu=fu,
        method=method,
        is_dealer=is_dealer,
        yakuman_units=yakuman_units,
        rules=rules,
    )
    base_points, limit = _base_points_and_limit(han, fu, yakuman_units, rules)
    ron, dealer_tsumo, non_dealer_tsumo = _payments(
        base_points,
        method,
        is_dealer,
    )
    return ScoreCalculation(
        han=han,
        fu=fu,
        yakuman_units=yakuman_units,
        method=method,
        is_dealer=is_dealer,
        base_points=base_points,
        limit=limit,
        ron_payment=ron,
        tsumo_dealer_payment=dealer_tsumo,
        tsumo_non_dealer_payment=non_dealer_tsumo,
        rules=rules,
    )


def _validate_inputs(
    *,
    han: int,
    fu: int | None,
    method: WinMethod,
    is_dealer: bool,
    yakuman_units: int,
    rules: RuleSet,
) -> None:
    if type(han) is not int or han < 0:
        raise ValueError("han must be a non-negative int")
    if not isinstance(method, WinMethod):
        raise TypeError("method must be a WinMethod")
    if type(is_dealer) is not bool:
        raise TypeError("is_dealer must be a bool")
    if type(yakuman_units) is not int or yakuman_units < 0:
        raise ValueError("yakuman_units must be a non-negative int")
    if not isinstance(rules, RuleSet):
        raise TypeError("rules must be a RuleSet")
    if yakuman_units:
        if han != 0:
            raise ValueError("an explicit yakuman must have zero han")
        if fu is not None:
            raise ValueError("an explicit yakuman must not have fu")
        return
    if han == 0:
        raise ValueError("a non-yakuman hand must have at least one han")
    if type(fu) is not int or fu <= 0:
        raise ValueError("a non-yakuman hand must have positive integer fu")


def _base_points_and_limit(
    han: int,
    fu: int | None,
    yakuman_units: int,
    rules: RuleSet,
) -> tuple[int, ScoreLimit]:
    """基本点と上限区分を返す。

    明示的な役満は倍率をそのまま基本点へ反映し、数え役満は倍率に関わらず
    常に1倍役満として扱う。
    """
    if yakuman_units:
        effective_units = yakuman_units if rules.multiple_yakuman_enabled else 1
        return 8_000 * effective_units, ScoreLimit.YAKUMAN
    assert fu is not None
    if han >= 13:
        if rules.counted_yakuman_enabled:
            return 8_000, ScoreLimit.YAKUMAN
        return 6_000, ScoreLimit.SANBAIMAN
    if han >= 11:
        return 6_000, ScoreLimit.SANBAIMAN
    if han >= 8:
        return 4_000, ScoreLimit.BAIMAN
    if han >= 6:
        return 3_000, ScoreLimit.HANEMAN
    if han >= 5 or (han == 4 and fu >= 40) or (han == 3 and fu >= 70):
        return 2_000, ScoreLimit.MANGAN
    if rules.rounded_mangan_enabled and (
        (han == 4 and fu == 30) or (han == 3 and fu == 60)
    ):
        return 2_000, ScoreLimit.MANGAN
    return fu * 2 ** (han + 2), ScoreLimit.NONE


def _payments(
    base_points: int,
    method: WinMethod,
    is_dealer: bool,
) -> tuple[int | None, int | None, int | None]:
    """ロン・ツモ別の支払点を、それぞれ100点単位へ切り上げて返す。"""
    if method is WinMethod.RON:
        multiplier = 6 if is_dealer else 4
        return _round_up_to_hundred(base_points * multiplier), None, None
    if is_dealer:
        return None, None, _round_up_to_hundred(base_points * 2)
    return (
        None,
        _round_up_to_hundred(base_points * 2),
        _round_up_to_hundred(base_points),
    )


def _round_up_to_hundred(points: int) -> int:
    return ((points + 99) // 100) * 100
