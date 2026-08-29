import unittest
from dataclasses import fields, is_dataclass
from functools import cache

from _round_fixtures import INERT_HAND, action_of_type, dealt_state, play_quiet_turn

from lisjong_engine.action_descriptor import (
    ActionDescriptor,
    RonActionDescriptor,
    TsumoActionDescriptor,
)
from lisjong_engine.dora import DoraCount, DoraIndicators
from lisjong_engine.driver import run_hanchan
from lisjong_engine.fu import FuCalculation, FuComponent, FuReason
from lisjong_engine.hand_value import HandValueEvaluation
from lisjong_engine.legal_action import TsumoLegalAction
from lisjong_engine.match_state import (
    CompletedMatch,
    CompletedRound,
    MatchEndReason,
    MatchState,
    RoundPosition,
)
from lisjong_engine.meld import Pon
from lisjong_engine.points import SeatPoints
from lisjong_engine.public_state import (
    PublicMeld,
    PublicTile,
    SeatPointDelta,
    SeatScore,
)
from lisjong_engine.round_allocation import create_round_random_provenance
from lisjong_engine.round_completion import (
    MatchCompletionFact,
    RoundCompletionDoraCount,
    RoundCompletionDoraIndicators,
    RoundCompletionFact,
    RoundCompletionSettlementTransfer,
    RoundOutcomeKind,
    project_match_completion,
    project_round_completion,
)
from lisjong_engine.round_result import (
    AbortiveDrawReason,
    WinningPlayerResult,
    WinResult,
)
from lisjong_engine.score import ScoreLimit, calculate_score
from lisjong_engine.seat import Seat
from lisjong_engine.settlement import (
    RoundSettlement,
    SettlementTransfer,
    TransferReason,
    aggregate_settlement_transfers,
    calculate_round_settlement,
)
from lisjong_engine.tile import STANDARD_TILES, Tile, TileCategory, TileType
from lisjong_engine.win_context import (
    RiichiStatus,
    WinMethod,
    WinningContext,
    WinOrigin,
)
from lisjong_engine.wind import Wind
from lisjong_engine.winning import WaitType, WinningShape
from lisjong_engine.winning_score import (
    WinningScoreCandidate,
    WinningScoreSelection,
    evaluate_winning_scores,
)
from lisjong_engine.yaku import Yaku
from lisjong_engine.yaku_evaluation import YakuEvaluation, YakuMatch

