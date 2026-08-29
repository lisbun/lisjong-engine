"""終局した1局について、viewerごとのplayer-safe evidenceをまとめるcontract。

`round_evidence.py` / `build_round_evidence()`が唯一のplayer-safe history
authorityであり、本moduleは新しいevent modelを作らない。engineが既に
所有するprojectionを、局が`FINISHED`へ確定してから`MatchState`が
active `RoundState`を手放すまでの間に、欠落なく取り出すためだけの薄い
value contractである。

```text
finished RoundState + 現在のRoundPosition
    -> build_round_evidence(round_state, viewer_seat) x 4 viewer
    -> RoundEvidenceCompletion（player-safe immutable value）
```

## bundleはsingle-player safeではない

1つの`SeatRoundEvidence`は、その`viewer_seat`に対してplayer-safeである。
`RoundEvidenceCompletion`は4席分のseat-relative projectionをviewer identity
付きで束ねるだけであり、**bundle全体を単一playerへ渡してよいglobal-public
objectとして扱ってはならない**。4席分を合わせれば他家のツモ牌という
viewer-privateな観測が集合として含まれるため、consumerは常に対象viewerの
`SeatRoundEvidence`だけを取り出して使う。

round identityには`MatchState.position`から得られるplayer-safeな位置情報
だけを持たせ、`round_ordinal`やseed等のrandom provenanceは公開しない。
"""

from dataclasses import dataclass

from lisjong_engine.match_state import MatchState
from lisjong_engine.round_evidence import RoundEvidence
from lisjong_engine.round_evidence_builder import build_round_evidence
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.seat import Seat
from lisjong_engine.wind import Wind

_SEAT_ORDER = tuple(Seat)


@dataclass(frozen=True)
class SeatRoundEvidence:
    """1 viewer分の、seat-relativeなordered player-safe evidence。

    `evidence`は`build_round_evidence(round_state, viewer_seat)`の結果そのもの
    であり、`viewer_seat`以外のviewerへ渡してよい値ではない。
    """

    viewer_seat: Seat
    evidence: tuple[RoundEvidence, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.viewer_seat, Seat):
            raise TypeError("viewer_seat must be a Seat")
        try:
            evidence = tuple(self.evidence)
        except TypeError:
            raise TypeError("evidence must be an iterable of RoundEvidence") from None
        if any(not isinstance(item, RoundEvidence) for item in evidence):
            raise TypeError("evidence must contain only RoundEvidence values")
        object.__setattr__(self, "evidence", evidence)


@dataclass(frozen=True, kw_only=True)
class RoundEvidenceCompletion:
    """終局した1局の、viewerごとのplayer-safe evidenceをまとめたimmutable value。

    `projections`は`tuple(Seat)`順の4件であり、各要素は自分の`viewer_seat`に
    対してだけplayer-safeである。bundle全体は単一playerへ安全な
    global-public objectではない（module docstring参照）。

    位置情報は`MatchState.position`由来のplayer-safeなround identityであり、
    精算後の点数移動は`round_completion.py`の別contractが扱う。
    """

    prevailing_wind: Wind
    hand_number: int
    dealer_seat: Seat
    honba: int
    projections: tuple[SeatRoundEvidence, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.prevailing_wind, Wind):
            raise TypeError("prevailing_wind must be a Wind")
        if type(self.hand_number) is not int:
            raise TypeError("hand_number must be an int")
        if not isinstance(self.dealer_seat, Seat):
            raise TypeError("dealer_seat must be a Seat")
        if type(self.honba) is not int:
            raise TypeError("honba must be an int")

        try:
            projections = tuple(self.projections)
        except TypeError:
            raise TypeError("projections must be an iterable") from None
        if any(
            not isinstance(projection, SeatRoundEvidence) for projection in projections
        ):
            raise TypeError("projections must contain only SeatRoundEvidence values")
        if tuple(projection.viewer_seat for projection in projections) != _SEAT_ORDER:
            raise ValueError(
                "projections must contain exactly all four viewer seats in order"
            )

        object.__setattr__(self, "projections", projections)


def build_round_evidence_completion(match_state: MatchState) -> RoundEvidenceCompletion:
    """終局済みのactive roundから、viewerごとのplayer-safe evidenceを構築する。

    `MatchState.settle_active_round()`より前、すなわちactive `RoundState`が
    まだ失われていない時点でだけ成立する。局が`FINISHED`でない場合は
    fail closedで拒否し、途中経過をcompletion valueとして公開しない。
    """
    if not isinstance(match_state, MatchState):
        raise TypeError("match_state must be a MatchState")
    round_state = match_state.active_round
    if round_state is None:
        raise ValueError("a round evidence completion requires an active round")
    if round_state.phase is not RoundPhase.FINISHED:
        raise ValueError("a round evidence completion requires a finished round")

    position = match_state.position
    return RoundEvidenceCompletion(
        prevailing_wind=position.prevailing_wind,
        hand_number=position.hand_number,
        dealer_seat=position.dealer_seat,
        honba=position.honba,
        projections=tuple(
            SeatRoundEvidence(seat, build_round_evidence(round_state, seat))
            for seat in _SEAT_ORDER
        ),
    )
