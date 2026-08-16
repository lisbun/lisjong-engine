import unittest
from dataclasses import replace

from _round_fixtures import tiles

from lisjong_engine.discard import Discard
from lisjong_engine.kan import PendingAnkan, PendingKakan
from lisjong_engine.legal_action import (
    AnkanLegalAction,
    ChiLegalAction,
    DaiminkanLegalAction,
    DiscardDeclaration,
    DiscardLegalAction,
    KakanLegalAction,
    PassLegalAction,
    PonLegalAction,
    ReactionOrigin,
    RonLegalAction,
)
from lisjong_engine.legal_actions import (
    RoundView,
    derive_discardable_tiles,
    derive_kuikae_forbidden_tile_types,
    derive_legal_actions,
    derive_riichi_discard_tiles,
)
from lisjong_engine.meld import Ankan, Chi, Kakan, Pon
from lisjong_engine.player_state import PlayerState
from lisjong_engine.round_event import DrawSource
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.rules import RuleSet
from lisjong_engine.seat import Seat
from lisjong_engine.tile import TileCategory, TileType
from lisjong_engine.win_context import RiichiStatus
from lisjong_engine.wind import Wind

_RULES = RuleSet.default()
_SEAT_WINDS = {
    Seat.EAST: Wind.EAST,
    Seat.SOUTH: Wind.SOUTH,
    Seat.WEST: Wind.WEST,
    Seat.NORTH: Wind.NORTH,
}
_TANYAO_TENPAI = tiles(
    "2m", "3m", "4m", "5m", "6m", "7m", "2p", "3p", "4p", "5p", "6p", "2s", "2s"
)
_SEVEN_PIN = tiles("7p", "7p", "7p", "7p")
# `_TANYAO_TENPAI`と物理牌が衝突しない、鳴き用の別copy。
_CHI_TILES = tiles("1m", "2m", "2m", "3m", "3m")
_DEAD_DRAW = tiles("9s")[0]


def _view(
    *,
    phase: RoundPhase = RoundPhase.AWAITING_DISCARD,
    current_seat: Seat | None = Seat.EAST,
    players: dict[Seat, PlayerState] | None = None,
    rules: RuleSet = _RULES,
    round_start_points: dict[Seat, int] | None = None,
    remaining_count: int = 40,
    can_draw_rinshan: bool = True,
    **overrides,
) -> RoundView:
    return RoundView(
        phase=phase,
        current_seat=current_seat,
        players=(
            {seat: PlayerState(seat) for seat in Seat} if players is None else players
        ),
        seat_winds=_SEAT_WINDS,
        prevailing_wind=Wind.EAST,
        rules=rules,
        round_start_points=(
            {seat: rules.starting_points for seat in Seat}
            if round_start_points is None
            else round_start_points
        ),
        remaining_count=remaining_count,
        can_draw_rinshan=can_draw_rinshan,
        **overrides,
    )


def _players(**hands_by_seat) -> dict[Seat, PlayerState]:
    players = {seat: PlayerState(seat) for seat in Seat}
    for seat_name, player in hands_by_seat.items():
        players[Seat[seat_name.upper()]] = player
    return players


class RoundViewValidationTest(unittest.TestCase):
    def test_requires_every_seat(self) -> None:
        with self.assertRaises(ValueError):
            _view(players={Seat.EAST: PlayerState(Seat.EAST)})

    def test_rejects_invalid_fields(self) -> None:
        with self.assertRaises(TypeError):
            _view(phase="awaiting_discard")
        with self.assertRaises(TypeError):
            _view(current_seat="east")
        with self.assertRaises(TypeError):
            _view(rules="standard", round_start_points={seat: 25_000 for seat in Seat})
        with self.assertRaises(TypeError):
            _view(players={seat: seat for seat in Seat})


