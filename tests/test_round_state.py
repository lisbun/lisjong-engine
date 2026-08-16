import unittest
from dataclasses import replace

from _round_fixtures import (
    INERT_HAND,
    QUIET_DRAWS,
    QUIET_HANDS,
    action_of_type,
    actions_of,
    advance_to_seat,
    all_pass_choices,
    build_wall,
    capture,
    chi_action,
    daiminkan_action,
    deal_positions,
    dealt_state,
    discard,
    discard_drawn_tile,
    draw_and_discard,
    has_action_of_type,
    new_state,
    pass_action,
    play_quiet_turn,
    pon_action,
    quiet_state,
    resolve_all_pass,
    resolve_with,
    ron_action,
    starting_points,
    tile_type,
)

from lisjong_engine.discard import Discard
from lisjong_engine.furiten import FuritenReason
from lisjong_engine.legal_action import (
    AnkanLegalAction,
    ChiLegalAction,
    DiscardDeclaration,
    DiscardLegalAction,
    KakanLegalAction,
    NineTerminalsLegalAction,
    PassLegalAction,
    PonLegalAction,
    ReactionOrigin,
    RonLegalAction,
    TsumoLegalAction,
)
from lisjong_engine.meld import Ankan, Kakan, Pon
from lisjong_engine.random_source import RandomSource
from lisjong_engine.reaction import ReactionType
from lisjong_engine.riichi_event import (
    RiichiContribution,
    RiichiDeclarationOutcome,
)
from lisjong_engine.round_event import (
    DoraIndicatorRevealedEvent,
    DrawSource,
    KanConfirmedEvent,
    KanDeclaredEvent,
    MeldCalledEvent,
    MissedRonRecordedEvent,
    ReactionsResolvedEvent,
    RiichiDeclaredEvent,
    RiichiFinalizedEvent,
    RoundStartedEvent,
    TileDiscardedEvent,
    TileDrawnEvent,
    TilesDealtEvent,
)
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.round_state import (
    IllegalActionError,
    IllegalOperationError,
    RoundInvariantError,
    RoundState,
    StaleActionError,
)
from lisjong_engine.rules import KanDoraRevealPolicy, RonResolutionPolicy, RuleSet
from lisjong_engine.seat import Seat
from lisjong_engine.tile import STANDARD_TILES, Tile
from lisjong_engine.wall import Wall, create_shuffled_wall
from lisjong_engine.win_context import (
    RiichiStatus,
    WinMethod,
    WinningContext,
    WinOrigin,
)
from lisjong_engine.wind import Wind
from lisjong_engine.yaku import Yaku
from lisjong_engine.yaku_evaluation import evaluate_yaku

_QUIET_HANDS = QUIET_HANDS
_QUIET_DRAWS = QUIET_DRAWS
_build_wall = build_wall
_capture = capture
_dealt_state = dealt_state
_quiet_state = quiet_state
_tile_type = tile_type
_deal_positions = deal_positions


def _discard_drawn_tile(state: RoundState, seat: Seat) -> Tile:
    tile = state.draw(seat)
    snapshot = state.legal_actions(seat)
    action = DiscardLegalAction(tile.id)
    state.apply(seat, action, expected_revision=snapshot.revision)
    return tile


class RoundStateInitializationTest(unittest.TestCase):
    def test_starts_undealt_with_the_configured_round_facts(self) -> None:
        wall = Wall(STANDARD_TILES[:60])

        state = new_state(wall, dealer_seat=Seat.SOUTH, prevailing_wind=Wind.SOUTH)

        self.assertIs(state.phase, RoundPhase.UNDEALT)
        self.assertIsNone(state.current_seat)
        self.assertIs(state.dealer_seat, Seat.SOUTH)
        self.assertIs(state.prevailing_wind, Wind.SOUTH)
        self.assertEqual(state.revision, 0)
        self.assertIsNone(state.drawn_tile_id)
        self.assertEqual(state.remaining_count, 60)
        for seat in Seat:
            with self.subTest(seat=seat):
                self.assertEqual(state.hand_tiles(seat), ())
                self.assertEqual(state.discards(seat), ())
                self.assertEqual(state.melds(seat), ())

    def test_uses_the_default_rule_set_when_none_is_given(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:60]))

        self.assertEqual(state.rules, RuleSet.default())

    def test_keeps_the_given_rule_set(self) -> None:
        rules = RuleSet.default()

        state = new_state(Wall(STANDARD_TILES[:60]), rules=rules)

        self.assertIs(state.rules, rules)

    def test_copies_the_given_wall(self) -> None:
        wall = Wall(STANDARD_TILES[:60])
        state = new_state(wall)

        state.deal()

        self.assertEqual(wall.remaining_count, 60)
        self.assertEqual(state.remaining_count, 8)

    def test_seat_wind_follows_the_dealer(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:60]), dealer_seat=Seat.WEST)

        self.assertIs(state.seat_wind(Seat.WEST), Wind.EAST)
        self.assertIs(state.seat_wind(Seat.NORTH), Wind.SOUTH)
        self.assertIs(state.seat_wind(Seat.EAST), Wind.WEST)
        self.assertIs(state.seat_wind(Seat.SOUTH), Wind.NORTH)

    def test_rejects_invalid_constructor_arguments(self) -> None:
        wall = Wall(STANDARD_TILES[:60])

        with self.assertRaises(TypeError):
            RoundState(STANDARD_TILES[:60])
        with self.assertRaises(TypeError):
            RoundState(wall, dealer_seat="east")
        with self.assertRaises(TypeError):
            RoundState(wall, prevailing_wind="east")
        with self.assertRaises(TypeError):
            RoundState(wall, rules="standard")

    def test_rejects_a_non_seat_for_seat_scoped_reads(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:60]))

        for read in (
            state.hand_tiles,
            state.discards,
            state.melds,
            state.legal_actions,
            state.seat_wind,
        ):
            with self.subTest(read=read):
                with self.assertRaises(TypeError):
                    read("east")


class RoundStateDealTest(unittest.TestCase):
    def _expected_initial_hands(self) -> dict[Seat, tuple[Tile, ...]]:
        return {
            seat: tuple(STANDARD_TILES[position] for position in positions)
            for seat, positions in _deal_positions(Seat.EAST).items()
        }

    def test_deals_thirteen_tiles_per_seat_in_the_standard_order(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:60]))
        expected_hands = self._expected_initial_hands()

        dealt_tiles = state.deal()

        self.assertEqual(dealt_tiles, expected_hands)
        for seat in Seat:
            with self.subTest(seat=seat):
                self.assertEqual(len(state.hand_tiles(seat)), 13)
                self.assertEqual(state.hand_tiles(seat), expected_hands[seat])
                self.assertEqual(state.discards(seat), ())
                self.assertEqual(state.melds(seat), ())

    def test_deal_sets_the_dealer_turn_and_phase(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:60]))

        state.deal()

        self.assertIs(state.current_seat, Seat.EAST)
        self.assertIs(state.phase, RoundPhase.AWAITING_DRAW)
        self.assertIsNone(state.drawn_tile_id)
        self.assertEqual(state.remaining_count, 8)
        self.assertEqual(state.remaining_tiles, STANDARD_TILES[52:60])
        self.assertEqual(state.revision, 1)

    def test_deals_from_the_configured_dealer_seat(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:60]), dealer_seat=Seat.SOUTH)

        dealt_tiles = state.deal()

        self.assertIs(state.current_seat, Seat.SOUTH)
        self.assertEqual(
            dealt_tiles[Seat.SOUTH],
            (
                *STANDARD_TILES[0:4],
                *STANDARD_TILES[16:20],
                *STANDARD_TILES[32:36],
                STANDARD_TILES[48],
            ),
        )

    def test_deal_records_the_round_start_and_the_dealt_hands(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:60]))

        dealt_tiles = state.deal()

        self.assertEqual(
            tuple(state.events),
            (
                RoundStartedEvent(Seat.EAST, Wind.EAST),
                *(TilesDealtEvent(seat, dealt_tiles[seat]) for seat in Seat),
            ),
        )

    def test_deal_keeps_every_physical_tile_distinct(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:60]))

        state.deal()

        tile_ids = [tile.id for seat in Seat for tile in state.hand_tiles(seat)] + [
            tile.id for tile in state.remaining_tiles
        ]
        self.assertEqual(len(set(tile_ids)), len(tile_ids))
        self.assertEqual(len(tile_ids), 60)

    def test_the_same_wall_always_produces_the_same_initial_state(self) -> None:
        first = new_state(Wall(STANDARD_TILES[:60]))
        second = new_state(Wall(STANDARD_TILES[:60]))

        first.deal()
        second.deal()

        self.assertEqual(_capture(first), _capture(second))

    def test_rejects_a_second_deal_without_changing_state(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:60]))
        state.deal()
        original = _capture(state)

        with self.assertRaises(IllegalOperationError):
            state.deal()

        self.assertEqual(_capture(state), original)

    def test_rejects_a_short_wall_without_changing_state(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:51]))
        original = _capture(state)

        with self.assertRaises(IndexError):
            state.deal()

        self.assertEqual(_capture(state), original)
        self.assertIs(state.phase, RoundPhase.UNDEALT)
        self.assertEqual(state.revision, 0)


class RoundStateDrawTest(unittest.TestCase):
    def test_moves_the_next_wall_tile_into_the_current_hand(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:60]))
        state.deal()

        tile = state.draw(Seat.EAST)

        self.assertEqual(tile, STANDARD_TILES[52])
        self.assertIn(tile, state.hand_tiles(Seat.EAST))
        self.assertEqual(len(state.hand_tiles(Seat.EAST)), 14)
        self.assertEqual(state.remaining_tiles, STANDARD_TILES[53:60])
        self.assertEqual(state.remaining_count, 7)

    def test_draw_moves_the_phase_and_records_the_drawn_tile(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:60]))
        state.deal()

        tile = state.draw(Seat.EAST)

        self.assertIs(state.phase, RoundPhase.AWAITING_DISCARD)
        self.assertIs(state.current_seat, Seat.EAST)
        self.assertEqual(state.drawn_tile_id, tile.id)
        self.assertEqual(state.drawn_tile, tile)
        self.assertEqual(state.revision, 2)

    def test_draw_records_a_live_wall_event(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:60]))
        state.deal()

        tile = state.draw(Seat.EAST)

        self.assertEqual(
            state.events[-1],
            TileDrawnEvent(Seat.EAST, tile, DrawSource.LIVE_WALL),
        )

    def test_other_seats_cannot_draw(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:60]))
        state.deal()
        original = _capture(state)

        for seat in (Seat.SOUTH, Seat.WEST, Seat.NORTH):
            with self.subTest(seat=seat):
                with self.assertRaises(IllegalOperationError):
                    state.draw(seat)

        self.assertEqual(_capture(state), original)

    def test_cannot_draw_outside_the_draw_phase(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:60]))

        with self.assertRaises(IllegalOperationError):
            state.draw(Seat.EAST)

        state.deal()
        state.draw(Seat.EAST)
        original = _capture(state)

        with self.assertRaises(IllegalOperationError):
            state.draw(Seat.EAST)

        self.assertEqual(_capture(state), original)

    def test_rejects_a_draw_from_an_empty_wall_without_changing_state(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:52]))
        state.deal()
        original = _capture(state)

        with self.assertRaises(IndexError):
            state.draw(Seat.EAST)

        self.assertEqual(_capture(state), original)
        self.assertEqual(state.remaining_count, 0)


class RoundStateLegalActionsTest(unittest.TestCase):
    def test_lists_every_hand_tile_for_the_current_seat(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:60]))
        state.deal()
        state.draw(Seat.EAST)

        snapshot = state.legal_actions(Seat.EAST)

        self.assertIs(snapshot.seat, Seat.EAST)
        self.assertIs(snapshot.phase, RoundPhase.AWAITING_DISCARD)
        self.assertEqual(snapshot.revision, state.revision)
        self.assertEqual(
            snapshot.actions,
            tuple(
                DiscardLegalAction(tile.id)
                for tile in sorted(
                    state.hand_tiles(Seat.EAST), key=lambda tile: tile.id
                )
            ),
        )
        self.assertEqual(len(snapshot.actions), 14)

    def test_does_not_offer_turn_actions_to_other_seats(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:60]))
        state.deal()
        state.draw(Seat.EAST)

        for seat in (Seat.SOUTH, Seat.WEST, Seat.NORTH):
            with self.subTest(seat=seat):
                self.assertEqual(state.legal_actions(seat).actions, ())

    def test_offers_nothing_while_awaiting_a_draw(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:60]))
        state.deal()

        snapshot = state.legal_actions(Seat.EAST)

        self.assertIs(snapshot.phase, RoundPhase.AWAITING_DRAW)
        self.assertEqual(snapshot.actions, ())

    def test_offers_nothing_before_the_deal(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:60]))

        self.assertEqual(state.legal_actions(Seat.EAST).actions, ())

    def test_snapshot_has_no_side_effects(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:60]))
        state.deal()
        state.draw(Seat.EAST)
        original = _capture(state)

        first = state.legal_actions(Seat.EAST)
        second = state.legal_actions(Seat.EAST)

        self.assertEqual(first, second)
        self.assertEqual(_capture(state), original)

    def test_candidates_are_limited_to_tiles_owned_by_the_hand(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:60]))
        state.deal()
        state.draw(Seat.EAST)
        hand_tile_ids = {tile.id for tile in state.hand_tiles(Seat.EAST)}

        snapshot = state.legal_actions(Seat.EAST)

        self.assertTrue(
            all(action.tile_id in hand_tile_ids for action in snapshot.actions)
        )

    def test_exposes_immutable_views_only(self) -> None:
        state = new_state(Wall(STANDARD_TILES[:60]))
        state.deal()

        self.assertIsInstance(state.hand_tiles(Seat.EAST), tuple)
        self.assertIsInstance(state.discards(Seat.EAST), tuple)
        self.assertIsInstance(state.melds(Seat.EAST), tuple)
        self.assertIsInstance(state.legal_actions(Seat.EAST).actions, tuple)


