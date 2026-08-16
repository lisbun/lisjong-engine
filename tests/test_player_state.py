import unittest

from lisjong_engine.discard import Discard
from lisjong_engine.furiten import FuritenReason
from lisjong_engine.meld import Chi, Pon
from lisjong_engine.player_state import PlayerState
from lisjong_engine.seat import Seat
from lisjong_engine.tile import STANDARD_TILES, Tile, TileCategory, TileType
from lisjong_engine.win_context import RiichiStatus

_TILE_CATEGORIES = {
    "m": TileCategory.MANZU,
    "p": TileCategory.PINZU,
    "s": TileCategory.SOUZU,
    "z": TileCategory.HONOR,
}


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


class PlayerStateTest(unittest.TestCase):
    def test_starts_empty_for_the_given_seat(self) -> None:
        player = PlayerState(Seat.SOUTH)

        self.assertIs(player.seat, Seat.SOUTH)
        self.assertEqual(player.hand_tiles, ())
        self.assertEqual(player.discards, ())
        self.assertEqual(player.melds, ())
        self.assertTrue(player.is_menzen)

    def test_exposes_immutable_views(self) -> None:
        player = PlayerState(Seat.EAST, _tiles("1m", "2m"))

        self.assertIsInstance(player.hand_tiles, tuple)
        self.assertIsInstance(player.discards, tuple)
        self.assertIsInstance(player.melds, tuple)
        self.assertFalse(hasattr(player, "hand"))
        self.assertFalse(hasattr(player, "river"))

    def test_rejects_a_non_seat(self) -> None:
        with self.assertRaises(TypeError):
            PlayerState("east")

    def test_adds_and_discards_physical_tiles(self) -> None:
        hand_tiles = _tiles("1m", "2m", "3m")
        player = PlayerState(Seat.EAST, hand_tiles)
        drawn_tile = _tiles("9p")[0]

        player.add_tile(drawn_tile)
        discard = player.discard_tile(hand_tiles[1].id, is_tsumogiri=False)

        self.assertEqual(
            player.hand_tiles,
            (hand_tiles[0], hand_tiles[2], drawn_tile),
        )
        self.assertEqual(discard.tile, hand_tiles[1])
        self.assertFalse(discard.is_tsumogiri)
        self.assertEqual(player.discards, (discard,))

    def test_records_tsumogiri_as_told_by_the_round(self) -> None:
        hand_tiles = _tiles("1m", "2m")
        player = PlayerState(Seat.EAST, hand_tiles)

        discard = player.discard_tile(hand_tiles[0].id, is_tsumogiri=True)

        self.assertTrue(discard.is_tsumogiri)

    def test_rejects_a_non_boolean_tsumogiri_flag(self) -> None:
        hand_tiles = _tiles("1m")
        player = PlayerState(Seat.EAST, hand_tiles)

        with self.assertRaises(TypeError):
            player.discard_tile(hand_tiles[0].id, is_tsumogiri=1)

    def test_rejects_discarding_a_tile_that_is_not_in_hand(self) -> None:
        hand_tiles = _tiles("1m", "2m")
        player = PlayerState(Seat.EAST, hand_tiles)

        with self.assertRaises(ValueError):
            player.discard_tile(_tiles("9s")[0].id, is_tsumogiri=False)

        self.assertEqual(player.hand_tiles, hand_tiles)
        self.assertEqual(player.discards, ())

    def test_rejects_adding_a_tile_that_is_already_in_the_river(self) -> None:
        tile = _tiles("1m")[0]
        player = PlayerState(Seat.EAST, (), (Discard(tile, is_tsumogiri=False),))

        with self.assertRaises(ValueError):
            player.add_tile(tile)

    def test_rejects_overlapping_hand_river_and_melds(self) -> None:
        tile = _tiles("1m")[0]

        with self.assertRaises(ValueError):
            PlayerState(Seat.EAST, (tile,), (Discard(tile, is_tsumogiri=False),))

        pon_tiles = _tiles("2m", "2m", "2m")
        pon = Pon(pon_tiles[0], (pon_tiles[1], pon_tiles[2]), Seat.NORTH)
        with self.assertRaises(ValueError):
            PlayerState(Seat.EAST, (pon_tiles[0],), (), (pon,))

    def test_rejects_non_meld_values(self) -> None:
        with self.assertRaises(TypeError):
            PlayerState(Seat.EAST, (), (), ("pon",))

    def test_owned_tile_ids_cover_hand_river_and_melds(self) -> None:
        hand_tiles = _tiles("1m", "2m")
        discarded_tile = _tiles("3m")[0]
        pon_tiles = _tiles("4m", "4m", "4m")
        pon = Pon(pon_tiles[0], (pon_tiles[1], pon_tiles[2]), Seat.NORTH)
        player = PlayerState(
            Seat.EAST,
            hand_tiles,
            (Discard(discarded_tile, is_tsumogiri=False),),
            (pon,),
        )

        self.assertEqual(
            sorted(player.owned_tile_ids),
            sorted(tile.id for tile in (*hand_tiles, discarded_tile, *pon_tiles)),
        )

    def test_owned_tile_ids_exclude_discards_that_were_called(self) -> None:
        discarded_tile = _tiles("3m")[0]
        player = PlayerState(
            Seat.EAST,
            (),
            (Discard(discarded_tile, is_tsumogiri=False, called_by=Seat.SOUTH),),
        )

        self.assertEqual(player.owned_tile_ids, ())

    def test_is_menzen_only_breaks_on_open_melds(self) -> None:
        pon_tiles = _tiles("4m", "4m", "4m")
        pon = Pon(pon_tiles[0], (pon_tiles[1], pon_tiles[2]), Seat.NORTH)

        self.assertFalse(PlayerState(Seat.EAST, (), (), (pon,)).is_menzen)

    def test_copy_is_independent_of_the_original(self) -> None:
        hand_tiles = _tiles("1m", "2m")
        player = PlayerState(Seat.EAST, hand_tiles)

        copied = player.copy()
        copied.discard_tile(hand_tiles[0].id, is_tsumogiri=False)

        self.assertIs(copied.seat, Seat.EAST)
        self.assertEqual(player.hand_tiles, hand_tiles)
        self.assertEqual(player.discards, ())
        self.assertEqual(copied.hand_tiles, (hand_tiles[1],))
        self.assertEqual(len(copied.discards), 1)


