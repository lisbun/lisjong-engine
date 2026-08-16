import unittest

from lisjong_engine.discard import Discard
from lisjong_engine.meld import Pon
from lisjong_engine.player_state import PlayerState
from lisjong_engine.seat import Seat
from lisjong_engine.tile import STANDARD_TILES, Tile, TileCategory, TileType

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


if __name__ == "__main__":
    unittest.main()
