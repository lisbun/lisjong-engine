import unittest

from lisjong_engine.reaction_boundary import has_possible_reaction
from lisjong_engine.seat import Seat
from lisjong_engine.tile import STANDARD_TILES, Tile, TileCategory, TileType

_TILE_CATEGORIES = {
    "m": TileCategory.MANZU,
    "p": TileCategory.PINZU,
    "s": TileCategory.SOUZU,
    "z": TileCategory.HONOR,
}
_NON_REACTING_HAND = (
    "1m",
    "2m",
    "4m",
    "7m",
    "1p",
    "3p",
    "6p",
    "9p",
    "2s",
    "5s",
    "8s",
    "1z",
    "3z",
)


def _tile_type(name: str) -> TileType:
    return TileType(_TILE_CATEGORIES[name[-1]], int(name[:-1]))


def _tiles(*names: str) -> tuple[Tile, ...]:
    copy_counts: dict[TileType, int] = {}
    tiles = []

    for name in names:
        tile_type = _tile_type(name)
        copy_index = copy_counts.get(tile_type, 0)
        tiles.append(STANDARD_TILES[tile_type.id * 4 + copy_index])
        copy_counts[tile_type] = copy_index + 1

    return tuple(tiles)


def _distinct_tile(name: str, copy_index: int) -> Tile:
    return STANDARD_TILES[_tile_type(name).id * 4 + copy_index]


class ReactionBoundaryTest(unittest.TestCase):
    def _detect(
        self,
        *,
        discarder: Seat = Seat.EAST,
        discarded_tile: Tile | None = None,
        hands: dict[Seat, tuple[Tile, ...]] | None = None,
        remaining_count: int = 20,
        can_draw_rinshan: bool = True,
    ) -> bool:
        hand_tiles_by_seat = {seat: () for seat in Seat}
        hand_tiles_by_seat.update(hands or {})
        return has_possible_reaction(
            discarder=discarder,
            discarded_tile=(
                _distinct_tile("5p", 3) if discarded_tile is None else discarded_tile
            ),
            hand_tiles_by_seat=hand_tiles_by_seat,
            melds_by_seat={seat: () for seat in Seat},
            remaining_count=remaining_count,
            can_draw_rinshan=can_draw_rinshan,
        )

    def test_reports_no_reaction_when_no_seat_can_respond(self) -> None:
        self.assertFalse(
            self._detect(
                hands={
                    seat: _tiles(*_NON_REACTING_HAND)
                    for seat in (Seat.SOUTH, Seat.WEST, Seat.NORTH)
                }
            )
        )

    def test_detects_a_possible_pon_from_any_seat(self) -> None:
        for seat in (Seat.SOUTH, Seat.WEST, Seat.NORTH):
            with self.subTest(seat=seat):
                self.assertTrue(
                    self._detect(hands={seat: _tiles("5p", "5p")}),
                )

    def test_detects_a_possible_daiminkan(self) -> None:
        self.assertTrue(self._detect(hands={Seat.WEST: _tiles("5p", "5p", "5p")}))

    def test_detects_a_possible_chi_only_from_the_next_seat(self) -> None:
        self.assertTrue(self._detect(hands={Seat.SOUTH: _tiles("3p", "4p")}))
        self.assertFalse(self._detect(hands={Seat.WEST: _tiles("3p", "4p")}))
        self.assertFalse(self._detect(hands={Seat.NORTH: _tiles("3p", "4p")}))

    def test_detects_every_chi_shape(self) -> None:
        for names in (("3p", "4p"), ("4p", "6p"), ("6p", "7p")):
            with self.subTest(names=names):
                self.assertTrue(self._detect(hands={Seat.SOUTH: _tiles(*names)}))

    def test_does_not_report_a_chi_across_categories_or_on_honors(self) -> None:
        self.assertFalse(self._detect(hands={Seat.SOUTH: _tiles("3m", "4m")}))
        self.assertFalse(
            self._detect(
                discarded_tile=_distinct_tile("1z", 3),
                hands={Seat.SOUTH: _tiles("2z", "3z")},
            )
        )

    def test_detects_a_possible_ron_shape(self) -> None:
        tenpai_hand = _tiles(
            "1m",
            "1m",
            "1m",
            "2m",
            "3m",
            "4m",
            "6m",
            "7m",
            "8m",
            "1p",
            "1p",
            "3p",
            "4p",
        )

        self.assertTrue(self._detect(hands={Seat.WEST: tenpai_hand}))

    def test_does_not_report_a_ron_shape_that_is_not_complete(self) -> None:
        tenpai_hand = _tiles(
            "1m",
            "1m",
            "1m",
            "2m",
            "3m",
            "4m",
            "6m",
            "7m",
            "8m",
            "1p",
            "1p",
            "3p",
            "9p",
        )

        self.assertFalse(self._detect(hands={Seat.WEST: tenpai_hand}))

    def test_detection_ignores_yaku_and_furiten_to_stay_fail_safe(self) -> None:
        """役なし・フリテンでもロン形は反応候補ありとして扱う。

        E1は成立可否まで判定しない。E2の解決を安全に接続するため、
        必要条件だけを見て過大に検知する。
        """
        yakuless_hand = _tiles(
            "2m",
            "3m",
            "4m",
            "5p",
            "6p",
            "7p",
            "2s",
            "3s",
            "4s",
            "6s",
            "7s",
            "7z",
            "7z",
        )

        self.assertTrue(
            self._detect(
                discarded_tile=_distinct_tile("8s", 3),
                hands={Seat.WEST: yakuless_hand},
            )
        )

    def test_calls_require_a_live_wall_but_ron_does_not(self) -> None:
        self.assertFalse(
            self._detect(
                hands={Seat.SOUTH: _tiles("5p", "5p", "5p")},
                remaining_count=0,
                can_draw_rinshan=False,
            )
        )

        haitei_tenpai_hand = _tiles(
            "1m",
            "1m",
            "1m",
            "2m",
            "3m",
            "4m",
            "6m",
            "7m",
            "8m",
            "1p",
            "1p",
            "3p",
            "4p",
        )
        self.assertTrue(
            self._detect(
                hands={Seat.WEST: haitei_tenpai_hand},
                remaining_count=0,
                can_draw_rinshan=False,
            )
        )

    def test_daiminkan_requires_a_drawable_rinshan_tile(self) -> None:
        self.assertFalse(
            self._detect(
                hands={Seat.WEST: _tiles("5p", "5p", "5p")},
                remaining_count=0,
                can_draw_rinshan=False,
            )
        )

    def test_ignores_the_discarder_own_hand(self) -> None:
        self.assertFalse(
            self._detect(
                discarder=Seat.EAST,
                hands={Seat.EAST: _tiles("5p", "5p", "5p")},
            )
        )

    def test_rejects_invalid_argument_types(self) -> None:
        with self.assertRaises(TypeError):
            self._detect(discarder="east")
        with self.assertRaises(TypeError):
            self._detect(discarded_tile="5p")
        with self.assertRaises(TypeError):
            self._detect(remaining_count="20")
        with self.assertRaises(TypeError):
            self._detect(can_draw_rinshan=1)

    def test_rejects_a_negative_remaining_count(self) -> None:
        with self.assertRaises(ValueError):
            self._detect(remaining_count=-1)


if __name__ == "__main__":
    unittest.main()