class PlayerStateOwnershipInvariantTest(unittest.TestCase):
    """同じ席の河と副露が同じ物理牌を持つ状態を拒否する。

    自分の捨て牌を自分で鳴くことはできないため、席内での重複は不正である。
    一方、鳴かれた捨て牌が他家の河の記録として残ることは正常であり、席を
    またぐ重複はここでは禁止しない（その検証は`RoundState`のownership
    保存則が担当する）。
    """

    def test_rejects_a_tile_owned_by_both_the_river_and_a_meld(self) -> None:
        pon_tiles = _tiles("5s", "5s", "5s")
        pon = Pon(pon_tiles[0], pon_tiles[1:], Seat.WEST)

        with self.assertRaises(ValueError):
            PlayerState(
                Seat.EAST,
                discards=(Discard(pon_tiles[0], is_tsumogiri=False),),
                melds=(pon,),
            )

    def test_allows_a_meld_called_from_another_seat(self) -> None:
        pon_tiles = _tiles("5s", "5s", "5s")
        pon = Pon(pon_tiles[0], pon_tiles[1:], Seat.WEST)

        player = PlayerState(Seat.EAST, melds=(pon,))

        self.assertEqual(player.melds, (pon,))

    def test_called_discards_leave_this_seat_ownership(self) -> None:
        discarded = _tiles("5s")[0]
        player = PlayerState(
            Seat.EAST,
            discards=(Discard(discarded, is_tsumogiri=False),),
        )

        self.assertIn(discarded.id, player.owned_tile_ids)

        player.mark_discard_called(discarded.id, Seat.SOUTH)

        self.assertNotIn(discarded.id, player.owned_tile_ids)


