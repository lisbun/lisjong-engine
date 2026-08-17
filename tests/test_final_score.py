import unittest
from dataclasses import FrozenInstanceError, replace

from lisjong_engine.final_score import (
    FinalPlayerScore,
    FinalScoreCalculation,
    _to_internal_points,
    calculate_bankruptcy_points,
    calculate_bankruptcy_points_for_seats,
    calculate_final_scores,
)
from lisjong_engine.rules import (
    FinalPointsRounding,
    FinalRankTiePolicy,
    RuleSet,
)
from lisjong_engine.seat import Seat

_DEFAULT_RULES = RuleSet.default()


class CalculateFinalScoresTest(unittest.TestCase):
    def test_applies_base_points_oka_and_uma(self) -> None:
        result = calculate_final_scores(
            {
                Seat.EAST: 35_000,
                Seat.SOUTH: 30_000,
                Seat.WEST: 25_000,
                Seat.NORTH: 10_000,
            }
        )

        self.assertEqual(
            tuple((player.seat, player.rank) for player in result.players),
            (
                (Seat.EAST, 1),
                (Seat.SOUTH, 2),
                (Seat.WEST, 3),
                (Seat.NORTH, 4),
            ),
        )
        self.assertEqual(
            tuple(player.final_points for player in result.players),
            (550, 100, -150, -500),
        )
        self.assertEqual(result.for_seat(Seat.EAST).oka_points, 200)
        self.assertEqual(
            tuple(player.uma_points for player in result.players),
            (300, 100, -100, -300),
        )

    def test_rounds_second_through_fourth_place_toward_zero(self) -> None:
        result = calculate_final_scores(
            {
                Seat.EAST: 32_100,
                Seat.SOUTH: 28_700,
                Seat.WEST: 25_000,
                Seat.NORTH: 14_200,
            }
        )

        self.assertEqual(
            tuple(player.base_points for player in result.players),
            (10, -10, -50, -150),
        )
        self.assertEqual(
            tuple(player.final_points for player in result.players),
            (510, 90, -150, -450),
        )
        self.assertEqual(sum(player.final_points for player in result.players), 0)

    def test_first_place_base_points_absorb_the_zero_sum_remainder(self) -> None:
        result = calculate_final_scores(
            {
                Seat.EAST: 41_200,
                Seat.SOUTH: 30_800,
                Seat.WEST: 22_100,
                Seat.NORTH: 5_900,
            }
        )

        self.assertEqual(
            tuple(player.base_points for player in result.players),
            (110, 0, -70, -240),
        )
        self.assertEqual(
            sum(player.base_points for player in result.players),
            -result.for_seat(Seat.EAST).oka_points,
        )

    def test_uses_return_points_not_first_place_target_points_as_baseline(
        self,
    ) -> None:
        """最終精算の基準点はreturn_pointsのみであり、終局判定用の
        first_place_target_pointsは使用されないことを確認する。
        """
        test_rules = replace(
            _DEFAULT_RULES,
            return_points=25_000,
            first_place_target_points=30_000,
        )

        result = calculate_final_scores(
            {
                Seat.EAST: 30_000,
                Seat.SOUTH: 25_000,
                Seat.WEST: 23_000,
                Seat.NORTH: 22_000,
            },
            rules=test_rules,
        )

        # oka_points/oka_rank_pointsはreturn_points基準で0のままであり、
        # first_place_target_points=30,000には引きずられない。
        self.assertEqual(result.for_seat(Seat.EAST).oka_points, 0)
        self.assertEqual(
            tuple(player.base_points for player in result.players),
            (50, 0, -20, -30),
        )

    def test_tied_scores_use_initial_seat_order(self) -> None:
        result = calculate_final_scores({seat: 25_000 for seat in Seat})

        self.assertEqual(tuple(player.seat for player in result.players), tuple(Seat))

    def test_applies_bankruptcy_points_after_normal_final_scoring(self) -> None:
        adjustments = calculate_bankruptcy_points(Seat.EAST, (Seat.SOUTH,))

        result = calculate_final_scores(
            {
                Seat.EAST: -100,
                Seat.SOUTH: 40_100,
                Seat.WEST: 30_000,
                Seat.NORTH: 30_000,
            },
            bankruptcy_points=adjustments,
        )

        self.assertEqual(result.for_seat(Seat.EAST).bankruptcy_points, -100)
        self.assertEqual(result.for_seat(Seat.SOUTH).bankruptcy_points, 100)
        self.assertEqual(sum(player.final_points for player in result.players), 0)

    def test_rejects_invalid_inputs(self) -> None:
        with self.assertRaises(TypeError):
            calculate_final_scores("scores")
        with self.assertRaises(ValueError):
            calculate_final_scores({Seat.EAST: 100_000})
        with self.assertRaises(TypeError):
            calculate_final_scores({seat: True for seat in Seat})
        with self.assertRaises(ValueError):
            calculate_final_scores(
                {seat: 25_000 for seat in Seat},
                bankruptcy_points={seat: 1 for seat in Seat},
            )


