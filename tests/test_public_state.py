import unittest
from dataclasses import FrozenInstanceError, fields

from lisjong_engine.public_state import (
    PublicDiscard,
    PublicMeld,
    PublicMeldType,
    PublicRiichiStatus,
    PublicTile,
    SeatDiscards,
    SeatMelds,
    SeatRiichiState,
    SeatScore,
)
from lisjong_engine.seat import Seat
from lisjong_engine.tile import TileCategory, TileType


class PublicTileTest(unittest.TestCase):
    def test_keeps_only_tile_type_and_red_information(self) -> None:
        normal = PublicTile(TileType(TileCategory.MANZU, 5))
        red = PublicTile(TileType(TileCategory.MANZU, 5), True)

        self.assertNotEqual(normal, red)
        self.assertEqual(
            {field.name for field in fields(PublicTile)},
            {"tile_type", "is_red"},
        )
        self.assertFalse(hasattr(normal, "id"))
        self.assertFalse(hasattr(normal, "copy_index"))

    def test_is_frozen_and_validates_fields(self) -> None:
        tile = PublicTile(TileType(TileCategory.PINZU, 1))
        with self.assertRaises(FrozenInstanceError):
            tile.is_red = True
        with self.assertRaises(TypeError):
            PublicTile("1p")
        with self.assertRaises(TypeError):
            PublicTile(TileType(TileCategory.PINZU, 5), 1)
        with self.assertRaises(ValueError):
            PublicTile(TileType(TileCategory.HONOR, 5), True)


class PublicDiscardTest(unittest.TestCase):
    def test_validates_every_field(self) -> None:
        tile = PublicTile(TileType(TileCategory.SOUZU, 3))
        discard = PublicDiscard(tile, True, 3, False, Seat.SOUTH)

        self.assertEqual(discard.tile, tile)
        self.assertTrue(discard.is_tsumogiri)
        self.assertEqual(discard.order, 3)
        self.assertIs(discard.called_by, Seat.SOUTH)
        for kwargs in (
            {"tile": object()},
            {"is_tsumogiri": 1},
            {"order": True},
            {"is_riichi_declaration": 0},
            {"called_by": "south"},
        ):
            values = {
                "tile": tile,
                "is_tsumogiri": False,
                "order": 0,
                "is_riichi_declaration": False,
                "called_by": None,
            }
            values.update(kwargs)
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(TypeError):
                    PublicDiscard(**values)
        with self.assertRaises(ValueError):
            PublicDiscard(tile, False, -1, False)


class PublicMeldTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tile = PublicTile(TileType(TileCategory.MANZU, 2))

    def test_open_and_concealed_meld_invariants(self) -> None:
        for meld_type, count in (
            (PublicMeldType.CHI, 3),
            (PublicMeldType.PON, 3),
            (PublicMeldType.DAIMINKAN, 4),
            (PublicMeldType.KAKAN, 4),
        ):
            with self.subTest(meld_type=meld_type):
                meld = PublicMeld(
                    meld_type,
                    [self.tile] * count,
                    Seat.WEST,
                    self.tile,
                )
                self.assertIsInstance(meld.tiles, tuple)
                self.assertIs(meld.from_seat, Seat.WEST)

        ankan = PublicMeld(PublicMeldType.ANKAN, [self.tile] * 4, None, None)
        self.assertIsNone(ankan.from_seat)

        one = PublicTile(TileType(TileCategory.MANZU, 1))
        three = PublicTile(TileType(TileCategory.MANZU, 3))
        chi = PublicMeld(
            PublicMeldType.CHI,
            [three, self.tile, one],
            Seat.WEST,
            self.tile,
        )
        self.assertEqual(chi.tiles, (one, self.tile, three))

    def test_rejects_wrong_count_or_source(self) -> None:
        with self.assertRaises(ValueError):
            PublicMeld(
                PublicMeldType.PON,
                [self.tile] * 4,
                Seat.SOUTH,
                self.tile,
            )
        with self.assertRaises(ValueError):
            PublicMeld(
                PublicMeldType.ANKAN,
                [self.tile] * 4,
                Seat.SOUTH,
                None,
            )
        with self.assertRaises(TypeError):
            PublicMeld(PublicMeldType.CHI, [self.tile] * 3, None, self.tile)
        with self.assertRaises(TypeError):
            PublicMeld("pon", [self.tile] * 3, Seat.SOUTH, self.tile)
        with self.assertRaises(TypeError):
            PublicMeld(
                PublicMeldType.PON,
                [object()] * 3,
                Seat.SOUTH,
                self.tile,
            )
        with self.assertRaises(TypeError):
            PublicMeld(PublicMeldType.PON, [self.tile] * 3, Seat.SOUTH, None)
        with self.assertRaises(ValueError):
            PublicMeld(
                PublicMeldType.ANKAN,
                [self.tile] * 4,
                None,
                self.tile,
            )
        with self.assertRaises(ValueError):
            PublicMeld(
                PublicMeldType.PON,
                [self.tile] * 3,
                Seat.SOUTH,
                PublicTile(TileType(TileCategory.MANZU, 3)),
            )


class SeatPublicStateTest(unittest.TestCase):
    def test_wrappers_copy_normalize_and_validate(self) -> None:
        tile = PublicTile(TileType(TileCategory.PINZU, 3))
        discard = PublicDiscard(tile, False, 0, False)
        meld = PublicMeld(PublicMeldType.PON, [tile] * 3, Seat.EAST, tile)

        self.assertEqual(SeatDiscards(Seat.SOUTH, [discard]).discards, (discard,))
        self.assertEqual(SeatMelds(Seat.SOUTH, [meld]).melds, (meld,))
        self.assertEqual(SeatScore(Seat.SOUTH, -100).points, -100)
        state = SeatRiichiState(Seat.SOUTH, PublicRiichiStatus.ESTABLISHED)
        self.assertIs(state.status, PublicRiichiStatus.ESTABLISHED)
        self.assertTrue(state.is_established)
        self.assertFalse(
            SeatRiichiState(Seat.SOUTH, PublicRiichiStatus.PENDING).is_established
        )
        self.assertEqual(
            {field.name for field in fields(SeatRiichiState)},
            {"seat", "status"},
        )
        self.assertEqual(
            {status.value for status in PublicRiichiStatus},
            {"none", "pending", "established"},
        )

        constructors = (
            lambda: SeatDiscards("south", ()),
            lambda: SeatDiscards(Seat.SOUTH, (object(),)),
            lambda: SeatMelds(Seat.SOUTH, (object(),)),
            lambda: SeatScore(Seat.SOUTH, True),
            lambda: SeatRiichiState(Seat.SOUTH, "established"),
        )
        for constructor in constructors:
            with self.subTest(constructor=constructor):
                with self.assertRaises(TypeError):
                    constructor()


if __name__ == "__main__":
    unittest.main()
