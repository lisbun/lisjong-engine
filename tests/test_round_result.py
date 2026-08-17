import unittest
from dataclasses import FrozenInstanceError, fields

from lisjong_engine.dora import DoraIndicators
from lisjong_engine.round_result import (
    AbortiveDrawReason,
    AbortiveDrawResult,
    ExhaustiveDrawResult,
    WinningPlayerResult,
    WinResult,
)
from lisjong_engine.seat import Seat
from lisjong_engine.tile import STANDARD_TILES, Tile, TileCategory, TileType
from lisjong_engine.win_context import WinMethod, WinningContext, WinOrigin
from lisjong_engine.wind import Wind
from lisjong_engine.winning_score import evaluate_winning_scores

_CATEGORIES = {
    "m": TileCategory.MANZU,
    "p": TileCategory.PINZU,
    "s": TileCategory.SOUZU,
    "z": TileCategory.HONOR,
}

_RYANPEIKOU_NAMES = (
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


def _tiles(*names: str) -> tuple[Tile, ...]:
    copy_counts: dict[TileType, int] = {}
    tiles = []
    for name in names:
        tile_type = TileType(_CATEGORIES[name[-1]], int(name[:-1]))
        copy_index = copy_counts.get(tile_type, 0)
        tiles.append(STANDARD_TILES[tile_type.id * 4 + copy_index])
        copy_counts[tile_type] = copy_index + 1
    return tuple(tiles)


def _winning_player(
    seat: Seat,
    *,
    method: WinMethod = WinMethod.RON,
    seat_wind: Wind = Wind.SOUTH,
    is_last_tile: bool = False,
) -> WinningPlayerResult:
    tiles = _tiles(*_RYANPEIKOU_NAMES)
    context = WinningContext(
        concealed_tiles=tiles,
        winning_tile=tiles[-1],
        method=method,
        origin=(WinOrigin.DISCARD if method is WinMethod.RON else WinOrigin.LIVE_WALL),
        seat_wind=seat_wind,
        prevailing_wind=Wind.EAST,
        is_last_tile=is_last_tile,
    )
    return WinningPlayerResult(
        seat=seat,
        context=context,
        score_selection=evaluate_winning_scores(
            context,
            dora_indicators=DoraIndicators(),
        ),
    )


class WinningPlayerResultTest(unittest.TestCase):
    def test_is_immutable_and_does_not_duplicate_yaku_evaluations(self) -> None:
        winner = _winning_player(Seat.SOUTH)

        with self.assertRaises(FrozenInstanceError):
            winner.seat = Seat.WEST

        self.assertEqual(
            {field.name for field in fields(WinningPlayerResult)},
            {"seat", "context", "score_selection"},
        )

    def test_rejects_score_selection_for_a_different_method(self) -> None:
        ron_winner = _winning_player(Seat.SOUTH)
        tsumo_winner = _winning_player(Seat.SOUTH, method=WinMethod.TSUMO)

        with self.assertRaisesRegex(ValueError, "candidate method"):
            WinningPlayerResult(
                Seat.SOUTH,
                tsumo_winner.context,
                ron_winner.score_selection,
            )


class WinResultTest(unittest.TestCase):
    def test_tsumo_result_is_immutable(self) -> None:
        winner = _winning_player(Seat.SOUTH, method=WinMethod.TSUMO)
        dora_indicators = DoraIndicators()
        result = WinResult(
            method=WinMethod.TSUMO,
            origin=WinOrigin.LIVE_WALL,
            winning_tile=winner.context.winning_tile,
            winners=(winner,),
            dora_indicators=dora_indicators,
        )

        with self.assertRaises(FrozenInstanceError):
            result.is_last_tile = True
        self.assertIsNone(result.source_seat)
        self.assertIs(result.dora_indicators, dora_indicators)
        self.assertEqual(
            {field.name for field in fields(result)},
            {
                "method",
                "origin",
                "winning_tile",
                "winners",
                "dora_indicators",
                "source_seat",
                "is_last_tile",
            },
        )

    def test_multiple_ron_winners_are_preserved_in_order(self) -> None:
        south = _winning_player(Seat.SOUTH, seat_wind=Wind.SOUTH)
        west = _winning_player(Seat.WEST, seat_wind=Wind.WEST)
        winners = [south, west]

        result = WinResult(
            method=WinMethod.RON,
            origin=WinOrigin.DISCARD,
            winning_tile=south.context.winning_tile,
            winners=winners,
            source_seat=Seat.EAST,
            dora_indicators=DoraIndicators(),
        )
        winners.clear()

        self.assertEqual(result.winners, (south, west))
        self.assertEqual(result.source_seat, Seat.EAST)

    def test_rejects_inconsistent_terminal_facts(self) -> None:
        winner = _winning_player(Seat.SOUTH)

        with self.assertRaisesRegex(ValueError, "source_seat"):
            WinResult(
                method=WinMethod.RON,
                origin=WinOrigin.DISCARD,
                winning_tile=winner.context.winning_tile,
                winners=(winner,),
                source_seat=Seat.SOUTH,
                dora_indicators=DoraIndicators(),
            )
        with self.assertRaisesRegex(ValueError, "is_last_tile"):
            WinResult(
                method=WinMethod.RON,
                origin=WinOrigin.DISCARD,
                winning_tile=winner.context.winning_tile,
                winners=(winner,),
                source_seat=Seat.EAST,
                dora_indicators=DoraIndicators(),
                is_last_tile=True,
            )


class ExhaustiveDrawResultTest(unittest.TestCase):
    def test_seat_collections_are_immutable_defensive_copies(self) -> None:
        tenpai = [Seat.EAST, Seat.WEST]
        nagashi = [Seat.NORTH]

        result = ExhaustiveDrawResult(tenpai, nagashi)
        tenpai.clear()
        nagashi.clear()

        self.assertEqual(result.tenpai_seats, (Seat.EAST, Seat.WEST))
        self.assertEqual(result.nagashi_mangan_seats, (Seat.NORTH,))
        with self.assertRaises(FrozenInstanceError):
            result.tenpai_seats = ()

    def test_rejects_duplicate_seats(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate"):
            ExhaustiveDrawResult((Seat.EAST, Seat.EAST))


class AbortiveDrawResultTest(unittest.TestCase):
    def test_all_supported_reasons_are_typed_terminal_results(self) -> None:
        expected = {
            AbortiveDrawReason.NINE_TERMINALS,
            AbortiveDrawReason.FOUR_WINDS,
            AbortiveDrawReason.FOUR_KANS,
            AbortiveDrawReason.FOUR_RIICHI,
            AbortiveDrawReason.TRIPLE_RON,
        }

        self.assertEqual(set(AbortiveDrawReason), expected)
        for reason in expected:
            with self.subTest(reason=reason):
                result = AbortiveDrawResult(reason)
                self.assertIs(result.reason, reason)
                with self.assertRaises(FrozenInstanceError):
                    result.reason = AbortiveDrawReason.NINE_TERMINALS

    def test_rejects_untyped_reason(self) -> None:
        with self.assertRaisesRegex(TypeError, "AbortiveDrawReason"):
            AbortiveDrawResult("four_winds")


if __name__ == "__main__":
    unittest.main()
