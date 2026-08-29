"""`rule_presets.py`が提供する4 presetの値と、preset間の重要差分を固定する。

本fileは次の3層を扱う。

1. preset固定値: 各presetの主要fieldが期待値どおりであること
2. preset差分: presetどうしが意図せず同一化されないこと。`RuleSet`の
   field集合全体を走査するため、将来fieldを追加したときの取りこぼしも検出する
3. mechanics integration: presetを実際にmechanicsへ注入すると、既存のpolicy
   実装がそのpreset値を参照すること

3では、既にfield単位のbehaviorが固定されているアルゴリズム自体を再検証せず、
代表的なpolicyについて「presetの値がmechanicsへ届く」ことだけを確認する。
"""

import unittest
from dataclasses import fields

from _round_fixtures import tiles

from lisjong_engine.final_score import calculate_final_scores
from lisjong_engine.fu import FuComponent, FuReason, enumerate_fu_components
from lisjong_engine.legal_action import (
    PassLegalAction,
    ReactionOrigin,
    RonLegalAction,
)
from lisjong_engine.reaction import reaction_seat_order, resolve_reaction_choices
from lisjong_engine.rule_presets import (
    M_LEAGUE_RULES,
    MAHJONG_SOUL_RULES,
    PROJECT_STANDARD_RULES,
    TENHOU_RULES,
)
from lisjong_engine.rules import (
    FinalPointsRounding,
    FinalRankTiePolicy,
    KanDoraRevealPolicy,
    MatchFormat,
    PaoCompoundYakumanPolicy,
    RiichiAnkanPolicy,
    RonResolutionPolicy,
    RuleSet,
)
from lisjong_engine.seat import Seat
from lisjong_engine.win_context import WinMethod, WinningContext, WinOrigin
from lisjong_engine.wind import Wind
from lisjong_engine.winning import find_standard_winning_interpretations
from lisjong_engine.yaku import Yaku
from lisjong_engine.yaku_evaluation import YakuEvaluation, evaluate_yaku

_EXTERNAL_PRESETS = {
    "tenhou": TENHOU_RULES,
    "mahjong-soul": MAHJONG_SOUL_RULES,
    "m-league": M_LEAGUE_RULES,
}
_ALL_PRESETS = {"project-standard": PROJECT_STANDARD_RULES, **_EXTERNAL_PRESETS}


class ProjectStandardPresetTest(unittest.TestCase):
    """`PROJECT_STANDARD_RULES`は`RuleSet.default()`の契約そのものである。"""

    def test_equals_the_default_rule_set(self) -> None:
        self.assertEqual(PROJECT_STANDARD_RULES, RuleSet.default())

    def test_keeps_the_default_identity(self) -> None:
        self.assertEqual(PROJECT_STANDARD_RULES.name, "project-standard-v1")
        self.assertEqual(PROJECT_STANDARD_RULES.version, 1)