class RoundStateApplyDiscardTest(unittest.TestCase):
    def test_applies_a_chosen_legal_discard(self) -> None:
        state = _quiet_state()
        state.draw(Seat.EAST)
        snapshot = state.legal_actions(Seat.EAST)
        chosen = snapshot.actions[0]

        state.apply(Seat.EAST, chosen, expected_revision=snapshot.revision)

        self.assertEqual(
            [discard.tile.id for discard in state.discards(Seat.EAST)],
            [chosen.tile_id],
        )
        self.assertNotIn(
            chosen.tile_id,
            {tile.id for tile in state.hand_tiles(Seat.EAST)},
        )
        self.assertEqual(len(state.hand_tiles(Seat.EAST)), 13)

    def test_engine_derives_tsumogiri_from_the_drawn_tile(self) -> None:
        state = _quiet_state()
        drawn_tile = state.draw(Seat.EAST)
        snapshot = state.legal_actions(Seat.EAST)

        state.apply(
            Seat.EAST,
            DiscardLegalAction(drawn_tile.id),
            expected_revision=snapshot.revision,
        )

        self.assertEqual(
            state.discards(Seat.EAST),
            (Discard(drawn_tile, is_tsumogiri=True),),
        )

    def test_engine_derives_tedashi_from_the_drawn_tile(self) -> None:
        state = _quiet_state()
        drawn_tile = state.draw(Seat.EAST)
        snapshot = state.legal_actions(Seat.EAST)
        hand_tile = next(
            tile for tile in state.hand_tiles(Seat.EAST) if tile.id != drawn_tile.id
        )

        state.apply(
            Seat.EAST,
            DiscardLegalAction(hand_tile.id),
            expected_revision=snapshot.revision,
        )

        self.assertEqual(
            state.discards(Seat.EAST),
            (Discard(hand_tile, is_tsumogiri=False),),
        )
        self.assertIn(drawn_tile, state.hand_tiles(Seat.EAST))

    def test_discard_records_an_event_and_clears_the_drawn_tile(self) -> None:
        state = _quiet_state()
        drawn_tile = state.draw(Seat.EAST)
        snapshot = state.legal_actions(Seat.EAST)

        state.apply(
            Seat.EAST,
            DiscardLegalAction(drawn_tile.id),
            expected_revision=snapshot.revision,
        )

        self.assertEqual(
            state.events[-1],
            TileDiscardedEvent(Seat.EAST, drawn_tile, True),
        )
        self.assertIsNone(state.drawn_tile_id)
        self.assertIsNone(state.drawn_tile)

    def test_discard_advances_the_turn_and_the_revision(self) -> None:
        state = _quiet_state()
        state.draw(Seat.EAST)
        snapshot = state.legal_actions(Seat.EAST)

        state.apply(Seat.EAST, snapshot.actions[0], expected_revision=snapshot.revision)

        self.assertIs(state.phase, RoundPhase.AWAITING_DRAW)
        self.assertIs(state.current_seat, Seat.SOUTH)
        self.assertEqual(state.revision, snapshot.revision + 1)

    def test_runs_several_turns_in_a_row(self) -> None:
        state = _quiet_state()
        expected_seats = (
            Seat.EAST,
            Seat.SOUTH,
            Seat.WEST,
            Seat.NORTH,
            Seat.EAST,
            Seat.SOUTH,
            Seat.WEST,
            Seat.NORTH,
        )

        discarded_tiles = []
        for expected_seat in expected_seats:
            self.assertIs(state.current_seat, expected_seat)
            self.assertIs(state.phase, RoundPhase.AWAITING_DRAW)
            discarded_tiles.append(_discard_drawn_tile(state, expected_seat))

        self.assertIs(state.current_seat, Seat.EAST)
        self.assertIs(state.phase, RoundPhase.AWAITING_DRAW)
        self.assertEqual(len(discarded_tiles), 8)
        for seat in Seat:
            with self.subTest(seat=seat):
                self.assertEqual(len(state.hand_tiles(seat)), 13)
                self.assertEqual(len(state.discards(seat)), 2)

    def test_physical_tiles_are_conserved_across_turns(self) -> None:
        state = _quiet_state()
        expected_tile_ids = {
            tile.id for tile in (*state.remaining_tiles, *state.dead_wall_tiles)
        } | {tile.id for seat in Seat for tile in state.hand_tiles(seat)}

        for seat in (Seat.EAST, Seat.SOUTH, Seat.WEST, Seat.NORTH):
            _discard_drawn_tile(state, seat)

        owned_tile_ids = [
            tile.id for tile in (*state.remaining_tiles, *state.dead_wall_tiles)
        ]
        for seat in Seat:
            owned_tile_ids.extend(tile.id for tile in state.hand_tiles(seat))
            owned_tile_ids.extend(discard.tile.id for discard in state.discards(seat))
            owned_tile_ids.extend(
                tile.id for meld in state.melds(seat) for tile in meld.tiles
            )

        self.assertEqual(len(set(owned_tile_ids)), len(owned_tile_ids))
        self.assertEqual(set(owned_tile_ids), expected_tile_ids)


class RoundStateRejectionTest(unittest.TestCase):
    def _drawn_state(self) -> RoundState:
        state = _quiet_state()
        state.draw(Seat.EAST)
        return state

    def test_rejects_a_turn_action_from_another_seat(self) -> None:
        state = self._drawn_state()
        snapshot = state.legal_actions(Seat.EAST)
        original = _capture(state)

        for seat in (Seat.SOUTH, Seat.WEST, Seat.NORTH):
            with self.subTest(seat=seat):
                with self.assertRaises(IllegalActionError):
                    state.apply(
                        seat,
                        snapshot.actions[0],
                        expected_revision=snapshot.revision,
                    )

        self.assertEqual(_capture(state), original)

    def test_rejects_an_action_that_is_not_in_the_legal_actions(self) -> None:
        state = self._drawn_state()
        snapshot = state.legal_actions(Seat.EAST)
        original = _capture(state)
        absent_tile_id = next(
            tile.id
            for tile in STANDARD_TILES
            if all(action.tile_id != tile.id for action in snapshot.actions)
        )

        with self.assertRaises(IllegalActionError):
            state.apply(
                Seat.EAST,
                DiscardLegalAction(absent_tile_id),
                expected_revision=snapshot.revision,
            )

        self.assertEqual(_capture(state), original)

    def test_rejects_discarding_a_tile_owned_by_another_seat(self) -> None:
        state = self._drawn_state()
        snapshot = state.legal_actions(Seat.EAST)
        other_tile = state.hand_tiles(Seat.SOUTH)[0]
        original = _capture(state)

        with self.assertRaises(IllegalActionError):
            state.apply(
                Seat.EAST,
                DiscardLegalAction(other_tile.id),
                expected_revision=snapshot.revision,
            )

        self.assertEqual(_capture(state), original)

    def test_rejects_a_declaration_that_is_not_generated_yet(self) -> None:
        state = self._drawn_state()
        snapshot = state.legal_actions(Seat.EAST)
        original = _capture(state)

        with self.assertRaises(IllegalActionError):
            state.apply(
                Seat.EAST,
                DiscardLegalAction(
                    snapshot.actions[0].tile_id,
                    DiscardDeclaration.RIICHI,
                ),
                expected_revision=snapshot.revision,
            )

        self.assertEqual(_capture(state), original)

    def test_rejects_actions_that_belong_to_later_scopes(self) -> None:
        state = self._drawn_state()
        snapshot = state.legal_actions(Seat.EAST)
        original = _capture(state)
        unsupported_actions = (
            TsumoLegalAction(),
            NineTerminalsLegalAction(),
            RonLegalAction(ReactionOrigin.DISCARD, 0),
            PassLegalAction(ReactionOrigin.DISCARD, 0),
            ChiLegalAction(0, (1, 2)),
            PonLegalAction(0, (1, 2)),
        )

        for action in unsupported_actions:
            with self.subTest(action=action):
                with self.assertRaises(IllegalActionError):
                    state.apply(
                        Seat.EAST,
                        action,
                        expected_revision=snapshot.revision,
                    )

        self.assertEqual(_capture(state), original)

    def test_rejects_an_action_whose_phase_does_not_match(self) -> None:
        state = self._drawn_state()
        snapshot = state.legal_actions(Seat.EAST)
        state.apply(Seat.EAST, snapshot.actions[0], expected_revision=snapshot.revision)
        original = _capture(state)

        with self.assertRaises(IllegalActionError):
            state.apply(
                Seat.SOUTH,
                DiscardLegalAction(state.hand_tiles(Seat.SOUTH)[0].id),
                expected_revision=state.revision,
            )

        self.assertIs(state.phase, RoundPhase.AWAITING_DRAW)
        self.assertEqual(_capture(state), original)

    def test_rejects_a_stale_snapshot(self) -> None:
        state = self._drawn_state()
        stale_snapshot = state.legal_actions(Seat.EAST)
        state.apply(
            Seat.EAST,
            stale_snapshot.actions[0],
            expected_revision=stale_snapshot.revision,
        )
        original = _capture(state)

        with self.assertRaises(StaleActionError):
            state.apply(
                Seat.SOUTH,
                stale_snapshot.actions[1],
                expected_revision=stale_snapshot.revision,
            )

        self.assertEqual(_capture(state), original)

    def test_rejects_a_stale_action_that_is_legal_again(self) -> None:
        state = _quiet_state()
        state.draw(Seat.EAST)
        stale_snapshot = state.legal_actions(Seat.EAST)
        stale_action = next(
            action
            for action in stale_snapshot.actions
            if action.tile_id != state.drawn_tile_id
        )
        state.apply(
            Seat.EAST,
            DiscardLegalAction(state.drawn_tile_id),
            expected_revision=stale_snapshot.revision,
        )
        for seat in (Seat.SOUTH, Seat.WEST, Seat.NORTH):
            _discard_drawn_tile(state, seat)
        state.draw(Seat.EAST)
        current_snapshot = state.legal_actions(Seat.EAST)
        original = _capture(state)

        self.assertIn(stale_action, current_snapshot.actions)
        self.assertNotEqual(stale_snapshot.revision, current_snapshot.revision)
        with self.assertRaises(StaleActionError):
            state.apply(
                Seat.EAST,
                stale_action,
                expected_revision=stale_snapshot.revision,
            )
        self.assertEqual(_capture(state), original)

        state.apply(
            Seat.EAST,
            stale_action,
            expected_revision=current_snapshot.revision,
        )

        self.assertEqual(
            state.discards(Seat.EAST)[-1].tile.id,
            stale_action.tile_id,
        )

    def test_rejects_invalid_apply_arguments(self) -> None:
        state = self._drawn_state()
        snapshot = state.legal_actions(Seat.EAST)
        original = _capture(state)

        with self.assertRaises(TypeError):
            state.apply(
                "east",
                snapshot.actions[0],
                expected_revision=snapshot.revision,
            )
        with self.assertRaises(TypeError):
            state.apply(
                Seat.EAST,
                "discard 1m",
                expected_revision=snapshot.revision,
            )
        with self.assertRaises(TypeError):
            state.apply(
                Seat.EAST,
                snapshot.actions[0],
                expected_revision="2",
            )

        self.assertEqual(_capture(state), original)


class RoundStateReactionBoundaryTest(unittest.TestCase):
    def _reaction_hands(self, reacting_hand: tuple[str, ...]) -> dict:
        hands = dict(_QUIET_HANDS)
        hands[Seat.WEST] = reacting_hand
        return hands

    def test_advances_when_no_seat_can_react(self) -> None:
        state = _quiet_state()

        _discard_drawn_tile(state, Seat.EAST)

        self.assertIs(state.phase, RoundPhase.AWAITING_DRAW)
        self.assertIs(state.current_seat, Seat.SOUTH)
        self.assertIsNone(state.pending_discarder)
        self.assertIsNone(state.pending_discard)

    def test_stops_for_a_possible_pon(self) -> None:
        state = _dealt_state(
            hands=self._reaction_hands(
                (
                    "5z",
                    "5z",
                    "1m",
                    "4m",
                    "7m",
                    "1p",
                    "4p",
                    "7p",
                    "1s",
                    "4s",
                    "7s",
                    "2z",
                    "3z",
                )
            ),
            draws=("5z",),
        )

        drawn_tile = state.draw(Seat.EAST)
        snapshot = state.legal_actions(Seat.EAST)
        state.apply(
            Seat.EAST,
            DiscardLegalAction(drawn_tile.id),
            expected_revision=snapshot.revision,
        )

        self.assertIs(state.phase, RoundPhase.AWAITING_REACTIONS)
        self.assertIsNone(state.current_seat)
        self.assertIs(state.pending_discarder, Seat.EAST)
        self.assertEqual(state.pending_discard.tile, drawn_tile)

    def test_stops_for_a_possible_chi_from_the_next_seat(self) -> None:
        hands = dict(_QUIET_HANDS)
        hands[Seat.SOUTH] = (
            "3p",
            "4p",
            "1m",
            "4m",
            "7m",
            "7p",
            "1s",
            "4s",
            "7s",
            "1z",
            "2z",
            "3z",
            "4z",
        )
        state = _dealt_state(hands=hands, draws=("5p",))

        drawn_tile = state.draw(Seat.EAST)
        snapshot = state.legal_actions(Seat.EAST)
        state.apply(
            Seat.EAST,
            DiscardLegalAction(drawn_tile.id),
            expected_revision=snapshot.revision,
        )

        self.assertIs(state.phase, RoundPhase.AWAITING_REACTIONS)
        self.assertIs(state.pending_discarder, Seat.EAST)

    def test_stops_for_a_possible_ron(self) -> None:
        state = _dealt_state(
            hands=self._reaction_hands(
                (
                    "2m",
                    "2m",
                    "2m",
                    "3m",
                    "4m",
                    "5m",
                    "6m",
                    "7m",
                    "8m",
                    "9p",
                    "9p",
                    "3p",
                    "4p",
                )
            ),
            draws=("5p",),
        )

        drawn_tile = state.draw(Seat.EAST)
        snapshot = state.legal_actions(Seat.EAST)
        state.apply(
            Seat.EAST,
            DiscardLegalAction(drawn_tile.id),
            expected_revision=snapshot.revision,
        )

        self.assertIs(state.phase, RoundPhase.AWAITING_REACTIONS)
        self.assertIs(state.pending_discarder, Seat.EAST)

    def test_offers_reaction_actions_only_to_the_other_seats(self) -> None:
        """反応window中は、打牌した席以外の3席だけがchoiceを持つ。

        反応できない席にもパスを提示し、「非パスの反応がある席だけが
        反応対象になる」という意味にしない。
        """
        state = _dealt_state(
            hands=self._reaction_hands(
                (
                    "5z",
                    "5z",
                    "1m",
                    "4m",
                    "7m",
                    "1p",
                    "4p",
                    "7p",
                    "1s",
                    "4s",
                    "7s",
                    "2z",
                    "3z",
                )
            ),
            draws=("5z",),
        )
        drawn_tile = state.draw(Seat.EAST)
        snapshot = state.legal_actions(Seat.EAST)
        state.apply(
            Seat.EAST,
            DiscardLegalAction(drawn_tile.id),
            expected_revision=snapshot.revision,
        )
        original = _capture(state)

        self.assertEqual(state.legal_actions(Seat.EAST).actions, ())
        self.assertEqual(state.reacting_seats, (Seat.SOUTH, Seat.WEST, Seat.NORTH))
        for seat in state.reacting_seats:
            with self.subTest(seat=seat):
                self.assertIn(
                    PassLegalAction(ReactionOrigin.DISCARD, drawn_tile.id),
                    state.legal_actions(seat).actions,
                )

        with self.assertRaises(IllegalOperationError):
            state.draw(Seat.SOUTH)
        with self.assertRaises(IllegalActionError):
            state.apply(
                Seat.WEST,
                PonLegalAction(drawn_tile.id, (0, 1)),
                expected_revision=state.revision,
            )

        self.assertEqual(_capture(state), original)


