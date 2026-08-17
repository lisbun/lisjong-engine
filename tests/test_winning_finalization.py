import unittest
from dataclasses import replace

from _round_fixtures import take

from lisjong_engine.legal_action import TsumoLegalAction
from lisjong_engine.legal_actions import RoundView, derive_legal_actions
from lisjong_engine.meld import Chi
from lisjong_engine.player_state import PlayerState
from lisjong_engine.round_event import DrawSource
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.round_result import WinResult
from lisjong_engine.rules import RuleSet
from lisjong_engine.seat import Seat
from lisjong_engine.tile import STANDARD_TILES
from lisjong_engine.win_context import RiichiStatus, WinMethod, WinOrigin
from lisjong_engine.wind import Wind
from lisjong_engine.winning_finalization import (
    DoraIndicatorState,
    WinningClaim,
    build_effective_dora_indicators,
    build_win_result,
    build_winning_context,
    has_winning_score,
)

_WINNING_NAMES = (
    "2m",
    "3m",
    "4p",
    "5p",
    "6p",
    "7s",
    "8s",
    "9s",
    "1z",
    "1z",
    "1z",
    "2z",
    "2z",
    "1m",
)


def _claim(
    *,
    method: WinMethod,
    origin: WinOrigin,
    seat: Seat = Seat.EAST,
) -> WinningClaim:
    pool = list(STANDARD_TILES)
    if method is WinMethod.TSUMO:
        concealed = take(pool, ("1m",))
        winning_tile = concealed[0]
    else:
        concealed = take(pool, ("2m",))
        winning_tile = take(pool, ("1m",))[0]
    return WinningClaim(
        seat=seat,
        concealed_tiles=concealed,
        winning_tile=winning_tile,
        method=method,
        origin=origin,
        seat_wind=Wind.EAST,
        prevailing_wind=Wind.EAST,
    )


class EffectiveDoraIndicatorsTest(unittest.TestCase):
    def test_separates_normal_kan_ura_and_kan_ura_regions_for_each_origin(
        self,
    ) -> None:
        pool = list(STANDARD_TILES)
        dora = take(pool, ("1p", "2p", "3p"))
        ura = take(pool, ("4p", "5p", "6p"))
        state = DoraIndicatorState(
            dora_indicator_tiles=dora,
            ura_dora_indicator_tiles=ura,
            revealed_dora_indicator_count=2,
            pending_kan_dora_reveal_seats=(Seat.EAST,),
        )
        cases = (
            (WinMethod.RON, WinOrigin.DISCARD, 1),
            (WinMethod.RON, WinOrigin.KAKAN, 1),
            (WinMethod.RON, WinOrigin.ANKAN, 1),
            (WinMethod.TSUMO, WinOrigin.LIVE_WALL, 1),
            (WinMethod.TSUMO, WinOrigin.RINSHAN, 2),
        )

        for method, origin, expected_kan_count in cases:
            with self.subTest(method=method, origin=origin):
                indicators = build_effective_dora_indicators(
                    _claim(method=method, origin=origin),
                    state,
                )

                self.assertEqual(indicators.visible, dora[:1])
                self.assertEqual(indicators.ura, ura[:1])
                self.assertEqual(indicators.kan, dora[1 : 1 + expected_kan_count])
                self.assertEqual(
                    indicators.kan_ura,
                    ura[1 : 1 + expected_kan_count],
                )

    def test_pending_kan_dora_only_applies_to_its_own_rinshan_claim(self) -> None:
        pool = list(STANDARD_TILES)
        dora = take(pool, ("1p", "2p"))
        ura = take(pool, ("3p", "4p"))
        state = DoraIndicatorState(
            dora,
            ura,
            revealed_dora_indicator_count=1,
            pending_kan_dora_reveal_seats=(Seat.SOUTH,),
        )

        indicators = build_effective_dora_indicators(
            _claim(method=WinMethod.TSUMO, origin=WinOrigin.RINSHAN),
            state,
        )

        self.assertEqual(indicators.kan, ())
        self.assertEqual(indicators.kan_ura, ())


