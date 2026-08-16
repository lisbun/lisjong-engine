import unittest
from dataclasses import FrozenInstanceError

from lisjong_engine.dora import DoraCount, DoraIndicators, count_dora, dora_tile_type
from lisjong_engine.meld import Ankan, Chi
from lisjong_engine.score import ScoreLimit
from lisjong_engine.seat import Seat
from lisjong_engine.tile import STANDARD_TILES, Tile, TileCategory, TileType
from lisjong_engine.win_context import (
    RiichiStatus,
    WinMethod,
    WinningContext,
    WinOrigin,
)
from lisjong_engine.wind import Wind
from lisjong_engine.winning_score import (
    enumerate_winning_score_candidates,
    evaluate_winning_scores,
)

_CATEGORIES = {
    "m": TileCategory.MANZU,
    "p": TileCategory.PINZU,
    "s": TileCategory.SOUZU,
    "z": TileCategory.HONOR,
}


def _tile(category: TileCategory, rank: int, copy_index: int = 0) -> Tile:
    return STANDARD_TILES[TileType(category, rank).id * 4 + copy_index]


def _context(
    concealed_tiles: tuple[Tile, ...],
    *,
    melds: tuple[object, ...] = (),
    riichi_status: RiichiStatus = RiichiStatus.NONE,
) -> WinningContext:
    return WinningContext(
        concealed_tiles=concealed_tiles,
        winning_tile=concealed_tiles[-1],
        method=WinMethod.RON,
        origin=WinOrigin.DISCARD,
        seat_wind=Wind.SOUTH,
        prevailing_wind=Wind.EAST,
        declared_melds=melds,
        riichi_status=riichi_status,
    )


def _named_context(
    names: tuple[str, ...],
    *,
    riichi_status: RiichiStatus = RiichiStatus.NONE,
) -> WinningContext:
    counts: dict[TileType, int] = {}
    tiles = []
    for name in names:
        tile_type = TileType(_CATEGORIES[name[-1]], int(name[:-1]))
        copy_index = counts.get(tile_type, 0)
        tiles.append(_tile(tile_type.category, tile_type.rank, copy_index))
        counts[tile_type] = copy_index + 1
    return _context(tuple(tiles), riichi_status=riichi_status)


def _indicator_pair(indicator: Tile, ura: Tile) -> DoraIndicators:
    return DoraIndicators(visible=(indicator,), ura=(ura,))


class DoraTileTypeTest(unittest.TestCase):
    def test_suited_tiles_wrap_after_nine(self) -> None:
        cases = (
            (TileType(TileCategory.MANZU, 1), TileType(TileCategory.MANZU, 2)),
            (TileType(TileCategory.MANZU, 9), TileType(TileCategory.MANZU, 1)),
            (TileType(TileCategory.PINZU, 9), TileType(TileCategory.PINZU, 1)),
            (TileType(TileCategory.SOUZU, 9), TileType(TileCategory.SOUZU, 1)),
        )
        for indicator, expected in cases:
            with self.subTest(indicator=indicator):
                self.assertEqual(dora_tile_type(indicator), expected)

    def test_winds_and_dragons_use_their_own_cycles(self) -> None:
        expected_ranks = (2, 3, 4, 1, 6, 7, 5)
        for rank, expected_rank in enumerate(expected_ranks, 1):
            with self.subTest(rank=rank):
                self.assertEqual(
                    dora_tile_type(TileType(TileCategory.HONOR, rank)),
                    TileType(TileCategory.HONOR, expected_rank),
                )

    def test_red_five_indicator_is_treated_as_a_five(self) -> None:
        self.assertTrue(_tile(TileCategory.MANZU, 5).is_red)
        self.assertEqual(
            dora_tile_type(_tile(TileCategory.MANZU, 5)),
            TileType(TileCategory.MANZU, 6),
        )

    def test_rejects_non_indicator_type(self) -> None:
        with self.assertRaises(TypeError):
            dora_tile_type("1m")


