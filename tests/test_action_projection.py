import unittest

from _round_fixtures import (
    INERT_HAND,
    QUIET_DRAWS,
    QUIET_HANDS,
    build_wall,
    deal_positions,
    draw_and_discard,
    new_state,
    starting_points,
)

from lisjong_engine.action_descriptor import (
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
)
from lisjong_engine.action_projection import (
    ActionProjectionError,
    project_legal_actions,
)
from lisjong_engine.legal_action import (
    AnkanLegalAction,
    ChiLegalAction,
    DaiminkanLegalAction,
    DiscardLegalAction,
    KakanLegalAction,
    LegalActionSnapshot,
    NineTerminalsLegalAction,
    PassLegalAction,
    PonLegalAction,
    ReactionOrigin,
    RiichiLegalAction,
    RonLegalAction,
    TsumoLegalAction,
)
from lisjong_engine.match_state import MatchPhase, MatchState
from lisjong_engine.observation_builder import build_seat_observation
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.round_state import StaleActionError
from lisjong_engine.seat import Seat
from lisjong_engine.tile import STANDARD_TILES
from lisjong_engine.wall import Wall

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


def _standard_turn_state():
    state = new_state(Wall(STANDARD_TILES), round_start_points=starting_points())
    state.deal()
    state.draw(Seat.EAST)
    return state


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
# 宣言牌候補が複数残るツモ牌を配る並び。
_RIICHI_MULTI_DRAWS = ("2s", "5z", "6z", "5z")


def _riichi_turn_state():
    """EASTが立直を選択でき、宣言牌候補も複数ある局面を返す。"""
    state = new_state(
        build_wall(
            hands=_RIICHI_HANDS,
            draws=_RIICHI_MULTI_DRAWS,
            with_dead_wall=True,
        ),
        round_start_points=starting_points(),
    )
    state.deal()
    state.draw(Seat.EAST)
    return state


def _reaction_state():
    state = new_state(
        build_wall(
            hands=_REACTION_HANDS,
            draws=("1z", "4p"),
            with_dead_wall=True,
        )
    )
    state.deal()
    draw_and_discard(state, Seat.EAST, "7p")
    return state


