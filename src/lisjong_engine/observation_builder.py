"""Matchの完全状態を意思決定席の公開Observationへpureに射影する。"""

from lisjong_engine.discard import Discard
from lisjong_engine.match_state import MatchPhase, MatchState
from lisjong_engine.observation import ObservationDecisionKind, SeatObservation
from lisjong_engine.public_state import (
    PublicDiscard,
    PublicRiichiStatus,
    PublicTile,
    SeatDiscards,
    SeatMelds,
    SeatRiichiState,
    SeatScore,
    public_meld,
    public_tile,
)
from lisjong_engine.round_event import RiichiDeclaredEvent, TileDiscardedEvent
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.round_state import RoundState
from lisjong_engine.seat import Seat

# current seatだけがdecisionを持つphase。立直選択後の宣言牌decisionも、
# 通常turnと同じくcurrent seatだけのdecisionである。
_CURRENT_SEAT_DECISION_PHASES = frozenset(
    {
        RoundPhase.AWAITING_DISCARD,
        RoundPhase.AWAITING_RIICHI_DISCARD,
    }
)

_DECISION_KINDS = {
    RoundPhase.AWAITING_DISCARD: ObservationDecisionKind.TURN,
    RoundPhase.AWAITING_RIICHI_DISCARD: ObservationDecisionKind.RIICHI_DISCARD,
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
    discard_orders = _discard_orders(round_state)
    riichi_declaration_tile_ids = _riichi_declaration_tile_ids(
        round_state,
        discard_orders,
    )
    return SeatObservation(
        viewer_seat=viewer_seat,
        decision_kind=decision_kind,
        hand_number=position.hand_number,
        honba=position.honba,
        riichi_sticks=_visible_riichi_sticks(match_state, round_state),
        hand_tiles=_sorted_public_tiles(round_state.hand_tiles(viewer_seat)),
        drawn_tile=_viewer_drawn_tile(round_state, viewer_seat),
        discards=tuple(
            _seat_discards(
                round_state,
                seat,
                discard_orders=discard_orders,
                riichi_declaration_tile_ids=riichi_declaration_tile_ids,
            )
            for seat in Seat
        ),
        melds=tuple(_seat_melds(round_state, seat) for seat in Seat),
        dora_indicators=tuple(
            public_tile(tile) for tile in round_state.revealed_dora_indicators
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
    if round_state.phase in _CURRENT_SEAT_DECISION_PHASES:
        if viewer_seat is not round_state.current_seat:
            raise RuntimeError("viewer is not the seat required to act")
        return
    if viewer_seat not in round_state.reacting_seats:
        raise RuntimeError("viewer is not a seat in the reaction window")


def _public_tile_sort_key(tile: PublicTile) -> tuple[int, bool]:
    return (tile.tile_type.id, tile.is_red)


def _sorted_public_tiles(tiles: tuple) -> tuple[PublicTile, ...]:
    return tuple(
        sorted((public_tile(tile) for tile in tiles), key=_public_tile_sort_key)
    )


def _viewer_drawn_tile(
    round_state: RoundState,
    viewer_seat: Seat,
) -> PublicTile | None:
    if round_state.phase not in _CURRENT_SEAT_DECISION_PHASES:
        return None
    if round_state.current_seat is not viewer_seat:
        raise RuntimeError("a turn decision viewer must be the current seat")
    drawn_tile = round_state.drawn_tile
    return None if drawn_tile is None else public_tile(drawn_tile)


def _discard_orders(round_state: RoundState) -> dict[int, int]:
    """Internal event historyからround-global discard orderを構築する。"""
    discard_events = tuple(
        event for event in round_state.events if isinstance(event, TileDiscardedEvent)
    )
    event_facts = {
        event.tile.id: (order, event.seat) for order, event in enumerate(discard_events)
    }
    if len(event_facts) != len(discard_events):
        raise RuntimeError("discard event history contains duplicate physical tiles")

    river_facts = tuple(
        (seat, discard) for seat in Seat for discard in round_state.discards(seat)
    )
    river_tile_ids = tuple(discard.tile.id for _, discard in river_facts)
    if len(set(river_tile_ids)) != len(river_tile_ids):
        raise RuntimeError("rivers contain duplicate physical discard tiles")
    if set(event_facts) != set(river_tile_ids):
        raise RuntimeError(
            "discard event history and rivers must describe the same tiles"
        )
    if any(
        event_facts[discard.tile.id][1] is not seat for seat, discard in river_facts
    ):
        raise RuntimeError("discard event history and river seats do not match")
    return {tile_id: order for tile_id, (order, _) in event_facts.items()}


def _riichi_declaration_tile_ids(
    round_state: RoundState,
    discard_orders: dict[int, int],
) -> frozenset[int]:
    tile_ids = tuple(
        event.declaration.discard.tile.id
        for event in round_state.events
        if isinstance(event, RiichiDeclaredEvent)
    )
    if len(set(tile_ids)) != len(tile_ids):
        raise RuntimeError(
            "riichi declaration history contains duplicate discard tiles"
        )
    if not set(tile_ids).issubset(discard_orders):
        raise RuntimeError("riichi declaration history must reference a discard")
    return frozenset(tile_ids)


def _public_discard(
    discard: Discard,
    *,
    order: int,
    is_riichi_declaration: bool,
) -> PublicDiscard:
    if not isinstance(discard, Discard):
        raise TypeError("discard must be a Discard")
    if type(is_riichi_declaration) is not bool:
        raise TypeError("is_riichi_declaration must be a bool")
    return PublicDiscard(
        tile=public_tile(discard.tile),
        is_tsumogiri=discard.is_tsumogiri,
        order=order,
        is_riichi_declaration=is_riichi_declaration,
        called_by=discard.called_by,
    )


def _seat_discards(
    round_state: RoundState,
    seat: Seat,
    *,
    discard_orders: dict[int, int],
    riichi_declaration_tile_ids: frozenset[int],
) -> SeatDiscards:
    return SeatDiscards(
        seat,
        tuple(
            _public_discard(
                discard,
                order=discard_orders[discard.tile.id],
                is_riichi_declaration=(discard.tile.id in riichi_declaration_tile_ids),
            )
            for discard in round_state.discards(seat)
        ),
    )


def _seat_melds(round_state: RoundState, seat: Seat) -> SeatMelds:
    return SeatMelds(
        seat,
        tuple(public_meld(meld) for meld in round_state.melds(seat)),
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
    pending_selection = (
        round_state.phase is RoundPhase.AWAITING_RIICHI_DISCARD
        and round_state.current_seat is seat
    )
    pending_declaration = round_state.pending_riichi_declaration
    is_pending = pending_selection or (
        pending_declaration is not None and pending_declaration.seat is seat
    )
    is_established = round_state.is_riichi_established(seat)
    if is_pending and is_established:
        raise RuntimeError("riichi cannot be pending and established at the same time")
    if is_established:
        status = PublicRiichiStatus.ESTABLISHED
    elif is_pending:
        status = PublicRiichiStatus.PENDING
    else:
        status = PublicRiichiStatus.NONE
    return SeatRiichiState(seat, status)


def _visible_riichi_sticks(
    match_state: MatchState,
    round_state: RoundState,
) -> int:
    return match_state.position.riichi_sticks + len(round_state.riichi_contributions)
