import unittest

from _round_fixtures import tiles

from lisjong_engine.kan import (
    PendingAnkan,
    PendingKakan,
    count_quads,
    find_kakan_pon,
    is_riichi_ankan_allowed,
    validate_riichi_ankan,
)
from lisjong_engine.meld import Ankan, Chi, Daiminkan, Kakan, Pon
from lisjong_engine.rules import RiichiAnkanPolicy
from lisjong_engine.seat import Seat

_SOU_FIVES = tiles("5s", "5s", "5s", "5s")
_PON = Pon(_SOU_FIVES[0], _SOU_FIVES[1:3], Seat.WEST)
_ADDED_TILE = _SOU_FIVES[3]
_ANKAN = Ankan(tiles("1z", "1z", "1z", "1z"))
_PIN_NINES = tiles("9p", "9p", "9p", "9p")


class PendingKanTest(unittest.TestCase):
    def test_a_pending_kakan_targets_the_added_tile(self) -> None:
        kakan = Kakan(_PON, _ADDED_TILE)

        pending = PendingKakan(Seat.SOUTH, kakan)

        self.assertIs(pending.seat, Seat.SOUTH)
        self.assertEqual(pending.target_tile, kakan.added_tile)

    def test_a_pending_ankan_targets_one_of_the_quad_tiles(self) -> None:
        pending = PendingAnkan(Seat.NORTH, _ANKAN)

        self.assertIs(pending.seat, Seat.NORTH)
        self.assertEqual(pending.target_tile, _ANKAN.tiles[0])

    def test_rejects_invalid_fields(self) -> None:
        with self.assertRaises(TypeError):
            PendingKakan("south", Kakan(_PON, _ADDED_TILE))
        with self.assertRaises(TypeError):
            PendingKakan(Seat.SOUTH, _PON)
        with self.assertRaises(TypeError):
            PendingAnkan("north", _ANKAN)
        with self.assertRaises(TypeError):
            PendingAnkan(Seat.NORTH, _PON)


class CountQuadsTest(unittest.TestCase):
    def test_counts_every_kind_of_quad(self) -> None:
        melds = (
            _ANKAN,
            Kakan(_PON, _ADDED_TILE),
            Daiminkan(_PIN_NINES[0], _PIN_NINES[1:], Seat.EAST),
        )

        self.assertEqual(count_quads(melds), 3)

    def test_ignores_pon_and_chi(self) -> None:
        chi = Chi(tiles("3m")[0], tiles("4m", "5m"), Seat.EAST)

        self.assertEqual(count_quads((_PON, chi)), 0)


class FindKakanPonTest(unittest.TestCase):
    def test_finds_the_pon_of_the_same_tile_type(self) -> None:
        added_tile = _ADDED_TILE

        self.assertIs(find_kakan_pon((_PON,), added_tile), _PON)

    def test_returns_none_without_a_matching_pon(self) -> None:
        self.assertIsNone(find_kakan_pon((_PON,), _PIN_NINES[0]))

    def test_ignores_melds_that_are_not_pon(self) -> None:
        ankan = Ankan(_SOU_FIVES)

        self.assertIsNone(find_kakan_pon((ankan,), _SOU_FIVES[0]))

    def test_rejects_a_value_that_is_not_a_tile(self) -> None:
        with self.assertRaises(TypeError):
            find_kakan_pon((_PON,), "5s")


class ValidateRiichiAnkanTest(unittest.TestCase):
    def _hand_with_quad_wait(self) -> tuple[tuple, tuple[int, ...]]:
        """1mの暗刻を含み、待ちが暗槓で変わらない手牌を返す。

        2m3m4m 5m6m7m 1m1m1m 7p8p9p + 5s（単騎）に1mを1枚ツモった形。
        1mを暗槓しても待ちは5s単騎のまま変わらない。
        """
        hand = tiles(
            "1m",
            "1m",
            "1m",
            "2m",
            "3m",
            "4m",
            "5m",
            "6m",
            "7m",
            "7p",
            "8p",
            "9p",
            "5s",
            "1m",
        )
        quad_ids = tuple(
            tile.id for tile in hand if tile.tile_type == hand[0].tile_type
        )
        return hand, quad_ids

    def test_accepts_an_ankan_that_keeps_the_wait_and_decomposition(self) -> None:
        hand, quad_ids = self._hand_with_quad_wait()
        drawn_tile = hand[-1]

        validate_riichi_ankan(
            hand_tiles=hand,
            melds=(),
            drawn_tile=drawn_tile,
            tile_ids=quad_ids,
            policy=RiichiAnkanPolicy.PRESERVE_WAIT_AND_DECOMPOSITION,
        )

        self.assertTrue(
            is_riichi_ankan_allowed(
                hand_tiles=hand,
                melds=(),
                drawn_tile=drawn_tile,
                tile_ids=quad_ids,
                policy=RiichiAnkanPolicy.PRESERVE_WAIT_ONLY,
            )
        )

    def test_rejects_an_ankan_that_does_not_use_the_drawn_tile(self) -> None:
        """送り槓（手内の4枚だけで槓する）は、policyに関わらず認めない。"""
        hand, quad_ids = self._hand_with_quad_wait()
        other_drawn_tile = next(tile for tile in hand if tile.id not in quad_ids)

        with self.assertRaises(ValueError):
            validate_riichi_ankan(
                hand_tiles=hand,
                melds=(),
                drawn_tile=other_drawn_tile,
                tile_ids=quad_ids,
                policy=RiichiAnkanPolicy.PRESERVE_WAIT_ONLY,
            )

    def test_rejects_an_ankan_that_changes_the_wait(self) -> None:
        """1m1m1m2m3m4m…の形では、1mの暗槓で待ちが変わる。"""
        hand = tiles(
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
            "1m",
        )
        quad_ids = tuple(
            tile.id for tile in hand if tile.tile_type == hand[0].tile_type
        )

        self.assertFalse(
            is_riichi_ankan_allowed(
                hand_tiles=hand,
                melds=(),
                drawn_tile=hand[-1],
                tile_ids=quad_ids,
                policy=RiichiAnkanPolicy.PRESERVE_WAIT_ONLY,
            )
        )

    def test_rejects_tiles_that_are_not_in_the_hand(self) -> None:
        hand, quad_ids = self._hand_with_quad_wait()

        with self.assertRaises(ValueError):
            validate_riichi_ankan(
                hand_tiles=hand[:-1],
                melds=(),
                drawn_tile=hand[-1],
                tile_ids=quad_ids,
                policy=RiichiAnkanPolicy.PRESERVE_WAIT_ONLY,
            )

    def test_rejects_invalid_arguments(self) -> None:
        hand, quad_ids = self._hand_with_quad_wait()

        with self.assertRaises(TypeError):
            validate_riichi_ankan(
                hand_tiles=hand,
                melds=(),
                drawn_tile="1m",
                tile_ids=quad_ids,
                policy=RiichiAnkanPolicy.PRESERVE_WAIT_ONLY,
            )
        with self.assertRaises(TypeError):
            validate_riichi_ankan(
                hand_tiles=hand,
                melds=(),
                drawn_tile=hand[-1],
                tile_ids=quad_ids,
                policy="preserve_wait_only",
            )


if __name__ == "__main__":
    unittest.main()
