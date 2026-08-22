"""局内で成立したobjective factを、player-safeなordered progressへ射影するmodule。

`RoundEvent` / `RoundEventSnapshot`（`round_event.py`）はengine内部のaudit /
test / `RoundResult`構築用contractであり、player-facing public contractでは
ない。本moduleはそのinternal eventから、Human Play等の外部consumerが
snapshot差分推測なしに「前回decisionから何が起きたか」を順序付きで受け取れる、
immutableかつwhitelist方式のpublic factだけを構築する。

生成するfactの種類は、次のinternal eventだけをsourceとする。

```text
TileDiscardedEvent           -> DiscardProgress
MeldCalledEvent               -> MeldCalledProgress（チー・ポン・大明槓成立）
KanDeclaredEvent               -> KanDeclaredProgress（加槓・暗槓宣言）
KanConfirmedEvent（大明槓以外） -> KanConfirmedProgress（加槓・暗槓成立）
RiichiDeclaredEvent            -> RiichiDeclaredProgress
RiichiFinalizedEvent           -> RiichiEstablishedProgress / RiichiFailedProgress
DoraIndicatorRevealedEvent     -> DoraIndicatorRevealedProgress
```

`KanConfirmedEvent`のうち大明槓由来のものは、同じtransactionで既に
`MeldCalledEvent`から`MeldCalledProgress`を生成しているため、二重生成しない
（成立factは`MeldCalledEvent`を単一のsourceとする）。

`ReactionsResolvedEvent`は、各seatのron capable / selected / passed、鳴きの
candidate等のhidden decision factを保持するため、一切progress factを生成
しない。`RoundStartedEvent` / `TilesDealtEvent`（他家の配牌を含む）/
`TileDrawnEvent`（他家のツモを含む）/ `MissedRonRecordedEvent`（見逃し
フリテンのinternal provenance）/ `RoundEndedEvent`（terminal resultは
`round_completion.py`の別contractが扱う）も同様に対象外である。この
whitelistに含まれないevent型は、将来追加されても黙って無視される。
"""

from collections.abc import Iterable
from dataclasses import dataclass

from lisjong_engine.meld import Daiminkan
from lisjong_engine.public_state import PublicMeld, PublicTile, public_meld, public_tile
from lisjong_engine.round_event import (
    DoraIndicatorRevealedEvent,
    KanConfirmedEvent,
    KanDeclaredEvent,
    MeldCalledEvent,
    RiichiDeclaredEvent,
    RiichiFinalizedEvent,
    RoundEvent,
    TileDiscardedEvent,
)
from lisjong_engine.seat import Seat


@dataclass(frozen=True)
class RoundProgressFact:
    """局内のplayer-facing progressを表す値の基底型。"""


@dataclass(frozen=True)
class DiscardProgress(RoundProgressFact):
    seat: Seat
    tile: PublicTile
    is_tsumogiri: bool

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.tile, PublicTile):
            raise TypeError("tile must be a PublicTile")
        if type(self.is_tsumogiri) is not bool:
            raise TypeError("is_tsumogiri must be a bool")


@dataclass(frozen=True)
class MeldCalledProgress(RoundProgressFact):
    """チー・ポン・大明槓が成立したことを表す。"""

    seat: Seat
    meld: PublicMeld

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.meld, PublicMeld):
            raise TypeError("meld must be a PublicMeld")


@dataclass(frozen=True)
class KanDeclaredProgress(RoundProgressFact):
    """加槓・暗槓が宣言され、槍槓の反応待ちに入ったことを表す。"""

    seat: Seat
    meld: PublicMeld

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.meld, PublicMeld):
            raise TypeError("meld must be a PublicMeld")


@dataclass(frozen=True)
class KanConfirmedProgress(RoundProgressFact):
    """加槓・暗槓が副露として確定したことを表す。"""

    seat: Seat
    meld: PublicMeld

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.meld, PublicMeld):
            raise TypeError("meld must be a PublicMeld")


@dataclass(frozen=True)
class RiichiDeclaredProgress(RoundProgressFact):
    seat: Seat
    tile: PublicTile

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.tile, PublicTile):
            raise TypeError("tile must be a PublicTile")


@dataclass(frozen=True)
class RiichiEstablishedProgress(RoundProgressFact):
    seat: Seat

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")


@dataclass(frozen=True)
class RiichiFailedProgress(RoundProgressFact):
    """宣言牌がロンされ、立直が不成立になったことを表す。"""

    seat: Seat

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")


@dataclass(frozen=True)
class DoraIndicatorRevealedProgress(RoundProgressFact):
    seat: Seat
    indicator: PublicTile

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.indicator, PublicTile):
            raise TypeError("indicator must be a PublicTile")


def project_round_progress(
    events: Iterable[RoundEvent],
) -> tuple[RoundProgressFact, ...]:
    """internal eventの列から、player-facingなordered progress factを構築する。

    `events`のiteration順をそのままfactの順序として保持する。whitelistに
    含まれないevent型は黙って無視し、内部eventの列挙が増えても未知の型を
    誤って公開しない。
    """
    facts: list[RoundProgressFact] = []
    for event in events:
        fact = _project_event(event)
        if fact is not None:
            facts.append(fact)
    return tuple(facts)


def _project_event(event: RoundEvent) -> RoundProgressFact | None:
    if isinstance(event, TileDiscardedEvent):
        return DiscardProgress(
            event.seat,
            public_tile(event.tile),
            event.is_tsumogiri,
        )
    if isinstance(event, MeldCalledEvent):
        return MeldCalledProgress(event.seat, public_meld(event.meld))
    if isinstance(event, KanDeclaredEvent):
        return KanDeclaredProgress(event.seat, public_meld(event.kan))
    if isinstance(event, KanConfirmedEvent):
        if isinstance(event.kan, Daiminkan):
            # 大明槓の成立は同じtransactionのMeldCalledEventが既に表しており、
            # ここで重複してprogress factを生成しない。
            return None
        return KanConfirmedProgress(event.seat, public_meld(event.kan))
    if isinstance(event, RiichiDeclaredEvent):
        declaration = event.declaration
        return RiichiDeclaredProgress(declaration.seat, public_tile(declaration.tile))
    if isinstance(event, RiichiFinalizedEvent):
        finalization = event.finalization
        if finalization.is_established:
            return RiichiEstablishedProgress(finalization.seat)
        return RiichiFailedProgress(finalization.seat)
    if isinstance(event, DoraIndicatorRevealedEvent):
        return DoraIndicatorRevealedProgress(event.seat, public_tile(event.indicator))
    return None
