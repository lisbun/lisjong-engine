"""Matchの完全状態を意思決定席の公開Observationへpureに射影する。"""

from lisjong_engine.discard import Discard
from lisjong_engine.match_state import MatchPhase, MatchState
from lisjong_engine.meld import Ankan, Chi, Daiminkan, Kakan, Meld, Pon
from lisjong_engine.observation import ObservationDecisionKind, SeatObservation
from lisjong_engine.public_state import (
    PublicDiscard,
    PublicMeld,
    PublicMeldType,
    PublicTile,
    SeatDiscards,
    SeatMelds,
    SeatRiichiState,
    SeatScore,
)
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.round_state import RoundState
from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile

_DECISION_KINDS = {
    RoundPhase.AWAITING_DISCARD: ObservationDecisionKind.TURN,
    RoundPhase.AWAITING_REACTIONS: ObservationDecisionKind.DISCARD_REACTION,
    RoundPhase.AWAITING_KAKAN_REACTIONS: ObservationDecisionKind.KAKAN_REACTION,
    RoundPhase.AWAITING_ANKAN_REACTIONS: ObservationDecisionKind.ANKAN_REACTION,
}


def build_seat_observation(
    match_state: MatchState,
    viewer_seat: Seat,
) -> SeatObservation:
    """現在decisionを求められている席の公開snapshotを返す。"""
    if not isinstance(match_state, MatchState):
        raise TypeError("match_state must be a MatchState")
    if not isinstance(viewer_seat, Seat):
        raise TypeError("viewer_seat must be a Seat")
    if match_state.phase is not MatchPhase.ROUND_IN_PROGRESS:
        raise RuntimeError("an observation requires a round in progress")

    round_state = match_state.active_round
    if round_state is None:
        raise RuntimeError("an observation requires an active round")
    decision_kind = _decision_kind_from_phase(round_state.phase)
    _validate_deciding_seat(round_state, viewer_seat)

    position = match_state.position
    return SeatObservation(
        viewer_seat=viewer_seat,
        decision_kind=decision_kind,
        hand_number=position.hand_number,
        honba=position.honba,
        riichi_sticks=_visible_riichi_sticks(match_state, round_state),
        hand_tiles=_sorted_public_tiles(round_state.hand_tiles(viewer_seat)),
        discards=tuple(_seat_discards(round_state, seat) for seat in Seat),
        melds=tuple(_seat_melds(round_state, seat) for seat in Seat),
        dora_indicators=tuple(
            _public_tile(tile) for tile in round_state.revealed_dora_indicators
        ),
        remaining_live_wall_count=round_state.remaining_count,
        scores=tuple(_seat_score(match_state, round_state, seat) for seat in Seat),
        dealer_seat=position.dealer_seat,
        prevailing_wind=position.prevailing_wind,
        riichi_states=tuple(_seat_riichi_state(round_state, seat) for seat in Seat),
    )


def _decision_kind_from_phase(phase: RoundPhase) -> ObservationDecisionKind:
    if not isinstance(phase, RoundPhase):
        raise TypeError("phase must be a RoundPhase")
    try:
        return _DECISION_KINDS[phase]
    except KeyError:
        raise RuntimeError("an observation requires a decision phase") from None


def _validate_deciding_seat(round_state: RoundState, viewer_seat: Seat) -> None:
    if round_state.phase is RoundPhase.AWAITING_DISCARD:
        if viewer_seat is not round_state.current_seat:
            raise RuntimeError("viewer is not the seat required to act")
        return
    if viewer_seat not in round_state.reacting_seats:
        raise RuntimeError("viewer is not a seat in the reaction window")


def _public_tile(tile: Tile) -> PublicTile:
    if not isinstance(tile, Tile):
        raise TypeError("tile must be a Tile")
    return PublicTile(tile.tile_type, tile.is_red)


def _public_tile_sort_key(tile: PublicTile) -> tuple[int, bool]:
    return (tile.tile_type.id, tile.is_red)


def _sorted_public_tiles(tiles: tuple[Tile, ...]) -> tuple[PublicTile, ...]:
    return tuple(
        sorted((_public_tile(tile) for tile in tiles), key=_public_tile_sort_key)
    )


def _public_meld(meld: Meld) -> PublicMeld:
    if isinstance(meld, Pon):
        meld_type = PublicMeldType.PON
        from_seat = meld.source_seat
    elif isinstance(meld, Chi):
        meld_type = PublicMeldType.CHI
        from_seat = meld.source_seat
    elif isinstance(meld, Daiminkan):
        meld_type = PublicMeldType.DAIMINKAN
        from_seat = meld.source_seat
    elif isinstance(meld, Kakan):
        meld_type = PublicMeldType.KAKAN
        from_seat = meld.source_seat
    elif isinstance(meld, Ankan):
        meld_type = PublicMeldType.ANKAN
        from_seat = None
    else:
        raise TypeError("meld must be Pon, Chi, Daiminkan, Kakan, or Ankan")
    return PublicMeld(
        meld_type=meld_type,
        tiles=_sorted_public_tiles(meld.tiles),
        from_seat=from_seat,
    )


def _established_riichi_declaration_tile_ids(
    round_state: RoundState,
    seat: Seat,
) -> frozenset[int]:
    return frozenset(
        finalization.declaration.discard.tile.id
        for finalization in round_state.riichi_finalizations
        if finalization.is_established and finalization.seat is seat
    )


def _public_discard(
    discard: Discard,
    *,
    is_riichi_declaration: bool,
) -> PublicDiscard:
    if not isinstance(discard, Discard):
        raise TypeError("discard must be a Discard")
    if type(is_riichi_declaration) is not bool:
        raise TypeError("is_riichi_declaration must be a bool")
    return PublicDiscard(
        tile=_public_tile(discard.tile),
        is_tsumogiri=discard.is_tsumogiri,
        is_riichi_declaration=is_riichi_declaration,
        called_by=discard.called_by,
    )


def _seat_discards(round_state: RoundState, seat: Seat) -> SeatDiscards:
    declaration_tile_ids = _established_riichi_declaration_tile_ids(
        round_state,
        seat,
    )
    return SeatDiscards(
        seat,
        tuple(
            _public_discard(
                discard,
                is_riichi_declaration=discard.tile.id in declaration_tile_ids,
            )
            for discard in round_state.discards(seat)
        ),
    )


def _seat_melds(round_state: RoundState, seat: Seat) -> SeatMelds:
    return SeatMelds(
        seat,
        tuple(_public_meld(meld) for meld in round_state.melds(seat)),
    )


def _seat_score(
    match_state: MatchState,
    round_state: RoundState,
    seat: Seat,
) -> SeatScore:
    return SeatScore(
        seat,
        match_state.scores[seat] + round_state.riichi_payment_deltas[seat],
    )


def _seat_riichi_state(
    round_state: RoundState,
    seat: Seat,
) -> SeatRiichiState:
    return SeatRiichiState(seat, round_state.is_riichi_established(seat))


def _visible_riichi_sticks(
    match_state: MatchState,
    round_state: RoundState,
) -> int:
    return match_state.position.riichi_sticks + len(round_state.riichi_contributions)
