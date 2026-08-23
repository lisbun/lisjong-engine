"""意思決定を要求された1席から見えるimmutableな局面snapshot。"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from lisjong_engine.public_state import (
    PublicTile,
    SeatDiscards,
    SeatMelds,
    SeatRiichiState,
    SeatScore,
)
from lisjong_engine.seat import Seat
from lisjong_engine.wind import Wind

_SEAT_ORDER = tuple(Seat)


class ObservationDecisionKind(Enum):
    """decisionの種類。consumerが候補集合から推測しなくて済むようにする。

    `RIICHI_DISCARD`は「立直は既に選択済みで、今は宣言牌を選ぶ」という
    follow-up decisionを表し、通常turnの`TURN`と明確に区別する。
    """

    TURN = "turn"
    RIICHI_DISCARD = "riichi_discard"
    DISCARD_REACTION = "discard_reaction"
    KAKAN_REACTION = "kakan_reaction"
    ANKAN_REACTION = "ankan_reaction"


@dataclass(frozen=True, kw_only=True)
class SeatObservation:
    viewer_seat: Seat
    decision_kind: ObservationDecisionKind
    hand_number: int
    honba: int
    riichi_sticks: int
    hand_tiles: tuple[PublicTile, ...]
    drawn_tile: PublicTile | None
    discards: tuple[SeatDiscards, ...]
    melds: tuple[SeatMelds, ...]
    dora_indicators: tuple[PublicTile, ...]
    remaining_live_wall_count: int
    scores: tuple[SeatScore, ...]
    dealer_seat: Seat
    prevailing_wind: Wind
    riichi_states: tuple[SeatRiichiState, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.viewer_seat, Seat):
            raise TypeError("viewer_seat must be a Seat")
        if not isinstance(self.decision_kind, ObservationDecisionKind):
            raise TypeError("decision_kind must be an ObservationDecisionKind")
        if type(self.hand_number) is not int:
            raise TypeError("hand_number must be an int")
        if not 1 <= self.hand_number <= 4:
            raise ValueError("hand_number must be between 1 and 4")
        for field_name in (
            "honba",
            "riichi_sticks",
            "remaining_live_wall_count",
        ):
            value = getattr(self, field_name)
            if type(value) is not int:
                raise TypeError(f"{field_name} must be an int")
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        if not isinstance(self.dealer_seat, Seat):
            raise TypeError("dealer_seat must be a Seat")
        if not isinstance(self.prevailing_wind, Wind):
            raise TypeError("prevailing_wind must be a Wind")

        hand_tiles = _typed_tuple(
            self.hand_tiles,
            PublicTile,
            field_name="hand_tiles",
        )
        if self.drawn_tile is not None:
            if not isinstance(self.drawn_tile, PublicTile):
                raise TypeError("drawn_tile must be a PublicTile or None")
            if self.drawn_tile not in hand_tiles:
                raise ValueError(
                    "drawn_tile must be semantically present in hand_tiles"
                )
        if (
            self.decision_kind
            in {
                ObservationDecisionKind.DISCARD_REACTION,
                ObservationDecisionKind.KAKAN_REACTION,
                ObservationDecisionKind.ANKAN_REACTION,
            }
            and self.drawn_tile is not None
        ):
            raise ValueError("reaction observations must not expose a drawn tile")
        dora_indicators = _typed_tuple(
            self.dora_indicators,
            PublicTile,
            field_name="dora_indicators",
        )
        discards = _seat_ordered_tuple(
            self.discards,
            SeatDiscards,
            field_name="discards",
        )
        melds = _seat_ordered_tuple(
            self.melds,
            SeatMelds,
            field_name="melds",
        )
        scores = _seat_ordered_tuple(
            self.scores,
            SeatScore,
            field_name="scores",
        )
        riichi_states = _seat_ordered_tuple(
            self.riichi_states,
            SeatRiichiState,
            field_name="riichi_states",
        )

        discard_orders = tuple(
            discard.order
            for seat_discards in discards
            for discard in seat_discards.discards
        )
        if tuple(sorted(discard_orders)) != tuple(range(len(discard_orders))):
            raise ValueError(
                "discard orders must be unique and contiguous from zero within a round"
            )

        object.__setattr__(self, "hand_tiles", hand_tiles)
        object.__setattr__(self, "dora_indicators", dora_indicators)
        object.__setattr__(self, "discards", discards)
        object.__setattr__(self, "melds", melds)
        object.__setattr__(self, "scores", scores)
        object.__setattr__(self, "riichi_states", riichi_states)


def _typed_tuple(values: Iterable, expected_type: type, *, field_name: str) -> tuple:
    try:
        normalized = tuple(values)
    except TypeError:
        raise TypeError(f"{field_name} must be an iterable") from None
    if any(not isinstance(value, expected_type) for value in normalized):
        raise TypeError(
            f"{field_name} must contain only {expected_type.__name__} values"
        )
    return normalized


def _seat_ordered_tuple(values: Iterable, expected_type: type, *, field_name: str):
    normalized = _typed_tuple(values, expected_type, field_name=field_name)
    if len(normalized) != len(_SEAT_ORDER):
        raise ValueError(f"{field_name} must contain exactly all four seats")
    if tuple(value.seat for value in normalized) != _SEAT_ORDER:
        raise ValueError(f"{field_name} must be ordered as tuple(Seat)")
    return normalized
