import unittest

from _round_fixtures import take

from lisjong_engine.discard import Discard
from lisjong_engine.draw_resolution import (
    build_exhaustive_draw_result,
    first_discard_abortive_draw,
    four_kans_abortive_draw,
    is_nagashi_mangan_river,
    nine_terminals_eligible,
)
from lisjong_engine.round_result import AbortiveDrawReason, AbortiveDrawResult
from lisjong_engine.seat import Seat
from lisjong_engine.tile import STANDARD_TILES


def _tile(name: str):
    return take(list(STANDARD_TILES), (name,))[0]


class NineTerminalsEligibleTest(unittest.TestCase):
    def test_nine_distinct_terminal_or_honor_types_is_eligible(self) -> None:
        names = (
            "1m",
            "9m",
            "1p",
            "9p",
            "1s",
            "9s",
            "1z",
            "2z",
            "3z",
            "2m",
            "3m",
            "4m",
            "5m",
        )
        hand = take(list(STANDARD_TILES), names)

        self.assertTrue(nine_terminals_eligible(hand))

    def test_eight_distinct_types_is_not_eligible(self) -> None:
        names = (
            "1m",
            "9m",
            "1p",
            "9p",
            "1s",
            "9s",
            "1z",
            "2z",
            "2m",
            "3m",
            "4m",
            "5m",
            "6m",
        )
        hand = take(list(STANDARD_TILES), names)

        self.assertFalse(nine_terminals_eligible(hand))

    def test_duplicate_terminal_types_do_not_count_twice(self) -> None:
        names = (
            "1m",
            "1m",
            "9m",
            "1p",
            "9p",
            "1s",
            "9s",
            "1z",
            "2z",
            "2m",
            "3m",
            "4m",
            "5m",
        )
        hand = take(list(STANDARD_TILES), names)

        self.assertFalse(nine_terminals_eligible(hand))


class FirstDiscardAbortiveDrawTest(unittest.TestCase):
    def _discard_types(self, names: dict[Seat, str]) -> dict[Seat, tuple]:
        return {seat: (_tile(name).tile_type,) for seat, name in names.items()}

    def test_four_matching_wind_first_discards_is_four_winds(self) -> None:
        result = first_discard_abortive_draw(
            four_winds_enabled=True,
            four_riichi_enabled=True,
            has_meld_occurred=False,
            discard_tile_types_by_seat=self._discard_types(
                {seat: "1z" for seat in Seat}
            ),
            riichi_established_by_seat={seat: False for seat in Seat},
        )

        self.assertEqual(result, AbortiveDrawResult(AbortiveDrawReason.FOUR_WINDS))

    def test_three_matching_first_discards_does_not_trigger(self) -> None:
        types = self._discard_types(
            {Seat.EAST: "1z", Seat.SOUTH: "1z", Seat.WEST: "1z"}
        )
        types[Seat.NORTH] = (_tile("2z").tile_type,)

        result = first_discard_abortive_draw(
            four_winds_enabled=True,
            four_riichi_enabled=True,
            has_meld_occurred=False,
            discard_tile_types_by_seat=types,
            riichi_established_by_seat={seat: False for seat in Seat},
        )

        self.assertIsNone(result)

    def test_matching_non_wind_first_discards_does_not_trigger(self) -> None:
        result = first_discard_abortive_draw(
            four_winds_enabled=True,
            four_riichi_enabled=True,
            has_meld_occurred=False,
            discard_tile_types_by_seat=self._discard_types(
                {seat: "5m" for seat in Seat}
            ),
            riichi_established_by_seat={seat: False for seat in Seat},
        )

        self.assertIsNone(result)

    def test_meld_before_matching_discards_prevents_four_winds(self) -> None:
        result = first_discard_abortive_draw(
            four_winds_enabled=True,
            four_riichi_enabled=True,
            has_meld_occurred=True,
            discard_tile_types_by_seat=self._discard_types(
                {seat: "1z" for seat in Seat}
            ),
            riichi_established_by_seat={seat: False for seat in Seat},
        )

        self.assertIsNone(result)

    def test_disabled_four_winds_rule_does_not_trigger(self) -> None:
        result = first_discard_abortive_draw(
            four_winds_enabled=False,
            four_riichi_enabled=True,
            has_meld_occurred=False,
            discard_tile_types_by_seat=self._discard_types(
                {seat: "1z" for seat in Seat}
            ),
            riichi_established_by_seat={seat: False for seat in Seat},
        )

        self.assertIsNone(result)

    def test_four_established_riichi_is_four_riichi(self) -> None:
        result = first_discard_abortive_draw(
            four_winds_enabled=True,
            four_riichi_enabled=True,
            has_meld_occurred=False,
            discard_tile_types_by_seat={},
            riichi_established_by_seat={seat: True for seat in Seat},
        )

        self.assertEqual(result, AbortiveDrawResult(AbortiveDrawReason.FOUR_RIICHI))

    def test_three_established_riichi_does_not_trigger(self) -> None:
        established = {seat: True for seat in Seat}
        established[Seat.NORTH] = False

        result = first_discard_abortive_draw(
            four_winds_enabled=True,
            four_riichi_enabled=True,
            has_meld_occurred=False,
            discard_tile_types_by_seat={},
            riichi_established_by_seat=established,
        )

        self.assertIsNone(result)

    def test_disabled_four_riichi_rule_does_not_trigger(self) -> None:
        result = first_discard_abortive_draw(
            four_winds_enabled=True,
            four_riichi_enabled=False,
            has_meld_occurred=False,
            discard_tile_types_by_seat={},
            riichi_established_by_seat={seat: True for seat in Seat},
        )

        self.assertIsNone(result)

    def test_four_winds_is_checked_before_four_riichi(self) -> None:
        """python-studyの既存契約どおり、四風連打を四家立直より先に判定する。"""
        result = first_discard_abortive_draw(
            four_winds_enabled=True,
            four_riichi_enabled=True,
            has_meld_occurred=False,
            discard_tile_types_by_seat=self._discard_types(
                {seat: "1z" for seat in Seat}
            ),
            riichi_established_by_seat={seat: True for seat in Seat},
        )

        self.assertEqual(result, AbortiveDrawResult(AbortiveDrawReason.FOUR_WINDS))


