import copy
import unittest
from dataclasses import fields, replace

from _round_fixtures import quiet_state, tiles

from lisjong_engine.discard import Discard
from lisjong_engine.kan import PendingAnkan, PendingKakan
from lisjong_engine.legal_action import DiscardLegalAction
from lisjong_engine.match_state import MatchPhase, MatchState
from lisjong_engine.meld import Ankan, Chi, Daiminkan, Kakan, Pon
from lisjong_engine.observation import ObservationDecisionKind, SeatObservation
from lisjong_engine.observation_builder import (
    _decision_kind_from_phase,
    build_seat_observation,
)
from lisjong_engine.player_state import PlayerState
from lisjong_engine.public_state import PublicMeldType
from lisjong_engine.public_state import public_meld as _public_meld
from lisjong_engine.reaction import ReactionType
from lisjong_engine.riichi_event import (
    RiichiDeclaration,
    finalize_riichi_declaration,
)
from lisjong_engine.round_allocation import create_round_random_provenance
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile
from lisjong_engine.wall import Wall
from lisjong_engine.win_context import RiichiStatus


def _started_turn_match(*, seed: int = 1) -> tuple[MatchState, object]:
    match = MatchState(seed=seed)
    round_state = match.start_round()
    round_state.draw(round_state.current_seat)
    return match, round_state


def _attach(match: MatchState, round_state) -> MatchState:
    """Observation fixture専用に、手作りRoundStateをMatchへattachする。"""
    match._phase = MatchPhase.ROUND_IN_PROGRESS
    match._active_round = round_state
    return match


def _turn_fixture() -> tuple[MatchState, object]:
    round_state = quiet_state(with_dead_wall=True)
    round_state.draw(Seat.EAST)
    return _attach(MatchState(seed=1), round_state), round_state


def _declaration(
    discard: Discard,
    *,
    seat: Seat = Seat.EAST,
) -> RiichiDeclaration:
    return RiichiDeclaration(
        seat=seat,
        discard=discard,
        discard_count=1,
        remaining_live_tiles=10,
        was_first_discard=True,
        had_prior_call=False,
    )


class ObservationBuilderValidationTest(unittest.TestCase):
    def test_rejects_wrong_input_types(self) -> None:
        with self.assertRaises(TypeError):
            build_seat_observation(object(), Seat.EAST)
        with self.assertRaises(TypeError):
            build_seat_observation(MatchState(seed=1), "east")

    def test_rejects_match_without_an_active_decision_round(self) -> None:
        match = MatchState(seed=1)
        with self.assertRaises(RuntimeError):
            build_seat_observation(match, Seat.EAST)

        match._phase = MatchPhase.ROUND_IN_PROGRESS
        with self.assertRaises(RuntimeError):
            build_seat_observation(match, Seat.EAST)

        match, round_state = _started_turn_match()
        round_state._phase = RoundPhase.AWAITING_DRAW
        with self.assertRaises(RuntimeError):
            build_seat_observation(match, Seat.EAST)

    def test_rejects_a_seat_not_required_to_decide(self) -> None:
        match, _ = _started_turn_match()
        with self.assertRaises(RuntimeError):
            build_seat_observation(match, Seat.SOUTH)

    def test_maps_only_the_decision_phases(self) -> None:
        expected = {
            RoundPhase.AWAITING_DISCARD: ObservationDecisionKind.TURN,
            RoundPhase.AWAITING_RIICHI_DISCARD: (
                ObservationDecisionKind.RIICHI_DISCARD
            ),
            RoundPhase.AWAITING_REACTIONS: (ObservationDecisionKind.DISCARD_REACTION),
            RoundPhase.AWAITING_KAKAN_REACTIONS: (
                ObservationDecisionKind.KAKAN_REACTION
            ),
            RoundPhase.AWAITING_ANKAN_REACTIONS: (
                ObservationDecisionKind.ANKAN_REACTION
            ),
        }
        for phase, decision_kind in expected.items():
            with self.subTest(phase=phase):
                self.assertIs(_decision_kind_from_phase(phase), decision_kind)
        for phase in set(RoundPhase) - set(expected):
            with self.subTest(phase=phase):
                with self.assertRaises(RuntimeError):
                    _decision_kind_from_phase(phase)

    def test_builds_each_reaction_kind_only_for_a_reacting_seat(self) -> None:
        match, round_state = _turn_fixture()
        target_tiles = tiles("2z", "3z", "3z", "3z", "3z", "4z", "4z", "4z", "4z")
        discard = Discard(target_tiles[0], False)
        pon = Pon(target_tiles[1], target_tiles[2:4], Seat.SOUTH)
        cases = (
            (
                RoundPhase.AWAITING_REACTIONS,
                "_pending_discarder",
                Seat.EAST,
                "_pending_discard",
                discard,
                ObservationDecisionKind.DISCARD_REACTION,
            ),
            (
                RoundPhase.AWAITING_KAKAN_REACTIONS,
                "_pending_kakan",
                PendingKakan(Seat.EAST, Kakan(pon, target_tiles[4])),
                None,
                None,
                ObservationDecisionKind.KAKAN_REACTION,
            ),
            (
                RoundPhase.AWAITING_ANKAN_REACTIONS,
                "_pending_ankan",
                PendingAnkan(Seat.EAST, Ankan(target_tiles[5:9])),
                None,
                None,
                ObservationDecisionKind.ANKAN_REACTION,
            ),
        )
        for phase, field_a, value_a, field_b, value_b, expected in cases:
            with self.subTest(phase=phase):
                round_state._phase = phase
                round_state._pending_discarder = None
                round_state._pending_discard = None
                round_state._pending_kakan = None
                round_state._pending_ankan = None
                setattr(round_state, field_a, value_a)
                if field_b is not None:
                    setattr(round_state, field_b, value_b)

                observation = build_seat_observation(match, Seat.SOUTH)

                self.assertIs(observation.decision_kind, expected)
                with self.assertRaises(RuntimeError):
                    build_seat_observation(match, Seat.EAST)