class TenhouPresetTest(unittest.TestCase):
    """天鳳・四人東南喰赤段位戦presetの固定値。"""

    def test_identity_and_match_format(self) -> None:
        self.assertEqual(TENHOU_RULES.name, "tenhou-4p-east-south-red-v1")
        self.assertEqual(TENHOU_RULES.version, 1)
        self.assertIs(TENHOU_RULES.match_format, MatchFormat.HANCHAN)
        self.assertEqual(TENHOU_RULES.player_count, 4)

    def test_points_and_rank_points(self) -> None:
        self.assertEqual(TENHOU_RULES.starting_points, 25_000)
        self.assertEqual(TENHOU_RULES.return_points, 30_000)
        self.assertEqual(TENHOU_RULES.first_place_target_points, 30_000)
        self.assertEqual(TENHOU_RULES.uma, (20, 10, -10, -20))
        self.assertEqual(TENHOU_RULES.oka_points, 20_000)

    def test_end_conditions_follow_the_standard_hanchan(self) -> None:
        self.assertTrue(TENHOU_RULES.bankruptcy_enabled)
        self.assertTrue(TENHOU_RULES.west_round_enabled)
        self.assertTrue(TENHOU_RULES.dealer_win_end_enabled)
        self.assertTrue(TENHOU_RULES.dealer_tenpai_end_enabled)

    def test_scoring_values(self) -> None:
        self.assertFalse(TENHOU_RULES.rounded_mangan_enabled)
        self.assertTrue(TENHOU_RULES.counted_yakuman_enabled)
        self.assertTrue(TENHOU_RULES.multiple_yakuman_enabled)
        self.assertTrue(TENHOU_RULES.nagashi_mangan_enabled)

    def test_pao_and_multiple_ron_values(self) -> None:
        self.assertTrue(TENHOU_RULES.pao_enabled)
        self.assertEqual(
            TENHOU_RULES.pao_yaku,
            frozenset({Yaku.DAISANGEN, Yaku.DAISUUSHII}),
        )
        self.assertIs(
            TENHOU_RULES.pao_compound_yakuman_policy,
            PaoCompoundYakumanPolicy.FULL_HAND,
        )
        self.assertTrue(TENHOU_RULES.double_ron_enabled)
        self.assertIs(
            TENHOU_RULES.ron_resolution_policy,
            RonResolutionPolicy.MULTIPLE_RON,
        )
        self.assertTrue(TENHOU_RULES.triple_ron_abortive_draw)

    def test_final_score_values(self) -> None:
        self.assertIs(
            TENHOU_RULES.final_points_rounding,
            FinalPointsRounding.EXACT_NO_ROUNDING,
        )
        self.assertIs(
            TENHOU_RULES.final_rank_tie_policy,
            FinalRankTiePolicy.SEAT_ORDER,
        )
        self.assertEqual(TENHOU_RULES.bankruptcy_bonus_points, 0)
        self.assertEqual(TENHOU_RULES.bankrupt_player_penalty_points, 0)

    def test_riichi_and_kan_values(self) -> None:
        self.assertIs(
            TENHOU_RULES.riichi_ankan_policy,
            RiichiAnkanPolicy.PRESERVE_WAIT_ONLY,
        )
        self.assertIs(
            TENHOU_RULES.kan_dora_reveal_policy,
            KanDoraRevealPolicy.DELAY_OPEN_KAN_DORA,
        )
        self.assertFalse(TENHOU_RULES.kokushi_ankan_chankan_enabled)
        self.assertEqual(TENHOU_RULES.riichi_minimum_points, 1_000)
        self.assertEqual(TENHOU_RULES.riichi_minimum_live_wall_tiles, 4)

    def test_yaku_and_fu_config_values(self) -> None:
        self.assertEqual(TENHOU_RULES.double_yakuman_variants, frozenset())
        self.assertEqual(TENHOU_RULES.double_wind_pair_fu, 4)