class BankruptcyPointsTest(unittest.TestCase):
    def test_single_and_double_winners_share_bonus(self) -> None:
        single = calculate_bankruptcy_points(Seat.EAST, (Seat.SOUTH,))
        double = calculate_bankruptcy_points(Seat.EAST, (Seat.SOUTH, Seat.WEST))

        self.assertEqual(
            single, {Seat.EAST: -10, Seat.SOUTH: 10, Seat.WEST: 0, Seat.NORTH: 0}
        )
        self.assertEqual(
            double, {Seat.EAST: -10, Seat.SOUTH: 5, Seat.WEST: 5, Seat.NORTH: 0}
        )

    def test_noten_recipients_split_remainder_by_order_after_bankrupt_seat(
        self,
    ) -> None:
        adjustments = calculate_bankruptcy_points(
            Seat.EAST,
            (Seat.NORTH, Seat.WEST, Seat.SOUTH),
        )

        self.assertEqual(
            adjustments,
            {Seat.EAST: -10, Seat.SOUTH: 4, Seat.WEST: 3, Seat.NORTH: 3},
        )

    def test_remainder_order_starts_after_the_bankrupt_seat(self) -> None:
        adjustments = calculate_bankruptcy_points(
            Seat.SOUTH,
            (Seat.NORTH, Seat.EAST, Seat.WEST),
        )

        self.assertEqual(
            adjustments,
            {Seat.EAST: 3, Seat.SOUTH: -10, Seat.WEST: 4, Seat.NORTH: 3},
        )

    def test_two_bankrupt_players_each_pay_one_recipient(self) -> None:
        adjustments = calculate_bankruptcy_points_for_seats(
            (Seat.EAST, Seat.SOUTH),
            (Seat.WEST,),
        )

        self.assertEqual(
            adjustments,
            {Seat.EAST: -10, Seat.SOUTH: -10, Seat.WEST: 20, Seat.NORTH: 0},
        )

    def test_two_bankrupt_players_split_each_bonus_between_two_recipients(
        self,
    ) -> None:
        adjustments = calculate_bankruptcy_points_for_seats(
            (Seat.EAST, Seat.SOUTH),
            (Seat.WEST, Seat.NORTH),
        )

        self.assertEqual(
            adjustments,
            {Seat.EAST: -10, Seat.SOUTH: -10, Seat.WEST: 10, Seat.NORTH: 10},
        )

    def test_each_bankrupt_player_uses_own_remainder_origin(self) -> None:
        adjustments = calculate_bankruptcy_points_for_seats(
            (Seat.EAST, Seat.SOUTH),
            (Seat.EAST, Seat.WEST, Seat.NORTH),
        )

        self.assertEqual(
            adjustments,
            {Seat.EAST: -7, Seat.SOUTH: -10, Seat.WEST: 9, Seat.NORTH: 8},
        )
        self.assertEqual(sum(adjustments.values()), 0)

    def test_no_bankrupt_players_produce_no_adjustment(self) -> None:
        adjustments = calculate_bankruptcy_points_for_seats((), ())

        self.assertEqual(adjustments, {seat: 0 for seat in Seat})

    def test_multiple_bankruptcy_bonus_preserves_total_final_points(self) -> None:
        scores = {
            Seat.EAST: -100,
            Seat.SOUTH: -100,
            Seat.WEST: 50_100,
            Seat.NORTH: 50_100,
        }
        adjustments = calculate_bankruptcy_points_for_seats(
            (Seat.EAST, Seat.SOUTH),
            (Seat.WEST, Seat.NORTH),
        )

        without_bonus = calculate_final_scores(scores)
        with_bonus = calculate_final_scores(scores, bankruptcy_points=adjustments)

        self.assertEqual(
            sum(player.final_points for player in without_bonus.players),
            sum(player.final_points for player in with_bonus.players),
        )
        self.assertEqual(sum(adjustments.values()), 0)

    def test_rejects_invalid_recipients(self) -> None:
        with self.assertRaises(ValueError):
            calculate_bankruptcy_points(Seat.EAST, ())
        with self.assertRaises(ValueError):
            calculate_bankruptcy_points(Seat.EAST, (Seat.EAST,))
        with self.assertRaises(TypeError):
            calculate_bankruptcy_points(Seat.EAST, ("south",))
        with self.assertRaises(ValueError):
            calculate_bankruptcy_points_for_seats((Seat.EAST, Seat.EAST), (Seat.SOUTH,))


