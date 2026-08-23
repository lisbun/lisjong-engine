import unittest
from dataclasses import FrozenInstanceError, fields

from lisjong_engine.action_descriptor import (
    ACTION_DESCRIPTOR_TYPES,
    AnkanActionDescriptor,
    ChiActionDescriptor,
    DaiminkanActionDescriptor,
    DiscardActionDescriptor,
    KakanActionDescriptor,
    NineTerminalsActionDescriptor,
    PassActionDescriptor,
    PonActionDescriptor,
    RiichiActionDescriptor,
    RonActionDescriptor,
    TsumoActionDescriptor,
    is_action_descriptor,
)
from lisjong_engine.public_state import PublicTile
from lisjong_engine.seat import Seat
from lisjong_engine.tile import TileCategory, TileType


def _tile(category: TileCategory, rank: int, *, red: bool = False) -> PublicTile:
    return PublicTile(TileType(category, rank), red)


ONE_MAN = _tile(TileCategory.MANZU, 1)
TWO_MAN = _tile(TileCategory.MANZU, 2)
THREE_MAN = _tile(TileCategory.MANZU, 3)
RED_FIVE_PIN = _tile(TileCategory.PINZU, 5, red=True)


def _all_descriptors():
    return (
        DiscardActionDescriptor(ONE_MAN, False),
        RiichiActionDescriptor(),
        AnkanActionDescriptor((ONE_MAN,) * 4),
        KakanActionDescriptor(ONE_MAN),
        TsumoActionDescriptor(ONE_MAN),
        NineTerminalsActionDescriptor(),
        PassActionDescriptor(ONE_MAN, Seat.EAST),
        RonActionDescriptor(ONE_MAN, Seat.EAST),
        ChiActionDescriptor(THREE_MAN, (TWO_MAN, ONE_MAN), Seat.EAST),
        PonActionDescriptor(RED_FIVE_PIN, (RED_FIVE_PIN, RED_FIVE_PIN), Seat.SOUTH),
        DaiminkanActionDescriptor(ONE_MAN, (ONE_MAN,) * 3, Seat.WEST),
    )


class ActionDescriptorValueTest(unittest.TestCase):
    def test_every_variant_is_frozen_and_recognized(self) -> None:
        descriptors = _all_descriptors()

        self.assertEqual(
            tuple(type(value) for value in descriptors), ACTION_DESCRIPTOR_TYPES
        )
        self.assertTrue(all(is_action_descriptor(value) for value in descriptors))
        for descriptor in descriptors:
            with self.subTest(descriptor_type=type(descriptor).__name__):
                with self.assertRaises(FrozenInstanceError):
                    descriptor.extra = object()

    def test_descriptors_expose_no_internal_identity_or_provenance_fields(self) -> None:
        forbidden = {
            "action_id",
            "tile_id",
            "tile_ids",
            "target_tile_id",
            "consumed_tile_ids",
            "match_seed",
            "round_seed",
            "random_provenance",
            "round_state",
            "match_state",
        }

        for descriptor_type in ACTION_DESCRIPTOR_TYPES:
            with self.subTest(descriptor_type=descriptor_type.__name__):
                self.assertTrue(
                    forbidden.isdisjoint(
                        field.name for field in fields(descriptor_type)
                    )
                )

    def test_consumed_tiles_are_normalized_by_public_meaning(self) -> None:
        descriptor = ChiActionDescriptor(
            THREE_MAN,
            (TWO_MAN, ONE_MAN),
            Seat.NORTH,
        )

        self.assertEqual(descriptor.consumed_tiles, (ONE_MAN, TWO_MAN))

    def test_red_and_non_red_tiles_remain_distinct(self) -> None:
        normal = _tile(TileCategory.PINZU, 5)

        self.assertNotEqual(
            DiscardActionDescriptor(normal, False),
            DiscardActionDescriptor(RED_FIVE_PIN, False),
        )

    def test_discard_public_flags_remain_distinct(self) -> None:
        self.assertNotEqual(
            DiscardActionDescriptor(ONE_MAN, False),
            DiscardActionDescriptor(ONE_MAN, True),
        )


class RiichiActionDescriptorTest(unittest.TestCase):
    def test_carries_no_declaration_tile(self) -> None:
        """立直choiceは宣言牌を持たない。宣言牌は別decisionで選ぶ。"""
        self.assertEqual(fields(RiichiActionDescriptor), ())
        self.assertEqual(RiichiActionDescriptor(), RiichiActionDescriptor())

    def test_riichi_discard_descriptor_is_not_part_of_the_contract(self) -> None:
        """宣言牌と結合したdescriptorはcanonical contractへ残さない。"""
        import lisjong_engine.action_descriptor as module

        self.assertFalse(hasattr(module, "RiichiDiscardActionDescriptor"))
        self.assertTrue(
            all(
                descriptor_type.__name__ != "RiichiDiscardActionDescriptor"
                for descriptor_type in ACTION_DESCRIPTOR_TYPES
            )
        )


if __name__ == "__main__":
    unittest.main()
