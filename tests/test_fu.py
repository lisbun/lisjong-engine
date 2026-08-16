import unittest
from dataclasses import replace

from lisjong_engine.fu import (
    FuCalculation,
    FuComponent,
    FuReason,
    calculate_fu,
    calculate_seven_pairs_fu,
    enumerate_fu_components,
    fu_component_for_group,
    fu_component_for_wait,
    round_fu,
)
from lisjong_engine.interpretation_analysis import GroupAnalysis, GroupKind
from lisjong_engine.meld import Ankan, Chi, Daiminkan, Kakan, Meld, Pon
from lisjong_engine.rules import RuleSet
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

_TWO_FU_DOUBLE_WIND_RULES = replace(RuleSet.default(), double_wind_pair_fu=2)


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


def _chi(pool: _TilePool, *names: str) -> Chi:
    tiles = pool.take(*names)
    return Chi(tiles[0], tiles[1:], Seat.NORTH)


def _pon(pool: _TilePool, name: str) -> Pon:
    tiles = pool.take(name, name, name)
    return Pon(tiles[0], tiles[1:], Seat.NORTH)


def _ankan(pool: _TilePool, name: str) -> Ankan:
    return Ankan(pool.take(name, name, name, name))


def _daiminkan(pool: _TilePool, name: str) -> Daiminkan:
    tiles = pool.take(name, name, name, name)
    return Daiminkan(tiles[0], tiles[1:], Seat.NORTH)


def _kakan(pool: _TilePool, name: str) -> Kakan:
    tiles = pool.take(name, name, name, name)
    return Kakan(Pon(tiles[0], tiles[1:3], Seat.NORTH), tiles[3])


def _context(
    concealed_names: tuple[str, ...],
    *,
    pool: _TilePool | None = None,
    declared_melds: tuple[Meld, ...] = (),
    method: WinMethod = WinMethod.RON,
    seat_wind: Wind = Wind.SOUTH,
    prevailing_wind: Wind = Wind.EAST,
) -> WinningContext:
    tile_pool = _TilePool() if pool is None else pool
    concealed_tiles = tile_pool.take(*concealed_names)
    return WinningContext(
        concealed_tiles=concealed_tiles,
        winning_tile=concealed_tiles[-1],
        method=method,
        origin=(WinOrigin.DISCARD if method is WinMethod.RON else WinOrigin.LIVE_WALL),
        seat_wind=seat_wind,
        prevailing_wind=prevailing_wind,
        declared_melds=declared_melds,
    )


def _interpretation(context: WinningContext) -> StandardWinningInterpretation:
    interpretations = find_standard_winning_interpretations(
        context.concealed_tiles,
        context.winning_tile,
        context.declared_melds,
    )
    if not interpretations:
        raise AssertionError("expected a standard winning interpretation")
    return next(iter(interpretations))


def _components(
    context: WinningContext,
    rules: RuleSet | None = None,
) -> tuple[FuComponent, ...]:
    return enumerate_fu_components(context, _interpretation(context), rules)


def _calculation(
    context: WinningContext,
    rules: RuleSet | None = None,
) -> FuCalculation:
    return calculate_fu(context, _interpretation(context), rules)


def _wind_pair_context(seat_wind: Wind, prevailing_wind: Wind) -> WinningContext:
    return _context(
        (
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
        ),
        seat_wind=seat_wind,
        prevailing_wind=prevailing_wind,
    )


def _open_sequence_context(method: WinMethod) -> WinningContext:
    pool = _TilePool()
    chi = _chi(pool, "1m", "2m", "3m")
    return _context(
        (
            "4m",
            "5m",
            "2p",
            "3p",
            "4p",
            "6s",
            "7s",
            "8s",
            "5p",
            "5p",
            "6m",
        ),
        pool=pool,
        declared_melds=(chi,),
        method=method,
    )


