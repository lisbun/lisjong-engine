import unittest
from dataclasses import FrozenInstanceError, fields, replace

from lisjong_engine.observation import ObservationDecisionKind, SeatObservation
from lisjong_engine.public_state import (
    PublicTile,
    SeatDiscards,
    SeatMelds,
    SeatRiichiState,
    SeatScore,
)
from lisjong_engine.seat import Seat
from lisjong_engine.tile import TileCategory, TileType
from lisjong_engine.wind import Wind


def _observation(**overrides) -> SeatObservation:
    tile = PublicTile(TileType(TileCategory.MANZU, 1))
    values = {
        "viewer_seat": Seat.EAST,
        "decision_kind": ObservationDecisionKind.TURN,
        "hand_number": 1,
        "honba": 0,
        "riichi_sticks": 0,
        "hand_tiles": [tile],
        "discards": [SeatDiscards(seat, ()) for seat in Seat],
        "melds": [SeatMelds(seat, ()) for seat in Seat],
        "dora_indicators": [tile],
        "remaining_live_wall_count": 17,
        "scores": [SeatScore(seat, 25_000) for seat in Seat],
        "dealer_seat": Seat.EAST,
        "prevailing_wind": Wind.EAST,
        "riichi_states": [SeatRiichiState(seat, False) for seat in Seat],
    }
    values.update(overrides)
    return SeatObservation(**values)


class ObservationDecisionKindTest(unittest.TestCase):
    def test_has_only_the_four_decision_kinds(self) -> None:
        self.assertEqual(
            {kind.value for kind in ObservationDecisionKind},
            {"turn", "discard_reaction", "kakan_reaction", "ankan_reaction"},
        )


class SeatObservationTest(unittest.TestCase):
    def test_keeps_fields_as_immutable_copied_tuples(self) -> None:
        observation = _observation()

        for name in (
            "hand_tiles",
            "discards",
            "melds",
            "dora_indicators",
            "scores",
            "riichi_states",
        ):
            self.assertIsInstance(getattr(observation, name), tuple)
        with self.assertRaises(FrozenInstanceError):
            observation.honba = 1

    def test_four_seat_fields_require_exact_seat_order(self) -> None:
        valid = _observation()
        for field_name in ("discards", "melds", "scores", "riichi_states"):
            values = list(getattr(valid, field_name))
            with self.subTest(field_name=field_name, case="missing"):
                with self.assertRaises(ValueError):
                    replace(valid, **{field_name: values[:-1]})
            values[1], values[2] = values[2], values[1]
            with self.subTest(field_name=field_name, case="order"):
                with self.assertRaises(ValueError):
                    replace(valid, **{field_name: values})
            values = [values[0]] * 4
            with self.subTest(field_name=field_name, case="duplicate"):
                with self.assertRaises(ValueError):
                    replace(valid, **{field_name: values})

    def test_rejects_invalid_scalar_values(self) -> None:
        cases = (
            ("viewer_seat", "east", TypeError),
            ("decision_kind", "turn", TypeError),
            ("hand_number", 0, ValueError),
            ("hand_number", True, TypeError),
            ("honba", -1, ValueError),
            ("riichi_sticks", -1, ValueError),
            ("remaining_live_wall_count", -1, ValueError),
            ("dealer_seat", "east", TypeError),
            ("prevailing_wind", "east", TypeError),
        )
        valid = _observation()
        for field_name, value, error in cases:
            with self.subTest(field_name=field_name, value=value):
                with self.assertRaises(error):
                    replace(valid, **{field_name: value})

    def test_has_no_action_or_internal_state_fields(self) -> None:
        field_names = {field.name for field in fields(SeatObservation)}
        forbidden = {
            "action_id",
            "action_options",
            "legal_actions",
            "legal_action_snapshot",
            "match_state",
            "round_state",
            "seed",
            "provenance",
        }
        self.assertTrue(field_names.isdisjoint(forbidden))


if __name__ == "__main__":
    unittest.main()