class PlayerStateRoundStateTest(unittest.TestCase):
    def test_starts_without_riichi_ippatsu_or_missed_ron_furiten(self) -> None:
        player = PlayerState(Seat.EAST)

        self.assertIs(player.riichi_status, RiichiStatus.NONE)
        self.assertFalse(player.is_riichi_established)
        self.assertFalse(player.is_double_riichi)
        self.assertFalse(player.is_ippatsu)
        self.assertIsNone(player.missed_ron_furiten)
        self.assertFalse(player.is_furiten)

    def test_establishes_riichi_with_an_ippatsu_window(self) -> None:
        player = PlayerState(Seat.EAST)

        player.establish_riichi(RiichiStatus.DOUBLE_RIICHI, ippatsu=True)

        self.assertIs(player.riichi_status, RiichiStatus.DOUBLE_RIICHI)
        self.assertTrue(player.is_double_riichi)
        self.assertTrue(player.is_ippatsu)

    def test_cancels_ippatsu_without_cancelling_riichi(self) -> None:
        player = PlayerState(Seat.EAST)
        player.establish_riichi(RiichiStatus.RIICHI, ippatsu=True)

        player.cancel_ippatsu()

        self.assertTrue(player.is_riichi_established)
        self.assertFalse(player.is_ippatsu)

    def test_rejects_establishing_riichi_twice(self) -> None:
        player = PlayerState(Seat.EAST)
        player.establish_riichi(RiichiStatus.RIICHI, ippatsu=True)

        with self.assertRaises(ValueError):
            player.establish_riichi(RiichiStatus.RIICHI, ippatsu=False)

    def test_rejects_an_established_status_of_none(self) -> None:
        player = PlayerState(Seat.EAST)

        with self.assertRaises(ValueError):
            player.establish_riichi(RiichiStatus.NONE, ippatsu=False)
        with self.assertRaises(TypeError):
            player.establish_riichi("riichi", ippatsu=False)

    def test_records_a_missed_ron_as_temporary_furiten(self) -> None:
        player = PlayerState(Seat.EAST)

        player.record_missed_ron()

        self.assertIs(player.missed_ron_furiten, FuritenReason.TEMPORARY)
        self.assertTrue(player.is_temporary_furiten)
        self.assertTrue(player.is_furiten)

    def test_records_a_missed_ron_after_riichi_for_the_whole_round(self) -> None:
        player = PlayerState(Seat.EAST)
        player.establish_riichi(RiichiStatus.RIICHI, ippatsu=False)

        player.record_missed_ron()

        self.assertIs(player.missed_ron_furiten, FuritenReason.RIICHI)
        self.assertTrue(player.is_riichi_furiten)

    def test_clears_only_the_temporary_missed_ron_furiten(self) -> None:
        temporary = PlayerState(Seat.EAST)
        temporary.record_missed_ron()
        riichi = PlayerState(Seat.SOUTH)
        riichi.establish_riichi(RiichiStatus.RIICHI, ippatsu=False)
        riichi.record_missed_ron()

        temporary.clear_temporary_furiten()
        riichi.clear_temporary_furiten()

        self.assertIsNone(temporary.missed_ron_furiten)
        self.assertIs(riichi.missed_ron_furiten, FuritenReason.RIICHI)

    def test_discard_furiten_is_derived_from_the_river(self) -> None:
        hand = _tiles(
            "2m",
            "3m",
            "4m",
            "5m",
            "6m",
            "7m",
            "2p",
            "3p",
            "4p",
            "5p",
            "6p",
            "2s",
            "2s",
        )
        player = PlayerState(
            Seat.EAST,
            hand,
            discards=(Discard(_tiles("7p")[0], is_tsumogiri=False),),
        )

        self.assertIn(_tile_type("7p"), player.winning_tile_types)
        self.assertEqual(player.furiten_reasons, frozenset({FuritenReason.DISCARD}))

    def test_rejects_inconsistent_riichi_state(self) -> None:
        with self.assertRaises(ValueError):
            PlayerState(Seat.EAST, is_ippatsu=True)
        with self.assertRaises(ValueError):
            PlayerState(Seat.EAST, missed_ron_furiten=FuritenReason.RIICHI)
        with self.assertRaises(ValueError):
            PlayerState(Seat.EAST, missed_ron_furiten=FuritenReason.DISCARD)
        with self.assertRaises(TypeError):
            PlayerState(Seat.EAST, riichi_status="riichi")
        with self.assertRaises(TypeError):
            PlayerState(Seat.EAST, is_ippatsu="yes")

    def test_copy_keeps_the_round_state(self) -> None:
        player = PlayerState(Seat.EAST, _tiles("1m", "2m"))
        player.establish_riichi(RiichiStatus.DOUBLE_RIICHI, ippatsu=True)
        player.record_missed_ron()

        copied = player.copy()

        self.assertIs(copied.riichi_status, RiichiStatus.DOUBLE_RIICHI)
        self.assertTrue(copied.is_ippatsu)
        self.assertIs(copied.missed_ron_furiten, FuritenReason.RIICHI)

    def test_copy_is_independent_of_the_original(self) -> None:
        player = PlayerState(Seat.EAST, _tiles("1m", "2m"))

        copied = player.copy()
        copied.establish_riichi(RiichiStatus.RIICHI, ippatsu=True)
        copied.add_tile(_tiles("9s")[0])

        self.assertFalse(player.is_riichi_established)
        self.assertEqual(len(player.hand_tiles), 2)


