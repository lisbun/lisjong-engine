import unittest
from dataclasses import replace

from lisjong_engine.legal_action import (
    ChiLegalAction,
    DaiminkanLegalAction,
    DiscardLegalAction,
    PassLegalAction,
    PonLegalAction,
    ReactionOrigin,
    RonLegalAction,
)
from lisjong_engine.reaction import (
    ReactionCandidate,
    ReactionChoice,
    ReactionResolution,
    ReactionType,
    is_reaction_action,
    reaction_action_sort_key,
    reaction_seat_order,
    reaction_type_of,
    resolve_reaction_choices,
)
from lisjong_engine.rules import RonResolutionPolicy
from lisjong_engine.seat import Seat

_TARGET = 40
_SOURCE = Seat.EAST

_PASS = PassLegalAction(ReactionOrigin.DISCARD, _TARGET)
_RON = RonLegalAction(ReactionOrigin.DISCARD, _TARGET)
_PON = PonLegalAction(_TARGET, (41, 42))
_CHI = ChiLegalAction(_TARGET, (44, 48))
_DAIMINKAN = DaiminkanLegalAction(_TARGET, (41, 42, 43))


def _candidates(**overrides) -> dict[Seat, tuple]:
    base = {seat: (_PASS,) for seat in reaction_seat_order(_SOURCE)}
    base.update(overrides)
    return base


def _choices(**overrides) -> dict[Seat, object]:
    base = {seat: _PASS for seat in reaction_seat_order(_SOURCE)}
    base.update(overrides)
    return base


def _resolve(
    *,
    candidates=None,
    choices=None,
    policy: RonResolutionPolicy = RonResolutionPolicy.MULTIPLE_RON,
    origin: ReactionOrigin = ReactionOrigin.DISCARD,
) -> ReactionResolution:
    return resolve_reaction_choices(
        origin=origin,
        source_seat=_SOURCE,
        target_tile_id=_TARGET,
        candidates=_candidates() if candidates is None else candidates,
        choices=_choices() if choices is None else choices,
        ron_resolution_policy=policy,
    )


class ReactionActionClassificationTest(unittest.TestCase):
    def test_maps_each_reaction_action_to_its_type(self) -> None:
        for action, reaction_type in (
            (_PASS, ReactionType.PASS),
            (_RON, ReactionType.RON),
            (_PON, ReactionType.PON),
            (_CHI, ReactionType.CHI),
            (_DAIMINKAN, ReactionType.DAIMINKAN),
        ):
            with self.subTest(action=action):
                self.assertIs(reaction_type_of(action), reaction_type)
                self.assertTrue(is_reaction_action(action))

    def test_turn_actions_are_not_reactions(self) -> None:
        self.assertFalse(is_reaction_action(DiscardLegalAction(1)))
        with self.assertRaises(TypeError):
            reaction_type_of(DiscardLegalAction(1))

    def test_sort_key_puts_pass_first_and_separates_call_types(self) -> None:
        actions = (_CHI, _DAIMINKAN, _PON, _RON, _PASS)

        self.assertEqual(
            tuple(sorted(actions, key=reaction_action_sort_key)),
            (_PASS, _RON, _PON, _DAIMINKAN, _CHI),
        )


class ReactionSeatOrderTest(unittest.TestCase):
    def test_orders_seats_by_distance_from_the_source(self) -> None:
        self.assertEqual(
            reaction_seat_order(Seat.EAST),
            (Seat.SOUTH, Seat.WEST, Seat.NORTH),
        )
        self.assertEqual(
            reaction_seat_order(Seat.WEST),
            (Seat.NORTH, Seat.EAST, Seat.SOUTH),
        )

    def test_rejects_a_value_that_is_not_a_seat(self) -> None:
        with self.assertRaises(TypeError):
            reaction_seat_order("east")