class MahjongSoulPresetTest(unittest.TestCase):
    """雀魂・四人東南喰赤段位戦presetの固定値。"""

    def test_identity_and_match_format(self) -> None:
        self.assertEqual(MAHJONG_SOUL_RULES.name, "mahjong-soul-4p-east-south-red-v1")
        self.assertEqual(MAHJONG_SOUL_RULES.version, 1)
        self.assertIs(MAHJONG_SOUL_RULES.match_format, MatchFormat.HANCHAN)
        self.assertEqual(MAHJONG_SOUL_RULES.player_count, 4)

    def test_points_and_rank_points(self) -> None:
        self.assertEqual(MAHJONG_SOUL_RULES.starting_points, 25_000)
        self.assertEqual(MAHJONG_SOUL_RULES.return_points, 25_000)
        self.assertEqual(MAHJONG_SOUL_RULES.first_place_target_points, 30_000)
        self.assertEqual(MAHJONG_SOUL_RULES.uma, (15, 5, -5, -15))

    def test_return_points_and_first_place_target_points_differ(self) -> None:
        """雀魂だけが、返し点と一位必要点数の分離を実値として持つ。"""
        self.assertNotEqual(
            MAHJONG_SOUL_RULES.return_points,
            MAHJONG_SOUL_RULES.first_place_target_points,
        )
        self.assertEqual(MAHJONG_SOUL_RULES.oka_points, 0)
        self.assertEqual(MAHJONG_SOUL_RULES.oka_rank_points, 0)

    def test_end_conditions_follow_the_standard_hanchan(self) -> None:
        self.assertTrue(MAHJONG_SOUL_RULES.bankruptcy_enabled)
        self.assertTrue(MAHJONG_SOUL_RULES.west_round_enabled)
        self.assertTrue(MAHJONG_SOUL_RULES.dealer_win_end_enabled)
        self.assertTrue(MAHJONG_SOUL_RULES.dealer_tenpai_end_enabled)

    def test_scoring_values(self) -> None:
        self.assertFalse(MAHJONG_SOUL_RULES.rounded_mangan_enabled)
        self.assertTrue(MAHJONG_SOUL_RULES.counted_yakuman_enabled)
        self.assertTrue(MAHJONG_SOUL_RULES.multiple_yakuman_enabled)
        self.assertTrue(MAHJONG_SOUL_RULES.nagashi_mangan_enabled)

    def test_triple_ron_is_resolved_as_a_normal_multiple_ron(self) -> None:
        """三家和を途中流局にせず、3人全員のロンとして成立させる設定。"""
        self.assertTrue(MAHJONG_SOUL_RULES.double_ron_enabled)
        self.assertIs(
            MAHJONG_SOUL_RULES.ron_resolution_policy,
            RonResolutionPolicy.MULTIPLE_RON,
        )
        self.assertFalse(MAHJONG_SOUL_RULES.triple_ron_abortive_draw)

    def test_pao_values(self) -> None:
        self.assertTrue(MAHJONG_SOUL_RULES.pao_enabled)
        self.assertEqual(
            MAHJONG_SOUL_RULES.pao_yaku,
            frozenset({Yaku.DAISANGEN, Yaku.DAISUUSHII}),
        )
        self.assertIs(
            MAHJONG_SOUL_RULES.pao_compound_yakuman_policy,
            PaoCompoundYakumanPolicy.FULL_HAND,
        )

    def test_final_score_values(self) -> None:
        self.assertIs(
            MAHJONG_SOUL_RULES.final_points_rounding,
            FinalPointsRounding.EXACT_NO_ROUNDING,
        )
        self.assertIs(
            MAHJONG_SOUL_RULES.final_rank_tie_policy,
            FinalRankTiePolicy.SEAT_ORDER,
        )
        self.assertEqual(MAHJONG_SOUL_RULES.bankruptcy_bonus_points, 0)
        self.assertEqual(MAHJONG_SOUL_RULES.bankrupt_player_penalty_points, 0)

    def test_riichi_and_kan_values(self) -> None:
        self.assertIs(
            MAHJONG_SOUL_RULES.riichi_ankan_policy,
            RiichiAnkanPolicy.PRESERVE_WAIT_ONLY,
        )
        self.assertIs(
            MAHJONG_SOUL_RULES.kan_dora_reveal_policy,
            KanDoraRevealPolicy.DELAY_OPEN_KAN_DORA,
        )
        self.assertTrue(MAHJONG_SOUL_RULES.kokushi_ankan_chankan_enabled)
        self.assertEqual(MAHJONG_SOUL_RULES.riichi_minimum_points, 1_000)
        self.assertEqual(MAHJONG_SOUL_RULES.riichi_minimum_live_wall_tiles, 4)

    def test_double_yakuman_variants_are_the_migrated_four(self) -> None:
        """旧`MAHJONG_SOUL_RANKED_YAKU_RULES`のダブル役満契約を維持する。"""
        self.assertEqual(
            MAHJONG_SOUL_RULES.double_yakuman_variants,
            frozenset(
                {
                    Yaku.SUUANKOU_TANKI,
                    Yaku.KOKUSHI_MUSOU_13_WAIT,
                    Yaku.DAISUUSHII,
                    Yaku.JUNSEI_CHUUREN_POUTOU,
                }
            ),
        )

    def test_double_wind_pair_fu_value(self) -> None:
        self.assertEqual(MAHJONG_SOUL_RULES.double_wind_pair_fu, 4)