class RoundStateInvariantGuardTest(unittest.TestCase):
    """commit前のinvariant checkが最後の安全網として機能することを固定する。

    通常の操作からは到達しないため、working copyを直接壊して確認する。
    """

    def test_rejects_a_transition_that_loses_a_physical_tile(self) -> None:
        state = _quiet_state()
        original = _capture(state)
        transition = state._begin()
        transition.players[Seat.EAST]._hand.remove(state.hand_tiles(Seat.EAST)[0].id)

        with self.assertRaises(RoundInvariantError):
            state._commit(transition)

        self.assertEqual(_capture(state), original)

    def test_rejects_a_transition_that_duplicates_a_physical_tile(self) -> None:
        state = _quiet_state()
        original = _capture(state)
        transition = state._begin()
        transition.players[Seat.SOUTH]._hand.add(state.hand_tiles(Seat.EAST)[0])

        with self.assertRaises(RoundInvariantError):
            state._commit(transition)

        self.assertEqual(_capture(state), original)

    def test_rejects_a_transition_whose_phase_is_inconsistent(self) -> None:
        state = _quiet_state()
        original = _capture(state)
        transition = state._begin()
        transition.phase = RoundPhase.AWAITING_REACTIONS

        with self.assertRaises(RoundInvariantError):
            state._commit(transition)

        self.assertEqual(_capture(state), original)

    def test_rejects_a_pending_discard_outside_the_reaction_phase(self) -> None:
        state = _quiet_state()
        original = _capture(state)
        transition = state._begin()
        transition.pending_discarder = Seat.EAST
        transition.pending_discard = Discard(
            state.hand_tiles(Seat.EAST)[0],
            is_tsumogiri=False,
        )

        with self.assertRaises(RoundInvariantError):
            state._commit(transition)

        self.assertEqual(_capture(state), original)

    def test_allows_awaiting_discard_without_a_drawn_tile(self) -> None:
        """鳴き成立直後の打牌（ツモを伴わない）を将来禁止しないことを固定する。

        E1はチー・ポンを実装しないが、成立後の状態は
        `phase = AWAITING_DISCARD` かつ `drawn_tile_id = None` であり、
        invariantがこれを一般的に拒否してはならない。
        """
        state = _quiet_state()
        transition = state._begin()
        transition.phase = RoundPhase.AWAITING_DISCARD
        transition.current_seat = Seat.EAST
        transition.drawn_tile_id = None

        state._commit(transition)

        self.assertIs(state.phase, RoundPhase.AWAITING_DISCARD)
        self.assertIs(state.current_seat, Seat.EAST)
        self.assertIsNone(state.drawn_tile_id)

    def test_allows_awaiting_rinshan_draw_with_a_current_seat(self) -> None:
        """槓成立後、嶺上牌を引くseatをcurrent seatとして保持できることを固定する。

        E1は槓を実装しないが、`AWAITING_RINSHAN_DRAW` はE2で
        `current_seat` を要求する正常なphaseであり、invariantが
        current seatありというだけで拒否してはならない。
        """
        state = _quiet_state()
        transition = state._begin()
        transition.phase = RoundPhase.AWAITING_RINSHAN_DRAW
        transition.current_seat = Seat.EAST
        transition.drawn_tile_id = None

        state._commit(transition)

        self.assertIs(state.phase, RoundPhase.AWAITING_RINSHAN_DRAW)
        self.assertIs(state.current_seat, Seat.EAST)

    def test_rejects_a_drawn_tile_reference_outside_allowed_phases(self) -> None:
        """drawn tileを保持できるphaseは discard / kakan・ankan反応待ちに限る。

        `AWAITING_RINSHAN_DRAW`はcurrent seatを要求するphaseだが、嶺上牌を
        引く前にdrawn tileが残っているのは不正状態であり、引き続き拒否する。
        `UNDEALT` / `AWAITING_DRAW` / `AWAITING_REACTIONS` / `FINISHED`は
        current seatの要不要が異なるphaseだが、いずれもdrawn tileを保持した
        ままの遷移をfail closedで拒否する。
        """
        disallowed_phases = (
            RoundPhase.UNDEALT,
            RoundPhase.AWAITING_DRAW,
            RoundPhase.AWAITING_RINSHAN_DRAW,
            RoundPhase.AWAITING_REACTIONS,
            RoundPhase.FINISHED,
        )

        for phase in disallowed_phases:
            with self.subTest(phase=phase):
                state = _quiet_state()
                drawn_tile = state.draw(Seat.EAST)
                original = _capture(state)
                transition = state._begin()
                transition.phase = phase

                with self.assertRaises(RoundInvariantError):
                    state._commit(transition)

                self.assertEqual(_capture(state), original)
                self.assertEqual(state.drawn_tile_id, drawn_tile.id)

    def test_rejects_a_drawn_tile_not_owned_by_the_current_hand(self) -> None:
        state = _quiet_state()
        state.draw(Seat.EAST)
        original = _capture(state)
        transition = state._begin()
        transition.drawn_tile_id = state.hand_tiles(Seat.SOUTH)[0].id

        with self.assertRaises(RoundInvariantError):
            state._commit(transition)

        self.assertEqual(_capture(state), original)

    def test_rejects_awaiting_draw_without_a_current_seat(self) -> None:
        state = _quiet_state()
        original = _capture(state)
        transition = state._begin()
        transition.current_seat = None

        with self.assertRaises(RoundInvariantError):
            state._commit(transition)

        self.assertEqual(_capture(state), original)

    def test_rejects_awaiting_discard_without_a_current_seat(self) -> None:
        state = _quiet_state()
        state.draw(Seat.EAST)
        original = _capture(state)
        transition = state._begin()
        transition.current_seat = None

        with self.assertRaises(RoundInvariantError):
            state._commit(transition)

        self.assertEqual(_capture(state), original)

    def test_rejects_a_current_seat_outside_seat_holding_phases(self) -> None:
        state = _quiet_state()
        original = _capture(state)
        transition = state._begin()
        transition.phase = RoundPhase.FINISHED
        transition.current_seat = Seat.EAST

        with self.assertRaises(RoundInvariantError):
            state._commit(transition)

        self.assertEqual(_capture(state), original)


class RoundStateDeterminismTest(unittest.TestCase):
    def _play(self, state: RoundState) -> None:
        for seat in (Seat.EAST, Seat.SOUTH, Seat.WEST, Seat.NORTH):
            _discard_drawn_tile(state, seat)

    def test_the_same_wall_and_actions_reach_the_same_state(self) -> None:
        first = _quiet_state()
        second = _quiet_state()

        self._play(first)
        self._play(second)

        self.assertEqual(_capture(first), _capture(second))
        self.assertEqual(first.revision, second.revision)
        self.assertEqual(tuple(first.events), tuple(second.events))

    def test_the_same_seed_reaches_the_same_state(self) -> None:
        states = []
        for _ in range(2):
            state = new_state(create_shuffled_wall(RandomSource(20260816)))
            state.deal()
            for seat in (Seat.EAST, Seat.SOUTH):
                tile = state.draw(seat)
                snapshot = state.legal_actions(seat)
                state.apply(
                    seat,
                    DiscardLegalAction(tile.id),
                    expected_revision=snapshot.revision,
                )
                if state.current_seat is None:
                    break
            states.append(state)

        self.assertEqual(_capture(states[0]), _capture(states[1]))

    def test_revision_increases_by_one_per_committed_transition(self) -> None:
        state = new_state(_build_wall(hands=_QUIET_HANDS, draws=_QUIET_DRAWS))

        self.assertEqual(state.revision, 0)
        state.deal()
        self.assertEqual(state.revision, 1)
        state.draw(Seat.EAST)
        self.assertEqual(state.revision, 2)
        snapshot = state.legal_actions(Seat.EAST)
        state.apply(Seat.EAST, snapshot.actions[0], expected_revision=snapshot.revision)
        self.assertEqual(state.revision, 3)

    def test_revision_is_local_to_each_round(self) -> None:
        first = _quiet_state()
        second = _quiet_state()

        self._play(first)

        self.assertEqual(second.revision, 1)
        self.assertNotEqual(first.revision, second.revision)


# --- E2: 反応解決・鳴き・立直・槓・フリテン --------------------------------

# EASTが7pを打ち、SOUTHがチー、WESTがロン、NORTHがポン・大明槓できる局面。
_REACTION_HANDS = {
    Seat.EAST: (
        "7p",
        "1m",
        "9m",
        "1s",
        "9s",
        "1z",
        "2z",
        "3z",
        "4z",
        "5z",
        "6z",
        "7z",
        "1p",
    ),
    Seat.SOUTH: (
        "5p",
        "6p",
        "1m",
        "9m",
        "1s",
        "9s",
        "1z",
        "2z",
        "3z",
        "4z",
        "5z",
        "6z",
        "7z",
    ),
    Seat.WEST: (
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
    ),
    Seat.NORTH: (
        "7p",
        "7p",
        "7p",
        "1m",
        "9m",
        "1s",
        "9s",
        "1z",
        "2z",
        "3z",
        "4z",
        "5z",
        "6z",
    ),
}
_REACTION_DRAWS = ("1z", "4p")

# WEST（両面）とNORTH（嵌張）の2席が同じ7pでロンできる局面。
_DOUBLE_RON_HANDS = {
    Seat.EAST: (
        "7p",
        "1m",
        "9m",
        "1s",
        "9s",
        "1z",
        "2z",
        "3z",
        "4z",
        "5z",
        "6z",
        "7z",
        "1p",
    ),
    Seat.SOUTH: (
        "1m",
        "4m",
        "7m",
        "1p",
        "4p",
        "7p",
        "1s",
        "4s",
        "7s",
        "1z",
        "2z",
        "3z",
        "4z",
    ),
    Seat.WEST: (
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
    ),
    Seat.NORTH: (
        "2m",
        "3m",
        "4m",
        "5m",
        "6m",
        "7m",
        "2p",
        "3p",
        "4p",
        "6p",
        "8p",
        "3s",
        "3s",
    ),
}

# EASTだけが門前聴牌で、立直宣言できる局面。
_RIICHI_HANDS = {
    Seat.EAST: (
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
    ),
    Seat.SOUTH: INERT_HAND,
    Seat.WEST: INERT_HAND,
    Seat.NORTH: INERT_HAND,
}
_RIICHI_DRAWS = ("5z", "6z", "5z", "6z", "5z", "6z", "5z", "6z")

# SOUTHが3pをポンし、4枚目の3pを引いて加槓する局面。WESTは4pをツモった
# 時点で3p/6p待ちの聴牌になり、加槓へ槍槓できる。
_KAKAN_HANDS = {
    Seat.EAST: (
        "3p",
        "1m",
        "4m",
        "7m",
        "1p",
        "7p",
        "1s",
        "4s",
        "7s",
        "1z",
        "2z",
        "3z",
        "4z",
    ),
    Seat.SOUTH: (
        "3p",
        "3p",
        "1m",
        "4m",
        "7m",
        "1p",
        "7p",
        "1s",
        "4s",
        "7s",
        "1z",
        "2z",
        "3z",
    ),
    Seat.WEST: (
        "2m",
        "3m",
        "4m",
        "5m",
        "6m",
        "7m",
        "7p",
        "8p",
        "9p",
        "5p",
        "2s",
        "2s",
        "9s",
    ),
    Seat.NORTH: (
        "1m",
        "4m",
        "7m",
        "9m",
        "1p",
        "7p",
        "1s",
        "4s",
        "7s",
        "1z",
        "2z",
        "3z",
        "4z",
    ),
}
_KAKAN_DRAWS = ("5z", "4p", "6z", "5z", "3p")

# EASTが1mの暗槓を持ち、NORTHが1m単騎の国士無双で待つ局面。
_ANKAN_HANDS = {
    Seat.EAST: (
        "1m",
        "1m",
        "1m",
        "1m",
        "2m",
        "3m",
        "4m",
        "5m",
        "6m",
        "7m",
        "8m",
        "2p",
        "3p",
    ),
    Seat.SOUTH: (
        "1z",
        "2z",
        "3z",
        "4z",
        "5z",
        "6z",
        "7z",
        "4p",
        "7p",
        "4s",
        "7s",
        "2s",
        "5s",
    ),
    Seat.WEST: (
        "1z",
        "2z",
        "3z",
        "4z",
        "5z",
        "6z",
        "7z",
        "5p",
        "8p",
        "3s",
        "6s",
        "9s",
        "9m",
    ),
    Seat.NORTH: (
        "9m",
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
    ),
}
_ANKAN_DRAWS = ("8s",)

_HEAD_BUMP_RULES = replace(
    RuleSet.default(),
    ron_resolution_policy=RonResolutionPolicy.HEAD_BUMP,
    triple_ron_abortive_draw=False,
)
_KOKUSHI_CHANKAN_RULES = replace(
    RuleSet.default(),
    kokushi_ankan_chankan_enabled=True,
)


def _reaction_state(**kwargs) -> RoundState:
    """EASTが7pを打ち、反応windowが開いた局面を返す。"""
    state = _dealt_state(
        hands=_REACTION_HANDS,
        draws=_REACTION_DRAWS,
        with_dead_wall=True,
        **kwargs,
    )
    draw_and_discard(state, Seat.EAST, "7p")
    return state


def _double_ron_state(**kwargs) -> RoundState:
    state = _dealt_state(
        hands=_DOUBLE_RON_HANDS,
        draws=_REACTION_DRAWS,
        with_dead_wall=True,
        **kwargs,
    )
    draw_and_discard(state, Seat.EAST, "7p")
    return state