class DoraModelTest(unittest.TestCase):
    def test_count_is_frozen_and_total_is_sum_of_parts(self) -> None:
        count = DoraCount(visible=1, ura=2, red=3, kan=4, kan_ura=5)

        self.assertEqual(count.total, 15)
        with self.assertRaises(FrozenInstanceError):
            count.visible = 2

    def test_count_rejects_bool_non_integer_and_negative_values(self) -> None:
        for value, error in ((True, TypeError), (1.5, TypeError), (-1, ValueError)):
            with self.subTest(value=value), self.assertRaises(error):
                DoraCount(visible=value)

    def test_indicators_copy_inputs_and_validate_correspondence(self) -> None:
        visible = [_tile(TileCategory.MANZU, 1)]
        indicators = DoraIndicators(
            visible=visible,
            ura=(_tile(TileCategory.PINZU, 1),),
        )
        visible.clear()

        self.assertEqual(len(indicators.visible), 1)
        for kwargs in (
            {"visible": ("1m",)},
            {"visible": (_tile(TileCategory.MANZU, 1),), "ura": ()},
            {
                "visible": (_tile(TileCategory.MANZU, 1),),
                "ura": (_tile(TileCategory.MANZU, 1),),
            },
            {
                "visible": (
                    _tile(TileCategory.MANZU, 1),
                    _tile(TileCategory.MANZU, 2),
                ),
                "ura": (
                    _tile(TileCategory.PINZU, 1),
                    _tile(TileCategory.PINZU, 2),
                ),
            },
            {
                "kan": tuple(_tile(TileCategory.SOUZU, rank) for rank in range(1, 6)),
                "kan_ura": tuple(
                    _tile(TileCategory.SOUZU, rank, 1) for rank in range(1, 6)
                ),
            },
        ):
            with (
                self.subTest(kwargs=kwargs),
                self.assertRaises((TypeError, ValueError)),
            ):
                DoraIndicators(**kwargs)

    def test_all_tiles_covers_every_indicator_region(self) -> None:
        indicators = DoraIndicators(
            visible=(_tile(TileCategory.MANZU, 1),),
            ura=(_tile(TileCategory.MANZU, 2),),
            kan=(_tile(TileCategory.MANZU, 3),),
            kan_ura=(_tile(TileCategory.MANZU, 4),),
        )

        self.assertEqual(
            tuple(tile.id for tile in indicators.all_tiles),
            (
                _tile(TileCategory.MANZU, 1).id,
                _tile(TileCategory.MANZU, 2).id,
                _tile(TileCategory.MANZU, 3).id,
                _tile(TileCategory.MANZU, 4).id,
            ),
        )


