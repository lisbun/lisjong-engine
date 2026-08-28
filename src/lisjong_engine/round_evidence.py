"""局のinternal完全stateから、viewerごとのordered player-safe evidenceを射影するmodule。

`RoundEvent` / `RoundEventSnapshot`（`round_event.py`）はengine内部の
audit / test / `RoundResult`構築用のomniscient recordであり、consumer-facing
contractではない。全席の配牌、他家のツモ牌、`ReactionResolution`のron
capable / selected / passed、見逃しフリテン遷移までを保持するため、その
まま公開できない。

本moduleは、そのinternal historyから **viewerが合法的に観測できた事実
だけ** をwhitelist方式で射影する。

```text
complete engine state / internal events
    -> engine-owned pure player-safe projection
    -> ordered player-safe round evidence
```

player-safeはpublic-onlyと同義ではない。

```text
player-safe evidence
├─ globally public evidence / context
└─ viewer-private legitimate observation（viewer自身のツモ牌）
```

## Response epochをruntime reaction activationから導出しない

current engineは打牌後に`has_possible_reaction()`を呼び、他家のhidden hand
を見てから`AWAITING_REACTIONS`へ入るかどうかを決める。暗槓も
`kokushi_ankan_chankan_enabled`と実際の国士無双候補の有無で、反応window
を開くか即座に成立させるかが変わる。したがって **反応windowが開いたと
いうruntime factそのものがhidden capabilityを漏らし得る**。

本moduleのresponse epochは、この分岐を一切入力にしない。

```text
public triggering action + RuleSet + seat topology
    -> structural response epoch / responder topology
```

- 打牌: publicに打牌が起きた時点で必ずstructural epochを開く
- 加槓: public kakan declarationで必ずstructural chankan epochを開く
- 暗槓: `RuleSet.kokushi_ankan_chankan_enabled`だけで開閉を決め、
  実際の槍槓候補の有無では変えない

responder topologyはいずれもsource seat以外の3席であり、
`reaction_seat_order()`というseat topologyだけから決まる。

epochのoutcomeは、実際にpublicへ現れた進行（鳴き成立、和了、次の進行）
からのみ決める。epochの解決がまだpublicに現れていない間は
`ResponseEpochClosedEvidence`を出さず、その解決を前提とする槓ドラ公開・
立直確定もfail closedで保留する。これにより、hidden candidateの有無で
runtimeのreaction windowが開いた場合と開かなかった場合とで、同じ公開
進行に対して同じevidenceになる。

## 公開しないもの

他家concealed hand、他家のツモ牌、live / dead wallのtile truth、
`ron_capable_seats` / `ron_passed_seats`、pon / chi capable等のactual per-player
legal opportunity、hidden-dependent pass、フリテン、ron legality、
`MissedRonRecordedEvent`、`ReactionResolution`自体、physical tile identity
はいずれもevidenceへ含めない。internal eventがそれらを保持していても、
projectionで明示的に落とす。

HandBelief / ML / dataset feature semanticsは本moduleの責務ではない。ここ
で決めるのは「そのviewerから何が合法的に観測可能だったか」だけである。
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

from lisjong_engine.meld import Ankan, Chi, Daiminkan, Kakan, Pon
from lisjong_engine.public_state import PublicMeld, PublicTile, public_meld, public_tile
from lisjong_engine.reaction import reaction_seat_order
from lisjong_engine.round_event import (
    DoraIndicatorRevealedEvent,
    DrawSource,
    KanConfirmedEvent,
    KanDeclaredEvent,
    MeldCalledEvent,
    RiichiDeclaredEvent,
    RiichiFinalizedEvent,
    RoundEndedEvent,
    RoundEvent,
    RoundStartedEvent,
    TileDiscardedEvent,
    TileDrawnEvent,
)
from lisjong_engine.round_result import (
    AbortiveDrawReason,
    AbortiveDrawResult,
    ExhaustiveDrawResult,
    RoundResult,
    WinResult,
)
from lisjong_engine.rules import RuleSet
from lisjong_engine.seat import Seat
from lisjong_engine.win_context import WinMethod, WinOrigin
from lisjong_engine.wind import Wind


class ResponseTrigger(Enum):
    """structural response epochを生じさせるpublic action種別。

    反応の合法性contractである`ReactionOrigin`とは別の値として持つ。
    player-safe evidenceのepochはlegal action導出に依存しないため、
    legality側のenumをそのまま公開contractへ持ち込まない。
    """

    DISCARD = "discard"
    KAKAN = "kakan"
    ANKAN = "ankan"


class ResponseOutcome(Enum):
    """structural response epochが、publicに何で解決したか。

    `NO_PUBLIC_RESPONSE`は「誰も合法な反応を持たなかった」ではなく
    「publicな反応actionが現れなかった」だけを意味する。
    """

    NO_PUBLIC_RESPONSE = "no_public_response"
    CALL = "call"
    RON = "ron"


class RoundEndKind(Enum):
    WIN = "win"
    EXHAUSTIVE_DRAW = "exhaustive_draw"
    ABORTIVE_DRAW = "abortive_draw"


_WIN_ORIGIN_TRIGGERS = {
    WinOrigin.DISCARD: ResponseTrigger.DISCARD,
    WinOrigin.KAKAN: ResponseTrigger.KAKAN,
    WinOrigin.ANKAN: ResponseTrigger.ANKAN,
}


@dataclass(frozen=True)
class RoundEvidence:
    """orderedなplayer-safe round evidenceを表す値の基底型。"""


@dataclass(frozen=True)
class RoundStartedEvidence(RoundEvidence):
    """局が開始し、親と場風が公開されたことを表す。"""

    dealer_seat: Seat
    prevailing_wind: Wind

    def __post_init__(self) -> None:
        if not isinstance(self.dealer_seat, Seat):
            raise TypeError("dealer_seat must be a Seat")
        if not isinstance(self.prevailing_wind, Wind):
            raise TypeError("prevailing_wind must be a Wind")


@dataclass(frozen=True)
class DrawEvidence(RoundEvidence):
    """ツモが発生したことと、その取得元を表す。

    `tile`はviewer自身のツモのときだけviewer-private legitimate observation
    として保持し、他家のツモでは常に`None`にする。ツモが起きたこと自体と
    live wall / 嶺上の区別はpublicである。
    """

    seat: Seat
    source: DrawSource
    tile: PublicTile | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.source, DrawSource):
            raise TypeError("source must be a DrawSource")
        if self.tile is not None and not isinstance(self.tile, PublicTile):
            raise TypeError("tile must be a PublicTile or None")


@dataclass(frozen=True)
class DiscardEvidence(RoundEvidence):
    """打牌のpublic evidence。

    `order`は局全体で0始まりのchronological identityであり、
    `SeatObservation`の`PublicDiscard.order`と同じ意味を持つ。
    `is_riichi_declaration`は立直の成立可否ではなく、その打牌が実際に
    宣言牌として打たれたhistorical factを表す。
    """

    seat: Seat
    tile: PublicTile
    is_tsumogiri: bool
    order: int
    is_riichi_declaration: bool

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.tile, PublicTile):
            raise TypeError("tile must be a PublicTile")
        if type(self.is_tsumogiri) is not bool:
            raise TypeError("is_tsumogiri must be a bool")
        if type(self.order) is not int:
            raise TypeError("order must be an int")
        if self.order < 0:
            raise ValueError("order must be non-negative")
        if type(self.is_riichi_declaration) is not bool:
            raise TypeError("is_riichi_declaration must be a bool")


@dataclass(frozen=True)
class ResponseEpochOpenedEvidence(RoundEvidence):
    """public triggerに対するstructural response epochが開いたことを表す。

    `responder_seats`はsource seat以外の3席というseat topologyであり、
    「その席が合法な反応を持っていた」ことを意味しない。epochの存在も
    topologyも、hidden handやengineのreaction window activationからは
    導出しない。
    """

    trigger: ResponseTrigger
    source_seat: Seat
    responder_seats: tuple[Seat, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.trigger, ResponseTrigger):
            raise TypeError("trigger must be a ResponseTrigger")
        if not isinstance(self.source_seat, Seat):
            raise TypeError("source_seat must be a Seat")
        try:
            responder_seats = tuple(self.responder_seats)
        except TypeError:
            raise TypeError("responder_seats must be an iterable of Seat") from None
        if any(not isinstance(seat, Seat) for seat in responder_seats):
            raise TypeError("responder_seats must contain only Seat values")
        if responder_seats != reaction_seat_order(self.source_seat):
            raise ValueError(
                "responder_seats must be the seat topology around the source seat"
            )
        object.__setattr__(self, "responder_seats", responder_seats)


@dataclass(frozen=True)
class ResponseEpochClosedEvidence(RoundEvidence):
    """structural response epochが、publicな結果で閉じたことを表す。"""

    trigger: ResponseTrigger
    source_seat: Seat
    outcome: ResponseOutcome

    def __post_init__(self) -> None:
        if not isinstance(self.trigger, ResponseTrigger):
            raise TypeError("trigger must be a ResponseTrigger")
        if not isinstance(self.source_seat, Seat):
            raise TypeError("source_seat must be a Seat")
        if not isinstance(self.outcome, ResponseOutcome):
            raise TypeError("outcome must be a ResponseOutcome")


@dataclass(frozen=True)
class MeldCalledEvidence(RoundEvidence):
    """チー・ポン・大明槓が成立したことを表す。

    `called_discard_order`は鳴かれた打牌の`DiscardEvidence.order`であり、
    打牌と鳴きのcalled-by関係を、過去のevidenceを書き換えずに保持する。
    """

    seat: Seat
    meld: PublicMeld
    called_discard_order: int

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.meld, PublicMeld):
            raise TypeError("meld must be a PublicMeld")
        if type(self.called_discard_order) is not int:
            raise TypeError("called_discard_order must be an int")
        if self.called_discard_order < 0:
            raise ValueError("called_discard_order must be non-negative")


@dataclass(frozen=True)
class KanDeclaredEvidence(RoundEvidence):
    """加槓・暗槓が宣言されたことを表す。成立はまだ確定していない。"""

    seat: Seat
    meld: PublicMeld

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.meld, PublicMeld):
            raise TypeError("meld must be a PublicMeld")


@dataclass(frozen=True)
class KanConfirmedEvidence(RoundEvidence):
    """加槓・暗槓が副露として確定したことを表す。

    大明槓の成立は`MeldCalledEvidence`が単一のsourceであり、ここで重複
    して表さない。
    """

    seat: Seat
    meld: PublicMeld

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.meld, PublicMeld):
            raise TypeError("meld must be a PublicMeld")


@dataclass(frozen=True)
class RiichiDeclaredEvidence(RoundEvidence):
    """立直が宣言され、宣言牌が打たれたことを表す。"""

    seat: Seat
    tile: PublicTile
    declaration_discard_order: int

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.tile, PublicTile):
            raise TypeError("tile must be a PublicTile")
        if type(self.declaration_discard_order) is not int:
            raise TypeError("declaration_discard_order must be an int")
        if self.declaration_discard_order < 0:
            raise ValueError("declaration_discard_order must be non-negative")


@dataclass(frozen=True)
class RiichiEstablishedEvidence(RoundEvidence):
    seat: Seat

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")


@dataclass(frozen=True)
class RiichiFailedEvidence(RoundEvidence):
    """宣言牌がロンされ、立直が不成立になったことを表す。"""

    seat: Seat

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")


@dataclass(frozen=True)
class DoraIndicatorRevealedEvidence(RoundEvidence):
    seat: Seat
    indicator: PublicTile

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if not isinstance(self.indicator, PublicTile):
            raise TypeError("indicator must be a PublicTile")


@dataclass(frozen=True, kw_only=True)
class RoundEndedEvidence(RoundEvidence):
    """局が終了したというpublicな事実と、その理由を表す。

    九種九牌のようにeligibilityがhidden handへ依存するterminalでも、
    実際に宣言されて終局したこと自体はpublicである。eligibilityや
    「可能だったが選ばなかった」は保持しない。

    精算後の点数移動・順位は`round_completion.py`の別contractが扱う。
    """

    kind: RoundEndKind
    win_method: WinMethod | None = None
    winner_seats: tuple[Seat, ...] = ()
    source_seat: Seat | None = None
    abortive_reason: AbortiveDrawReason | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RoundEndKind):
            raise TypeError("kind must be a RoundEndKind")
        if self.win_method is not None and not isinstance(self.win_method, WinMethod):
            raise TypeError("win_method must be a WinMethod or None")
        try:
            winner_seats = tuple(self.winner_seats)
        except TypeError:
            raise TypeError("winner_seats must be an iterable of Seat") from None
        if any(not isinstance(seat, Seat) for seat in winner_seats):
            raise TypeError("winner_seats must contain only Seat values")
        if len(set(winner_seats)) != len(winner_seats):
            raise ValueError("winner_seats must not contain duplicate seats")
        if self.source_seat is not None and not isinstance(self.source_seat, Seat):
            raise TypeError("source_seat must be a Seat or None")
        if self.abortive_reason is not None and not isinstance(
            self.abortive_reason, AbortiveDrawReason
        ):
            raise TypeError("abortive_reason must be an AbortiveDrawReason or None")

        if self.kind is RoundEndKind.WIN:
            if self.win_method is None or not winner_seats:
                raise ValueError("a win requires a win method and winner seats")
            if self.abortive_reason is not None:
                raise ValueError("a win must not carry an abortive reason")
            if (self.win_method is WinMethod.RON) is not (self.source_seat is not None):
                raise ValueError("only a ron win has a source seat")
        else:
            if self.win_method is not None or winner_seats or self.source_seat:
                raise ValueError("a draw must not carry win facts")
            if (self.kind is RoundEndKind.ABORTIVE_DRAW) is not (
                self.abortive_reason is not None
            ):
                raise ValueError("only an abortive draw has an abortive reason")
        object.__setattr__(self, "winner_seats", winner_seats)


def project_round_evidence(
    events: Iterable[RoundEvent],
    *,
    viewer_seat: Seat,
    rules: RuleSet,
) -> tuple[RoundEvidence, ...]:
    """internal event historyを、1 viewer分のordered player-safe evidenceへ射影する。

    `events`のiteration順をそのままevidenceの順序として保持する。
    whitelistに含まれないevent型は黙って無視し、内部eventが増えても未知
    の型を誤って公開しない。
    """
    if not isinstance(viewer_seat, Seat):
        raise TypeError("viewer_seat must be a Seat")
    if not isinstance(rules, RuleSet):
        raise TypeError("rules must be a RuleSet")
    try:
        ordered = tuple(events)
    except TypeError:
        raise TypeError("events must be an iterable of RoundEvent instances") from None
    if any(not isinstance(event, RoundEvent) for event in ordered):
        raise TypeError("events must contain only RoundEvent instances")

    return _Projection(viewer_seat=viewer_seat, rules=rules).run(ordered)


@dataclass
class _OpenEpoch:
    """まだpublicに解決していないstructural response epoch。"""

    trigger: ResponseTrigger
    source_seat: Seat
    deferred: list[RoundEvidence] = field(default_factory=list)


class _Projection:
    """whitelist projectionの逐次state。1回の射影だけに使う。"""

    def __init__(self, *, viewer_seat: Seat, rules: RuleSet) -> None:
        self._viewer_seat = viewer_seat
        self._rules = rules
        self._evidence: list[RoundEvidence] = []
        self._epoch: _OpenEpoch | None = None
        self._discard_orders: dict[int, int] = {}
        self._discard_count = 0
        self._absorbed_declaration: RiichiDeclaredEvent | None = None

    def run(self, events: tuple[RoundEvent, ...]) -> tuple[RoundEvidence, ...]:
        for index, event in enumerate(events):
            follower = events[index + 1] if index + 1 < len(events) else None
            self._consume(event, follower)
        # epochがまだpublicに解決していない場合、その解決を前提とする
        # 槓ドラ公開・立直確定はまだ公開しない。次のprojectionでepochが
        # 閉じた時点で、同じ順序で現れる。
        return tuple(self._evidence)

    def _consume(self, event: RoundEvent, follower: RoundEvent | None) -> None:
        if event is self._absorbed_declaration:
            # 宣言牌の打牌と同じstepとして、既にevidenceへ射影済みである。
            self._absorbed_declaration = None
            return
        if isinstance(event, RiichiDeclaredEvent):
            raise ValueError("a riichi declaration must follow its declaration discard")

        deferred = self._deferred_evidence(event)
        if deferred is not None:
            self._emit_or_defer(deferred)
            return

        if self._epoch is not None:
            outcome = self._closing_outcome(event, self._epoch)
            if outcome is not None:
                self._close_epoch(outcome)
        self._project(event, follower)

    def _deferred_evidence(self, event: RoundEvent) -> RoundEvidence | None:
        """response epochの解決を前提とするfactを射影する。

        槓ドラの解放と立直の成立可否は、打牌・加槓・暗槓への反応が解決
        したこと自体を意味する。epochがまだpublicに閉じていない間に公開
        すると、runtime reaction windowの有無を漏らし得るため保留する。
        """
        if isinstance(event, DoraIndicatorRevealedEvent):
            return DoraIndicatorRevealedEvidence(
                event.seat,
                public_tile(event.indicator),
            )
        if isinstance(event, RiichiFinalizedEvent):
            finalization = event.finalization
            if finalization.is_established:
                return RiichiEstablishedEvidence(finalization.seat)
            return RiichiFailedEvidence(finalization.seat)
        return None

    def _emit_or_defer(self, evidence: RoundEvidence) -> None:
        if self._epoch is None:
            self._evidence.append(evidence)
            return
        self._epoch.deferred.append(evidence)

    def _closing_outcome(
        self,
        event: RoundEvent,
        epoch: _OpenEpoch,
    ) -> ResponseOutcome | None:
        """publicな進行から、開いているepochのoutcomeを決める。

        `ReactionsResolvedEvent`をはじめとするreaction windowのruntime
        factは一切見ない。
        """
        if isinstance(event, MeldCalledEvent):
            return ResponseOutcome.CALL
        if isinstance(event, RoundEndedEvent):
            return self._terminal_outcome(event.result, epoch)
        if isinstance(event, (KanConfirmedEvent, TileDrawnEvent, TileDiscardedEvent)):
            return ResponseOutcome.NO_PUBLIC_RESPONSE
        return None

    @staticmethod
    def _terminal_outcome(
        result: RoundResult,
        epoch: _OpenEpoch,
    ) -> ResponseOutcome:
        if isinstance(result, WinResult) and result.method is WinMethod.RON:
            if (
                result.source_seat is not epoch.source_seat
                or _WIN_ORIGIN_TRIGGERS[result.origin] is not epoch.trigger
            ):
                raise ValueError("a ron result must resolve the open response epoch")
            return ResponseOutcome.RON
        if (
            isinstance(result, AbortiveDrawResult)
            and result.reason is AbortiveDrawReason.TRIPLE_RON
        ):
            # 三家和は、publicに宣言された3つのロンによる解決である。
            return ResponseOutcome.RON
        return ResponseOutcome.NO_PUBLIC_RESPONSE

    def _open_epoch(self, trigger: ResponseTrigger, source_seat: Seat) -> None:
        if self._epoch is not None:
            raise ValueError("a response epoch is already open")
        self._epoch = _OpenEpoch(trigger, source_seat)
        self._evidence.append(
            ResponseEpochOpenedEvidence(
                trigger=trigger,
                source_seat=source_seat,
                responder_seats=reaction_seat_order(source_seat),
            )
        )

    def _close_epoch(self, outcome: ResponseOutcome) -> None:
        epoch = self._epoch
        if epoch is None:
            raise ValueError("no response epoch is open")
        self._epoch = None
        self._evidence.append(
            ResponseEpochClosedEvidence(
                trigger=epoch.trigger,
                source_seat=epoch.source_seat,
                outcome=outcome,
            )
        )
        self._evidence.extend(epoch.deferred)

    def _project(self, event: RoundEvent, follower: RoundEvent | None) -> None:
        if isinstance(event, RoundStartedEvent):
            self._evidence.append(
                RoundStartedEvidence(event.dealer_seat, event.prevailing_wind)
            )
            return
        if isinstance(event, TileDrawnEvent):
            self._evidence.append(
                DrawEvidence(
                    event.seat,
                    event.source,
                    public_tile(event.tile)
                    if event.seat is self._viewer_seat
                    else None,
                )
            )
            return
        if isinstance(event, TileDiscardedEvent):
            self._project_discard(event, follower)
            return
        if isinstance(event, MeldCalledEvent):
            self._evidence.append(
                MeldCalledEvidence(
                    event.seat,
                    public_meld(event.meld),
                    self._called_discard_order(event),
                )
            )
            return
        if isinstance(event, KanDeclaredEvent):
            trigger = _declared_kan_trigger(event)
            self._evidence.append(
                KanDeclaredEvidence(event.seat, public_meld(event.kan))
            )
            self._open_declared_kan_epoch(trigger, event.seat)
            return
        if isinstance(event, KanConfirmedEvent):
            if isinstance(event.kan, Daiminkan):
                # 大明槓の成立は同じtransactionのMeldCalledEventが表す。
                return
            self._evidence.append(
                KanConfirmedEvidence(event.seat, public_meld(event.kan))
            )
            return
        if isinstance(event, RoundEndedEvent):
            self._evidence.append(_round_ended_evidence(event.result))
            return
        # `TilesDealtEvent`（全席の配牌）、`ReactionsResolvedEvent`
        # （ron capable / selected / passed）、`MissedRonRecordedEvent`
        # （見逃しフリテン）を含む、whitelist外のeventは公開しない。

    def _project_discard(
        self,
        event: TileDiscardedEvent,
        follower: RoundEvent | None,
    ) -> None:
        if event.tile.id in self._discard_orders:
            raise ValueError("discard history contains duplicate physical tiles")
        order = self._discard_count
        self._discard_count += 1
        self._discard_orders[event.tile.id] = order
        declaration = _declaration_of(event, follower)
        self._evidence.append(
            DiscardEvidence(
                seat=event.seat,
                tile=public_tile(event.tile),
                is_tsumogiri=event.is_tsumogiri,
                order=order,
                is_riichi_declaration=declaration is not None,
            )
        )
        if declaration is not None:
            self._absorbed_declaration = declaration
            self._evidence.append(
                RiichiDeclaredEvidence(
                    declaration.declaration.seat,
                    public_tile(declaration.declaration.tile),
                    order,
                )
            )
        # 打牌がpublicに起きた時点で、hidden handを見ずにstructural epochを開く。
        self._open_epoch(ResponseTrigger.DISCARD, event.seat)

    def _open_declared_kan_epoch(
        self,
        trigger: ResponseTrigger,
        seat: Seat,
    ) -> None:
        """加槓・暗槓のstructural response epochをrule / topologyから決める。

        暗槓は`kokushi_ankan_chankan_enabled`というpublic rule settingだけ
        で開閉が決まり、実際の国士無双候補の有無では変わらない。加槓は
        常に槍槓のstructural epochを持つ。
        """
        if (
            trigger is ResponseTrigger.ANKAN
            and not self._rules.kokushi_ankan_chankan_enabled
        ):
            return
        self._open_epoch(trigger, seat)

    def _called_discard_order(self, event: MeldCalledEvent) -> int:
        meld = event.meld
        if not isinstance(meld, (Chi, Pon, Daiminkan)):
            raise ValueError("a called meld must be a chi, pon, or daiminkan")
        try:
            return self._discard_orders[meld.called_tile.id]
        except KeyError:
            raise ValueError("a called meld must consume a discarded tile") from None


def _declared_kan_trigger(event: KanDeclaredEvent) -> ResponseTrigger:
    if isinstance(event.kan, Ankan):
        return ResponseTrigger.ANKAN
    if isinstance(event.kan, Kakan):
        return ResponseTrigger.KAKAN
    raise ValueError("a daiminkan is not declared through a kan declaration")


def _declaration_of(
    event: TileDiscardedEvent,
    follower: RoundEvent | None,
) -> RiichiDeclaredEvent | None:
    """打牌の直後に記録された、その打牌自身の立直宣言を返す。"""
    if not isinstance(follower, RiichiDeclaredEvent):
        return None
    declaration = follower.declaration
    if declaration.seat is not event.seat or declaration.tile.id != event.tile.id:
        raise ValueError("a riichi declaration must follow its declaration discard")
    return follower


def _round_ended_evidence(result: RoundResult) -> RoundEndedEvidence:
    if isinstance(result, WinResult):
        return RoundEndedEvidence(
            kind=RoundEndKind.WIN,
            win_method=result.method,
            winner_seats=tuple(winner.seat for winner in result.winners),
            source_seat=result.source_seat,
        )
    if isinstance(result, AbortiveDrawResult):
        return RoundEndedEvidence(
            kind=RoundEndKind.ABORTIVE_DRAW,
            abortive_reason=result.reason,
        )
    if isinstance(result, ExhaustiveDrawResult):
        return RoundEndedEvidence(kind=RoundEndKind.EXHAUSTIVE_DRAW)
    raise TypeError("result must be a RoundResult")