def _riichi_state(**kwargs) -> RoundState:
    return _dealt_state(
        hands=_RIICHI_HANDS,
        draws=_RIICHI_DRAWS,
        with_dead_wall=True,
        **kwargs,
    )


def _declare_riichi(state: RoundState, seat: Seat = Seat.EAST) -> DiscardLegalAction:
    """`seat`がツモってから、立直を宣言できる打牌を1つ適用する。"""
    state.draw(seat)
    snapshot = state.legal_actions(seat)
    action = next(
        candidate
        for candidate in snapshot.actions
        if isinstance(candidate, DiscardLegalAction)
        and candidate.declaration is DiscardDeclaration.RIICHI
    )
    state.apply(seat, action, expected_revision=snapshot.revision)
    return action


def _kakan_declared_state(**kwargs) -> RoundState:
    """SOUTHが3pをポンし、4枚目で加槓を宣言した局面を返す。"""
    state = _dealt_state(
        hands=_KAKAN_HANDS,
        draws=_KAKAN_DRAWS,
        with_dead_wall=True,
        **kwargs,
    )
    draw_and_discard(state, Seat.EAST, "3p")
    resolve_with(state, {Seat.SOUTH: pon_action(state, Seat.SOUTH)})
    discard(state, Seat.SOUTH, "1z")
    draw_and_discard(state, Seat.WEST, "9s")
    play_quiet_turn(state)
    play_quiet_turn(state)
    state.draw(Seat.SOUTH)
    snapshot = state.legal_actions(Seat.SOUTH)
    state.apply(
        Seat.SOUTH,
        action_of_type(state, Seat.SOUTH, KakanLegalAction),
        expected_revision=snapshot.revision,
    )
    return state


def _ankan_state(**kwargs) -> RoundState:
    state = _dealt_state(
        hands=_ANKAN_HANDS,
        draws=_ANKAN_DRAWS,
        with_dead_wall=True,
        **kwargs,
    )
    state.draw(Seat.EAST)
    return state


def _declare_ankan(state: RoundState, seat: Seat = Seat.EAST) -> None:
    snapshot = state.legal_actions(seat)
    state.apply(
        seat,
        action_of_type(state, seat, AnkanLegalAction),
        expected_revision=snapshot.revision,
    )


class RoundStateRoundStartPointsTest(unittest.TestCase):
    """立直条件の判定に使う点数は、局開始時点のimmutable snapshotである。"""

    def test_requires_a_points_snapshot(self) -> None:
        with self.assertRaises(TypeError):
            RoundState(Wall(STANDARD_TILES[:60]))

    def test_exposes_the_snapshot_for_every_seat(self) -> None:
        points = {seat: 25_000 for seat in Seat}
        points[Seat.SOUTH] = 12_300

        state = new_state(Wall(STANDARD_TILES[:60]), round_start_points=points)

        self.assertEqual(dict(state.round_start_points), points)

    def test_rejects_an_incomplete_seat_mapping(self) -> None:
        with self.assertRaises(ValueError):
            new_state(
                Wall(STANDARD_TILES[:60]),
                round_start_points={Seat.EAST: 25_000, Seat.SOUTH: 25_000},
            )

    def test_rejects_a_mapping_with_a_key_that_is_not_a_seat(self) -> None:
        points = {seat: 25_000 for seat in Seat}
        points["extra"] = 25_000

        with self.assertRaises(TypeError):
            new_state(Wall(STANDARD_TILES[:60]), round_start_points=points)

    def test_rejects_non_integer_points(self) -> None:
        points = {seat: 25_000 for seat in Seat}
        points[Seat.WEST] = 25_000.0

        with self.assertRaises(TypeError):
            new_state(Wall(STANDARD_TILES[:60]), round_start_points=points)

    def test_rejects_a_mapping_that_is_not_a_mapping(self) -> None:
        with self.assertRaises(TypeError):
            new_state(
                Wall(STANDARD_TILES[:60]),
                round_start_points=[(seat, 25_000) for seat in Seat],
            )

    def test_copies_the_caller_mapping_defensively(self) -> None:
        points = {seat: 25_000 for seat in Seat}
        state = new_state(Wall(STANDARD_TILES[:60]), round_start_points=points)

        points[Seat.EAST] = 0

        self.assertEqual(state.round_start_points[Seat.EAST], 25_000)

    def test_the_exposed_snapshot_is_read_only(self) -> None:
        state = new_state(
            Wall(STANDARD_TILES[:60]),
            round_start_points={seat: 25_000 for seat in Seat},
        )

        with self.assertRaises(TypeError):
            state.round_start_points[Seat.EAST] = 0


class RoundStateReactionWindowTest(unittest.TestCase):
    def test_every_reacting_seat_shares_the_same_revision(self) -> None:
        state = _reaction_state()

        snapshots = [state.legal_actions(seat) for seat in state.reacting_seats]

        self.assertEqual(state.reacting_seats, (Seat.SOUTH, Seat.WEST, Seat.NORTH))
        self.assertEqual(
            {snapshot.revision for snapshot in snapshots}, {state.revision}
        )

    def test_a_seat_that_cannot_react_still_has_a_pass_only_choice(self) -> None:
        state = _double_ron_state()

        self.assertEqual(
            actions_of(state, Seat.SOUTH),
            (PassLegalAction(ReactionOrigin.DISCARD, state.pending_discard.tile.id),),
        )

    def test_the_discarding_seat_is_not_a_reacting_seat(self) -> None:
        state = _reaction_state()

        self.assertNotIn(Seat.EAST, state.reacting_seats)
        self.assertEqual(actions_of(state, Seat.EAST), ())

    def test_no_reaction_window_is_open_outside_the_reaction_phases(self) -> None:
        state = _quiet_state()

        self.assertEqual(state.reacting_seats, ())

    def test_all_pass_advances_to_the_next_draw(self) -> None:
        state = _reaction_state()

        resolution = resolve_all_pass(state)

        self.assertTrue(resolution.all_passed)
        self.assertIs(state.phase, RoundPhase.AWAITING_DRAW)
        self.assertIs(state.current_seat, Seat.SOUTH)
        self.assertIsNone(state.pending_discard)
        self.assertIsNone(state.pending_discarder)

    def test_a_successful_batch_advances_the_revision_exactly_once(self) -> None:
        state = _reaction_state()
        revision = state.revision

        resolve_all_pass(state)

        self.assertEqual(state.revision, revision + 1)

    def test_records_the_resolution_as_a_single_event(self) -> None:
        state = _reaction_state()

        resolution = resolve_all_pass(state)

        reaction_events = [
            event for event in state.events if isinstance(event, ReactionsResolvedEvent)
        ]
        self.assertEqual(len(reaction_events), 1)
        self.assertEqual(reaction_events[0].resolution, resolution)


class RoundStateReactionBatchAtomicityTest(unittest.TestCase):
    def _assert_rejected(self, state: RoundState, call) -> None:
        original = _capture(state)

        with self.assertRaises(IllegalOperationError):
            call()

        self.assertEqual(_capture(state), original)

    def test_rejects_a_batch_that_misses_a_reacting_seat(self) -> None:
        state = _reaction_state()
        choices = all_pass_choices(state)
        del choices[Seat.WEST]

        self._assert_rejected(
            state,
            lambda: state.resolve_reactions(
                choices,
                expected_revision=state.revision,
            ),
        )

    def test_rejects_a_batch_with_a_seat_that_cannot_react(self) -> None:
        state = _reaction_state()
        choices = all_pass_choices(state)
        choices[Seat.EAST] = PassLegalAction(
            ReactionOrigin.DISCARD,
            state.pending_discard.tile.id,
        )

        self._assert_rejected(
            state,
            lambda: state.resolve_reactions(
                choices,
                expected_revision=state.revision,
            ),
        )

    def test_rejects_a_batch_with_an_illegal_choice(self) -> None:
        state = _reaction_state()
        choices = all_pass_choices(state)
        choices[Seat.SOUTH] = RonLegalAction(
            ReactionOrigin.DISCARD,
            state.pending_discard.tile.id,
        )

        self._assert_rejected(
            state,
            lambda: state.resolve_reactions(
                choices,
                expected_revision=state.revision,
            ),
        )

    def test_rejects_a_batch_derived_from_a_stale_revision(self) -> None:
        state = _reaction_state()
        choices = all_pass_choices(state)

        original = _capture(state)
        with self.assertRaises(StaleActionError):
            state.resolve_reactions(choices, expected_revision=state.revision - 1)

        self.assertEqual(_capture(state), original)

    def test_rejects_a_batch_outside_a_reaction_window(self) -> None:
        state = _quiet_state()

        original = _capture(state)
        with self.assertRaises(IllegalOperationError):
            state.resolve_reactions({}, expected_revision=state.revision)

        self.assertEqual(_capture(state), original)

    def test_a_rejected_batch_leaves_seat_state_untouched(self) -> None:
        """失敗したbatchは、フリテン・一発・立直・eventも一切変えない。"""
        state = _reaction_state()
        choices = all_pass_choices(state)
        choices[Seat.WEST] = ron_action(state, Seat.WEST)
        del choices[Seat.NORTH]
        original = _capture(state)

        with self.assertRaises(IllegalActionError):
            state.resolve_reactions(choices, expected_revision=state.revision)

        self.assertEqual(_capture(state), original)
        self.assertEqual(state.furiten_reasons(Seat.WEST), frozenset())
        self.assertIsNone(state.pending_ron_resolution)

    def test_rejects_invalid_choice_containers(self) -> None:
        state = _reaction_state()
        original = _capture(state)

        with self.assertRaises(TypeError):
            state.resolve_reactions([], expected_revision=state.revision)
        with self.assertRaises(TypeError):
            state.resolve_reactions(
                {"south": pass_action(state, Seat.SOUTH)},
                expected_revision=state.revision,
            )
        with self.assertRaises(TypeError):
            state.resolve_reactions(
                {seat: "pass" for seat in state.reacting_seats},
                expected_revision=state.revision,
            )
        with self.assertRaises(TypeError):
            state.resolve_reactions(
                all_pass_choices(state),
                expected_revision="0",
            )

        self.assertEqual(_capture(state), original)

    def test_the_choice_iteration_order_does_not_change_the_result(self) -> None:
        forward_state = _reaction_state()
        reversed_state = _reaction_state()

        forward_choices = all_pass_choices(forward_state)
        forward_choices[Seat.NORTH] = pon_action(forward_state, Seat.NORTH)
        forward_choices[Seat.SOUTH] = chi_action(forward_state, Seat.SOUTH)
        reversed_choices = dict(
            reversed(
                list(
                    {
                        Seat.SOUTH: chi_action(reversed_state, Seat.SOUTH),
                        Seat.WEST: pass_action(reversed_state, Seat.WEST),
                        Seat.NORTH: pon_action(reversed_state, Seat.NORTH),
                    }.items()
                )
            )
        )

        forward = forward_state.resolve_reactions(
            forward_choices,
            expected_revision=forward_state.revision,
        )
        backward = reversed_state.resolve_reactions(
            reversed_choices,
            expected_revision=reversed_state.revision,
        )

        self.assertEqual(forward, backward)
        self.assertEqual(_capture(forward_state), _capture(reversed_state))


class RoundStateReactionPriorityTest(unittest.TestCase):
    def test_ron_beats_a_pon(self) -> None:
        state = _reaction_state()

        resolution = resolve_with(
            state,
            {
                Seat.WEST: ron_action(state, Seat.WEST),
                Seat.NORTH: pon_action(state, Seat.NORTH),
            },
        )

        self.assertIs(resolution.resolved_type, ReactionType.RON)
        self.assertEqual(state.melds(Seat.NORTH), ())
        self.assertIs(state.phase, RoundPhase.AWAITING_WIN_FINALIZATION)

    def test_ron_beats_a_daiminkan(self) -> None:
        state = _reaction_state()

        resolution = resolve_with(
            state,
            {
                Seat.WEST: ron_action(state, Seat.WEST),
                Seat.NORTH: daiminkan_action(state, Seat.NORTH),
            },
        )

        self.assertIs(resolution.resolved_type, ReactionType.RON)
        self.assertEqual(state.melds(Seat.NORTH), ())

    def test_ron_beats_a_chi(self) -> None:
        state = _reaction_state()

        resolution = resolve_with(
            state,
            {
                Seat.SOUTH: chi_action(state, Seat.SOUTH),
                Seat.WEST: ron_action(state, Seat.WEST),
            },
        )

        self.assertIs(resolution.resolved_type, ReactionType.RON)
        self.assertEqual(state.melds(Seat.SOUTH), ())

    def test_a_pon_beats_a_chi(self) -> None:
        state = _reaction_state()

        resolution = resolve_with(
            state,
            {
                Seat.SOUTH: chi_action(state, Seat.SOUTH),
                Seat.NORTH: pon_action(state, Seat.NORTH),
            },
        )

        self.assertIs(resolution.resolved_type, ReactionType.PON)
        self.assertIs(state.current_seat, Seat.NORTH)
        self.assertEqual(state.melds(Seat.SOUTH), ())

    def test_a_daiminkan_beats_a_chi(self) -> None:
        state = _reaction_state()

        resolution = resolve_with(
            state,
            {
                Seat.SOUTH: chi_action(state, Seat.SOUTH),
                Seat.NORTH: daiminkan_action(state, Seat.NORTH),
            },
        )

        self.assertIs(resolution.resolved_type, ReactionType.DAIMINKAN)
        self.assertIs(state.phase, RoundPhase.AWAITING_RINSHAN_DRAW)

    def test_multiple_ron_awards_every_selecting_seat(self) -> None:
        state = _double_ron_state()

        resolution = resolve_with(
            state,
            {
                Seat.WEST: ron_action(state, Seat.WEST),
                Seat.NORTH: ron_action(state, Seat.NORTH),
            },
        )

        self.assertEqual(resolution.ron_awarded_seats, (Seat.WEST, Seat.NORTH))
        self.assertEqual(
            state.pending_ron_resolution.winner_seats,
            (Seat.WEST, Seat.NORTH),
        )

    def test_head_bump_awards_only_the_nearest_seat(self) -> None:
        state = _double_ron_state(rules=_HEAD_BUMP_RULES)

        resolution = resolve_with(
            state,
            {
                Seat.WEST: ron_action(state, Seat.WEST),
                Seat.NORTH: ron_action(state, Seat.NORTH),
            },
        )

        self.assertEqual(resolution.ron_selected_seats, (Seat.WEST, Seat.NORTH))
        self.assertEqual(resolution.ron_awarded_seats, (Seat.WEST,))
        self.assertEqual(state.pending_ron_resolution.winner_seats, (Seat.WEST,))

    def test_a_head_bumped_seat_is_not_treated_as_a_missed_ron(self) -> None:
        """頭ハネで成立しなかったロン選択者を見逃しフリテンにしない。"""
        state = _double_ron_state(rules=_HEAD_BUMP_RULES)

        resolution = resolve_with(
            state,
            {
                Seat.WEST: ron_action(state, Seat.WEST),
                Seat.NORTH: ron_action(state, Seat.NORTH),
            },
        )

        self.assertNotIn(Seat.NORTH, resolution.ron_passed_seats)
        self.assertEqual(state.furiten_reasons(Seat.NORTH), frozenset())
        self.assertFalse(
            any(isinstance(event, MissedRonRecordedEvent) for event in state.events)
        )

    def test_a_capable_seat_that_passed_is_recorded_as_a_missed_ron(self) -> None:
        state = _double_ron_state()

        resolution = resolve_with(
            state,
            {Seat.WEST: ron_action(state, Seat.WEST)},
        )

        self.assertEqual(resolution.ron_passed_seats, frozenset({Seat.NORTH}))
        self.assertEqual(
            state.furiten_reasons(Seat.NORTH),
            frozenset({FuritenReason.TEMPORARY}),
        )


