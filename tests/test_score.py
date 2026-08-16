import unittest
from dataclasses import replace

from lisjong_engine.rules import RuleSet
from lisjong_engine.score import ScoreCalculation, ScoreLimit, calculate_score
from lisjong_engine.win_context import WinMethod


class NormalScoreTest(unittest.TestCase):
    def test_representative_ron_scores(self) -> None:
        cases = (
            (1, 30, False, 1_000),
            (1, 30, True, 1_500),
            (2, 40, False, 2_600),
            (3, 30, False, 3_900),
            (4, 30, False, 7_700),
            (4, 30, True, 11_600),
            (3, 60, False, 7_700),
            (3, 60, True, 11_600),
        )
        for han, fu, is_dealer, expected in cases:
            with self.subTest(han=han, fu=fu, is_dealer=is_dealer):
                result = calculate_score(
                    han=han,
                    fu=fu,
                    method=WinMethod.RON,
                    is_dealer=is_dealer,
                )
                self.assertEqual(result.ron_payment, expected)
                self.assertIs(result.limit, ScoreLimit.NONE)
                self.assertIsNone(result.tsumo_dealer_payment)
                self.assertIsNone(result.tsumo_non_dealer_payment)

    def test_representative_tsumo_scores(self) -> None:
        child = calculate_score(
            han=1,
            fu=30,
            method=WinMethod.TSUMO,
            is_dealer=False,
        )
        dealer = calculate_score(
            han=1,
            fu=30,
            method=WinMethod.TSUMO,
            is_dealer=True,
        )

        self.assertEqual(child.tsumo_dealer_payment, 500)
        self.assertEqual(child.tsumo_non_dealer_payment, 300)
        self.assertEqual(dealer.tsumo_non_dealer_payment, 500)
        self.assertIsNone(dealer.tsumo_dealer_payment)
        self.assertIsNone(child.ron_payment)
        self.assertIsNone(dealer.ron_payment)

    def test_omitted_rules_use_the_default_rule_set(self) -> None:
        result = calculate_score(
            han=1,
            fu=30,
            method=WinMethod.RON,
            is_dealer=False,
        )

        self.assertEqual(result.rules, RuleSet.default())


class LimitScoreTest(unittest.TestCase):
    def test_rounded_mangan_rule_can_be_enabled(self) -> None:
        enabled_rules = replace(RuleSet.default(), rounded_mangan_enabled=True)
        for han, fu in ((4, 30), (3, 60)):
            with self.subTest(han=han, fu=fu):
                standard = calculate_score(
                    han=han,
                    fu=fu,
                    method=WinMethod.RON,
                    is_dealer=False,
                )
                rounded = calculate_score(
                    han=han,
                    fu=fu,
                    method=WinMethod.RON,
                    is_dealer=False,
                    rules=enabled_rules,
                )

                self.assertIs(standard.limit, ScoreLimit.NONE)
                self.assertIs(rounded.limit, ScoreLimit.MANGAN)
                self.assertEqual(rounded.ron_payment, 8_000)

    def test_mangan_boundaries(self) -> None:
        cases = ((3, 70), (4, 40), (5, 20))
        for han, fu in cases:
            with self.subTest(han=han, fu=fu):
                result = calculate_score(
                    han=han,
                    fu=fu,
                    method=WinMethod.RON,
                    is_dealer=False,
                )
                self.assertIs(result.limit, ScoreLimit.MANGAN)
                self.assertEqual(result.base_points, 2_000)
                self.assertEqual(result.ron_payment, 8_000)

    def test_child_ron_limit_scores(self) -> None:
        cases = (
            (5, ScoreLimit.MANGAN, 8_000),
            (6, ScoreLimit.HANEMAN, 12_000),
            (8, ScoreLimit.BAIMAN, 16_000),
            (11, ScoreLimit.SANBAIMAN, 24_000),
            (13, ScoreLimit.YAKUMAN, 32_000),
        )
        for han, limit, expected in cases:
            with self.subTest(limit=limit):
                result = calculate_score(
                    han=han,
                    fu=30,
                    method=WinMethod.RON,
                    is_dealer=False,
                )
                self.assertIs(result.limit, limit)
                self.assertEqual(result.ron_payment, expected)

    def test_dealer_ron_limit_scores(self) -> None:
        cases = (
            (5, ScoreLimit.MANGAN, 12_000),
            (6, ScoreLimit.HANEMAN, 18_000),
            (8, ScoreLimit.BAIMAN, 24_000),
            (11, ScoreLimit.SANBAIMAN, 36_000),
            (13, ScoreLimit.YAKUMAN, 48_000),
        )
        for han, limit, expected in cases:
            with self.subTest(limit=limit):
                result = calculate_score(
                    han=han,
                    fu=30,
                    method=WinMethod.RON,
                    is_dealer=True,
                )
                self.assertIs(result.limit, limit)
                self.assertEqual(result.ron_payment, expected)

    def test_mangan_and_yakuman_tsumo_scores(self) -> None:
        cases = (
            (5, 0, False, 4_000, 2_000),
            (5, 0, True, None, 4_000),
            (0, 1, False, 16_000, 8_000),
            (0, 1, True, None, 16_000),
        )
        for han, units, is_dealer, dealer_payment, child_payment in cases:
            with self.subTest(han=han, units=units, is_dealer=is_dealer):
                result = calculate_score(
                    han=han,
                    fu=None if units else 30,
                    method=WinMethod.TSUMO,
                    is_dealer=is_dealer,
                    yakuman_units=units,
                )
                self.assertEqual(result.tsumo_dealer_payment, dealer_payment)
                self.assertEqual(result.tsumo_non_dealer_payment, child_payment)