class MLeaguePresetTest(unittest.TestCase):
    """Mリーグ・四人東南戦presetの固定値。"""

    def test_identity_and_match_format(self) -> None:
        self.assertEqual(M_LEAGUE_RULES.name, "m-league-4p-east-south-v1")
        self.assertEqual(M_LEAGUE_RULES.version, 1)
        self.assertIs(M_LEAGUE_RULES.match_format, MatchFormat.HANCHAN)
        self.assertEqual(M_LEAGUE_RULES.player_count, 4)

    def test_points_and_rank_points(self) -> None:
        self.assertEqual(M_LEAGUE_RULES.starting_points, 25_000)
        self.assertEqual(M_LEAGUE_RULES.return_points, 30_000)
        self.assertEqual(M_LEAGUE_RULES.first_place_target_points, 30_000)
        self.assertEqual(M_LEAGUE_RULES.uma, (30, 10, -10, -30))

    def test_no_early_termination_conditions(self) -> None:
        self.assertFalse(M_LEAGUE_RULES.bankruptcy_enabled)
        self.assertFalse(M_LEAGUE_RULES.west_round_enabled)
        self.assertFalse(M_LEAGUE_RULES.dealer_win_end_enabled)
        self.assertFalse(M_LEAGUE_RULES.dealer_tenpai_end_enabled)

    def test_scoring_values(self) -> None:
        self.assertTrue(M_LEAGUE_RULES.rounded_mangan_enabled)
        self.assertFalse(M_LEAGUE_RULES.counted_yakuman_enabled)
        self.assertTrue(M_LEAGUE_RULES.multiple_yakuman_enabled)
        self.assertFalse(M_LEAGUE_RULES.nagashi_mangan_enabled)

    def test_pao_values_include_suukantsu_and_limit_responsibility(self) -> None:
        self.assertTrue(M_LEAGUE_RULES.pao_enabled)
        self.assertEqual(
            M_LEAGUE_RULES.pao_yaku,
            frozenset({Yaku.DAISANGEN, Yaku.DAISUUSHII, Yaku.SUUKANTSU}),
        )
        self.assertIs(
            M_LEAGUE_RULES.pao_compound_yakuman_policy,
            PaoCompoundYakumanPolicy.RESPONSIBLE_YAKUMAN_ONLY,
        )

    def test_head_bump_resolves_ron_to_a_single_winner(self) -> None:
        self.assertIs(
            M_LEAGUE_RULES.ron_resolution_policy,
            RonResolutionPolicy.HEAD_BUMP,
        )
        self.assertFalse(M_LEAGUE_RULES.double_ron_enabled)
        self.assertFalse(M_LEAGUE_RULES.triple_ron_abortive_draw)

    def test_no_abortive_draws(self) -> None:
        self.assertFalse(M_LEAGUE_RULES.nine_terminals_abortive_draw_enabled)
        self.assertFalse(M_LEAGUE_RULES.four_winds_abortive_draw_enabled)
        self.assertFalse(M_LEAGUE_RULES.four_kans_abortive_draw_enabled)
        self.assertFalse(M_LEAGUE_RULES.four_riichi_abortive_draw_enabled)

    def test_final_score_values(self) -> None:
        self.assertIs(
            M_LEAGUE_RULES.final_points_rounding,
            FinalPointsRounding.EXACT_NO_ROUNDING,
        )
        self.assertIs(
            M_LEAGUE_RULES.final_rank_tie_policy,
            FinalRankTiePolicy.SPLIT_RANK_POINTS,
        )
        self.assertEqual(M_LEAGUE_RULES.bankruptcy_bonus_points, 0)
        self.assertEqual(M_LEAGUE_RULES.bankrupt_player_penalty_points, 0)

    def test_riichi_and_kan_values(self) -> None:
        self.assertIs(
            M_LEAGUE_RULES.riichi_ankan_policy,
            RiichiAnkanPolicy.PRESERVE_WAIT_AND_DECOMPOSITION,
        )
        self.assertIs(
            M_LEAGUE_RULES.kan_dora_reveal_policy,
            KanDoraRevealPolicy.IMMEDIATE_ON_KAN_CONFIRMATION,
        )
        self.assertFalse(M_LEAGUE_RULES.kokushi_ankan_chankan_enabled)

    def test_riichi_has_no_minimum_points_and_allows_the_last_draw(self) -> None:
        self.assertIsNone(M_LEAGUE_RULES.riichi_minimum_points)
        self.assertEqual(M_LEAGUE_RULES.riichi_minimum_live_wall_tiles, 1)

    def test_yaku_and_fu_config_values(self) -> None:
        self.assertEqual(M_LEAGUE_RULES.double_yakuman_variants, frozenset())
        self.assertEqual(M_LEAGUE_RULES.double_wind_pair_fu, 2)


def _differing_field_names(rules: RuleSet, other: RuleSet) -> frozenset[str]:
    return frozenset(
        field.name
        for field in fields(RuleSet)
        if getattr(rules, field.name) != getattr(other, field.name)
    )


