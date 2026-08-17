import unittest
from dataclasses import FrozenInstanceError, replace

from lisjong_engine.dora import DoraIndicators
from lisjong_engine.points import SeatPoints
from lisjong_engine.riichi_event import RiichiContribution
from lisjong_engine.round_result import (
    WinningPlayerResult,
    WinResult,
)
from lisjong_engine.rules import RuleSet
from lisjong_engine.seat import Seat
from lisjong_engine.settlement import (
    RiichiStickAward,
    RoundSettlement,
    SettlementTransfer,
    TransferReason,
    aggregate_settlement_transfers,
    calculate_single_win_settlement_transfers,
)
from lisjong_engine.tile import STANDARD_TILES
from lisjong_engine.win_context import (
    WinMethod,
    WinningContext,
    WinOrigin,
)
from lisjong_engine.wind import Wind
from lisjong_engine.winning_score import evaluate_winning_scores


def _seat_wind(seat: Seat, dealer_seat: Seat) -> Wind:
    seats = tuple(Seat)
    distance = (seats.index(seat) - seats.index(dealer_seat)) % len(seats)
    return tuple(Wind)[distance]


def _winning_player(
    seat: Seat,
    *,
    method: WinMethod,
    dealer_seat: Seat = Seat.EAST,
    seat_wind: Wind | None = None,
    rules: RuleSet | None = None,
) -> WinningPlayerResult:
    concealed_tiles = tuple(
        STANDARD_TILES[tile_type_id * 4 + copy_index]
        for tile_type_id in (0, 3, 6, 10, 14, 16, 20)
        for copy_index in range(2)
    )
    winning_tile = concealed_tiles[-1]

    context = WinningContext(
        concealed_tiles=concealed_tiles,
        winning_tile=winning_tile,
        method=method,
        origin=(WinOrigin.DISCARD if method is WinMethod.RON else WinOrigin.LIVE_WALL),
        seat_wind=(_seat_wind(seat, dealer_seat) if seat_wind is None else seat_wind),
        prevailing_wind=Wind.EAST,
    )

    return WinningPlayerResult(
        seat=seat,
        context=context,
        score_selection=evaluate_winning_scores(
            context,
            dora_indicators=DoraIndicators(),
            rules=rules,
        ),
    )


def _win_result(
    winner_seat: Seat,
    *,
    method: WinMethod,
    dealer_seat: Seat = Seat.EAST,
    source_seat: Seat | None = None,
    seat_wind: Wind | None = None,
    rules: RuleSet | None = None,
) -> WinResult:
    winner = _winning_player(
        winner_seat,
        method=method,
        dealer_seat=dealer_seat,
        seat_wind=seat_wind,
        rules=rules,
    )

    return WinResult(
        method=method,
        origin=(WinOrigin.DISCARD if method is WinMethod.RON else WinOrigin.LIVE_WALL),
        winning_tile=winner.context.winning_tile,
        winners=(winner,),
        dora_indicators=DoraIndicators(),
        source_seat=source_seat,
    )


