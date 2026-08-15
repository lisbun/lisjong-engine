import unittest

from lisjong_engine.interpretation_analysis import (
    GroupAnalysis,
    GroupKind,
    WinningInterpretationAnalysis,
    analyze_winning_interpretation,
)
from lisjong_engine.meld import Ankan, Chi, Daiminkan, Kakan, Pon
from lisjong_engine.seat import Seat
from lisjong_engine.tile import STANDARD_TILES, Tile, TileCategory, TileType
from lisjong_engine.win_context import WinMethod, WinningContext, WinOrigin
from lisjong_engine.wind import Wind
from lisjong_engine.winning import (
    StandardWinningInterpretation,
    WaitType,
    find_standard_winning_interpretations,
)

_CATEGORIES = {
    "m": TileCategory.MANZU,
    "p": TileCategory.PINZU,
    "s": TileCategory.SOUZU,
    "z": TileCategory.HONOR,
}


def _tile_type(name: str) -> TileType:
    return TileType(_CATEGORIES[name[-1]], int(name[:-1]))


class _TilePool:
    """同じ牌種の物理牌を重複なく払い出す。"""

    def __init__(self) -> None:
        self._copy_counts: dict[TileType, int] = {}

    def take(self, *names: str) -> tuple[Tile, ...]:
        tiles = []
        for name in names:
            tile_type = _tile_type(name)
            copy_index = self._copy_counts.get(tile_type, 0)
            if copy_index >= 4:
                raise ValueError("test fixture requests a fifth tile")
            tiles.append(STANDARD_TILES[tile_type.id * 4 + copy_index])
            self._copy_counts[tile_type] = copy_index + 1
        return tuple(tiles)


def _context(
    concealed_tiles: tuple[Tile, ...],
    *,
    winning_tile: Tile | None = None,
    declared_melds: tuple[object, ...] = (),
    method: WinMethod = WinMethod.RON,
    origin: WinOrigin = WinOrigin.DISCARD,
    seat_wind: Wind = Wind.SOUTH,
    prevailing_wind: Wind = Wind.EAST,
) -> WinningContext:
    return WinningContext(
        concealed_tiles=concealed_tiles,
        winning_tile=(concealed_tiles[-1] if winning_tile is None else winning_tile),
        method=method,
        origin=origin,
        seat_wind=seat_wind,
        prevailing_wind=prevailing_wind,
        declared_melds=declared_melds,
    )


def _interpretations(
    context: WinningContext,
) -> frozenset[StandardWinningInterpretation]:
    return find_standard_winning_interpretations(
        context.concealed_tiles,
        context.winning_tile,
        context.declared_melds,
    )


def _analyze_sole_interpretation(
    context: WinningContext,
) -> WinningInterpretationAnalysis:
    interpretations = _interpretations(context)
    if len(interpretations) != 1:
        raise ValueError("test fixture expects exactly one winning interpretation")
    return analyze_winning_interpretation(context, next(iter(interpretations)))


def _group_analysis(
    analysis: WinningInterpretationAnalysis,
    kind: GroupKind,
    tile_type: TileType,
) -> GroupAnalysis:
    matches = [
        group
        for group in analysis.groups
        if group.kind is kind and group.tile_type == tile_type
    ]
    if len(matches) != 1:
        raise ValueError("test fixture expects exactly one matching group")
    return matches[0]


def _ryanmen_context_with_meld(
    pool: _TilePool,
    meld: object,
    *,
    method: WinMethod = WinMethod.RON,
    origin: WinOrigin = WinOrigin.DISCARD,
) -> WinningContext:
    """副露1つ+手牌内3面子1雀頭で、1mの両面待ちを和了した局面を作る。"""
    concealed_tiles = pool.take(
        "1m",
        "2m",
        "3m",
        "4p",
        "5p",
        "6p",
        "7s",
        "8s",
        "9s",
        "2z",
        "2z",
    )
    return _context(
        concealed_tiles,
        winning_tile=concealed_tiles[0],
        declared_melds=(meld,),
        method=method,
        origin=origin,
    )


def _pair_context(
    pair_name: str,
    *,
    seat_wind: Wind,
    prevailing_wind: Wind,
) -> WinningContext:
    pool = _TilePool()
    concealed_tiles = pool.take(
        "1m",
        "2m",
        "3m",
        "4p",
        "5p",
        "6p",
        "7s",
        "8s",
        "9s",
        "9p",
        "9p",
        "9p",
        pair_name,
        pair_name,
    )
    return _context(
        concealed_tiles,
        seat_wind=seat_wind,
        prevailing_wind=prevailing_wind,
    )