class RoundStateCallTest(unittest.TestCase):
    def test_a_pon_moves_tile_ownership_and_the_turn(self) -> None:
        state = _reaction_state()
        target_tile = state.pending_discard.tile
        action = pon_action(state, Seat.NORTH)
        hand_before = {tile.id for tile in state.hand_tiles(Seat.NORTH)}

        resolve_with(state, {Seat.NORTH: action})

        meld = state.melds(Seat.NORTH)[0]
        self.assertEqual(meld.called_tile, target_tile)
        self.assertIs(meld.source_seat, Seat.EAST)
        self.assertEqual(
            {tile.id for tile in meld.consumed_tiles},
            set(action.consumed_tile_ids),
        )
        self.assertEqual(
            {tile.id for tile in state.hand_tiles(Seat.NORTH)},
            hand_before - set(action.consumed_tile_ids),
        )
        self.assertIs(state.discards(Seat.EAST)[-1].called_by, Seat.NORTH)
        self.assertIs(state.phase, RoundPhase.AWAITING_DISCARD)
        self.assertIs(state.current_seat, Seat.NORTH)
        self.assertIsNone(state.drawn_tile_id)

    def test_a_called_discard_stays_in_the_source_river(self) -> None:
        """鳴かれた捨て牌の記録は放銃者の河に残り、所有だけがmeldへ移る。"""
        state = _reaction_state()
        target_tile = state.pending_discard.tile

        resolve_with(state, {Seat.NORTH: pon_action(state, Seat.NORTH)})

        river_tile_ids = {discard.tile.id for discard in state.discards(Seat.EAST)}
        meld_tile_ids = {
            tile.id for meld in state.melds(Seat.NORTH) for tile in meld.tiles
        }
        self.assertIn(target_tile.id, river_tile_ids)
        self.assertIn(target_tile.id, meld_tile_ids)

    def test_a_chi_leaves_the_caller_awaiting_a_discard_without_a_drawn_tile(
        self,
    ) -> None:
        state = _reaction_state()

        resolve_with(state, {Seat.SOUTH: chi_action(state, Seat.SOUTH)})

        self.assertIs(state.phase, RoundPhase.AWAITING_DISCARD)
        self.assertIs(state.current_seat, Seat.SOUTH)
        self.assertIsNone(state.drawn_tile_id)
        self.assertNotEqual(actions_of(state, Seat.SOUTH), ())

    def test_a_daiminkan_moves_to_a_rinshan_draw(self) -> None:
        state = _reaction_state()

        resolve_with(state, {Seat.NORTH: daiminkan_action(state, Seat.NORTH)})

        self.assertIs(state.phase, RoundPhase.AWAITING_RINSHAN_DRAW)
        self.assertIs(state.current_seat, Seat.NORTH)
        self.assertIsNone(state.drawn_tile_id)
        self.assertEqual(len(state.melds(Seat.NORTH)), 1)

    def test_a_call_records_a_meld_event(self) -> None:
        state = _reaction_state()

        resolve_with(state, {Seat.SOUTH: chi_action(state, Seat.SOUTH)})

        meld_events = [
            event for event in state.events if isinstance(event, MeldCalledEvent)
        ]
        self.assertEqual(len(meld_events), 1)
        self.assertIs(meld_events[0].seat, Seat.SOUTH)
        self.assertEqual(meld_events[0].meld, state.melds(Seat.SOUTH)[0])

    def test_physical_tiles_are_conserved_across_a_call(self) -> None:
        state = _reaction_state()
        expected_tile_ids = _owned_tile_ids(state)

        resolve_with(state, {Seat.NORTH: pon_action(state, Seat.NORTH)})

        self.assertEqual(_owned_tile_ids(state), expected_tile_ids)


def _owned_tile_ids(state: RoundState) -> frozenset[int]:
    """局全体で所有されている物理牌IDを集める。"""
    owned = {tile.id for tile in (*state.remaining_tiles, *state.dead_wall_tiles)}
    for seat in Seat:
        owned |= {tile.id for tile in state.hand_tiles(seat)}
        owned |= {
            discard.tile.id
            for discard in state.discards(seat)
            if discard.called_by is None
        }
        owned |= {tile.id for meld in state.melds(seat) for tile in meld.tiles}
    return frozenset(owned)


class RoundStateRiichiTest(unittest.TestCase):
    def test_a_declaration_is_pending_until_the_reactions_resolve(self) -> None:
        state = _riichi_declaration_state()

        self.assertIs(state.phase, RoundPhase.AWAITING_REACTIONS)
        self.assertIsNotNone(state.pending_riichi_declaration)
        self.assertIs(state.pending_riichi_declaration.seat, Seat.EAST)
        self.assertFalse(state.is_riichi_established(Seat.EAST))
        self.assertEqual(state.riichi_finalizations, ())
        self.assertEqual(state.riichi_contributions, ())

    def test_an_unclaimed_declaration_establishes_riichi_with_ippatsu(self) -> None:
        state = _riichi_state()

        _declare_riichi(state)

        self.assertTrue(state.is_riichi_established(Seat.EAST))
        self.assertIs(state.riichi_status(Seat.EAST), RiichiStatus.DOUBLE_RIICHI)
        self.assertTrue(state.is_ippatsu(Seat.EAST))
        self.assertIsNone(state.pending_riichi_declaration)
        self.assertEqual(len(state.riichi_finalizations), 1)

    def test_an_established_riichi_records_a_contribution_fact(self) -> None:
        state = _riichi_state()

        _declare_riichi(state)

        self.assertEqual(
            state.riichi_contributions,
            (RiichiContribution(Seat.EAST, state.rules.riichi_stick_points),),
        )
        self.assertEqual(
            dict(state.riichi_payment_deltas),
            {
                Seat.EAST: -state.rules.riichi_stick_points,
                Seat.SOUTH: 0,
                Seat.WEST: 0,
                Seat.NORTH: 0,
            },
        )

    def test_the_contribution_follows_the_configured_stick_points(self) -> None:
        """供託額は`riichi_stick_points`であり、成立条件の点数とは別である。"""
        rules = replace(
            RuleSet.default(),
            riichi_minimum_points=1_500,
            riichi_stick_points=2_000,
        )
        state = _riichi_state(rules=rules)

        _declare_riichi(state)

        self.assertEqual(
            state.riichi_contributions,
            (RiichiContribution(Seat.EAST, 2_000),),
        )

    def test_the_points_snapshot_does_not_change_when_riichi_is_established(
        self,
    ) -> None:
        state = _riichi_state()
        before = dict(state.round_start_points)

        _declare_riichi(state)

        self.assertEqual(dict(state.round_start_points), before)

    def test_a_seat_below_the_minimum_points_has_no_riichi_discard(self) -> None:
        points = starting_points()
        points[Seat.EAST] = RuleSet.default().riichi_minimum_points - 1
        state = _riichi_state(round_start_points=points)

        state.draw(Seat.EAST)

        self.assertFalse(
            any(
                isinstance(action, DiscardLegalAction)
                and action.declaration is DiscardDeclaration.RIICHI
                for action in actions_of(state, Seat.EAST)
            )
        )

    def test_exactly_the_minimum_points_allows_a_riichi_discard(self) -> None:
        points = starting_points()
        points[Seat.EAST] = RuleSet.default().riichi_minimum_points
        state = _riichi_state(round_start_points=points)

        state.draw(Seat.EAST)

        self.assertTrue(
            any(
                isinstance(action, DiscardLegalAction)
                and action.declaration is DiscardDeclaration.RIICHI
                for action in actions_of(state, Seat.EAST)
            )
        )

    def test_a_ruleset_without_a_minimum_allows_riichi_from_any_score(self) -> None:
        rules = replace(RuleSet.default(), riichi_minimum_points=None)
        points = {seat: -5_000 for seat in Seat}
        state = _riichi_state(rules=rules, round_start_points=points)

        state.draw(Seat.EAST)

        self.assertTrue(
            any(
                isinstance(action, DiscardLegalAction)
                and action.declaration is DiscardDeclaration.RIICHI
                for action in actions_of(state, Seat.EAST)
            )
        )

    def test_an_established_riichi_seat_may_only_discard_the_drawn_tile(self) -> None:
        state = _riichi_state()
        _declare_riichi(state)
        advance_to_seat(state, Seat.EAST)

        drawn_tile = state.draw(Seat.EAST)

        self.assertEqual(
            actions_of(state, Seat.EAST),
            (DiscardLegalAction(drawn_tile.id),),
        )

    def test_ippatsu_ends_on_the_declaring_seats_next_discard(self) -> None:
        state = _riichi_state()
        _declare_riichi(state)
        self.assertTrue(state.is_ippatsu(Seat.EAST))

        advance_to_seat(state, Seat.EAST)
        self.assertTrue(state.is_ippatsu(Seat.EAST))
        draw_and_discard(state, Seat.EAST)

        self.assertFalse(state.is_ippatsu(Seat.EAST))
        self.assertTrue(state.is_riichi_established(Seat.EAST))

    def test_records_declaration_and_finalization_events(self) -> None:
        state = _riichi_state()

        _declare_riichi(state)

        event_types = [type(event) for event in state.events]
        self.assertIn(RiichiDeclaredEvent, event_types)
        self.assertIn(RiichiFinalizedEvent, event_types)
        self.assertLess(
            event_types.index(RiichiDeclaredEvent),
            event_types.index(RiichiFinalizedEvent),
        )


class RoundStateRiichiFinalizationTest(unittest.TestCase):
    """宣言牌への反応によって、立直の成立可否と一発が変わることを固定する。"""

    def test_a_ron_on_the_declaration_tile_fails_the_riichi(self) -> None:
        state = _riichi_declaration_state()

        resolve_with(state, {Seat.WEST: ron_action(state, Seat.WEST)})

        self.assertFalse(state.is_riichi_established(Seat.EAST))
        self.assertEqual(state.riichi_contributions, ())
        self.assertEqual(dict(state.riichi_payment_deltas)[Seat.EAST], 0)
        finalization = state.riichi_finalizations[-1]
        self.assertIs(
            finalization.outcome,
            RiichiDeclarationOutcome.FAILED_BY_RON,
        )

    def test_an_unclaimed_declaration_tile_establishes_riichi(self) -> None:
        state = _riichi_declaration_state()

        resolve_all_pass(state)

        self.assertTrue(state.is_riichi_established(Seat.EAST))
        self.assertTrue(state.is_ippatsu(Seat.EAST))
        self.assertEqual(len(state.riichi_contributions), 1)

    def test_a_called_declaration_tile_establishes_riichi_without_ippatsu(self) -> None:
        state = _riichi_declaration_state()

        resolve_with(state, {Seat.NORTH: pon_action(state, Seat.NORTH)})

        self.assertTrue(state.is_riichi_established(Seat.EAST))
        self.assertFalse(state.is_ippatsu(Seat.EAST))
        self.assertEqual(len(state.riichi_contributions), 1)
        self.assertTrue(state.riichi_finalizations[-1].established_after_call)


def _riichi_declaration_state(**kwargs) -> RoundState:
    """EASTが7pで立直を宣言し、WESTがロン、NORTHがポンできる局面を返す。

    EASTの手牌を門前聴牌にし、7pを宣言牌にできるようにする。
    """
    hands = {
        Seat.EAST: (
            "7p",
            "2m",
            "3m",
            "4m",
            "5m",
            "6m",
            "7m",
            "2p",
            "3p",
            "4p",
            "5s",
            "6s",
            "7s",
        ),
        Seat.SOUTH: (
            "7p",
            "8s",
            "8m",
            "8m",
            "8m",
            "8m",
            "1z",
            "2z",
            "3z",
            "4z",
            "5z",
            "6z",
            "7z",
        ),
        Seat.WEST: (
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
        ),
        Seat.NORTH: (
            "7p",
            "7p",
            "1m",
            "9m",
            "1s",
            "9s",
            "1z",
            "2z",
            "3z",
            "4z",
            "5z",
            "6z",
            "9p",
        ),
    }
    state = _dealt_state(hands=hands, draws=("8s",), with_dead_wall=True, **kwargs)
    state.draw(Seat.EAST)
    snapshot = state.legal_actions(Seat.EAST)
    seven_pin = next(
        tile
        for tile in state.hand_tiles(Seat.EAST)
        if tile.tile_type == _tile_type("7p")
    )
    state.apply(
        Seat.EAST,
        DiscardLegalAction(seven_pin.id, DiscardDeclaration.RIICHI),
        expected_revision=snapshot.revision,
    )
    return state