class ObservationBuilderProjectionTest(unittest.TestCase):
    def test_projects_only_the_viewers_hand_and_all_public_seat_state(self) -> None:
        match, round_state = _started_turn_match()
        observation = build_seat_observation(match, Seat.EAST)

        self.assertIsInstance(observation, SeatObservation)
        self.assertEqual(len(observation.hand_tiles), 14)
        self.assertEqual(
            tuple(item.seat for item in observation.discards),
            tuple(Seat),
        )
        self.assertEqual(tuple(item.seat for item in observation.melds), tuple(Seat))
        self.assertEqual(tuple(item.seat for item in observation.scores), tuple(Seat))
        self.assertEqual(
            tuple(item.seat for item in observation.riichi_states),
            tuple(Seat),
        )
        self.assertEqual(
            observation.remaining_live_wall_count,
            round_state.remaining_count,
        )
        self.assertFalse(
            any(
                hasattr(tile, attribute)
                for tile in (*observation.hand_tiles, *observation.dora_indicators)
                for attribute in ("id", "copy_index")
            )
        )

        field_names = {field.name for field in fields(SeatObservation)}
        self.assertTrue(
            field_names.isdisjoint(
                {
                    "opponent_hands",
                    "concealed_hand_counts",
                    "remaining_tiles",
                    "dead_wall_tiles",
                    "ura_dora_indicators",
                    "match_seed",
                    "round_seed",
                    "random_provenance",
                    "legal_actions",
                    "action_options",
                }
            )
        )

    def test_keeps_discard_tsumogiri_and_called_by(self) -> None:
        match, round_state = _turn_fixture()
        discarded_tile = round_state.hand_tiles(Seat.SOUTH)[0]
        round_state._players[Seat.SOUTH] = PlayerState(
            Seat.SOUTH,
            discards=(Discard(discarded_tile, True, Seat.WEST),),
        )

        public_discard = (
            build_seat_observation(match, Seat.EAST).discards[1].discards[0]
        )

        self.assertTrue(public_discard.is_tsumogiri)
        self.assertIs(public_discard.called_by, Seat.WEST)

    def test_projects_all_five_meld_types_with_publicly_sorted_tiles(self) -> None:
        one, two, three, four = tiles("3m", "3m", "3m", "3m")
        chi_tiles = tiles("3p", "1p", "2p")
        pon = Pon(one, (two, three), Seat.EAST)
        melds = (
            Chi(chi_tiles[0], chi_tiles[1:], Seat.NORTH),
            pon,
            Daiminkan(one, (two, three, four), Seat.SOUTH),
            Kakan(pon, four),
            Ankan((one, two, three, four)),
        )
        expected_types = (
            PublicMeldType.CHI,
            PublicMeldType.PON,
            PublicMeldType.DAIMINKAN,
            PublicMeldType.KAKAN,
            PublicMeldType.ANKAN,
        )

        projected = tuple(_public_meld(meld) for meld in melds)

        self.assertEqual(tuple(meld.meld_type for meld in projected), expected_types)
        self.assertEqual(
            tuple(tile.tile_type.rank for tile in projected[0].tiles),
            (1, 2, 3),
        )
        self.assertIsNone(projected[-1].from_seat)
        self.assertTrue(all(meld.from_seat is not None for meld in projected[:-1]))
        with self.assertRaises(TypeError):
            _public_meld(object())

    def test_pending_kakan_and_ankan_do_not_enter_established_melds(self) -> None:
        match, round_state = _turn_fixture()
        one, two, three, four = tiles("6s", "6s", "6s", "6s")
        pon = Pon(one, (two, three), Seat.SOUTH)
        round_state._pending_kakan = PendingKakan(Seat.EAST, Kakan(pon, four))
        round_state._pending_ankan = PendingAnkan(
            Seat.EAST,
            Ankan((one, two, three, four)),
        )

        observation = build_seat_observation(match, Seat.EAST)

        self.assertTrue(all(not seat_melds.melds for seat_melds in observation.melds))

    def test_exposes_only_revealed_dora_even_when_delayed_kan_dora_is_pending(
        self,
    ) -> None:
        match, round_state = _turn_fixture()
        round_state._pending_kan_dora_reveals = (Seat.SOUTH,)

        observation = build_seat_observation(match, Seat.EAST)

        self.assertEqual(len(observation.dora_indicators), 1)
        self.assertEqual(
            observation.dora_indicators[0].tile_type,
            round_state.revealed_dora_indicators[0].tile_type,
        )


