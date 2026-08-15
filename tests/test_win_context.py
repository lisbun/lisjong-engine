import unittest

from lisjong_engine.meld import Ankan, Chi, Pon
from lisjong_engine.seat import Seat
from lisjong_engine.tile import STANDARD_TILES, Tile, TileCategory, TileType
from lisjong_engine.win_context import (
    RiichiStatus,
    WinMethod,
    WinningContext,
    WinOrigin,
)
from lisjong_engine.wind import Wind

_CATEGORIES = {
    "m": TileCategory.MANZU,
    "p": TileCategory.PINZU,
    "s": TileCategory.SOUZU,
    "z": TileCategory.HONOR,
}


def _tile_type(name: str) -> TileType:
    return TileType(_CATEGORIES[name[-1]], int(name[:-1]))


class _TilePool:
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


def _base_context(
    pool: _TilePool | None = None,
    *,
    declared_melds: tuple[object, ...] = (),
    **overrides: object,
) -> WinningContext:
    tile_pool = _TilePool() if pool is None else pool
    concealed_tiles = tile_pool.take(
        "1m",
        "2m",
        "3m",
        "4m",
        "5m",
        "6m",
        "7m",
        "8m",
        "9m",
        "1p",
        "1p",
        "1p",
        "2z",
        "2z",
    )
    values = {
        "concealed_tiles": concealed_tiles,
        "winning_tile": concealed_tiles[-1],
        "method": WinMethod.RON,
        "origin": WinOrigin.DISCARD,
        "seat_wind": Wind.SOUTH,
        "prevailing_wind": Wind.EAST,
        "declared_melds": declared_melds,
    }
    values.update(overrides)
    return WinningContext(**values)