def _shanpon_context(
    *,
    method: WinMethod = WinMethod.RON,
    origin: WinOrigin = WinOrigin.DISCARD,
) -> WinningContext:
    """1mと3zの双碰で、1mを和了した局面を作る。"""
    pool = _TilePool()
    concealed_tiles = pool.take(
        "1m",
        "1m",
        "1m",
        "4p",
        "5p",
        "6p",
        "7s",
        "8s",
        "9s",
        "3z",
        "3z",
        "3z",
        "2z",
        "2z",
    )
    return _context(
        concealed_tiles,
        winning_tile=concealed_tiles[2],
        method=method,
        origin=origin,
    )


class ConcealedGroupAnalysisTest(unittest.TestCase):
    def test_analyzes_concealed_sequence(self) -> None:
        pool = _TilePool()
        concealed_tiles = pool.take(
            "1m",
            "2m",
            "3m",
            "4p",
            "5p",
            "6p",
            "7s",
            "8s",
            "9s",
            "1z",
            "1z",
            "1z",
            "2z",
            "2z",
        )
        context = _context(concealed_tiles, winning_tile=concealed_tiles[0])

        analysis = _analyze_sole_interpretation(context)
        group = _group_analysis(
            analysis,
            GroupKind.SEQUENCE,
            _tile_type("1m"),
        )

        self.assertFalse(group.is_open)
        self.assertFalse(group.is_terminal_or_honor)
        self.assertFalse(group.is_completed_by_ron)
        self.assertTrue(group.is_concealed_for_scoring)

    def test_analyzes_concealed_triplet(self) -> None:
        pool = _TilePool()
        concealed_tiles = pool.take(
            "1m",
            "2m",
            "3m",
            "4p",
            "5p",
            "6p",
            "7s",
            "8s",
            "9s",
            "1z",
            "1z",
            "1z",
            "2z",
            "2z",
        )
        context = _context(concealed_tiles, winning_tile=concealed_tiles[0])

        analysis = _analyze_sole_interpretation(context)
        group = _group_analysis(
            analysis,
            GroupKind.TRIPLET,
            _tile_type("1z"),
        )

        self.assertFalse(group.is_open)
        self.assertTrue(group.is_terminal_or_honor)
        self.assertFalse(group.is_completed_by_ron)
        self.assertTrue(group.is_concealed_for_scoring)

    def test_marks_only_the_triplet_completed_by_ron(self) -> None:
        analysis = _analyze_sole_interpretation(_shanpon_context())

        completed_triplet = _group_analysis(
            analysis,
            GroupKind.TRIPLET,
            _tile_type("1m"),
        )
        other_triplet = _group_analysis(
            analysis,
            GroupKind.TRIPLET,
            _tile_type("3z"),
        )

        self.assertTrue(completed_triplet.is_completed_by_ron)
        self.assertFalse(completed_triplet.is_concealed_for_scoring)
        self.assertFalse(other_triplet.is_completed_by_ron)
        self.assertTrue(other_triplet.is_concealed_for_scoring)

    def test_keeps_tsumo_completed_triplet_concealed(self) -> None:
        context = _shanpon_context(
            method=WinMethod.TSUMO,
            origin=WinOrigin.LIVE_WALL,
        )

        analysis = _analyze_sole_interpretation(context)
        completed_triplet = _group_analysis(
            analysis,
            GroupKind.TRIPLET,
            _tile_type("1m"),
        )

        self.assertFalse(completed_triplet.is_completed_by_ron)
        self.assertTrue(completed_triplet.is_concealed_for_scoring)

    def test_distinguishes_terminal_honor_and_simple_triplets(self) -> None:
        pool = _TilePool()
        concealed_tiles = pool.take(
            "9m",
            "9m",
            "9m",
            "2m",
            "2m",
            "2m",
            "4p",
            "5p",
            "6p",
            "7s",
            "8s",
            "9s",
            "2z",
            "2z",
        )
        context = _context(concealed_tiles)

        analysis = _analyze_sole_interpretation(context)

        self.assertTrue(
            _group_analysis(
                analysis,
                GroupKind.TRIPLET,
                _tile_type("9m"),
            ).is_terminal_or_honor
        )
        self.assertFalse(
            _group_analysis(
                analysis,
                GroupKind.TRIPLET,
                _tile_type("2m"),
            ).is_terminal_or_honor
        )
        self.assertFalse(
            _group_analysis(
                analysis,
                GroupKind.SEQUENCE,
                _tile_type("7s"),
            ).is_terminal_or_honor
        )