def _pinfu_tsumo_context() -> WinningContext:
    return _context(
        (
            "1m",
            "2m",
            "3m",
            "4m",
            "5m",
            "2p",
            "3p",
            "4p",
            "6s",
            "7s",
            "8s",
            "5p",
            "5p",
            "6m",
        ),
        method=WinMethod.TSUMO,
    )


class FuModelTest(unittest.TestCase):
    def test_fu_component_requires_positive_fu(self) -> None:
        with self.assertRaises(ValueError):
            FuComponent(FuReason.BASE, 0)

    def test_twenty_five_fu_component_is_reserved_for_seven_pairs(self) -> None:
        with self.assertRaises(ValueError):
            FuComponent(FuReason.BASE, 25)
        with self.assertRaises(ValueError):
            FuComponent(FuReason.SEVEN_PAIRS, 20)

    def test_fu_calculation_derives_raw_fu_from_copied_components(self) -> None:
        components = [
            FuComponent(FuReason.BASE, 20),
            FuComponent(FuReason.TSUMO, 2),
        ]
        calculation = FuCalculation(components, rounded_fu=30)
        components.clear()

        self.assertEqual(
            calculation.components,
            (
                FuComponent(FuReason.BASE, 20),
                FuComponent(FuReason.TSUMO, 2),
            ),
        )
        self.assertEqual(calculation.raw_fu, 22)
        self.assertEqual(calculation.rounded_fu, 30)

    def test_fu_calculation_rejects_invalid_results(self) -> None:
        base = FuComponent(FuReason.BASE, 20)
        seven_pairs = FuComponent(FuReason.SEVEN_PAIRS, 25)
        invalid_cases = (
            (((), 30), ValueError),
            ((("component",), 30), TypeError),
            (((base, FuComponent(FuReason.CLOSED_SIMPLE_QUAD, 32)), 50), ValueError),
            (((base,), 25), ValueError),
            (((seven_pairs,), 30), ValueError),
        )
        for arguments, exception_type in invalid_cases:
            with self.subTest(arguments=arguments), self.assertRaises(exception_type):
                FuCalculation(*arguments)