class TurnActionProjectionTest(unittest.TestCase):
    def test_projects_every_turn_variant_and_tsumo_winning_tile(self) -> None:
        state = _standard_turn_state()
        hand_ids = tuple(tile.id for tile in state.hand_tiles(Seat.EAST))
        drawn_id = state.drawn_tile_id
        self.assertIsNotNone(drawn_id)
        snapshot = LegalActionSnapshot(
            Seat.EAST,
            state.phase,
            state.revision,
            (
                DiscardLegalAction(hand_ids[0]),
                RiichiLegalAction(),
                AnkanLegalAction(hand_ids[:4]),
                KakanLegalAction(hand_ids[4]),
                TsumoLegalAction(),
                NineTerminalsLegalAction(),
            ),
        )

        projection = project_legal_actions(snapshot, state)

        self.assertEqual(
            {type(option) for option in projection.options},
            {
                DiscardActionDescriptor,
                RiichiActionDescriptor,
                AnkanActionDescriptor,
                KakanActionDescriptor,
                TsumoActionDescriptor,
                NineTerminalsActionDescriptor,
            },
        )
        tsumo = next(
            option
            for option in projection.options
            if isinstance(option, TsumoActionDescriptor)
        )
        self.assertEqual(tsumo.tile.tile_type, state.drawn_tile.tile_type)
        self.assertEqual(tsumo.tile.is_red, state.drawn_tile.is_red)

    def test_collapses_publicly_equal_discards_and_uses_minimum_internal_id(
        self,
    ) -> None:
        state = _standard_turn_state()
        snapshot = state.legal_actions(Seat.EAST)
        one_man_actions = tuple(
            action
            for action in snapshot.actions
            if isinstance(action, DiscardLegalAction)
            and next(
                tile
                for tile in state.hand_tiles(Seat.EAST)
                if tile.id == action.tile_id
            ).tile_type.id
            == 0
        )

        projection = project_legal_actions(snapshot, state)
        descriptor = next(
            option
            for option in projection.options
            if isinstance(option, DiscardActionDescriptor)
            and option.tile.tile_type.id == 0
        )

        self.assertGreater(len(one_man_actions), 1)
        self.assertEqual(
            projection.resolve(descriptor).tile_id,
            min(action.tile_id for action in one_man_actions),
        )
        self.assertEqual(
            sum(
                isinstance(option, DiscardActionDescriptor)
                and option.tile.tile_type.id == 0
                for option in projection.options
            ),
            1,
        )

    def test_red_and_non_red_discards_are_not_collapsed(self) -> None:
        state = _standard_turn_state()
        projection = project_legal_actions(state.legal_actions(Seat.EAST), state)
        five_man = tuple(
            option
            for option in projection.options
            if isinstance(option, DiscardActionDescriptor)
            and option.tile.tile_type.id == 4
        )

        self.assertEqual(len(five_man), 2)
        self.assertEqual({option.tile.is_red for option in five_man}, {False, True})

    def test_tsumogiri_and_tedashi_are_not_collapsed(self) -> None:
        hands = dict(QUIET_HANDS)
        hands[Seat.EAST] = (*QUIET_HANDS[Seat.EAST][:-1], "5z")
        state = new_state(build_wall(hands=hands, draws=("5z",), with_dead_wall=True))
        state.deal()
        state.draw(Seat.EAST)

        projection = project_legal_actions(state.legal_actions(Seat.EAST), state)
        five_honor = tuple(
            option
            for option in projection.options
            if isinstance(option, DiscardActionDescriptor)
            and option.tile.tile_type.id == 31
        )

        self.assertEqual(len(five_honor), 2)
        self.assertEqual({option.is_tsumogiri for option in five_honor}, {False, True})

    def test_internal_enumeration_order_does_not_affect_options_or_canonical_action(
        self,
    ) -> None:
        state = _standard_turn_state()
        forward = state.legal_actions(Seat.EAST)
        backward = LegalActionSnapshot(
            forward.seat,
            forward.phase,
            forward.revision,
            tuple(reversed(forward.actions)),
        )

        first = project_legal_actions(forward, state)
        second = project_legal_actions(backward, state)

        self.assertEqual(first.options, second.options)
        self.assertEqual(
            tuple(first.resolve(option) for option in first.options),
            tuple(second.resolve(option) for option in second.options),
        )