class PresetDifferenceTest(unittest.TestCase):
    """preset間の差分そのものを固定する。

    差分集合は`fields(RuleSet)`全体から求めるため、`RuleSet`へfieldを追加した
    ときに、どのpresetでその値を決めそこねたかもここで検出できる。
    """

    def test_every_preset_has_a_distinct_identity(self) -> None:
        names = {preset.name for preset in _ALL_PRESETS.values()}

        self.assertEqual(len(names), len(_ALL_PRESETS))

    def test_external_presets_are_not_equal_to_the_project_standard(self) -> None:
        for label, preset in _EXTERNAL_PRESETS.items():
            with self.subTest(preset=label):
                self.assertNotEqual(preset, PROJECT_STANDARD_RULES)

    def test_tenhou_differs_from_the_project_standard_only_here(self) -> None:
        self.assertEqual(
            _differing_field_names(TENHOU_RULES, PROJECT_STANDARD_RULES),
            frozenset(
                {
                    "name",
                    "uma",
                    "final_points_rounding",
                    "bankruptcy_bonus_points",
                    "bankrupt_player_penalty_points",
                    "riichi_ankan_policy",
                }
            ),
        )

    def test_mahjong_soul_differs_from_the_project_standard_only_here(self) -> None:
        self.assertEqual(
            _differing_field_names(MAHJONG_SOUL_RULES, PROJECT_STANDARD_RULES),
            frozenset(
                {
                    "name",
                    "return_points",
                    "uma",
                    "triple_ron_abortive_draw",
                    "final_points_rounding",
                    "bankruptcy_bonus_points",
                    "bankrupt_player_penalty_points",
                    "riichi_ankan_policy",
                    "kokushi_ankan_chankan_enabled",
                    "double_yakuman_variants",
                }
            ),
        )

    def test_m_league_differs_from_the_project_standard_only_here(self) -> None:
        self.assertEqual(
            _differing_field_names(M_LEAGUE_RULES, PROJECT_STANDARD_RULES),
            frozenset(
                {
                    "name",
                    "bankruptcy_enabled",
                    "west_round_enabled",
                    "dealer_win_end_enabled",
                    "dealer_tenpai_end_enabled",
                    "rounded_mangan_enabled",
                    "counted_yakuman_enabled",
                    "nagashi_mangan_enabled",
                    "pao_yaku",
                    "pao_compound_yakuman_policy",
                    "double_ron_enabled",
                    "ron_resolution_policy",
                    "triple_ron_abortive_draw",
                    "nine_terminals_abortive_draw_enabled",
                    "four_winds_abortive_draw_enabled",
                    "four_kans_abortive_draw_enabled",
                    "four_riichi_abortive_draw_enabled",
                    "final_points_rounding",
                    "final_rank_tie_policy",
                    "bankruptcy_bonus_points",
                    "bankrupt_player_penalty_points",
                    "kan_dora_reveal_policy",
                    "riichi_minimum_points",
                    "riichi_minimum_live_wall_tiles",
                    "double_wind_pair_fu",
                }
            ),
        )

    def test_only_mahjong_soul_adopts_double_yakuman_variants(self) -> None:
        for label, preset in _ALL_PRESETS.items():
            with self.subTest(preset=label):
                if preset is MAHJONG_SOUL_RULES:
                    self.assertTrue(preset.double_yakuman_variants)
                else:
                    self.assertEqual(preset.double_yakuman_variants, frozenset())

    def test_only_m_league_uses_two_fu_for_a_double_wind_pair(self) -> None:
        for label, preset in _ALL_PRESETS.items():
            with self.subTest(preset=label):
                expected = 2 if preset is M_LEAGUE_RULES else 4
                self.assertEqual(preset.double_wind_pair_fu, expected)


_TARGET_TILE_ID = 40
_SOURCE_SEAT = Seat.EAST
_PASS = PassLegalAction(ReactionOrigin.DISCARD, _TARGET_TILE_ID)
_RON = RonLegalAction(ReactionOrigin.DISCARD, _TARGET_TILE_ID)


