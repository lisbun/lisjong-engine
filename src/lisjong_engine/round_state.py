"""1局の状態基盤と、pull型core APIを提供する`RoundState`を定義する。

core境界はpull型である。engineはactionを選ばない。

```text
snapshot = state.legal_actions(seat)
chosen = snapshot.actions[0]
state.apply(seat, chosen, expected_revision=snapshot.revision)
```

`RoundState`はmutableだが、`apply()`はtransactionalである。

```text
seat / phase / revision validation
    -> 現在stateから合法手を再導出
    -> action membership validation
    -> working copyへ遷移
    -> invariant validation
    -> 成功時のみ本体へcommit
```

validationまたは遷移が失敗した場合、本体へpartial mutationを残さない。

E1の責務は、局初期化、通常のツモ、通常の打牌、次turnへの進行、および
打牌後に反応windowが必要かの安全な検知までである。反応の解決、鳴き、
立直、槓、フリテンはE2、和了確定、流局、`RoundResult`はE3で実装する。
未実装の経路は暫定fallbackを作らず、fail closedで拒否する。
"""

from dataclasses import dataclass

from lisjong_engine.discard import Discard
from lisjong_engine.legal_action import (
    DiscardLegalAction,
    LegalAction,
    LegalActionSnapshot,
    is_legal_action,
)
from lisjong_engine.legal_actions import derive_legal_actions
from lisjong_engine.meld import Meld
from lisjong_engine.player_state import PlayerState
from lisjong_engine.reaction_boundary import has_possible_reaction
from lisjong_engine.round_event import (
    DrawSource,
    RoundEventSnapshot,
    RoundStartedEvent,
    TileDiscardedEvent,
    TileDrawnEvent,
    TilesDealtEvent,
)
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.rules import RuleSet
from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile
from lisjong_engine.wall import Wall
from lisjong_engine.wind import Wind

_SEAT_ORDER = tuple(Seat)
_DEAL_BLOCK_SIZE = 4
_DEAL_BLOCK_COUNT = 3


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


@dataclass
class _Transition:
    """commit前の遷移結果をまとめて保持するworking copy。"""

    wall: Wall
    players: dict[Seat, PlayerState]
    phase: RoundPhase
    current_seat: Seat | None
    drawn_tile_id: int | None
    pending_discarder: Seat | None
    pending_discard: Discard | None
    events: RoundEventSnapshot


