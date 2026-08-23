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
成立者が確定した局面は`AWAITING_WIN_FINALIZATION`へ進み、明示的な
`finalize_pending_win()`がscoringと終局commitを行う。ツモも合法手として
strictに再評価してから同じterminal commitを使う。

立直は「立直を選ぶ」と「宣言牌を打つ」の2つの独立したdecisionである。
`RiichiLegalAction`の適用は`AWAITING_RIICHI_DISCARD`へ進むだけで、手牌・
河・drawn tile・供託・立直成立のいずれも変更しない。`RiichiDeclaration`
は従来どおり宣言牌を打った時点で確定する事実であり、その打牌から既存の
反応・成立judgement pathへ接続する。engineがselectorの代わりに宣言牌を
選ぶことはない。

九種九牌はplayerが選択したときだけ`AbortiveDrawResult`へ終局するturn
actionとして扱う。四風連打・四家立直・四槓散了・荒牌流局は、成立timing
（reaction windowの解決後、または槓の実際の確定直後）でだけ自動判定し、
`draw_resolution`のpure判定関数へ委譲する。判定logicそのものは本module
へ複製しない。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from lisjong_engine.discard import Discard
from lisjong_engine.draw_resolution import (
    build_exhaustive_draw_result,
    first_discard_abortive_draw,
    four_kans_abortive_draw,
)
from lisjong_engine.furiten import FuritenReason
from lisjong_engine.kan import PendingAnkan, PendingKakan, count_quads
from lisjong_engine.legal_action import (
    AnkanLegalAction,
    DiscardLegalAction,
    KakanLegalAction,
    LegalAction,
    LegalActionSnapshot,
    NineTerminalsLegalAction,
    ReactionOrigin,
    RiichiLegalAction,
    TsumoLegalAction,
    is_legal_action,
)
from lisjong_engine.legal_actions import (
    RoundView,
    derive_legal_actions,
    derive_nine_terminals_eligibility,
    derive_riichi_discard_tiles,
    derive_tsumo_claim,
    dora_indicator_state,
)
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
    RoundEndedEvent,
    RoundEventSnapshot,
    RoundStartedEvent,
    TileDiscardedEvent,
    TileDrawnEvent,
    TilesDealtEvent,
)
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.round_result import (
    AbortiveDrawReason,
    AbortiveDrawResult,
    RoundResult,
)
from lisjong_engine.rules import KanDoraRevealPolicy, RuleSet
from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile
from lisjong_engine.wall import Wall
from lisjong_engine.win_context import RiichiStatus, WinMethod, WinOrigin
from lisjong_engine.wind import Wind
from lisjong_engine.winning_finalization import WinningClaim, build_win_result
from lisjong_engine.yaku import Yaku

_SEAT_ORDER = tuple(Seat)
_DEAL_BLOCK_SIZE = 4
_DEAL_BLOCK_COUNT = 3

# drawn tileを保持できるphase。加槓・暗槓は打牌前の`AWAITING_DISCARD`から
# 宣言し、槍槓reactionを待つ間もそのturnのdrawn tileを保持し続ける。加槓・
# 暗槓の成立が確定した時点で初めてdrawn tileをclearし`AWAITING_RINSHAN_DRAW`
# へ進む。
_DRAWN_TILE_HOLDING_PHASES = (
    RoundPhase.AWAITING_DISCARD,
    RoundPhase.AWAITING_RIICHI_DISCARD,
    RoundPhase.AWAITING_KAKAN_REACTIONS,
    RoundPhase.AWAITING_ANKAN_REACTIONS,
)

# 現在seatを持つphase。加槓・暗槓の反応待ちでは、宣言した席をcurrent seat
# として保持したまま他家の槍槓を待つ。
_CURRENT_SEAT_PHASES = (
    RoundPhase.AWAITING_DRAW,
    RoundPhase.AWAITING_DISCARD,
    RoundPhase.AWAITING_RIICHI_DISCARD,
    RoundPhase.AWAITING_RINSHAN_DRAW,
    RoundPhase.AWAITING_KAKAN_REACTIONS,
    RoundPhase.AWAITING_ANKAN_REACTIONS,
)

_REACTION_PHASES = (
    RoundPhase.AWAITING_REACTIONS,
    RoundPhase.AWAITING_KAKAN_REACTIONS,
    RoundPhase.AWAITING_ANKAN_REACTIONS,
)