class InternalPointUnitTest(unittest.TestCase):
    """FinalScore内部単位（1 = 0.1ポイント）の変換契約を確認する。"""

    def test_to_internal_points_converts_human_units_to_tenths(self) -> None:
        self.assertEqual(_to_internal_points(11), 110)
        self.assertEqual(_to_internal_points(30), 300)
        self.assertEqual(_to_internal_points(-7), -70)
        self.assertEqual(_to_internal_points(0), 0)

    def test_my_rule_final_scores_are_ten_times_the_human_point_values(self) -> None:
        """現行マイルールの最終スコアの意味は変わらず、内部値は
        従来の人間向けポイント値をちょうど10倍したものになる。
        """
        result = calculate_final_scores(
            {
                Seat.EAST: 41_200,
                Seat.SOUTH: 30_800,
                Seat.WEST: 22_100,
                Seat.NORTH: 5_900,
            }
        )

        human_final_points = (61, 10, -17, -54)
        self.assertEqual(
            tuple(player.final_points for player in result.players),
            tuple(_to_internal_points(value) for value in human_final_points),
        )
        self.assertEqual(sum(player.final_points for player in result.players), 0)


class ExactNoRoundingTest(unittest.TestCase):
    """EXACT_NO_ROUNDING方式（残差配分なしの粗点計算）を確認する。"""

    def _rules(self):
        return replace(
            _DEFAULT_RULES,
            final_points_rounding=FinalPointsRounding.EXACT_NO_ROUNDING,
        )

    def test_hundred_point_precision_case(self) -> None:
        result = calculate_final_scores(
            {
                Seat.EAST: 35_800,
                Seat.SOUTH: 30_700,
                Seat.WEST: 20_100,
                Seat.NORTH: 13_400,
            },
            rules=self._rules(),
        )

        self.assertEqual(
            {player.seat: player.base_points for player in result.players},
            {
                Seat.EAST: 58,
                Seat.SOUTH: 7,
                Seat.WEST: -99,
                Seat.NORTH: -166,
            },
        )

    def test_does_not_absorb_remainder_into_first_place(self) -> None:
        rules = self._rules()
        scores = {
            Seat.EAST: 35_800,
            Seat.SOUTH: 30_700,
            Seat.WEST: 20_100,
            Seat.NORTH: 13_400,
        }
        result = calculate_final_scores(scores, rules=rules)

        for player in result.players:
            self.assertEqual(
                player.base_points,
                (scores[player.seat] - rules.return_points) // 100,
            )

    def test_base_points_sum_to_negative_oka_rank_points(self) -> None:
        rules = self._rules()
        result = calculate_final_scores(
            {
                Seat.EAST: 30_000,
                Seat.SOUTH: 30_000,
                Seat.WEST: 20_000,
                Seat.NORTH: 20_000,
            },
            rules=rules,
        )

        self.assertEqual(
            sum(player.base_points for player in result.players),
            -_to_internal_points(rules.oka_rank_points),
        )

    def test_final_points_sum_to_zero(self) -> None:
        result = calculate_final_scores(
            {
                Seat.EAST: 35_800,
                Seat.SOUTH: 30_700,
                Seat.WEST: 20_100,
                Seat.NORTH: 13_400,
            },
            rules=self._rules(),
        )

        self.assertEqual(sum(player.final_points for player in result.players), 0)

    def test_rejects_scores_not_expressible_in_hundred_point_units(self) -> None:
        with self.assertRaises(ValueError):
            calculate_final_scores(
                {
                    Seat.EAST: 35_850,
                    Seat.SOUTH: 30_700,
                    Seat.WEST: 20_050,
                    Seat.NORTH: 13_400,
                },
                rules=self._rules(),
            )

    def test_thousand_point_only_case(self) -> None:
        result = calculate_final_scores(
            {
                Seat.EAST: 30_000,
                Seat.SOUTH: 30_000,
                Seat.WEST: 20_000,
                Seat.NORTH: 20_000,
            },
            rules=self._rules(),
        )

        self.assertEqual(
            {player.seat: player.base_points for player in result.players},
            {
                Seat.EAST: 0,
                Seat.SOUTH: 0,
                Seat.WEST: -100,
                Seat.NORTH: -100,
            },
        )

    def test_does_not_correct_total_score_inconsistency(self) -> None:
        """100点単位は満たすが総点が理論値と一致しない入力は、残差補正
        されず、既存のゼロサム不変条件で検出される。
        """
        with self.assertRaises(ValueError):
            calculate_final_scores(
                {
                    Seat.EAST: 35_800,
                    Seat.SOUTH: 30_700,
                    Seat.WEST: 20_100,
                    Seat.NORTH: 13_500,
                },
                rules=self._rules(),
            )