def _resolve_two_ron_choices(rules: RuleSet):
    """WEST・NORTHが同じ打牌へロンを選んだ反応windowをpresetで解決する。"""
    candidates = {seat: (_PASS,) for seat in reaction_seat_order(_SOURCE_SEAT)}
    candidates[Seat.WEST] = (_PASS, _RON)
    candidates[Seat.NORTH] = (_PASS, _RON)
    choices = {Seat.SOUTH: _PASS, Seat.WEST: _RON, Seat.NORTH: _RON}
    return resolve_reaction_choices(
        origin=ReactionOrigin.DISCARD,
        source_seat=_SOURCE_SEAT,
        target_tile_id=_TARGET_TILE_ID,
        candidates=candidates,
        choices=choices,
        ron_resolution_policy=rules.ron_resolution_policy,
    )


def _double_wind_pair_context() -> WinningContext:
    """東場・東家の1z雀頭単騎で和了した、連風牌雀頭の符を持つ手。"""
    concealed_tiles = tiles(
        "1m",
        "2m",
        "3m",
        "4m",
        "5m",
        "6m",
        "2p",
        "3p",
        "4p",
        "6s",
        "7s",
        "8s",
        "1z",
        "1z",
    )
    return WinningContext(
        concealed_tiles=concealed_tiles,
        winning_tile=concealed_tiles[-1],
        method=WinMethod.RON,
        origin=WinOrigin.DISCARD,
        seat_wind=Wind.EAST,
        prevailing_wind=Wind.EAST,
    )


def _double_wind_pair_components(rules: RuleSet) -> tuple[FuComponent, ...]:
    context = _double_wind_pair_context()
    interpretation = next(
        iter(
            find_standard_winning_interpretations(
                context.concealed_tiles,
                context.winning_tile,
                context.declared_melds,
            )
        )
    )
    return enumerate_fu_components(context, interpretation, rules)


def _suuankou_tanki_context() -> WinningContext:
    """四暗刻単騎（字一色・大三元と複合）で和了した手。"""
    concealed_tiles = tiles(
        "5z",
        "5z",
        "5z",
        "6z",
        "6z",
        "6z",
        "7z",
        "7z",
        "7z",
        "1z",
        "1z",
        "1z",
        "2z",
        "2z",
    )
    return WinningContext(
        concealed_tiles=concealed_tiles,
        winning_tile=concealed_tiles[-1],
        method=WinMethod.RON,
        origin=WinOrigin.DISCARD,
        seat_wind=Wind.SOUTH,
        prevailing_wind=Wind.EAST,
    )


def _yakuman_units(
    evaluations: frozenset[YakuEvaluation],
    yaku: Yaku,
) -> frozenset[int]:
    return frozenset(
        match.yakuman_units
        for evaluation in evaluations
        for match in evaluation.matches
        if match.yaku is yaku
    )


class MLeaguePresetMechanicsTest(unittest.TestCase):
    """Mリーグpresetの値が、実際にmechanicsの分岐へ届くことを確認する。"""

    def test_head_bump_awards_only_the_nearest_ron(self) -> None:
        m_league = _resolve_two_ron_choices(M_LEAGUE_RULES)
        project_standard = _resolve_two_ron_choices(PROJECT_STANDARD_RULES)

        self.assertEqual(m_league.ron_awarded_seats, (Seat.WEST,))
        self.assertEqual(project_standard.ron_awarded_seats, (Seat.WEST, Seat.NORTH))

    def test_tied_top_seats_split_rank_points(self) -> None:
        scores = {
            Seat.EAST: 30_000,
            Seat.SOUTH: 30_000,
            Seat.WEST: 20_000,
            Seat.NORTH: 20_000,
        }

        m_league = calculate_final_scores(scores, rules=M_LEAGUE_RULES)
        project_standard = calculate_final_scores(
            scores,
            rules=PROJECT_STANDARD_RULES,
        )

        self.assertEqual(
            {player.seat: player.rank for player in m_league.players},
            {Seat.EAST: 1, Seat.SOUTH: 1, Seat.WEST: 3, Seat.NORTH: 3},
        )
        self.assertEqual(
            {player.seat: player.final_points for player in m_league.players},
            {Seat.EAST: 300, Seat.SOUTH: 300, Seat.WEST: -300, Seat.NORTH: -300},
        )
        # 同じ持ち点でも、project標準は起家順で一意な順位へ分解する。
        self.assertEqual(
            {player.seat: player.rank for player in project_standard.players},
            {Seat.EAST: 1, Seat.SOUTH: 2, Seat.WEST: 3, Seat.NORTH: 4},
        )
        self.assertEqual(
            {player.seat: player.final_points for player in project_standard.players},
            {Seat.EAST: 500, Seat.SOUTH: 100, Seat.WEST: -200, Seat.NORTH: -400},
        )

    def test_double_wind_pair_is_worth_two_fu(self) -> None:
        self.assertIn(
            FuComponent(FuReason.DOUBLE_WIND_PAIR, 2),
            _double_wind_pair_components(M_LEAGUE_RULES),
        )
        self.assertIn(
            FuComponent(FuReason.DOUBLE_WIND_PAIR, 4),
            _double_wind_pair_components(PROJECT_STANDARD_RULES),
        )