class ObservationBuilderRiichiTest(unittest.TestCase):
    def _install_declaration(
        self,
        *,
        reaction_type: ReactionType | None,
        called_by: Seat | None = None,
    ) -> tuple[MatchState, object]:
        match, round_state = _turn_fixture()
        tile = tiles("7z")[0]
        river_discard = Discard(tile, False, called_by)
        declaration = _declaration(Discard(tile, False))
        round_state._players[Seat.EAST] = PlayerState(
            Seat.EAST,
            discards=(river_discard,),
            riichi_status=(
                RiichiStatus.RIICHI
                if reaction_type is not None and reaction_type is not ReactionType.RON
                else RiichiStatus.NONE
            ),
        )
        if reaction_type is None:
            round_state._pending_riichi_declaration = declaration
        else:
            round_state._riichi_finalizations = (
                finalize_riichi_declaration(
                    declaration,
                    reaction_type=reaction_type,
                    riichi_stick_points=round_state.rules.riichi_stick_points,
                ),
            )
        return match, round_state

    def test_marks_only_an_established_riichi_declaration_tile(self) -> None:
        for reaction_type, expected in (
            (None, False),
            (ReactionType.RON, False),
            (ReactionType.PASS, True),
            (ReactionType.CHI, True),
            (ReactionType.PON, True),
            (ReactionType.DAIMINKAN, True),
        ):
            with self.subTest(reaction_type=reaction_type):
                match, _ = self._install_declaration(
                    reaction_type=reaction_type,
                    called_by=(
                        Seat.SOUTH
                        if reaction_type
                        in (
                            ReactionType.CHI,
                            ReactionType.PON,
                            ReactionType.DAIMINKAN,
                        )
                        else None
                    ),
                )
                discard = (
                    build_seat_observation(
                        match,
                        Seat.EAST,
                    )
                    .discards[0]
                    .discards[0]
                )
                self.assertIs(discard.is_riichi_declaration, expected)

    def test_visible_scores_and_sticks_use_established_contributions(self) -> None:
        match, round_state = self._install_declaration(reaction_type=ReactionType.PASS)
        match._position = replace(match.position, riichi_sticks=2)
        scores_before = match.scores
        position_before = match.position

        observation = build_seat_observation(match, Seat.EAST)

        scores = {score.seat: score.points for score in observation.scores}
        self.assertEqual(scores[Seat.EAST], match.scores[Seat.EAST] - 1_000)
        self.assertEqual(scores[Seat.SOUTH], match.scores[Seat.SOUTH])
        self.assertEqual(observation.riichi_sticks, 3)
        self.assertEqual(match.scores, scores_before)
        self.assertEqual(match.position, position_before)
        self.assertEqual(len(round_state.riichi_contributions), 1)

    def test_pending_or_failed_riichi_does_not_change_visible_score_or_sticks(
        self,
    ) -> None:
        for reaction_type in (None, ReactionType.RON):
            with self.subTest(reaction_type=reaction_type):
                match, _ = self._install_declaration(reaction_type=reaction_type)
                observation = build_seat_observation(match, Seat.EAST)
                self.assertEqual(
                    tuple(score.points for score in observation.scores),
                    tuple(match.scores[seat] for seat in Seat),
                )
                self.assertEqual(observation.riichi_sticks, 0)