class FinalScoreModelTest(unittest.TestCase):
    def test_models_are_frozen_and_validate_totals(self) -> None:
        player = FinalPlayerScore(Seat.EAST, 1, 25_000, -5, 30, 20, 0, 45)
        with self.assertRaises(FrozenInstanceError):
            player.rank = 2
        with self.assertRaises(ValueError):
            FinalPlayerScore(Seat.EAST, 1, 25_000, -5, 30, 20, 0, 44)
        with self.assertRaises(ValueError):
            FinalScoreCalculation((player,))

    def test_accepts_standard_competition_ranking_with_ties(self) -> None:
        """同点者が順位帯の先頭順位を共有する標準競技順位
        （例: 1位・2位同点なら双方rank=1、次点はrank=3）を受け入れる。
        """
        players = (
            FinalPlayerScore(Seat.EAST, 1, 35_000, 0, 300, 0, 0, 300),
            FinalPlayerScore(Seat.SOUTH, 1, 35_000, 0, 300, 0, 0, 300),
            FinalPlayerScore(Seat.WEST, 3, 20_000, 0, -100, 0, 0, -100),
            FinalPlayerScore(Seat.NORTH, 4, 10_000, 0, -500, 0, 0, -500),
        )
        calculation = FinalScoreCalculation(players)
        self.assertEqual(
            tuple(player.rank for player in calculation.players), (1, 1, 3, 4)
        )

    def test_rejects_a_rank_sequence_that_is_not_a_valid_competition_ranking(
        self,
    ) -> None:
        players = (
            FinalPlayerScore(Seat.EAST, 1, 35_000, 0, 300, 0, 0, 300),
            FinalPlayerScore(Seat.SOUTH, 2, 30_000, 0, 100, 0, 0, 100),
            FinalPlayerScore(Seat.WEST, 2, 20_000, 0, -100, 0, 0, -100),
            FinalPlayerScore(Seat.NORTH, 3, 10_000, 0, -300, 0, 0, -300),
        )
        with self.assertRaises(ValueError):
            FinalScoreCalculation(players)

    def test_rejects_duplicate_seat_even_when_all_seats_are_present(self) -> None:
        players = (
            FinalPlayerScore(Seat.EAST, 1, 40_000, 0, 300, 0, 0, 300),
            FinalPlayerScore(Seat.SOUTH, 2, 30_000, 0, 100, 0, 0, 100),
            FinalPlayerScore(Seat.WEST, 3, 20_000, 0, -100, 0, 0, -100),
            FinalPlayerScore(Seat.NORTH, 4, 10_000, 0, -300, 0, 0, -300),
            FinalPlayerScore(Seat.NORTH, 4, 10_000, 0, 0, 0, 0, 0),
        )

        with self.assertRaises(ValueError):
            FinalScoreCalculation(players)