class RoundStateFuritenTest(unittest.TestCase):
    def test_a_missed_ron_creates_temporary_furiten(self) -> None:
        state = _reaction_state()

        resolve_all_pass(state)

        self.assertEqual(
            state.furiten_reasons(Seat.WEST),
            frozenset({FuritenReason.TEMPORARY}),
        )
        self.assertTrue(state.is_furiten(Seat.WEST))

    def test_temporary_furiten_clears_on_the_seats_own_draw(self) -> None:
        state = _reaction_state()
        resolve_all_pass(state)
        self.assertTrue(state.is_furiten(Seat.WEST))

        advance_to_seat(state, Seat.WEST)
        state.draw(Seat.WEST)

        self.assertEqual(state.furiten_reasons(Seat.WEST), frozenset())

    def test_a_missed_ron_records_a_furiten_event(self) -> None:
        state = _reaction_state()

        resolve_all_pass(state)

        events = [
            event for event in state.events if isinstance(event, MissedRonRecordedEvent)
        ]
        self.assertEqual(len(events), 1)
        self.assertIs(events[0].seat, Seat.WEST)
        self.assertIs(events[0].reason, FuritenReason.TEMPORARY)

    def test_a_missed_ron_after_riichi_lasts_for_the_rest_of_the_round(self) -> None:
        state = _riichi_declaration_state()
        resolve_all_pass(state)
        self.assertTrue(state.is_riichi_established(Seat.EAST))

        # 立直したEASTが、和了牌である8sの打牌を見逃す。
        advance_to_seat(state, Seat.SOUTH)
        draw_and_discard(state, Seat.SOUTH, "8s")
        self.assertIn(Seat.EAST, state.reacting_seats)
        self.assertTrue(has_action_of_type(state, Seat.EAST, RonLegalAction))
        resolve_all_pass(state)

        self.assertEqual(
            state.furiten_reasons(Seat.EAST),
            frozenset({FuritenReason.RIICHI}),
        )

        advance_to_seat(state, Seat.EAST)
        state.draw(Seat.EAST)

        self.assertEqual(
            state.furiten_reasons(Seat.EAST),
            frozenset({FuritenReason.RIICHI}),
        )

    def test_a_furiten_seat_is_not_offered_a_ron_on_the_same_tile(self) -> None:
        state = _riichi_declaration_state()
        resolve_all_pass(state)
        self.assertTrue(state.is_furiten(Seat.WEST))

        draw_and_discard(state, Seat.SOUTH, "7p")

        self.assertIn(Seat.WEST, state.reacting_seats)
        self.assertFalse(has_action_of_type(state, Seat.WEST, RonLegalAction))

    def test_a_call_by_another_seat_cancels_an_ippatsu_window(self) -> None:
        state = _riichi_declaration_state()
        resolve_all_pass(state)
        self.assertTrue(state.is_ippatsu(Seat.EAST))

        draw_and_discard(state, Seat.SOUTH, "7p")
        resolve_with(state, {Seat.NORTH: pon_action(state, Seat.NORTH)})

        self.assertFalse(state.is_ippatsu(Seat.EAST))
        self.assertTrue(state.is_riichi_established(Seat.EAST))

    def test_discarding_a_winning_tile_type_creates_discard_furiten(self) -> None:
        state = _reaction_state()
        resolve_with(state, {Seat.SOUTH: chi_action(state, Seat.SOUTH)})
        discard(state, Seat.SOUTH, "9m")
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)
        advance_to_seat(state, Seat.WEST)

        # WESTは4p/7p待ちであり、7pを自分で打つと河由来のフリテンになる。
        draw_and_discard(state, Seat.WEST, "4p")
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)

        self.assertEqual(
            state.furiten_reasons(Seat.WEST),
            frozenset({FuritenReason.DISCARD}),
        )


class RoundStateKakanTest(unittest.TestCase):
    def test_a_kakan_declaration_keeps_the_original_pon(self) -> None:
        """槍槓が解決するまで、元のポンを破壊的に書き換えない。"""
        state = _kakan_declared_state()

        self.assertIs(state.phase, RoundPhase.AWAITING_KAKAN_REACTIONS)
        self.assertIs(state.current_seat, Seat.SOUTH)
        self.assertIsNotNone(state.pending_kakan)
        self.assertEqual([type(meld) for meld in state.melds(Seat.SOUTH)], [Pon])
        self.assertIsNotNone(state.drawn_tile_id)

    def test_a_kakan_declaration_records_an_event(self) -> None:
        state = _kakan_declared_state()

        declared = [
            event for event in state.events if isinstance(event, KanDeclaredEvent)
        ]
        self.assertEqual(len(declared), 1)
        self.assertIs(declared[0].seat, Seat.SOUTH)
        self.assertFalse(
            any(isinstance(event, KanConfirmedEvent) for event in state.events)
        )

    def test_a_chankan_ron_prevents_the_kakan(self) -> None:
        state = _kakan_declared_state()

        resolution = resolve_with(state, {Seat.WEST: ron_action(state, Seat.WEST)})

        self.assertIs(resolution.origin, ReactionOrigin.KAKAN)
        self.assertIs(state.phase, RoundPhase.AWAITING_WIN_FINALIZATION)
        self.assertEqual([type(meld) for meld in state.melds(Seat.SOUTH)], [Pon])
        self.assertIsNone(state.pending_kakan)
        self.assertTrue(state.pending_ron_resolution.is_chankan)
        self.assertEqual(state.pending_ron_resolution.winner_seats, (Seat.WEST,))

    def test_an_unclaimed_kakan_is_confirmed_and_leads_to_a_rinshan_draw(self) -> None:
        state = _kakan_declared_state()

        resolve_all_pass(state)

        self.assertIs(state.phase, RoundPhase.AWAITING_RINSHAN_DRAW)
        self.assertIs(state.current_seat, Seat.SOUTH)
        self.assertEqual([type(meld) for meld in state.melds(Seat.SOUTH)], [Kakan])
        self.assertIsNone(state.drawn_tile_id)
        self.assertTrue(
            any(isinstance(event, KanConfirmedEvent) for event in state.events)
        )

    def test_the_kakan_reaction_window_covers_the_other_three_seats(self) -> None:
        state = _kakan_declared_state()

        self.assertEqual(state.reacting_seats, (Seat.WEST, Seat.NORTH, Seat.EAST))
        for seat in state.reacting_seats:
            with self.subTest(seat=seat):
                self.assertTrue(has_action_of_type(state, seat, PassLegalAction))
        self.assertEqual(actions_of(state, Seat.SOUTH), ())

    def test_physical_tiles_are_conserved_through_a_kakan(self) -> None:
        state = _kakan_declared_state()
        expected_tile_ids = _owned_tile_ids(state)

        resolve_all_pass(state)

        self.assertEqual(_owned_tile_ids(state), expected_tile_ids)


class RoundStateAnkanTest(unittest.TestCase):
    def test_an_ankan_without_a_chankan_candidate_is_confirmed_at_once(self) -> None:
        state = _ankan_state()

        _declare_ankan(state)

        self.assertIs(state.phase, RoundPhase.AWAITING_RINSHAN_DRAW)
        self.assertIs(state.current_seat, Seat.EAST)
        self.assertEqual([type(meld) for meld in state.melds(Seat.EAST)], [Ankan])
        self.assertIsNone(state.pending_ankan)
        self.assertTrue(state.is_menzen(Seat.EAST))

    def test_an_ankan_reveals_its_kan_dora_immediately(self) -> None:
        """暗槓の槓ドラは`KanDoraRevealPolicy`の対象外で、成立と同時に開く。"""
        state = _ankan_state()
        revealed_before = len(state.revealed_dora_indicators)

        _declare_ankan(state)

        self.assertEqual(len(state.revealed_dora_indicators), revealed_before + 1)
        self.assertEqual(state.pending_kan_dora_reveals, ())

    def test_an_allowed_ankan_chankan_opens_a_reaction_window(self) -> None:
        state = _ankan_state(rules=_KOKUSHI_CHANKAN_RULES)

        _declare_ankan(state)

        self.assertIs(state.phase, RoundPhase.AWAITING_ANKAN_REACTIONS)
        self.assertIs(state.current_seat, Seat.EAST)
        self.assertIsNotNone(state.pending_ankan)
        self.assertEqual(state.melds(Seat.EAST), ())
        self.assertIsNotNone(state.drawn_tile_id)
        self.assertTrue(has_action_of_type(state, Seat.NORTH, RonLegalAction))

    def test_only_a_kokushi_hand_may_rob_an_ankan(self) -> None:
        state = _ankan_state(rules=_KOKUSHI_CHANKAN_RULES)

        _declare_ankan(state)

        self.assertFalse(has_action_of_type(state, Seat.SOUTH, RonLegalAction))
        self.assertFalse(has_action_of_type(state, Seat.WEST, RonLegalAction))

    def test_a_prohibited_ankan_chankan_offers_no_ron(self) -> None:
        state = _ankan_state()

        _declare_ankan(state)

        self.assertIs(state.phase, RoundPhase.AWAITING_RINSHAN_DRAW)

    def test_an_ankan_chankan_ron_prevents_the_ankan(self) -> None:
        state = _ankan_state(rules=_KOKUSHI_CHANKAN_RULES)
        _declare_ankan(state)
        hand_size = len(state.hand_tiles(Seat.EAST))

        resolution = resolve_with(state, {Seat.NORTH: ron_action(state, Seat.NORTH)})

        self.assertIs(resolution.origin, ReactionOrigin.ANKAN)
        self.assertIs(state.phase, RoundPhase.AWAITING_WIN_FINALIZATION)
        self.assertEqual(state.melds(Seat.EAST), ())
        self.assertEqual(len(state.hand_tiles(Seat.EAST)), hand_size)
        self.assertIsNone(state.pending_ankan)

    def test_an_unclaimed_ankan_chankan_confirms_the_ankan(self) -> None:
        state = _ankan_state(rules=_KOKUSHI_CHANKAN_RULES)
        _declare_ankan(state)

        resolve_all_pass(state)

        self.assertIs(state.phase, RoundPhase.AWAITING_RINSHAN_DRAW)
        self.assertEqual([type(meld) for meld in state.melds(Seat.EAST)], [Ankan])
        self.assertEqual(
            state.furiten_reasons(Seat.NORTH),
            frozenset({FuritenReason.TEMPORARY}),
        )

    def test_physical_tiles_are_conserved_through_an_ankan(self) -> None:
        state = _ankan_state()
        expected_tile_ids = _owned_tile_ids(state)

        _declare_ankan(state)

        self.assertEqual(_owned_tile_ids(state), expected_tile_ids)


class RoundStateRinshanDrawTest(unittest.TestCase):
    def test_a_rinshan_draw_moves_a_dead_wall_tile_into_the_hand(self) -> None:
        state = _ankan_state()
        _declare_ankan(state)
        rinshan_before = state.remaining_rinshan_count
        live_before = state.remaining_count
        hand_before = len(state.hand_tiles(Seat.EAST))

        tile = state.draw_rinshan(Seat.EAST)

        self.assertIs(state.phase, RoundPhase.AWAITING_DISCARD)
        self.assertIs(state.drawn_tile_source, DrawSource.RINSHAN)
        self.assertEqual(state.drawn_tile_id, tile.id)
        self.assertEqual(len(state.hand_tiles(Seat.EAST)), hand_before + 1)
        self.assertEqual(state.remaining_rinshan_count, rinshan_before - 1)
        self.assertEqual(state.remaining_count, live_before - 1)

    def test_a_rinshan_draw_records_its_own_draw_source(self) -> None:
        state = _ankan_state()
        _declare_ankan(state)

        state.draw_rinshan(Seat.EAST)

        self.assertEqual(
            state.events[-1],
            TileDrawnEvent(Seat.EAST, state.drawn_tile, DrawSource.RINSHAN),
        )

    def test_only_the_current_seat_may_draw_a_rinshan_tile(self) -> None:
        state = _ankan_state()
        _declare_ankan(state)
        original = _capture(state)

        with self.assertRaises(IllegalOperationError):
            state.draw_rinshan(Seat.SOUTH)

        self.assertEqual(_capture(state), original)

    def test_a_rinshan_draw_is_rejected_outside_its_phase(self) -> None:
        state = _quiet_state()
        original = _capture(state)

        with self.assertRaises(IllegalOperationError):
            state.draw_rinshan(Seat.EAST)

        self.assertEqual(_capture(state), original)

    def test_a_normal_draw_is_rejected_while_awaiting_a_rinshan_draw(self) -> None:
        state = _ankan_state()
        _declare_ankan(state)

        with self.assertRaises(IllegalOperationError):
            state.draw(Seat.EAST)


