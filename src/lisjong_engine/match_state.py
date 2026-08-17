"""半荘全体を束ねるMatch層のimmutable value objectと初期stateを定義するmodule。

Issue #21（F1）で確定した局精算 / 最終score計算はpure calculationとして
再実装しない。本moduleはF2として、それらのpure APIを後から適切な順序で
呼び出すための「箱」（value objectと初期state）だけを提供する。

局開始・Wall割当・settlement適用・局進行・半荘終了判定は本moduleの責務では
なく、後続段階で追加する。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from lisjong_engine.final_score import FinalScoreCalculation
from lisjong_engine.points import SeatPoints
from lisjong_engine.round_allocation import (
    RoundRandomProvenance,
    create_round_random_provenance,
    create_round_wall,
)
from lisjong_engine.round_result import RoundResult
from lisjong_engine.round_state import RoundState
from lisjong_engine.rules import MatchFormat, RuleSet
from lisjong_engine.seat import Seat
from lisjong_engine.settlement import RiichiStickAward, RoundSettlement
from lisjong_engine.wind import Wind

# F2は4人半荘のみを扱う。北場は対局位置として成立しない。
_SUPPORTED_PREVAILING_WINDS = (Wind.EAST, Wind.SOUTH, Wind.WEST)

# 初期起家をSeat.EASTに固定した場合の、hand numberとdealer seatの対応。
_DEALER_SEAT_BY_HAND_NUMBER = {
    1: Seat.EAST,
    2: Seat.SOUTH,
    3: Seat.WEST,
    4: Seat.NORTH,
}


@dataclass(frozen=True)
class RoundPosition:
    """現在の対局位置を表すimmutableな値。

    `riichi_sticks`は卓上供託の本数であり、player scoreとは別authorityと
    して扱う。
    """

    prevailing_wind: Wind
    hand_number: int
    dealer_seat: Seat
    honba: int
    riichi_sticks: int

    def __post_init__(self) -> None:
        if not isinstance(self.prevailing_wind, Wind):
            raise TypeError("prevailing_wind must be a Wind")
        if self.prevailing_wind not in _SUPPORTED_PREVAILING_WINDS:
            raise ValueError("prevailing_wind must be EAST, SOUTH, or WEST")

        if type(self.hand_number) is not int:
            raise TypeError("hand_number must be an int")
        if not 1 <= self.hand_number <= 4:
            raise ValueError("hand_number must be between 1 and 4")

        if not isinstance(self.dealer_seat, Seat):
            raise TypeError("dealer_seat must be a Seat")

        if type(self.honba) is not int:
            raise TypeError("honba must be an int")
        if self.honba < 0:
            raise ValueError("honba must be non-negative")

        if type(self.riichi_sticks) is not int:
            raise TypeError("riichi_sticks must be an int")
        if self.riichi_sticks < 0:
            raise ValueError("riichi_sticks must be non-negative")

        expected_dealer_seat = _DEALER_SEAT_BY_HAND_NUMBER[self.hand_number]
        if self.dealer_seat is not expected_dealer_seat:
            raise ValueError(
                "dealer_seat must match hand_number under a fixed East start "
                "(hand 1 -> EAST, hand 2 -> SOUTH, hand 3 -> WEST, hand 4 -> NORTH)"
            )


class MatchPhase(Enum):
    AWAITING_ROUND = "awaiting_round"
    ROUND_IN_PROGRESS = "round_in_progress"
    FINISHED = "finished"


class MatchEndReason(Enum):
    """半荘が終了した理由。`RuleSet`の意味へ合わせた名称を使う。

    旧`python-study`の`RETURN_POINTS`（最終score計算専用の概念であり
    match end reasonではない）と`MANUAL`（手動終了API未実装のため
    対応するreasonが存在しない）は移植しない。
    """

    BANKRUPTCY = "bankruptcy"
    DEALER_WIN = "dealer_win"
    DEALER_TENPAI = "dealer_tenpai"
    TARGET_REACHED = "target_reached"
    FINAL_ROUND = "final_round"


@dataclass(frozen=True)
class CompletedRound:
    """1局が終了し精算が確定した後の、監査可能なimmutable記録。

    `next_position`は`RoundPosition | None`であり、`None`はmatch終了により
    実際には開始されない仮想的な次局位置を生成しないことを表す。
    """

    random_provenance: RoundRandomProvenance
    position_before: RoundPosition
    result: RoundResult
    settlement: RoundSettlement
    scores_after_settlement: SeatPoints
    dealer_continues: bool
    next_position: RoundPosition | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.random_provenance, RoundRandomProvenance):
            raise TypeError("random_provenance must be a RoundRandomProvenance")
        if not isinstance(self.position_before, RoundPosition):
            raise TypeError("position_before must be a RoundPosition")
        if not isinstance(self.result, RoundResult):
            raise TypeError("result must be a RoundResult")
        if not isinstance(self.settlement, RoundSettlement):
            raise TypeError("settlement must be a RoundSettlement")
        if not isinstance(self.scores_after_settlement, SeatPoints):
            raise TypeError("scores_after_settlement must be SeatPoints")
        if type(self.dealer_continues) is not bool:
            raise TypeError("dealer_continues must be a bool")
        if self.next_position is not None and not isinstance(
            self.next_position, RoundPosition
        ):
            raise TypeError("next_position must be a RoundPosition or None")


@dataclass(frozen=True)
class CompletedMatch:
    """半荘終了時のimmutableな最終結果。"""

    end_reason: MatchEndReason
    final_riichi_stick_awards: tuple[RiichiStickAward, ...]
    final_raw_scores: SeatPoints
    final_score: FinalScoreCalculation
    history: tuple[CompletedRound, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.end_reason, MatchEndReason):
            raise TypeError("end_reason must be a MatchEndReason")

        try:
            awards = tuple(self.final_riichi_stick_awards)
        except TypeError:
            raise TypeError(
                "final_riichi_stick_awards must be an iterable of "
                "RiichiStickAward values"
            ) from None
        if any(not isinstance(award, RiichiStickAward) for award in awards):
            raise TypeError(
                "final_riichi_stick_awards must contain only RiichiStickAward values"
            )

        if not isinstance(self.final_raw_scores, SeatPoints):
            raise TypeError("final_raw_scores must be SeatPoints")
        if not isinstance(self.final_score, FinalScoreCalculation):
            raise TypeError("final_score must be a FinalScoreCalculation")

        try:
            history = tuple(self.history)
        except TypeError:
            raise TypeError(
                "history must be an iterable of CompletedRound values"
            ) from None
        if any(not isinstance(item, CompletedRound) for item in history):
            raise TypeError("history must contain only CompletedRound values")

        object.__setattr__(self, "final_riichi_stick_awards", awards)
        object.__setattr__(self, "history", history)


class MatchState:
    """半荘全体のauthoritativeな状態。

    今回の段階では初期化して read-only に参照できるところまでを実装する。
    局開始・Wall割当・settlement適用・局進行・半荘終了判定は後続段階の
    責務であり、ここでは行わない。
    """

    def __init__(
        self,
        *,
        seed: int,
        rules: RuleSet | None = None,
        starting_scores: Mapping[Seat, int] | SeatPoints | None = None,
    ) -> None:
        if type(seed) is not int:
            raise TypeError("seed must be an int")

        resolved_rules = RuleSet.default() if rules is None else rules
        if not isinstance(resolved_rules, RuleSet):
            raise TypeError("rules must be a RuleSet or None")
        if resolved_rules.player_count != 4:
            raise ValueError("MatchState only supports a four-player RuleSet")
        if resolved_rules.match_format is not MatchFormat.HANCHAN:
            raise ValueError("MatchState only supports MatchFormat.HANCHAN")

        self._rules = resolved_rules
        self._scores = _resolve_starting_scores(starting_scores, resolved_rules)
        self._position = RoundPosition(
            prevailing_wind=Wind.EAST,
            hand_number=1,
            dealer_seat=Seat.EAST,
            honba=0,
            riichi_sticks=0,
        )
        self._phase = MatchPhase.AWAITING_ROUND
        self._active_round: RoundState | None = None
        self._history: tuple[CompletedRound, ...] = ()
        self._completed_match: CompletedMatch | None = None
        self._match_seed = seed
        # 後続段階が`derive_round_seed(match_seed, started_round_count + 1)`
        # としてnext round ordinalを導出するための内部state。
        # global counterではなく、このinstanceだけが所有する。
        self._started_round_count = 0
        # active roundのrandom provenance。`start_round()`が完全成功した
        # ときだけ設定し、後続段階の`CompletedRound.random_provenance`へ
        # そのまま引き継ぐ。
        self._active_round_random_provenance: RoundRandomProvenance | None = None

    @property
    def rules(self) -> RuleSet:
        return self._rules

    @property
    def scores(self) -> SeatPoints:
        return self._scores

    @property
    def position(self) -> RoundPosition:
        return self._position

    @property
    def phase(self) -> MatchPhase:
        return self._phase

    @property
    def active_round(self) -> RoundState | None:
        return self._active_round

    @property
    def history(self) -> tuple[CompletedRound, ...]:
        return self._history

    @property
    def completed_match(self) -> CompletedMatch | None:
        return self._completed_match

    @property
    def match_seed(self) -> int:
        return self._match_seed

    def start_round(self) -> RoundState:
        """deterministicかつatomicに次局を開始し、配牌済みの`RoundState`を返す。

        `MatchPhase.AWAITING_ROUND`のときだけ成功する。round ordinal決定、
        `RoundRandomProvenance`生成、Wall生成、`RoundState`構築、
        `RoundState.deal()`をすべてlocal candidateとして成功させてから、
        最後にまとめてauthoritative stateへcommitする。途中で失敗した場合、
        `self`は一切mutationしない。
        """
        if self._phase is not MatchPhase.AWAITING_ROUND:
            raise RuntimeError("start_round() requires MatchPhase.AWAITING_ROUND")
        if self._active_round is not None:
            raise RuntimeError("start_round() requires no active round in progress")

        round_ordinal = self._started_round_count + 1

        provenance = create_round_random_provenance(
            self._match_seed,
            round_ordinal,
        )
        wall = create_round_wall(provenance)

        candidate_round = RoundState(
            wall,
            round_start_points=self._scores.as_dict(),
            dealer_seat=self._position.dealer_seat,
            prevailing_wind=self._position.prevailing_wind,
            rules=self._rules,
        )
        candidate_round.deal()

        self._active_round = candidate_round
        self._active_round_random_provenance = provenance
        self._started_round_count = round_ordinal
        self._phase = MatchPhase.ROUND_IN_PROGRESS

        return candidate_round


def _resolve_starting_scores(
    starting_scores: Mapping[Seat, int] | SeatPoints | None,
    rules: RuleSet,
) -> SeatPoints:
    if starting_scores is None:
        return SeatPoints(
            rules.starting_points,
            rules.starting_points,
            rules.starting_points,
            rules.starting_points,
        )
    if isinstance(starting_scores, SeatPoints):
        return starting_scores
    return SeatPoints.from_mapping(starting_scores)