class SplitRankPointsTest(unittest.TestCase):
    def _rules(self):
        return replace(
            _DEFAULT_RULES,
            final_rank_tie_policy=FinalRankTiePolicy.SPLIT_RANK_POINTS,
        )

    def test_no_ties_produce_the_normal_rank_points(self) -> None:
        result = calculate_final_scores(
            {
                Seat.EAST: 35_000,
                Seat.SOUTH: 30_000,
                Seat.WEST: 25_000,
                Seat.NORTH: 10_000,
            },
            rules=self._rules(),
        )

        self.assertEqual(tuple(player.rank for player in result.players), (1, 2, 3, 4))
        # 同点なしでも、ウマとオカは個別の内訳として保持する
        # （1位のみオカ200 = 内部単位でのoka_rank_points20相当を受け取る）。
        self.assertEqual(
            tuple(player.uma_points for player in result.players),
            (300, 100, -100, -300),
        )
        self.assertEqual(
            tuple(player.oka_points for player in result.players), (200, 0, 0, 0)
        )
        self.assertEqual(
            tuple(player.uma_points + player.oka_points for player in result.players),
            (500, 100, -100, -300),
        )
        self.assertEqual(sum(player.final_points for player in result.players), 0)

    def test_first_and_second_place_tie_splits_into_thirty_each(self) -> None:
        result = calculate_final_scores(
            {
                Seat.EAST: 35_000,
                Seat.SOUTH: 35_000,
                Seat.WEST: 20_000,
                Seat.NORTH: 10_000,
            },
            rules=self._rules(),
        )

        self.assertEqual(
            {player.seat: player.rank for player in result.players},
            {Seat.EAST: 1, Seat.SOUTH: 1, Seat.WEST: 3, Seat.NORTH: 4},
        )
        # ウマ(30+10)/2=20、オカ20/2=10がそれぞれ個別に按分される。
        self.assertEqual(result.for_seat(Seat.EAST).uma_points, 200)
        self.assertEqual(result.for_seat(Seat.SOUTH).uma_points, 200)
        self.assertEqual(result.for_seat(Seat.EAST).oka_points, 100)
        self.assertEqual(result.for_seat(Seat.SOUTH).oka_points, 100)
        self.assertEqual(
            result.for_seat(Seat.EAST).uma_points
            + result.for_seat(Seat.EAST).oka_points,
            300,
        )
        self.assertEqual(
            result.for_seat(Seat.SOUTH).uma_points
            + result.for_seat(Seat.SOUTH).oka_points,
            300,
        )
        self.assertEqual(sum(player.final_points for player in result.players), 0)

    def test_second_and_third_place_tie_splits_into_zero_each(self) -> None:
        result = calculate_final_scores(
            {
                Seat.EAST: 30_500,
                Seat.SOUTH: 25_000,
                Seat.WEST: 25_000,
                Seat.NORTH: 19_500,
            },
            rules=self._rules(),
        )

        self.assertEqual(
            {player.seat: player.rank for player in result.players},
            {Seat.EAST: 1, Seat.SOUTH: 2, Seat.WEST: 2, Seat.NORTH: 4},
        )
        self.assertEqual(result.for_seat(Seat.SOUTH).uma_points, 0)
        self.assertEqual(result.for_seat(Seat.WEST).uma_points, 0)
        # 2・3位同点グループは1位を含まないため、オカは配分されない。
        self.assertEqual(result.for_seat(Seat.SOUTH).oka_points, 0)
        self.assertEqual(result.for_seat(Seat.WEST).oka_points, 0)
        self.assertEqual(sum(player.final_points for player in result.players), 0)

    def test_three_way_top_tie_distributes_the_tenth_point_remainder_from_east(
        self,
    ) -> None:
        result = calculate_final_scores(
            {
                Seat.EAST: 10_000,
                Seat.SOUTH: 30_000,
                Seat.WEST: 30_000,
                Seat.NORTH: 30_000,
            },
            rules=self._rules(),
        )

        self.assertEqual(
            {player.seat: player.rank for player in result.players},
            {Seat.EAST: 4, Seat.SOUTH: 1, Seat.WEST: 1, Seat.NORTH: 1},
        )
        # ウマ(30+10-10)=30を3人へ均等分配すると内部単位100が割り切れ、
        # 各自100（10.0pt）ずつとなる。
        self.assertEqual(
            {
                Seat.SOUTH: result.for_seat(Seat.SOUTH).uma_points,
                Seat.WEST: result.for_seat(Seat.WEST).uma_points,
                Seat.NORTH: result.for_seat(Seat.NORTH).uma_points,
            },
            {Seat.SOUTH: 100, Seat.WEST: 100, Seat.NORTH: 100},
        )
        # オカ20（内部単位200）を3人へ均等分配すると16.6/16.6/16.6が
        # 割り切れず、内部0.1pt単位で2単位余る。起家に近い席（南→西→北）
        # から順に配分する。
        self.assertEqual(
            {
                Seat.SOUTH: result.for_seat(Seat.SOUTH).oka_points,
                Seat.WEST: result.for_seat(Seat.WEST).oka_points,
                Seat.NORTH: result.for_seat(Seat.NORTH).oka_points,
            },
            {Seat.SOUTH: 67, Seat.WEST: 67, Seat.NORTH: 66},
        )
        self.assertEqual(
            {
                seat: result.for_seat(seat).uma_points
                + result.for_seat(seat).oka_points
                for seat in (Seat.SOUTH, Seat.WEST, Seat.NORTH)
            },
            {Seat.SOUTH: 167, Seat.WEST: 167, Seat.NORTH: 166},
        )
        self.assertEqual(sum(player.final_points for player in result.players), 0)

    def test_four_way_tie_splits_the_full_pot_evenly(self) -> None:
        result = calculate_final_scores(
            {seat: 25_000 for seat in Seat},
            rules=self._rules(),
        )

        self.assertEqual(tuple(player.rank for player in result.players), (1, 1, 1, 1))
        # ウマ(30+10-10-30)=0を4人へ均等分配すると各自0、オカ20は
        # 各自5（内部単位50）ずつとなる。
        self.assertEqual(
            tuple(player.uma_points for player in result.players),
            (0, 0, 0, 0),
        )
        self.assertEqual(
            tuple(player.oka_points for player in result.players),
            (50, 50, 50, 50),
        )
        self.assertEqual(sum(player.final_points for player in result.players), 0)

    def test_non_top_tie_group_preserves_a_negative_uma_total(self) -> None:
        """トップ以外の同点グループで、負のウマ合計も総額どおり保存される
        ことを確認する。
        """
        result = calculate_final_scores(
            {
                Seat.EAST: 40_000,
                Seat.SOUTH: 20_000,
                Seat.WEST: 20_000,
                Seat.NORTH: 20_000,
            },
            rules=self._rules(),
        )

        self.assertEqual(
            {player.seat: player.rank for player in result.players},
            {Seat.EAST: 1, Seat.SOUTH: 2, Seat.WEST: 2, Seat.NORTH: 2},
        )
        # 2〜4位同点グループのウマ合計 (10-10-30) = -30 を3人へ均等分配。
        tied_uma = {
            seat: result.for_seat(seat).uma_points
            for seat in (Seat.SOUTH, Seat.WEST, Seat.NORTH)
        }
        self.assertEqual(sum(tied_uma.values()), _to_internal_points(-30))
        self.assertEqual(
            tied_uma, {Seat.SOUTH: -100, Seat.WEST: -100, Seat.NORTH: -100}
        )
        self.assertEqual(
            tuple(result.for_seat(seat).oka_points for seat in Seat),
            tuple(200 if seat is Seat.EAST else 0 for seat in Seat),
        )
        self.assertEqual(sum(player.final_points for player in result.players), 0)

    def test_combined_totals_match_the_pre_split_allocation_when_uma_and_oka_remainders_conflict(
        self,
    ) -> None:
        """旧python-studyで確定した契約・決定B（[AI-DECISION] comment）の回帰
        テスト。ウマ・オカを別々に按分すると、`uma=(20, 10, -10, -20)`・
        `oka_rank_points=20`の3人トップ同点で両成分の端数が同時に生じ、
        単純な個別按分では各人の合算値が修正前の按分結果から0.1ポイント
        ずれる。決定Bにより、合算目標（修正前と同じ按分）を先に求め、
        オカをその差分として逆算することで、各人の`uma_points +
        oka_points`が修正前の合算按分結果と一致することを固定する。
        """
        rules = replace(self._rules(), uma=(20, 10, -10, -20))
        result = calculate_final_scores(
            {
                Seat.EAST: 10_000,
                Seat.SOUTH: 30_000,
                Seat.WEST: 30_000,
                Seat.NORTH: 30_000,
            },
            rules=rules,
        )

        self.assertEqual(
            {player.seat: player.rank for player in result.players},
            {Seat.EAST: 4, Seat.SOUTH: 1, Seat.WEST: 1, Seat.NORTH: 1},
        )
        # ウマ合計(20+10-10)=20（内部単位200）を3人で按分すると67/67/66。
        self.assertEqual(
            {
                Seat.SOUTH: result.for_seat(Seat.SOUTH).uma_points,
                Seat.WEST: result.for_seat(Seat.WEST).uma_points,
                Seat.NORTH: result.for_seat(Seat.NORTH).uma_points,
            },
            {Seat.SOUTH: 67, Seat.WEST: 67, Seat.NORTH: 66},
        )
        # オカは合算目標(134/133/133)からウマを差し引いた67/66/67。
        self.assertEqual(
            {
                Seat.SOUTH: result.for_seat(Seat.SOUTH).oka_points,
                Seat.WEST: result.for_seat(Seat.WEST).oka_points,
                Seat.NORTH: result.for_seat(Seat.NORTH).oka_points,
            },
            {Seat.SOUTH: 67, Seat.WEST: 66, Seat.NORTH: 67},
        )
        # 各人の合算値は、修正前の「ウマ＋オカを合算してから按分」した
        # 結果（134/133/133）と一致する。
        self.assertEqual(
            {
                seat: result.for_seat(seat).uma_points
                + result.for_seat(seat).oka_points
                for seat in (Seat.SOUTH, Seat.WEST, Seat.NORTH)
            },
            {Seat.SOUTH: 134, Seat.WEST: 133, Seat.NORTH: 133},
        )
        # ウマ・オカそれぞれの総額は保存され、成分間の席差も最大1内部単位。
        self.assertEqual(
            result.for_seat(Seat.SOUTH).uma_points
            + result.for_seat(Seat.WEST).uma_points
            + result.for_seat(Seat.NORTH).uma_points,
            _to_internal_points(20),
        )
        self.assertEqual(
            result.for_seat(Seat.SOUTH).oka_points
            + result.for_seat(Seat.WEST).oka_points
            + result.for_seat(Seat.NORTH).oka_points,
            _to_internal_points(20),
        )
        self.assertEqual(sum(player.final_points for player in result.players), 0)

    def test_base_points_stay_independent_of_the_tie_policy(self) -> None:
        """粗点計算方式（`final_points_rounding`）は同点順位policyと独立で
        あることを確認する。`EXACT_NO_ROUNDING`との組み合わせでも100点
        精度の粗点がそのまま保たれる。
        """
        rules = replace(
            self._rules(),
            final_points_rounding=FinalPointsRounding.EXACT_NO_ROUNDING,
        )
        scores = {
            Seat.EAST: 35_800,
            Seat.SOUTH: 35_800,
            Seat.WEST: 20_100,
            Seat.NORTH: 8_300,
        }
        result = calculate_final_scores(scores, rules=rules)

        for player in result.players:
            self.assertEqual(
                player.base_points,
                (scores[player.seat] - rules.return_points) // 100,
            )
        self.assertEqual(sum(player.final_points for player in result.players), 0)


if __name__ == "__main__":
    unittest.main()