class DeclaredMeldAnalysisTest(unittest.TestCase):
    def test_analyzes_chi_as_open_sequence_after_concealed_groups(self) -> None:
        pool = _TilePool()
        chi_tiles = pool.take("2s", "3s", "1s")
        chi = Chi(chi_tiles[0], chi_tiles[1:], Seat.NORTH)
        context = _ryanmen_context_with_meld(pool, chi)

        analysis = _analyze_sole_interpretation(context)
        group = analysis.groups[-1]

        self.assertIs(group.kind, GroupKind.SEQUENCE)
        self.assertEqual(group.tile_type, _tile_type("1s"))
        self.assertTrue(group.is_open)
        self.assertFalse(group.is_terminal_or_honor)
        self.assertFalse(group.is_completed_by_ron)
        self.assertFalse(group.is_concealed_for_scoring)
        self.assertEqual(len(analysis.groups), 4)

    def test_analyzes_pon_as_open_triplet(self) -> None:
        pool = _TilePool()
        pon_tiles = pool.take("5z", "5z", "5z")
        pon = Pon(pon_tiles[0], pon_tiles[1:], Seat.WEST)
        context = _ryanmen_context_with_meld(pool, pon)

        analysis = _analyze_sole_interpretation(context)
        group = analysis.groups[-1]

        self.assertIs(group.kind, GroupKind.TRIPLET)
        self.assertEqual(group.tile_type, _tile_type("5z"))
        self.assertTrue(group.is_open)
        self.assertTrue(group.is_terminal_or_honor)
        self.assertFalse(group.is_concealed_for_scoring)

    def test_analyzes_daiminkan_as_open_quad(self) -> None:
        pool = _TilePool()
        kan_tiles = pool.take("9p", "9p", "9p", "9p")
        daiminkan = Daiminkan(kan_tiles[0], kan_tiles[1:], Seat.SOUTH)
        context = _ryanmen_context_with_meld(pool, daiminkan)

        analysis = _analyze_sole_interpretation(context)
        group = analysis.groups[-1]

        self.assertIs(group.kind, GroupKind.QUAD)
        self.assertEqual(group.tile_type, _tile_type("9p"))
        self.assertTrue(group.is_open)
        self.assertTrue(group.is_terminal_or_honor)
        self.assertFalse(group.is_concealed_for_scoring)

    def test_analyzes_kakan_as_open_quad(self) -> None:
        pool = _TilePool()
        kan_tiles = pool.take("4m", "4m", "4m", "4m")
        pon = Pon(kan_tiles[0], kan_tiles[1:3], Seat.WEST)
        kakan = Kakan(pon, kan_tiles[3])
        context = _ryanmen_context_with_meld(pool, kakan)

        analysis = _analyze_sole_interpretation(context)
        group = analysis.groups[-1]

        self.assertIs(group.kind, GroupKind.QUAD)
        self.assertEqual(group.tile_type, _tile_type("4m"))
        self.assertTrue(group.is_open)
        self.assertFalse(group.is_terminal_or_honor)
        self.assertFalse(group.is_concealed_for_scoring)

    def test_analyzes_ankan_as_concealed_quad(self) -> None:
        pool = _TilePool()
        ankan = Ankan(pool.take("1z", "1z", "1z", "1z"))
        context = _ryanmen_context_with_meld(pool, ankan)

        analysis = _analyze_sole_interpretation(context)
        group = analysis.groups[-1]

        self.assertIs(group.kind, GroupKind.QUAD)
        self.assertEqual(group.tile_type, _tile_type("1z"))
        self.assertFalse(group.is_open)
        self.assertTrue(group.is_terminal_or_honor)
        self.assertTrue(group.is_concealed_for_scoring)
        self.assertTrue(context.is_menzen)