class DeriveTurnActionsTest(unittest.TestCase):
    def _tenpai_view(self, **overrides) -> RoundView:
        """聴牌手に、手を崩す牌を1枚ツモった局面を作る。

        ツモ牌以外を打つと聴牌が崩れるため、立直宣言できる打牌が
        ツモ牌だけへ絞られる。
        """
        hand = (*_TANYAO_TENPAI, _DEAD_DRAW)
        player = PlayerState(Seat.EAST, hand)
        overrides.setdefault("drawn_tile_id", _DEAD_DRAW.id)
        return _view(players=_players(east=player), **overrides)

    def test_lists_every_hand_tile_as_a_discard_candidate(self) -> None:
        view = self._tenpai_view()

        actions = derive_legal_actions(view, Seat.EAST)

        discards = tuple(
            action
            for action in actions
            if isinstance(action, DiscardLegalAction)
            and action.declaration is DiscardDeclaration.NONE
        )
        self.assertEqual(len(discards), 14)
        self.assertEqual(
            tuple(action.tile_id for action in discards),
            tuple(sorted(action.tile_id for action in discards)),
        )

    def test_offers_nothing_to_a_seat_that_is_not_the_current_seat(self) -> None:
        self.assertEqual(derive_legal_actions(self._tenpai_view(), Seat.SOUTH), ())

    def test_offers_nothing_outside_the_acting_phases(self) -> None:
        for phase in (
            RoundPhase.UNDEALT,
            RoundPhase.AWAITING_DRAW,
            RoundPhase.AWAITING_RINSHAN_DRAW,
            RoundPhase.AWAITING_WIN_FINALIZATION,
            RoundPhase.FINISHED,
        ):
            with self.subTest(phase=phase):
                view = self._tenpai_view(phase=phase, drawn_tile_id=None)
                self.assertEqual(derive_legal_actions(view, Seat.EAST), ())

    def test_offers_a_riichi_declaration_for_every_tenpai_discard(self) -> None:
        view = self._tenpai_view()

        riichi_tiles = derive_riichi_discard_tiles(view, Seat.EAST)

        self.assertEqual(
            tuple(tile.id for tile in riichi_tiles),
            (_DEAD_DRAW.id,),
        )
        self.assertIn(
            DiscardLegalAction(_DEAD_DRAW.id, DiscardDeclaration.RIICHI),
            derive_legal_actions(view, Seat.EAST),
        )

    def test_a_hand_below_the_minimum_points_cannot_declare_riichi(self) -> None:
        below = {seat: _RULES.starting_points for seat in Seat}
        below[Seat.EAST] = _RULES.riichi_minimum_points - 1

        view = self._tenpai_view(round_start_points=below)

        self.assertEqual(derive_riichi_discard_tiles(view, Seat.EAST), ())

    def test_exactly_the_minimum_points_can_declare_riichi(self) -> None:
        boundary = {seat: _RULES.starting_points for seat in Seat}
        boundary[Seat.EAST] = _RULES.riichi_minimum_points

        view = self._tenpai_view(round_start_points=boundary)

        self.assertNotEqual(derive_riichi_discard_tiles(view, Seat.EAST), ())

    def test_no_minimum_points_allows_riichi_from_any_score(self) -> None:
        rules = replace(_RULES, riichi_minimum_points=None)
        broke = {seat: 0 for seat in Seat}
        broke[Seat.EAST] = -3_000

        view = self._tenpai_view(rules=rules, round_start_points=broke)

        self.assertNotEqual(derive_riichi_discard_tiles(view, Seat.EAST), ())

    def test_a_short_live_wall_prevents_riichi(self) -> None:
        view = self._tenpai_view(
            remaining_count=_RULES.riichi_minimum_live_wall_tiles - 1
        )

        self.assertEqual(derive_riichi_discard_tiles(view, Seat.EAST), ())

    def test_an_open_hand_cannot_declare_riichi(self) -> None:
        chi = Chi(_CHI_TILES[0], (_CHI_TILES[2], _CHI_TILES[4]), Seat.NORTH)
        player = PlayerState(
            Seat.EAST,
            (*_TANYAO_TENPAI[:10], _DEAD_DRAW),
            melds=(chi,),
        )
        view = _view(
            players=_players(east=player),
            drawn_tile_id=_DEAD_DRAW.id,
        )

        self.assertEqual(derive_riichi_discard_tiles(view, Seat.EAST), ())

    def test_an_established_riichi_seat_can_only_discard_the_drawn_tile(self) -> None:
        player = PlayerState(
            Seat.EAST,
            (*_TANYAO_TENPAI, _DEAD_DRAW),
            riichi_status=RiichiStatus.RIICHI,
        )
        view = _view(players=_players(east=player), drawn_tile_id=_DEAD_DRAW.id)

        self.assertEqual(
            tuple(tile.id for tile in derive_discardable_tiles(view, Seat.EAST)),
            (_DEAD_DRAW.id,),
        )
        self.assertEqual(derive_riichi_discard_tiles(view, Seat.EAST), ())

    def test_offers_an_ankan_for_a_hand_with_four_copies(self) -> None:
        hand = (*_TANYAO_TENPAI[:10], *_SEVEN_PIN)
        player = PlayerState(Seat.EAST, hand)
        view = _view(players=_players(east=player), drawn_tile_id=_SEVEN_PIN[3].id)

        actions = derive_legal_actions(view, Seat.EAST)

        self.assertIn(
            AnkanLegalAction(tuple(tile.id for tile in _SEVEN_PIN)),
            actions,
        )

    def test_an_ankan_needs_a_drawn_tile_and_an_available_rinshan(self) -> None:
        hand = (*_TANYAO_TENPAI[:10], *_SEVEN_PIN)
        player = PlayerState(Seat.EAST, hand)

        for overrides in (
            {"drawn_tile_id": None},
            {"drawn_tile_id": _SEVEN_PIN[3].id, "can_draw_rinshan": False},
        ):
            with self.subTest(overrides=overrides):
                view = _view(players=_players(east=player), **overrides)
                self.assertFalse(
                    any(
                        isinstance(action, AnkanLegalAction)
                        for action in derive_legal_actions(view, Seat.EAST)
                    )
                )

    def test_offers_a_kakan_for_a_tile_matching_an_existing_pon(self) -> None:
        pon = Pon(_SEVEN_PIN[0], _SEVEN_PIN[1:3], Seat.NORTH)
        player = PlayerState(
            Seat.EAST,
            (*_TANYAO_TENPAI[:10], _SEVEN_PIN[3]),
            melds=(pon,),
        )
        view = _view(players=_players(east=player), drawn_tile_id=_SEVEN_PIN[3].id)

        self.assertIn(
            KakanLegalAction(_SEVEN_PIN[3].id),
            derive_legal_actions(view, Seat.EAST),
        )

    def test_a_hand_without_the_matching_pon_has_no_kakan(self) -> None:
        ankan = Ankan(_SEVEN_PIN)
        player = PlayerState(Seat.EAST, _TANYAO_TENPAI[:11], melds=(ankan,))
        view = _view(
            players=_players(east=player),
            drawn_tile_id=_TANYAO_TENPAI[0].id,
        )

        self.assertFalse(
            any(
                isinstance(action, KakanLegalAction)
                for action in derive_legal_actions(view, Seat.EAST)
            )
        )


