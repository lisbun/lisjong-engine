import unittest
from dataclasses import replace

from lisjong_engine.dora import DoraIndicators
from lisjong_engine.meld import Ankan, Daiminkan, Kakan, Pon
from lisjong_engine.points import SeatPoints
from lisjong_engine.round_result import WinningPlayerResult, WinResult
from lisjong_engine.rules import PaoCompoundYakumanPolicy, RuleSet
from lisjong_engine.seat import Seat
from lisjong_engine.settlement import (
    SettlementTransfer,
    TransferReason,
    aggregate_settlement_transfers,
    calculate_win_settlement_transfers,
)
from lisjong_engine.tile import STANDARD_TILES, Tile, TileCategory, TileType
from lisjong_engine.win_context import WinMethod, WinningContext, WinOrigin
from lisjong_engine.wind import Wind
from lisjong_engine.winning_score import evaluate_winning_scores
from lisjong_engine.yaku import Yaku

_CATEGORIES = {
    "m": TileCategory.MANZU,
    "p": TileCategory.PINZU,
    "s": TileCategory.SOUZU,
    "z": TileCategory.HONOR,
}


def _tile_type(name: str) -> TileType:
    return TileType(_CATEGORIES[name[-1]], int(name[:-1]))


class _TilePool:
    def __init__(self) -> None:
        self._copy_counts: dict[TileType, int] = {}

    def take(self, *names: str) -> tuple[Tile, ...]:
        tiles = []
        for name in names:
            tile_type = _tile_type(name)
            copy_index = self._copy_counts.get(tile_type, 0)
            if copy_index >= 4:
                raise ValueError("test fixture requests a fifth tile")
            tiles.append(STANDARD_TILES[tile_type.id * 4 + copy_index])
            self._copy_counts[tile_type] = copy_index + 1
        return tuple(tiles)


def _pon(pool: _TilePool, name: str, source_seat: Seat) -> Pon:
    tiles = pool.take(name, name, name)
    return Pon(tiles[0], tiles[1:], source_seat)


def _ankan(pool: _TilePool, name: str) -> Ankan:
    return Ankan(pool.take(name, name, name, name))


def _daiminkan(pool: _TilePool, name: str, source_seat: Seat) -> Daiminkan:
    tiles = pool.take(name, name, name, name)
    return Daiminkan(tiles[0], tiles[1:], source_seat)


def _kakan(pool: _TilePool, name: str, source_seat: Seat) -> Kakan:
    tiles = pool.take(name, name, name, name)
    return Kakan(Pon(tiles[0], tiles[1:3], source_seat), tiles[3])


def _seat_wind(seat: Seat, dealer_seat: Seat) -> Wind:
    seats = tuple(Seat)
    distance = (seats.index(seat) - seats.index(dealer_seat)) % len(seats)
    return tuple(Wind)[distance]


def _daisangen_context(
    pool: _TilePool,
    *,
    dealer_seat: Seat,
    winner_seat: Seat,
    method: WinMethod,
    origin: WinOrigin,
    last_meld,
    other_source_seat: Seat = Seat.EAST,
) -> WinningContext:
    melds = (
        _pon(pool, "5z", other_source_seat),
        _pon(pool, "6z", other_source_seat),
        last_meld,
    )
    concealed_tiles = pool.take("1m", "1m", "1m", "2p", "2p")
    return WinningContext(
        concealed_tiles=concealed_tiles,
        winning_tile=concealed_tiles[-1],
        method=method,
        origin=origin,
        seat_wind=_seat_wind(winner_seat, dealer_seat),
        prevailing_wind=Wind.EAST,
        declared_melds=melds,
    )


def _compound_daisangen_tsuuiisou_context(
    pool: _TilePool,
    *,
    dealer_seat: Seat,
    winner_seat: Seat,
    method: WinMethod,
    origin: WinOrigin,
    pao_seat: Seat,
) -> WinningContext:
    melds = (
        _pon(pool, "5z", pao_seat),
        _pon(pool, "6z", pao_seat),
        _pon(pool, "7z", pao_seat),
    )
    concealed_tiles = pool.take("1z", "1z", "1z", "2z", "2z")
    return WinningContext(
        concealed_tiles=concealed_tiles,
        winning_tile=concealed_tiles[-1],
        method=method,
        origin=origin,
        seat_wind=_seat_wind(winner_seat, dealer_seat),
        prevailing_wind=Wind.EAST,
        declared_melds=melds,
    )