class DoraCountTest(unittest.TestCase):
    def test_visible_dora_counts_zero_one_two_and_four_owned_tiles(self) -> None:
        indicator = _tile(TileCategory.MANZU, 1)
        ura = _tile(TileCategory.PINZU, 1)
        for count in (0, 1, 2, 4):
            owned = tuple(_tile(TileCategory.MANZU, 2, index) for index in range(count))
            concealed = owned or (_tile(TileCategory.SOUZU, 9),)
            with self.subTest(count=count):
                self.assertEqual(
                    count_dora(_context(concealed), _indicator_pair(indicator, ura)),
                    DoraCount(visible=count),
                )

    def test_counts_tiles_across_concealed_chi_and_ankan_including_all_four(
        self,
    ) -> None:
        concealed = (_tile(TileCategory.SOUZU, 9),)
        chi = Chi(
            _tile(TileCategory.MANZU, 2, 0),
            (
                _tile(TileCategory.MANZU, 3, 0),
                _tile(TileCategory.MANZU, 4, 0),
            ),
            Seat.EAST,
        )
        ankan = Ankan(tuple(_tile(TileCategory.PINZU, 2, i) for i in range(4)))
        indicators = DoraIndicators(
            visible=(_tile(TileCategory.MANZU, 1),),
            ura=(_tile(TileCategory.SOUZU, 1),),
            kan=(_tile(TileCategory.PINZU, 1),),
            kan_ura=(_tile(TileCategory.SOUZU, 2),),
        )

        count = count_dora(_context(concealed, melds=(chi, ankan)), indicators)

        self.assertEqual(count.visible, 1)
        self.assertEqual(count.kan, 4)

    def test_duplicate_indicator_types_are_each_counted(self) -> None:
        owned = tuple(_tile(TileCategory.MANZU, 2, index) for index in range(2))
        indicators = DoraIndicators(
            visible=(_tile(TileCategory.MANZU, 1, 0),),
            ura=(_tile(TileCategory.PINZU, 9, 0),),
            kan=(_tile(TileCategory.MANZU, 1, 1),),
            kan_ura=(_tile(TileCategory.PINZU, 9, 1),),
        )

        self.assertEqual(count_dora(_context(owned), indicators).visible, 2)
        self.assertEqual(count_dora(_context(owned), indicators).kan, 2)

    def test_red_five_counts_as_red_and_indicator_dora(self) -> None:
        red_five = _tile(TileCategory.SOUZU, 5, 0)
        normal_five = _tile(TileCategory.SOUZU, 5, 1)
        indicators = _indicator_pair(
            _tile(TileCategory.SOUZU, 4),
            _tile(TileCategory.PINZU, 1),
        )

        count = count_dora(_context((red_five, normal_five)), indicators)

        self.assertEqual(count, DoraCount(visible=2, red=1))

    def test_red_tiles_in_open_melds_and_quads_are_counted(self) -> None:
        red = _tile(TileCategory.MANZU, 5, 0)
        chi = Chi(
            red,
            (_tile(TileCategory.MANZU, 4), _tile(TileCategory.MANZU, 6)),
            Seat.EAST,
        )
        ankan = Ankan(tuple(_tile(TileCategory.PINZU, 5, i) for i in range(4)))

        count = count_dora(
            _context((_tile(TileCategory.SOUZU, 9),), melds=(chi, ankan)),
            DoraIndicators(),
        )

        self.assertEqual(count.red, 2)

    def test_ura_and_kan_ura_require_established_riichi(self) -> None:
        owned = (_tile(TileCategory.MANZU, 2), _tile(TileCategory.PINZU, 2))
        indicators = DoraIndicators(
            visible=(_tile(TileCategory.SOUZU, 9),),
            ura=(_tile(TileCategory.MANZU, 1),),
            kan=(_tile(TileCategory.HONOR, 7),),
            kan_ura=(_tile(TileCategory.PINZU, 1),),
        )

        for status, expected in (
            (RiichiStatus.NONE, DoraCount()),
            (RiichiStatus.RIICHI, DoraCount(ura=1, kan_ura=1)),
            (RiichiStatus.DOUBLE_RIICHI, DoraCount(ura=1, kan_ura=1)),
        ):
            with self.subTest(status=status):
                self.assertEqual(
                    count_dora(_context(owned, riichi_status=status), indicators),
                    expected,
                )

    def test_rejects_physical_tile_shared_by_hand_and_indicator(self) -> None:
        tile = _tile(TileCategory.MANZU, 1)

        with self.assertRaises(ValueError):
            count_dora(
                _context((tile,)),
                _indicator_pair(tile, _tile(TileCategory.PINZU, 1)),
            )

    def test_rejects_invalid_argument_types(self) -> None:
        context = _context((_tile(TileCategory.MANZU, 1),))

        with self.assertRaises(TypeError):
            count_dora((), DoraIndicators())
        with self.assertRaises(TypeError):
            count_dora(context, ())


