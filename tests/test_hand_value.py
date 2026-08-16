import unittest
from dataclasses import replace

from lisjong_engine.dora import DoraCount
from lisjong_engine.fu import FuReason, calculate_fu
from lisjong_engine.hand_value import HandValueEvaluation, evaluate_hand_value
from lisjong_engine.rules import RuleSet
from lisjong_engine.tile import STANDARD_TILES, Tile, TileCategory, TileType
from lisjong_engine.win_context import WinMethod, WinningContext, WinOrigin
from lisjong_engine.wind import Wind
from lisjong_engine.winning import WinningShape
from lisjong_engine.yaku import Yaku
from lisjong_engine.yaku_evaluation import evaluate_yaku

_CATEGORIES = {
    "m": TileCategory.MANZU,
    "p": TileCategory.PINZU,
    "s": TileCategory.SOUZU,
    "z": TileCategory.HONOR,
}

_RYANPEIKOU_NAMES = (
    "1m",
    "1m",
    "2m",
    "2m",
    "3m",
    "3m",
    "4m",
    "4m",
    "5m",
    "5m",
    "6m",
    "6m",
    "7m",
    "7m",
)
_TSUUIISOU_NAMES = (
    "1z",
    "1z",
    "2z",
    "2z",
    "3z",
    "3z",
    "4z",
    "4z",
    "5z",
    "5z",
    "6z",
    "6z",
    "7z",
    "7z",
)


def _tiles(*names: str) -> tuple[Tile, ...]:
    copy_counts: dict[TileType, int] = {}
    tiles = []
    for name in names:
        tile_type = TileType(_CATEGORIES[name[-1]], int(name[:-1]))
        copy_index = copy_counts.get(tile_type, 0)
        tiles.append(STANDARD_TILES[tile_type.id * 4 + copy_index])
        copy_counts[tile_type] = copy_index + 1
    return tuple(tiles)


def _context(*names: str) -> WinningContext:
    tiles = _tiles(*names)
    return WinningContext(
        concealed_tiles=tiles,
        winning_tile=tiles[-1],
        method=WinMethod.RON,
        origin=WinOrigin.DISCARD,
        seat_wind=Wind.SOUTH,
        prevailing_wind=Wind.EAST,
    )


