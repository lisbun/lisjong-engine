"""1局の状態基盤と、pull型core APIを提供する`RoundState`を定義する。

core境界はpull型である。engineはactionを選ばない。

```text
snapshot = state.legal_actions(seat)
chosen = snapshot.actions[0]
state.apply(seat, chosen, expected_revision=snapshot.revision)
```

反応windowだけは、同じwindowを複数席が同時に見るため、1席ずつの
`apply()`では扱わない。callerが席ごとの合法手snapshotからchoiceを選び、
window全体を1回のbatchとして渡す。

```text
choices = {seat: chosen_action for seat in state.reacting_seats}
resolution = state.resolve_reactions(choices, expected_revision=snapshot.revision)
```

choice収集中に`RoundState`をmutationしないため、3席のsnapshotは同じ
revisionを共有できる。優先順位の解決はengine側で行い、callerの入力順序
には依存させない。

`RoundState`はmutableだが、状態遷移はtransactionalである。

```text
seat / phase / revision validation
    -> 現在stateから合法手を再導出
    -> action membership validation
    -> working copyへ遷移
    -> invariant validation
    -> 成功時のみ本体へcommit
```

validationまたは遷移が失敗した場合、本体へpartial mutationを残さない。
成功したtransactionはrevisionをちょうど1つだけ進める。

## 点数との境界

`RoundState`はMatchの持ち点authorityではない。立直の点数条件判定に必要な
持ち点は、局開始時点のimmutable snapshot（`round_start_points`）として
注入する。立直成立時も持ち点を減算せず、`RiichiContribution`という供託の
事実だけを記録する。実際の点数移動と供託本数の管理は後続のMatch層が行う。

## E2とE3の境界

反応としてのロンは、合法判定・選択・優先順位解決までを本moduleが行う。
成立者が確定した局面は`AWAITING_WIN_FINALIZATION`へ進み、点数確定・
`RoundResult`構築・終局commitはE3が担当する。荒牌流局・途中流局の確定も
E3の責務であり、本moduleは暫定fallbackを作らない。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from lisjong_engine.discard import Discard
from lisjong_engine.furiten import FuritenReason
from lisjong_engine.kan import PendingAnkan, PendingKakan, count_quads
from lisjong_engine.legal_action import (
    AnkanLegalAction,
    DiscardDeclaration,
    DiscardLegalAction,
    KakanLegalAction,
    LegalAction,
    LegalActionSnapshot,
    ReactionOrigin,
    is_legal_action,
)
from lisjong_engine.legal_actions import RoundView, derive_legal_actions
from lisjong_engine.meld import Ankan, Kakan, Meld
from lisjong_engine.player_state import PlayerState
from lisjong_engine.reaction import (
    ReactionResolution,
    ReactionType,
    is_reaction_action,
    reaction_seat_order,
    resolve_reaction_choices,
)
from lisjong_engine.reaction_boundary import has_possible_reaction
from lisjong_engine.riichi_event import (
    RiichiContribution,
    RiichiDeclaration,
    RiichiDeclarationFinalization,
    finalize_riichi_declaration,
)
from lisjong_engine.round_event import (
    DoraIndicatorRevealedEvent,
    DrawSource,
    KanConfirmedEvent,
    KanDeclaredEvent,
    MeldCalledEvent,
    MissedRonRecordedEvent,
    ReactionsResolvedEvent,
    RiichiDeclaredEvent,
    RiichiFinalizedEvent,
    RoundEventSnapshot,
    RoundStartedEvent,
    TileDiscardedEvent,
    TileDrawnEvent,
    TilesDealtEvent,
)
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.rules import KanDoraRevealPolicy, RuleSet
from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile
from lisjong_engine.wall import Wall
from lisjong_engine.win_context import RiichiStatus
from lisjong_engine.wind import Wind

_SEAT_ORDER = tuple(Seat)
_DEAL_BLOCK_SIZE = 4
_DEAL_BLOCK_COUNT = 3

# drawn tileを保持できるphase。加槓・暗槓は打牌前の`AWAITING_DISCARD`から
# 宣言し、槍槓reactionを待つ間もそのturnのdrawn tileを保持し続ける。加槓・
# 暗槓の成立が確定した時点で初めてdrawn tileをclearし`AWAITING_RINSHAN_DRAW`
# へ進む。
_DRAWN_TILE_HOLDING_PHASES = (
    RoundPhase.AWAITING_DISCARD,
    RoundPhase.AWAITING_KAKAN_REACTIONS,
    RoundPhase.AWAITING_ANKAN_REACTIONS,
)

# 現在seatを持つphase。加槓・暗槓の反応待ちでは、宣言した席をcurrent seat
# として保持したまま他家の槍槓を待つ。
_CURRENT_SEAT_PHASES = (
    RoundPhase.AWAITING_DRAW,
    RoundPhase.AWAITING_DISCARD,
    RoundPhase.AWAITING_RINSHAN_DRAW,
    RoundPhase.AWAITING_KAKAN_REACTIONS,
    RoundPhase.AWAITING_ANKAN_REACTIONS,
)

_REACTION_PHASES = (
    RoundPhase.AWAITING_REACTIONS,
    RoundPhase.AWAITING_KAKAN_REACTIONS,
    RoundPhase.AWAITING_ANKAN_REACTIONS,
)

_TURN_ACTION_TYPES = (DiscardLegalAction, AnkanLegalAction, KakanLegalAction)


class RoundStateError(Exception):
    """局の状態機械が呼び出しを拒否したことを表す基底例外。"""


class IllegalOperationError(RoundStateError):
    """現在のphase・席では実行できない操作を表す。"""


class IllegalActionError(IllegalOperationError):
    """現在の合法手集合に存在しないactionを表す。"""


class StaleActionError(IllegalOperationError):
    """既に古くなったsnapshotのactionを表す。"""


class RoundInvariantError(RoundStateError):
    """遷移後の状態が局の不変条件を満たさないことを表す。"""


@dataclass(frozen=True)
class PendingRonResolution:
    """ロンの成立者が確定し、E3の和了確定を待っている事実。

    E3が点数確定・`RoundResult`構築へ進むために必要なprovenanceを、
    反応windowが閉じた後も失わないよう保持する。どの席が和了できたか
    （capable）、選択したか（selected）、成立したか（awarded）、見逃したか
    （passed）の区別は`resolution`が持つ。
    """

    resolution: ReactionResolution
    target_tile: Tile
    is_last_tile: bool

    def __post_init__(self) -> None:
        if not isinstance(self.resolution, ReactionResolution):
            raise TypeError("resolution must be a ReactionResolution")
        if not self.resolution.is_ron:
            raise ValueError("a pending ron resolution requires a ron resolution")
        if not isinstance(self.target_tile, Tile):
            raise TypeError("target_tile must be a Tile")
        if self.target_tile.id != self.resolution.target_tile_id:
            raise ValueError("target_tile must match the resolved reaction target")
        if type(self.is_last_tile) is not bool:
            raise TypeError("is_last_tile must be a bool")

    @property
    def origin(self) -> ReactionOrigin:
        return self.resolution.origin

    @property
    def source_seat(self) -> Seat:
        return self.resolution.source_seat

    @property
    def winner_seats(self) -> tuple[Seat, ...]:
        return self.resolution.ron_awarded_seats

    @property
    def is_chankan(self) -> bool:
        return self.resolution.origin in (ReactionOrigin.KAKAN, ReactionOrigin.ANKAN)


@dataclass
class _Transition:
    """commit前の遷移結果をまとめて保持するworking copy。"""

    wall: Wall
    players: dict[Seat, PlayerState]
    phase: RoundPhase
    current_seat: Seat | None
    drawn_tile_id: int | None
    drawn_tile_source: DrawSource | None
    pending_discarder: Seat | None
    pending_discard: Discard | None
    pending_discard_source: DrawSource | None
    pending_kakan: PendingKakan | None
    pending_ankan: PendingAnkan | None
    pending_riichi_declaration: RiichiDeclaration | None
    pending_ron_resolution: PendingRonResolution | None
    pending_kan_dora_reveals: tuple[Seat, ...]
    riichi_finalizations: tuple[RiichiDeclarationFinalization, ...]
    suukantsu_pao_seats: dict[Seat, Seat]
    events: RoundEventSnapshot


class RoundState:
    def __init__(
        self,
        wall: Wall,
        *,
        round_start_points: Mapping[Seat, int],
        dealer_seat: Seat = Seat.EAST,
        prevailing_wind: Wind = Wind.EAST,
        rules: RuleSet | None = None,
    ) -> None:
        if not isinstance(wall, Wall):
            raise TypeError("wall must be a Wall")
        if not isinstance(dealer_seat, Seat):
            raise TypeError("dealer_seat must be a Seat")
        if not isinstance(prevailing_wind, Wind):
            raise TypeError("prevailing_wind must be a Wind")
        if rules is not None and not isinstance(rules, RuleSet):
            raise TypeError("rules must be a RuleSet or None")

        self._wall = wall.copy()
        self._dealer_seat = dealer_seat
        self._prevailing_wind = prevailing_wind
        self._rules = RuleSet.default() if rules is None else rules
        self._round_start_points = _normalize_round_start_points(round_start_points)
        self._players = {seat: PlayerState(seat) for seat in _SEAT_ORDER}
        self._phase = RoundPhase.UNDEALT
        self._current_seat: Seat | None = None
        self._drawn_tile_id: int | None = None
        self._drawn_tile_source: DrawSource | None = None
        self._pending_discarder: Seat | None = None
        self._pending_discard: Discard | None = None
        self._pending_discard_source: DrawSource | None = None
        self._pending_kakan: PendingKakan | None = None
        self._pending_ankan: PendingAnkan | None = None
        self._pending_riichi_declaration: RiichiDeclaration | None = None
        self._pending_ron_resolution: PendingRonResolution | None = None
        self._pending_kan_dora_reveals: tuple[Seat, ...] = ()
        self._riichi_finalizations: tuple[RiichiDeclarationFinalization, ...] = ()
        self._suukantsu_pao_seats: dict[Seat, Seat] = {}
        self._events = RoundEventSnapshot()
        self._revision = 0
        # 保存則checkの基準。局中に物理牌が増減しないことを直接確認する。
        self._tile_ids = frozenset(
            tile.id
            for tile in (*self._wall.remaining_tiles, *self._wall.dead_wall_tiles)
        )

    @property
    def phase(self) -> RoundPhase:
        return self._phase

    @property
    def current_seat(self) -> Seat | None:
        return self._current_seat

    @property
    def dealer_seat(self) -> Seat:
        return self._dealer_seat

    @property
    def prevailing_wind(self) -> Wind:
        return self._prevailing_wind

    @property
    def rules(self) -> RuleSet:
        return self._rules

    @property
    def round_start_points(self) -> Mapping[Seat, int]:
        """局開始時点の席別持ち点snapshot。

        Matchの現在点への参照ではなく、局開始時点で確定したimmutableな
        入力である。局中に立直が成立してもこのsnapshot自体は変化しない。
        """
        return MappingProxyType(self._round_start_points)

    @property
    def revision(self) -> int:
        """局内で単調増加するstate revision。

        process-globalではなく局ローカルであり、同じ初期状態と同じaction
        sequenceからは常に同じprogressionになる。
        """
        return self._revision

    @property
    def remaining_count(self) -> int:
        return self._wall.remaining_count

    @property
    def remaining_tiles(self) -> tuple[Tile, ...]:
        return self._wall.remaining_tiles

    @property
    def dead_wall_tiles(self) -> tuple[Tile, ...]:
        return self._wall.dead_wall_tiles

    @property
    def revealed_dora_indicators(self) -> tuple[Tile, ...]:
        return self._wall.revealed_dora_indicators

    @property
    def corresponding_ura_dora_indicators(self) -> tuple[Tile, ...]:
        return self._wall.corresponding_ura_dora_indicators

    @property
    def remaining_rinshan_count(self) -> int:
        return self._wall.remaining_rinshan_count

    @property
    def drawn_tile_id(self) -> int | None:
        """現在のturnでツモった物理牌ID。

        ツモ牌自体は手牌が所有し、本fieldはそのturn-level factとしての
        参照である。ツモ切り判定はこの参照からengineが導出する。
        """
        return self._drawn_tile_id

    @property
    def drawn_tile_source(self) -> DrawSource | None:
        return self._drawn_tile_source

    @property
    def drawn_tile(self) -> Tile | None:
        if self._drawn_tile_id is None or self._current_seat is None:
            return None
        return next(
            tile
            for tile in self._players[self._current_seat].hand_tiles
            if tile.id == self._drawn_tile_id
        )

    @property
    def pending_discarder(self) -> Seat | None:
        return self._pending_discarder

    @property
    def pending_discard(self) -> Discard | None:
        return self._pending_discard

    @property
    def pending_kakan(self) -> PendingKakan | None:
        """槍槓の解決を待っている加槓。まだ副露へ確定していない。"""
        return self._pending_kakan

    @property
    def pending_ankan(self) -> PendingAnkan | None:
        """国士無双の槍槓の解決を待っている暗槓。まだ副露へ確定していない。"""
        return self._pending_ankan

    @property
    def pending_riichi_declaration(self) -> RiichiDeclaration | None:
        return self._pending_riichi_declaration

    @property
    def pending_ron_resolution(self) -> PendingRonResolution | None:
        """成立者が確定し、E3の和了確定を待っているロン。"""
        return self._pending_ron_resolution

    @property
    def pending_kan_dora_reveals(self) -> tuple[Seat, ...]:
        """公開を保留している槓ドラの、原因となった槓の宣言者。

        `KanDoraRevealPolicy.DELAY_OPEN_KAN_DORA`のとき、大明槓・加槓の
        槓ドラは直後の打牌がロン以外で解決するまで公開しない。
        """
        return self._pending_kan_dora_reveals

    @property
    def riichi_finalizations(self) -> tuple[RiichiDeclarationFinalization, ...]:
        return self._riichi_finalizations

    @property
    def riichi_contributions(self) -> tuple[RiichiContribution, ...]:
        """立直成立により供託が必要になった事実の一覧。

        `RoundState`はこの事実を記録するだけで持ち点を減算しない。実際の
        点数移動と供託本数の管理はMatch層の責務である。
        """
        return tuple(
            finalization.contribution
            for finalization in self._riichi_finalizations
            if finalization.contribution is not None
        )

    @property
    def riichi_payment_deltas(self) -> Mapping[Seat, int]:
        """立直供託としてMatchが適用すべき、席別の点数増減。"""
        deltas = {seat: 0 for seat in _SEAT_ORDER}
        for contribution in self.riichi_contributions:
            deltas[contribution.seat] -= contribution.points
        return MappingProxyType(deltas)

    @property
    def has_meld_occurred(self) -> bool:
        return any(player.melds for player in self._players.values())

    @property
    def reacting_seats(self) -> tuple[Seat, ...]:
        """現在の反応windowで、choiceを求められる3席を返す。

        反応windowが開いていない場合は空のtupleを返す。反応できない席も
        パスというchoiceを持つため、ここから席が省かれることはない。
        """
        if self._phase not in _REACTION_PHASES:
            return ()
        return reaction_seat_order(self._reaction_window()[1])

    @property
    def events(self) -> RoundEventSnapshot:
        return self._events

    def seat_wind(self, seat: Seat) -> Wind:
        self._validate_seat(seat)
        seat_offset = (
            _SEAT_ORDER.index(seat) - _SEAT_ORDER.index(self._dealer_seat)
        ) % len(_SEAT_ORDER)
        return tuple(Wind)[seat_offset]

    def hand_tiles(self, seat: Seat) -> tuple[Tile, ...]:
        self._validate_seat(seat)
        return self._players[seat].hand_tiles

    def discards(self, seat: Seat) -> tuple[Discard, ...]:
        self._validate_seat(seat)
        return self._players[seat].discards

    def melds(self, seat: Seat) -> tuple[Meld, ...]:
        self._validate_seat(seat)
        return self._players[seat].melds

    def is_menzen(self, seat: Seat) -> bool:
        self._validate_seat(seat)
        return self._players[seat].is_menzen

    def riichi_status(self, seat: Seat) -> RiichiStatus:
        self._validate_seat(seat)
        return self._players[seat].riichi_status

    def is_riichi_established(self, seat: Seat) -> bool:
        self._validate_seat(seat)
        return self._players[seat].is_riichi_established

    def is_ippatsu(self, seat: Seat) -> bool:
        self._validate_seat(seat)
        return self._players[seat].is_ippatsu

    def furiten_reasons(self, seat: Seat) -> frozenset[FuritenReason]:
        self._validate_seat(seat)
        return self._players[seat].furiten_reasons

    def is_furiten(self, seat: Seat) -> bool:
        self._validate_seat(seat)
        return self._players[seat].is_furiten

    def suukantsu_pao_seat(self, seat: Seat) -> Seat | None:
        """四槓子の責任払いが成立している場合の責任者席。

        責任の成立は大明槓の成立時点でしか判定できない。加槓は元のポンの
        位置で差し替わるため、和了時点の副露の並びからは復元できないため
        である。
        """
        self._validate_seat(seat)
        return self._suukantsu_pao_seats.get(seat)

    def legal_actions(self, seat: Seat) -> LegalActionSnapshot:
        """`seat`の合法手を、副作用のないimmutable snapshotで返す。

        導出は`legal_actions`moduleのpure関数へ委譲する。本methodは
        現在stateをviewへ写して渡すだけの薄いfacadeである。
        """
        self._validate_seat(seat)
        return LegalActionSnapshot(
            seat=seat,
            phase=self._phase,
            revision=self._revision,
            actions=derive_legal_actions(self._committed_view(), seat),
        )

    def deal(self) -> dict[Seat, tuple[Tile, ...]]:
        """親から順に4枚ずつ3巡、最後に1枚ずつ配る標準の配牌を行う。"""
        if self._phase is not RoundPhase.UNDEALT:
            raise IllegalOperationError("deal is only allowed before the initial deal")

        transition = self._begin()
        deal_order = self._seat_order_from(self._dealer_seat)
        dealt_tiles: dict[Seat, list[Tile]] = {seat: [] for seat in _SEAT_ORDER}

        for _ in range(_DEAL_BLOCK_COUNT):
            for seat in deal_order:
                for _ in range(_DEAL_BLOCK_SIZE):
                    tile = transition.wall.draw()
                    transition.players[seat].add_tile(tile)
                    dealt_tiles[seat].append(tile)
        for seat in deal_order:
            tile = transition.wall.draw()
            transition.players[seat].add_tile(tile)
            dealt_tiles[seat].append(tile)

        transition.current_seat = self._dealer_seat
        transition.phase = RoundPhase.AWAITING_DRAW
        transition.events = transition.events.appended(
            (
                RoundStartedEvent(self._dealer_seat, self._prevailing_wind),
                *(
                    TilesDealtEvent(seat, tuple(dealt_tiles[seat]))
                    for seat in deal_order
                ),
            )
        )

        self._commit(transition)
        return {seat: tuple(dealt_tiles[seat]) for seat in _SEAT_ORDER}

    def draw(self, seat: Seat) -> Tile:
        """山から1枚ツモる。合法手の選択を伴わない強制操作である。"""
        self._validate_seat(seat)
        if self._phase is not RoundPhase.AWAITING_DRAW:
            raise IllegalOperationError("draw is only allowed while awaiting a draw")
        if seat is not self._current_seat:
            raise IllegalOperationError("only the current seat can draw")

        return self._draw_into_hand(seat, DrawSource.LIVE_WALL)

    def draw_rinshan(self, seat: Seat) -> Tile:
        """槓の成立後に嶺上牌をツモる。通常の山からのツモとは区別する。"""
        self._validate_seat(seat)
        if self._phase is not RoundPhase.AWAITING_RINSHAN_DRAW:
            raise IllegalOperationError(
                "a rinshan draw is only allowed while awaiting one"
            )
        if seat is not self._current_seat:
            raise IllegalOperationError("only the current seat can draw")

        return self._draw_into_hand(seat, DrawSource.RINSHAN)

    def apply(
        self,
        seat: Seat,
        action: LegalAction,
        *,
        expected_revision: int,
    ) -> None:
        """callerが選んだturn actionを適用する。

        `expected_revision`はsnapshot取得時のrevisionである。局の状態が
        1つでも進んでいれば、同じdomain valueのactionが現在も合法かどうか
        に関わらずstaleとして拒否する。

        callerの「さっき合法だった」という主張は信用せず、必ず現在state
        から合法手を再導出して照合する。反応actionは複数席を同時に解決
        する必要があるため、本methodでは受け付けず`resolve_reactions()`
        へ回す。
        """
        self._validate_seat(seat)
        if not is_legal_action(action):
            raise TypeError("action must be a legal action")
        if type(expected_revision) is not int:
            raise TypeError("expected_revision must be an int")

        self._validate_revision(expected_revision)
        if is_reaction_action(action):
            raise IllegalActionError(
                "reaction actions must be resolved for every reacting seat at once "
                "through resolve_reactions()"
            )
        if not isinstance(action, _TURN_ACTION_TYPES):
            # E3のaction型はvalueとして存在するが、E2の状態機械は遷移を
            # 持たない。暗黙のpassやfallbackを作らず拒否する。
            raise IllegalActionError(
                f"{type(action).__name__} is not supported by this round state"
            )
        if action not in self.legal_actions(seat).actions:
            raise IllegalActionError(
                "action is not in the current legal actions for this seat"
            )

        if isinstance(action, DiscardLegalAction):
            self._apply_discard(seat, action)
        elif isinstance(action, AnkanLegalAction):
            self._apply_ankan(seat, action)
        else:
            self._apply_kakan(seat, action)

    def resolve_reactions(
        self,
        choices: Mapping[Seat, LegalAction],
        *,
        expected_revision: int,
    ) -> ReactionResolution:
        """反応windowを1つのtransactionで解決する。

        `choices`は反応対象の3席ちょうどを含まなければならない。不足・
        余分・非合法のいずれかがあれば、window全体を拒否して状態を1つも
        変更しない。優先順位はengine側で解決し、`choices`のiteration順は
        結果に影響しない。

        成功した場合だけ、鳴き・立直成立・フリテン・一発・槓を含む
        すべての更新をまとめてcommitし、revisionをちょうど1つ進める。
        """
        if not isinstance(choices, Mapping):
            raise TypeError("choices must be a mapping keyed by seat")
        if any(not isinstance(seat, Seat) for seat in choices):
            raise TypeError("choices must be keyed by Seat values")
        if any(not is_legal_action(action) for action in choices.values()):
            raise TypeError("choices must contain only legal actions")
        if type(expected_revision) is not int:
            raise TypeError("expected_revision must be an int")

        self._validate_revision(expected_revision)
        if self._phase not in _REACTION_PHASES:
            raise IllegalOperationError(
                "resolve_reactions is only allowed while a reaction window is open"
            )

        origin, source_seat, target_tile = self._reaction_window()
        required_seats = reaction_seat_order(source_seat)
        candidates = {
            seat: derive_legal_actions(self._committed_view(), seat)
            for seat in required_seats
        }
        self._validate_reaction_choices(choices, candidates, required_seats)

        resolution = resolve_reaction_choices(
            origin=origin,
            source_seat=source_seat,
            target_tile_id=target_tile.id,
            candidates=candidates,
            choices={seat: choices[seat] for seat in required_seats},
            ron_resolution_policy=self._rules.ron_resolution_policy,
        )

        transition = self._begin()
        transition.events = transition.events.appended(
            (ReactionsResolvedEvent(resolution),)
        )
        self._apply_resolution(transition, resolution, target_tile)
        self._commit(transition)
        return resolution

    def _validate_reaction_choices(
        self,
        choices: Mapping[Seat, LegalAction],
        candidates: Mapping[Seat, tuple[LegalAction, ...]],
        required_seats: tuple[Seat, ...],
    ) -> None:
        missing = tuple(seat for seat in required_seats if seat not in choices)
        if missing:
            raise IllegalActionError(
                "every reacting seat must choose an action; missing "
                f"{tuple(seat.value for seat in missing)}"
            )
        extra = tuple(seat for seat in choices if seat not in required_seats)
        if extra:
            raise IllegalActionError(
                "only the reacting seats may choose an action; unexpected "
                f"{tuple(seat.value for seat in extra)}"
            )
        for seat in required_seats:
            if choices[seat] not in candidates[seat]:
                raise IllegalActionError(
                    f"the chosen action is not legal for the {seat.value} seat"
                )

    def _reaction_window(self) -> tuple[ReactionOrigin, Seat, Tile]:
        """現在開いている反応windowの起点・発生元席・対象牌を返す。"""
        if self._phase is RoundPhase.AWAITING_REACTIONS:
            if self._pending_discarder is None or self._pending_discard is None:
                raise RoundInvariantError("the pending discard state is incomplete")
            return (
                ReactionOrigin.DISCARD,
                self._pending_discarder,
                self._pending_discard.tile,
            )
        if self._phase is RoundPhase.AWAITING_KAKAN_REACTIONS:
            if self._pending_kakan is None:
                raise RoundInvariantError("the pending kakan state is incomplete")
            return (
                ReactionOrigin.KAKAN,
                self._pending_kakan.seat,
                self._pending_kakan.target_tile,
            )
        if self._pending_ankan is None:
            raise RoundInvariantError("the pending ankan state is incomplete")
        return (
            ReactionOrigin.ANKAN,
            self._pending_ankan.seat,
            self._pending_ankan.target_tile,
        )

    def _draw_into_hand(self, seat: Seat, source: DrawSource) -> Tile:
        transition = self._begin()
        tile = (
            transition.wall.draw_rinshan()
            if source is DrawSource.RINSHAN
            else transition.wall.draw()
        )
        # 自分のツモ番が来た時点で、同巡内の見逃しフリテンは解除される。
        transition.players[seat].clear_temporary_furiten()
        transition.players[seat].add_tile(tile)
        transition.drawn_tile_id = tile.id
        transition.drawn_tile_source = source
        transition.phase = RoundPhase.AWAITING_DISCARD
        transition.events = transition.events.appended(
            (TileDrawnEvent(seat, tile, source),)
        )

        self._commit(transition)
        return tile

    def _apply_discard(self, seat: Seat, action: DiscardLegalAction) -> None:
        transition = self._begin()
        player = transition.players[seat]
        declares_riichi = action.declaration is DiscardDeclaration.RIICHI
        was_first_discard = not player.has_discarded
        had_prior_call = self.has_meld_occurred

        is_tsumogiri = action.tile_id == transition.drawn_tile_id
        discard = player.discard_tile(action.tile_id, is_tsumogiri=is_tsumogiri)
        # 一発は、立直した席自身の次の打牌で失効する。
        player.cancel_ippatsu()
        discard_source = transition.drawn_tile_source
        transition.drawn_tile_id = None
        transition.drawn_tile_source = None
        new_events = [TileDiscardedEvent(seat, discard.tile, discard.is_tsumogiri)]

        if declares_riichi:
            declaration = RiichiDeclaration(
                seat=seat,
                discard=discard,
                discard_count=player.discard_count,
                remaining_live_tiles=transition.wall.remaining_count,
                was_first_discard=was_first_discard,
                had_prior_call=had_prior_call,
            )
            transition.pending_riichi_declaration = declaration
            new_events.append(RiichiDeclaredEvent(declaration))
        transition.events = transition.events.appended(new_events)

        if has_possible_reaction(
            discarder=seat,
            discarded_tile=discard.tile,
            hand_tiles_by_seat={
                other: transition.players[other].hand_tiles for other in _SEAT_ORDER
            },
            melds_by_seat={
                other: transition.players[other].melds for other in _SEAT_ORDER
            },
            remaining_count=transition.wall.remaining_count,
            can_draw_rinshan=transition.wall.can_draw_rinshan,
        ):
            transition.phase = RoundPhase.AWAITING_REACTIONS
            transition.current_seat = None
            transition.pending_discarder = seat
            transition.pending_discard = discard
            transition.pending_discard_source = discard_source
        else:
            # 反応の必要条件を誰も満たさないため、反応windowを開いても
            # 全員パスにしかならない。同じtransactionで全員パスと同じ
            # 結果まで進める。
            self._release_pending_kan_dora(transition)
            self._finalize_riichi(transition, ReactionType.PASS)
            transition.phase = RoundPhase.AWAITING_DRAW
            transition.current_seat = seat.next()

        self._commit(transition)

    def _apply_ankan(self, seat: Seat, action: AnkanLegalAction) -> None:
        transition = self._begin()
        # 副露へ確定させる前に、値としてのAnkanだけを組み立てる。槍槓で
        # 成立しない可能性があるため、この時点では手牌を減らさない。
        ankan = transition.players[seat].copy().declare_ankan(action.tile_ids)
        pending = PendingAnkan(seat, ankan)
        # 槓の宣言自体で一発は消える。槍槓候補の有無に関わらず確定させる。
        self._cancel_all_ippatsu(transition)
        transition.events = transition.events.appended((KanDeclaredEvent(seat, ankan),))

        transition.pending_ankan = pending
        transition.phase = RoundPhase.AWAITING_ANKAN_REACTIONS
        if self._has_reaction_candidate(transition, seat):
            self._commit(transition)
            return

        # 国士無双の槍槓候補がいない（またはルールで無効な）暗槓は、
        # 反応windowを開かずその場で成立させる。
        transition.pending_ankan = None
        self._confirm_ankan(transition, seat, ankan)
        self._commit(transition)

    def _apply_kakan(self, seat: Seat, action: KakanLegalAction) -> None:
        transition = self._begin()
        # 元のポンをここで書き換えない。加槓は値として保留し、槍槓が全員
        # パスされてから初めて副露へ差し替える。
        kakan = transition.players[seat].copy().declare_kakan(action.added_tile_id)
        self._cancel_all_ippatsu(transition)
        transition.events = transition.events.appended((KanDeclaredEvent(seat, kakan),))

        transition.pending_kakan = PendingKakan(seat, kakan)
        transition.phase = RoundPhase.AWAITING_KAKAN_REACTIONS
        self._commit(transition)

    def _has_reaction_candidate(
        self, transition: _Transition, source_seat: Seat
    ) -> bool:
        view = self._transition_view(transition)
        return any(
            len(derive_legal_actions(view, seat)) > 1
            for seat in reaction_seat_order(source_seat)
        )

    def _apply_resolution(
        self,
        transition: _Transition,
        resolution: ReactionResolution,
        target_tile: Tile,
    ) -> None:
        self._record_missed_rons(transition, resolution)
        if resolution.is_ron:
            self._apply_ron(transition, resolution, target_tile)
        elif resolution.origin is ReactionOrigin.DISCARD:
            # この打牌はロン以外で解決したため、保留していた槓ドラを公開する。
            self._release_pending_kan_dora(transition)
            if resolution.is_call:
                self._apply_call(transition, resolution)
            else:
                self._advance_after_pass(transition, resolution)
        elif resolution.origin is ReactionOrigin.KAKAN:
            pending = transition.pending_kakan
            if pending is None:
                raise RoundInvariantError("the pending kakan state is incomplete")
            transition.pending_kakan = None
            self._confirm_kakan(transition, pending.seat, pending.kakan)
        else:
            pending = transition.pending_ankan
            if pending is None:
                raise RoundInvariantError("the pending ankan state is incomplete")
            transition.pending_ankan = None
            self._confirm_ankan(transition, pending.seat, pending.ankan)

        if resolution.origin is ReactionOrigin.DISCARD:
            self._finalize_riichi(transition, resolution.resolved_type)

    def _apply_ron(
        self,
        transition: _Transition,
        resolution: ReactionResolution,
        target_tile: Tile,
    ) -> None:
        """ロンの成立者を確定し、E3の和了確定待ちへ進める。

        点数確定・`RoundResult`構築・終局commitはE3の責務である。ここで
        保留中の加槓・暗槓を成立させないことで、槍槓で槓が流れる契約も
        同時に満たす。
        """
        is_last_tile = (
            resolution.origin is ReactionOrigin.DISCARD
            and transition.pending_discard_source is DrawSource.LIVE_WALL
            and transition.wall.remaining_count == 0
        )
        transition.pending_ron_resolution = PendingRonResolution(
            resolution,
            target_tile,
            is_last_tile,
        )
        transition.phase = RoundPhase.AWAITING_WIN_FINALIZATION
        transition.current_seat = None
        transition.drawn_tile_id = None
        transition.drawn_tile_source = None
        transition.pending_discarder = None
        transition.pending_discard = None
        transition.pending_discard_source = None
        transition.pending_kakan = None
        transition.pending_ankan = None

    def _apply_call(
        self,
        transition: _Transition,
        resolution: ReactionResolution,
    ) -> None:
        seat = resolution.resolved_seat
        action = resolution.resolved_action
        discarder = resolution.source_seat
        discard = transition.pending_discard
        if seat is None or action is None or discard is None:
            raise RoundInvariantError("the resolved call state is incomplete")

        player = transition.players[seat]
        if resolution.resolved_type is ReactionType.PON:
            meld = player.call_pon(discard.tile, action.consumed_tile_ids, discarder)
        elif resolution.resolved_type is ReactionType.CHI:
            meld = player.call_chi(discard.tile, action.consumed_tile_ids, discarder)
        else:
            # 四槓子の責任払いは、大明槓で4つ目の槓子が確定した時点でしか
            # 判定できないため、成立前の槓子数をここで見る。
            completes_four_kans = count_quads(player.melds) == 3
            meld = player.call_daiminkan(
                discard.tile,
                action.consumed_tile_ids,
                discarder,
            )
            if completes_four_kans:
                transition.suukantsu_pao_seats[seat] = discarder

        transition.players[discarder].mark_discard_called(discard.tile.id, seat)
        self._cancel_all_ippatsu(transition)

        new_events = [MeldCalledEvent(seat, meld)]
        transition.current_seat = seat
        transition.drawn_tile_id = None
        transition.drawn_tile_source = None
        transition.pending_discarder = None
        transition.pending_discard = None
        transition.pending_discard_source = None
        if resolution.resolved_type is ReactionType.DAIMINKAN:
            # 大明槓自体には槍槓が無く、この時点で成立が確定している。
            new_events.append(KanConfirmedEvent(seat, meld))
            new_events.extend(self._confirm_kan_dora(transition, seat))
            transition.phase = RoundPhase.AWAITING_RINSHAN_DRAW
        else:
            # 鳴き後の打牌はツモを伴わないため、drawn tileのない
            # `AWAITING_DISCARD`が正常状態である。
            transition.phase = RoundPhase.AWAITING_DISCARD
        transition.events = transition.events.appended(new_events)

    def _advance_after_pass(
        self,
        transition: _Transition,
        resolution: ReactionResolution,
    ) -> None:
        transition.phase = RoundPhase.AWAITING_DRAW
        transition.current_seat = resolution.source_seat.next()
        transition.pending_discarder = None
        transition.pending_discard = None
        transition.pending_discard_source = None

    def _confirm_kakan(
        self,
        transition: _Transition,
        seat: Seat,
        kakan: Kakan,
    ) -> None:
        committed = transition.players[seat].declare_kakan(kakan.added_tile.id)
        if committed != kakan:
            raise RoundInvariantError("the pending kakan no longer matches the hand")

        transition.drawn_tile_id = None
        transition.drawn_tile_source = None
        transition.current_seat = seat
        transition.phase = RoundPhase.AWAITING_RINSHAN_DRAW
        transition.events = transition.events.appended(
            (
                KanConfirmedEvent(seat, committed),
                *self._confirm_kan_dora(transition, seat),
            )
        )

    def _confirm_ankan(
        self,
        transition: _Transition,
        seat: Seat,
        ankan: Ankan,
    ) -> None:
        committed = transition.players[seat].declare_ankan(
            tuple(tile.id for tile in ankan.tiles)
        )
        if committed != ankan:
            raise RoundInvariantError("the pending ankan no longer matches the hand")

        # 暗槓には（国士無双の槍槓を除き）槍槓が無いため、成立と同時に
        # 槓ドラを公開する。この公開は`KanDoraRevealPolicy`の対象外である。
        indicator = transition.wall.reveal_kan_dora()
        transition.drawn_tile_id = None
        transition.drawn_tile_source = None
        transition.current_seat = seat
        transition.phase = RoundPhase.AWAITING_RINSHAN_DRAW
        transition.events = transition.events.appended(
            (
                KanConfirmedEvent(seat, committed),
                DoraIndicatorRevealedEvent(seat, indicator),
            )
        )

    def _confirm_kan_dora(
        self,
        transition: _Transition,
        seat: Seat,
    ) -> tuple[DoraIndicatorRevealedEvent, ...]:
        """大明槓・加槓の成立確定時に、公開タイミングpolicyへ従う。"""
        if (
            self._rules.kan_dora_reveal_policy
            is KanDoraRevealPolicy.IMMEDIATE_ON_KAN_CONFIRMATION
        ):
            indicator = transition.wall.reveal_kan_dora()
            return (DoraIndicatorRevealedEvent(seat, indicator),)
        transition.pending_kan_dora_reveals = (
            *transition.pending_kan_dora_reveals,
            seat,
        )
        return ()

    def _release_pending_kan_dora(self, transition: _Transition) -> None:
        """保留していた槓ドラを、まとめて公開する。"""
        if not transition.pending_kan_dora_reveals:
            return
        new_events = []
        for seat in transition.pending_kan_dora_reveals:
            new_events.append(
                DoraIndicatorRevealedEvent(seat, transition.wall.reveal_kan_dora())
            )
        transition.pending_kan_dora_reveals = ()
        transition.events = transition.events.appended(new_events)

    def _record_missed_rons(
        self,
        transition: _Transition,
        resolution: ReactionResolution,
    ) -> None:
        """ロンできた牌を見逃した席だけを、フリテンへ反映する。

        頭ハネで成立しなかったロン選択者は見逃しではないため、
        `ron_passed_seats`へ含まれず、ここでも対象にならない。
        """
        new_events = []
        for seat in reaction_seat_order(resolution.source_seat):
            if seat not in resolution.ron_passed_seats:
                continue
            player = transition.players[seat]
            player.record_missed_ron()
            reason = player.missed_ron_furiten
            if reason is None:
                raise RoundInvariantError("a missed ron must set a furiten reason")
            new_events.append(MissedRonRecordedEvent(seat, reason))
        transition.events = transition.events.appended(new_events)

    def _finalize_riichi(
        self,
        transition: _Transition,
        reaction_type: ReactionType,
    ) -> None:
        """宣言牌への反応が解決した時点で、立直の成立可否を確定する。

        ロンが成立した場合は立直不成立であり、供託の事実も作らない。
        鳴かれた場合は立直自体は成立するが、一発は付かない。
        """
        declaration = transition.pending_riichi_declaration
        if declaration is None:
            return

        finalization = finalize_riichi_declaration(
            declaration,
            reaction_type=reaction_type,
            riichi_stick_points=self._rules.riichi_stick_points,
        )
        transition.pending_riichi_declaration = None
        transition.riichi_finalizations = (
            *transition.riichi_finalizations,
            finalization,
        )
        if finalization.is_established:
            transition.players[declaration.seat].establish_riichi(
                finalization.riichi_status,
                ippatsu=finalization.grants_ippatsu,
            )
        transition.events = transition.events.appended(
            (RiichiFinalizedEvent(finalization),)
        )

    @staticmethod
    def _cancel_all_ippatsu(transition: _Transition) -> None:
        for player in transition.players.values():
            player.cancel_ippatsu()

    def _committed_view(self) -> RoundView:
        return self._build_view(
            players=self._players,
            phase=self._phase,
            current_seat=self._current_seat,
            drawn_tile_id=self._drawn_tile_id,
            remaining_count=self._wall.remaining_count,
            can_draw_rinshan=self._wall.can_draw_rinshan,
            pending_discarder=self._pending_discarder,
            pending_discard=self._pending_discard,
            pending_discard_source=self._pending_discard_source,
            pending_kakan=self._pending_kakan,
            pending_ankan=self._pending_ankan,
        )

    def _transition_view(self, transition: _Transition) -> RoundView:
        return self._build_view(
            players=transition.players,
            phase=transition.phase,
            current_seat=transition.current_seat,
            drawn_tile_id=transition.drawn_tile_id,
            remaining_count=transition.wall.remaining_count,
            can_draw_rinshan=transition.wall.can_draw_rinshan,
            pending_discarder=transition.pending_discarder,
            pending_discard=transition.pending_discard,
            pending_discard_source=transition.pending_discard_source,
            pending_kakan=transition.pending_kakan,
            pending_ankan=transition.pending_ankan,
        )

    def _build_view(self, **fields) -> RoundView:
        return RoundView(
            seat_winds={seat: self.seat_wind(seat) for seat in _SEAT_ORDER},
            prevailing_wind=self._prevailing_wind,
            rules=self._rules,
            round_start_points=self._round_start_points,
            **fields,
        )

    def _begin(self) -> _Transition:
        return _Transition(
            wall=self._wall.copy(),
            players={seat: player.copy() for seat, player in self._players.items()},
            phase=self._phase,
            current_seat=self._current_seat,
            drawn_tile_id=self._drawn_tile_id,
            drawn_tile_source=self._drawn_tile_source,
            pending_discarder=self._pending_discarder,
            pending_discard=self._pending_discard,
            pending_discard_source=self._pending_discard_source,
            pending_kakan=self._pending_kakan,
            pending_ankan=self._pending_ankan,
            pending_riichi_declaration=self._pending_riichi_declaration,
            pending_ron_resolution=self._pending_ron_resolution,
            pending_kan_dora_reveals=self._pending_kan_dora_reveals,
            riichi_finalizations=self._riichi_finalizations,
            suukantsu_pao_seats=dict(self._suukantsu_pao_seats),
            events=self._events,
        )

    def _commit(self, transition: _Transition) -> None:
        self._validate_invariants(transition)
        self._wall = transition.wall
        self._players = transition.players
        self._phase = transition.phase
        self._current_seat = transition.current_seat
        self._drawn_tile_id = transition.drawn_tile_id
        self._drawn_tile_source = transition.drawn_tile_source
        self._pending_discarder = transition.pending_discarder
        self._pending_discard = transition.pending_discard
        self._pending_discard_source = transition.pending_discard_source
        self._pending_kakan = transition.pending_kakan
        self._pending_ankan = transition.pending_ankan
        self._pending_riichi_declaration = transition.pending_riichi_declaration
        self._pending_ron_resolution = transition.pending_ron_resolution
        self._pending_kan_dora_reveals = transition.pending_kan_dora_reveals
        self._riichi_finalizations = transition.riichi_finalizations
        self._suukantsu_pao_seats = transition.suukantsu_pao_seats
        self._events = transition.events
        self._revision += 1

    def _validate_revision(self, expected_revision: int) -> None:
        if expected_revision != self._revision:
            raise StaleActionError(
                "action was derived from revision "
                f"{expected_revision} but the round is at revision {self._revision}"
            )

    def _validate_invariants(self, transition: _Transition) -> None:
        self._validate_tile_ownership(transition)
        self._validate_phase_consistency(transition)
        self._validate_pending_facts(transition)
        self._validate_seat_states(transition)

    def _validate_tile_ownership(self, transition: _Transition) -> None:
        """物理牌の重複・消失がないことをownershipで確認する。

        「どのobjectを通しても物理牌IDが1回しか現れない」ことは、河の
        historical discardと鳴きmeldが同じ牌を参照した時点で破綻するため、
        公開contractにしない。ここでは山・手牌・河（未鳴き）・meldという
        ownershipの重複と消失だけを検証する。
        """
        owned_tile_ids = [
            tile.id
            for tile in (
                *transition.wall.remaining_tiles,
                *transition.wall.dead_wall_tiles,
            )
        ]
        for player in transition.players.values():
            owned_tile_ids.extend(player.owned_tile_ids)

        if len(set(owned_tile_ids)) != len(owned_tile_ids):
            raise RoundInvariantError("a physical tile is owned more than once")
        if set(owned_tile_ids) != self._tile_ids:
            raise RoundInvariantError("physical tiles were created or lost")

    def _validate_phase_consistency(self, transition: _Transition) -> None:
        phase = transition.phase
        expects_current_seat = phase in _CURRENT_SEAT_PHASES
        if expects_current_seat and transition.current_seat is None:
            raise RoundInvariantError(f"{phase.value} requires a current seat")
        if not expects_current_seat and transition.current_seat is not None:
            raise RoundInvariantError(f"{phase.value} must not have a current seat")

        if transition.drawn_tile_id is not None:
            # drawn tileがあれば必ず`_DRAWN_TILE_HOLDING_PHASES`のいずれかで
            # ある、という片方向の含意だけを検証する。逆方向（それらの
            # phaseなら必ずdrawn tileがある）は要求しない。鳴き成立後の
            # 打牌はツモを伴わない正常なAWAITING_DISCARDだからである。
            if phase not in _DRAWN_TILE_HOLDING_PHASES:
                raise RoundInvariantError(
                    "a drawn tile reference can only be held while awaiting a "
                    "discard or a kakan/ankan reaction"
                )
            if all(
                tile.id != transition.drawn_tile_id
                for tile in transition.players[transition.current_seat].hand_tiles
            ):
                raise RoundInvariantError(
                    "the drawn tile must be owned by the current hand"
                )
        if (transition.drawn_tile_source is not None) is not (
            transition.drawn_tile_id is not None
        ):
            raise RoundInvariantError("a drawn tile and its source are held together")

    def _validate_pending_facts(self, transition: _Transition) -> None:
        phase = transition.phase
        has_pending_discard = transition.pending_discard is not None
        if has_pending_discard is not (transition.pending_discarder is not None):
            raise RoundInvariantError(
                "a pending discard and its discarder are held together"
            )
        if has_pending_discard is not (phase is RoundPhase.AWAITING_REACTIONS):
            raise RoundInvariantError(
                "a pending discard is held exactly while awaiting reactions"
            )
        if has_pending_discard is not (transition.pending_discard_source is not None):
            raise RoundInvariantError(
                "a pending discard and its draw source are held together"
            )

        for pending, pending_phase, description in (
            (
                transition.pending_kakan,
                RoundPhase.AWAITING_KAKAN_REACTIONS,
                "kakan",
            ),
            (
                transition.pending_ankan,
                RoundPhase.AWAITING_ANKAN_REACTIONS,
                "ankan",
            ),
        ):
            if (pending is not None) is not (phase is pending_phase):
                raise RoundInvariantError(
                    f"a pending {description} is held exactly while awaiting "
                    f"its reactions"
                )
            if pending is not None and pending.seat is not transition.current_seat:
                raise RoundInvariantError(
                    f"the pending {description} must belong to the current seat"
                )

        if (transition.pending_ron_resolution is not None) is not (
            phase is RoundPhase.AWAITING_WIN_FINALIZATION
        ):
            raise RoundInvariantError(
                "a pending ron resolution is held exactly while awaiting "
                "win finalization"
            )
        if (
            transition.pending_riichi_declaration is not None
            and phase is not RoundPhase.AWAITING_REACTIONS
        ):
            raise RoundInvariantError(
                "a pending riichi declaration is only held while awaiting reactions"
            )

    @staticmethod
    def _validate_seat_states(transition: _Transition) -> None:
        for player in transition.players.values():
            if player.is_riichi_established and not player.is_menzen:
                raise RoundInvariantError(
                    "an established riichi requires a menzen hand"
                )

    @staticmethod
    def _validate_seat(seat: Seat) -> None:
        if not isinstance(seat, Seat):
            raise TypeError("seat must be a Seat")

    @staticmethod
    def _seat_order_from(first_seat: Seat) -> tuple[Seat, ...]:
        start = _SEAT_ORDER.index(first_seat)
        return tuple(
            _SEAT_ORDER[(start + offset) % len(_SEAT_ORDER)]
            for offset in range(len(_SEAT_ORDER))
        )


def _normalize_round_start_points(
    round_start_points: Mapping[Seat, int],
) -> dict[Seat, int]:
    """局開始時点の持ち点snapshotを検証し、防御的にコピーする。

    暗黙の既定値（配給原点へのfallback等）は用意しない。callerが渡し
    忘れた場合に、実際は立直できない点数の席を合法と判定するsilent
    failureを避けるためである。
    """
    if not isinstance(round_start_points, Mapping):
        raise TypeError("round_start_points must be a mapping keyed by seat")
    if any(not isinstance(seat, Seat) for seat in round_start_points):
        raise TypeError("round_start_points must be keyed by Seat values")
    if any(type(points) is not int for points in round_start_points.values()):
        raise TypeError("round_start_points must contain only ints")

    missing = tuple(seat for seat in _SEAT_ORDER if seat not in round_start_points)
    if missing:
        raise ValueError("round_start_points must contain every seat")
    return {seat: round_start_points[seat] for seat in _SEAT_ORDER}