class ResolveReactionChoicesTest(unittest.TestCase):
    def test_all_pass_resolves_without_a_caller(self) -> None:
        resolution = _resolve()

        self.assertIs(resolution.resolved_type, ReactionType.PASS)
        self.assertTrue(resolution.all_passed)
        self.assertIsNone(resolution.resolved_seat)
        self.assertIsNone(resolution.resolved_action)
        self.assertEqual(resolution.ron_capable_seats, frozenset())

    def test_ron_beats_pon(self) -> None:
        resolution = _resolve(
            candidates={
                Seat.SOUTH: (_PASS,),
                Seat.WEST: (_PASS, _RON),
                Seat.NORTH: (_PASS, _PON),
            },
            choices={Seat.SOUTH: _PASS, Seat.WEST: _RON, Seat.NORTH: _PON},
        )

        self.assertIs(resolution.resolved_type, ReactionType.RON)
        self.assertEqual(resolution.ron_awarded_seats, (Seat.WEST,))

    def test_ron_beats_chi_and_daiminkan(self) -> None:
        resolution = _resolve(
            candidates={
                Seat.SOUTH: (_PASS, _CHI),
                Seat.WEST: (_PASS, _RON),
                Seat.NORTH: (_PASS, _DAIMINKAN),
            },
            choices={Seat.SOUTH: _CHI, Seat.WEST: _RON, Seat.NORTH: _DAIMINKAN},
        )

        self.assertIs(resolution.resolved_type, ReactionType.RON)
        self.assertEqual(resolution.ron_selected_seats, (Seat.WEST,))

    def test_pon_beats_chi(self) -> None:
        resolution = _resolve(
            candidates={
                Seat.SOUTH: (_PASS, _CHI),
                Seat.WEST: (_PASS,),
                Seat.NORTH: (_PASS, _PON),
            },
            choices={Seat.SOUTH: _CHI, Seat.WEST: _PASS, Seat.NORTH: _PON},
        )

        self.assertIs(resolution.resolved_type, ReactionType.PON)
        self.assertIs(resolution.resolved_seat, Seat.NORTH)
        self.assertEqual(resolution.resolved_action, _PON)

    def test_daiminkan_beats_chi(self) -> None:
        resolution = _resolve(
            candidates={
                Seat.SOUTH: (_PASS, _CHI),
                Seat.WEST: (_PASS,),
                Seat.NORTH: (_PASS, _DAIMINKAN),
            },
            choices={Seat.SOUTH: _CHI, Seat.WEST: _PASS, Seat.NORTH: _DAIMINKAN},
        )

        self.assertIs(resolution.resolved_type, ReactionType.DAIMINKAN)
        self.assertIs(resolution.resolved_seat, Seat.NORTH)

    def test_equal_priority_calls_resolve_by_seat_distance(self) -> None:
        """同順位の鳴きが並んだ場合は、放銃者に最も近い席が成立する。"""
        other_pon = PonLegalAction(_TARGET, (45, 46))
        resolution = _resolve(
            candidates={
                Seat.SOUTH: (_PASS, _PON),
                Seat.WEST: (_PASS, other_pon),
                Seat.NORTH: (_PASS,),
            },
            choices={Seat.SOUTH: _PON, Seat.WEST: other_pon, Seat.NORTH: _PASS},
        )

        self.assertIs(resolution.resolved_seat, Seat.SOUTH)

    def test_the_choice_iteration_order_does_not_change_the_result(self) -> None:
        candidates = {
            Seat.SOUTH: (_PASS, _CHI),
            Seat.WEST: (_PASS, _RON),
            Seat.NORTH: (_PASS, _PON),
        }
        forward = {Seat.SOUTH: _CHI, Seat.WEST: _RON, Seat.NORTH: _PON}
        reversed_choices = dict(reversed(list(forward.items())))

        self.assertEqual(
            _resolve(candidates=candidates, choices=forward),
            _resolve(candidates=candidates, choices=reversed_choices),
        )

    def test_multiple_ron_awards_every_selecting_seat(self) -> None:
        resolution = _resolve(
            candidates={
                Seat.SOUTH: (_PASS,),
                Seat.WEST: (_PASS, _RON),
                Seat.NORTH: (_PASS, _RON),
            },
            choices={Seat.SOUTH: _PASS, Seat.WEST: _RON, Seat.NORTH: _RON},
            policy=RonResolutionPolicy.MULTIPLE_RON,
        )

        self.assertEqual(resolution.ron_selected_seats, (Seat.WEST, Seat.NORTH))
        self.assertEqual(resolution.ron_awarded_seats, (Seat.WEST, Seat.NORTH))
        self.assertEqual(resolution.ron_passed_seats, frozenset())

    def test_head_bump_awards_only_the_nearest_selecting_seat(self) -> None:
        resolution = _resolve(
            candidates={
                Seat.SOUTH: (_PASS,),
                Seat.WEST: (_PASS, _RON),
                Seat.NORTH: (_PASS, _RON),
            },
            choices={Seat.SOUTH: _PASS, Seat.WEST: _RON, Seat.NORTH: _RON},
            policy=RonResolutionPolicy.HEAD_BUMP,
        )

        self.assertEqual(resolution.ron_selected_seats, (Seat.WEST, Seat.NORTH))
        self.assertEqual(resolution.ron_awarded_seats, (Seat.WEST,))

    def test_a_head_bumped_selector_did_not_pass(self) -> None:
        """頭ハネで成立しなかったロン選択者は「見逃し」ではない。"""
        resolution = _resolve(
            candidates={
                Seat.SOUTH: (_PASS,),
                Seat.WEST: (_PASS, _RON),
                Seat.NORTH: (_PASS, _RON),
            },
            choices={Seat.SOUTH: _PASS, Seat.WEST: _RON, Seat.NORTH: _RON},
            policy=RonResolutionPolicy.HEAD_BUMP,
        )

        self.assertNotIn(Seat.NORTH, resolution.ron_passed_seats)
        self.assertEqual(resolution.ron_passed_seats, frozenset())

    def test_a_capable_seat_that_chose_pass_is_recorded_as_passed(self) -> None:
        resolution = _resolve(
            candidates={
                Seat.SOUTH: (_PASS,),
                Seat.WEST: (_PASS, _RON),
                Seat.NORTH: (_PASS, _RON),
            },
            choices={Seat.SOUTH: _PASS, Seat.WEST: _RON, Seat.NORTH: _PASS},
        )

        self.assertEqual(
            resolution.ron_capable_seats,
            frozenset({Seat.WEST, Seat.NORTH}),
        )
        self.assertEqual(resolution.ron_selected_seats, (Seat.WEST,))
        self.assertEqual(resolution.ron_passed_seats, frozenset({Seat.NORTH}))

    def test_a_capable_seat_that_called_instead_is_recorded_as_passed(self) -> None:
        resolution = _resolve(
            candidates={
                Seat.SOUTH: (_PASS,),
                Seat.WEST: (_PASS, _RON, _PON),
                Seat.NORTH: (_PASS,),
            },
            choices={Seat.SOUTH: _PASS, Seat.WEST: _PON, Seat.NORTH: _PASS},
        )

        self.assertEqual(resolution.ron_capable_seats, frozenset({Seat.WEST}))
        self.assertEqual(resolution.ron_selected_seats, ())
        self.assertEqual(resolution.ron_passed_seats, frozenset({Seat.WEST}))

    def test_rejects_a_missing_seat(self) -> None:
        with self.assertRaises(ValueError):
            _resolve(choices={Seat.SOUTH: _PASS, Seat.WEST: _PASS})

    def test_rejects_an_extra_seat(self) -> None:
        with self.assertRaises(ValueError):
            _resolve(choices=_choices() | {Seat.EAST: _PASS})

    def test_rejects_a_choice_outside_the_seat_candidates(self) -> None:
        with self.assertRaises(ValueError):
            _resolve(
                choices={
                    Seat.SOUTH: _PON,
                    Seat.WEST: _PASS,
                    Seat.NORTH: _PASS,
                }
            )

    def test_rejects_an_action_from_another_window(self) -> None:
        other_pass = PassLegalAction(ReactionOrigin.DISCARD, _TARGET + 1)
        with self.assertRaises(ValueError):
            _resolve(
                candidates={
                    Seat.SOUTH: (other_pass,),
                    Seat.WEST: (_PASS,),
                    Seat.NORTH: (_PASS,),
                },
                choices={
                    Seat.SOUTH: other_pass,
                    Seat.WEST: _PASS,
                    Seat.NORTH: _PASS,
                },
            )

    def test_rejects_a_call_in_a_kakan_window(self) -> None:
        kakan_pass = PassLegalAction(ReactionOrigin.KAKAN, _TARGET)
        with self.assertRaises(ValueError):
            _resolve(
                origin=ReactionOrigin.KAKAN,
                candidates={
                    Seat.SOUTH: (kakan_pass, _PON),
                    Seat.WEST: (kakan_pass,),
                    Seat.NORTH: (kakan_pass,),
                },
                choices={
                    Seat.SOUTH: _PON,
                    Seat.WEST: kakan_pass,
                    Seat.NORTH: kakan_pass,
                },
            )

    def test_rejects_invalid_argument_types(self) -> None:
        with self.assertRaises(TypeError):
            _resolve(origin="discard")
        with self.assertRaises(TypeError):
            resolve_reaction_choices(
                origin=ReactionOrigin.DISCARD,
                source_seat=_SOURCE,
                target_tile_id=_TARGET,
                candidates=_candidates(),
                choices=[(Seat.SOUTH, _PASS)],
                ron_resolution_policy=RonResolutionPolicy.MULTIPLE_RON,
            )
        with self.assertRaises(TypeError):
            resolve_reaction_choices(
                origin=ReactionOrigin.DISCARD,
                source_seat=_SOURCE,
                target_tile_id=_TARGET,
                candidates=_candidates(),
                choices=_choices(),
                ron_resolution_policy="head_bump",
            )