class HandValueEvaluationTest(unittest.TestCase):
    def test_preserves_all_standard_and_seven_pairs_candidates(self) -> None:
        context = _context(*_RYANPEIKOU_NAMES)
        dora_count = DoraCount(visible=2)

        evaluations = evaluate_hand_value(context, dora_count=dora_count)

        self.assertEqual(
            {evaluation.yaku_evaluation for evaluation in evaluations},
            set(evaluate_yaku(context)),
        )
        self.assertEqual(
            {evaluation.yaku_evaluation.shape for evaluation in evaluations},
            {WinningShape.STANDARD, WinningShape.SEVEN_PAIRS},
        )
        for evaluation in evaluations:
            with self.subTest(shape=evaluation.yaku_evaluation.shape):
                self.assertEqual(
                    evaluation.total_han,
                    evaluation.yaku_evaluation.han + 2,
                )
                self.assertIsNotNone(evaluation.fu_calculation)
                if evaluation.yaku_evaluation.shape is WinningShape.STANDARD:
                    interpretation = evaluation.yaku_evaluation.standard_interpretation
                    self.assertIsNotNone(interpretation)
                    self.assertEqual(
                        evaluation.fu_calculation,
                        calculate_fu(context, interpretation),
                    )
                else:
                    self.assertEqual(evaluation.fu_calculation.raw_fu, 25)
                    self.assertEqual(evaluation.fu_calculation.rounded_fu, 25)

    def test_dora_count_is_kept_and_added_to_total_han(self) -> None:
        context = _context(*_RYANPEIKOU_NAMES)
        dora_count = DoraCount(visible=1, red=1)

        evaluations = evaluate_hand_value(context, dora_count=dora_count)

        self.assertTrue(evaluations)
        for evaluation in evaluations:
            with self.subTest(shape=evaluation.yaku_evaluation.shape):
                self.assertEqual(evaluation.dora_count, dora_count)
                self.assertEqual(evaluation.dora_han, 2)
                self.assertEqual(
                    evaluation.total_han,
                    evaluation.yaku_evaluation.han + 2,
                )

    def test_omitted_dora_count_adds_no_han(self) -> None:
        context = _context(*_RYANPEIKOU_NAMES)

        evaluations = evaluate_hand_value(context)

        self.assertTrue(evaluations)
        for evaluation in evaluations:
            with self.subTest(shape=evaluation.yaku_evaluation.shape):
                self.assertIsNone(evaluation.dora_count)
                self.assertEqual(evaluation.dora_han, 0)
                self.assertEqual(evaluation.total_han, evaluation.yaku_evaluation.han)

    def test_yakuman_candidate_has_no_fu_calculation_and_drops_dora(self) -> None:
        context = _context(*_TSUUIISOU_NAMES)

        evaluations = evaluate_hand_value(context, dora_count=DoraCount(visible=2))

        self.assertTrue(evaluations)
        for evaluation in evaluations:
            with self.subTest(shape=evaluation.yaku_evaluation.shape):
                self.assertTrue(evaluation.yaku_evaluation.yakuman_units)
                self.assertIsNone(evaluation.fu_calculation)
                self.assertIsNone(evaluation.dora_count)
                self.assertEqual(evaluation.dora_han, 0)
                self.assertEqual(evaluation.total_han, 0)

    def test_rejects_fu_that_does_not_match_evaluation_shape(self) -> None:
        context = _context(*_RYANPEIKOU_NAMES)
        evaluations = evaluate_hand_value(context)
        standard = next(
            evaluation
            for evaluation in evaluations
            if evaluation.yaku_evaluation.shape is WinningShape.STANDARD
        )
        seven_pairs = next(
            evaluation
            for evaluation in evaluations
            if evaluation.yaku_evaluation.shape is WinningShape.SEVEN_PAIRS
        )

        with self.assertRaises(ValueError):
            HandValueEvaluation(
                standard.yaku_evaluation,
                seven_pairs.fu_calculation,
            )
        with self.assertRaises(ValueError):
            HandValueEvaluation(
                seven_pairs.yaku_evaluation,
                standard.fu_calculation,
            )

    def test_rejects_missing_or_unexpected_fu_calculation(self) -> None:
        normal = next(iter(evaluate_hand_value(_context(*_RYANPEIKOU_NAMES))))
        yakuman = next(iter(evaluate_hand_value(_context(*_TSUUIISOU_NAMES))))

        with self.assertRaises(ValueError):
            HandValueEvaluation(normal.yaku_evaluation, None)
        with self.assertRaises(ValueError):
            HandValueEvaluation(
                yakuman.yaku_evaluation,
                normal.fu_calculation,
            )

    def test_rejects_invalid_field_types(self) -> None:
        normal = next(iter(evaluate_hand_value(_context(*_RYANPEIKOU_NAMES))))

        with self.assertRaises(TypeError):
            HandValueEvaluation("chiitoitsu", normal.fu_calculation)
        with self.assertRaises(TypeError):
            HandValueEvaluation(normal.yaku_evaluation, 25)
        with self.assertRaises(TypeError):
            HandValueEvaluation(
                normal.yaku_evaluation,
                normal.fu_calculation,
                dora_count=2,
            )

    def test_standard_fu_does_not_use_seven_pairs_component(self) -> None:
        context = _context(*_RYANPEIKOU_NAMES)

        standard_results = (
            evaluation
            for evaluation in evaluate_hand_value(context)
            if evaluation.yaku_evaluation.shape is WinningShape.STANDARD
        )

        self.assertTrue(
            all(
                component.reason is not FuReason.SEVEN_PAIRS
                for evaluation in standard_results
                for component in evaluation.fu_calculation.components
            )
        )

    def test_yakuless_hand_has_no_hand_value(self) -> None:
        context = _context(
            "1m",
            "2m",
            "3m",
            "4m",
            "5m",
            "6m",
            "7p",
            "8p",
            "9p",
            "1s",
            "2s",
            "3s",
            "5p",
            "5p",
        )

        self.assertEqual(
            evaluate_hand_value(context, dora_count=DoraCount(visible=5)),
            frozenset(),
        )

    def test_rejects_invalid_arguments(self) -> None:
        context = _context(*_RYANPEIKOU_NAMES)

        with self.assertRaises(TypeError):
            evaluate_hand_value(())
        with self.assertRaises(TypeError):
            evaluate_hand_value(context, dora_count=2)
        with self.assertRaises(TypeError):
            evaluate_hand_value(context, rules="project-standard-v1")

    def test_rules_flow_into_fu_and_yakuman_units(self) -> None:
        double_wind_tiles = _tiles(
            "2m",
            "2m",
            "2m",
            "1p",
            "2p",
            "3p",
            "4p",
            "6p",
            "7s",
            "8s",
            "9s",
            "1z",
            "1z",
            "5p",
        )
        double_wind_context = WinningContext(
            concealed_tiles=double_wind_tiles,
            winning_tile=double_wind_tiles[-1],
            method=WinMethod.TSUMO,
            origin=WinOrigin.LIVE_WALL,
            seat_wind=Wind.EAST,
            prevailing_wind=Wind.EAST,
        )
        two_fu_rules = replace(RuleSet.default(), double_wind_pair_fu=2)
        suuankou_context = _context(
            "1m",
            "1m",
            "1m",
            "2p",
            "2p",
            "2p",
            "3s",
            "3s",
            "3s",
            "4z",
            "4z",
            "4z",
            "5m",
            "5m",
        )
        double_yakuman_rules = replace(
            RuleSet.default(),
            double_yakuman_variants=frozenset({Yaku.SUUANKOU_TANKI}),
        )

        default_fu = {
            evaluation.fu_calculation.rounded_fu
            for evaluation in evaluate_hand_value(double_wind_context)
        }
        custom_fu = {
            evaluation.fu_calculation.rounded_fu
            for evaluation in evaluate_hand_value(
                double_wind_context,
                rules=two_fu_rules,
            )
        }
        default_units = {
            evaluation.yaku_evaluation.yakuman_units
            for evaluation in evaluate_hand_value(suuankou_context)
        }
        custom_units = {
            evaluation.yaku_evaluation.yakuman_units
            for evaluation in evaluate_hand_value(
                suuankou_context,
                rules=double_yakuman_rules,
            )
        }

        self.assertEqual(default_fu, {40})
        self.assertEqual(custom_fu, {30})
        self.assertEqual(default_units, {1})
        self.assertEqual(custom_units, {2})


if __name__ == "__main__":
    unittest.main()