class PairAnalysisTest(unittest.TestCase):
    def test_analyzes_dragon_pair(self) -> None:
        context = _pair_context(
            "5z",
            seat_wind=Wind.SOUTH,
            prevailing_wind=Wind.EAST,
        )

        pair = _analyze_sole_interpretation(context).pair

        self.assertEqual(pair.tile_type, _tile_type("5z"))
        self.assertTrue(pair.is_dragon)
        self.assertFalse(pair.is_seat_wind)
        self.assertFalse(pair.is_prevailing_wind)
        self.assertFalse(pair.is_double_wind)
        self.assertTrue(pair.is_value_pair)

    def test_analyzes_seat_wind_pair(self) -> None:
        context = _pair_context(
            "2z",
            seat_wind=Wind.SOUTH,
            prevailing_wind=Wind.EAST,
        )

        pair = _analyze_sole_interpretation(context).pair

        self.assertFalse(pair.is_dragon)
        self.assertTrue(pair.is_seat_wind)
        self.assertFalse(pair.is_prevailing_wind)
        self.assertFalse(pair.is_double_wind)
        self.assertTrue(pair.is_value_pair)

    def test_analyzes_prevailing_wind_pair(self) -> None:
        context = _pair_context(
            "1z",
            seat_wind=Wind.SOUTH,
            prevailing_wind=Wind.EAST,
        )

        pair = _analyze_sole_interpretation(context).pair

        self.assertFalse(pair.is_seat_wind)
        self.assertTrue(pair.is_prevailing_wind)
        self.assertFalse(pair.is_double_wind)
        self.assertTrue(pair.is_value_pair)

    def test_analyzes_double_wind_pair(self) -> None:
        context = _pair_context(
            "1z",
            seat_wind=Wind.EAST,
            prevailing_wind=Wind.EAST,
        )

        pair = _analyze_sole_interpretation(context).pair

        self.assertTrue(pair.is_seat_wind)
        self.assertTrue(pair.is_prevailing_wind)
        self.assertTrue(pair.is_double_wind)
        self.assertTrue(pair.is_value_pair)

    def test_analyzes_pair_without_value(self) -> None:
        context = _pair_context(
            "3z",
            seat_wind=Wind.SOUTH,
            prevailing_wind=Wind.EAST,
        )

        pair = _analyze_sole_interpretation(context).pair

        self.assertFalse(pair.is_dragon)
        self.assertFalse(pair.is_seat_wind)
        self.assertFalse(pair.is_prevailing_wind)
        self.assertFalse(pair.is_double_wind)
        self.assertFalse(pair.is_value_pair)


class WaitTypeAnalysisTest(unittest.TestCase):
    def test_carries_over_the_interpretation_wait_type(self) -> None:
        pool = _TilePool()
        concealed_tiles = pool.take(
            "1m",
            "2m",
            "3m",
            "4p",
            "5p",
            "6p",
            "7s",
            "8s",
            "9s",
            "1z",
            "1z",
            "1z",
            "2z",
            "2z",
        )
        ryanmen_context = _context(
            concealed_tiles,
            winning_tile=concealed_tiles[0],
        )
        tanki_context = _context(concealed_tiles)

        self.assertIs(
            _analyze_sole_interpretation(ryanmen_context).wait_type,
            WaitType.RYANMEN,
        )
        self.assertIs(
            _analyze_sole_interpretation(tanki_context).wait_type,
            WaitType.TANKI,
        )

    def test_carries_over_the_shanpon_wait_type(self) -> None:
        analysis = _analyze_sole_interpretation(_shanpon_context())

        self.assertIs(analysis.wait_type, WaitType.SHANPON)


class MultipleInterpretationAnalysisTest(unittest.TestCase):
    def test_analyzes_every_interpretation_independently(self) -> None:
        pool = _TilePool()
        concealed_tiles = pool.take(
            "1m",
            "1m",
            "1m",
            "2m",
            "2m",
            "3m",
            "3m",
            "3m",
            "4m",
            "4m",
            "4m",
            "5m",
            "5m",
            "2m",
        )
        context = _context(concealed_tiles)

        interpretations = _interpretations(context)
        analyses = tuple(
            analyze_winning_interpretation(context, interpretation)
            for interpretation in interpretations
        )

        self.assertGreater(len(interpretations), 1)
        self.assertEqual(
            {analysis.wait_type for analysis in analyses},
            frozenset(
                {
                    WaitType.RYANMEN,
                    WaitType.KANCHAN,
                    WaitType.SHANPON,
                    WaitType.TANKI,
                }
            ),
        )
        for analysis in analyses:
            with self.subTest(wait_type=analysis.wait_type):
                self.assertEqual(len(analysis.groups), 4)
                self.assertLessEqual(
                    sum(group.is_completed_by_ron for group in analysis.groups),
                    1,
                )
                self.assertFalse(any(group.is_open for group in analysis.groups))

    def test_marks_ron_completed_triplet_only_in_the_shanpon_interpretation(
        self,
    ) -> None:
        pool = _TilePool()
        concealed_tiles = pool.take(
            "1m",
            "1m",
            "1m",
            "2m",
            "2m",
            "3m",
            "3m",
            "3m",
            "4m",
            "4m",
            "4m",
            "5m",
            "5m",
            "2m",
        )
        context = _context(concealed_tiles)

        analyses = {
            analysis.wait_type: analysis
            for analysis in (
                analyze_winning_interpretation(context, interpretation)
                for interpretation in _interpretations(context)
            )
        }

        shanpon_groups = analyses[WaitType.SHANPON].groups
        ryanmen_groups = analyses[WaitType.RYANMEN].groups

        self.assertTrue(any(group.is_completed_by_ron for group in shanpon_groups))
        self.assertFalse(any(group.is_completed_by_ron for group in ryanmen_groups))