class WinningClaimEvaluationTest(unittest.TestCase):
    def test_ron_tile_is_added_only_to_the_evaluation_context(self) -> None:
        claim = replace(
            _claim(method=WinMethod.RON, origin=WinOrigin.DISCARD),
            suukantsu_pao_seat=Seat.NORTH,
        )
        original_tiles = claim.concealed_tiles

        context = build_winning_context(claim)

        self.assertEqual(claim.concealed_tiles, original_tiles)
        self.assertNotIn(claim.winning_tile, claim.concealed_tiles)
        self.assertIn(claim.winning_tile, context.concealed_tiles)
        self.assertIs(context.suukantsu_pao_seat, Seat.NORTH)

    def test_non_throwing_probe_returns_false_for_an_open_yakuless_tsumo(
        self,
    ) -> None:
        pool = list(STANDARD_TILES)
        chi_tiles = take(pool, ("1m", "2m", "3m"))
        concealed = take(
            pool,
            (
                "4p",
                "5p",
                "6p",
                "7s",
                "8s",
                "9s",
                "2m",
                "3m",
                "4m",
                "5z",
                "5z",
            ),
        )
        claim = WinningClaim(
            seat=Seat.EAST,
            concealed_tiles=concealed,
            winning_tile=concealed[8],
            method=WinMethod.TSUMO,
            origin=WinOrigin.LIVE_WALL,
            seat_wind=Wind.EAST,
            prevailing_wind=Wind.EAST,
            declared_melds=(Chi(chi_tiles[0], chi_tiles[1:], Seat.NORTH),),
        )

        self.assertFalse(
            has_winning_score(claim, DoraIndicatorState(), RuleSet.default())
        )
        players = {seat: PlayerState(seat) for seat in Seat}
        players[Seat.EAST] = PlayerState(
            Seat.EAST,
            concealed,
            melds=claim.declared_melds,
        )
        view = RoundView(
            phase=RoundPhase.AWAITING_DISCARD,
            current_seat=Seat.EAST,
            players=players,
            seat_winds=dict(zip(Seat, Wind, strict=True)),
            prevailing_wind=Wind.EAST,
            rules=RuleSet.default(),
            round_start_points={seat: 25_000 for seat in Seat},
            remaining_count=40,
            can_draw_rinshan=True,
            drawn_tile_id=claim.winning_tile.id,
            drawn_tile_source=DrawSource.LIVE_WALL,
        )
        self.assertFalse(
            any(
                isinstance(action, TsumoLegalAction)
                for action in derive_legal_actions(view, Seat.EAST)
            )
        )

    def test_strict_result_uses_existing_scoring_for_all_dora_kinds(self) -> None:
        pool = list(STANDARD_TILES)
        concealed = take(pool, _WINNING_NAMES)
        dora = take(pool, ("1m", "3p"))
        ura = take(pool, ("2m", "4p"))
        claim = WinningClaim(
            seat=Seat.EAST,
            concealed_tiles=concealed,
            winning_tile=concealed[-1],
            method=WinMethod.TSUMO,
            origin=WinOrigin.LIVE_WALL,
            seat_wind=Wind.EAST,
            prevailing_wind=Wind.EAST,
            riichi_status=RiichiStatus.RIICHI,
        )

        result = build_win_result(
            (claim,),
            DoraIndicatorState(dora, ura, revealed_dora_indicator_count=2),
            RuleSet.default(),
        )

        self.assertIsInstance(result, WinResult)
        dora_counts = {
            candidate.hand_value.dora_count
            for candidate in result.winners[0].score_selection.candidates
        }
        self.assertTrue(dora_counts)
        for count in dora_counts:
            self.assertEqual(
                (count.visible, count.ura, count.kan, count.kan_ura, count.red),
                (1, 1, 1, 1, 1),
            )


if __name__ == "__main__":
    unittest.main()