class RiichiProjectionTest(unittest.TestCase):
    """立直の2段階decisionが、別々のprojectionとして成立することを固定する。"""

    def test_the_turn_offers_exactly_one_riichi_choice(self) -> None:
        state = _riichi_turn_state()

        projection = project_legal_actions(state.legal_actions(Seat.EAST), state)
        riichi_options = tuple(
            option
            for option in projection.options
            if isinstance(option, RiichiActionDescriptor)
        )

        self.assertEqual(riichi_options, (RiichiActionDescriptor(),))
        self.assertGreater(
            len(
                tuple(
                    option
                    for option in projection.options
                    if isinstance(option, DiscardActionDescriptor)
                )
            ),
            1,
        )
        self.assertEqual(
            projection.resolve(RiichiActionDescriptor()),
            RiichiLegalAction(),
        )

    def test_the_turn_never_offers_a_riichi_discard_descriptor(self) -> None:
        state = _riichi_turn_state()

        projection = project_legal_actions(state.legal_actions(Seat.EAST), state)

        self.assertTrue(
            all(
                type(option).__name__ != "RiichiDiscardActionDescriptor"
                for option in projection.options
            )
        )
        self.assertTrue(
            all(not hasattr(option, "tile_id") for option in projection.options)
        )

    def test_the_follow_up_builds_a_fresh_projection_of_plain_discards(self) -> None:
        state = _riichi_turn_state()
        turn = project_legal_actions(state.legal_actions(Seat.EAST), state)
        state.apply(
            Seat.EAST,
            turn.resolve(RiichiActionDescriptor()),
            expected_revision=turn.revision,
        )

        follow_up = project_legal_actions(state.legal_actions(Seat.EAST), state)

        self.assertEqual(follow_up.revision, turn.revision + 1)
        self.assertNotEqual(follow_up.options, ())
        self.assertTrue(
            all(
                isinstance(option, DiscardActionDescriptor)
                for option in follow_up.options
            )
        )
        self.assertLess(len(follow_up.options), len(turn.options))

    def test_the_pre_riichi_snapshot_cannot_be_projected_after_the_selection(
        self,
    ) -> None:
        state = _riichi_turn_state()
        stale_snapshot = state.legal_actions(Seat.EAST)
        stale_projection = project_legal_actions(stale_snapshot, state)
        state.apply(
            Seat.EAST,
            RiichiLegalAction(),
            expected_revision=stale_snapshot.revision,
        )

        with self.assertRaises(ActionProjectionError):
            project_legal_actions(stale_snapshot, state)
        self.assertNotEqual(stale_projection.revision, state.revision)

    def test_a_stale_projection_choice_is_rejected_by_the_round_state(self) -> None:
        state = _riichi_turn_state()
        stale = project_legal_actions(state.legal_actions(Seat.EAST), state)
        stale_discard = next(
            option
            for option in stale.options
            if isinstance(option, DiscardActionDescriptor)
        )
        state.apply(
            Seat.EAST,
            RiichiLegalAction(),
            expected_revision=stale.revision,
        )

        with self.assertRaises(StaleActionError):
            state.apply(
                Seat.EAST,
                stale.resolve(stale_discard),
                expected_revision=stale.revision,
            )