class SingleWinSettlementTest(unittest.TestCase):
    def test_child_ron_and_honba(self) -> None:
        result = _win_result(
            Seat.SOUTH,
            method=WinMethod.RON,
            source_seat=Seat.EAST,
        )

        transfers = calculate_single_win_settlement_transfers(
            result,
            dealer_seat=Seat.EAST,
            honba=2,
        )

        self.assertEqual(
            transfers,
            (
                SettlementTransfer(
                    Seat.EAST,
                    Seat.SOUTH,
                    1_600,
                    TransferReason.RON,
                    Seat.SOUTH,
                ),
                SettlementTransfer(
                    Seat.EAST,
                    Seat.SOUTH,
                    600,
                    TransferReason.HONBA,
                    Seat.SOUTH,
                ),
            ),
        )
        self.assertEqual(
            aggregate_settlement_transfers(transfers),
            SeatPoints(-2_200, 2_200, 0, 0),
        )

    def test_dealer_ron_and_honba(self) -> None:
        result = _win_result(
            Seat.EAST,
            method=WinMethod.RON,
            source_seat=Seat.SOUTH,
        )

        transfers = calculate_single_win_settlement_transfers(
            result,
            dealer_seat=Seat.EAST,
            honba=1,
        )

        self.assertEqual(
            aggregate_settlement_transfers(transfers),
            SeatPoints(2_700, -2_700, 0, 0),
        )
        self.assertEqual(
            tuple(transfer.amount for transfer in transfers),
            (2_400, 300),
        )

    def test_child_tsumo_and_honba(self) -> None:
        result = _win_result(
            Seat.SOUTH,
            method=WinMethod.TSUMO,
        )

        transfers = calculate_single_win_settlement_transfers(
            result,
            dealer_seat=Seat.EAST,
            honba=2,
        )

        self.assertEqual(
            aggregate_settlement_transfers(transfers),
            SeatPoints(-1_800, 3_800, -1_000, -1_000),
        )
        self.assertEqual(
            tuple(
                (
                    transfer.payer,
                    transfer.amount,
                    transfer.reason,
                )
                for transfer in transfers
            ),
            (
                (Seat.EAST, 1_600, TransferReason.TSUMO),
                (Seat.EAST, 200, TransferReason.HONBA),
                (Seat.WEST, 800, TransferReason.TSUMO),
                (Seat.WEST, 200, TransferReason.HONBA),
                (Seat.NORTH, 800, TransferReason.TSUMO),
                (Seat.NORTH, 200, TransferReason.HONBA),
            ),
        )

    def test_dealer_tsumo_and_honba(self) -> None:
        result = _win_result(
            Seat.EAST,
            method=WinMethod.TSUMO,
        )

        transfers = calculate_single_win_settlement_transfers(
            result,
            dealer_seat=Seat.EAST,
            honba=1,
        )

        self.assertEqual(
            aggregate_settlement_transfers(transfers),
            SeatPoints(5_100, -1_700, -1_700, -1_700),
        )

    def test_transfer_aggregation_is_zero_sum(self) -> None:
        result = _win_result(
            Seat.SOUTH,
            method=WinMethod.TSUMO,
        )

        transfers = calculate_single_win_settlement_transfers(
            result,
            dealer_seat=Seat.EAST,
            honba=3,
        )

        self.assertEqual(
            aggregate_settlement_transfers(transfers).total,
            0,
        )

    def test_rejects_score_candidates_evaluated_with_other_rules(self) -> None:
        result = _win_result(
            Seat.SOUTH,
            method=WinMethod.RON,
            source_seat=Seat.EAST,
        )
        other_rules = replace(
            RuleSet.default(),
            ron_honba_points=400,
        )

        with self.assertRaisesRegex(
            ValueError,
            "evaluated with settlement rules",
        ):
            calculate_single_win_settlement_transfers(
                result,
                dealer_seat=Seat.EAST,
                rules=other_rules,
            )

    def test_rejects_dealer_seat_inconsistent_with_context(self) -> None:
        result = _win_result(
            Seat.WEST,
            method=WinMethod.RON,
            source_seat=Seat.EAST,
            seat_wind=Wind.SOUTH,
        )

        with self.assertRaisesRegex(ValueError, "seat_wind"):
            calculate_single_win_settlement_transfers(
                result,
                dealer_seat=Seat.EAST,
            )

    def test_rejects_invalid_inputs(self) -> None:
        result = _win_result(
            Seat.SOUTH,
            method=WinMethod.RON,
            source_seat=Seat.EAST,
        )

        cases = (
            (("result",), {"dealer_seat": Seat.EAST}, TypeError),
            ((result,), {"dealer_seat": "east"}, TypeError),
            ((result,), {"dealer_seat": Seat.EAST, "honba": True}, TypeError),
            ((result,), {"dealer_seat": Seat.EAST, "honba": -1}, ValueError),
            (
                (result,),
                {"dealer_seat": Seat.EAST, "rules": "rules"},
                TypeError,
            ),
        )

        for arguments, keywords, error in cases:
            with self.subTest(
                arguments=arguments,
                keywords=keywords,
            ):
                with self.assertRaises(error):
                    calculate_single_win_settlement_transfers(
                        *arguments,
                        **keywords,
                    )


if __name__ == "__main__":
    unittest.main()