class ReactionCandidateTest(unittest.TestCase):
    def test_a_candidate_always_offers_pass(self) -> None:
        with self.assertRaises(ValueError):
            ReactionCandidate(Seat.SOUTH, (_RON,))

    def test_rejects_duplicate_actions(self) -> None:
        with self.assertRaises(ValueError):
            ReactionCandidate(Seat.SOUTH, (_PASS, _PASS))

    def test_rejects_turn_actions(self) -> None:
        with self.assertRaises(TypeError):
            ReactionCandidate(Seat.SOUTH, (_PASS, DiscardLegalAction(1)))

    def test_can_ron_reflects_the_offered_actions(self) -> None:
        self.assertTrue(ReactionCandidate(Seat.SOUTH, (_PASS, _RON)).can_ron)
        self.assertFalse(ReactionCandidate(Seat.SOUTH, (_PASS, _PON)).can_ron)


class ReactionResolutionValidationTest(unittest.TestCase):
    def _valid(self) -> ReactionResolution:
        return _resolve(
            candidates={
                Seat.SOUTH: (_PASS,),
                Seat.WEST: (_PASS, _RON),
                Seat.NORTH: (_PASS, _RON),
            },
            choices={Seat.SOUTH: _PASS, Seat.WEST: _RON, Seat.NORTH: _RON},
            policy=RonResolutionPolicy.HEAD_BUMP,
        )

    def test_keeps_candidates_and_choices_in_seat_distance_order(self) -> None:
        resolution = self._valid()

        self.assertEqual(
            resolution.reacting_seats,
            (Seat.SOUTH, Seat.WEST, Seat.NORTH),
        )
        self.assertEqual(
            tuple(choice.seat for choice in resolution.choices),
            (Seat.SOUTH, Seat.WEST, Seat.NORTH),
        )

    def test_choice_for_returns_the_selected_action(self) -> None:
        resolution = self._valid()

        self.assertEqual(resolution.choice_for(Seat.WEST), _RON)
        with self.assertRaises(ValueError):
            resolution.choice_for(Seat.EAST)

    def test_rejects_awarded_seats_that_are_not_a_prefix_of_selected(self) -> None:
        resolution = self._valid()

        with self.assertRaises(ValueError):
            replace(resolution, ron_awarded_seats=(Seat.NORTH,))

    def test_rejects_passed_seats_that_are_not_derived_from_the_choices(self) -> None:
        resolution = self._valid()

        with self.assertRaises(ValueError):
            replace(resolution, ron_passed_seats=frozenset({Seat.WEST}))

    def test_rejects_a_call_resolution_while_a_ron_was_selected(self) -> None:
        resolution = self._valid()

        with self.assertRaises(ValueError):
            replace(
                resolution,
                resolved_type=ReactionType.PON,
                resolved_seat=Seat.WEST,
                resolved_action=_PON,
            )

    def test_rejects_an_all_pass_resolution_with_a_non_pass_choice(self) -> None:
        resolution = _resolve(
            candidates={
                Seat.SOUTH: (_PASS, _CHI),
                Seat.WEST: (_PASS,),
                Seat.NORTH: (_PASS,),
            },
            choices={Seat.SOUTH: _CHI, Seat.WEST: _PASS, Seat.NORTH: _PASS},
        )

        with self.assertRaises(ValueError):
            replace(
                resolution,
                resolved_type=ReactionType.PASS,
                resolved_seat=None,
                resolved_action=None,
            )

    def test_rejects_a_choice_set_that_misses_a_reacting_seat(self) -> None:
        resolution = self._valid()

        with self.assertRaises(ValueError):
            replace(resolution, choices=resolution.choices[:2])

    def test_rejects_a_choice_outside_the_seat_candidates(self) -> None:
        resolution = self._valid()

        with self.assertRaises(ValueError):
            replace(
                resolution,
                choices=(
                    ReactionChoice(Seat.SOUTH, _CHI),
                    *resolution.choices[1:],
                ),
            )


if __name__ == "__main__":
    unittest.main()
