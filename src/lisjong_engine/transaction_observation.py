"""成功したengine transactionの内部semantic stepを取り出すprivileged観測contract。

既存のdelivery境界（`RoundProgressFact`、`RoundEvidenceCompletion`、
`SelectorDecisionCommit`）は、成功transaction後のplayer-safeな結果だけを
渡す。1つのtransactionの中では、打牌→反応不要の解決→立直成立や、
反応解決→加槓成立のように複数のsemantic stepが進むため、最終状態だけ
では「どの順で何が起きたか」を検証できない。

本moduleは、その順序を外部の記録用途（学習用sourceのproducer等）へ渡す
ための**opt-inのprivileged** valueだけを定義する。

```text
RoundState.enable_transaction_observation()
    -> 以後の成功transactionごとに TransactionStep を順に保持
    -> run_hanchan(on_transaction_observation=...) が TransactionObservation を渡す
```

## 情報境界

`RoundCheckpoint`は全席の手牌・ツモ牌・副露・河・見逃し理由・成立立直・
一発を含む。これはどの席に対してもplayer-safeではない。Policy・selector・
`on_delivery`等のplayer-safe deliveryへ渡してはならない。

山の残り牌の並び、未公開の表示牌・裏表示牌・嶺上牌、乱数状態は含めない。
公開済みのドラ表示牌と、山・嶺上の残り枚数だけを持つ。

## transactionとstep

- step列は1つの成功transactionの内部順序であり、各stepの`checkpoint`は
  selector時点の独立snapshotではない。selector入力は従来どおり
  `SelectorDecision.observation`である。
- 失敗したtransactionのstepは保持も配信もしない。
- transactionが追加した`RoundEvent`は、欠落・重複なくいずれかのstepの
  `events`に属する。
- 最後のstepの`checkpoint`は、commit後の盤面（phase・current seatを除く）と
  一致する。commit後のphase・current seatは`TransactionObservation`が持つ。
"""

from dataclasses import dataclass
from enum import Enum

from lisjong_engine.discard import Discard
from lisjong_engine.furiten import FuritenReason
from lisjong_engine.kan import PendingAnkan, PendingKakan
from lisjong_engine.meld import Meld
from lisjong_engine.riichi_event import (
    RiichiDeclaration,
    RiichiDeclarationFinalization,
)
from lisjong_engine.round_event import DrawSource, RoundEvent
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.seat import Seat
from lisjong_engine.selector_decision import SelectorDecisionCommit
from lisjong_engine.tile import Tile
from lisjong_engine.win_context import RiichiStatus
from lisjong_engine.wind import Wind


class TransactionStepKind(Enum):
    """transaction内のsemantic step。

    ```text
    ROUND_STARTED            配牌済みの開始状態
    DRAW                     通常ツモ・嶺上ツモ（同巡見逃しの解除を含む）
    TURN_CHOICE              打牌・立直選択・槓宣言・ツモ和了・九種九牌の適用
    REACTION_WINDOW_SKIPPED  反応windowを開かずに解決した打牌・暗槓（機会なし）
    REACTION_RESOLVED        明示的な反応windowの解決（見逃し・鳴き・ロン確定）
    KAN_CONFIRMED            加槓・暗槓の成立（大明槓はREACTION_RESOLVEDに含む）
    RIICHI_FINALIZED         宣言牌への反応解決による立直の成立・不成立
    ROUND_ENDED              終局結果（精算前の終端状態）
    ```
    """

    ROUND_STARTED = "round_started"
    DRAW = "draw"
    TURN_CHOICE = "turn_choice"
    REACTION_WINDOW_SKIPPED = "reaction_window_skipped"
    REACTION_RESOLVED = "reaction_resolved"
    KAN_CONFIRMED = "kan_confirmed"
    RIICHI_FINALIZED = "riichi_finalized"
    ROUND_ENDED = "round_ended"


@dataclass(frozen=True, kw_only=True)
class SeatCheckpoint:
    """1席の盤面と局内席state。`hand_tiles`はツモ牌を含む。"""

    seat: Seat
    seat_wind: Wind
    hand_tiles: tuple[Tile, ...]
    drawn_tile: Tile | None
    drawn_tile_source: DrawSource | None
    discards: tuple[Discard, ...]
    melds: tuple[Meld, ...]
    riichi_status: RiichiStatus
    is_ippatsu: bool
    # 見逃しによるフリテン理由（TEMPORARY / RIICHI）。河由来のフリテンは
    # `discards`から導出できるため保持しない。
    missed_ron_furiten: FuritenReason | None

    def __post_init__(self) -> None:
        if (self.drawn_tile is None) is not (self.drawn_tile_source is None):
            raise ValueError("drawn_tile and drawn_tile_source must be set together")
        if self.drawn_tile is not None and self.drawn_tile not in self.hand_tiles:
            raise ValueError("drawn_tile must be owned by hand_tiles")


@dataclass(frozen=True, kw_only=True)
class RoundCheckpoint:
    """step時点の全席の盤面と公開round情報（privileged）。"""

    dealer_seat: Seat
    prevailing_wind: Wind
    live_tiles_remaining: int
    rinshan_tiles_remaining: int
    revealed_dora_indicators: tuple[Tile, ...]
    seats: tuple[SeatCheckpoint, ...]
    # 宣言牌への反応が未解決の立直宣言。
    pending_riichi_declaration: RiichiDeclaration | None
    # 宣言済みで、槍槓の解決を待つ加槓・暗槓。
    pending_kakan: PendingKakan | None
    pending_ankan: PendingAnkan | None
    riichi_finalizations: tuple[RiichiDeclarationFinalization, ...]

    def __post_init__(self) -> None:
        if tuple(seat.seat for seat in self.seats) != tuple(Seat):
            raise ValueError("seats must contain every seat in seat order")


@dataclass(frozen=True)
class TransactionStep:
    kind: TransactionStepKind
    # このstepで追加された`RoundEvent`（反応不要の解決等では空）。
    events: tuple[RoundEvent, ...]
    checkpoint: RoundCheckpoint

    def __post_init__(self) -> None:
        if not isinstance(self.kind, TransactionStepKind):
            raise TypeError("kind must be a TransactionStepKind")
        if any(not isinstance(event, RoundEvent) for event in self.events):
            raise TypeError("events must contain only RoundEvent values")
        if not isinstance(self.checkpoint, RoundCheckpoint):
            raise TypeError("checkpoint must be a RoundCheckpoint")


@dataclass(frozen=True, kw_only=True)
class TransactionObservation:
    """1つの成功したround transactionのprivilegedな観測。

    `selector_decision`は、このtransactionへ投入されたselector decision
    （selectorを伴わないツモ・和了確定等ではNone）。`revision`はcommit後の
    `RoundState.revision`、`round_ordinal`は半荘内で何局目か。
    """

    round_ordinal: int
    revision: int
    phase: RoundPhase
    current_seat: Seat | None
    steps: tuple[TransactionStep, ...]
    selector_decision: SelectorDecisionCommit | None

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("a committed transaction has at least one step")
        if any(not isinstance(step, TransactionStep) for step in self.steps):
            raise TypeError("steps must contain only TransactionStep values")