class SevenPairsFuCalculationTest(unittest.TestCase):
    def test_seven_pairs_is_fixed_at_twenty_five_fu_without_rounding(self) -> None:
        names = (
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
        for method in (WinMethod.RON, WinMethod.TSUMO):
            with self.subTest(method=method):
                calculation = calculate_seven_pairs_fu(_context(names, method=method))
                self.assertEqual(
                    calculation.components,
                    (FuComponent(FuReason.SEVEN_PAIRS, 25),),
                )
                self.assertEqual(calculation.raw_fu, 25)
                self.assertEqual(calculation.rounded_fu, 25)

    def test_rejects_non_seven_pairs_shape(self) -> None:
        context = _context(
            (
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
                "5z",
                "5z",
            )
        )

        with self.assertRaises(ValueError):
            calculate_seven_pairs_fu(context)

    def test_rejects_four_identical_tiles_as_two_pairs(self) -> None:
        context = _context(
            (
                "1m",
                "1m",
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
                "6z",
                "6z",
            )
        )

        with self.assertRaises(ValueError):
            calculate_seven_pairs_fu(context)

    def test_rejects_non_context(self) -> None:
        with self.assertRaises(TypeError):
            calculate_seven_pairs_fu(())


class FuRoundingTest(unittest.TestCase):
    def test_rounds_normal_fu_at_required_boundaries(self) -> None:
        cases = (
            (20, 30),
            (22, 30),
            (25, 30),
            (30, 30),
            (32, 40),
            (34, 40),
            (40, 40),
        )
        for raw_fu, expected in cases:
            with self.subTest(raw_fu=raw_fu):
                self.assertEqual(round_fu(raw_fu), expected)

    def test_pinfu_tsumo_remains_twenty_fu(self) -> None:
        self.assertEqual(round_fu(20, is_pinfu_tsumo=True), 20)

    def test_rejects_invalid_rounding_inputs(self) -> None:
        with self.assertRaises(ValueError):
            round_fu(22, is_pinfu_tsumo=True)
        with self.assertRaises(TypeError):
            round_fu(20, is_pinfu_tsumo=1)
        with self.assertRaises(ValueError):
            round_fu(0)


class FuInputValidationTest(unittest.TestCase):
    def test_rejects_invalid_arguments(self) -> None:
        context = _pinfu_tsumo_context()
        interpretation = _interpretation(context)
        invalid_calls = (
            ((), interpretation, None),
            (context, (), None),
            (context, interpretation, "project-standard-v1"),
        )
        for arguments in invalid_calls:
            with self.subTest(arguments=arguments), self.assertRaises(TypeError):
                calculate_fu(*arguments)
            with self.subTest(arguments=arguments), self.assertRaises(TypeError):
                enumerate_fu_components(*arguments)

    def test_omitted_rules_use_the_default_rule_set(self) -> None:
        context = _wind_pair_context(Wind.EAST, Wind.EAST)

        self.assertEqual(
            _calculation(context),
            _calculation(context, RuleSet.default()),
        )


class FinalFuCalculationTest(unittest.TestCase):
    def test_pinfu_tsumo_is_twenty_fu(self) -> None:
        calculation = _calculation(_pinfu_tsumo_context())

        self.assertEqual(calculation.raw_fu, 20)
        self.assertEqual(calculation.rounded_fu, 20)

    def test_open_pinfu_shape_is_rounded_from_twenty_to_thirty_fu(self) -> None:
        calculation = _calculation(_open_sequence_context(WinMethod.RON))

        self.assertEqual(calculation.raw_fu, 20)
        self.assertEqual(calculation.rounded_fu, 30)

    def test_open_sequence_tsumo_is_rounded_after_adding_tsumo_fu(self) -> None:
        calculation = _calculation(_open_sequence_context(WinMethod.TSUMO))

        self.assertEqual(calculation.raw_fu, 22)
        self.assertEqual(calculation.rounded_fu, 30)


class BasicFuComponentTest(unittest.TestCase):
    def test_pinfu_tsumo_has_only_base_fu(self) -> None:
        self.assertEqual(
            _components(_pinfu_tsumo_context()),
            (FuComponent(FuReason.BASE, 20),),
        )

    def test_open_ron_has_only_base_fu_for_non_value_pair(self) -> None:
        pool = _TilePool()
        chi = _chi(pool, "1m", "2m", "3m")
        context = _context(
            (
                "4m",
                "5m",
                "2p",
                "3p",
                "4p",
                "6s",
                "7s",
                "8s",
                "5p",
                "5p",
                "6m",
            ),
            pool=pool,
            declared_melds=(chi,),
        )

        self.assertEqual(_components(context), (FuComponent(FuReason.BASE, 20),))

    def test_menzen_ron_adds_ten_fu(self) -> None:
        context = _context(
            (
                "1m",
                "2m",
                "3m",
                "4m",
                "5m",
                "2p",
                "3p",
                "4p",
                "6s",
                "7s",
                "8s",
                "5p",
                "5p",
                "6m",
            )
        )

        self.assertEqual(
            _components(context),
            (
                FuComponent(FuReason.BASE, 20),
                FuComponent(FuReason.MENZEN_RON, 10),
            ),
        )

    def test_tsumo_adds_two_fu(self) -> None:
        context = _context(
            (
                "1m",
                "2m",
                "3m",
                "4m",
                "4m",
                "4m",
                "2p",
                "3p",
                "4p",
                "6s",
                "7s",
                "8s",
                "5p",
                "5p",
            ),
            method=WinMethod.TSUMO,
        )

        components = _components(context)

        self.assertIn(FuComponent(FuReason.TSUMO, 2), components)
        self.assertIn(FuComponent(FuReason.CLOSED_SIMPLE_TRIPLET, 4), components)

    def test_dragon_pair_adds_two_fu(self) -> None:
        context = _context(
            (
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
                "5z",
                "5z",
            )
        )

        self.assertIn(FuComponent(FuReason.DRAGON_PAIR, 2), _components(context))

    def test_seat_wind_pair_adds_two_fu(self) -> None:
        context = _wind_pair_context(Wind.EAST, Wind.SOUTH)

        self.assertIn(FuComponent(FuReason.SEAT_WIND_PAIR, 2), _components(context))

    def test_prevailing_wind_pair_adds_two_fu(self) -> None:
        context = _wind_pair_context(Wind.SOUTH, Wind.EAST)

        self.assertIn(
            FuComponent(FuReason.PREVAILING_WIND_PAIR, 2),
            _components(context),
        )

    def test_double_wind_pair_uses_default_four_fu(self) -> None:
        context = _wind_pair_context(Wind.EAST, Wind.EAST)

        self.assertIn(
            FuComponent(FuReason.DOUBLE_WIND_PAIR, 4),
            _components(context),
        )

    def test_double_wind_pair_can_use_two_fu(self) -> None:
        context = _wind_pair_context(Wind.EAST, Wind.EAST)

        self.assertIn(
            FuComponent(FuReason.DOUBLE_WIND_PAIR, 2),
            _components(context, _TWO_FU_DOUBLE_WIND_RULES),
        )


class DeclaredMeldFuIntegrationTest(unittest.TestCase):
    def test_pon_ankan_daiminkan_and_kakan_are_analyzed(self) -> None:
        cases = (
            (_pon, "5m", FuReason.OPEN_SIMPLE_TRIPLET, 2),
            (_ankan, "1m", FuReason.CLOSED_TERMINAL_OR_HONOR_QUAD, 32),
            (_daiminkan, "1m", FuReason.OPEN_TERMINAL_OR_HONOR_QUAD, 16),
            (_kakan, "5m", FuReason.OPEN_SIMPLE_QUAD, 8),
        )
        for meld_factory, tile_name, reason, fu in cases:
            with self.subTest(reason=reason):
                pool = _TilePool()
                meld = meld_factory(pool, tile_name)
                context = _context(
                    (
                        "1p",
                        "2p",
                        "4p",
                        "5p",
                        "6p",
                        "7s",
                        "8s",
                        "9s",
                        "2z",
                        "2z",
                        "3p",
                    ),
                    pool=pool,
                    declared_melds=(meld,),
                )

                self.assertIn(FuComponent(reason, fu), _components(context))


class ShanponCompletionFuIntegrationTest(unittest.TestCase):
    def test_ron_opens_only_completed_triplet_but_tsumo_does_not(self) -> None:
        names = (
            "2m",
            "2m",
            "5p",
            "5p",
            "5p",
            "1s",
            "2s",
            "3s",
            "6s",
            "7s",
            "8s",
            "4z",
            "4z",
            "2m",
        )
        ron_components = _components(_context(names))
        tsumo_components = _components(_context(names, method=WinMethod.TSUMO))

        self.assertIn(FuComponent(FuReason.OPEN_SIMPLE_TRIPLET, 2), ron_components)
        self.assertEqual(
            ron_components.count(FuComponent(FuReason.CLOSED_SIMPLE_TRIPLET, 4)),
            1,
        )
        self.assertNotIn(FuComponent(FuReason.OPEN_SIMPLE_TRIPLET, 2), tsumo_components)
        self.assertEqual(
            tsumo_components.count(FuComponent(FuReason.CLOSED_SIMPLE_TRIPLET, 4)),
            2,
        )


class GroupFuComponentTest(unittest.TestCase):
    def test_sequence_has_no_group_fu(self) -> None:
        group = GroupAnalysis(GroupKind.SEQUENCE, _tile_type("1m"), False, False)

        self.assertIsNone(fu_component_for_group(group))

    def test_rejects_non_group_analysis(self) -> None:
        with self.assertRaises(TypeError):
            fu_component_for_group("triplet")

    def test_unknown_group_kind_raises_value_error(self) -> None:
        group = GroupAnalysis(GroupKind.SEQUENCE, _tile_type("1m"), False, False)
        object.__setattr__(group, "kind", "unknown")

        with self.assertRaises(ValueError):
            fu_component_for_group(group)

    def test_triplet_fu_patterns(self) -> None:
        simple = _tile_type("5m")
        terminal = _tile_type("1m")
        cases = (
            (
                GroupAnalysis(GroupKind.TRIPLET, simple, True, False),
                FuReason.OPEN_SIMPLE_TRIPLET,
                2,
            ),
            (
                GroupAnalysis(GroupKind.TRIPLET, terminal, True, True),
                FuReason.OPEN_TERMINAL_OR_HONOR_TRIPLET,
                4,
            ),
            (
                GroupAnalysis(GroupKind.TRIPLET, simple, False, False),
                FuReason.CLOSED_SIMPLE_TRIPLET,
                4,
            ),
            (
                GroupAnalysis(GroupKind.TRIPLET, terminal, False, True),
                FuReason.CLOSED_TERMINAL_OR_HONOR_TRIPLET,
                8,
            ),
        )
        for group, reason, fu in cases:
            with self.subTest(reason=reason):
                self.assertEqual(
                    fu_component_for_group(group),
                    FuComponent(reason, fu),
                )

    def test_quad_fu_patterns(self) -> None:
        simple = _tile_type("5m")
        honor = _tile_type("5z")
        cases = (
            (
                GroupAnalysis(GroupKind.QUAD, simple, True, False),
                FuReason.OPEN_SIMPLE_QUAD,
                8,
            ),
            (
                GroupAnalysis(GroupKind.QUAD, honor, True, True),
                FuReason.OPEN_TERMINAL_OR_HONOR_QUAD,
                16,
            ),
            (
                GroupAnalysis(GroupKind.QUAD, simple, False, False),
                FuReason.CLOSED_SIMPLE_QUAD,
                16,
            ),
            (
                GroupAnalysis(GroupKind.QUAD, honor, False, True),
                FuReason.CLOSED_TERMINAL_OR_HONOR_QUAD,
                32,
            ),
        )
        for group, reason, fu in cases:
            with self.subTest(reason=reason):
                self.assertEqual(
                    fu_component_for_group(group),
                    FuComponent(reason, fu),
                )

    def test_ron_completed_triplet_is_open_for_scoring(self) -> None:
        group = GroupAnalysis(
            GroupKind.TRIPLET,
            _tile_type("5m"),
            is_open=False,
            is_terminal_or_honor=False,
            is_completed_by_ron=True,
        )

        self.assertEqual(
            fu_component_for_group(group),
            FuComponent(FuReason.OPEN_SIMPLE_TRIPLET, 2),
        )


class WaitFuComponentTest(unittest.TestCase):
    def test_two_fu_waits(self) -> None:
        cases = (
            (WaitType.KANCHAN, FuReason.KANCHAN_WAIT),
            (WaitType.PENCHAN, FuReason.PENCHAN_WAIT),
            (WaitType.TANKI, FuReason.TANKI_WAIT),
        )
        for wait_type, reason in cases:
            with self.subTest(wait_type=wait_type):
                self.assertEqual(
                    fu_component_for_wait(wait_type),
                    FuComponent(reason, 2),
                )

    def test_ryanmen_and_shanpon_have_no_wait_fu(self) -> None:
        self.assertIsNone(fu_component_for_wait(WaitType.RYANMEN))
        self.assertIsNone(fu_component_for_wait(WaitType.SHANPON))

    def test_rejects_non_wait_type(self) -> None:
        with self.assertRaises(TypeError):
            fu_component_for_wait("ryanmen")


if __name__ == "__main__":
    unittest.main()