class DoraWinningScoreIntegrationTest(unittest.TestCase):
    def test_real_hand_dora_breakdown_flows_into_han_fu_and_points(self) -> None:
        context = _named_context(
            (
                "1m",
                "1m",
                "2m",
                "2m",
                "3p",
                "3p",
                "4p",
                "4p",
                "6s",
                "6s",
                "8s",
                "8s",
                "7z",
                "7z",
            )
        )
        indicators = _indicator_pair(
            _tile(TileCategory.HONOR, 6, 2),
            _tile(TileCategory.MANZU, 9),
        )

        dora = count_dora(context, indicators)
        selection = evaluate_winning_scores(context, dora_indicators=indicators)
        candidates = enumerate_winning_score_candidates(
            context,
            dora_indicators=indicators,
        )

        self.assertEqual(dora, DoraCount(visible=2))
        self.assertEqual(selection.candidates, candidates)
        candidate = next(iter(selection.max_score_candidates))
        self.assertEqual(candidate.hand_value.dora_count, dora)
        self.assertEqual(candidate.hand_value.dora_han, 2)
        self.assertEqual(candidate.hand_value.total_han, 4)
        self.assertEqual(candidate.score.fu, 25)
        self.assertEqual(candidate.score.ron_payment, 6_400)
        self.assertEqual(candidate.winner_points, 6_400)

    def test_all_dora_kinds_flow_to_bonus_han_without_becoming_yaku(self) -> None:
        context = _named_context(
            (
                "1m",
                "1m",
                "2m",
                "2m",
                "3p",
                "3p",
                "4p",
                "4p",
                "5s",
                "5s",
                "6s",
                "6s",
                "7z",
                "7z",
            ),
            riichi_status=RiichiStatus.RIICHI,
        )
        indicators = DoraIndicators(
            visible=(_tile(TileCategory.HONOR, 6, 2),),
            ura=(_tile(TileCategory.SOUZU, 4, 2),),
            kan=(_tile(TileCategory.SOUZU, 5, 2),),
            kan_ura=(_tile(TileCategory.HONOR, 6, 3),),
        )

        dora = count_dora(context, indicators)
        candidate = next(
            iter(
                evaluate_winning_scores(
                    context,
                    dora_indicators=indicators,
                ).max_score_candidates
            )
        )

        self.assertEqual(dora, DoraCount(visible=2, ura=2, red=1, kan=2, kan_ura=2))
        self.assertEqual(candidate.hand_value.dora_count, dora)
        self.assertEqual(candidate.hand_value.dora_han, 9)
        self.assertEqual(candidate.hand_value.total_han, 12)
        self.assertEqual(candidate.score.fu, 25)
        self.assertIs(candidate.score.limit, ScoreLimit.SANBAIMAN)
        self.assertEqual(candidate.winner_points, 24_000)

    def test_automatic_dora_can_reach_counted_yakuman(self) -> None:
        context = _named_context(
            (
                "1m",
                "1m",
                "2m",
                "2m",
                "3p",
                "3p",
                "4p",
                "4p",
                "5s",
                "5s",
                "6s",
                "6s",
                "7z",
                "7z",
            )
        )
        indicators = DoraIndicators(
            visible=(_tile(TileCategory.HONOR, 6, 2),),
            ura=(_tile(TileCategory.MANZU, 9),),
            kan=(
                _tile(TileCategory.HONOR, 6, 3),
                _tile(TileCategory.HONOR, 6, 0),
                _tile(TileCategory.HONOR, 6, 1),
                _tile(TileCategory.SOUZU, 5, 2),
            ),
            kan_ura=(
                _tile(TileCategory.PINZU, 9, 0),
                _tile(TileCategory.PINZU, 9, 1),
                _tile(TileCategory.PINZU, 9, 2),
                _tile(TileCategory.PINZU, 9, 3),
            ),
        )

        dora = count_dora(context, indicators)
        candidate = next(
            iter(
                evaluate_winning_scores(
                    context,
                    dora_indicators=indicators,
                ).max_score_candidates
            )
        )

        self.assertEqual(dora.total, 11)
        self.assertEqual(candidate.hand_value.dora_count, dora)
        self.assertEqual(candidate.hand_value.total_han, 13)
        self.assertIs(candidate.score.limit, ScoreLimit.YAKUMAN)
        self.assertEqual(candidate.score.yakuman_units, 0)
        self.assertEqual(candidate.winner_points, 32_000)

    def test_explicit_yakuman_ignores_automatic_dora(self) -> None:
        context = _named_context(
            (
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
        )
        indicators = _indicator_pair(
            _tile(TileCategory.HONOR, 4, 2),
            _tile(TileCategory.MANZU, 9),
        )

        candidates = evaluate_winning_scores(
            context,
            dora_indicators=indicators,
        ).candidates

        self.assertGreater(count_dora(context, indicators).total, 0)
        for candidate in candidates:
            self.assertGreater(candidate.score.yakuman_units, 0)
            self.assertEqual(candidate.hand_value.dora_han, 0)
            self.assertEqual(candidate.hand_value.total_han, 0)
            self.assertIsNone(candidate.hand_value.dora_count)

    def test_dora_alone_does_not_create_a_winning_candidate(self) -> None:
        context = _named_context(
            (
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
        )
        indicators = _indicator_pair(
            _tile(TileCategory.PINZU, 4, 2),
            _tile(TileCategory.HONOR, 1),
        )

        self.assertGreater(count_dora(context, indicators).total, 0)
        self.assertEqual(
            enumerate_winning_score_candidates(
                context,
                dora_indicators=indicators,
            ),
            frozenset(),
        )
        with self.assertRaises(ValueError):
            evaluate_winning_scores(context, dora_indicators=indicators)


if __name__ == "__main__":
    unittest.main()