class RoundStateKanDoraRevealTest(unittest.TestCase):
    """槓ドラの公開タイミングは、槓の種類ごとに異なることを固定する。

    ```text
    Ankan      policy対象外。成立と同時に公開する
    Kakan      槍槓が全員パスして成立が確定した時点で公開する
    Daiminkan  IMMEDIATE: 成立時
               DELAY:     直後の打牌がロン以外で解決した時
    ```

    `KanDoraRevealPolicy`で公開タイミングが変わるのは大明槓だけである。
    加槓の「遅延」は槍槓の解決までであり、次の打牌までは待たない。
    """

    def test_a_delayed_policy_holds_the_daiminkan_dora_until_the_discard_resolves(
        self,
    ) -> None:
        state = _reaction_state()
        revealed_before = len(state.revealed_dora_indicators)

        resolve_with(state, {Seat.NORTH: daiminkan_action(state, Seat.NORTH)})

        self.assertEqual(state.pending_kan_dora_reveals, (Seat.NORTH,))
        self.assertEqual(len(state.revealed_dora_indicators), revealed_before)

        state.draw_rinshan(Seat.NORTH)
        discard_drawn_tile(state, Seat.NORTH)
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)

        self.assertEqual(state.pending_kan_dora_reveals, ())
        self.assertEqual(len(state.revealed_dora_indicators), revealed_before + 1)

    def test_an_immediate_policy_reveals_the_daiminkan_dora_on_confirmation(
        self,
    ) -> None:
        rules = replace(
            RuleSet.default(),
            kan_dora_reveal_policy=KanDoraRevealPolicy.IMMEDIATE_ON_KAN_CONFIRMATION,
        )
        state = _reaction_state(rules=rules)
        revealed_before = len(state.revealed_dora_indicators)

        resolve_with(state, {Seat.NORTH: daiminkan_action(state, Seat.NORTH)})

        self.assertEqual(state.pending_kan_dora_reveals, ())
        self.assertEqual(len(state.revealed_dora_indicators), revealed_before + 1)
        self.assertTrue(
            any(isinstance(event, DoraIndicatorRevealedEvent) for event in state.events)
        )

    def test_a_delayed_policy_reveals_the_kakan_dora_when_the_chankan_window_closes(
        self,
    ) -> None:
        """加槓は`DELAY_OPEN_KAN_DORA`でも、次の打牌まで公開を待たない。"""
        state = _kakan_declared_state()
        self.assertIs(
            state.rules.kan_dora_reveal_policy,
            KanDoraRevealPolicy.DELAY_OPEN_KAN_DORA,
        )
        revealed_before = len(state.revealed_dora_indicators)

        resolve_all_pass(state)

        self.assertEqual(len(state.revealed_dora_indicators), revealed_before + 1)
        self.assertEqual(state.pending_kan_dora_reveals, ())

    def test_the_kakan_dora_is_not_revealed_again_on_the_following_discard(
        self,
    ) -> None:
        state = _kakan_declared_state()
        resolve_all_pass(state)
        revealed_after_confirmation = len(state.revealed_dora_indicators)

        state.draw_rinshan(Seat.SOUTH)
        discard_drawn_tile(state, Seat.SOUTH)
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)

        self.assertEqual(
            len(state.revealed_dora_indicators),
            revealed_after_confirmation,
        )
        self.assertEqual(state.pending_kan_dora_reveals, ())

    def test_an_immediate_policy_reveals_the_kakan_dora_at_the_same_moment(
        self,
    ) -> None:
        rules = replace(
            RuleSet.default(),
            kan_dora_reveal_policy=KanDoraRevealPolicy.IMMEDIATE_ON_KAN_CONFIRMATION,
        )
        state = _kakan_declared_state(rules=rules)
        revealed_before = len(state.revealed_dora_indicators)

        resolve_all_pass(state)

        self.assertEqual(len(state.revealed_dora_indicators), revealed_before + 1)
        self.assertEqual(state.pending_kan_dora_reveals, ())

    def test_a_kakan_never_queues_a_delayed_reveal(self) -> None:
        """加槓は宣言中も成立後も、大明槓用の保留listへ積まれない。"""
        state = _kakan_declared_state()

        self.assertEqual(state.pending_kan_dora_reveals, ())

        resolve_all_pass(state)

        self.assertEqual(state.pending_kan_dora_reveals, ())

    def test_an_ankan_reveals_its_dora_under_either_policy(self) -> None:
        for policy in KanDoraRevealPolicy:
            with self.subTest(policy=policy):
                rules = replace(RuleSet.default(), kan_dora_reveal_policy=policy)
                state = _ankan_state(rules=rules)
                revealed_before = len(state.revealed_dora_indicators)

                _declare_ankan(state)

                self.assertEqual(
                    len(state.revealed_dora_indicators),
                    revealed_before + 1,
                )
                self.assertEqual(state.pending_kan_dora_reveals, ())

    def test_a_chankan_never_reveals_the_kakan_dora(self) -> None:
        """槍槓で加槓が成立しなかった場合、槓ドラは増えず保留にも残らない。"""
        for policy in KanDoraRevealPolicy:
            with self.subTest(policy=policy):
                rules = replace(RuleSet.default(), kan_dora_reveal_policy=policy)
                state = _kakan_declared_state(rules=rules)
                revealed_before = len(state.revealed_dora_indicators)

                resolve_with(state, {Seat.WEST: ron_action(state, Seat.WEST)})

                self.assertEqual(
                    len(state.revealed_dora_indicators),
                    revealed_before,
                )
                self.assertEqual(state.pending_kan_dora_reveals, ())


class RoundStatePendingRonResolutionTest(unittest.TestCase):
    def test_keeps_the_facts_that_win_finalization_needs(self) -> None:
        state = _double_ron_state()
        target_tile = state.pending_discard.tile

        resolution = resolve_with(
            state,
            {
                Seat.WEST: ron_action(state, Seat.WEST),
                Seat.NORTH: ron_action(state, Seat.NORTH),
            },
        )

        pending = state.pending_ron_resolution
        self.assertIs(pending.origin, ReactionOrigin.DISCARD)
        self.assertIs(pending.source_seat, Seat.EAST)
        self.assertEqual(pending.target_tile, target_tile)
        self.assertEqual(pending.winner_seats, (Seat.WEST, Seat.NORTH))
        self.assertEqual(pending.resolution, resolution)
        self.assertFalse(pending.is_chankan)
        self.assertFalse(pending.is_last_tile)

    def test_the_same_reaction_window_cannot_be_resolved_twice(self) -> None:
        state = _reaction_state()
        choices = all_pass_choices(state)
        choices[Seat.WEST] = ron_action(state, Seat.WEST)
        state.resolve_reactions(choices, expected_revision=state.revision)
        original = _capture(state)

        with self.assertRaises(IllegalOperationError):
            state.resolve_reactions(choices, expected_revision=state.revision)

        self.assertEqual(_capture(state), original)

    def test_no_seat_has_a_legal_action_while_awaiting_win_finalization(self) -> None:
        state = _reaction_state()
        resolve_with(state, {Seat.WEST: ron_action(state, Seat.WEST)})

        self.assertIs(state.phase, RoundPhase.AWAITING_WIN_FINALIZATION)
        self.assertEqual(state.reacting_seats, ())
        for seat in Seat:
            with self.subTest(seat=seat):
                self.assertEqual(actions_of(state, seat), ())

    def test_a_ron_does_not_finish_the_round(self) -> None:
        """E2はロンの成立者確定までで、終局commitはE3の責務である。"""
        state = _reaction_state()

        resolve_with(state, {Seat.WEST: ron_action(state, Seat.WEST)})

        self.assertIsNot(state.phase, RoundPhase.FINISHED)


class RoundStateApplyBoundaryTest(unittest.TestCase):
    def test_reaction_actions_are_not_accepted_through_apply(self) -> None:
        """反応は席ごとに逐次commitせず、必ずbatchで解決する。"""
        state = _reaction_state()
        original = _capture(state)

        with self.assertRaises(IllegalActionError):
            state.apply(
                Seat.WEST,
                ron_action(state, Seat.WEST),
                expected_revision=state.revision,
            )

        self.assertEqual(_capture(state), original)

    def test_win_finalization_actions_are_still_rejected(self) -> None:
        state = _quiet_state()
        state.draw(Seat.EAST)
        original = _capture(state)

        for action in (TsumoLegalAction(), NineTerminalsLegalAction()):
            with self.subTest(action=action):
                with self.assertRaises(IllegalActionError):
                    state.apply(
                        Seat.EAST,
                        action,
                        expected_revision=state.revision,
                    )

        self.assertEqual(_capture(state), original)

    def test_a_stale_kan_declaration_is_rejected(self) -> None:
        state = _ankan_state()
        snapshot = state.legal_actions(Seat.EAST)
        action = action_of_type(state, Seat.EAST, AnkanLegalAction)
        state.apply(Seat.EAST, action, expected_revision=snapshot.revision)
        original = _capture(state)

        with self.assertRaises(StaleActionError):
            state.apply(Seat.EAST, action, expected_revision=snapshot.revision)

        self.assertEqual(_capture(state), original)


# NORTHが3回暗槓したあと、EASTの打牌を大明槓して四槓子を確定させる局面。
_SUUKANTSU_HANDS = {
    Seat.EAST: (
        "4p",
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
        "2p",
    ),
    Seat.SOUTH: (
        "2s",
        "5s",
        "8s",
        "3p",
        "6p",
        "9m",
        "2z",
        "3z",
        "4z",
        "5z",
        "6z",
        "7z",
        "1z",
    ),
    Seat.WEST: (
        "3s",
        "6s",
        "9s",
        "5p",
        "7p",
        "8m",
        "2z",
        "3z",
        "4z",
        "5z",
        "6z",
        "7z",
        "1z",
    ),
    Seat.NORTH: (
        "1m",
        "1m",
        "1m",
        "1m",
        "2m",
        "2m",
        "2m",
        "2m",
        "3m",
        "3m",
        "3m",
        "3m",
        "7s",
    ),
}
_SUUKANTSU_DRAWS = ("4s", "1p", "9p", "7s")
# 先頭4枚が嶺上牌。NORTHが大明槓できるよう、4pを3枚引かせる。
_SUUKANTSU_DEAD_WALL = (
    "4p",
    "4p",
    "4p",
    "1p",
    "5m",
    "6m",
    "7m",
    "9m",
    "1s",
    "2s",
    "3s",
    "4s",
    "5s",
    "6s",
)


# 四槓子をパオ対象へ含めたルールセット。既定では対象外である。
_SUUKANTSU_PAO_RULES = replace(
    RuleSet.default(),
    pao_yaku=RuleSet.default().pao_yaku | {Yaku.SUUKANTSU},
)


def _three_ankan_state(*, rules: RuleSet | None = None) -> RoundState:
    """NORTHが暗槓を3つ持ち、4pを3枚抱えた局面を返す。"""
    state = _dealt_state(
        hands=_SUUKANTSU_HANDS,
        draws=_SUUKANTSU_DRAWS,
        dead_wall=_SUUKANTSU_DEAD_WALL,
        rules=rules,
    )
    for _ in range(3):
        play_quiet_turn(state)
    state.draw(Seat.NORTH)
    for _ in range(3):
        _declare_ankan(state, Seat.NORTH)
        state.draw_rinshan(Seat.NORTH)
    return state


class RoundStateSuukantsuPaoTest(unittest.TestCase):
    """四槓子の責任払いは、大明槓の成立時点でしか判定できない事実である。

    加槓は元のポンの位置で差し替わるため、和了時点の副露の並びからは
    「大明槓の時点で既に3槓あったか」を復元できない。E3が必要とする事実を
    失わないよう、E2で成立時点の判断を記録する。

    ただし記録するのは責任払いが実際に成立する場合だけであり、対象役は
    `RuleSet.pao_enabled`と`pao_yaku`が決める。
    """

    def _four_kan_state(self, *, rules: RuleSet | None = None) -> RoundState:
        """NORTHが3暗槓のあと、EASTの4pを大明槓して四槓子を確定させる。"""
        state = _three_ankan_state(rules=rules)
        discard(state, Seat.NORTH, "7s")
        if state.phase is RoundPhase.AWAITING_REACTIONS:
            resolve_all_pass(state)
        draw_and_discard(state, Seat.EAST, "4p")

        resolve_with(state, {Seat.NORTH: daiminkan_action(state, Seat.NORTH)})

        self.assertEqual(len(state.melds(Seat.NORTH)), 4)
        self.assertIs(state.phase, RoundPhase.AWAITING_RINSHAN_DRAW)
        return state

    def test_no_seat_owes_pao_before_the_fourth_kan(self) -> None:
        state = _three_ankan_state(rules=_SUUKANTSU_PAO_RULES)

        for seat in Seat:
            with self.subTest(seat=seat):
                self.assertIsNone(state.suukantsu_pao_seat(seat))

    def test_the_default_rules_do_not_make_suukantsu_a_pao_yaku(self) -> None:
        """既定のルールセットは大三元と大四喜だけをパオ対象にする。"""
        self.assertNotIn(Yaku.SUUKANTSU, RuleSet.default().pao_yaku)

        state = self._four_kan_state()

        for seat in Seat:
            with self.subTest(seat=seat):
                self.assertIsNone(state.suukantsu_pao_seat(seat))

    def test_the_discarder_of_the_fourth_kan_owes_pao_when_the_rules_say_so(
        self,
    ) -> None:
        state = self._four_kan_state(rules=_SUUKANTSU_PAO_RULES)

        self.assertIs(state.suukantsu_pao_seat(Seat.NORTH), Seat.EAST)

    def test_disabled_pao_rules_never_record_a_responsible_seat(self) -> None:
        rules = replace(_SUUKANTSU_PAO_RULES, pao_enabled=False)

        state = self._four_kan_state(rules=rules)

        for seat in Seat:
            with self.subTest(seat=seat):
                self.assertIsNone(state.suukantsu_pao_seat(seat))

    def test_an_ankan_never_creates_a_pao_obligation(self) -> None:
        for rules in (None, _SUUKANTSU_PAO_RULES):
            with self.subTest(rules=rules):
                state = _ankan_state(rules=rules)

                _declare_ankan(state)

                self.assertIsNone(state.suukantsu_pao_seat(Seat.EAST))

    def test_a_kakan_never_creates_a_pao_obligation(self) -> None:
        state = _kakan_declared_state(rules=_SUUKANTSU_PAO_RULES)

        resolve_all_pass(state)

        self.assertEqual([type(meld) for meld in state.melds(Seat.SOUTH)], [Kakan])
        for seat in Seat:
            with self.subTest(seat=seat):
                self.assertIsNone(state.suukantsu_pao_seat(seat))


# EASTが3zを打ってSOUTHがポンし、SOUTHがツモを伴わずに7pを打つ局面。
# その打牌へWESTがロン・チー、NORTHがポンで反応できる。
_CALLED_DISCARD_HANDS = {
    Seat.EAST: (
        "3z",
        "1m",
        "9m",
        "1s",
        "9s",
        "1z",
        "2z",
        "4z",
        "5z",
        "6z",
        "7z",
        "1p",
        "9p",
    ),
    Seat.SOUTH: (
        "3z",
        "3z",
        "7p",
        "1m",
        "9m",
        "1s",
        "9s",
        "1z",
        "2z",
        "4z",
        "5z",
        "6z",
        "7z",
    ),
    Seat.WEST: (
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
    ),
    Seat.NORTH: (
        "7p",
        "7p",
        "1m",
        "9m",
        "1s",
        "9s",
        "1z",
        "2z",
        "4z",
        "5z",
        "6z",
        "7z",
        "9p",
    ),
}
_CALLED_DISCARD_DRAWS = ("5z",)


def _called_discard_state(**kwargs) -> RoundState:
    """鳴き成立直後のツモなし打牌が、さらに反応windowを開いた局面を返す。"""
    state = _dealt_state(
        hands=_CALLED_DISCARD_HANDS,
        draws=_CALLED_DISCARD_DRAWS,
        with_dead_wall=True,
        **kwargs,
    )
    draw_and_discard(state, Seat.EAST, "3z")
    resolve_with(state, {Seat.SOUTH: pon_action(state, Seat.SOUTH)})
    discard(state, Seat.SOUTH, "7p")
    return state