class KuikaeTest(unittest.TestCase):
    def _view_after_call(self, meld) -> RoundView:
        player = PlayerState(Seat.EAST, _TANYAO_TENPAI[:10], melds=(meld,))
        return _view(players=_players(east=player), drawn_tile_id=None)

    def test_a_pon_forbids_discarding_the_same_tile_type(self) -> None:
        pon = Pon(_SEVEN_PIN[0], _SEVEN_PIN[1:3], Seat.NORTH)

        forbidden = derive_kuikae_forbidden_tile_types(
            self._view_after_call(pon),
            Seat.EAST,
        )

        self.assertEqual(forbidden, frozenset({_SEVEN_PIN[0].tile_type}))

    def test_a_ryanmen_chi_also_forbids_the_other_end(self) -> None:
        chi_tiles = tiles("4m", "4m", "5m", "5m", "6m", "6m")
        chi = Chi(chi_tiles[1], (chi_tiles[3], chi_tiles[5]), Seat.NORTH)

        forbidden = derive_kuikae_forbidden_tile_types(
            self._view_after_call(chi),
            Seat.EAST,
        )

        self.assertEqual(
            forbidden,
            frozenset(
                {
                    TileType(TileCategory.MANZU, 4),
                    TileType(TileCategory.MANZU, 7),
                }
            ),
        )

    def test_a_kanchan_chi_forbids_only_the_called_tile_type(self) -> None:
        chi_tiles = tiles("4m", "4m", "5m", "5m", "6m", "6m")
        chi = Chi(chi_tiles[3], (chi_tiles[1], chi_tiles[5]), Seat.NORTH)

        forbidden = derive_kuikae_forbidden_tile_types(
            self._view_after_call(chi),
            Seat.EAST,
        )

        self.assertEqual(forbidden, frozenset({TileType(TileCategory.MANZU, 5)}))

    def test_a_drawn_tile_clears_the_kuikae_restriction(self) -> None:
        pon = Pon(_SEVEN_PIN[0], _SEVEN_PIN[1:3], Seat.NORTH)
        player = PlayerState(
            Seat.EAST,
            (*_TANYAO_TENPAI[:10], _SEVEN_PIN[3]),
            melds=(pon,),
        )
        view = _view(players=_players(east=player), drawn_tile_id=_SEVEN_PIN[3].id)

        self.assertEqual(
            derive_kuikae_forbidden_tile_types(view, Seat.EAST),
            frozenset(),
        )