def _suukantsu_context(
    pool: _TilePool,
    *,
    dealer_seat: Seat,
    winner_seat: Seat,
    method: WinMethod,
    origin: WinOrigin,
    pao_seat: Seat | None,
) -> WinningContext:
    melds = (
        _ankan(pool, "1m"),
        _daiminkan(pool, "2p", Seat.EAST),
        _kakan(pool, "3s", Seat.EAST),
        _daiminkan(pool, "4m", Seat.EAST),
    )
    concealed_tiles = pool.take("5z", "5z")
    return WinningContext(
        concealed_tiles=concealed_tiles,
        winning_tile=concealed_tiles[-1],
        method=method,
        origin=origin,
        seat_wind=_seat_wind(winner_seat, dealer_seat),
        prevailing_wind=Wind.EAST,
        declared_melds=melds,
        suukantsu_pao_seat=pao_seat,
    )


def _winner(
    seat: Seat,
    context: WinningContext,
    *,
    rules: RuleSet,
) -> WinningPlayerResult:
    return WinningPlayerResult(
        seat=seat,
        context=context,
        score_selection=evaluate_winning_scores(
            context,
            dora_indicators=DoraIndicators(),
            rules=rules,
        ),
    )


def _tsumo_result(winner: WinningPlayerResult) -> WinResult:
    return WinResult(
        method=WinMethod.TSUMO,
        origin=WinOrigin.LIVE_WALL,
        winning_tile=winner.context.winning_tile,
        winners=(winner,),
        dora_indicators=DoraIndicators(),
    )


def _ron_result(winner: WinningPlayerResult, source_seat: Seat) -> WinResult:
    return WinResult(
        method=WinMethod.RON,
        origin=WinOrigin.DISCARD,
        winning_tile=winner.context.winning_tile,
        winners=(winner,),
        dora_indicators=DoraIndicators(),
        source_seat=source_seat,
    )


class FullHandPaoSettlementTest(unittest.TestCase):
    def test_daisangen_tsumo_full_hand(self) -> None:
        rules = RuleSet.default()
        pool = _TilePool()
        context = _daisangen_context(
            pool,
            dealer_seat=Seat.EAST,
            winner_seat=Seat.SOUTH,
            method=WinMethod.TSUMO,
            origin=WinOrigin.LIVE_WALL,
            last_meld=_pon(pool, "7z", Seat.NORTH),
        )
        winner = _winner(Seat.SOUTH, context, rules=rules)
        result = _tsumo_result(winner)

        transfers = calculate_win_settlement_transfers(
            result,
            dealer_seat=Seat.EAST,
            rules=rules,
        )

        self.assertEqual(
            transfers,
            (
                SettlementTransfer(
                    Seat.NORTH,
                    Seat.SOUTH,
                    32_000,
                    TransferReason.PAO_TSUMO,
                    Seat.SOUTH,
                ),
            ),
        )
        self.assertEqual(
            aggregate_settlement_transfers(transfers),
            SeatPoints(0, 32_000, 0, -32_000),
        )

    def test_daisangen_ron_third_party_pao_splits_with_discarder(self) -> None:
        rules = RuleSet.default()
        pool = _TilePool()
        context = _daisangen_context(
            pool,
            dealer_seat=Seat.EAST,
            winner_seat=Seat.SOUTH,
            method=WinMethod.RON,
            origin=WinOrigin.DISCARD,
            last_meld=_pon(pool, "7z", Seat.NORTH),
        )
        winner = _winner(Seat.SOUTH, context, rules=rules)
        result = _ron_result(winner, Seat.WEST)

        transfers = calculate_win_settlement_transfers(
            result,
            dealer_seat=Seat.EAST,
            rules=rules,
        )

        self.assertEqual(
            transfers,
            (
                SettlementTransfer(
                    Seat.WEST,
                    Seat.SOUTH,
                    16_000,
                    TransferReason.RON,
                    Seat.SOUTH,
                ),
                SettlementTransfer(
                    Seat.NORTH,
                    Seat.SOUTH,
                    16_000,
                    TransferReason.PAO_RON,
                    Seat.SOUTH,
                ),
            ),
        )

    def test_daisangen_ron_discarder_is_pao_payer(self) -> None:
        rules = RuleSet.default()
        pool = _TilePool()
        context = _daisangen_context(
            pool,
            dealer_seat=Seat.EAST,
            winner_seat=Seat.SOUTH,
            method=WinMethod.RON,
            origin=WinOrigin.DISCARD,
            last_meld=_pon(pool, "7z", Seat.NORTH),
        )
        winner = _winner(Seat.SOUTH, context, rules=rules)
        result = _ron_result(winner, Seat.NORTH)

        transfers = calculate_win_settlement_transfers(
            result,
            dealer_seat=Seat.EAST,
            rules=rules,
        )

        self.assertEqual(
            transfers,
            (
                SettlementTransfer(
                    Seat.NORTH,
                    Seat.SOUTH,
                    32_000,
                    TransferReason.PAO_RON,
                    Seat.SOUTH,
                ),
            ),
        )

    def test_custom_tsumo_honba_uses_per_payer_times_three(self) -> None:
        rules = replace(
            RuleSet.default(),
            ron_honba_points=500,
            tsumo_honba_points_per_payer=120,
        )
        pool = _TilePool()
        context = _daisangen_context(
            pool,
            dealer_seat=Seat.EAST,
            winner_seat=Seat.SOUTH,
            method=WinMethod.TSUMO,
            origin=WinOrigin.LIVE_WALL,
            last_meld=_pon(pool, "7z", Seat.NORTH),
        )
        winner = _winner(Seat.SOUTH, context, rules=rules)
        result = _tsumo_result(winner)

        transfers = calculate_win_settlement_transfers(
            result,
            dealer_seat=Seat.EAST,
            honba=2,
            rules=rules,
        )

        self.assertIn(
            SettlementTransfer(
                Seat.NORTH,
                Seat.SOUTH,
                720,
                TransferReason.HONBA,
                Seat.SOUTH,
            ),
            transfers,
        )


