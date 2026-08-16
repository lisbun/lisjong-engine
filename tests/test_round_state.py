import unittest

from lisjong_engine.discard import Discard
from lisjong_engine.legal_action import (
    ChiLegalAction,
    DiscardDeclaration,
    DiscardLegalAction,
    NineTerminalsLegalAction,
    PassLegalAction,
    PonLegalAction,
    ReactionOrigin,
    RonLegalAction,
    TsumoLegalAction,
)
from lisjong_engine.random_source import RandomSource
from lisjong_engine.round_event import (
    DrawSource,
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
from lisjong_engine.rules import RuleSet
from lisjong_engine.seat import Seat
from lisjong_engine.tile import STANDARD_TILES, Tile, TileCategory, TileType
from lisjong_engine.wall import Wall, create_shuffled_wall
from lisjong_engine.wind import Wind

_TILE_CATEGORIES = {
    "m": TileCategory.MANZU,
    "p": TileCategory.PINZU,
    "s": TileCategory.SOUZU,
    "z": TileCategory.HONOR,
}
_LIVE_WALL_SIZE = 70
_FIRST_DRAW_POSITION = 52

# 誰も反応できない局面を作るための配牌。各席は同じ牌種を2枚以上持たず、
# 白（5z）・發（6z）を1枚も持たない。ツモ牌をすべて白・發にすることで、
# ポン・チー・大明槓・ロンのいずれの必要条件も満たさなくなる。
_QUIET_HANDS = {
    Seat.EAST: (
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
    Seat.SOUTH: (
        "2m",
        "5m",
        "8m",
        "2p",
        "5p",
        "8p",
        "2s",
        "5s",
        "8s",
        "1z",
        "2z",
        "3z",
        "4z",
    ),
    Seat.WEST: (
        "3m",
        "6m",
        "9m",
        "3p",
        "6p",
        "9p",
        "3s",
        "6s",
        "9s",
        "1z",
        "2z",
        "3z",
        "4z",
    ),
    Seat.NORTH: (
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
}
_QUIET_DRAWS = ("5z", "5z", "5z", "5z", "6z", "6z", "6z", "6z")


def _tile_type(name: str) -> TileType:
    return TileType(_TILE_CATEGORIES[name[-1]], int(name[:-1]))


def _take(pool: list[Tile], names: tuple[str, ...]) -> tuple[Tile, ...]:
    taken = []
    for name in names:
        expected = _tile_type(name)
        index = next(
            index for index, tile in enumerate(pool) if tile.tile_type == expected
        )
        taken.append(pool.pop(index))
    return tuple(taken)


def _deal_positions(dealer_seat: Seat) -> dict[Seat, tuple[int, ...]]:
    """配牌順（親から4枚ずつ3巡＋1枚ずつ）に対応する山のindexを返す。"""
    seats = tuple(Seat)
    start = seats.index(dealer_seat)
    deal_order = tuple(seats[(start + offset) % len(seats)] for offset in range(4))
    return {
        seat: (
            *range(order * 4, order * 4 + 4),
            *range(16 + order * 4, 16 + order * 4 + 4),
            *range(32 + order * 4, 32 + order * 4 + 4),
            48 + order,
        )
        for order, seat in enumerate(deal_order)
    }


def _build_wall(
    *,
    hands: dict[Seat, tuple[str, ...]],
    draws: tuple[str, ...] = (),
    dealer_seat: Seat = Seat.EAST,
    with_dead_wall: bool = False,
) -> Wall:
    """指定した配牌とツモ順になる山を組み立てる。"""
    pool = list(STANDARD_TILES)
    drawn_tiles = _take(pool, draws)
    hand_tiles = {seat: _take(pool, names) for seat, names in hands.items()}

    wall_tiles: list[Tile | None] = [None] * _LIVE_WALL_SIZE
    for seat, positions in _deal_positions(dealer_seat).items():
        for position, tile in zip(positions, hand_tiles[seat], strict=True):
            wall_tiles[position] = tile
    for offset, tile in enumerate(drawn_tiles):
        wall_tiles[_FIRST_DRAW_POSITION + offset] = tile
    for index, tile in enumerate(wall_tiles):
        if tile is None:
            wall_tiles[index] = pool.pop(0)

    dead_wall = tuple(pool.pop(0) for _ in range(14)) if with_dead_wall else ()
    return Wall(tuple(wall_tiles), dead_wall)


def _capture(state: RoundState) -> tuple:
    """failure atomicityの確認に使う、観測可能な状態のすべて。"""
    return (
        state.phase,
        state.current_seat,
        state.revision,
        state.drawn_tile_id,
        state.remaining_tiles,
        state.dead_wall_tiles,
        state.pending_discarder,
        state.pending_discard,
        tuple(state.hand_tiles(seat) for seat in Seat),
        tuple(state.discards(seat) for seat in Seat),
        tuple(state.melds(seat) for seat in Seat),
        state.events,
    )


def _dealt_state(**kwargs) -> RoundState:
    state = RoundState(_build_wall(**kwargs))
    state.deal()
    return state


def _quiet_state() -> RoundState:
    return _dealt_state(hands=_QUIET_HANDS, draws=_QUIET_DRAWS)


def _discard_drawn_tile(state: RoundState, seat: Seat) -> Tile:
    tile = state.draw(seat)
    snapshot = state.legal_actions(seat)
    action = DiscardLegalAction(tile.id)
    state.apply(seat, action, expected_revision=snapshot.revision)
    return tile


class RoundStateInitializationTest(unittest.TestCase):
    def test_starts_undealt_with_the_configured_round_facts(self) -> None:
        wall = Wall(STANDARD_TILES[:60])

        state = RoundState(wall, dealer_seat=Seat.SOUTH, prevailing_wind=Wind.SOUTH)

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
        state = RoundState(Wall(STANDARD_TILES[:60]))

        self.assertEqual(state.rules, RuleSet.default())

    def test_keeps_the_given_rule_set(self) -> None:
        rules = RuleSet.default()

        state = RoundState(Wall(STANDARD_TILES[:60]), rules=rules)

        self.assertIs(state.rules, rules)

    def test_copies_the_given_wall(self) -> None:
        wall = Wall(STANDARD_TILES[:60])
        state = RoundState(wall)

        state.deal()

        self.assertEqual(wall.remaining_count, 60)
        self.assertEqual(state.remaining_count, 8)

    def test_seat_wind_follows_the_dealer(self) -> None:
        state = RoundState(Wall(STANDARD_TILES[:60]), dealer_seat=Seat.WEST)

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
        state = RoundState(Wall(STANDARD_TILES[:60]))

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
        state = RoundState(Wall(STANDARD_TILES[:60]))
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
        state = RoundState(Wall(STANDARD_TILES[:60]))

        state.deal()

        self.assertIs(state.current_seat, Seat.EAST)
        self.assertIs(state.phase, RoundPhase.AWAITING_DRAW)
        self.assertIsNone(state.drawn_tile_id)
        self.assertEqual(state.remaining_count, 8)
        self.assertEqual(state.remaining_tiles, STANDARD_TILES[52:60])
        self.assertEqual(state.revision, 1)

    def test_deals_from_the_configured_dealer_seat(self) -> None:
        state = RoundState(Wall(STANDARD_TILES[:60]), dealer_seat=Seat.SOUTH)

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
        state = RoundState(Wall(STANDARD_TILES[:60]))

        dealt_tiles = state.deal()

        self.assertEqual(
            tuple(state.events),
            (
                RoundStartedEvent(Seat.EAST, Wind.EAST),
                *(TilesDealtEvent(seat, dealt_tiles[seat]) for seat in Seat),
            ),
        )

    def test_deal_keeps_every_physical_tile_distinct(self) -> None:
        state = RoundState(Wall(STANDARD_TILES[:60]))

        state.deal()

        tile_ids = [tile.id for seat in Seat for tile in state.hand_tiles(seat)] + [
            tile.id for tile in state.remaining_tiles
        ]
        self.assertEqual(len(set(tile_ids)), len(tile_ids))
        self.assertEqual(len(tile_ids), 60)

    def test_the_same_wall_always_produces_the_same_initial_state(self) -> None:
        first = RoundState(Wall(STANDARD_TILES[:60]))
        second = RoundState(Wall(STANDARD_TILES[:60]))

        first.deal()
        second.deal()

        self.assertEqual(_capture(first), _capture(second))

    def test_rejects_a_second_deal_without_changing_state(self) -> None:
        state = RoundState(Wall(STANDARD_TILES[:60]))
        state.deal()
        original = _capture(state)

        with self.assertRaises(IllegalOperationError):
            state.deal()

        self.assertEqual(_capture(state), original)

    def test_rejects_a_short_wall_without_changing_state(self) -> None:
        state = RoundState(Wall(STANDARD_TILES[:51]))
        original = _capture(state)

        with self.assertRaises(IndexError):
            state.deal()

        self.assertEqual(_capture(state), original)
        self.assertIs(state.phase, RoundPhase.UNDEALT)
        self.assertEqual(state.revision, 0)


class RoundStateDrawTest(unittest.TestCase):
    def test_moves_the_next_wall_tile_into_the_current_hand(self) -> None:
        state = RoundState(Wall(STANDARD_TILES[:60]))
        state.deal()

        tile = state.draw(Seat.EAST)

        self.assertEqual(tile, STANDARD_TILES[52])
        self.assertIn(tile, state.hand_tiles(Seat.EAST))
        self.assertEqual(len(state.hand_tiles(Seat.EAST)), 14)
        self.assertEqual(state.remaining_tiles, STANDARD_TILES[53:60])
        self.assertEqual(state.remaining_count, 7)

    def test_draw_moves_the_phase_and_records_the_drawn_tile(self) -> None:
        state = RoundState(Wall(STANDARD_TILES[:60]))
        state.deal()

        tile = state.draw(Seat.EAST)

        self.assertIs(state.phase, RoundPhase.AWAITING_DISCARD)
        self.assertIs(state.current_seat, Seat.EAST)
        self.assertEqual(state.drawn_tile_id, tile.id)
        self.assertEqual(state.drawn_tile, tile)
        self.assertEqual(state.revision, 2)

    def test_draw_records_a_live_wall_event(self) -> None:
        state = RoundState(Wall(STANDARD_TILES[:60]))
        state.deal()

        tile = state.draw(Seat.EAST)

        self.assertEqual(
            state.events[-1],
            TileDrawnEvent(Seat.EAST, tile, DrawSource.LIVE_WALL),
        )

    def test_other_seats_cannot_draw(self) -> None:
        state = RoundState(Wall(STANDARD_TILES[:60]))
        state.deal()
        original = _capture(state)

        for seat in (Seat.SOUTH, Seat.WEST, Seat.NORTH):
            with self.subTest(seat=seat):
                with self.assertRaises(IllegalOperationError):
                    state.draw(seat)

        self.assertEqual(_capture(state), original)

    def test_cannot_draw_outside_the_draw_phase(self) -> None:
        state = RoundState(Wall(STANDARD_TILES[:60]))

        with self.assertRaises(IllegalOperationError):
            state.draw(Seat.EAST)

        state.deal()
        state.draw(Seat.EAST)
        original = _capture(state)

        with self.assertRaises(IllegalOperationError):
            state.draw(Seat.EAST)

        self.assertEqual(_capture(state), original)

    def test_rejects_a_draw_from_an_empty_wall_without_changing_state(self) -> None:
        state = RoundState(Wall(STANDARD_TILES[:52]))
        state.deal()
        original = _capture(state)

        with self.assertRaises(IndexError):
            state.draw(Seat.EAST)

        self.assertEqual(_capture(state), original)
        self.assertEqual(state.remaining_count, 0)


class RoundStateLegalActionsTest(unittest.TestCase):
    def test_lists_every_hand_tile_for_the_current_seat(self) -> None:
        state = RoundState(Wall(STANDARD_TILES[:60]))
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
        state = RoundState(Wall(STANDARD_TILES[:60]))
        state.deal()
        state.draw(Seat.EAST)

        for seat in (Seat.SOUTH, Seat.WEST, Seat.NORTH):
            with self.subTest(seat=seat):
                self.assertEqual(state.legal_actions(seat).actions, ())

    def test_offers_nothing_while_awaiting_a_draw(self) -> None:
        state = RoundState(Wall(STANDARD_TILES[:60]))
        state.deal()

        snapshot = state.legal_actions(Seat.EAST)

        self.assertIs(snapshot.phase, RoundPhase.AWAITING_DRAW)
        self.assertEqual(snapshot.actions, ())

    def test_offers_nothing_before_the_deal(self) -> None:
        state = RoundState(Wall(STANDARD_TILES[:60]))

        self.assertEqual(state.legal_actions(Seat.EAST).actions, ())

    def test_snapshot_has_no_side_effects(self) -> None:
        state = RoundState(Wall(STANDARD_TILES[:60]))
        state.deal()
        state.draw(Seat.EAST)
        original = _capture(state)

        first = state.legal_actions(Seat.EAST)
        second = state.legal_actions(Seat.EAST)

        self.assertEqual(first, second)
        self.assertEqual(_capture(state), original)

    def test_candidates_are_limited_to_tiles_owned_by_the_hand(self) -> None:
        state = RoundState(Wall(STANDARD_TILES[:60]))
        state.deal()
        state.draw(Seat.EAST)
        hand_tile_ids = {tile.id for tile in state.hand_tiles(Seat.EAST)}

        snapshot = state.legal_actions(Seat.EAST)

        self.assertTrue(
            all(action.tile_id in hand_tile_ids for action in snapshot.actions)
        )

    def test_exposes_immutable_views_only(self) -> None:
        state = RoundState(Wall(STANDARD_TILES[:60]))
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

    def test_offers_no_actions_while_awaiting_reactions(self) -> None:
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

        for seat in Seat:
            with self.subTest(seat=seat):
                self.assertEqual(state.legal_actions(seat).actions, ())

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

    def test_allows_awaiting_kakan_reactions_with_a_current_seat(self) -> None:
        """加槓宣言後、槍槓reactionを待つ間もcurrent seatを保持できることを固定する。

        E1は加槓を実装しないが、`AWAITING_KAKAN_REACTIONS` はE2で
        加槓を宣言したseatを`current_seat`として保持したまま槍槓の反応を
        待つ正常なphaseであり、invariantがcurrent seatありというだけで
        拒否してはならない。
        """
        state = _quiet_state()
        transition = state._begin()
        transition.phase = RoundPhase.AWAITING_KAKAN_REACTIONS
        transition.current_seat = Seat.EAST
        transition.drawn_tile_id = None

        state._commit(transition)

        self.assertIs(state.phase, RoundPhase.AWAITING_KAKAN_REACTIONS)
        self.assertIs(state.current_seat, Seat.EAST)

    def test_allows_awaiting_ankan_reactions_with_a_current_seat(self) -> None:
        """暗槓宣言後、槍槓reactionを待つ間もcurrent seatを保持できることを固定する。

        E1は暗槓を実装しないが、`AWAITING_ANKAN_REACTIONS` はE2で
        暗槓を宣言したseatを`current_seat`として保持したまま
        （国士無双限定の）槍槓の反応を待つ正常なphaseであり、invariantが
        current seatありというだけで拒否してはならない。
        """
        state = _quiet_state()
        transition = state._begin()
        transition.phase = RoundPhase.AWAITING_ANKAN_REACTIONS
        transition.current_seat = Seat.EAST
        transition.drawn_tile_id = None

        state._commit(transition)

        self.assertIs(state.phase, RoundPhase.AWAITING_ANKAN_REACTIONS)
        self.assertIs(state.current_seat, Seat.EAST)

    def test_rejects_a_drawn_tile_reference_outside_the_discard_phase(self) -> None:
        state = _quiet_state()
        drawn_tile = state.draw(Seat.EAST)
        original = _capture(state)
        transition = state._begin()
        transition.phase = RoundPhase.AWAITING_RINSHAN_DRAW

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
            state = RoundState(create_shuffled_wall(RandomSource(20260816)))
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
        state = RoundState(_build_wall(hands=_QUIET_HANDS, draws=_QUIET_DRAWS))

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


if __name__ == "__main__":
    unittest.main()