class ObservationBuilderHiddenStateEquivalenceTest(unittest.TestCase):
    def test_opponent_concealed_hand_and_count_do_not_affect_observation(self) -> None:
        match_a, _ = _started_turn_match(seed=10)
        match_b, round_b = _started_turn_match(seed=10)
        round_b._players[Seat.SOUTH] = PlayerState(Seat.SOUTH)

        self.assertEqual(
            build_seat_observation(match_a, Seat.EAST),
            build_seat_observation(match_b, Seat.EAST),
        )

    def test_hidden_live_wall_order_does_not_affect_observation(self) -> None:
        match_a, _ = _started_turn_match(seed=11)
        match_b, round_b = _started_turn_match(seed=11)
        round_b._wall = Wall(
            tuple(reversed(round_b.remaining_tiles)),
            round_b.dead_wall_tiles,
        )

        self.assertEqual(
            build_seat_observation(match_a, Seat.EAST),
            build_seat_observation(match_b, Seat.EAST),
        )

    def test_hidden_dead_wall_and_ura_do_not_affect_observation(self) -> None:
        match_a, _ = _started_turn_match(seed=12)
        match_b, round_b = _started_turn_match(seed=12)
        hidden_dead_wall = list(round_b.dead_wall_tiles)
        hidden_dead_wall[5], hidden_dead_wall[7] = (
            hidden_dead_wall[7],
            hidden_dead_wall[5],
        )
        round_b._wall = Wall(round_b.remaining_tiles, hidden_dead_wall)

        self.assertEqual(
            build_seat_observation(match_a, Seat.EAST),
            build_seat_observation(match_b, Seat.EAST),
        )

    def test_physical_copies_do_not_affect_publicly_equal_hand(self) -> None:
        match_a, _ = _started_turn_match(seed=13)
        match_b, round_b = _started_turn_match(seed=13)
        public_equivalent_hand = tuple(
            Tile(tile.tile_type, (tile.copy_index + 1) % 4, tile.is_red)
            for tile in round_b.hand_tiles(Seat.EAST)
        )
        round_b._players[Seat.EAST] = PlayerState(
            Seat.EAST,
            public_equivalent_hand,
        )

        self.assertEqual(
            build_seat_observation(match_a, Seat.EAST),
            build_seat_observation(match_b, Seat.EAST),
        )

    def test_match_and_round_random_provenance_do_not_affect_observation(self) -> None:
        match_a, round_state = _started_turn_match(seed=14)
        match_b = _attach(MatchState(seed=999), round_state)
        match_a._active_round_random_provenance = create_round_random_provenance(14, 1)
        match_b._active_round_random_provenance = create_round_random_provenance(999, 1)

        self.assertEqual(
            build_seat_observation(match_a, Seat.EAST),
            build_seat_observation(match_b, Seat.EAST),
        )

    def test_projection_is_deterministic_and_snapshot_isolated(self) -> None:
        match, round_state = _started_turn_match(seed=15)
        observation = build_seat_observation(match, Seat.EAST)
        saved_snapshot = copy.deepcopy(observation)
        self.assertEqual(observation, build_seat_observation(match, Seat.EAST))

        snapshot = round_state.legal_actions(Seat.EAST)
        discard = next(
            action
            for action in snapshot.actions
            if isinstance(action, DiscardLegalAction)
        )
        round_state.apply(
            Seat.EAST,
            discard,
            expected_revision=snapshot.revision,
        )

        self.assertEqual(observation, saved_snapshot)


if __name__ == "__main__":
    unittest.main()