_TURN_ACTION_TYPES = (
    DiscardLegalAction,
    RiichiLegalAction,
    AnkanLegalAction,
    KakanLegalAction,
    TsumoLegalAction,
    NineTerminalsLegalAction,
)


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
    # 保留中の打牌の直前にどこからツモったか。鳴き成立直後のツモを伴わない
    # 打牌ではNoneになる。
    pending_discard_source: DrawSource | None
    pending_kakan: PendingKakan | None
    pending_ankan: PendingAnkan | None
    pending_riichi_declaration: RiichiDeclaration | None
    pending_ron_resolution: PendingRonResolution | None
    pending_kan_dora_reveals: tuple[Seat, ...]
    riichi_finalizations: tuple[RiichiDeclarationFinalization, ...]
    suukantsu_pao_seats: dict[Seat, Seat]
    events: RoundEventSnapshot
    result: RoundResult | None


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
        self._result: RoundResult | None = None
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
    def pending_discard_source(self) -> DrawSource | None:
        """反応待ちの打牌が、直前のどのツモから出たかを表す補助的な事実。

        ```text
        LIVE_WALL  通常のツモ後の打牌
        RINSHAN    嶺上ツモ後の打牌
        None       鳴き成立直後など、ツモを伴わない打牌
        ```

        河底ロンの判定はこの値が`LIVE_WALL`かつ山が尽きている場合だけで
        あり、`None`を`LIVE_WALL`へ補完したり、より前のツモ元から推測したり
        しない。
        """
        return self._pending_discard_source

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
        """公開を保留している槓ドラの、原因となった大明槓の宣言者。

        `KanDoraRevealPolicy.DELAY_OPEN_KAN_DORA`のとき、大明槓の槓ドラは
        直後の打牌がロン以外で解決するまで公開しない。暗槓と加槓は成立が
        確定した時点で公開するため、ここへ積まれることはない。
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
    def _suukantsu_pao_enabled(self) -> bool:
        """このルールで四槓子の責任払いが成立し得るかを返す。

        パオの対象役は`RuleSet`の設定値であり、既定のルールセットは大三元と
        大四喜だけを対象にする。四槓子を対象へ含めるかどうかをmechanics側で
        推測せず、必ず`pao_enabled`と`pao_yaku`へ従う。
        """
        return self._rules.pao_enabled and Yaku.SUUKANTSU in self._rules.pao_yaku

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

    @property
    def result(self) -> RoundResult | None:
        return self._result

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

        記録するのは責任払いが実際に成立する場合だけであり、
        `RuleSet.pao_enabled`と`pao_yaku`が四槓子を対象にしていなければ、
        4つ目の槓子が大明槓で確定してもNoneのままになる。
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
            # `LegalAction`の全variantは反応actionかturn actionのいずれかで
            # あり、現状は両方とも遷移を持つ。将来unionへ新しいvariantが
            # 追加された場合に、暗黙のpassやfallbackを作らずfail closedで
            # 拒否するための防御的な分岐として維持する。
            raise IllegalActionError(
                f"{type(action).__name__} is not supported by this round state"
            )
        if action not in self.legal_actions(seat).actions:
            raise IllegalActionError(
                "action is not in the current legal actions for this seat"
            )

        if isinstance(action, DiscardLegalAction):
            self._apply_discard(seat, action)
        elif isinstance(action, RiichiLegalAction):
            self._apply_riichi(seat)
        elif isinstance(action, AnkanLegalAction):
            self._apply_ankan(seat, action)
        elif isinstance(action, KakanLegalAction):
            self._apply_kakan(seat, action)
        elif isinstance(action, TsumoLegalAction):
            self._apply_tsumo(seat)
        else:
            self._apply_nine_terminals(seat)

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

    def finalize_pending_win(self, *, expected_revision: int) -> RoundResult:
        """E2で確定したRon resolutionをstrictに採点して局を終了する。"""
        if type(expected_revision) is not int:
            raise TypeError("expected_revision must be an int")
        self._validate_revision(expected_revision)
        if self._phase is not RoundPhase.AWAITING_WIN_FINALIZATION:
            raise IllegalOperationError(
                "win finalization is only allowed while awaiting it"
            )
        if self._pending_ron_resolution is None:
            raise RoundInvariantError("the pending ron resolution is missing")

        transition = self._begin()
        pending = transition.pending_ron_resolution
        if pending is None:
            raise RoundInvariantError("the pending ron resolution is missing")

        if (
            self._rules.triple_ron_abortive_draw
            and len(pending.resolution.ron_selected_seats) == 3
        ):
            result: RoundResult = AbortiveDrawResult(AbortiveDrawReason.TRIPLE_RON)
        else:
            claims = tuple(
                self._ron_claim(transition, pending, seat)
                for seat in pending.resolution.ron_awarded_seats
            )
            result = build_win_result(
                claims,
                dora_indicator_state(self._transition_view(transition)),
                self._rules,
                source_seat=pending.source_seat,
            )

        self._finish_round(transition, result)
        self._commit(transition)
        return result

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

    def _apply_tsumo(self, seat: Seat) -> None:
        """ツモactionをstrictに再評価し、成功時だけterminal commitする。"""
        transition = self._begin()
        view = self._transition_view(transition)
        claim = derive_tsumo_claim(view, seat)
        if claim is None:
            raise RoundInvariantError("a tsumo action requires a current drawn tile")
        result = build_win_result(
            (claim,),
            dora_indicator_state(view),
            self._rules,
        )
        self._finish_round(transition, result)
        self._commit(transition)

    def _apply_nine_terminals(self, seat: Seat) -> None:
        """九種九牌をstrictに再評価し、成功時だけterminal commitする。

        callerの選択であり、engineが自動的に流局を選ぶことはない。
        """
        transition = self._begin()
        view = self._transition_view(transition)
        if not derive_nine_terminals_eligibility(view, seat):
            raise RoundInvariantError(
                "nine terminals abortive draw is no longer eligible"
            )
        result = AbortiveDrawResult(AbortiveDrawReason.NINE_TERMINALS)
        self._finish_round(transition, result)
        self._commit(transition)

    def _apply_riichi(self, seat: Seat) -> None:
        """立直の選択だけをcommitし、宣言牌decisionへ進める。

        この時点では宣言牌が確定していないため、手牌・河・drawn tile・
        供託・立直成立のいずれも変更せず、`RiichiDeclaration`も作らない。
        `RiichiDeclaration`は宣言牌を打った時点で確定する事実である。
        """
        transition = self._begin()
        if not derive_riichi_discard_tiles(self._transition_view(transition), seat):
            # 合法な宣言牌が存在しない`AWAITING_RIICHI_DISCARD`は正常状態
            # として許容しない。
            raise RoundInvariantError(
                "a riichi selection requires at least one declaration discard"
            )
        transition.phase = RoundPhase.AWAITING_RIICHI_DISCARD
        self._commit(transition)

    def _apply_discard(self, seat: Seat, action: DiscardLegalAction) -> None:
        transition = self._begin()
        player = transition.players[seat]
        # 宣言牌かどうかは、この打牌がどのdecisionで選ばれたかで決まる。
        declares_riichi = self._phase is RoundPhase.AWAITING_RIICHI_DISCARD
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
            self._finish_discard_without_ron(transition, discarder=seat)

        self._commit(transition)

    def _apply_ankan(self, seat: Seat, action: AnkanLegalAction) -> None:
        transition = self._begin()
        # 副露へ確定させる前に、値としてのAnkanだけを組み立てる。槍槓で
        # 成立しない可能性があるため、この時点では手牌を減らさない。
        ankan = transition.players[seat].copy().declare_ankan(action.tile_ids)
        pending = PendingAnkan(seat, ankan)
        # 一発を消すのは槓の宣言ではなく成立である。槍槓で暗槓が流れた場合、
        # その槓は無かったことになるため一発windowも維持する。
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
        # 一発を消すのは槓の宣言ではなく成立である。槍槓で加槓が流れた場合、
        # 和了者は`RIICHI + IPPATSU + CHANKAN`のまま和了できる。
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
            if not resolution.is_ron and not resolution.is_call:
                # 反応windowが荒牌流局・四風連打・四家立直それぞれの成立
                # timingを兼ねる。立直成立の確定より後でなければならない。
                self._finish_discard_without_ron(
                    transition, discarder=resolution.source_seat
                )

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

    def _ron_claim(
        self,
        transition: _Transition,
        pending: PendingRonResolution,
        seat: Seat,
    ) -> WinningClaim:
        """E2のawarded seatとpending provenanceからRon claimを構築する。"""
        origins = {
            ReactionOrigin.DISCARD: WinOrigin.DISCARD,
            ReactionOrigin.KAKAN: WinOrigin.KAKAN,
            ReactionOrigin.ANKAN: WinOrigin.ANKAN,
        }
        player = transition.players[seat]
        return WinningClaim(
            seat=seat,
            concealed_tiles=player.hand_tiles,
            winning_tile=pending.target_tile,
            method=WinMethod.RON,
            origin=origins[pending.origin],
            seat_wind=self.seat_wind(seat),
            prevailing_wind=self._prevailing_wind,
            declared_melds=player.melds,
            riichi_status=player.riichi_status,
            is_ippatsu=player.is_ippatsu,
            is_last_tile=pending.is_last_tile,
            suukantsu_pao_seat=transition.suukantsu_pao_seats.get(seat),
        )

    @staticmethod
    def _finish_round(transition: _Transition, result: RoundResult) -> None:
        """result/event/cleanup/FINISHEDをworking copyへ一度だけ構築する。"""
        if transition.result is not None:
            raise RoundInvariantError("the round already has a result")
        if any(isinstance(event, RoundEndedEvent) for event in transition.events):
            raise RoundInvariantError("the round already has a terminal event")

        transition.result = result
        transition.current_seat = None
        transition.drawn_tile_id = None
        transition.drawn_tile_source = None
        transition.pending_discarder = None
        transition.pending_discard = None
        transition.pending_discard_source = None
        transition.pending_kakan = None
        transition.pending_ankan = None
        transition.pending_riichi_declaration = None
        transition.pending_ron_resolution = None
        transition.pending_kan_dora_reveals = ()
        transition.phase = RoundPhase.FINISHED
        transition.events = transition.events.appended((RoundEndedEvent(result),))

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
            if completes_four_kans and self._suukantsu_pao_enabled:
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
            # ただし槓ドラの公開タイミングだけは`KanDoraRevealPolicy`に従う。
            new_events.append(KanConfirmedEvent(seat, meld))
            new_events.extend(self._confirm_daiminkan_dora(transition, seat))
            transition.phase = RoundPhase.AWAITING_RINSHAN_DRAW
            transition.events = transition.events.appended(new_events)
            self._finish_four_kans_if_applicable(transition)
            return
        # 鳴き後の打牌はツモを伴わないため、drawn tileのない
        # `AWAITING_DISCARD`が正常状態である。
        transition.phase = RoundPhase.AWAITING_DISCARD
        transition.events = transition.events.appended(new_events)

    def _finish_discard_without_ron(
        self,
        transition: _Transition,
        *,
        discarder: Seat,
    ) -> None:
        """打牌がロン・鳴きなしで解決した直後の共通後処理。

        reaction不要のfast pathと、explicit all-passの両方がここを通る。
        呼び出し前に、保留槓ドラの解放と立直確定を済ませておくこと。

        次のツモへ進めるか、荒牌流局・四風連打・四家立直として終局するか
        をここで一箇所にまとめ、判定logicを二重実装しない。
        """
        transition.phase = RoundPhase.AWAITING_DRAW
        transition.current_seat = discarder.next()
        transition.pending_discarder = None
        transition.pending_discard = None
        transition.pending_discard_source = None

        if transition.wall.remaining_count == 0:
            # 最後のlive-wall牌の打牌に対する反応windowが、Ronなしで
            # 解決した後にだけ荒牌流局を確定する。海底ツモ・河底ロンの
            # 機会が終わるまでは、live wallが尽きただけで終局しない。
            result = build_exhaustive_draw_result(
                tenpai_by_seat={
                    seat: bool(transition.players[seat].winning_tile_types)
                    for seat in _SEAT_ORDER
                },
                discards_by_seat={
                    seat: transition.players[seat].discards for seat in _SEAT_ORDER
                },
                nagashi_mangan_enabled=self._rules.nagashi_mangan_enabled,
            )
            self._finish_round(transition, result)
            return

        abortive = first_discard_abortive_draw(
            four_winds_enabled=self._rules.four_winds_abortive_draw_enabled,
            four_riichi_enabled=self._rules.four_riichi_abortive_draw_enabled,
            has_meld_occurred=any(
                transition.players[seat].melds for seat in _SEAT_ORDER
            ),
            discard_tile_types_by_seat={
                seat: tuple(
                    discard.tile.tile_type
                    for discard in transition.players[seat].discards
                )
                for seat in _SEAT_ORDER
            },
            riichi_established_by_seat={
                seat: transition.players[seat].is_riichi_established
                for seat in _SEAT_ORDER
            },
        )
        if abortive is not None:
            self._finish_round(transition, abortive)

    def _finish_four_kans_if_applicable(self, transition: _Transition) -> None:
        """槓が実際に確定した直後に四槓散了を判定する。

        `_finish_round`が槍槓で流れた未成立の槓を数えないことは、この
        methodが成立済みmeld（`transition.players[*].melds`）だけを
        参照することで自然に満たされる。
        """
        result = four_kans_abortive_draw(
            enabled=self._rules.four_kans_abortive_draw_enabled,
            quad_counts_by_seat={
                seat: count_quads(transition.players[seat].melds)
                for seat in _SEAT_ORDER
            },
        )
        if result is not None:
            self._finish_round(transition, result)

    def _confirm_kakan(
        self,
        transition: _Transition,
        seat: Seat,
        kakan: Kakan,
    ) -> None:
        committed = transition.players[seat].declare_kakan(kakan.added_tile.id)
        if committed != kakan:
            raise RoundInvariantError("the pending kakan no longer matches the hand")

        # 加槓の公開は、槍槓が全員パスして成立が確定したこの時点で行う。
        # `DELAY_OPEN_KAN_DORA`の「遅延」は槍槓の解決までを指すため、
        # 大明槓のように次の打牌までは待たない。槍槓が成立した場合は加槓
        # 自体が成立せず、この経路へ到達しない。
        self._cancel_all_ippatsu(transition)
        transition.drawn_tile_id = None
        transition.drawn_tile_source = None
        transition.current_seat = seat
        transition.phase = RoundPhase.AWAITING_RINSHAN_DRAW
        transition.events = transition.events.appended(
            (
                KanConfirmedEvent(seat, committed),
                *self._reveal_kan_dora(transition, seat),
            )
        )
        self._finish_four_kans_if_applicable(transition)

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
        self._cancel_all_ippatsu(transition)
        transition.drawn_tile_id = None
        transition.drawn_tile_source = None
        transition.current_seat = seat
        transition.phase = RoundPhase.AWAITING_RINSHAN_DRAW
        transition.events = transition.events.appended(
            (
                KanConfirmedEvent(seat, committed),
                *self._reveal_kan_dora(transition, seat),
            )
        )
        self._finish_four_kans_if_applicable(transition)

    @staticmethod
    def _reveal_kan_dora(
        transition: _Transition,
        seat: Seat,
    ) -> tuple[DoraIndicatorRevealedEvent, ...]:
        """槓ドラ表示牌を直ちに1枚公開する。"""
        indicator = transition.wall.reveal_kan_dora()
        return (DoraIndicatorRevealedEvent(seat, indicator),)

    def _confirm_daiminkan_dora(
        self,
        transition: _Transition,
        seat: Seat,
    ) -> tuple[DoraIndicatorRevealedEvent, ...]:
        """大明槓の槓ドラ公開を`KanDoraRevealPolicy`へ従わせる。

        大明槓は成立と同時に確定するが、`DELAY_OPEN_KAN_DORA`では直後の
        打牌がロン以外で解決するまで公開を保留する。3種類の槓のうち、この
        policyで公開タイミングが変わるのは大明槓だけである。

        ```text
        Ankan      policy対象外。成立と同時に公開する
        Kakan      槍槓が全員パスした時点で公開する（policyによらない）
        Daiminkan  IMMEDIATE: 成立時 / DELAY: 直後の打牌がロン以外で解決した時
        ```
        """
        if (
            self._rules.kan_dora_reveal_policy
            is KanDoraRevealPolicy.IMMEDIATE_ON_KAN_CONFIRMATION
        ):
            return self._reveal_kan_dora(transition, seat)
        transition.pending_kan_dora_reveals = (
            *transition.pending_kan_dora_reveals,
            seat,
        )
        return ()

    def _release_pending_kan_dora(self, transition: _Transition) -> None:
        """保留していた大明槓の槓ドラを、まとめて公開する。"""
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
        """成立した割り込みにより、全席の一発windowを終了する。

        一発を消すのは「宣言」ではなく「成立」である。

        ```text
        Chi / Pon / Daiminkan  成立時に終了
        Kakan / Ankan          槍槓が解決して成立が確定した時点で終了
        槍槓で流れたKakan/Ankan 成立していないため一発を維持する
        ```

        立直した席自身の次の打牌による自然失効は`_apply_discard()`が扱う。
        """
        for player in transition.players.values():
            player.cancel_ippatsu()

    def _committed_view(self) -> RoundView:
        return self._build_view(
            players=self._players,
            phase=self._phase,
            current_seat=self._current_seat,
            drawn_tile_id=self._drawn_tile_id,
            drawn_tile_source=self._drawn_tile_source,
            remaining_count=self._wall.remaining_count,
            can_draw_rinshan=self._wall.can_draw_rinshan,
            pending_discarder=self._pending_discarder,
            pending_discard=self._pending_discard,
            pending_discard_source=self._pending_discard_source,
            pending_kakan=self._pending_kakan,
            pending_ankan=self._pending_ankan,
            wall=self._wall,
            pending_kan_dora_reveals=self._pending_kan_dora_reveals,
            suukantsu_pao_seats=self._suukantsu_pao_seats,
        )

    def _transition_view(self, transition: _Transition) -> RoundView:
        return self._build_view(
            players=transition.players,
            phase=transition.phase,
            current_seat=transition.current_seat,
            drawn_tile_id=transition.drawn_tile_id,
            drawn_tile_source=transition.drawn_tile_source,
            remaining_count=transition.wall.remaining_count,
            can_draw_rinshan=transition.wall.can_draw_rinshan,
            pending_discarder=transition.pending_discarder,
            pending_discard=transition.pending_discard,
            pending_discard_source=transition.pending_discard_source,
            pending_kakan=transition.pending_kakan,
            pending_ankan=transition.pending_ankan,
            wall=transition.wall,
            pending_kan_dora_reveals=transition.pending_kan_dora_reveals,
            suukantsu_pao_seats=transition.suukantsu_pao_seats,
        )

    def _build_view(self, *, wall: Wall, **fields) -> RoundView:
        return RoundView(
            seat_winds={seat: self.seat_wind(seat) for seat in _SEAT_ORDER},
            prevailing_wind=self._prevailing_wind,
            rules=self._rules,
            round_start_points=self._round_start_points,
            dora_indicator_tiles=wall.dora_indicator_tiles,
            ura_dora_indicator_tiles=wall.ura_dora_indicator_tiles,
            revealed_dora_indicator_count=wall.revealed_dora_indicator_count,
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
            result=self._result,
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
        self._result = transition.result
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
        self._validate_terminal_state(transition)

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
        # `pending_discard_source`は「その打牌の直前にどこからツモったか」と
        # いう補助的なprovenanceであり、すべての打牌がツモを伴うわけでは
        # ない。鳴き成立直後のツモなし打牌ではNoneが正常値である。したがって
        # pending discardの存在条件とsourceの存在条件を同一にせず、sourceが
        # あるならその打牌も保持されている、という片方向の含意だけを検証する。
        if transition.pending_discard_source is not None and not has_pending_discard:
            raise RoundInvariantError(
                "a pending draw source requires the pending discard it came from"
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
    def _validate_terminal_state(transition: _Transition) -> None:
        terminal_events = tuple(
            event for event in transition.events if isinstance(event, RoundEndedEvent)
        )
        if transition.phase is not RoundPhase.FINISHED:
            if transition.result is not None:
                raise RoundInvariantError("a non-finished round must not have a result")
            if terminal_events:
                raise RoundInvariantError(
                    "a non-finished round must not have a terminal event"
                )
            return

        if transition.result is None:
            raise RoundInvariantError("a finished round requires a result")
        if len(terminal_events) != 1:
            raise RoundInvariantError(
                "a finished round requires exactly one terminal event"
            )
        terminal_event = terminal_events[0]
        if terminal_event.result != transition.result:
            raise RoundInvariantError("the terminal event must match the round result")
        if transition.events[-1] is not terminal_event:
            raise RoundInvariantError("the terminal event must be the last event")

        pending_values = (
            transition.current_seat,
            transition.drawn_tile_id,
            transition.drawn_tile_source,
            transition.pending_discarder,
            transition.pending_discard,
            transition.pending_discard_source,
            transition.pending_kakan,
            transition.pending_ankan,
            transition.pending_riichi_declaration,
            transition.pending_ron_resolution,
        )
        if any(value is not None for value in pending_values):
            raise RoundInvariantError("a finished round must not retain pending state")
        if transition.pending_kan_dora_reveals:
            raise RoundInvariantError(
                "a finished round must not retain pending kan dora reveals"
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