class FourKansAbortiveDrawTest(unittest.TestCase):
    def test_four_kans_across_multiple_owners_is_abortive(self) -> None:
        result = four_kans_abortive_draw(
            enabled=True,
            quad_counts_by_seat={
                Seat.EAST: 2,
                Seat.SOUTH: 2,
                Seat.WEST: 0,
                Seat.NORTH: 0,
            },
        )

        self.assertEqual(result, AbortiveDrawResult(AbortiveDrawReason.FOUR_KANS))

    def test_four_kans_by_one_owner_is_not_abortive(self) -> None:
        result = four_kans_abortive_draw(
            enabled=True,
            quad_counts_by_seat={
                Seat.EAST: 4,
                Seat.SOUTH: 0,
                Seat.WEST: 0,
                Seat.NORTH: 0,
            },
        )

        self.assertIsNone(result)

    def test_fewer_than_four_kans_is_not_abortive(self) -> None:
        result = four_kans_abortive_draw(
            enabled=True,
            quad_counts_by_seat={
                Seat.EAST: 1,
                Seat.SOUTH: 1,
                Seat.WEST: 0,
                Seat.NORTH: 0,
            },
        )

        self.assertIsNone(result)

    def test_disabled_rule_does_not_trigger(self) -> None:
        result = four_kans_abortive_draw(
            enabled=False,
            quad_counts_by_seat={
                Seat.EAST: 2,
                Seat.SOUTH: 2,
                Seat.WEST: 0,
                Seat.NORTH: 0,
            },
        )

        self.assertIsNone(result)


class NagashiManganRiverTest(unittest.TestCase):
    def test_all_terminal_or_honor_uncalled_river_is_nagashi(self) -> None:
        discards = (
            Discard(_tile("1m"), True),
            Discard(_tile("9p"), True),
            Discard(_tile("1z"), True),
        )

        self.assertTrue(is_nagashi_mangan_river(discards))

    def test_empty_river_is_not_nagashi(self) -> None:
        self.assertFalse(is_nagashi_mangan_river(()))

    def test_simple_tile_disqualifies(self) -> None:
        discards = (
            Discard(_tile("1m"), True),
            Discard(_tile("5p"), True),
        )

        self.assertFalse(is_nagashi_mangan_river(discards))

    def test_called_discard_disqualifies(self) -> None:
        discards = (
            Discard(_tile("1m"), True),
            Discard(_tile("9p"), True, called_by=Seat.SOUTH),
        )

        self.assertFalse(is_nagashi_mangan_river(discards))


class BuildExhaustiveDrawResultTest(unittest.TestCase):
    def test_combines_tenpai_and_nagashi_facts(self) -> None:
        nagashi_river = (Discard(_tile("1m"), True),)
        non_nagashi_river = (Discard(_tile("5p"), True),)

        result = build_exhaustive_draw_result(
            tenpai_by_seat={
                Seat.EAST: True,
                Seat.SOUTH: False,
                Seat.WEST: True,
                Seat.NORTH: False,
            },
            discards_by_seat={
                Seat.EAST: nagashi_river,
                Seat.SOUTH: non_nagashi_river,
                Seat.WEST: (),
                Seat.NORTH: nagashi_river,
            },
            nagashi_mangan_enabled=True,
        )

        self.assertEqual(result.tenpai_seats, (Seat.EAST, Seat.WEST))
        self.assertEqual(result.nagashi_mangan_seats, (Seat.EAST, Seat.NORTH))

    def test_disabled_nagashi_mangan_rule_yields_no_nagashi_seats(self) -> None:
        nagashi_river = (Discard(_tile("1m"), True),)

        result = build_exhaustive_draw_result(
            tenpai_by_seat={seat: False for seat in Seat},
            discards_by_seat={seat: nagashi_river for seat in Seat},
            nagashi_mangan_enabled=False,
        )

        self.assertEqual(result.nagashi_mangan_seats, ())


if __name__ == "__main__":
    unittest.main()
