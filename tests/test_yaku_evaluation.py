import unittest
from dataclasses import replace

from lisjong_engine.meld import Ankan, Chi, Daiminkan, Kakan, Pon
from lisjong_engine.rules import RuleSet
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
from lisjong_engine.yaku import Yaku
from lisjong_engine.yaku_evaluation import (
    YAKU_DEFINITIONS,
    YakuDefinition,
    YakuEvaluation,
    YakuMatch,
    evaluate_yaku,
)

_CATEGORIES = {
    "m": TileCategory.MANZU,
    "p": TileCategory.PINZU,
    "s": TileCategory.SOUZU,
    "z": TileCategory.HONOR,
}

# 旧`python-study`のプリセット差分は、単一`RuleSet`のfield差分として表現する。
_DOUBLE_YAKUMAN_RULES = replace(
    RuleSet.default(),
    double_yakuman_variants=frozenset(
        {
            Yaku.SUUANKOU_TANKI,
            Yaku.KOKUSHI_MUSOU_13_WAIT,
            Yaku.DAISUUSHII,
            Yaku.JUNSEI_CHUUREN_POUTOU,
        }
    ),
)


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
    return Pon(tiles[0], tiles[1:], Seat.WEST)


def _ankan(pool: _TilePool, name: str) -> Ankan:
    return Ankan(pool.take(name, name, name, name))


def _daiminkan(pool: _TilePool, name: str) -> Daiminkan:
    tiles = pool.take(name, name, name, name)
    return Daiminkan(tiles[0], tiles[1:], Seat.SOUTH)


def _kakan(pool: _TilePool, name: str) -> Kakan:
    tiles = pool.take(name, name, name, name)
    return Kakan(Pon(tiles[0], tiles[1:3], Seat.EAST), tiles[3])


def _context(
    concealed_names: tuple[str, ...],
    *,
    pool: _TilePool | None = None,
    declared_melds: tuple[object, ...] = (),
    method: WinMethod = WinMethod.RON,
    origin: WinOrigin | None = None,
    seat_wind: Wind = Wind.SOUTH,
    prevailing_wind: Wind = Wind.EAST,
    riichi_status: RiichiStatus = RiichiStatus.NONE,
    is_ippatsu: bool = False,
    is_last_tile: bool = False,
    is_first_uninterrupted_turn: bool = False,
) -> WinningContext:
    tile_pool = _TilePool() if pool is None else pool
    concealed_tiles = tile_pool.take(*concealed_names)
    default_origin = (
        WinOrigin.DISCARD if method is WinMethod.RON else WinOrigin.LIVE_WALL
    )
    return WinningContext(
        concealed_tiles=concealed_tiles,
        winning_tile=concealed_tiles[-1],
        method=method,
        origin=default_origin if origin is None else origin,
        seat_wind=seat_wind,
        prevailing_wind=prevailing_wind,
        declared_melds=declared_melds,
        riichi_status=riichi_status,
        is_ippatsu=is_ippatsu,
        is_last_tile=is_last_tile,
        is_first_uninterrupted_turn=is_first_uninterrupted_turn,
    )


def _all_yakus(evaluations: frozenset[YakuEvaluation]) -> frozenset[Yaku]:
    return frozenset(yaku for evaluation in evaluations for yaku in evaluation.yakus)