class PaoDisabledSettlementTest(unittest.TestCase):
    def test_daisangen_tsumo_becomes_normal_tsumo_when_pao_disabled(self) -> None:
        rules = replace(RuleSet.default(), pao_enabled=False)
        pool = _TilePool()
        context = _daisangen_context(
            pool,
            dealer_seat=Seat.EAST,
            winner_seat=Seat.SOUTH,
            method=WinMethod.TSUMO,
            origin=WinOrigin.LIVE_WALL,
            last_meld=_pon(pool, "7z", Seat.NORTH),
        )
        winner = _winner(Seat.SOUTH, context, rules=rules)
        result = _tsumo_result(winner)

        transfers = calculate_win_settlement_transfers(
            result,
            dealer_seat=Seat.EAST,
            rules=rules,
        )

        self.assertEqual(
            {transfer.reason for transfer in transfers},
            {TransferReason.TSUMO},
        )
        self.assertEqual(
            aggregate_settlement_transfers(transfers),
            SeatPoints(-16_000, 32_000, -8_000, -8_000),
        )


class ResponsibilityDetectionTest(unittest.TestCase):
    def test_daisangen_with_ankan_as_last_group_has_no_pao(self) -> None:
        rules = RuleSet.default()
        pool = _TilePool()
        context = _daisangen_context(
            pool,
            dealer_seat=Seat.EAST,
            winner_seat=Seat.SOUTH,
            method=WinMethod.TSUMO,
            origin=WinOrigin.LIVE_WALL,
            last_meld=_ankan(pool, "7z"),
        )
        winner = _winner(Seat.SOUTH, context, rules=rules)
        result = _tsumo_result(winner)

        transfers = calculate_win_settlement_transfers(
            result,
            dealer_seat=Seat.EAST,
            rules=rules,
        )

        self.assertEqual(
            {transfer.reason for transfer in transfers},
            {TransferReason.TSUMO},
        )

    def test_suukantsu_uses_suukantsu_pao_seat(self) -> None:
        rules = replace(
            RuleSet.default(),
            pao_yaku=frozenset(RuleSet.default().pao_yaku | {Yaku.SUUKANTSU}),
        )
        pool = _TilePool()
        context = _suukantsu_context(
            pool,
            dealer_seat=Seat.EAST,
            winner_seat=Seat.SOUTH,
            method=WinMethod.TSUMO,
            origin=WinOrigin.LIVE_WALL,
            pao_seat=Seat.WEST,
        )
        winner = _winner(Seat.SOUTH, context, rules=rules)
        result = _tsumo_result(winner)

        transfers = calculate_win_settlement_transfers(
            result,
            dealer_seat=Seat.EAST,
            rules=rules,
        )

        self.assertEqual(
            transfers,
            (
                SettlementTransfer(
                    Seat.WEST,
                    Seat.SOUTH,
                    32_000,
                    TransferReason.PAO_TSUMO,
                    Seat.SOUTH,
                ),
            ),
        )