class DeriveDiscardReactionActionsTest(unittest.TestCase):
    def _view(self, **overrides) -> RoundView:
        discard = Discard(_SEVEN_PIN[0], is_tsumogiri=True)
        players = overrides.pop("players", None) or _players()
        return _view(
            phase=RoundPhase.AWAITING_REACTIONS,
            current_seat=None,
            players=players,
            pending_discarder=Seat.EAST,
            pending_discard=discard,
            pending_discard_source=DrawSource.LIVE_WALL,
            **overrides,
        )

    def test_the_discarding_seat_has_no_reaction(self) -> None:
        self.assertEqual(derive_legal_actions(self._view(), Seat.EAST), ())

    def test_a_seat_that_cannot_react_still_gets_a_pass(self) -> None:
        actions = derive_legal_actions(self._view(), Seat.WEST)

        self.assertEqual(
            actions,
            (PassLegalAction(ReactionOrigin.DISCARD, _SEVEN_PIN[0].id),),
        )

    def test_offers_a_pon_and_a_daiminkan_for_matching_tiles(self) -> None:
        player = PlayerState(Seat.WEST, (*_TANYAO_TENPAI[:10], *_SEVEN_PIN[1:]))
        view = self._view(players=_players(west=player))

        actions = derive_legal_actions(view, Seat.WEST)

        self.assertEqual(
            sum(1 for action in actions if isinstance(action, PonLegalAction)),
            3,
        )
        self.assertIn(
            DaiminkanLegalAction(
                _SEVEN_PIN[0].id,
                tuple(tile.id for tile in _SEVEN_PIN[1:]),
            ),
            actions,
        )

    def test_only_the_next_seat_may_chi(self) -> None:
        chi_tiles = tiles("5p", "5p", "5p", "6p", "6p", "6p")
        next_player = PlayerState(Seat.SOUTH, (chi_tiles[1], chi_tiles[4]))
        far_player = PlayerState(Seat.NORTH, (chi_tiles[2], chi_tiles[5]))

        view = self._view(players=_players(south=next_player, north=far_player))

        self.assertIn(
            ChiLegalAction(_SEVEN_PIN[0].id, (chi_tiles[1].id, chi_tiles[4].id)),
            derive_legal_actions(view, Seat.SOUTH),
        )
        self.assertFalse(
            any(
                isinstance(action, ChiLegalAction)
                for action in derive_legal_actions(view, Seat.NORTH)
            )
        )

    def test_an_empty_live_wall_removes_pon_and_chi(self) -> None:
        player = PlayerState(Seat.WEST, (*_TANYAO_TENPAI[:10], *_SEVEN_PIN[1:]))
        view = self._view(
            players=_players(west=player),
            remaining_count=0,
            can_draw_rinshan=False,
        )

        self.assertEqual(
            derive_legal_actions(view, Seat.WEST),
            (PassLegalAction(ReactionOrigin.DISCARD, _SEVEN_PIN[0].id),),
        )

    def test_an_established_riichi_seat_cannot_call(self) -> None:
        player = PlayerState(
            Seat.WEST,
            (*_TANYAO_TENPAI[:10], *_SEVEN_PIN[1:]),
            riichi_status=RiichiStatus.RIICHI,
        )
        view = self._view(players=_players(west=player))

        self.assertEqual(
            derive_legal_actions(view, Seat.WEST),
            (PassLegalAction(ReactionOrigin.DISCARD, _SEVEN_PIN[0].id),),
        )

    def test_offers_a_ron_to_a_seat_that_can_win_on_the_discard(self) -> None:
        player = PlayerState(Seat.WEST, _TANYAO_TENPAI)
        view = self._view(players=_players(west=player))

        self.assertIn(
            RonLegalAction(ReactionOrigin.DISCARD, _SEVEN_PIN[0].id),
            derive_legal_actions(view, Seat.WEST),
        )

    def test_a_furiten_seat_is_offered_no_ron(self) -> None:
        player = PlayerState(
            Seat.WEST,
            _TANYAO_TENPAI,
            discards=(Discard(_SEVEN_PIN[3], is_tsumogiri=False),),
        )
        view = self._view(players=_players(west=player))

        self.assertNotIn(
            RonLegalAction(ReactionOrigin.DISCARD, _SEVEN_PIN[0].id),
            derive_legal_actions(view, Seat.WEST),
        )

    def test_requires_a_pending_discard(self) -> None:
        view = _view(phase=RoundPhase.AWAITING_REACTIONS, current_seat=None)

        with self.assertRaises(ValueError):
            derive_legal_actions(view, Seat.SOUTH)