class ReactionActionProjectionTest(unittest.TestCase):
    def test_projects_all_reaction_variants_with_public_source_and_consumed_tiles(
        self,
    ) -> None:
        state = _reaction_state()
        target_id = state.pending_discard.tile.id
        consumed = tuple(tile.id for tile in state.hand_tiles(Seat.NORTH)[:3])
        snapshot = LegalActionSnapshot(
            Seat.NORTH,
            RoundPhase.AWAITING_REACTIONS,
            state.revision,
            (
                PassLegalAction(ReactionOrigin.DISCARD, target_id),
                RonLegalAction(ReactionOrigin.DISCARD, target_id),
                ChiLegalAction(target_id, consumed[:2]),
                PonLegalAction(target_id, consumed[:2]),
                DaiminkanLegalAction(target_id, consumed),
            ),
        )

        projection = project_legal_actions(snapshot, state)

        self.assertEqual(
            {type(option) for option in projection.options},
            {
                PassActionDescriptor,
                RonActionDescriptor,
                ChiActionDescriptor,
                PonActionDescriptor,
                DaiminkanActionDescriptor,
            },
        )
        self.assertTrue(
            all(option.from_seat is Seat.EAST for option in projection.options)
        )
        self.assertTrue(
            all(
                option.tile == projection.options[0].tile
                for option in projection.options
            )
        )

    def test_duplicate_calls_collapse_but_red_consumption_remains_distinct(
        self,
    ) -> None:
        hands = dict(_REACTION_HANDS)
        hands[Seat.SOUTH] = (
            "5p",
            "5p",
            "6p",
            "6p",
            *_REACTION_HANDS[Seat.SOUTH][2:-2],
        )
        state = new_state(
            build_wall(
                hands=hands,
                draws=("1z",),
                with_dead_wall=True,
            )
        )
        state.deal()
        draw_and_discard(state, Seat.EAST, "7p")
        target_id = state.pending_discard.tile.id

        south_tiles = state.hand_tiles(Seat.SOUTH)
        fives = tuple(tile for tile in south_tiles if tile.tile_type.id == 13)
        sixes = tuple(tile for tile in south_tiles if tile.tile_type.id == 14)
        red_five = next(tile for tile in fives if tile.is_red)
        normal_five = next(tile for tile in fives if not tile.is_red)
        chi_actions = (
            ChiLegalAction(target_id, (red_five.id, sixes[0].id)),
            ChiLegalAction(target_id, (red_five.id, sixes[1].id)),
            ChiLegalAction(target_id, (normal_five.id, sixes[0].id)),
        )
        north_sevens = tuple(
            tile.id for tile in state.hand_tiles(Seat.NORTH) if tile.tile_type.id == 15
        )
        pon_actions = (
            PonLegalAction(target_id, north_sevens[:2]),
            PonLegalAction(target_id, north_sevens[1:]),
        )

        south_projection = project_legal_actions(
            LegalActionSnapshot(
                Seat.SOUTH,
                state.phase,
                state.revision,
                chi_actions,
            ),
            state,
        )
        north_projection = project_legal_actions(
            LegalActionSnapshot(
                Seat.NORTH,
                state.phase,
                state.revision,
                pon_actions,
            ),
            state,
        )

        self.assertEqual(len(south_projection.options), 2)
        self.assertEqual(
            {
                next(
                    tile.is_red
                    for tile in option.consumed_tiles
                    if tile.tile_type.id == 13
                )
                for option in south_projection.options
            },
            {False, True},
        )
        self.assertEqual(len(north_projection.options), 1)
        self.assertEqual(
            north_projection.resolve(north_projection.options[0]).consumed_tile_ids,
            min(action.consumed_tile_ids for action in pon_actions),
        )

    def test_rejects_wrong_type_and_not_offered_choice_without_internal_details(
        self,
    ) -> None:
        state = _standard_turn_state()
        projection = project_legal_actions(state.legal_actions(Seat.EAST), state)

        for choice in (object(), NineTerminalsActionDescriptor()):
            with self.subTest(choice_type=type(choice).__name__):
                with self.assertRaises((TypeError, ValueError)) as raised:
                    projection.resolve(choice)
                message = str(raised.exception)
                self.assertNotIn("LegalAction", message)
                self.assertNotIn("tile_id", message)
                self.assertNotIn("seed", message)


class PublicOptionOrderingTest(unittest.TestCase):
    def test_physical_tile_identity_swap_does_not_change_public_options(self) -> None:
        wall = build_wall(
            hands=QUIET_HANDS,
            draws=QUIET_DRAWS,
            with_dead_wall=True,
        )
        tiles = list(wall.remaining_tiles)
        east_positions = set(deal_positions(Seat.EAST)[Seat.EAST])
        first_index, second_index = next(
            (first, second)
            for first in east_positions
            for second in range(len(tiles))
            if second not in east_positions
            and tiles[first].tile_type == tiles[second].tile_type
            and tiles[first].is_red == tiles[second].is_red
        )
        tiles[first_index], tiles[second_index] = (
            tiles[second_index],
            tiles[first_index],
        )

        first = new_state(Wall(wall.remaining_tiles, wall.dead_wall_tiles))
        second = new_state(Wall(tuple(tiles), wall.dead_wall_tiles))
        for state in (first, second):
            state.deal()
            state.draw(Seat.EAST)

        matches = []
        for state in (first, second):
            match = MatchState(seed=17)
            match._phase = MatchPhase.ROUND_IN_PROGRESS
            match._active_round = state
            matches.append(match)

        first_options = project_legal_actions(
            first.legal_actions(Seat.EAST),
            first,
        ).options
        second_options = project_legal_actions(
            second.legal_actions(Seat.EAST),
            second,
        ).options

        self.assertNotEqual(first.hand_tiles(Seat.EAST), second.hand_tiles(Seat.EAST))
        self.assertEqual(
            build_seat_observation(matches[0], Seat.EAST),
            build_seat_observation(matches[1], Seat.EAST),
        )
        self.assertEqual(first_options, second_options)


if __name__ == "__main__":
    unittest.main()