class ResponsibleYakumanOnlyPolicyTest(unittest.TestCase):
    def test_compound_tsumo_splits_responsible_and_other_units(self) -> None:
        rules = replace(
            RuleSet.default(),
            pao_compound_yakuman_policy=(
                PaoCompoundYakumanPolicy.RESPONSIBLE_YAKUMAN_ONLY
            ),
        )
        pool = _TilePool()
        context = _compound_daisangen_tsuuiisou_context(
            pool,
            dealer_seat=Seat.EAST,
            winner_seat=Seat.SOUTH,
            method=WinMethod.TSUMO,
            origin=WinOrigin.LIVE_WALL,
            pao_seat=Seat.NORTH,
        )
        winner = _winner(Seat.SOUTH, context, rules=rules)
        result = _tsumo_result(winner)

        transfers = calculate_win_settlement_transfers(
            result,
            dealer_seat=Seat.EAST,
            rules=rules,
        )

        self.assertEqual(
            transfers,
            (
                SettlementTransfer(
                    Seat.NORTH,
                    Seat.SOUTH,
                    32_000,
                    TransferReason.PAO_TSUMO,
                    Seat.SOUTH,
                ),
                SettlementTransfer(
                    Seat.EAST,
                    Seat.SOUTH,
                    16_000,
                    TransferReason.TSUMO,
                    Seat.SOUTH,
                ),
                SettlementTransfer(
                    Seat.WEST,
                    Seat.SOUTH,
                    8_000,
                    TransferReason.TSUMO,
                    Seat.SOUTH,
                ),
                SettlementTransfer(
                    Seat.NORTH,
                    Seat.SOUTH,
                    8_000,
                    TransferReason.TSUMO,
                    Seat.SOUTH,
                ),
            ),
        )

    def test_compound_ron_splits_responsible_and_other_units(self) -> None:
        rules = replace(
            RuleSet.default(),
            pao_compound_yakuman_policy=(
                PaoCompoundYakumanPolicy.RESPONSIBLE_YAKUMAN_ONLY
            ),
        )
        pool = _TilePool()
        context = _compound_daisangen_tsuuiisou_context(
            pool,
            dealer_seat=Seat.EAST,
            winner_seat=Seat.SOUTH,
            method=WinMethod.RON,
            origin=WinOrigin.DISCARD,
            pao_seat=Seat.NORTH,
        )
        winner = _winner(Seat.SOUTH, context, rules=rules)
        result = _ron_result(winner, Seat.WEST)

        transfers = calculate_win_settlement_transfers(
            result,
            dealer_seat=Seat.EAST,
            rules=rules,
        )

        self.assertEqual(
            transfers,
            (
                SettlementTransfer(
                    Seat.WEST,
                    Seat.SOUTH,
                    16_000,
                    TransferReason.RON,
                    Seat.SOUTH,
                ),
                SettlementTransfer(
                    Seat.NORTH,
                    Seat.SOUTH,
                    16_000,
                    TransferReason.PAO_RON,
                    Seat.SOUTH,
                ),
                SettlementTransfer(
                    Seat.WEST,
                    Seat.SOUTH,
                    32_000,
                    TransferReason.RON,
                    Seat.SOUTH,
                ),
            ),
        )

    def test_rejects_compound_split_when_multiple_yakuman_disabled(self) -> None:
        rules = replace(
            RuleSet.default(),
            pao_compound_yakuman_policy=(
                PaoCompoundYakumanPolicy.RESPONSIBLE_YAKUMAN_ONLY
            ),
            multiple_yakuman_enabled=False,
        )
        pool = _TilePool()
        context = _compound_daisangen_tsuuiisou_context(
            pool,
            dealer_seat=Seat.EAST,
            winner_seat=Seat.SOUTH,
            method=WinMethod.TSUMO,
            origin=WinOrigin.LIVE_WALL,
            pao_seat=Seat.NORTH,
        )
        winner = _winner(Seat.SOUTH, context, rules=rules)
        result = _tsumo_result(winner)

        with self.assertRaisesRegex(
            ValueError,
            "cannot split compound pao yakuman when multiple yakuman is disabled",
        ):
            calculate_win_settlement_transfers(
                result,
                dealer_seat=Seat.EAST,
                rules=rules,
            )

    def test_single_pao_yaku_allowed_without_multiple_yakuman(self) -> None:
        rules = replace(
            RuleSet.default(),
            pao_compound_yakuman_policy=(
                PaoCompoundYakumanPolicy.RESPONSIBLE_YAKUMAN_ONLY
            ),
            multiple_yakuman_enabled=False,
        )
        pool = _TilePool()
        context = _daisangen_context(
            pool,
            dealer_seat=Seat.EAST,
            winner_seat=Seat.SOUTH,
            method=WinMethod.TSUMO,
            origin=WinOrigin.LIVE_WALL,
            last_meld=_pon(pool, "7z", Seat.NORTH),
        )
        winner = _winner(Seat.SOUTH, context, rules=rules)
        result = _tsumo_result(winner)

        transfers = calculate_win_settlement_transfers(
            result,
            dealer_seat=Seat.EAST,
            rules=rules,
        )

        self.assertEqual(
            transfers,
            (
                SettlementTransfer(
                    Seat.NORTH,
                    Seat.SOUTH,
                    32_000,
                    TransferReason.PAO_TSUMO,
                    Seat.SOUTH,
                ),
            ),
        )


if __name__ == "__main__":
    unittest.main()