def _han_values(
    evaluations: frozenset[YakuEvaluation],
    yaku: Yaku,
) -> frozenset[int]:
    return frozenset(
        match.han
        for evaluation in evaluations
        for match in evaluation.matches
        if match.yaku is yaku
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


class YakuModelTest(unittest.TestCase):
    def test_definitions_cover_every_yaku(self) -> None:
        self.assertEqual(set(YAKU_DEFINITIONS), set(Yaku))

    def test_inventory_has_normal_and_yakuman_roles(self) -> None:
        normal_yaku = {
            Yaku.MENZEN_TSUMO,
            Yaku.RIICHI,
            Yaku.IPPATSU,
            Yaku.DOUBLE_RIICHI,
            Yaku.CHANKAN,
            Yaku.RINSHAN_KAIHOU,
            Yaku.HAITEI,
            Yaku.HOUTEI,
            Yaku.TANYAO,
            Yaku.SEAT_WIND,
            Yaku.PREVAILING_WIND,
            Yaku.WHITE_DRAGON,
            Yaku.GREEN_DRAGON,
            Yaku.RED_DRAGON,
            Yaku.PINFU,
            Yaku.IIPEIKOU,
            Yaku.CHANTA,
            Yaku.ITTSUU,
            Yaku.SANSHOKU_DOUJUN,
            Yaku.SANSHOKU_DOUKOU,
            Yaku.SANKANTSU,
            Yaku.TOITOI,
            Yaku.SANANKOU,
            Yaku.SHOUSANGEN,
            Yaku.HONROUTOU,
            Yaku.CHIITOITSU,
            Yaku.JUNCHAN,
            Yaku.HONITSU,
            Yaku.RYANPEIKOU,
            Yaku.CHINITSU,
        }
        yakuman = {
            Yaku.TENHOU,
            Yaku.CHIIHOU,
            Yaku.DAISANGEN,
            Yaku.SUUANKOU,
            Yaku.SUUANKOU_TANKI,
            Yaku.TSUUIISOU,
            Yaku.RYUUIISOU,
            Yaku.CHINROUTOU,
            Yaku.KOKUSHI_MUSOU,
            Yaku.KOKUSHI_MUSOU_13_WAIT,
            Yaku.DAISUUSHII,
            Yaku.SHOUSUUSHII,
            Yaku.SUUKANTSU,
            Yaku.CHUUREN_POUTOU,
            Yaku.JUNSEI_CHUUREN_POUTOU,
        }

        self.assertEqual(normal_yaku | yakuman, set(Yaku))
        self.assertEqual(
            {
                yaku
                for yaku, definition in YAKU_DEFINITIONS.items()
                if definition.is_yakuman
            },
            yakuman,
        )

    def test_definition_rejects_inconsistent_values(self) -> None:
        invalid_cases = (
            (("", 1, None, False), ValueError),
            ((None, 1, None, False), TypeError),
            (("断么九", 0, None, False), ValueError),
            (("断么九", 1, None, 1), TypeError),
            (("大三元", 1, None, True), ValueError),
        )
        for arguments, error in invalid_cases:
            with self.subTest(arguments=arguments), self.assertRaises(error):
                YakuDefinition(*arguments)

    def test_yaku_match_requires_exactly_one_value_kind(self) -> None:
        with self.assertRaises(ValueError):
            YakuMatch(Yaku.TANYAO)
        with self.assertRaises(ValueError):
            YakuMatch(Yaku.TANYAO, han=1, yakuman_units=1)
        with self.assertRaises(ValueError):
            YakuMatch(Yaku.TANYAO, yakuman_units=1)
        with self.assertRaises(ValueError):
            YakuMatch(Yaku.DAISANGEN, han=1)

        self.assertEqual(YakuMatch(Yaku.TANYAO, han=1).japanese_name, "断么九")

    def test_evaluation_rejects_inconsistent_matches(self) -> None:
        tanyao = YakuMatch(Yaku.TANYAO, han=1)
        daisangen = YakuMatch(Yaku.DAISANGEN, yakuman_units=1)
        invalid_cases = (
            ((WinningShape.SEVEN_PAIRS, WaitType.TANKI, ()), ValueError),
            (
                (WinningShape.SEVEN_PAIRS, WaitType.TANKI, (tanyao, tanyao)),
                ValueError,
            ),
            (
                (WinningShape.SEVEN_PAIRS, WaitType.TANKI, (tanyao, daisangen)),
                ValueError,
            ),
            ((WinningShape.SEVEN_PAIRS, WaitType.TANKI, ("tanyao",)), TypeError),
            ((WinningShape.STANDARD, WaitType.TANKI, (tanyao,)), TypeError),
        )
        for arguments, error in invalid_cases:
            with self.subTest(arguments=arguments), self.assertRaises(error):
                YakuEvaluation(*arguments)

    def test_rejects_invalid_inputs(self) -> None:
        with self.assertRaises(TypeError):
            evaluate_yaku(())
        context = _context(
            (
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
        )
        with self.assertRaises(TypeError):
            evaluate_yaku(context, "project-standard-v1")

    def test_omitted_rules_use_the_default_rule_set(self) -> None:
        context = _context(
            (
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
        )

        self.assertEqual(
            evaluate_yaku(context),
            evaluate_yaku(context, RuleSet.default()),
        )
        self.assertEqual(
            _yakuman_units(evaluate_yaku(context), Yaku.SUUANKOU_TANKI),
            frozenset({1}),
        )


class BasicYakuTest(unittest.TestCase):
    def test_tanyao_is_one_han_closed_and_open(self) -> None:
        closed = _context(
            (
                "2m",
                "3m",
                "4m",
                "3p",
                "4p",
                "5p",
                "4s",
                "5s",
                "6s",
                "6s",
                "7s",
                "8s",
                "2p",
                "2p",
            )
        )
        pool = _TilePool()
        chi = _chi(pool, "2m", "3m", "4m")
        opened = _context(
            (
                "3p",
                "4p",
                "5p",
                "4s",
                "5s",
                "6s",
                "6s",
                "7s",
                "8s",
                "2p",
                "2p",
            ),
            pool=pool,
            declared_melds=(chi,),
        )

        self.assertEqual(
            _han_values(evaluate_yaku(closed), Yaku.TANYAO),
            frozenset({1}),
        )
        self.assertEqual(
            _han_values(evaluate_yaku(opened), Yaku.TANYAO),
            frozenset({1}),
        )

    def test_wind_and_dragon_yakuhai_stack(self) -> None:
        context = _context(
            (
                "1z",
                "1z",
                "1z",
                "5z",
                "5z",
                "5z",
                "1m",
                "2m",
                "3m",
                "4p",
                "5p",
                "6p",
                "2s",
                "2s",
            ),
            seat_wind=Wind.EAST,
            prevailing_wind=Wind.EAST,
        )

        self.assertLessEqual(
            {Yaku.SEAT_WIND, Yaku.PREVAILING_WIND, Yaku.WHITE_DRAGON},
            _all_yakus(evaluate_yaku(context)),
        )

    def test_each_dragon_triplet_is_yakuhai(self) -> None:
        cases = (
            ("5z", Yaku.WHITE_DRAGON),
            ("6z", Yaku.GREEN_DRAGON),
            ("7z", Yaku.RED_DRAGON),
        )
        for dragon, expected_yaku in cases:
            with self.subTest(dragon=dragon):
                context = _context(
                    (
                        dragon,
                        dragon,
                        dragon,
                        "1m",
                        "2m",
                        "3m",
                        "4p",
                        "5p",
                        "6p",
                        "7s",
                        "8s",
                        "9s",
                        "2m",
                        "2m",
                    )
                )

                self.assertIn(expected_yaku, _all_yakus(evaluate_yaku(context)))

    def test_pinfu_requires_non_value_pair_and_ryanmen(self) -> None:
        ryanmen = _context(
            (
                "1m",
                "2m",
                "3m",
                "4m",
                "5m",
                "6m",
                "2p",
                "3p",
                "6s",
                "7s",
                "8s",
                "5p",
                "5p",
                "4p",
            )
        )
        value_pair = _context(
            (
                "1m",
                "2m",
                "3m",
                "4m",
                "5m",
                "6m",
                "2p",
                "3p",
                "6s",
                "7s",
                "8s",
                "1z",
                "1z",
                "4p",
            ),
            seat_wind=Wind.EAST,
        )
        kanchan = _context(
            (
                "1m",
                "2m",
                "3m",
                "4m",
                "5m",
                "6m",
                "2p",
                "4p",
                "6s",
                "7s",
                "8s",
                "5p",
                "5p",
                "3p",
            )
        )
        pool = _TilePool()
        chi = _chi(pool, "1m", "2m", "3m")
        opened = _context(
            (
                "4m",
                "5m",
                "6m",
                "2p",
                "3p",
                "6s",
                "7s",
                "8s",
                "5p",
                "5p",
                "4p",
            ),
            pool=pool,
            declared_melds=(chi,),
        )

        self.assertIn(Yaku.PINFU, _all_yakus(evaluate_yaku(ryanmen)))
        self.assertNotIn(Yaku.PINFU, _all_yakus(evaluate_yaku(value_pair)))
        self.assertNotIn(Yaku.PINFU, _all_yakus(evaluate_yaku(kanchan)))
        self.assertNotIn(Yaku.PINFU, _all_yakus(evaluate_yaku(opened)))

    def test_ryanpeikou_replaces_iipeikou(self) -> None:
        iipeikou = _context(
            (
                "1m",
                "2m",
                "3m",
                "1m",
                "2m",
                "3m",
                "4p",
                "5p",
                "6p",
                "7s",
                "8s",
                "9s",
                "5p",
                "5p",
            )
        )
        ryanpeikou = _context(
            (
                "1m",
                "2m",
                "3m",
                "1m",
                "2m",
                "3m",
                "4p",
                "5p",
                "6p",
                "4p",
                "5p",
                "6p",
                "7s",
                "7s",
            )
        )

        self.assertIn(Yaku.IIPEIKOU, _all_yakus(evaluate_yaku(iipeikou)))
        ryanpeikou_yakus = _all_yakus(evaluate_yaku(ryanpeikou))
        self.assertIn(Yaku.RYANPEIKOU, ryanpeikou_yakus)
        self.assertNotIn(Yaku.IIPEIKOU, ryanpeikou_yakus)

    def test_iipeikou_requires_a_menzen_hand(self) -> None:
        pool = _TilePool()
        chi = _chi(pool, "7s", "8s", "9s")
        context = _context(
            (
                "1m",
                "2m",
                "3m",
                "1m",
                "2m",
                "3m",
                "4p",
                "5p",
                "6p",
                "5p",
                "5p",
            ),
            pool=pool,
            declared_melds=(chi,),
        )

        self.assertNotIn(Yaku.IIPEIKOU, _all_yakus(evaluate_yaku(context)))


class OutsideAndSequenceYakuTest(unittest.TestCase):
    def test_chanta_and_junchan_use_closed_and_open_han(self) -> None:
        chanta_names = (
            "1m",
            "2m",
            "3m",
            "7p",
            "8p",
            "9p",
            "9s",
            "9s",
            "9s",
            "4z",
            "4z",
            "4z",
            "5z",
            "5z",
        )
        closed_chanta = _context(chanta_names)
        pool = _TilePool()
        chanta_chi = _chi(pool, "1m", "2m", "3m")
        open_chanta = _context(
            chanta_names[3:],
            pool=pool,
            declared_melds=(chanta_chi,),
        )

        junchan_names = (
            "1m",
            "2m",
            "3m",
            "7p",
            "8p",
            "9p",
            "1s",
            "1s",
            "1s",
            "9s",
            "9s",
            "9s",
            "1p",
            "1p",
        )
        closed_junchan = _context(junchan_names)
        pool = _TilePool()
        junchan_chi = _chi(pool, "1m", "2m", "3m")
        open_junchan = _context(
            junchan_names[3:],
            pool=pool,
            declared_melds=(junchan_chi,),
        )

        self.assertEqual(
            _han_values(evaluate_yaku(closed_chanta), Yaku.CHANTA),
            frozenset({2}),
        )
        self.assertEqual(
            _han_values(evaluate_yaku(open_chanta), Yaku.CHANTA),
            frozenset({1}),
        )
        self.assertEqual(
            _han_values(evaluate_yaku(closed_junchan), Yaku.JUNCHAN),
            frozenset({3}),
        )
        self.assertEqual(
            _han_values(evaluate_yaku(open_junchan), Yaku.JUNCHAN),
            frozenset({2}),
        )
        self.assertNotIn(Yaku.CHANTA, _all_yakus(evaluate_yaku(closed_junchan)))

    def test_ittsuu_and_sanshoku_doujun_are_kuisagari(self) -> None:
        cases = (
            (
                Yaku.ITTSUU,
                ("1m", "2m", "3m"),
                (
                    "4m",
                    "5m",
                    "6m",
                    "7m",
                    "8m",
                    "9m",
                    "2p",
                    "2p",
                    "2p",
                    "5s",
                    "5s",
                ),
            ),
            (
                Yaku.SANSHOKU_DOUJUN,
                ("1m", "2m", "3m"),
                (
                    "1p",
                    "2p",
                    "3p",
                    "1s",
                    "2s",
                    "3s",
                    "7m",
                    "7m",
                    "7m",
                    "5p",
                    "5p",
                ),
            ),
        )
        for yaku, called_names, remaining_names in cases:
            with self.subTest(yaku=yaku):
                closed = _context((*called_names, *remaining_names))
                pool = _TilePool()
                chi = _chi(pool, *called_names)
                opened = _context(
                    remaining_names,
                    pool=pool,
                    declared_melds=(chi,),
                )

                self.assertEqual(
                    _han_values(evaluate_yaku(closed), yaku),
                    frozenset({2}),
                )
                self.assertEqual(
                    _han_values(evaluate_yaku(opened), yaku),
                    frozenset({1}),
                )

    def test_sanshoku_doukou_is_two_han_when_open(self) -> None:
        pool = _TilePool()
        pon = _pon(pool, "2m")
        context = _context(
            (
                "2p",
                "2p",
                "2p",
                "2s",
                "2s",
                "2s",
                "4m",
                "5m",
                "6m",
                "5z",
                "5z",
            ),
            pool=pool,
            declared_melds=(pon,),
        )

        self.assertEqual(
            _han_values(evaluate_yaku(context), Yaku.SANSHOKU_DOUKOU),
            frozenset({2}),
        )


class TripletAndSpecialYakuTest(unittest.TestCase):
    def test_toitoi_and_sanankou_can_coexist_in_open_hand(self) -> None:
        pool = _TilePool()
        pon = _pon(pool, "1m")
        context = _context(
            (
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
            ),
            pool=pool,
            declared_melds=(pon,),
        )

        self.assertLessEqual(
            {Yaku.TOITOI, Yaku.SANANKOU},
            _all_yakus(evaluate_yaku(context)),
        )

    def test_ron_completed_triplet_is_not_concealed_but_tsumo_is(self) -> None:
        def create(method: WinMethod) -> WinningContext:
            pool = _TilePool()
            pon = _pon(pool, "1m")
            return _context(
                (
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
                    "2p",
                ),
                pool=pool,
                declared_melds=(pon,),
                method=method,
            )

        ron_yakus = _all_yakus(evaluate_yaku(create(WinMethod.RON)))
        tsumo_yakus = _all_yakus(evaluate_yaku(create(WinMethod.TSUMO)))

        self.assertIn(Yaku.TOITOI, ron_yakus)
        self.assertNotIn(Yaku.SANANKOU, ron_yakus)
        self.assertIn(Yaku.SANANKOU, tsumo_yakus)

    def test_ankan_counts_as_a_concealed_triplet(self) -> None:
        pool = _TilePool()
        ankan = _ankan(pool, "1m")
        context = _context(
            (
                "2p",
                "2p",
                "2p",
                "3s",
                "3s",
                "3s",
                "4m",
                "5m",
                "6m",
                "5z",
                "5z",
            ),
            pool=pool,
            declared_melds=(ankan,),
        )

        self.assertIn(Yaku.SANANKOU, _all_yakus(evaluate_yaku(context)))

    def test_sankantsu_counts_all_three_kan_kinds(self) -> None:
        pool = _TilePool()
        melds = (
            _ankan(pool, "1m"),
            _daiminkan(pool, "2p"),
            _kakan(pool, "3s"),
        )
        context = _context(
            ("4z", "4z", "4z", "5m", "5m"),
            pool=pool,
            declared_melds=melds,
        )

        self.assertEqual(
            _han_values(evaluate_yaku(context), Yaku.SANKANTSU),
            frozenset({2}),
        )

    def test_shousangen_stacks_with_two_dragon_yakuhai(self) -> None:
        context = _context(
            (
                "5z",
                "5z",
                "5z",
                "6z",
                "6z",
                "6z",
                "7z",
                "7z",
                "1m",
                "2m",
                "3m",
                "4p",
                "5p",
                "6p",
            )
        )

        self.assertLessEqual(
            {Yaku.SHOUSANGEN, Yaku.WHITE_DRAGON, Yaku.GREEN_DRAGON},
            _all_yakus(evaluate_yaku(context)),
        )

    def test_honroutou_combines_with_toitoi_or_chiitoitsu(self) -> None:
        toitoi = _context(
            (
                "1m",
                "1m",
                "1m",
                "9m",
                "9m",
                "9m",
                "1p",
                "1p",
                "1p",
                "5z",
                "5z",
                "9p",
                "9p",
                "9p",
            )
        )
        chiitoitsu = _context(
            (
                "1m",
                "1m",
                "9m",
                "9m",
                "1p",
                "1p",
                "9p",
                "9p",
                "1s",
                "1s",
                "9s",
                "9s",
                "5z",
                "5z",
            )
        )

        self.assertLessEqual(
            {Yaku.HONROUTOU, Yaku.TOITOI},
            _all_yakus(evaluate_yaku(toitoi)),
        )
        self.assertLessEqual(
            {Yaku.HONROUTOU, Yaku.CHIITOITSU},
            _all_yakus(evaluate_yaku(chiitoitsu)),
        )

    def test_sequence_hand_is_not_toitoi(self) -> None:
        context = _context(
            (
                "5z",
                "5z",
                "5z",
                "1m",
                "2m",
                "3m",
                "4m",
                "5m",
                "6m",
                "6s",
                "7s",
                "8s",
                "2p",
                "2p",
            )
        )

        self.assertNotIn(Yaku.TOITOI, _all_yakus(evaluate_yaku(context)))


class YakumanTest(unittest.TestCase):
    def test_first_uninterrupted_tsumo_distinguishes_tenhou_chiihou(self) -> None:
        names = (
            "1m",
            "2m",
            "3m",
            "4p",
            "5p",
            "6p",
            "7s",
            "8s",
            "9s",
            "2m",
            "2m",
            "2m",
            "5z",
            "5z",
        )
        cases = (
            (Wind.EAST, Yaku.TENHOU),
            (Wind.SOUTH, Yaku.CHIIHOU),
        )
        for seat_wind, expected_yaku in cases:
            with self.subTest(seat_wind=seat_wind):
                context = _context(
                    names,
                    method=WinMethod.TSUMO,
                    seat_wind=seat_wind,
                    is_first_uninterrupted_turn=True,
                )
                evaluations = evaluate_yaku(context)

                self.assertEqual(_all_yakus(evaluations), frozenset({expected_yaku}))
                self.assertEqual(
                    _yakuman_units(evaluations, expected_yaku),
                    frozenset({1}),
                )

    def test_daisangen_replaces_normal_dragon_yaku(self) -> None:
        context = _context(
            (
                "5z",
                "5z",
                "5z",
                "6z",
                "6z",
                "6z",
                "7z",
                "7z",
                "7z",
                "1m",
                "2m",
                "3m",
                "1p",
                "1p",
            )
        )

        evaluations = evaluate_yaku(context)

        self.assertEqual(_all_yakus(evaluations), frozenset({Yaku.DAISANGEN}))
        self.assertTrue(all(evaluation.han == 0 for evaluation in evaluations))

    def test_suuankou_wait_and_ron_completed_triplet(self) -> None:
        shanpon_names = (
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
            "5m",
            "5m",
            "4z",
        )
        tanki_names = (
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
        shanpon_tsumo = _context(shanpon_names, method=WinMethod.TSUMO)
        shanpon_ron = _context(shanpon_names)
        tanki = _context(tanki_names)

        self.assertIn(Yaku.SUUANKOU, _all_yakus(evaluate_yaku(shanpon_tsumo)))
        ron_yakus = _all_yakus(evaluate_yaku(shanpon_ron))
        self.assertNotIn(Yaku.SUUANKOU, ron_yakus)
        self.assertNotIn(Yaku.SUUANKOU_TANKI, ron_yakus)
        self.assertIn(Yaku.SANANKOU, ron_yakus)

        self.assertEqual(
            _yakuman_units(evaluate_yaku(tanki), Yaku.SUUANKOU_TANKI),
            frozenset({1}),
        )
        self.assertEqual(
            _yakuman_units(
                evaluate_yaku(tanki, _DOUBLE_YAKUMAN_RULES),
                Yaku.SUUANKOU_TANKI,
            ),
            frozenset({2}),
        )

    def test_tsuuiisou_supports_standard_and_seven_pairs(self) -> None:
        standard = _context(
            (
                "1z",
                "1z",
                "1z",
                "2z",
                "2z",
                "2z",
                "5z",
                "5z",
                "5z",
                "7z",
                "7z",
                "6z",
                "6z",
                "6z",
            )
        )
        seven_pairs = _context(
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

        self.assertEqual(
            _all_yakus(evaluate_yaku(standard)), frozenset({Yaku.TSUUIISOU})
        )
        evaluations = evaluate_yaku(seven_pairs)
        self.assertEqual(_all_yakus(evaluations), frozenset({Yaku.TSUUIISOU}))
        self.assertEqual(
            {evaluation.shape for evaluation in evaluations},
            {WinningShape.SEVEN_PAIRS},
        )

    def test_ryuuiisou_does_not_require_green_dragon(self) -> None:
        pool = _TilePool()
        pon = _pon(pool, "2s")
        context = _context(
            (
                "3s",
                "3s",
                "3s",
                "4s",
                "4s",
                "4s",
                "6s",
                "6s",
                "6s",
                "8s",
                "8s",
            ),
            pool=pool,
            declared_melds=(pon,),
        )

        self.assertEqual(
            _all_yakus(evaluate_yaku(context)), frozenset({Yaku.RYUUIISOU})
        )

    def test_chinroutou_allows_open_hand(self) -> None:
        pool = _TilePool()
        pon = _pon(pool, "1m")
        context = _context(
            (
                "9m",
                "9m",
                "9m",
                "1p",
                "1p",
                "1p",
                "9p",
                "9p",
                "9p",
                "1s",
                "1s",
            ),
            pool=pool,
            declared_melds=(pon,),
        )

        self.assertEqual(
            _all_yakus(evaluate_yaku(context)), frozenset({Yaku.CHINROUTOU})
        )

    def test_big_and_little_four_winds_are_distinct(self) -> None:
        pool = _TilePool()
        big_winds = _context(
            ("5m", "5m"),
            pool=pool,
            declared_melds=tuple(_pon(pool, f"{rank}z") for rank in range(1, 5)),
        )
        little_winds = _context(
            (
                "1z",
                "1z",
                "1z",
                "2z",
                "2z",
                "2z",
                "3z",
                "3z",
                "3z",
                "1m",
                "2m",
                "3m",
                "4z",
                "4z",
            )
        )

        default_big = evaluate_yaku(big_winds)
        double_big = evaluate_yaku(big_winds, _DOUBLE_YAKUMAN_RULES)

        self.assertEqual(_all_yakus(default_big), frozenset({Yaku.DAISUUSHII}))
        self.assertEqual(
            _yakuman_units(default_big, Yaku.DAISUUSHII),
            frozenset({1}),
        )
        self.assertEqual(
            _yakuman_units(double_big, Yaku.DAISUUSHII),
            frozenset({2}),
        )
        self.assertEqual(
            _all_yakus(evaluate_yaku(little_winds)),
            frozenset({Yaku.SHOUSUUSHII}),
        )

    def test_suukantsu_counts_all_declared_kan_kinds(self) -> None:
        pool = _TilePool()
        context = _context(
            ("5z", "5z"),
            pool=pool,
            declared_melds=(
                _ankan(pool, "1m"),
                _daiminkan(pool, "2p"),
                _kakan(pool, "3s"),
                _daiminkan(pool, "4m"),
            ),
        )

        self.assertEqual(
            _all_yakus(evaluate_yaku(context)), frozenset({Yaku.SUUKANTSU})
        )

    def test_kokushi_distinguishes_single_and_thirteen_sided_wait(self) -> None:
        orphans = (
            "1m",
            "9m",
            "1p",
            "9p",
            "1s",
            "9s",
            "1z",
            "2z",
            "3z",
            "4z",
            "5z",
            "6z",
            "7z",
        )
        thirteen_sided = _context((*orphans, "1m"))
        single = _context(
            (
                "1m",
                "1m",
                "9m",
                "1p",
                "9p",
                "1s",
                "1z",
                "2z",
                "3z",
                "4z",
                "5z",
                "6z",
                "7z",
                "9s",
            )
        )

        self.assertEqual(
            _all_yakus(evaluate_yaku(single)),
            frozenset({Yaku.KOKUSHI_MUSOU}),
        )
        self.assertEqual(
            _yakuman_units(evaluate_yaku(thirteen_sided), Yaku.KOKUSHI_MUSOU_13_WAIT),
            frozenset({1}),
        )
        self.assertEqual(
            _yakuman_units(
                evaluate_yaku(thirteen_sided, _DOUBLE_YAKUMAN_RULES),
                Yaku.KOKUSHI_MUSOU_13_WAIT,
            ),
            frozenset({2}),
        )

    def test_chuuren_distinguishes_pure_nine_sided_wait(self) -> None:
        ordinary = _context(
            (
                "1m",
                "1m",
                "1m",
                "2m",
                "3m",
                "4m",
                "5m",
                "5m",
                "6m",
                "7m",
                "8m",
                "9m",
                "9m",
                "9m",
            )
        )
        pure = _context(
            (
                "1m",
                "1m",
                "1m",
                "2m",
                "3m",
                "4m",
                "5m",
                "6m",
                "7m",
                "8m",
                "9m",
                "9m",
                "9m",
                "5m",
            )
        )

        self.assertEqual(
            _all_yakus(evaluate_yaku(ordinary)),
            frozenset({Yaku.CHUUREN_POUTOU}),
        )
        self.assertEqual(
            _yakuman_units(evaluate_yaku(pure), Yaku.JUNSEI_CHUUREN_POUTOU),
            frozenset({1}),
        )
        self.assertEqual(
            _yakuman_units(
                evaluate_yaku(pure, _DOUBLE_YAKUMAN_RULES),
                Yaku.JUNSEI_CHUUREN_POUTOU,
            ),
            frozenset({2}),
        )

    def test_chuuren_rejects_hand_with_ankan(self) -> None:
        pool = _TilePool()
        ankan = _ankan(pool, "1m")
        context = _context(
            (
                "2m",
                "3m",
                "4m",
                "5m",
                "6m",
                "7m",
                "9m",
                "9m",
                "9m",
                "5m",
                "5m",
            ),
            pool=pool,
            declared_melds=(ankan,),
        )

        yakus = _all_yakus(evaluate_yaku(context))

        self.assertNotIn(Yaku.CHUUREN_POUTOU, yakus)
        self.assertNotIn(Yaku.JUNSEI_CHUUREN_POUTOU, yakus)
        self.assertIn(Yaku.CHINITSU, yakus)

    def test_multiple_yakuman_are_preserved(self) -> None:
        context = _context(
            (
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
        )

        evaluations = evaluate_yaku(context)

        self.assertEqual(
            _all_yakus(evaluations),
            frozenset({Yaku.DAISANGEN, Yaku.SUUANKOU_TANKI, Yaku.TSUUIISOU}),
        )
        self.assertTrue(
            all(evaluation.yakuman_units == 3 for evaluation in evaluations)
        )

    def test_double_yakuman_variants_apply_only_to_selected_yaku(self) -> None:
        context = _context(
            (
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
        )
        rules = replace(
            RuleSet.default(),
            double_yakuman_variants=frozenset({Yaku.SUUANKOU_TANKI}),
        )

        evaluations = evaluate_yaku(context, rules)

        self.assertEqual(
            _yakuman_units(evaluations, Yaku.SUUANKOU_TANKI), frozenset({2})
        )
        self.assertEqual(_yakuman_units(evaluations, Yaku.DAISANGEN), frozenset({1}))
        self.assertTrue(
            all(evaluation.yakuman_units == 4 for evaluation in evaluations)
        )


class SituationalYakuTest(unittest.TestCase):
    @staticmethod
    def _closed_context(
        *,
        method: WinMethod = WinMethod.RON,
        origin: WinOrigin | None = None,
        riichi_status: RiichiStatus = RiichiStatus.NONE,
        is_ippatsu: bool = False,
        is_last_tile: bool = False,
    ) -> WinningContext:
        return _context(
            (
                "1m",
                "2m",
                "3m",
                "4p",
                "5p",
                "6p",
                "7s",
                "8s",
                "9s",
                "2m",
                "2m",
                "2m",
                "5z",
                "5z",
            ),
            method=method,
            origin=origin,
            riichi_status=riichi_status,
            is_ippatsu=is_ippatsu,
            is_last_tile=is_last_tile,
        )

    @staticmethod
    def _open_context(
        *,
        method: WinMethod,
        origin: WinOrigin | None = None,
        is_last_tile: bool = False,
    ) -> WinningContext:
        pool = _TilePool()
        chi = _chi(pool, "1m", "2m", "3m")
        return _context(
            (
                "4p",
                "5p",
                "6p",
                "7s",
                "8s",
                "9s",
                "2m",
                "2m",
                "2m",
                "5z",
                "5z",
            ),
            pool=pool,
            declared_melds=(chi,),
            method=method,
            origin=origin,
            is_last_tile=is_last_tile,
        )

    def test_menzen_tsumo_allows_ankan_but_not_open_call(self) -> None:
        pool = _TilePool()
        ankan = _ankan(pool, "3z")
        with_ankan = _context(
            (
                "1m",
                "2m",
                "3m",
                "4p",
                "5p",
                "6p",
                "7s",
                "8s",
                "9s",
                "5z",
                "5z",
            ),
            pool=pool,
            declared_melds=(ankan,),
            method=WinMethod.TSUMO,
        )
        opened = self._open_context(method=WinMethod.TSUMO)

        self.assertIn(Yaku.MENZEN_TSUMO, _all_yakus(evaluate_yaku(with_ankan)))
        self.assertNotIn(Yaku.MENZEN_TSUMO, _all_yakus(evaluate_yaku(opened)))

    def test_double_riichi_replaces_riichi_and_ippatsu_stacks(self) -> None:
        riichi = self._closed_context(riichi_status=RiichiStatus.RIICHI)
        double_riichi = self._closed_context(
            riichi_status=RiichiStatus.DOUBLE_RIICHI,
        )
        ippatsu = self._closed_context(
            riichi_status=RiichiStatus.RIICHI,
            is_ippatsu=True,
        )

        self.assertIn(Yaku.RIICHI, _all_yakus(evaluate_yaku(riichi)))
        double_yakus = _all_yakus(evaluate_yaku(double_riichi))
        self.assertIn(Yaku.DOUBLE_RIICHI, double_yakus)
        self.assertNotIn(Yaku.RIICHI, double_yakus)
        self.assertLessEqual(
            {Yaku.RIICHI, Yaku.IPPATSU},
            _all_yakus(evaluate_yaku(ippatsu)),
        )

    def test_chankan_and_rinshan_follow_win_origin(self) -> None:
        chankan = self._open_context(
            method=WinMethod.RON,
            origin=WinOrigin.KAKAN,
        )
        rinshan = self._open_context(
            method=WinMethod.TSUMO,
            origin=WinOrigin.RINSHAN,
        )

        self.assertEqual(_all_yakus(evaluate_yaku(chankan)), frozenset({Yaku.CHANKAN}))
        self.assertEqual(
            _all_yakus(evaluate_yaku(rinshan)),
            frozenset({Yaku.RINSHAN_KAIHOU}),
        )

    def test_last_live_wall_tile_distinguishes_haitei_and_houtei(self) -> None:
        haitei = self._open_context(method=WinMethod.TSUMO, is_last_tile=True)
        houtei = self._open_context(method=WinMethod.RON, is_last_tile=True)

        self.assertEqual(_all_yakus(evaluate_yaku(haitei)), frozenset({Yaku.HAITEI}))
        self.assertEqual(_all_yakus(evaluate_yaku(houtei)), frozenset({Yaku.HOUTEI}))

    def test_ippatsu_and_chankan_can_coexist(self) -> None:
        context = self._closed_context(
            origin=WinOrigin.KAKAN,
            riichi_status=RiichiStatus.RIICHI,
            is_ippatsu=True,
        )

        self.assertLessEqual(
            {Yaku.RIICHI, Yaku.IPPATSU, Yaku.CHANKAN},
            _all_yakus(evaluate_yaku(context)),
        )


class FlushAndInterpretationYakuTest(unittest.TestCase):
    def test_honitsu_and_chinitsu_use_open_and_closed_han(self) -> None:
        honitsu_names = (
            "1m",
            "1m",
            "1m",
            "2m",
            "3m",
            "4m",
            "5m",
            "6m",
            "7m",
            "9m",
            "9m",
            "9m",
            "5z",
            "5z",
        )
        chinitsu_names = (
            "1m",
            "1m",
            "1m",
            "2m",
            "3m",
            "4m",
            "5m",
            "6m",
            "7m",
            "7m",
            "8m",
            "9m",
            "5m",
            "5m",
        )
        cases = (
            (Yaku.HONITSU, honitsu_names, 3, 2),
            (Yaku.CHINITSU, chinitsu_names, 6, 5),
        )
        for yaku, names, closed_han, open_han in cases:
            with self.subTest(yaku=yaku):
                closed = _context(names)
                pool = _TilePool()
                chi = _chi(pool, names[3], names[4], names[5])
                opened = _context(
                    (*names[:3], *names[6:]),
                    pool=pool,
                    declared_melds=(chi,),
                )

                self.assertEqual(
                    _han_values(evaluate_yaku(closed), yaku),
                    frozenset({closed_han}),
                )
                self.assertEqual(
                    _han_values(evaluate_yaku(opened), yaku),
                    frozenset({open_han}),
                )

        self.assertNotIn(
            Yaku.HONITSU,
            _all_yakus(evaluate_yaku(_context(chinitsu_names))),
        )

    def test_seven_pairs_combines_with_tile_set_yaku(self) -> None:
        context = _context(
            (
                "2m",
                "2m",
                "3m",
                "3m",
                "4m",
                "4m",
                "5p",
                "5p",
                "6p",
                "6p",
                "7s",
                "7s",
                "8s",
                "8s",
            )
        )

        self.assertLessEqual(
            {Yaku.CHIITOITSU, Yaku.TANYAO},
            _all_yakus(evaluate_yaku(context)),
        )

    def test_preserves_standard_and_seven_pairs_interpretations(self) -> None:
        context = _context(
            (
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
        )

        evaluations = evaluate_yaku(context)

        self.assertEqual(
            {evaluation.shape for evaluation in evaluations},
            {WinningShape.STANDARD, WinningShape.SEVEN_PAIRS},
        )
        self.assertTrue(
            any(
                Yaku.RYANPEIKOU in evaluation.yakus
                for evaluation in evaluations
                if evaluation.shape is WinningShape.STANDARD
            )
        )
        self.assertTrue(
            any(
                Yaku.CHIITOITSU in evaluation.yakus
                for evaluation in evaluations
                if evaluation.shape is WinningShape.SEVEN_PAIRS
            )
        )

    def test_returns_empty_set_for_complete_but_yakuless_open_hand(self) -> None:
        pool = _TilePool()
        chi = _chi(pool, "1m", "2m", "3m")
        context = _context(
            (
                "4p",
                "5p",
                "6p",
                "7s",
                "8s",
                "9s",
                "2m",
                "2m",
                "2m",
                "5z",
                "5z",
            ),
            pool=pool,
            declared_melds=(chi,),
        )

        self.assertEqual(evaluate_yaku(context), frozenset())


if __name__ == "__main__":
    unittest.main()