class WinningContextTest(unittest.TestCase):
    def test_copies_collections_and_exposes_all_tiles(self) -> None:
        pool = _TilePool()
        meld_tiles = pool.take("7z", "7z", "7z")
        pon = Pon(meld_tiles[0], meld_tiles[1:], Seat.WEST)
        concealed_tiles = list(
            pool.take(
                "1m",
                "2m",
                "3m",
                "4m",
                "5m",
                "6m",
                "7m",
                "8m",
                "9m",
                "2z",
                "2z",
            )
        )
        melds = [pon]

        context = WinningContext(
            concealed_tiles=concealed_tiles,
            winning_tile=concealed_tiles[-1],
            method=WinMethod.RON,
            origin=WinOrigin.DISCARD,
            seat_wind=Wind.SOUTH,
            prevailing_wind=Wind.EAST,
            declared_melds=melds,
        )
        concealed_tiles.clear()
        melds.clear()

        self.assertEqual(len(context.concealed_tiles), 11)
        self.assertEqual(context.declared_melds, (pon,))
        self.assertEqual(
            context.all_tiles,
            (*context.concealed_tiles, *pon.tiles),
        )
        self.assertFalse(context.is_menzen)

    def test_ankan_keeps_hand_menzen(self) -> None:
        pool = _TilePool()
        tiles = pool.take("1z", "1z", "1z", "1z")
        ankan = Ankan(tiles)
        concealed_tiles = pool.take(
            "1m",
            "2m",
            "3m",
            "4m",
            "5m",
            "6m",
            "7m",
            "8m",
            "9m",
            "2z",
            "2z",
        )

        context = WinningContext(
            concealed_tiles=concealed_tiles,
            winning_tile=concealed_tiles[-1],
            method=WinMethod.TSUMO,
            origin=WinOrigin.LIVE_WALL,
            seat_wind=Wind.EAST,
            prevailing_wind=Wind.EAST,
            declared_melds=(ankan,),
            riichi_status=RiichiStatus.RIICHI,
        )

        self.assertTrue(context.is_menzen)

    def test_rejects_invalid_collections_and_winning_tile(self) -> None:
        context = _base_context()
        invalid_cases = (
            ({"concealed_tiles": None}, TypeError),
            (
                {
                    "concealed_tiles": (
                        *context.concealed_tiles[:-1],
                        "2z",
                    )
                },
                TypeError,
            ),
            ({"declared_melds": None}, TypeError),
            (
                {"declared_melds": (context.concealed_tiles[0],)},
                TypeError,
            ),
            ({"winning_tile": "2z"}, TypeError),
            ({"winning_tile": STANDARD_TILES[-1]}, ValueError),
        )

        for overrides, expected_error in invalid_cases:
            with self.subTest(overrides=overrides):
                values = {
                    **context.__dict__,
                    **overrides,
                }
                with self.assertRaises(expected_error):
                    WinningContext(**values)

    def test_rejects_duplicate_physical_tiles(self) -> None:
        context = _base_context()

        with self.assertRaises(ValueError):
            WinningContext(
                **{
                    **context.__dict__,
                    "concealed_tiles": (
                        *context.concealed_tiles,
                        context.concealed_tiles[0],
                    ),
                }
            )

    def test_rejects_invalid_method_origin_and_winds(self) -> None:
        context = _base_context()
        invalid_cases = (
            ({"method": "ron"}, TypeError),
            ({"origin": "discard"}, TypeError),
            ({"seat_wind": Seat.EAST}, TypeError),
            ({"prevailing_wind": Seat.EAST}, TypeError),
            (
                {
                    "method": WinMethod.TSUMO,
                    "origin": WinOrigin.DISCARD,
                },
                ValueError,
            ),
            (
                {
                    "method": WinMethod.RON,
                    "origin": WinOrigin.LIVE_WALL,
                },
                ValueError,
            ),
        )

        for overrides, expected_error in invalid_cases:
            with (
                self.subTest(overrides=overrides),
                self.assertRaises(expected_error),
            ):
                WinningContext(
                    **{
                        **context.__dict__,
                        **overrides,
                    }
                )

    def test_accepts_and_rejects_suukantsu_pao_seat(self) -> None:
        context = _base_context()

        self.assertIsNone(context.suukantsu_pao_seat)
        accepted = WinningContext(
            **{**context.__dict__, "suukantsu_pao_seat": Seat.WEST}
        )
        self.assertIs(accepted.suukantsu_pao_seat, Seat.WEST)

        with self.assertRaises(TypeError):
            WinningContext(**{**context.__dict__, "suukantsu_pao_seat": "west"})

    def test_validates_riichi_and_ippatsu_relationships(self) -> None:
        context = _base_context()
        pool = _TilePool()
        chi_tiles = pool.take("1s", "2s", "3s")
        chi = Chi(chi_tiles[0], chi_tiles[1:], Seat.NORTH)
        open_context = _base_context(pool, declared_melds=(chi,))

        invalid_values = (
            {
                **open_context.__dict__,
                "riichi_status": RiichiStatus.RIICHI,
            },
            {
                **context.__dict__,
                "is_ippatsu": True,
            },
            {
                **context.__dict__,
                "method": WinMethod.TSUMO,
                "origin": WinOrigin.RINSHAN,
                "riichi_status": RiichiStatus.RIICHI,
                "is_ippatsu": True,
            },
        )

        for values in invalid_values:
            with self.subTest(values=values), self.assertRaises(ValueError):
                WinningContext(**values)

    def test_validates_last_tile_and_first_turn_flags(self) -> None:
        context = _base_context()

        with self.assertRaises(ValueError):
            WinningContext(
                **{
                    **context.__dict__,
                    "origin": WinOrigin.KAKAN,
                    "is_last_tile": True,
                }
            )
        with self.assertRaises(ValueError):
            WinningContext(
                **{
                    **context.__dict__,
                    "is_first_uninterrupted_turn": True,
                }
            )

        first_turn = WinningContext(
            **{
                **context.__dict__,
                "method": WinMethod.TSUMO,
                "origin": WinOrigin.LIVE_WALL,
                "is_first_uninterrupted_turn": True,
            }
        )

        self.assertTrue(first_turn.is_first_uninterrupted_turn)


if __name__ == "__main__":
    unittest.main()
