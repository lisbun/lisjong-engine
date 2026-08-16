import unittest
from dataclasses import FrozenInstanceError, fields, replace

from lisjong_engine.rules import (
    FinalPointsRounding,
    FinalRankTiePolicy,
    KanDoraRevealPolicy,
    MatchFormat,
    MultipleRonAwardPolicy,
    PaoCompoundYakumanPolicy,
    RiichiAnkanPolicy,
    RonResolutionPolicy,
    RuleSet,
)
from lisjong_engine.yaku import Yaku


class DefaultRuleSetTest(unittest.TestCase):
    """`RuleSet.default()`が表現する`project-standard-v1`の契約。"""

    def test_identity_values(self) -> None:
        rules = RuleSet.default()

        self.assertEqual(rules.name, "project-standard-v1")
        self.assertEqual(rules.version, 1)
        self.assertIs(rules.match_format, MatchFormat.HANCHAN)
        self.assertEqual(rules.player_count, 4)

    def test_points_and_rank_point_values(self) -> None:
        rules = RuleSet.default()

        self.assertEqual(rules.starting_points, 25_000)
        self.assertEqual(rules.return_points, 30_000)
        self.assertEqual(rules.first_place_target_points, 30_000)
        self.assertEqual(rules.uma, (30, 10, -10, -30))
        self.assertEqual(sum(rules.uma), 0)
        self.assertEqual(rules.oka_points, 20_000)
        self.assertEqual(rules.oka_rank_points, 20)

    def test_end_condition_values(self) -> None:
        rules = RuleSet.default()

        self.assertTrue(rules.bankruptcy_enabled)
        self.assertEqual(rules.bankruptcy_threshold, 0)
        self.assertTrue(rules.west_round_enabled)
        self.assertTrue(rules.dealer_win_end_enabled)
        self.assertTrue(rules.dealer_tenpai_end_enabled)

    def test_scoring_values(self) -> None:
        rules = RuleSet.default()

        self.assertFalse(rules.rounded_mangan_enabled)
        self.assertTrue(rules.counted_yakuman_enabled)
        self.assertTrue(rules.multiple_yakuman_enabled)

    def test_honba_stick_and_penalty_values(self) -> None:
        rules = RuleSet.default()

        self.assertEqual(rules.ron_honba_points, 300)
        self.assertEqual(rules.tsumo_honba_points_per_payer, 100)
        self.assertEqual(rules.riichi_stick_points, 1_000)
        self.assertEqual(rules.noten_penalty_total, 3_000)
        self.assertTrue(rules.nagashi_mangan_enabled)

    def test_pao_values(self) -> None:
        rules = RuleSet.default()

        self.assertTrue(rules.pao_enabled)
        self.assertEqual(rules.pao_yaku, frozenset({Yaku.DAISANGEN, Yaku.DAISUUSHII}))
        self.assertIs(
            rules.pao_compound_yakuman_policy,
            PaoCompoundYakumanPolicy.FULL_HAND,
        )

    def test_multiple_ron_values(self) -> None:
        rules = RuleSet.default()

        self.assertTrue(rules.double_ron_enabled)
        self.assertIs(rules.ron_resolution_policy, RonResolutionPolicy.MULTIPLE_RON)
        self.assertTrue(rules.triple_ron_abortive_draw)
        self.assertIs(
            rules.multiple_ron_honba_policy,
            MultipleRonAwardPolicy.NEAREST_WINNER_TO_DISCARDER,
        )
        self.assertIs(
            rules.multiple_ron_riichi_stick_policy,
            MultipleRonAwardPolicy.NEAREST_WINNER_TO_DISCARDER,
        )

    def test_abortive_draw_values(self) -> None:
        rules = RuleSet.default()

        self.assertTrue(rules.nine_terminals_abortive_draw_enabled)
        self.assertTrue(rules.four_winds_abortive_draw_enabled)
        self.assertTrue(rules.four_kans_abortive_draw_enabled)
        self.assertTrue(rules.four_riichi_abortive_draw_enabled)

    def test_final_score_values(self) -> None:
        rules = RuleSet.default()

        self.assertIs(
            rules.final_points_rounding,
            FinalPointsRounding.TOWARD_ZERO_REMAINDER_TO_FIRST,
        )
        self.assertIs(rules.final_rank_tie_policy, FinalRankTiePolicy.SEAT_ORDER)
        self.assertEqual(rules.bankruptcy_bonus_points, 10)
        self.assertEqual(rules.bankrupt_player_penalty_points, -10)
        self.assertEqual(
            rules.bankruptcy_bonus_points + rules.bankrupt_player_penalty_points,
            0,
        )

    def test_riichi_and_kan_values(self) -> None:
        rules = RuleSet.default()

        self.assertIs(
            rules.riichi_ankan_policy,
            RiichiAnkanPolicy.PRESERVE_WAIT_AND_DECOMPOSITION,
        )
        self.assertIs(
            rules.kan_dora_reveal_policy,
            KanDoraRevealPolicy.DELAY_OPEN_KAN_DORA,
        )
        self.assertFalse(rules.kokushi_ankan_chankan_enabled)
        self.assertEqual(rules.riichi_minimum_points, 1_000)
        self.assertEqual(rules.riichi_minimum_live_wall_tiles, 4)

    def test_absorbed_yaku_and_fu_config_values(self) -> None:
        # 旧`YakuRules`・`FuRules`の標準値が`RuleSet`自身へ統合されている。
        rules = RuleSet.default()

        self.assertEqual(rules.double_yakuman_variants, frozenset())
        self.assertEqual(rules.double_wind_pair_fu, 4)

    def test_repeated_calls_are_equal_values(self) -> None:
        # 等価であることは契約とするが、同一instanceであることは契約しない。
        self.assertEqual(RuleSet.default(), RuleSet.default())