_TSUMO_HAND = (
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

_CATEGORIES = {
    "m": TileCategory.MANZU,
    "p": TileCategory.PINZU,
    "s": TileCategory.SOUZU,
    "z": TileCategory.HONOR,
}
_PINFU_NAMES = (
    "2m",
    "3m",
    "4m",
    "6m",
    "7m",
    "8m",
    "2p",
    "3p",
    "4p",
    "7s",
    "8s",
    "3s",
    "3s",
    "9s",
)
_RYANPEIKOU_WITH_RED_NAMES = (
    "1m",
    "1m",
    "2m",
    "2m",
    "3m",
    "3m",
    "4m",
    "4m",
    "0m",
    "5m",
    "6m",
    "6m",
    "7m",
    "7m",
)


def _tiles(*names: str) -> tuple[Tile, ...]:
    used_ids: set[int] = set()
    tiles = []
    for name in names:
        rank = 5 if name[0] == "0" else int(name[:-1])
        is_red = name[0] == "0"
        tile_type = TileType(_CATEGORIES[name[-1]], rank)
        tile = next(
            tile
            for tile in STANDARD_TILES
            if tile.id not in used_ids
            and tile.tile_type == tile_type
            and tile.is_red is is_red
        )
        used_ids.add(tile.id)
        tiles.append(tile)
    return tuple(tiles)


def _tile(name: str, copy_index: int) -> Tile:
    tile_type = TileType(_CATEGORIES[name[-1]], int(name[:-1]))
    return STANDARD_TILES[tile_type.id * 4 + copy_index]


def _pinfu_context(
    *,
    method: WinMethod = WinMethod.RON,
    riichi_status: RiichiStatus = RiichiStatus.NONE,
    seat_wind: Wind = Wind.SOUTH,
) -> WinningContext:
    tiles = _tiles(*_PINFU_NAMES)
    return WinningContext(
        concealed_tiles=tiles,
        winning_tile=tiles[-1],
        method=method,
        origin=(WinOrigin.DISCARD if method is WinMethod.RON else WinOrigin.LIVE_WALL),
        seat_wind=seat_wind,
        prevailing_wind=Wind.EAST,
        riichi_status=riichi_status,
    )


def _winner(
    seat: Seat,
    context: WinningContext,
    indicators: DoraIndicators | None = None,
) -> WinningPlayerResult:
    resolved_indicators = DoraIndicators() if indicators is None else indicators
    return WinningPlayerResult(
        seat,
        context,
        evaluate_winning_scores(context, dora_indicators=resolved_indicators),
    )


def _win_result(
    winners: tuple[WinningPlayerResult, ...],
    indicators: DoraIndicators | None = None,
    *,
    source_seat: Seat = Seat.EAST,
) -> WinResult:
    first = winners[0]
    context = first.context
    resolved_indicators = DoraIndicators() if indicators is None else indicators
    return WinResult(
        method=context.method,
        origin=context.origin,
        winning_tile=context.winning_tile,
        winners=winners,
        dora_indicators=resolved_indicators,
        source_seat=(source_seat if context.method is WinMethod.RON else None),
    )


def _completed_round(
    result: WinResult,
    *,
    honba: int = 0,
    riichi_sticks: int = 0,
    settlement: RoundSettlement | None = None,
) -> CompletedRound:
    position = RoundPosition(
        prevailing_wind=Wind.EAST,
        hand_number=1,
        dealer_seat=Seat.EAST,
        honba=honba,
        riichi_sticks=riichi_sticks,
    )
    if settlement is None:
        settlement = calculate_round_settlement(
            result,
            dealer_seat=Seat.EAST,
            honba=honba,
            riichi_sticks_before=riichi_sticks,
            riichi_contributions=(),
        )
    scores_after = SeatPoints(25000, 25000, 25000, 25000).add(settlement.point_deltas)
    return CompletedRound(
        random_provenance=create_round_random_provenance(10, 20),
        position_before=position,
        result=result,
        settlement=settlement,
        scores_after_settlement=scores_after,
        dealer_continues=False,
        next_position=RoundPosition(
            prevailing_wind=Wind.EAST,
            hand_number=2,
            dealer_seat=Seat.SOUTH,
            honba=0,
            riichi_sticks=settlement.riichi_sticks_after,
        ),
    )


def _candidate_with_score(
    context: WinningContext,
    *,
    han: int,
    fu: int,
) -> WinningScoreCandidate:
    base = next(iter(evaluate_winning_scores(context).max_score_candidates))
    evaluation = base.hand_value.yaku_evaluation
    dora_count = DoraCount(visible=han - evaluation.han)
    hand_value = HandValueEvaluation(
        yaku_evaluation=evaluation,
        fu_calculation=FuCalculation((FuComponent(FuReason.BASE, 20),), fu),
        dora_count=dora_count,
    )
    return WinningScoreCandidate(
        hand_value,
        calculate_score(
            han=han,
            fu=fu,
            method=context.method,
            is_dealer=context.seat_wind is Wind.EAST,
        ),
    )


def _winner_with_candidates(
    seat: Seat,
    context: WinningContext,
    candidates: frozenset[WinningScoreCandidate],
) -> WinningPlayerResult:
    return WinningPlayerResult(
        seat,
        context,
        WinningScoreSelection(candidates, candidates),
    )


def _play_deterministic_hanchan(seed: int = 12345) -> tuple[MatchState, CompletedMatch]:
    """`test_driver.py`と同じ決定的selectorで半荘を完走させ、historyを得る。"""

    def winning_first_selector(
        _observation,
        options: tuple[ActionDescriptor, ...],
    ) -> ActionDescriptor:
        return next(
            (
                option
                for option in options
                if isinstance(option, (RonActionDescriptor, TsumoActionDescriptor))
            ),
            options[0],
        )

    match = MatchState(seed=seed)
    completed = run_hanchan(match, {seat: winning_first_selector for seat in Seat})
    return match, completed


@cache
def _deterministic_completed_match(seed: int = 12345) -> CompletedMatch:
    """決定的半荘を1度だけ実行し、共有可能な`CompletedMatch`のみを返す。

    `MatchState`はmutableなため共有しない。`CompletedMatch`は
    `@dataclass(frozen=True)`で、historyもtupleの`CompletedRound`から
    成るため、この境界での共有は安全である。
    """
    return _play_deterministic_hanchan(seed)[1]


def _build_non_dealer_tsumo_completed_round() -> CompletedRound:
    """South tsumoの`CompletedRound`を、乱数の運に頼らず決定的に組み立てる。"""
    hands = {seat: INERT_HAND for seat in Seat}
    hands[Seat.SOUTH] = _TSUMO_HAND
    state = dealt_state(hands=hands, draws=("5z", "7p"), with_dead_wall=True)
    play_quiet_turn(state)  # 親(EAST)がツモ切りし、Southの番へ進める。
    state.draw(Seat.SOUTH)
    snapshot = state.legal_actions(Seat.SOUTH)
    state.apply(
        Seat.SOUTH,
        action_of_type(state, Seat.SOUTH, TsumoLegalAction),
        expected_revision=snapshot.revision,
    )
    result = state.result

    position = RoundPosition(
        prevailing_wind=Wind.EAST,
        hand_number=1,
        dealer_seat=Seat.EAST,
        honba=0,
        riichi_sticks=0,
    )
    settlement = calculate_round_settlement(
        result,
        dealer_seat=Seat.EAST,
        honba=0,
        riichi_sticks_before=0,
        riichi_contributions=state.riichi_contributions,
        rules=state.rules,
    )
    scores_before = SeatPoints(25000, 25000, 25000, 25000)
    scores_after = scores_before.add(settlement.point_deltas)
    next_position = RoundPosition(
        prevailing_wind=Wind.EAST,
        hand_number=2,
        dealer_seat=Seat.SOUTH,
        honba=0,
        riichi_sticks=settlement.riichi_sticks_after,
    )
    return CompletedRound(
        random_provenance=create_round_random_provenance(1, 1),
        position_before=position,
        result=result,
        settlement=settlement,
        scores_after_settlement=scores_after,
        dealer_continues=False,
        next_position=next_position,
    )


class RoundCompletionProjectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.completed_match = _deterministic_completed_match()
        cls.history = cls.completed_match.history

    def test_rejects_non_completed_round(self) -> None:
        with self.assertRaises(TypeError):
            project_round_completion(object())

    def test_projects_every_round_in_history_without_error(self) -> None:
        for completed_round in self.history:
            with self.subTest(position=completed_round.position_before):
                fact = project_round_completion(completed_round)
                self.assertIsInstance(fact, RoundCompletionFact)

    def test_projected_position_matches_the_source_round(self) -> None:
        completed_round = self.history[0]
        fact = project_round_completion(completed_round)

        self.assertIs(
            fact.prevailing_wind, completed_round.position_before.prevailing_wind
        )
        self.assertEqual(fact.hand_number, completed_round.position_before.hand_number)
        self.assertIs(fact.dealer_seat, completed_round.position_before.dealer_seat)
        self.assertEqual(fact.honba, completed_round.position_before.honba)
        self.assertEqual(fact.dealer_continues, completed_round.dealer_continues)
        self.assertEqual(fact.has_next_round, completed_round.next_position is not None)

    def test_point_deltas_and_scores_after_match_the_settlement(self) -> None:
        completed_round = self.history[0]
        fact = project_round_completion(completed_round)

        for delta in fact.point_deltas:
            self.assertEqual(
                delta.delta,
                completed_round.settlement.point_deltas[delta.seat],
            )
        for score in fact.scores_after:
            self.assertEqual(
                score.points,
                completed_round.scores_after_settlement[score.seat],
            )

    def test_win_outcome_reports_winners_and_source_seat(self) -> None:
        win_round = _build_non_dealer_tsumo_completed_round()
        fact = project_round_completion(win_round)

        self.assertIs(fact.outcome, RoundOutcomeKind.WIN)
        self.assertEqual(len(fact.winners), 1)
        self.assertIs(fact.winners[0].seat, Seat.SOUTH)
        self.assertIs(fact.winners[0].win_method, WinMethod.TSUMO)
        self.assertIsNone(fact.source_seat)
        self.assertFalse(fact.dealer_continues)
        self.assertTrue(fact.has_next_round)
        candidate = fact.winners[0].max_score_candidates[0]
        self.assertEqual(candidate.yakuman_units, 1)
        self.assertIs(candidate.score_limit, ScoreLimit.YAKUMAN)


class RoundCompletionWinDetailProjectionTest(unittest.TestCase):
    def test_projects_normal_ron_yaku_hand_fu_and_payment(self) -> None:
        context = _pinfu_context()
        fact = project_round_completion(
            _completed_round(_win_result((_winner(Seat.SOUTH, context),)))
        )

        winner = fact.winners[0]
        self.assertIs(winner.seat, Seat.SOUTH)
        self.assertIs(winner.win_method, WinMethod.RON)
        self.assertIsInstance(winner.winning_tile, PublicTile)
        self.assertEqual(len(winner.concealed_tiles), 14)
        self.assertTrue(
            all(isinstance(tile, PublicTile) for tile in winner.concealed_tiles)
        )
        self.assertIn(winner.winning_tile, winner.concealed_tiles)

        candidate = winner.max_score_candidates[0]
        pinfu = next(item for item in candidate.yaku if item.yaku is Yaku.PINFU)
        self.assertEqual(
            (pinfu.japanese_name, pinfu.han, pinfu.yakuman_units), ("平和", 1, None)
        )
        self.assertEqual(candidate.total_han, 1)
        self.assertEqual(candidate.rounded_fu, 30)
        self.assertIsNone(candidate.yakuman_units)
        self.assertIs(candidate.score_limit, ScoreLimit.NONE)
        self.assertEqual(candidate.ron_payment, 1_000)
        self.assertIsNone(candidate.tsumo_dealer_payment)
        self.assertIsNone(candidate.tsumo_non_dealer_payment)

    def test_projects_normal_tsumo_payment_fields(self) -> None:
        context = _pinfu_context(method=WinMethod.TSUMO)
        fact = project_round_completion(
            _completed_round(_win_result((_winner(Seat.SOUTH, context),)))
        )

        candidate = fact.winners[0].max_score_candidates[0]
        self.assertIsNone(candidate.ron_payment)
        self.assertEqual(candidate.tsumo_dealer_payment, 700)
        self.assertEqual(candidate.tsumo_non_dealer_payment, 400)

    def test_projects_declared_meld_and_red_concealed_tile(self) -> None:
        meld_tiles = _tiles("5z", "5z", "5z")
        meld = Pon(meld_tiles[0], meld_tiles[1:], Seat.NORTH)
        concealed = _tiles(
            "2m",
            "3m",
            "4m",
            "2p",
            "3p",
            "4p",
            "2s",
            "3s",
            "4s",
            "1z",
            "1z",
        )
        open_context = WinningContext(
            concealed_tiles=concealed,
            winning_tile=concealed[-1],
            method=WinMethod.RON,
            origin=WinOrigin.DISCARD,
            seat_wind=Wind.SOUTH,
            prevailing_wind=Wind.EAST,
            declared_melds=(meld,),
        )
        open_fact = project_round_completion(
            _completed_round(_win_result((_winner(Seat.SOUTH, open_context),)))
        )
        self.assertEqual(len(open_fact.winners[0].declared_melds), 1)
        self.assertIsInstance(open_fact.winners[0].declared_melds[0], PublicMeld)

        red_tiles = _tiles(*_RYANPEIKOU_WITH_RED_NAMES)
        red_context = WinningContext(
            concealed_tiles=red_tiles,
            winning_tile=red_tiles[-1],
            method=WinMethod.RON,
            origin=WinOrigin.DISCARD,
            seat_wind=Wind.SOUTH,
            prevailing_wind=Wind.EAST,
        )
        red_fact = project_round_completion(
            _completed_round(_win_result((_winner(Seat.SOUTH, red_context),)))
        )
        red_winner = red_fact.winners[0]
        self.assertEqual(sum(tile.is_red for tile in red_winner.concealed_tiles), 1)
        self.assertTrue(
            any(
                candidate.dora_count is not None and candidate.dora_count.red == 1
                for candidate in red_winner.max_score_candidates
            )
        )

    def test_multiple_ron_keeps_winner_specific_details_in_seat_order(self) -> None:
        winners = (
            _winner(Seat.WEST, _pinfu_context(seat_wind=Wind.WEST)),
            _winner(Seat.SOUTH, _pinfu_context(seat_wind=Wind.SOUTH)),
        )
        fact = project_round_completion(
            _completed_round(_win_result(winners, source_seat=Seat.EAST))
        )

        self.assertEqual(
            tuple(item.seat for item in fact.winners), (Seat.SOUTH, Seat.WEST)
        )
        for winner in fact.winners:
            self.assertIsNotNone(winner.winning_tile)
            self.assertTrue(winner.concealed_tiles)
            self.assertTrue(winner.max_score_candidates)

    def test_projects_every_normal_score_limit_without_recalculation(self) -> None:
        context = _pinfu_context()
        cases = (
            (5, ScoreLimit.MANGAN),
            (6, ScoreLimit.HANEMAN),
            (8, ScoreLimit.BAIMAN),
            (11, ScoreLimit.SANBAIMAN),
            (13, ScoreLimit.YAKUMAN),
        )
        for han, expected_limit in cases:
            with self.subTest(han=han):
                candidate = _candidate_with_score(context, han=han, fu=30)
                winner = _winner_with_candidates(
                    Seat.SOUTH, context, frozenset({candidate})
                )
                fact = project_round_completion(
                    _completed_round(_win_result((winner,)))
                )
                projected = fact.winners[0].max_score_candidates[0]
                self.assertEqual(projected.total_han, han)
                self.assertEqual(projected.rounded_fu, 30)
                self.assertIs(projected.score_limit, expected_limit)

    def test_projects_double_yakuman_without_fabricated_han_fu_or_dora(self) -> None:
        tiles = _tiles(
            "1m",
            "9m",
            "1p",
            "9p",
            "1s",
            "9s",
            "1z",
            "2z",
            "3z",
            "4z",
            "5z",
            "6z",
            "7z",
            "1m",
        )
        context = WinningContext(
            concealed_tiles=tiles,
            winning_tile=tiles[-1],
            method=WinMethod.RON,
            origin=WinOrigin.DISCARD,
            seat_wind=Wind.SOUTH,
            prevailing_wind=Wind.EAST,
        )
        evaluation = YakuEvaluation(
            shape=WinningShape.THIRTEEN_ORPHANS,
            wait_type=WaitType.KOKUSHI_THIRTEEN_SIDED,
            matches=(YakuMatch(Yaku.KOKUSHI_MUSOU_13_WAIT, yakuman_units=2),),
        )
        candidate = WinningScoreCandidate(
            HandValueEvaluation(evaluation, None),
            calculate_score(
                han=0,
                fu=None,
                method=WinMethod.RON,
                is_dealer=False,
                yakuman_units=2,
            ),
        )
        winner = _winner_with_candidates(Seat.SOUTH, context, frozenset({candidate}))
        fact = project_round_completion(_completed_round(_win_result((winner,))))

        projected = fact.winners[0].max_score_candidates[0]
        self.assertEqual(projected.yakuman_units, 2)
        self.assertIs(projected.score_limit, ScoreLimit.YAKUMAN)
        self.assertEqual(projected.ron_payment, 64_000)
        self.assertIsNone(projected.total_han)
        self.assertIsNone(projected.rounded_fu)
        self.assertIsNone(projected.dora_count)
        self.assertEqual(projected.yaku[0].japanese_name, "国士無双十三面待ち")
        self.assertEqual(projected.yaku[0].yakuman_units, 2)
        self.assertIsNone(projected.yaku[0].han)

    def test_projects_all_dora_count_categories_and_riichi_indicators(self) -> None:
        indicators = DoraIndicators(
            visible=(_tile("1m", 3),),
            ura=(_tile("2m", 3),),
            kan=(_tile("6m", 3),),
            kan_ura=(_tile("7s", 3),),
        )
        for status in (RiichiStatus.RIICHI, RiichiStatus.DOUBLE_RIICHI):
            with self.subTest(status=status):
                context = _pinfu_context(riichi_status=status)
                fact = project_round_completion(
                    _completed_round(
                        _win_result(
                            (_winner(Seat.SOUTH, context, indicators),), indicators
                        )
                    )
                )
                projected_indicators = fact.revealed_dora_indicators
                self.assertIsInstance(
                    projected_indicators, RoundCompletionDoraIndicators
                )
                self.assertEqual(
                    projected_indicators,
                    RoundCompletionDoraIndicators(
                        visible=(PublicTile(indicators.visible[0].tile_type),),
                        kan=(PublicTile(indicators.kan[0].tile_type),),
                        ura=(PublicTile(indicators.ura[0].tile_type),),
                        kan_ura=(PublicTile(indicators.kan_ura[0].tile_type),),
                    ),
                )
                counts = fact.winners[0].max_score_candidates[0].dora_count
                self.assertEqual(counts, RoundCompletionDoraCount(1, 1, 0, 1, 1))

    def test_non_riichi_win_hides_ura_and_kan_ura_indicators(self) -> None:
        indicators = DoraIndicators(
            visible=(_tile("1m", 3),),
            ura=(_tile("2m", 3),),
            kan=(_tile("6m", 3),),
            kan_ura=(_tile("7s", 3),),
        )
        context = _pinfu_context()
        fact = project_round_completion(
            _completed_round(
                _win_result((_winner(Seat.SOUTH, context, indicators),), indicators)
            )
        )

        projected = fact.revealed_dora_indicators
        self.assertIsNotNone(projected)
        self.assertEqual(projected.ura, ())
        self.assertEqual(projected.kan_ura, ())
        self.assertEqual(len(projected.visible), 1)
        self.assertEqual(len(projected.kan), 1)
        counts = fact.winners[0].max_score_candidates[0].dora_count
        self.assertEqual((counts.ura, counts.kan_ura), (0, 0))

    def test_revealed_indicator_order_is_preserved(self) -> None:
        indicators = DoraIndicators(
            visible=(_tile("1m", 3),),
            ura=(_tile("2m", 3),),
            kan=(_tile("6m", 3), _tile("1p", 3)),
            kan_ura=(_tile("7s", 3), _tile("2p", 3)),
        )
        context = _pinfu_context(riichi_status=RiichiStatus.RIICHI)
        fact = project_round_completion(
            _completed_round(
                _win_result((_winner(Seat.SOUTH, context, indicators),), indicators)
            )
        )

        projected = fact.revealed_dora_indicators
        self.assertEqual(
            tuple(tile.tile_type for tile in projected.kan),
            tuple(tile.tile_type for tile in indicators.kan),
        )
        self.assertEqual(
            tuple(tile.tile_type for tile in projected.kan_ura),
            tuple(tile.tile_type for tile in indicators.kan_ura),
        )

    def test_one_riichi_winner_reveals_ura_table_wide_in_multiple_ron(self) -> None:
        indicators = DoraIndicators(
            visible=(_tile("1m", 3),),
            ura=(_tile("2m", 3),),
        )
        riichi_context = _pinfu_context(
            riichi_status=RiichiStatus.RIICHI,
            seat_wind=Wind.SOUTH,
        )
        non_riichi_context = _pinfu_context(seat_wind=Wind.WEST)
        winners = (
            _winner(Seat.SOUTH, riichi_context, indicators),
            _winner(Seat.WEST, non_riichi_context, indicators),
        )
        fact = project_round_completion(
            _completed_round(_win_result(winners, indicators))
        )

        self.assertEqual(len(fact.revealed_dora_indicators.ura), 1)
        counts_by_seat = {
            winner.seat: winner.max_score_candidates[0].dora_count
            for winner in fact.winners
        }
        self.assertEqual(counts_by_seat[Seat.SOUTH].ura, 1)
        self.assertEqual(counts_by_seat[Seat.WEST].ura, 0)

    def test_equal_maximum_candidates_are_complete_and_deterministic(self) -> None:
        context = _pinfu_context()
        candidates = frozenset(
            {
                _candidate_with_score(context, han=4, fu=40),
                _candidate_with_score(context, han=3, fu=70),
            }
        )
        winner = _winner_with_candidates(Seat.SOUTH, context, candidates)
        completed = _completed_round(_win_result((winner,)))

        first = project_round_completion(completed)
        second = project_round_completion(completed)
        projected = first.winners[0].max_score_candidates
        self.assertEqual(len(projected), 2)
        self.assertEqual(
            tuple((item.total_han, item.rounded_fu) for item in projected),
            ((3, 70), (4, 40)),
        )
        self.assertEqual(first, second)

    def test_projects_settlement_reasons_honba_and_riichi_stick_award(self) -> None:
        context = _pinfu_context()
        result = _win_result((_winner(Seat.SOUTH, context),))
        awarded = project_round_completion(
            _completed_round(result, honba=1, riichi_sticks=1)
        )
        self.assertTrue(
            any(
                transfer.reason is TransferReason.HONBA
                for transfer in awarded.settlement_transfers
            )
        )
        self.assertEqual(
            tuple(
                (award.recipient, award.amount) for award in awarded.riichi_stick_awards
            ),
            ((Seat.SOUTH, 1_000),),
        )

        transfers = (
            SettlementTransfer(
                Seat.EAST, Seat.SOUTH, 1_000, TransferReason.RON, Seat.SOUTH
            ),
            SettlementTransfer(
                Seat.WEST, Seat.SOUTH, 1_000, TransferReason.TSUMO, Seat.SOUTH
            ),
            SettlementTransfer(
                Seat.NORTH, Seat.SOUTH, 1_000, TransferReason.PAO_RON, Seat.SOUTH
            ),
            SettlementTransfer(
                Seat.EAST, Seat.SOUTH, 1_000, TransferReason.PAO_TSUMO, Seat.SOUTH
            ),
            SettlementTransfer(
                Seat.WEST, Seat.SOUTH, 100, TransferReason.HONBA, Seat.SOUTH
            ),
            SettlementTransfer(Seat.EAST, Seat.WEST, 100, TransferReason.NOTEN_PENALTY),
            SettlementTransfer(
                Seat.NORTH, Seat.SOUTH, 1_000, TransferReason.NAGASHI_MANGAN, Seat.SOUTH
            ),
        )
        settlement = RoundSettlement(
            point_deltas=aggregate_settlement_transfers(transfers),
            transfers=transfers,
        )
        projected = project_round_completion(
            _completed_round(result, settlement=settlement)
        )
        self.assertEqual(
            tuple(item.reason for item in projected.settlement_transfers),
            tuple(reason for reason in TransferReason),
        )
        self.assertTrue(
            all(
                isinstance(item, RoundCompletionSettlementTransfer)
                for item in projected.settlement_transfers
            )
        )
        for delta in projected.point_deltas:
            self.assertEqual(delta.delta, settlement.point_deltas[delta.seat])

    def test_projection_contains_no_internal_or_physical_values(self) -> None:
        context = _pinfu_context(riichi_status=RiichiStatus.RIICHI)
        internal_indicators = DoraIndicators(
            visible=(_tile("1m", 3),),
            ura=(_tile("2m", 3),),
        )
        fact = project_round_completion(
            _completed_round(
                _win_result(
                    (_winner(Seat.SOUTH, context, internal_indicators),),
                    internal_indicators,
                )
            )
        )
        forbidden = (
            Tile,
            WinningContext,
            WinningScoreCandidate,
            DoraIndicators,
            SettlementTransfer,
            RoundSettlement,
        )

        def assert_safe(value, seen: set[int] | None = None) -> None:
            if seen is None:
                seen = set()
            if id(value) in seen:
                return
            seen.add(id(value))
            self.assertNotIsInstance(value, forbidden)
            if is_dataclass(value) and not isinstance(value, type):
                for field in fields(value):
                    self.assertNotIn(field.name, {"tile_id", "physical_id", "history"})
                    assert_safe(getattr(value, field.name), seen)
            elif isinstance(value, (tuple, list, frozenset, set)):
                for item in value:
                    assert_safe(item, seen)

        assert_safe(fact)
        self.assertEqual(tuple(winner.seat for winner in fact.winners), (Seat.SOUTH,))


class MatchCompletionProjectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.completed_match = _deterministic_completed_match()

    def test_rejects_non_completed_match(self) -> None:
        with self.assertRaises(TypeError):
            project_match_completion(object())

    def test_projects_end_reason_and_final_scores(self) -> None:
        fact = project_match_completion(self.completed_match)

        self.assertIsInstance(fact, MatchCompletionFact)
        self.assertIsInstance(fact.end_reason, MatchEndReason)
        for score in fact.final_scores:
            self.assertEqual(
                score.points,
                self.completed_match.final_raw_scores[score.seat],
            )

    def test_final_results_cover_every_seat_with_a_valid_rank(self) -> None:
        fact = project_match_completion(self.completed_match)

        self.assertEqual({result.seat for result in fact.final_results}, set(Seat))
        for result in fact.final_results:
            self.assertTrue(1 <= result.rank <= 4)
            expected = self.completed_match.final_score.for_seat(result.seat)
            self.assertEqual(result.rank, expected.rank)
            self.assertEqual(result.final_points, expected.final_points)


class RoundCompletionFactValidationTest(unittest.TestCase):
    def _base_kwargs(self) -> dict:
        seats = tuple(Seat)
        return dict(
            prevailing_wind=Wind.EAST,
            hand_number=1,
            dealer_seat=Seat.EAST,
            honba=0,
            outcome=RoundOutcomeKind.ABORTIVE_DRAW,
            abortive_reason=AbortiveDrawReason.FOUR_WINDS,
            point_deltas=tuple(SeatPointDelta(seat, 0) for seat in seats),
            scores_after=tuple(SeatScore(seat, 25000) for seat in seats),
            dealer_continues=True,
            has_next_round=True,
        )

    def test_rejects_incomplete_seat_coverage(self) -> None:
        kwargs = self._base_kwargs()
        kwargs["point_deltas"] = (SeatPointDelta(Seat.EAST, 0),)
        with self.assertRaises(ValueError):
            RoundCompletionFact(**kwargs)

    def test_rejects_wrong_types(self) -> None:
        kwargs = self._base_kwargs()
        kwargs["dealer_seat"] = "east"
        with self.assertRaises(TypeError):
            RoundCompletionFact(**kwargs)


if __name__ == "__main__":
    unittest.main()