class RoundState:
    def __init__(
        self,
        wall: Wall,
        *,
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
        self._players = {seat: PlayerState(seat) for seat in _SEAT_ORDER}
        self._phase = RoundPhase.UNDEALT
        self._current_seat: Seat | None = None
        self._drawn_tile_id: int | None = None
        self._pending_discarder: Seat | None = None
        self._pending_discard: Discard | None = None
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

    def legal_actions(self, seat: Seat) -> LegalActionSnapshot:
        """`seat`の合法手を、副作用のないimmutable snapshotで返す。

        導出は`legal_actions`moduleのpure関数へ委譲する。本methodは
        現在stateを渡すだけの薄いfacadeである。
        """
        self._validate_seat(seat)
        return LegalActionSnapshot(
            seat=seat,
            phase=self._phase,
            revision=self._revision,
            actions=derive_legal_actions(
                phase=self._phase,
                seat=seat,
                current_seat=self._current_seat,
                hand_tiles=self._players[seat].hand_tiles,
            ),
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

        transition = self._begin()
        tile = transition.wall.draw()
        transition.players[seat].add_tile(tile)
        transition.drawn_tile_id = tile.id
        transition.phase = RoundPhase.AWAITING_DISCARD
        transition.events = transition.events.appended(
            (TileDrawnEvent(seat, tile, DrawSource.LIVE_WALL),)
        )

        self._commit(transition)
        return tile

    def apply(
        self,
        seat: Seat,
        action: LegalAction,
        *,
        expected_revision: int,
    ) -> None:
        """callerが選んだ合法手を適用する。

        `expected_revision`はsnapshot取得時のrevisionである。局の状態が
        1つでも進んでいれば、同じdomain valueのactionが現在も合法かどうか
        に関わらずstaleとして拒否する。

        callerの「さっき合法だった」という主張は信用せず、必ず現在state
        から合法手を再導出して照合する。
        """
        self._validate_seat(seat)
        if not is_legal_action(action):
            raise TypeError("action must be a legal action")
        if type(expected_revision) is not int:
            raise TypeError("expected_revision must be an int")

        if expected_revision != self._revision:
            raise StaleActionError(
                "action was derived from revision "
                f"{expected_revision} but the round is at revision {self._revision}"
            )
        if not isinstance(action, DiscardLegalAction):
            # E2/E3のaction型はvalueとして存在するが、E1の状態機械は遷移を
            # 持たない。暗黙のpassやfallbackを作らず拒否する。
            raise IllegalActionError(
                f"{type(action).__name__} is not supported by this round state"
            )
        if action not in self.legal_actions(seat).actions:
            raise IllegalActionError(
                "action is not in the current legal actions for this seat"
            )

        self._apply_discard(seat, action)

    def _apply_discard(self, seat: Seat, action: DiscardLegalAction) -> None:
        transition = self._begin()
        is_tsumogiri = action.tile_id == self._drawn_tile_id
        discard = transition.players[seat].discard_tile(
            action.tile_id,
            is_tsumogiri=is_tsumogiri,
        )
        transition.drawn_tile_id = None
        transition.events = transition.events.appended(
            (TileDiscardedEvent(seat, discard.tile, discard.is_tsumogiri),)
        )

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
            # 反応候補が存在し得る局面をE1で自動passせず、E2が解決を
            # 実装するまでここで停止する。
            transition.phase = RoundPhase.AWAITING_REACTIONS
            transition.current_seat = None
            transition.pending_discarder = seat
            transition.pending_discard = discard
        else:
            transition.phase = RoundPhase.AWAITING_DRAW
            transition.current_seat = seat.next()
            transition.pending_discarder = None
            transition.pending_discard = None

        self._commit(transition)

    def _begin(self) -> _Transition:
        return _Transition(
            wall=self._wall.copy(),
            players={seat: player.copy() for seat, player in self._players.items()},
            phase=self._phase,
            current_seat=self._current_seat,
            drawn_tile_id=self._drawn_tile_id,
            pending_discarder=self._pending_discarder,
            pending_discard=self._pending_discard,
            events=self._events,
        )

    def _commit(self, transition: _Transition) -> None:
        self._validate_invariants(transition)
        self._wall = transition.wall
        self._players = transition.players
        self._phase = transition.phase
        self._current_seat = transition.current_seat
        self._drawn_tile_id = transition.drawn_tile_id
        self._pending_discarder = transition.pending_discarder
        self._pending_discard = transition.pending_discard
        self._events = transition.events
        self._revision += 1

    def _validate_invariants(self, transition: _Transition) -> None:
        self._validate_tile_ownership(transition)
        self._validate_phase_consistency(transition)

    def _validate_tile_ownership(self, transition: _Transition) -> None:
        """物理牌の重複・消失がないことをownershipで確認する。

        「どのobjectを通しても物理牌IDが1回しか現れない」ことは、E2で河の
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
        # E1が到達するphaseだけでなく、`RoundPhase`が意味として現在seatを
        # 要求するphase全体を対象にする。`AWAITING_RINSHAN_DRAW`はE1では
        # 未到達だが、E2の槓成立後は嶺上牌を引くseatをcurrent seatとして
        # 保持する正常状態であり、ここで一般化して禁止してはならない。
        expects_current_seat = phase in (
            RoundPhase.AWAITING_DRAW,
            RoundPhase.AWAITING_DISCARD,
            RoundPhase.AWAITING_RINSHAN_DRAW,
        )

        if expects_current_seat and transition.current_seat is None:
            raise RoundInvariantError(f"{phase.value} requires a current seat")
        if not expects_current_seat and transition.current_seat is not None:
            raise RoundInvariantError(f"{phase.value} must not have a current seat")

        if transition.drawn_tile_id is not None:
            # drawn tileがあれば必ずAWAITING_DISCARDである、という片方向の
            # 含意だけを検証する。逆方向（AWAITING_DISCARDなら必ずdrawn
            # tileがある）は要求しない。鳴き成立後の打牌はツモを伴わない
            # 正常なAWAITING_DISCARDだからである。
            if phase is not RoundPhase.AWAITING_DISCARD:
                raise RoundInvariantError(
                    "a drawn tile reference can only be held while awaiting a discard"
                )
            if all(
                tile.id != transition.drawn_tile_id
                for tile in transition.players[transition.current_seat].hand_tiles
            ):
                raise RoundInvariantError(
                    "the drawn tile must be owned by the current hand"
                )

        has_pending_discard = transition.pending_discard is not None
        if has_pending_discard is not (transition.pending_discarder is not None):
            raise RoundInvariantError(
                "a pending discard and its discarder are held together"
            )
        if has_pending_discard is not (phase is RoundPhase.AWAITING_REACTIONS):
            raise RoundInvariantError(
                "a pending discard is held exactly while awaiting reactions"
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