class MahjongSoulPresetMechanicsTest(unittest.TestCase):
    """雀魂presetの値が、実際にmechanicsの分岐へ届くことを確認する。"""

    def test_selected_yaku_are_scored_as_double_yakuman(self) -> None:
        context = _suuankou_tanki_context()

        mahjong_soul = evaluate_yaku(context, MAHJONG_SOUL_RULES)
        project_standard = evaluate_yaku(context, PROJECT_STANDARD_RULES)

        self.assertEqual(
            _yakuman_units(mahjong_soul, Yaku.SUUANKOU_TANKI),
            frozenset({2}),
        )
        self.assertEqual(
            _yakuman_units(project_standard, Yaku.SUUANKOU_TANKI),
            frozenset({1}),
        )
        # ダブル役満の対象外は、雀魂でも1倍役満のまま変わらない。
        self.assertEqual(
            _yakuman_units(mahjong_soul, Yaku.DAISANGEN),
            frozenset({1}),
        )

    def test_multiple_ron_policy_awards_every_selecting_seat(self) -> None:
        """`ron_resolution_policy`だけを消費する反応window解決のtest。

        三家和を途中流局にしない（`triple_ron_abortive_draw=False`）という
        雀魂固有の差分は、局終了判定を含む
        `tests/test_round_winning.py`の
        `test_triple_ron_abortive_draw_follows_the_injected_preset`で固定する。
        """
        candidates = {seat: (_PASS, _RON) for seat in reaction_seat_order(_SOURCE_SEAT)}
        choices = {seat: _RON for seat in reaction_seat_order(_SOURCE_SEAT)}

        resolution = resolve_reaction_choices(
            origin=ReactionOrigin.DISCARD,
            source_seat=_SOURCE_SEAT,
            target_tile_id=_TARGET_TILE_ID,
            candidates=candidates,
            choices=choices,
            ron_resolution_policy=MAHJONG_SOUL_RULES.ron_resolution_policy,
        )

        self.assertEqual(
            resolution.ron_awarded_seats,
            (Seat.SOUTH, Seat.WEST, Seat.NORTH),
        )


class TenhouPresetMechanicsTest(unittest.TestCase):
    """天鳳presetの値が、実際にmechanicsの分岐へ届くことを確認する。"""

    def test_final_points_are_not_rounded_and_use_the_tenhou_uma(self) -> None:
        scores = {
            Seat.EAST: 35_800,
            Seat.SOUTH: 30_700,
            Seat.WEST: 20_100,
            Seat.NORTH: 13_400,
        }

        tenhou = calculate_final_scores(scores, rules=TENHOU_RULES)
        project_standard = calculate_final_scores(
            scores,
            rules=PROJECT_STANDARD_RULES,
        )

        # 100点単位をそのまま粗点にし、1位への残差吸収を行わない。
        self.assertEqual(
            {player.seat: player.base_points for player in tenhou.players},
            {Seat.EAST: 58, Seat.SOUTH: 7, Seat.WEST: -99, Seat.NORTH: -166},
        )
        self.assertEqual(
            {player.seat: player.uma_points for player in tenhou.players},
            {Seat.EAST: 200, Seat.SOUTH: 100, Seat.WEST: -100, Seat.NORTH: -200},
        )
        # project標準は1000点単位で0方向へ丸め、残差を1位が吸収する。
        self.assertEqual(
            {player.seat: player.base_points for player in project_standard.players},
            {Seat.EAST: 50, Seat.SOUTH: 0, Seat.WEST: -90, Seat.NORTH: -160},
        )


if __name__ == "__main__":
    unittest.main()