class YakumanScoreTest(unittest.TestCase):
    def test_counted_yakuman_rule_can_be_disabled(self) -> None:
        disabled_rules = replace(RuleSet.default(), counted_yakuman_enabled=False)

        enabled = calculate_score(
            han=13,
            fu=30,
            method=WinMethod.RON,
            is_dealer=False,
        )
        disabled = calculate_score(
            han=13,
            fu=30,
            method=WinMethod.RON,
            is_dealer=False,
            rules=disabled_rules,
        )

        self.assertIs(enabled.limit, ScoreLimit.YAKUMAN)
        self.assertEqual(enabled.ron_payment, 32_000)
        self.assertIs(disabled.limit, ScoreLimit.SANBAIMAN)
        self.assertEqual(disabled.ron_payment, 24_000)

    def test_multiple_yakuman_rule_can_be_disabled(self) -> None:
        disabled_rules = replace(RuleSet.default(), multiple_yakuman_enabled=False)

        enabled = calculate_score(
            han=0,
            fu=None,
            method=WinMethod.RON,
            is_dealer=False,
            yakuman_units=2,
        )
        disabled = calculate_score(
            han=0,
            fu=None,
            method=WinMethod.RON,
            is_dealer=False,
            yakuman_units=2,
            rules=disabled_rules,
        )

        self.assertEqual(enabled.ron_payment, 64_000)
        self.assertEqual(disabled.ron_payment, 32_000)
        self.assertEqual(disabled.yakuman_units, 2)

    def test_counted_yakuman_is_always_single_yakuman(self) -> None:
        cases = (
            (12, ScoreLimit.SANBAIMAN, 6_000),
            (13, ScoreLimit.YAKUMAN, 8_000),
            (26, ScoreLimit.YAKUMAN, 8_000),
        )
        for han, limit, base_points in cases:
            with self.subTest(han=han):
                result = calculate_score(
                    han=han,
                    fu=30,
                    method=WinMethod.RON,
                    is_dealer=False,
                )
                self.assertIs(result.limit, limit)
                self.assertEqual(result.base_points, base_points)

    def test_explicit_yakuman_units_support_all_payments(self) -> None:
        for units in (1, 2, 3):
            for is_dealer in (False, True):
                for method in WinMethod:
                    with self.subTest(
                        units=units,
                        is_dealer=is_dealer,
                        method=method,
                    ):
                        result = calculate_score(
                            han=0,
                            fu=None,
                            method=method,
                            is_dealer=is_dealer,
                            yakuman_units=units,
                        )
                        base_points = 8_000 * units
                        self.assertIs(result.limit, ScoreLimit.YAKUMAN)
                        self.assertIsNone(result.fu)
                        self.assertEqual(result.base_points, base_points)
                        if method is WinMethod.RON:
                            multiplier = 6 if is_dealer else 4
                            self.assertEqual(
                                result.ron_payment,
                                base_points * multiplier,
                            )
                        elif is_dealer:
                            self.assertEqual(
                                result.tsumo_non_dealer_payment,
                                base_points * 2,
                            )
                        else:
                            self.assertEqual(
                                result.tsumo_dealer_payment,
                                base_points * 2,
                            )
                            self.assertEqual(
                                result.tsumo_non_dealer_payment,
                                base_points,
                            )


class RoundingTest(unittest.TestCase):
    def test_each_tsumo_payment_is_rounded_individually(self) -> None:
        result = calculate_score(
            han=1,
            fu=30,
            method=WinMethod.TSUMO,
            is_dealer=False,
        )

        self.assertEqual(result.base_points, 240)
        self.assertEqual(result.tsumo_dealer_payment, 500)
        self.assertEqual(result.tsumo_non_dealer_payment, 300)
        self.assertEqual(
            result.tsumo_dealer_payment + result.tsumo_non_dealer_payment * 2,
            1_100,
        )


