import unittest
from dataclasses import FrozenInstanceError, replace

from lisjong_engine.dora import DoraCount, DoraIndicators
from lisjong_engine.hand_value import HandValueEvaluation, evaluate_hand_value
from lisjong_engine.meld import Ankan, Daiminkan, Kakan, Pon
from lisjong_engine.rules import RuleSet
from lisjong_engine.score import ScoreCalculation, ScoreLimit, calculate_score
from lisjong_engine.seat import Seat
from lisjong_engine.tile import STANDARD_TILES, Tile, TileCategory, TileType
from lisjong_engine.win_context import (
    RiichiStatus,
    WinMethod,
    WinningContext,
    WinOrigin,
)
from lisjong_engine.wind import Wind
from lisjong_engine.winning import WaitType, WinningShape
from lisjong_engine.winning_score import (
    WinningScoreCandidate,
    WinningScoreSelection,
    enumerate_winning_score_candidates,
    evaluate_winning_scores,
    select_max_score_candidates,
)
from lisjong_engine.yaku import Yaku

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
_TRIPLE_YAKUMAN_NAMES = (
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


def _tiles(*names: str) -> tuple[Tile, ...]:
    copy_counts: dict[TileType, int] = {}
    tiles = []
    for name in names:
        tile_type = TileType(_CATEGORIES[name[-1]], int(name[:-1]))
        copy_index = copy_counts.get(tile_type, 0)
        tiles.append(STANDARD_TILES[tile_type.id * 4 + copy_index])
        copy_counts[tile_type] = copy_index + 1
    return tuple(tiles)


def _tile(name: str, copy_index: int) -> Tile:
    tile_type = TileType(_CATEGORIES[name[-1]], int(name[:-1]))
    return STANDARD_TILES[tile_type.id * 4 + copy_index]


def _ankan(name: str) -> Ankan:
    return Ankan(_tiles(name, name, name, name))


def _pon(name: str) -> Pon:
    tiles = _tiles(name, name, name)
    return Pon(tiles[0], tiles[1:], Seat.NORTH)


def _daiminkan(name: str) -> Daiminkan:
    tiles = _tiles(name, name, name, name)
    return Daiminkan(tiles[0], tiles[1:], Seat.NORTH)


def _kakan(name: str) -> Kakan:
    tiles = _tiles(name, name, name, name)
    return Kakan(Pon(tiles[0], tiles[1:3], Seat.NORTH), tiles[3])


def _context(
    *names: str,
    method: WinMethod = WinMethod.RON,
    is_dealer: bool = False,
) -> WinningContext:
    tiles = _tiles(*names)
    return WinningContext(
        concealed_tiles=tiles,
        winning_tile=tiles[-1],
        method=method,
        origin=WinOrigin.DISCARD if method is WinMethod.RON else WinOrigin.LIVE_WALL,
        seat_wind=Wind.EAST if is_dealer else Wind.SOUTH,
        prevailing_wind=Wind.EAST,
    )


def _hand_value(
    *,
    method: WinMethod = WinMethod.RON,
    is_dealer: bool = False,
    yakuman: bool = False,
) -> HandValueEvaluation:
    names = _TRIPLE_YAKUMAN_NAMES if yakuman else _RYANPEIKOU_NAMES
    context = _context(*names, method=method, is_dealer=is_dealer)
    evaluations = evaluate_hand_value(context)
    if yakuman:
        return next(
            evaluation
            for evaluation in evaluations
            if evaluation.yaku_evaluation.yakuman_units
        )
    return next(
        evaluation
        for evaluation in evaluations
        if evaluation.yaku_evaluation.shape is WinningShape.SEVEN_PAIRS
    )


def _candidate(method: WinMethod, is_dealer: bool) -> WinningScoreCandidate:
    hand_value = _hand_value(method=method, is_dealer=is_dealer)
    fu_calculation = hand_value.fu_calculation
    assert fu_calculation is not None
    score = calculate_score(
        han=hand_value.total_han,
        fu=fu_calculation.rounded_fu,
        method=method,
        is_dealer=is_dealer,
    )
    return WinningScoreCandidate(hand_value, score)


def _candidate_with_score(
    *,
    han: int,
    fu: int | None,
    method: WinMethod = WinMethod.RON,
    is_dealer: bool = False,
    yakuman_units: int = 0,
) -> WinningScoreCandidate:
    hand_value = _hand_value(
        method=method,
        is_dealer=is_dealer,
        yakuman=bool(yakuman_units),
    )
    score = calculate_score(
        han=han,
        fu=fu,
        method=method,
        is_dealer=is_dealer,
        yakuman_units=yakuman_units,
    )
    return WinningScoreCandidate(hand_value, score)


def _five_dora_indicators() -> DoraIndicators:
    """`_RYANPEIKOU_NAMES`の手に対して、赤1枚を含む合計5枚のドラを与える。"""
    return DoraIndicators(
        visible=(_tile("4m", 2),),
        ura=(_tile("9p", 0),),
        kan=(_tile("1m", 2),),
        kan_ura=(_tile("9p", 1),),
    )


def _honor_dora_indicators() -> DoraIndicators:
    """`_TRIPLE_YAKUMAN_NAMES`の手に対して、ドラ2枚を与える。"""
    return DoraIndicators(visible=(_tile("1z", 3),), ura=(_tile("9p", 0),))


class WinningScoreCandidateTest(unittest.TestCase):
    def test_constructs_normal_candidate(self) -> None:
        candidate = _candidate(WinMethod.RON, False)

        self.assertIsInstance(candidate.hand_value, HandValueEvaluation)
        self.assertIsInstance(candidate.score, ScoreCalculation)
        self.assertIsNotNone(candidate.score.fu)

    def test_constructs_explicit_yakuman_candidate_with_no_fu(self) -> None:
        hand_value = _hand_value(yakuman=True)
        score = calculate_score(
            han=0,
            fu=None,
            method=WinMethod.RON,
            is_dealer=False,
            yakuman_units=hand_value.yaku_evaluation.yakuman_units,
        )

        candidate = WinningScoreCandidate(hand_value, score)

        self.assertIsNone(candidate.hand_value.fu_calculation)
        self.assertIsNone(candidate.score.fu)

    def test_winner_points_delegates_to_score(self) -> None:
        for method, is_dealer in (
            (WinMethod.RON, False),
            (WinMethod.RON, True),
            (WinMethod.TSUMO, False),
            (WinMethod.TSUMO, True),
        ):
            with self.subTest(method=method, is_dealer=is_dealer):
                candidate = _candidate(method, is_dealer)

                self.assertEqual(
                    candidate.winner_points,
                    candidate.score.winner_points,
                )
                if method is WinMethod.RON:
                    self.assertEqual(
                        candidate.winner_points,
                        candidate.score.ron_payment,
                    )
                elif is_dealer:
                    assert candidate.score.tsumo_non_dealer_payment is not None
                    self.assertEqual(
                        candidate.winner_points,
                        candidate.score.tsumo_non_dealer_payment * 3,
                    )
                else:
                    assert candidate.score.tsumo_dealer_payment is not None
                    assert candidate.score.tsumo_non_dealer_payment is not None
                    self.assertEqual(
                        candidate.winner_points,
                        candidate.score.tsumo_dealer_payment
                        + candidate.score.tsumo_non_dealer_payment * 2,
                    )

    def test_rejects_invalid_field_types(self) -> None:
        candidate = _candidate(WinMethod.RON, False)

        with self.assertRaises(TypeError):
            WinningScoreCandidate(True, candidate.score)
        with self.assertRaises(TypeError):
            WinningScoreCandidate(candidate.hand_value, True)

    def test_is_frozen(self) -> None:
        candidate = _candidate(WinMethod.RON, False)

        with self.assertRaises(FrozenInstanceError):
            candidate.score = candidate.score


class EnumerateWinningScoreCandidatesTest(unittest.TestCase):
    def test_preserves_every_interpretation_and_its_own_fu(self) -> None:
        context = _context(*_RYANPEIKOU_NAMES)
        hand_values = evaluate_hand_value(context)

        candidates = enumerate_winning_score_candidates(context)

        self.assertIsInstance(candidates, frozenset)
        self.assertEqual(
            {candidate.hand_value for candidate in candidates},
            set(hand_values),
        )
        self.assertEqual(
            {candidate.hand_value.yaku_evaluation.shape for candidate in candidates},
            {WinningShape.STANDARD, WinningShape.SEVEN_PAIRS},
        )
        self.assertGreater(
            sum(
                candidate.hand_value.yaku_evaluation.shape is WinningShape.STANDARD
                for candidate in candidates
            ),
            1,
        )
        for candidate in candidates:
            with self.subTest(evaluation=candidate.hand_value.yaku_evaluation):
                fu_calculation = candidate.hand_value.fu_calculation
                assert fu_calculation is not None
                self.assertEqual(candidate.score.han, candidate.hand_value.total_han)
                self.assertEqual(candidate.score.fu, fu_calculation.rounded_fu)
                self.assertEqual(candidate.score.yakuman_units, 0)
                if (
                    candidate.hand_value.yaku_evaluation.shape
                    is WinningShape.SEVEN_PAIRS
                ):
                    self.assertEqual(candidate.score.fu, 25)

        self.assertGreater(len({candidate.score.han for candidate in candidates}), 1)

    def test_dora_is_applied_and_can_produce_counted_yakuman(self) -> None:
        context = _context(*_RYANPEIKOU_NAMES)

        candidates = enumerate_winning_score_candidates(
            context,
            dora_indicators=_five_dora_indicators(),
        )

        counted_yakuman = [
            candidate for candidate in candidates if candidate.score.han >= 13
        ]
        self.assertTrue(counted_yakuman)
        for candidate in candidates:
            with self.subTest(evaluation=candidate.hand_value.yaku_evaluation):
                self.assertEqual(
                    candidate.hand_value.dora_count,
                    DoraCount(visible=2, red=1, kan=2),
                )
                self.assertEqual(
                    candidate.score.han,
                    candidate.hand_value.yaku_evaluation.han + 5,
                )
        for candidate in counted_yakuman:
            self.assertIsNotNone(candidate.score.fu)
            self.assertEqual(candidate.score.yakuman_units, 0)
            self.assertIs(candidate.score.limit, ScoreLimit.YAKUMAN)

    def test_rules_flow_through_candidate_enumeration(self) -> None:
        context = _context(*_RYANPEIKOU_NAMES)
        disabled_rules = replace(RuleSet.default(), counted_yakuman_enabled=False)

        candidates = enumerate_winning_score_candidates(
            context,
            dora_indicators=_five_dora_indicators(),
            rules=disabled_rules,
        )

        counted_candidates = tuple(
            candidate for candidate in candidates if candidate.score.han >= 13
        )
        self.assertTrue(counted_candidates)
        self.assertTrue(
            all(
                candidate.score.limit is ScoreLimit.SANBAIMAN
                for candidate in counted_candidates
            )
        )
        self.assertTrue(
            all(candidate.score.rules == disabled_rules for candidate in candidates)
        )

    def test_explicit_multiple_yakuman_ignores_dora(self) -> None:
        context = _context(*_TRIPLE_YAKUMAN_NAMES)

        candidates = enumerate_winning_score_candidates(
            context,
            dora_indicators=_honor_dora_indicators(),
        )

        self.assertTrue(candidates)
        for candidate in candidates:
            with self.subTest(evaluation=candidate.hand_value.yaku_evaluation):
                self.assertEqual(candidate.hand_value.yaku_evaluation.yakuman_units, 3)
                self.assertIsNone(candidate.hand_value.dora_count)
                self.assertEqual(candidate.score.han, 0)
                self.assertIsNone(candidate.score.fu)
                self.assertEqual(candidate.score.yakuman_units, 3)
                self.assertEqual(candidate.score.base_points, 24_000)

    def test_context_supplies_method_and_dealer_status(self) -> None:
        expected = {
            (WinMethod.RON, False): (16_000, None, None, 16_000),
            (WinMethod.RON, True): (24_000, None, None, 24_000),
            (WinMethod.TSUMO, False): (None, 8_000, 4_000, 16_000),
            (WinMethod.TSUMO, True): (None, None, 8_000, 24_000),
        }
        for (method, is_dealer), payments in expected.items():
            with self.subTest(method=method, is_dealer=is_dealer):
                context = _context(
                    *_RYANPEIKOU_NAMES,
                    method=method,
                    is_dealer=is_dealer,
                )
                candidate = next(
                    candidate
                    for candidate in enumerate_winning_score_candidates(context)
                    if candidate.hand_value.yaku_evaluation.shape
                    is WinningShape.SEVEN_PAIRS
                )

                self.assertIs(candidate.score.method, method)
                self.assertIs(candidate.score.is_dealer, is_dealer)
                self.assertEqual(
                    (
                        candidate.score.ron_payment,
                        candidate.score.tsumo_dealer_payment,
                        candidate.score.tsumo_non_dealer_payment,
                        candidate.winner_points,
                    ),
                    payments,
                )

    def test_rejects_invalid_inputs(self) -> None:
        context = _context(*_RYANPEIKOU_NAMES)

        with self.assertRaises(TypeError):
            enumerate_winning_score_candidates(True)
        with self.assertRaises(TypeError):
            enumerate_winning_score_candidates(context, dora_indicators=True)
        with self.assertRaises(TypeError):
            enumerate_winning_score_candidates(context, rules=True)

    def test_yakuless_hand_stays_without_candidates_even_with_dora(self) -> None:
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
        indicators = DoraIndicators(
            visible=(_tile("4p", 2),),
            ura=(_tile("1z", 0),),
        )

        self.assertEqual(
            enumerate_winning_score_candidates(context, dora_indicators=indicators),
            frozenset(),
        )
        with self.assertRaises(ValueError):
            evaluate_winning_scores(context, dora_indicators=indicators)


class SelectMaxScoreCandidatesTest(unittest.TestCase):
    def test_selects_by_winner_points_instead_of_han(self) -> None:
        two_han = _candidate_with_score(han=2, fu=110)
        three_han = _candidate_with_score(han=3, fu=30)

        selected = select_max_score_candidates((three_han, two_han))

        self.assertEqual(two_han.winner_points, 7_100)
        self.assertEqual(three_han.winner_points, 3_900)
        self.assertEqual(selected, frozenset({two_han}))
        self.assertIsInstance(selected, frozenset)
        self.assertEqual(select_max_score_candidates((two_han, three_han)), selected)

    def test_preserves_all_candidates_tied_for_mangan(self) -> None:
        three_han = _candidate_with_score(han=3, fu=70)
        four_han = _candidate_with_score(han=4, fu=40)

        selected = select_max_score_candidates((three_han, four_han))

        self.assertEqual(three_han.winner_points, 8_000)
        self.assertEqual(four_han.winner_points, 8_000)
        self.assertEqual(selected, frozenset({three_han, four_han}))

    def test_accepts_supported_iterables_and_single_candidate(self) -> None:
        candidate = _candidate_with_score(han=1, fu=30)
        inputs = (
            frozenset({candidate}),
            {candidate},
            (candidate,),
            [candidate],
            (item for item in (candidate,)),
        )
        for candidates in inputs:
            with self.subTest(type=type(candidates)):
                self.assertEqual(
                    select_max_score_candidates(candidates),
                    frozenset({candidate}),
                )

    def test_generator_is_consumed_only_once(self) -> None:
        lower = _candidate_with_score(han=1, fu=30)
        higher = _candidate_with_score(han=2, fu=40)
        iterations = 0

        def candidates():
            nonlocal iterations
            iterations += 1
            yield lower
            yield higher

        self.assertEqual(
            select_max_score_candidates(candidates()),
            frozenset({higher}),
        )
        self.assertEqual(iterations, 1)

    def test_rejects_empty_or_invalid_inputs(self) -> None:
        candidate = _candidate_with_score(han=1, fu=30)
        with self.assertRaises(ValueError):
            select_max_score_candidates(())
        for candidates in (
            (True, candidate),
            (candidate, 1, candidate),
            (candidate, "invalid"),
        ):
            with self.subTest(candidates=candidates), self.assertRaises(TypeError):
                select_max_score_candidates(candidates)
        with self.assertRaises(TypeError):
            select_max_score_candidates(1)

    def test_selects_multiple_yakuman_over_single_yakuman(self) -> None:
        single = _candidate_with_score(han=0, fu=None, yakuman_units=1)
        multiple = _candidate_with_score(han=0, fu=None, yakuman_units=3)

        self.assertEqual(
            select_max_score_candidates((single, multiple)),
            frozenset({multiple}),
        )

    def test_selects_multiple_yakuman_over_normal_candidate(self) -> None:
        normal = _candidate_with_score(han=4, fu=40)
        multiple_yakuman = _candidate_with_score(han=0, fu=None, yakuman_units=3)

        selected = select_max_score_candidates((multiple_yakuman, normal))

        self.assertEqual(normal.winner_points, 8_000)
        self.assertEqual(multiple_yakuman.score.yakuman_units, 3)
        self.assertEqual(multiple_yakuman.winner_points, 96_000)
        self.assertEqual(selected, frozenset({multiple_yakuman}))

    def test_uses_total_tsumo_winnings(self) -> None:
        ron = _candidate_with_score(han=2, fu=110)
        tsumo = _candidate_with_score(han=2, fu=110, method=WinMethod.TSUMO)

        self.assertEqual(ron.winner_points, 7_100)
        self.assertEqual(tsumo.score.tsumo_dealer_payment, 3_600)
        self.assertEqual(tsumo.winner_points, 7_200)
        self.assertEqual(
            select_max_score_candidates((ron, tsumo)),
            frozenset({tsumo}),
        )

    def test_selects_all_tied_real_interpretations(self) -> None:
        context = _context(*_RYANPEIKOU_NAMES)
        candidates = enumerate_winning_score_candidates(context)

        selected = select_max_score_candidates(candidates)

        self.assertEqual(selected, candidates)
        self.assertGreater(len(selected), 1)


class WinningScoreSelectionTest(unittest.TestCase):
    def test_normalizes_and_holds_complete_maximum_set(self) -> None:
        lower = _candidate_with_score(han=3, fu=30)
        maximum_a = _candidate_with_score(han=3, fu=70)
        maximum_b = _candidate_with_score(han=4, fu=40)

        selection = WinningScoreSelection(
            [lower, maximum_a, maximum_b],
            [maximum_a, maximum_b],
        )

        self.assertEqual(
            selection.candidates,
            frozenset({lower, maximum_a, maximum_b}),
        )
        self.assertEqual(
            selection.max_score_candidates,
            frozenset({maximum_a, maximum_b}),
        )
        self.assertIsInstance(selection.candidates, frozenset)
        self.assertIsInstance(selection.max_score_candidates, frozenset)
        with self.assertRaises(FrozenInstanceError):
            selection.candidates = selection.candidates

    def test_rejects_empty_or_invalid_candidate_collections(self) -> None:
        candidate = _candidate_with_score(han=1, fu=30)
        cases = (
            ((), (), ValueError),
            ((candidate,), (), ValueError),
            ((candidate, True), (candidate,), TypeError),
            ((candidate,), (True,), TypeError),
        )
        for candidates, maximums, error in cases:
            with (
                self.subTest(candidates=candidates, maximums=maximums),
                self.assertRaises(error),
            ):
                WinningScoreSelection(candidates, maximums)

    def test_rejects_subset_that_is_not_the_complete_maximum_set(self) -> None:
        lower = _candidate_with_score(han=3, fu=30)
        maximum_a = _candidate_with_score(han=3, fu=70)
        maximum_b = _candidate_with_score(han=4, fu=40)
        external = _candidate_with_score(han=0, fu=None, yakuman_units=1)
        candidates = frozenset({lower, maximum_a, maximum_b})

        invalid_maximums = (
            frozenset({external}),
            frozenset({lower}),
            frozenset({maximum_a}),
        )
        for maximums in invalid_maximums:
            with self.subTest(maximums=maximums), self.assertRaises(ValueError):
                WinningScoreSelection(candidates, maximums)


class EvaluateWinningScoresTest(unittest.TestCase):
    def test_pinfu_tsumo_uses_20_fu_through_score_selection(self) -> None:
        context = _context(
            "2m",
            "3m",
            "4m",
            "6m",
            "7m",
            "8m",
            "2p",
            "3p",
            "4p",
            "7s",
            "8s",
            "3s",
            "3s",
            "9s",
            method=WinMethod.TSUMO,
        )
        indicators = DoraIndicators(
            visible=(_tile("8s", 2),),
            ura=(_tile("1z", 0),),
        )

        selection = evaluate_winning_scores(context, dora_indicators=indicators)

        self.assertEqual(len(selection.candidates), 1)
        candidate = next(iter(selection.candidates))
        self.assertEqual(
            candidate.hand_value.yaku_evaluation.yakus,
            frozenset({Yaku.PINFU, Yaku.MENZEN_TSUMO}),
        )
        self.assertEqual(candidate.hand_value.dora_count, DoraCount(visible=1))
        self.assertEqual(
            (
                candidate.score.han,
                candidate.score.fu,
                candidate.score.tsumo_dealer_payment,
                candidate.score.tsumo_non_dealer_payment,
                candidate.winner_points,
            ),
            (3, 20, 1_300, 700, 2_700),
        )
        self.assertEqual(selection.max_score_candidates, selection.candidates)

    def test_south_seat_ron_with_two_ankan_and_one_kakan(self) -> None:
        tiles = _tiles("2m", "3m", "4m", "5m", "2m")
        context = WinningContext(
            concealed_tiles=tiles,
            winning_tile=tiles[-1],
            method=WinMethod.RON,
            origin=WinOrigin.DISCARD,
            seat_wind=Wind.SOUTH,
            prevailing_wind=Wind.EAST,
            declared_melds=(_ankan("1p"), _ankan("9p"), _kakan("3z")),
        )

        selection = evaluate_winning_scores(context)
        candidate = next(iter(selection.max_score_candidates))

        self.assertEqual(
            candidate.hand_value.yaku_evaluation.yakus,
            frozenset({Yaku.SANKANTSU}),
        )
        assert candidate.hand_value.fu_calculation is not None
        self.assertEqual(candidate.hand_value.fu_calculation.raw_fu, 102)
        self.assertEqual(
            (candidate.score.han, candidate.score.fu, candidate.winner_points),
            (2, 110, 7_100),
        )

    def test_dealer_tsumo_with_two_pon_and_green_dragon_kakan(self) -> None:
        tiles = _tiles("1s", "1s", "3s", "3s", "1s")
        context = WinningContext(
            concealed_tiles=tiles,
            winning_tile=tiles[-1],
            method=WinMethod.TSUMO,
            origin=WinOrigin.LIVE_WALL,
            seat_wind=Wind.EAST,
            prevailing_wind=Wind.EAST,
            declared_melds=(_pon("2m"), _pon("9m"), _kakan("6z")),
        )

        selection = evaluate_winning_scores(context)
        candidate = next(iter(selection.max_score_candidates))

        self.assertEqual(
            candidate.hand_value.yaku_evaluation.yakus,
            frozenset({Yaku.TOITOI, Yaku.GREEN_DRAGON}),
        )
        assert candidate.hand_value.fu_calculation is not None
        self.assertEqual(candidate.hand_value.fu_calculation.raw_fu, 52)
        self.assertEqual(
            (
                candidate.score.han,
                candidate.score.fu,
                candidate.score.tsumo_non_dealer_payment,
                candidate.winner_points,
            ),
            (3, 60, 3_900, 11_700),
        )

    def test_ron_with_ankan_and_white_dragon_daiminkan(self) -> None:
        tiles = _tiles("1s", "2s", "3s", "6s", "7s", "8s", "7z", "7z")
        context = WinningContext(
            concealed_tiles=tiles,
            winning_tile=tiles[-1],
            method=WinMethod.RON,
            origin=WinOrigin.DISCARD,
            seat_wind=Wind.SOUTH,
            prevailing_wind=Wind.EAST,
            declared_melds=(_ankan("9m"), _daiminkan("5z")),
        )

        selection = evaluate_winning_scores(context)
        candidate = next(iter(selection.max_score_candidates))

        self.assertEqual(
            candidate.hand_value.yaku_evaluation.yakus,
            frozenset({Yaku.WHITE_DRAGON}),
        )
        assert candidate.hand_value.fu_calculation is not None
        self.assertEqual(candidate.hand_value.fu_calculation.raw_fu, 72)
        self.assertEqual(
            (candidate.score.han, candidate.score.fu, candidate.winner_points),
            (1, 80, 2_600),
        )

    def test_west_seat_riichi_tsumo_with_ankan(self) -> None:
        tiles = _tiles(
            "3m",
            "4m",
            "5m",
            "7p",
            "8p",
            "9p",
            "2z",
            "2z",
            "4z",
            "4z",
            "2z",
        )
        context = WinningContext(
            concealed_tiles=tiles,
            winning_tile=tiles[-1],
            method=WinMethod.TSUMO,
            origin=WinOrigin.LIVE_WALL,
            seat_wind=Wind.WEST,
            prevailing_wind=Wind.EAST,
            declared_melds=(_ankan("1m"),),
            riichi_status=RiichiStatus.RIICHI,
        )

        selection = evaluate_winning_scores(context)
        candidate = next(iter(selection.max_score_candidates))

        self.assertEqual(
            candidate.hand_value.yaku_evaluation.yakus,
            frozenset({Yaku.RIICHI, Yaku.MENZEN_TSUMO}),
        )
        assert candidate.hand_value.fu_calculation is not None
        self.assertEqual(candidate.hand_value.fu_calculation.raw_fu, 62)
        self.assertEqual(
            (
                candidate.score.han,
                candidate.score.fu,
                candidate.score.tsumo_dealer_payment,
                candidate.score.tsumo_non_dealer_payment,
                candidate.winner_points,
            ),
            (2, 70, 2_300, 1_200, 4_700),
        )

    def test_selects_50_fu_for_west_seat_tsumo_on_56778m_hand(self) -> None:
        tiles = _tiles(
            "5m",
            "6m",
            "7m",
            "7m",
            "8m",
            "1p",
            "1p",
            "1p",
            "5z",
            "5z",
            "3z",
            "3z",
            "3z",
            "6m",
        )
        context = WinningContext(
            concealed_tiles=tiles,
            winning_tile=tiles[-1],
            method=WinMethod.TSUMO,
            origin=WinOrigin.LIVE_WALL,
            seat_wind=Wind.WEST,
            prevailing_wind=Wind.EAST,
        )

        selection = evaluate_winning_scores(context)

        ryanmen = next(
            candidate
            for candidate in selection.candidates
            if candidate.hand_value.yaku_evaluation.wait_type is WaitType.RYANMEN
        )
        kanchan = next(
            candidate
            for candidate in selection.candidates
            if candidate.hand_value.yaku_evaluation.wait_type is WaitType.KANCHAN
        )
        expected_yakus = frozenset({Yaku.MENZEN_TSUMO, Yaku.SEAT_WIND})

        self.assertEqual(len(selection.candidates), 2)
        self.assertEqual(ryanmen.hand_value.yaku_evaluation.yakus, expected_yakus)
        self.assertEqual(kanchan.hand_value.yaku_evaluation.yakus, expected_yakus)
        assert ryanmen.hand_value.fu_calculation is not None
        assert kanchan.hand_value.fu_calculation is not None
        self.assertEqual(
            (
                ryanmen.hand_value.fu_calculation.raw_fu,
                ryanmen.score.han,
                ryanmen.score.fu,
                ryanmen.score.tsumo_dealer_payment,
                ryanmen.score.tsumo_non_dealer_payment,
                ryanmen.winner_points,
            ),
            (40, 2, 40, 1_300, 700, 2_700),
        )
        self.assertEqual(
            (
                kanchan.hand_value.fu_calculation.raw_fu,
                kanchan.score.han,
                kanchan.score.fu,
                kanchan.score.tsumo_dealer_payment,
                kanchan.score.tsumo_non_dealer_payment,
                kanchan.winner_points,
            ),
            (42, 2, 50, 1_600, 800, 3_200),
        )
        self.assertEqual(selection.max_score_candidates, frozenset({kanchan}))

    def test_selects_best_interpretation_for_888m34445666p22s_ron_4p(self) -> None:
        context = _context(
            "8m",
            "8m",
            "8m",
            "3p",
            "4p",
            "4p",
            "4p",
            "5p",
            "6p",
            "6p",
            "6p",
            "2s",
            "2s",
            "4p",
        )

        selection = evaluate_winning_scores(context)

        kanchan = next(
            candidate
            for candidate in selection.candidates
            if candidate.hand_value.yaku_evaluation.wait_type is WaitType.KANCHAN
        )
        shanpon = next(
            candidate
            for candidate in selection.candidates
            if candidate.hand_value.yaku_evaluation.wait_type is WaitType.SHANPON
        )

        self.assertEqual(len(selection.candidates), 2)
        self.assertEqual(
            kanchan.hand_value.yaku_evaluation.yakus,
            frozenset({Yaku.TANYAO, Yaku.SANANKOU}),
        )
        self.assertEqual(
            (kanchan.score.han, kanchan.score.fu, kanchan.winner_points),
            (3, 50, 6_400),
        )
        self.assertEqual(
            shanpon.hand_value.yaku_evaluation.yakus,
            frozenset({Yaku.TANYAO}),
        )
        self.assertEqual(
            (shanpon.score.han, shanpon.score.fu, shanpon.winner_points),
            (1, 40, 1_300),
        )
        self.assertEqual(selection.max_score_candidates, frozenset({kanchan}))

    def test_selects_best_interpretation_for_111222333p7899s_tsumo_9s(self) -> None:
        context = _context(
            "1p",
            "1p",
            "1p",
            "2p",
            "2p",
            "2p",
            "3p",
            "3p",
            "3p",
            "7s",
            "8s",
            "9s",
            "9s",
            "9s",
            method=WinMethod.TSUMO,
        )

        selection = evaluate_winning_scores(context)

        pinfu = next(
            candidate
            for candidate in selection.candidates
            if Yaku.PINFU in candidate.hand_value.yaku_evaluation.yakus
        )
        junchan_tanki = next(
            candidate
            for candidate in selection.candidates
            if candidate.hand_value.yaku_evaluation.wait_type is WaitType.TANKI
            and Yaku.JUNCHAN in candidate.hand_value.yaku_evaluation.yakus
        )
        sanankou = {
            candidate
            for candidate in selection.candidates
            if Yaku.SANANKOU in candidate.hand_value.yaku_evaluation.yakus
        }

        self.assertEqual(
            pinfu.hand_value.yaku_evaluation.yakus,
            frozenset({Yaku.MENZEN_TSUMO, Yaku.PINFU, Yaku.JUNCHAN, Yaku.IIPEIKOU}),
        )
        self.assertIs(pinfu.hand_value.yaku_evaluation.wait_type, WaitType.RYANMEN)
        self.assertEqual((pinfu.score.han, pinfu.score.fu), (6, 20))
        self.assertEqual(
            (
                pinfu.score.tsumo_dealer_payment,
                pinfu.score.tsumo_non_dealer_payment,
                pinfu.winner_points,
            ),
            (6_000, 3_000, 12_000),
        )
        self.assertEqual(
            junchan_tanki.hand_value.yaku_evaluation.yakus,
            frozenset({Yaku.MENZEN_TSUMO, Yaku.JUNCHAN, Yaku.IIPEIKOU}),
        )
        self.assertEqual((junchan_tanki.score.han, junchan_tanki.score.fu), (5, 30))
        self.assertEqual(len(sanankou), 2)
        self.assertTrue(
            all(
                (candidate.score.han, candidate.score.fu, candidate.winner_points)
                == (3, 40, 5_200)
                for candidate in sanankou
            )
        )
        self.assertEqual(selection.max_score_candidates, frozenset({pinfu}))

    def test_composes_enumeration_and_maximum_selection(self) -> None:
        context = _context(
            "1m",
            "1m",
            "2m",
            "2m",
            "3m",
            "3m",
            "4p",
            "4p",
            "5p",
            "5p",
            "6p",
            "6p",
            "7s",
            "7s",
        )

        selection = evaluate_winning_scores(context)
        expected_candidates = enumerate_winning_score_candidates(context)

        self.assertIsInstance(selection, WinningScoreSelection)
        self.assertEqual(selection.candidates, expected_candidates)
        self.assertEqual(
            selection.max_score_candidates,
            select_max_score_candidates(expected_candidates),
        )
        self.assertGreater(len(selection.candidates), 1)
        self.assertEqual(len(selection.max_score_candidates), 1)
        self.assertLess(
            min(candidate.winner_points for candidate in selection.candidates),
            next(iter(selection.max_score_candidates)).winner_points,
        )
        standard = next(
            candidate
            for candidate in selection.candidates
            if candidate.hand_value.yaku_evaluation.shape is WinningShape.STANDARD
        )
        seven_pairs = next(
            candidate
            for candidate in selection.candidates
            if candidate.hand_value.yaku_evaluation.shape is WinningShape.SEVEN_PAIRS
        )

        self.assertIn(Yaku.RYANPEIKOU, standard.hand_value.yaku_evaluation.yakus)
        self.assertEqual(
            (standard.score.han, standard.score.fu, standard.winner_points),
            (3, 40, 5_200),
        )
        self.assertEqual(
            (seven_pairs.score.han, seven_pairs.score.fu, seven_pairs.winner_points),
            (2, 25, 1_600),
        )
        self.assertEqual(selection.max_score_candidates, frozenset({standard}))

    def test_preserves_all_tied_maximum_interpretations(self) -> None:
        context = _context(*_RYANPEIKOU_NAMES)

        selection = evaluate_winning_scores(context)

        self.assertEqual(selection.max_score_candidates, selection.candidates)
        self.assertGreater(len(selection.max_score_candidates), 1)
        self.assertEqual(
            {
                candidate.hand_value.yaku_evaluation.shape
                for candidate in selection.candidates
            },
            {WinningShape.STANDARD, WinningShape.SEVEN_PAIRS},
        )
        for candidate in selection.candidates:
            with self.subTest(evaluation=candidate.hand_value.yaku_evaluation):
                self.assertIs(candidate.score.limit, ScoreLimit.BAIMAN)
                self.assertEqual(candidate.score.base_points, 4_000)
                self.assertEqual(candidate.winner_points, 16_000)

    def test_custom_double_wind_pair_fu_changes_the_score(self) -> None:
        tiles = _tiles(
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
        context = WinningContext(
            concealed_tiles=tiles,
            winning_tile=tiles[-1],
            method=WinMethod.TSUMO,
            origin=WinOrigin.LIVE_WALL,
            seat_wind=Wind.EAST,
            prevailing_wind=Wind.EAST,
        )
        custom_rules = replace(RuleSet.default(), double_wind_pair_fu=2)

        common = evaluate_winning_scores(context)
        custom = evaluate_winning_scores(context, rules=custom_rules)
        common_candidate = next(iter(common.max_score_candidates))
        custom_candidate = next(iter(custom.max_score_candidates))

        self.assertEqual(
            (common_candidate.score.fu, common_candidate.winner_points),
            (40, 2_100),
        )
        self.assertEqual(
            (custom_candidate.score.fu, custom_candidate.winner_points),
            (30, 1_500),
        )
        self.assertEqual(
            custom.candidates,
            enumerate_winning_score_candidates(context, rules=custom_rules),
        )

    def test_double_yakuman_variants_change_units_but_ignore_dora(self) -> None:
        context = _context(*_TRIPLE_YAKUMAN_NAMES)
        indicators = _honor_dora_indicators()
        custom_rules = replace(
            RuleSet.default(),
            double_yakuman_variants=frozenset({Yaku.SUUANKOU_TANKI}),
        )

        common = evaluate_winning_scores(context, dora_indicators=indicators)
        custom = evaluate_winning_scores(
            context,
            dora_indicators=indicators,
            rules=custom_rules,
        )

        self.assertEqual(
            {
                (candidate.score.yakuman_units, candidate.winner_points)
                for candidate in common.candidates
            },
            {(3, 96_000)},
        )
        self.assertEqual(
            {
                (candidate.score.yakuman_units, candidate.winner_points)
                for candidate in custom.candidates
            },
            {(4, 128_000)},
        )
        self.assertTrue(
            all(
                candidate.hand_value.dora_count is None
                and candidate.hand_value.total_han == 0
                for candidate in common.candidates | custom.candidates
            )
        )
        self.assertEqual(
            custom.candidates,
            enumerate_winning_score_candidates(
                context,
                dora_indicators=indicators,
                rules=custom_rules,
            ),
        )
        self.assertEqual(
            custom.max_score_candidates,
            select_max_score_candidates(custom.candidates),
        )

    def test_preserves_explicit_yakuman_contract(self) -> None:
        context = _context(*_TRIPLE_YAKUMAN_NAMES)

        selection = evaluate_winning_scores(
            context,
            dora_indicators=_honor_dora_indicators(),
        )
        without_dora = evaluate_winning_scores(context)

        self.assertEqual(selection, without_dora)
        self.assertEqual(
            selection.max_score_candidates,
            select_max_score_candidates(selection.candidates),
        )
        for candidate in selection.candidates:
            with self.subTest(evaluation=candidate.hand_value.yaku_evaluation):
                self.assertIsNone(candidate.hand_value.dora_count)
                self.assertEqual(candidate.hand_value.total_han, 0)
                self.assertEqual(candidate.score.han, 0)
                self.assertIsNone(candidate.score.fu)
                self.assertEqual(candidate.score.yakuman_units, 3)

    def test_delegates_invalid_input_validation(self) -> None:
        context = _context(
            "1m",
            "1m",
            "2m",
            "2m",
            "3m",
            "3m",
            "4p",
            "4p",
            "5p",
            "5p",
            "6p",
            "6p",
            "7s",
            "7s",
        )
        calls = (
            ((True,), {}),
            ((context,), {"dora_indicators": True}),
            ((context,), {"rules": True}),
        )
        for args, kwargs in calls:
            with self.subTest(args=args, kwargs=kwargs), self.assertRaises(TypeError):
                evaluate_winning_scores(*args, **kwargs)


if __name__ == "__main__":
    unittest.main()