class AnalyzeWinningInterpretationValidationTest(unittest.TestCase):
    def test_rejects_invalid_argument_types(self) -> None:
        pool = _TilePool()
        concealed_tiles = pool.take(
            "1m",
            "2m",
            "3m",
            "4p",
            "5p",
            "6p",
            "7s",
            "8s",
            "9s",
            "1z",
            "1z",
            "1z",
            "2z",
            "2z",
        )
        context = _context(concealed_tiles)
        interpretation = next(iter(_interpretations(context)))

        with self.assertRaises(TypeError):
            analyze_winning_interpretation("context", interpretation)
        with self.assertRaises(TypeError):
            analyze_winning_interpretation(context, interpretation.decomposition)

    def test_rejects_interpretation_with_a_different_winning_tile_type(self) -> None:
        pool = _TilePool()
        concealed_tiles = pool.take(
            "1m",
            "2m",
            "3m",
            "4p",
            "5p",
            "6p",
            "7s",
            "8s",
            "9s",
            "1z",
            "1z",
            "1z",
            "2z",
            "2z",
        )
        tanki_context = _context(concealed_tiles)
        ryanmen_context = _context(
            concealed_tiles,
            winning_tile=concealed_tiles[0],
        )
        ryanmen_interpretation = next(iter(_interpretations(ryanmen_context)))

        with self.assertRaises(ValueError):
            analyze_winning_interpretation(
                tanki_context,
                ryanmen_interpretation,
            )

    def test_rejects_interpretation_with_different_declared_melds(self) -> None:
        pool = _TilePool()
        pon_tiles = pool.take("5z", "5z", "5z")
        pon = Pon(pon_tiles[0], pon_tiles[1:], Seat.WEST)
        open_context = _ryanmen_context_with_meld(pool, pon)
        open_interpretation = next(iter(_interpretations(open_context)))

        concealed_context = _context(
            (*open_context.concealed_tiles, *pon.tiles),
            winning_tile=open_context.winning_tile,
        )

        with self.assertRaises(ValueError):
            analyze_winning_interpretation(
                concealed_context,
                open_interpretation,
            )


class GroupAnalysisValidationTest(unittest.TestCase):
    def test_rejects_invalid_field_types(self) -> None:
        invalid_values = (
            {"kind": "triplet"},
            {"tile_type": "1z"},
            {"is_open": 1},
            {"is_terminal_or_honor": None},
            {"is_completed_by_ron": 0},
        )

        for overrides in invalid_values:
            values = {
                "kind": GroupKind.TRIPLET,
                "tile_type": _tile_type("1z"),
                "is_open": False,
                "is_terminal_or_honor": True,
                **overrides,
            }
            with self.subTest(overrides=overrides), self.assertRaises(TypeError):
                GroupAnalysis(**values)

    def test_rejects_non_triplet_completed_by_ron(self) -> None:
        with self.assertRaises(ValueError):
            GroupAnalysis(
                kind=GroupKind.SEQUENCE,
                tile_type=_tile_type("1m"),
                is_open=False,
                is_terminal_or_honor=False,
                is_completed_by_ron=True,
            )

    def test_rejects_open_group_completed_by_ron(self) -> None:
        with self.assertRaises(ValueError):
            GroupAnalysis(
                kind=GroupKind.TRIPLET,
                tile_type=_tile_type("1z"),
                is_open=True,
                is_terminal_or_honor=True,
                is_completed_by_ron=True,
            )


class SequenceGroupAnalysisTileTypeTest(unittest.TestCase):
    def test_uses_the_sequence_start_tile_type(self) -> None:
        pool = _TilePool()
        concealed_tiles = pool.take(
            "1m",
            "2m",
            "3m",
            "4p",
            "5p",
            "6p",
            "7s",
            "8s",
            "9s",
            "1z",
            "1z",
            "1z",
            "2z",
            "2z",
        )
        context = _context(concealed_tiles, winning_tile=concealed_tiles[0])

        analysis = _analyze_sole_interpretation(context)
        sequence_tile_types = {
            group.tile_type
            for group in analysis.groups
            if group.kind is GroupKind.SEQUENCE
        }

        self.assertEqual(
            sequence_tile_types,
            {
                _tile_type("1m"),
                _tile_type("4p"),
                _tile_type("7s"),
            },
        )


if __name__ == "__main__":
    unittest.main()