class WinnerPointsTest(unittest.TestCase):
    def test_winner_points_equals_total_payments(self) -> None:
        cases = (
            (WinMethod.RON, False, 1_000),
            (WinMethod.RON, True, 1_500),
            (WinMethod.TSUMO, False, 1_100),
            (WinMethod.TSUMO, True, 1_500),
        )
        for method, is_dealer, expected in cases:
            with self.subTest(method=method, is_dealer=is_dealer):
                result = calculate_score(
                    han=1,
                    fu=30,
                    method=method,
                    is_dealer=is_dealer,
                )
                self.assertEqual(result.winner_points, expected)
                if method is WinMethod.RON:
                    self.assertEqual(result.winner_points, result.ron_payment)
                elif is_dealer:
                    self.assertEqual(
                        result.winner_points,
                        result.tsumo_non_dealer_payment * 3,
                    )
                else:
                    self.assertEqual(
                        result.winner_points,
                        result.tsumo_dealer_payment
                        + result.tsumo_non_dealer_payment * 2,
                    )


class ScoreValidationTest(unittest.TestCase):
    def test_rejects_invalid_inputs(self) -> None:
        valid = {
            "han": 1,
            "fu": 30,
            "method": WinMethod.RON,
            "is_dealer": False,
            "yakuman_units": 0,
        }
        invalid_changes = (
            ("han", True, ValueError),
            ("han", -1, ValueError),
            ("han", 0, ValueError),
            ("fu", True, ValueError),
            ("fu", None, ValueError),
            ("fu", 0, ValueError),
            ("fu", -1, ValueError),
            ("method", "ron", TypeError),
            ("is_dealer", 1, TypeError),
            ("yakuman_units", True, ValueError),
            ("yakuman_units", -1, ValueError),
            ("rules", "project-standard-v1", TypeError),
        )
        for name, value, error in invalid_changes:
            with self.subTest(name=name, value=value), self.assertRaises(error):
                calculate_score(**(valid | {name: value}))

    def test_explicit_yakuman_uses_none_fu(self) -> None:
        result = calculate_score(
            han=0,
            fu=None,
            method=WinMethod.RON,
            is_dealer=False,
            yakuman_units=1,
        )

        self.assertEqual(result.han, 0)
        self.assertIsNone(result.fu)
        self.assertEqual(result.base_points, 8_000)

    def test_rejects_fu_or_han_on_explicit_yakuman(self) -> None:
        invalid_cases = (
            {"han": 0, "fu": 30, "yakuman_units": 1},
            {"han": 1, "fu": None, "yakuman_units": 1},
            {"han": 13, "fu": 30, "yakuman_units": 1},
        )
        for arguments in invalid_cases:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                calculate_score(
                    method=WinMethod.RON,
                    is_dealer=False,
                    **arguments,
                )

    def test_counted_yakuman_keeps_actual_fu(self) -> None:
        result = calculate_score(
            han=13,
            fu=40,
            method=WinMethod.RON,
            is_dealer=False,
        )

        self.assertEqual(result.fu, 40)
        self.assertEqual(result.yakuman_units, 0)
        self.assertIs(result.limit, ScoreLimit.YAKUMAN)

    def test_result_model_rejects_inconsistent_values(self) -> None:
        valid = calculate_score(
            han=1,
            fu=30,
            method=WinMethod.RON,
            is_dealer=False,
        )
        values = {
            "han": valid.han,
            "fu": valid.fu,
            "yakuman_units": valid.yakuman_units,
            "method": valid.method,
            "is_dealer": valid.is_dealer,
            "base_points": valid.base_points,
            "limit": valid.limit,
            "ron_payment": valid.ron_payment,
            "tsumo_dealer_payment": valid.tsumo_dealer_payment,
            "tsumo_non_dealer_payment": valid.tsumo_non_dealer_payment,
            "rules": valid.rules,
        }
        invalid_changes = (
            ("base_points", 2_000, ValueError),
            ("limit", ScoreLimit.MANGAN, ValueError),
            ("limit", "none", TypeError),
            ("ron_payment", 1_100, ValueError),
            ("tsumo_dealer_payment", 500, ValueError),
            ("rules", None, TypeError),
        )
        for name, value, error in invalid_changes:
            with self.subTest(name=name), self.assertRaises(error):
                ScoreCalculation(**(values | {name: value}))

    def test_result_keeps_the_applied_rule_set(self) -> None:
        rules = replace(RuleSet.default(), rounded_mangan_enabled=True)

        result = calculate_score(
            han=4,
            fu=30,
            method=WinMethod.RON,
            is_dealer=False,
            rules=rules,
        )

        self.assertEqual(result.rules, rules)
        self.assertIs(result.limit, ScoreLimit.MANGAN)


if __name__ == "__main__":
    unittest.main()