class RuleSetImmutabilityTest(unittest.TestCase):
    def test_is_frozen(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            RuleSet.default().starting_points = 30_000

    def test_is_hashable(self) -> None:
        self.assertEqual(
            len({RuleSet.default(), RuleSet.default()}),
            1,
        )

    def test_uma_is_normalized_to_a_tuple(self) -> None:
        rules = replace(RuleSet.default(), uma=[20, 10, -10, -20])

        self.assertIsInstance(rules.uma, tuple)
        self.assertEqual(rules.uma, (20, 10, -10, -20))

    def test_yaku_sets_are_normalized_to_frozensets(self) -> None:
        rules = replace(
            RuleSet.default(),
            pao_yaku=[Yaku.DAISANGEN, Yaku.DAISUUSHII],
            double_yakuman_variants=[Yaku.SUUANKOU_TANKI],
        )

        self.assertIsInstance(rules.pao_yaku, frozenset)
        self.assertIsInstance(rules.double_yakuman_variants, frozenset)
        self.assertEqual(rules.pao_yaku, frozenset({Yaku.DAISANGEN, Yaku.DAISUUSHII}))
        self.assertEqual(
            rules.double_yakuman_variants,
            frozenset({Yaku.SUUANKOU_TANKI}),
        )


class RuleSetValidationTest(unittest.TestCase):
    def test_rejects_invalid_field_types(self) -> None:
        cases = (
            ("name", 1),
            ("version", True),
            ("match_format", "hanchan"),
            ("player_count", True),
            ("starting_points", True),
            ("first_place_target_points", True),
            ("uma", (30, 10, -10, False)),
            ("uma", 30),
            ("bankruptcy_enabled", 1),
            ("ron_resolution_policy", "multiple_ron"),
            ("multiple_ron_honba_policy", "nearest"),
            ("multiple_ron_riichi_stick_policy", "nearest"),
            ("final_points_rounding", "floor"),
            ("final_rank_tie_policy", "seat_order"),
            ("riichi_ankan_policy", "preserve_wait_only"),
            ("bankruptcy_bonus_points", True),
            ("noten_penalty_total", True),
            ("nagashi_mangan_enabled", 1),
            ("pao_enabled", 1),
            ("nine_terminals_abortive_draw_enabled", 1),
            ("four_winds_abortive_draw_enabled", 1),
            ("four_kans_abortive_draw_enabled", 1),
            ("four_riichi_abortive_draw_enabled", 1),
            ("kokushi_ankan_chankan_enabled", 1),
            ("kan_dora_reveal_policy", "immediate"),
            ("pao_compound_yakuman_policy", "full_hand"),
            ("pao_yaku", (Yaku.DAISANGEN, "daisuushii")),
            ("pao_yaku", 1),
            ("riichi_minimum_points", "1000"),
            ("riichi_minimum_live_wall_tiles", True),
            ("double_yakuman_variants", (Yaku.SUUANKOU_TANKI, "daisuushii")),
            ("double_yakuman_variants", 1),
            ("double_wind_pair_fu", True),
        )
        for field_name, value in cases:
            with self.subTest(field_name=field_name, value=value):
                with self.assertRaises(TypeError):
                    replace(RuleSet.default(), **{field_name: value})

    def test_rejects_invalid_values_and_contradictions(self) -> None:
        cases = (
            {"name": ""},
            {"version": 0},
            {"player_count": 3},
            {"starting_points": 0},
            {"return_points": 20_000},
            {"return_points": 30_001},
            {"first_place_target_points": 0},
            {"uma": (30, 10, -10, -20)},
            {"bankruptcy_threshold": -1},
            {"ron_honba_points": -1},
            {"tsumo_honba_points_per_payer": -1},
            {"riichi_stick_points": 0},
            {"noten_penalty_total": 0},
            {"noten_penalty_total": 3_001},
            {"pao_yaku": frozenset({Yaku.SUUANKOU})},
            {"pao_yaku": frozenset()},
            {"double_ron_enabled": False},
            {"ron_resolution_policy": RonResolutionPolicy.HEAD_BUMP},
            {"bankruptcy_bonus_points": -1},
            {"bankrupt_player_penalty_points": 1},
            {"bankruptcy_bonus_points": 5},
            {"riichi_minimum_live_wall_tiles": 0},
            {"riichi_minimum_live_wall_tiles": -1},
            {"double_yakuman_variants": frozenset({Yaku.DAISANGEN})},
            {"double_wind_pair_fu": 0},
            {"double_wind_pair_fu": 3},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    replace(RuleSet.default(), **changes)

    def test_accepts_a_valid_equivalent_profile(self) -> None:
        self.assertEqual(replace(RuleSet.default()), RuleSet.default())


class RuleSetExpressivePowerTest(unittest.TestCase):
    """外部サービスpresetを追加せず、`RuleSet`の型表現能力だけを固定する。"""

    def test_return_points_and_first_place_target_points_are_independent(self) -> None:
        # 25,000点返し・一位必要点数30,000のように、意味の異なる2つの
        # fieldが別々の値を取れることを固定する。
        rules = replace(
            RuleSet.default(),
            return_points=25_000,
            first_place_target_points=30_000,
        )

        self.assertEqual(rules.return_points, 25_000)
        self.assertEqual(rules.first_place_target_points, 30_000)
        self.assertNotEqual(rules.return_points, rules.first_place_target_points)
        self.assertEqual(rules.oka_points, 0)
        self.assertEqual(rules.oka_rank_points, 0)

    def test_head_bump_configuration(self) -> None:
        # 頭ハネでは和了者が常に1名へ確定するため、ダブロンと三家和
        # 途中流局を同時に無効化した組み合わせだけが受理される。
        rules = replace(
            RuleSet.default(),
            ron_resolution_policy=RonResolutionPolicy.HEAD_BUMP,
            double_ron_enabled=False,
            triple_ron_abortive_draw=False,
        )

        self.assertIs(rules.ron_resolution_policy, RonResolutionPolicy.HEAD_BUMP)
        self.assertFalse(rules.double_ron_enabled)
        self.assertFalse(rules.triple_ron_abortive_draw)

    def test_split_rank_points_tie_policy(self) -> None:
        rules = replace(
            RuleSet.default(),
            final_rank_tie_policy=FinalRankTiePolicy.SPLIT_RANK_POINTS,
        )

        self.assertIs(
            rules.final_rank_tie_policy,
            FinalRankTiePolicy.SPLIT_RANK_POINTS,
        )

    def test_exact_no_rounding_final_points(self) -> None:
        rules = replace(
            RuleSet.default(),
            final_points_rounding=FinalPointsRounding.EXACT_NO_ROUNDING,
        )

        self.assertIs(
            rules.final_points_rounding,
            FinalPointsRounding.EXACT_NO_ROUNDING,
        )

    def test_suukantsu_pao_with_responsible_yakuman_only_policy(self) -> None:
        rules = replace(
            RuleSet.default(),
            pao_yaku=frozenset({Yaku.DAISANGEN, Yaku.DAISUUSHII, Yaku.SUUKANTSU}),
            pao_compound_yakuman_policy=(
                PaoCompoundYakumanPolicy.RESPONSIBLE_YAKUMAN_ONLY
            ),
        )

        self.assertEqual(
            rules.pao_yaku,
            frozenset({Yaku.DAISANGEN, Yaku.DAISUUSHII, Yaku.SUUKANTSU}),
        )
        self.assertIs(
            rules.pao_compound_yakuman_policy,
            PaoCompoundYakumanPolicy.RESPONSIBLE_YAKUMAN_ONLY,
        )

    def test_immediate_kan_dora_reveal_and_preserve_wait_only_riichi_ankan(
        self,
    ) -> None:
        rules = replace(
            RuleSet.default(),
            kan_dora_reveal_policy=KanDoraRevealPolicy.IMMEDIATE_ON_KAN_CONFIRMATION,
            riichi_ankan_policy=RiichiAnkanPolicy.PRESERVE_WAIT_ONLY,
        )

        self.assertIs(
            rules.kan_dora_reveal_policy,
            KanDoraRevealPolicy.IMMEDIATE_ON_KAN_CONFIRMATION,
        )
        self.assertIs(rules.riichi_ankan_policy, RiichiAnkanPolicy.PRESERVE_WAIT_ONLY)

    def test_riichi_minimum_points_can_be_none(self) -> None:
        rules = replace(RuleSet.default(), riichi_minimum_points=None)

        self.assertIsNone(rules.riichi_minimum_points)

    def test_riichi_minimum_live_wall_tiles_of_one(self) -> None:
        rules = replace(RuleSet.default(), riichi_minimum_live_wall_tiles=1)

        self.assertEqual(rules.riichi_minimum_live_wall_tiles, 1)

    def test_double_wind_pair_fu_of_two(self) -> None:
        rules = replace(RuleSet.default(), double_wind_pair_fu=2)

        self.assertEqual(rules.double_wind_pair_fu, 2)

    def test_double_yakuman_variants_can_be_enabled(self) -> None:
        variants = frozenset(
            {
                Yaku.SUUANKOU_TANKI,
                Yaku.KOKUSHI_MUSOU_13_WAIT,
                Yaku.DAISUUSHII,
                Yaku.JUNSEI_CHUUREN_POUTOU,
            }
        )
        rules = replace(RuleSet.default(), double_yakuman_variants=variants)

        self.assertEqual(rules.double_yakuman_variants, variants)

    def test_bankruptcy_bonus_can_be_disabled(self) -> None:
        rules = replace(
            RuleSet.default(),
            bankruptcy_bonus_points=0,
            bankrupt_player_penalty_points=0,
        )

        self.assertEqual(rules.bankruptcy_bonus_points, 0)
        self.assertEqual(rules.bankrupt_player_penalty_points, 0)


class RuleSetNameIsIdentificationOnlyTest(unittest.TestCase):
    """`name`は識別情報であり、mechanicsの分岐条件でも許可リストでもない。"""

    def test_any_non_empty_name_is_accepted(self) -> None:
        rules = replace(RuleSet.default(), name="some-other-rule-set")

        self.assertEqual(rules.name, "some-other-rule-set")

    def test_changing_the_name_changes_no_other_field(self) -> None:
        default_rules = RuleSet.default()
        renamed = replace(default_rules, name="some-other-rule-set")

        for field in fields(RuleSet):
            if field.name == "name":
                continue
            with self.subTest(field=field.name):
                self.assertEqual(
                    getattr(renamed, field.name),
                    getattr(default_rules, field.name),
                )


if __name__ == "__main__":
    unittest.main()