class RoundStateCalledDiscardReactionTest(unittest.TestCase):
    """鳴き直後のツモなし打牌でも、反応windowを正常に開けることを固定する。

    `pending_discard_source` は「その打牌の直前にどこからツモったか」という
    補助的なprovenanceであり、すべての打牌がツモを伴うわけではない。鳴き
    成立直後の打牌では `None` が正常値であり、打牌そのものの存在条件と
    同一にしてはならない。
    """

    def test_a_call_leaves_the_caller_without_a_drawn_tile(self) -> None:
        state = _dealt_state(
            hands=_CALLED_DISCARD_HANDS,
            draws=_CALLED_DISCARD_DRAWS,
            with_dead_wall=True,
        )
        draw_and_discard(state, Seat.EAST, "3z")

        resolve_with(state, {Seat.SOUTH: pon_action(state, Seat.SOUTH)})

        self.assertIs(state.phase, RoundPhase.AWAITING_DISCARD)
        self.assertIs(state.current_seat, Seat.SOUTH)
        self.assertIsNone(state.drawn_tile_id)
        self.assertIsNone(state.drawn_tile_source)

    def test_a_discard_without_a_draw_opens_a_reaction_window(self) -> None:
        state = _called_discard_state()

        self.assertIs(state.phase, RoundPhase.AWAITING_REACTIONS)
        self.assertIs(state.pending_discarder, Seat.SOUTH)
        self.assertIsNotNone(state.pending_discard)
        self.assertEqual(
            state.pending_discard.tile.tile_type,
            _tile_type("7p"),
        )
        self.assertIsNone(state.pending_discard_source)

    def test_every_reacting_seat_gets_a_choice(self) -> None:
        state = _called_discard_state()
        target_tile_id = state.pending_discard.tile.id

        self.assertEqual(state.reacting_seats, (Seat.WEST, Seat.NORTH, Seat.EAST))
        for seat in state.reacting_seats:
            with self.subTest(seat=seat):
                self.assertIn(
                    PassLegalAction(ReactionOrigin.DISCARD, target_tile_id),
                    actions_of(state, seat),
                )
        self.assertTrue(has_action_of_type(state, Seat.WEST, RonLegalAction))
        self.assertTrue(has_action_of_type(state, Seat.NORTH, PonLegalAction))
        # 反応できないEASTにも、パスだけの選択肢が提示される。
        self.assertEqual(
            actions_of(state, Seat.EAST),
            (PassLegalAction(ReactionOrigin.DISCARD, target_tile_id),),
        )
        self.assertEqual(actions_of(state, Seat.SOUTH), ())

    def test_all_reacting_seats_share_the_same_revision(self) -> None:
        state = _called_discard_state()

        snapshots = [state.legal_actions(seat) for seat in state.reacting_seats]

        self.assertEqual(
            {snapshot.revision for snapshot in snapshots}, {state.revision}
        )

    def test_the_window_can_be_closed_by_an_all_pass_batch(self) -> None:
        state = _called_discard_state()
        revision = state.revision

        resolution = resolve_all_pass(state)

        self.assertTrue(resolution.all_passed)
        self.assertIs(state.phase, RoundPhase.AWAITING_DRAW)
        self.assertIs(state.current_seat, Seat.WEST)
        self.assertIsNone(state.pending_discard)
        self.assertIsNone(state.pending_discard_source)
        self.assertEqual(state.revision, revision + 1)

    def test_the_window_can_resolve_into_a_ron(self) -> None:
        state = _called_discard_state()

        resolution = resolve_with(state, {Seat.WEST: ron_action(state, Seat.WEST)})

        self.assertIs(resolution.resolved_type, ReactionType.RON)
        self.assertIs(state.phase, RoundPhase.AWAITING_WIN_FINALIZATION)
        self.assertEqual(state.pending_ron_resolution.winner_seats, (Seat.WEST,))
        self.assertIs(state.pending_ron_resolution.source_seat, Seat.SOUTH)

    def test_the_window_can_resolve_into_another_call(self) -> None:
        state = _called_discard_state()

        resolution = resolve_with(state, {Seat.NORTH: pon_action(state, Seat.NORTH)})

        self.assertIs(resolution.resolved_type, ReactionType.PON)
        self.assertIs(state.phase, RoundPhase.AWAITING_DISCARD)
        self.assertIs(state.current_seat, Seat.NORTH)
        self.assertIsNone(state.drawn_tile_id)
        self.assertIs(state.discards(Seat.SOUTH)[-1].called_by, Seat.NORTH)

    def test_a_ron_priority_still_beats_the_calls(self) -> None:
        state = _called_discard_state()

        resolution = resolve_with(
            state,
            {
                Seat.WEST: ron_action(state, Seat.WEST),
                Seat.NORTH: pon_action(state, Seat.NORTH),
            },
        )

        self.assertIs(resolution.resolved_type, ReactionType.RON)
        self.assertEqual(state.melds(Seat.NORTH), ())

    def test_a_discard_without_a_draw_is_never_a_last_tile_win(self) -> None:
        """ツモ元のない打牌を`LIVE_WALL`へ補完せず、河底扱いにしない。"""
        state = _called_discard_state()

        resolve_with(state, {Seat.WEST: ron_action(state, Seat.WEST)})

        self.assertIsNone(state.pending_discard_source)
        self.assertFalse(state.pending_ron_resolution.is_last_tile)

    def test_a_rejected_batch_leaves_the_window_untouched(self) -> None:
        state = _called_discard_state()
        choices = all_pass_choices(state)
        del choices[Seat.NORTH]
        original = _capture(state)

        with self.assertRaises(IllegalActionError):
            state.resolve_reactions(choices, expected_revision=state.revision)

        self.assertEqual(_capture(state), original)

    def test_physical_tiles_are_conserved_through_the_window(self) -> None:
        state = _called_discard_state()
        expected_tile_ids = _owned_tile_ids(state)

        resolve_with(state, {Seat.NORTH: pon_action(state, Seat.NORTH)})

        self.assertEqual(_owned_tile_ids(state), expected_tile_ids)

    def test_a_source_less_discard_keeps_the_draw_source_invariant(self) -> None:
        """`pending_discard_source`があるならpending discardも必ず存在する。"""
        state = _called_discard_state()
        original = _capture(state)
        transition = state._begin()
        transition.pending_discarder = None
        transition.pending_discard = None
        transition.phase = RoundPhase.AWAITING_DRAW
        transition.current_seat = Seat.WEST
        transition.pending_discard_source = DrawSource.LIVE_WALL

        with self.assertRaises(RoundInvariantError):
            state._commit(transition)

        self.assertEqual(_capture(state), original)


# EASTが1mの暗槓材料を持ち、NORTHが1m単騎の国士無双で立直できる局面用の
# ツモ順。全員が1巡目をツモ切りし、NORTHが立直を宣言してからEASTが暗槓
# できるようにする。
_ANKAN_RIICHI_DRAWS = ("8s", "8s", "8s", "8s", "8m")


def _riichi_before_kakan_state(**kwargs) -> RoundState:
    """WESTが立直（一発中）のまま、SOUTHが加槓を宣言した局面を返す。

    ポンはWESTの立直より前に済ませてあるため、加槓宣言の時点でWESTの
    一発windowはまだ開いている。
    """
    state = _dealt_state(
        hands=_KAKAN_HANDS,
        draws=_KAKAN_DRAWS,
        with_dead_wall=True,
        **kwargs,
    )
    draw_and_discard(state, Seat.EAST, "3p")
    resolve_with(state, {Seat.SOUTH: pon_action(state, Seat.SOUTH)})
    discard(state, Seat.SOUTH, "1z")
    state.draw(Seat.WEST)
    discard(state, Seat.WEST, "9s", declaration=DiscardDeclaration.RIICHI)
    play_quiet_turn(state)
    play_quiet_turn(state)
    state.draw(Seat.SOUTH)
    snapshot = state.legal_actions(Seat.SOUTH)
    state.apply(
        Seat.SOUTH,
        action_of_type(state, Seat.SOUTH, KakanLegalAction),
        expected_revision=snapshot.revision,
    )
    return state


def _riichi_before_ankan_state(**kwargs) -> RoundState:
    """NORTHが国士無双で立直（一発中）のまま、EASTが暗槓を宣言した局面。"""
    state = _dealt_state(
        hands=_ANKAN_HANDS,
        draws=_ANKAN_RIICHI_DRAWS,
        with_dead_wall=True,
        **kwargs,
    )
    for _ in range(3):
        play_quiet_turn(state)
    state.draw(Seat.NORTH)
    snapshot = state.legal_actions(Seat.NORTH)
    state.apply(
        Seat.NORTH,
        next(
            action
            for action in snapshot.actions
            if isinstance(action, DiscardLegalAction)
            and action.declaration is DiscardDeclaration.RIICHI
        ),
        expected_revision=snapshot.revision,
    )
    if state.phase is RoundPhase.AWAITING_REACTIONS:
        resolve_all_pass(state)
    state.draw(Seat.EAST)
    _declare_ankan(state, Seat.EAST)
    return state


class RoundStateKanIppatsuTest(unittest.TestCase):
    """一発を終わらせるのは槓の「宣言」ではなく「成立」であることを固定する。

    槍槓で流れた加槓・暗槓はそもそも成立していないため、和了者は
    `RIICHI + IPPATSU + CHANKAN` のまま和了できなければならない。
    """

    def test_a_kakan_declaration_does_not_cancel_ippatsu(self) -> None:
        state = _riichi_before_kakan_state()

        self.assertIs(state.phase, RoundPhase.AWAITING_KAKAN_REACTIONS)
        self.assertTrue(state.is_riichi_established(Seat.WEST))
        self.assertTrue(state.is_ippatsu(Seat.WEST))

    def test_a_chankan_ron_preserves_the_winner_ippatsu(self) -> None:
        state = _riichi_before_kakan_state()

        resolution = resolve_with(state, {Seat.WEST: ron_action(state, Seat.WEST)})

        self.assertIs(resolution.origin, ReactionOrigin.KAKAN)
        self.assertIs(state.phase, RoundPhase.AWAITING_WIN_FINALIZATION)
        self.assertEqual(state.pending_ron_resolution.winner_seats, (Seat.WEST,))
        self.assertTrue(state.is_ippatsu(Seat.WEST))
        self.assertIs(state.riichi_status(Seat.WEST), RiichiStatus.RIICHI)
        # 加槓は成立せず、元のポンが残る。
        self.assertEqual([type(meld) for meld in state.melds(Seat.SOUTH)], [Pon])
        self.assertIsNone(state.pending_kakan)

    def test_the_chankan_facts_build_a_riichi_ippatsu_chankan_context(self) -> None:
        """E3が`RIICHI + IPPATSU + CHANKAN`を構築できることを確認する。

        点数確定はE3の責務のため、ここでは`WinningContext`と役の成立まで
        だけを確認し、`RoundResult`や精算へは踏み込まない。
        """
        state = _riichi_before_kakan_state()
        resolve_with(state, {Seat.WEST: ron_action(state, Seat.WEST)})
        pending = state.pending_ron_resolution
        winner = pending.winner_seats[0]

        context = WinningContext(
            concealed_tiles=(*state.hand_tiles(winner), pending.target_tile),
            winning_tile=pending.target_tile,
            method=WinMethod.RON,
            origin=WinOrigin.KAKAN,
            seat_wind=state.seat_wind(winner),
            prevailing_wind=state.prevailing_wind,
            declared_melds=state.melds(winner),
            riichi_status=state.riichi_status(winner),
            is_ippatsu=state.is_ippatsu(winner),
        )
        yakus = frozenset(
            yaku
            for evaluation in evaluate_yaku(context, state.rules)
            for yaku in evaluation.yakus
        )

        self.assertIn(Yaku.RIICHI, yakus)
        self.assertIn(Yaku.IPPATSU, yakus)
        self.assertIn(Yaku.CHANKAN, yakus)

    def test_a_confirmed_kakan_cancels_ippatsu(self) -> None:
        state = _riichi_before_kakan_state()
        revision = state.revision

        resolve_all_pass(state)

        self.assertFalse(state.is_ippatsu(Seat.WEST))
        self.assertTrue(state.is_riichi_established(Seat.WEST))
        self.assertIs(state.phase, RoundPhase.AWAITING_RINSHAN_DRAW)
        self.assertEqual([type(meld) for meld in state.melds(Seat.SOUTH)], [Kakan])
        self.assertEqual(state.revision, revision + 1)

    def test_an_ankan_declaration_does_not_cancel_ippatsu(self) -> None:
        state = _riichi_before_ankan_state(rules=_KOKUSHI_CHANKAN_RULES)

        self.assertIs(state.phase, RoundPhase.AWAITING_ANKAN_REACTIONS)
        self.assertTrue(state.is_ippatsu(Seat.NORTH))
        self.assertEqual(state.melds(Seat.EAST), ())

    def test_an_ankan_chankan_ron_preserves_the_winner_ippatsu(self) -> None:
        state = _riichi_before_ankan_state(rules=_KOKUSHI_CHANKAN_RULES)

        resolution = resolve_with(state, {Seat.NORTH: ron_action(state, Seat.NORTH)})

        self.assertIs(resolution.origin, ReactionOrigin.ANKAN)
        self.assertIs(state.phase, RoundPhase.AWAITING_WIN_FINALIZATION)
        self.assertEqual(state.pending_ron_resolution.winner_seats, (Seat.NORTH,))
        self.assertTrue(state.is_ippatsu(Seat.NORTH))
        self.assertIs(state.riichi_status(Seat.NORTH), RiichiStatus.DOUBLE_RIICHI)
        # 暗槓は成立せず、4枚は宣言者の手牌に残る。
        self.assertEqual(state.melds(Seat.EAST), ())
        self.assertIsNone(state.pending_ankan)

    def test_a_confirmed_ankan_cancels_ippatsu(self) -> None:
        state = _riichi_before_ankan_state(rules=_KOKUSHI_CHANKAN_RULES)

        resolve_all_pass(state)

        self.assertFalse(state.is_ippatsu(Seat.NORTH))
        self.assertTrue(state.is_riichi_established(Seat.NORTH))
        self.assertEqual([type(meld) for meld in state.melds(Seat.EAST)], [Ankan])

    def test_an_ankan_without_a_chankan_candidate_cancels_ippatsu_at_once(self) -> None:
        """槍槓候補がない暗槓は、宣言と成立が同じtransactionで完了する。"""
        state = _riichi_before_ankan_state()

        self.assertIs(state.phase, RoundPhase.AWAITING_RINSHAN_DRAW)
        self.assertEqual([type(meld) for meld in state.melds(Seat.EAST)], [Ankan])
        self.assertFalse(state.is_ippatsu(Seat.NORTH))
        self.assertTrue(state.is_riichi_established(Seat.NORTH))

    def test_a_failed_chankan_batch_leaves_ippatsu_untouched(self) -> None:
        state = _riichi_before_kakan_state()
        original = _capture(state)
        choices = all_pass_choices(state)
        del choices[Seat.EAST]

        with self.assertRaises(IllegalActionError):
            state.resolve_reactions(choices, expected_revision=state.revision)

        self.assertEqual(_capture(state), original)
        self.assertTrue(state.is_ippatsu(Seat.WEST))
        self.assertIsNotNone(state.pending_kakan)


if __name__ == "__main__":
    unittest.main()