class DeriveKanReactionActionsTest(unittest.TestCase):
    def test_a_kakan_offers_pass_and_ron_to_the_other_seats(self) -> None:
        pon = Pon(_SEVEN_PIN[0], _SEVEN_PIN[1:3], Seat.NORTH)
        kakan = Kakan(pon, _SEVEN_PIN[3])
        winner = PlayerState(Seat.WEST, _TANYAO_TENPAI)
        view = _view(
            phase=RoundPhase.AWAITING_KAKAN_REACTIONS,
            current_seat=Seat.EAST,
            players=_players(west=winner),
            pending_kakan=PendingKakan(Seat.EAST, kakan),
        )

        self.assertEqual(derive_legal_actions(view, Seat.EAST), ())
        self.assertEqual(
            derive_legal_actions(view, Seat.SOUTH),
            (PassLegalAction(ReactionOrigin.KAKAN, _SEVEN_PIN[3].id),),
        )
        self.assertIn(
            RonLegalAction(ReactionOrigin.KAKAN, _SEVEN_PIN[3].id),
            derive_legal_actions(view, Seat.WEST),
        )

    def test_an_ankan_only_offers_ron_to_a_kokushi_hand(self) -> None:
        quad = tiles("1m", "1m", "1m", "1m")
        ankan = Ankan(quad)
        kokushi = PlayerState(
            Seat.WEST,
            tiles(
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
        )
        standard = PlayerState(Seat.NORTH, _TANYAO_TENPAI)
        rules = replace(_RULES, kokushi_ankan_chankan_enabled=True)
        view = _view(
            phase=RoundPhase.AWAITING_ANKAN_REACTIONS,
            current_seat=Seat.EAST,
            players=_players(west=kokushi, north=standard),
            pending_ankan=PendingAnkan(Seat.EAST, ankan),
            rules=rules,
        )

        self.assertIn(
            RonLegalAction(ReactionOrigin.ANKAN, quad[0].id),
            derive_legal_actions(view, Seat.WEST),
        )
        self.assertEqual(
            derive_legal_actions(view, Seat.NORTH),
            (PassLegalAction(ReactionOrigin.ANKAN, quad[0].id),),
        )

    def test_a_disabled_ankan_chankan_offers_only_pass(self) -> None:
        quad = tiles("1m", "1m", "1m", "1m")
        kokushi = PlayerState(
            Seat.WEST,
            tiles(
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
        )
        view = _view(
            phase=RoundPhase.AWAITING_ANKAN_REACTIONS,
            current_seat=Seat.EAST,
            players=_players(west=kokushi),
            pending_ankan=PendingAnkan(Seat.EAST, Ankan(quad)),
        )

        self.assertEqual(
            derive_legal_actions(view, Seat.WEST),
            (PassLegalAction(ReactionOrigin.ANKAN, quad[0].id),),
        )

    def test_requires_the_pending_kan(self) -> None:
        for phase in (
            RoundPhase.AWAITING_KAKAN_REACTIONS,
            RoundPhase.AWAITING_ANKAN_REACTIONS,
        ):
            with self.subTest(phase=phase):
                view = _view(phase=phase, current_seat=Seat.EAST)
                with self.assertRaises(ValueError):
                    derive_legal_actions(view, Seat.SOUTH)


class DeriveLegalActionsArgumentTest(unittest.TestCase):
    def test_rejects_invalid_arguments(self) -> None:
        with self.assertRaises(TypeError):
            derive_legal_actions("view", Seat.EAST)
        with self.assertRaises(TypeError):
            derive_legal_actions(_view(), "east")


if __name__ == "__main__":
    unittest.main()