class PlayerStateCallTest(unittest.TestCase):
    def _pon_hand(self) -> tuple[PlayerState, tuple[Tile, ...]]:
        pon_tiles = _tiles("5s", "5s", "5s", "5s")
        player = PlayerState(Seat.EAST, (*pon_tiles[1:], *_tiles("1m", "2m", "3m")))
        return player, pon_tiles

    def test_call_pon_moves_the_consumed_tiles_into_the_meld(self) -> None:
        player, pon_tiles = self._pon_hand()

        pon = player.call_pon(
            pon_tiles[0],
            (pon_tiles[1].id, pon_tiles[2].id),
            Seat.NORTH,
        )

        self.assertEqual(pon.tiles, (pon_tiles[0], pon_tiles[1], pon_tiles[2]))
        self.assertIs(pon.source_seat, Seat.NORTH)
        self.assertNotIn(pon_tiles[1].id, {tile.id for tile in player.hand_tiles})
        self.assertFalse(player.is_menzen)

    def test_call_chi_and_daiminkan_move_ownership(self) -> None:
        chi_tiles = _tiles("3m", "4m", "5m")
        chi_player = PlayerState(Seat.EAST, chi_tiles[1:])
        kan_tiles = _tiles("5s", "5s", "5s", "5s")
        kan_player = PlayerState(Seat.EAST, kan_tiles[1:])

        chi = chi_player.call_chi(
            chi_tiles[0],
            (chi_tiles[1].id, chi_tiles[2].id),
            Seat.NORTH,
        )
        daiminkan = kan_player.call_daiminkan(
            kan_tiles[0],
            tuple(tile.id for tile in kan_tiles[1:]),
            Seat.NORTH,
        )

        self.assertEqual(chi_player.hand_tiles, ())
        self.assertEqual(chi_player.melds, (chi,))
        self.assertEqual(kan_player.hand_tiles, ())
        self.assertEqual(kan_player.melds, (daiminkan,))

    def test_declare_ankan_keeps_the_hand_closed(self) -> None:
        quad = _tiles("5s", "5s", "5s", "5s")
        player = PlayerState(Seat.EAST, quad)

        ankan = player.declare_ankan(tuple(tile.id for tile in quad))

        self.assertEqual(player.melds, (ankan,))
        self.assertEqual(player.hand_tiles, ())
        self.assertTrue(player.is_menzen)

    def test_declare_kakan_replaces_the_pon_in_place(self) -> None:
        quad = _tiles("5s", "5s", "5s", "5s")
        chi_tiles = _tiles("3m", "4m", "5m")
        pon = Pon(quad[0], quad[1:3], Seat.NORTH)
        chi = Chi(chi_tiles[0], chi_tiles[1:], Seat.NORTH)
        player = PlayerState(Seat.EAST, (quad[3],), melds=(pon, chi))

        kakan = player.declare_kakan(quad[3].id)

        self.assertEqual(player.melds, (kakan, chi))
        self.assertIs(kakan.pon, pon)
        self.assertEqual(kakan.added_tile, quad[3])
        self.assertEqual(player.hand_tiles, ())

    def test_declare_kakan_requires_a_matching_pon(self) -> None:
        player = PlayerState(Seat.EAST, _tiles("5s"))

        with self.assertRaises(ValueError):
            player.declare_kakan(player.hand_tiles[0].id)

    def test_a_failed_call_leaves_the_hand_untouched(self) -> None:
        player, pon_tiles = self._pon_hand()
        original_hand = player.hand_tiles

        with self.assertRaises(ValueError):
            player.call_pon(
                pon_tiles[0],
                (pon_tiles[1].id, _tiles("9p")[0].id),
                Seat.NORTH,
            )

        self.assertEqual(player.hand_tiles, original_hand)
        self.assertEqual(player.melds, ())

    def test_a_call_rejects_duplicate_consumed_tile_ids(self) -> None:
        player, pon_tiles = self._pon_hand()

        with self.assertRaises(ValueError):
            player.call_pon(
                pon_tiles[0],
                (pon_tiles[1].id, pon_tiles[1].id),
                Seat.NORTH,
            )

        self.assertEqual(player.melds, ())

    def test_calls_keep_the_round_state(self) -> None:
        player, pon_tiles = self._pon_hand()
        player.record_missed_ron()

        player.call_pon(pon_tiles[0], (pon_tiles[1].id, pon_tiles[2].id), Seat.NORTH)

        self.assertIs(player.missed_ron_furiten, FuritenReason.TEMPORARY)


if __name__ == "__main__":
    unittest.main()
