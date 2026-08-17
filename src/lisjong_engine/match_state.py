"""半荘全体を束ねるMatch層のstate machineを定義するmodule（Issue #24, F2）。

Issue #21（F1）で確定した局精算 / 最終score計算はpure calculationとして
再実装せず、本moduleはそれらのpure APIを正しい順序で呼び出すorchestration
層に徹する。`MatchState`は複数の`RoundState`を1つの半荘として束ね、
指定seedと（呼び出し側が選んだ合法action列の結果である）`RoundResult`から、
東1局開始から半荘終了・最終score確定までを決定的に進行する。

```text
MatchState.start_round()
    -> deterministic Wall / RoundState / deal()

MatchState.settle_active_round()
    -> calculate_round_settlement()（F1）
    -> match end判定
    -> non-terminalならnext RoundPositionへ、terminalならfinalizationへ
    -> CompletedRound / (terminal時のみ)CompletedMatch
    -> atomic commit
```
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from lisjong_engine.final_score import (
    FinalScoreCalculation,
    calculate_bankruptcy_points_from_transfers,
    calculate_final_scores,
)
from lisjong_engine.points import SeatPoints
from lisjong_engine.round_allocation import (
    RoundRandomProvenance,
    create_round_random_provenance,
    create_round_wall,
)
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.round_result import (
    AbortiveDrawResult,
    ExhaustiveDrawResult,
    RoundResult,
    WinResult,
)
from lisjong_engine.round_state import RoundState
from lisjong_engine.rules import MatchFormat, RuleSet
from lisjong_engine.seat import Seat
from lisjong_engine.settlement import (
    RiichiStickAward,
    RoundSettlement,
    calculate_final_riichi_stick_awards,
    calculate_round_settlement,
)
from lisjong_engine.wind import Wind

_SEAT_ORDER = tuple(Seat)

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

    所有するauthoritative factは、`RuleSet`、4席のraw score（`SeatPoints`）、
    現在（または半荘終了時点で最後に実際に開始された）`RoundPosition`、
    `MatchPhase`、進行中の`RoundState | None`、`CompletedRound`の履歴、
    deterministic round allocationに必要な内部state、終了後の
    `CompletedMatch | None`である。

    `FINISHED`後も`position`は最後に実際に開始された局の位置のままであり、
    仮想的な次局位置（例: West4終了後のNorth1）へは書き換えない。半荘の
    最終結果の正本は常に`completed_match`である。
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
        # 次に開始する局の1-based ordinalを、成功裏に開始した局数 + 1として
        # 決定するためのinstance-local state。成功したstart_round()だけが増やす。
        self._started_round_count = 0
        # active roundのrandom provenance。start_round()が完全成功したときだけ
        # 設定し、settlement時のCompletedRound.random_provenanceへそのまま引き継ぐ。
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

    def settle_active_round(self) -> CompletedRound:
        """終了済みactive roundをF1でpureに精算し、non-terminalなら次局待ち
        stateへ、terminalなら半荘finalizationまでatomicにcommitする。

        `MatchPhase.ROUND_IN_PROGRESS`かつ、active roundが
        `RoundPhase.FINISHED`で`result`を確定しているときだけ成功する。
        精算計算そのものは一切再実装せず、`calculate_round_settlement()`
        （F1）を唯一の正本として使う。dealer continuation・next position・
        match end判定もIssue #24前段階のpure helperをそのまま使う。

        判定順序は次で固定する。

        ```text
        context / provenance validation
            -> calculate_round_settlement()
            -> scores_after_settlement
            -> _dealer_continues()
            -> _match_end_reason()
        ```

        ``_match_end_reason() is None`` ならnon-terminalとして
        ``_next_round_position()`` で次局位置を計算する。``None``でない
        場合はterminalとして、``_next_round_position()``を一切呼ばずに
        （西4終了後の仮想North1等を作らない）、必要ならbankruptcy
        adjustmentを、続けて残存riichi sticksの最終配分を、それぞれF1へ
        委譲してから``calculate_final_scores()``で最終scoreを確定する。

        すべてのcandidate計算・value object構築が成功するまで`self`を
        一切mutationせず、成功した場合だけ最後にまとめてcommitする。
        途中で例外になった場合、終了済みのactive roundとそのprovenanceを
        含め、`self`は呼び出し前と完全に同一のままとなる。
        """
        if self._phase is not MatchPhase.ROUND_IN_PROGRESS:
            raise RuntimeError(
                "settle_active_round() requires MatchPhase.ROUND_IN_PROGRESS"
            )
        if self._active_round is None:
            raise RuntimeError("settle_active_round() requires an active round")
        if self._active_round_random_provenance is None:
            raise RuntimeError(
                "settle_active_round() requires the active round's random provenance"
            )

        round_state = self._active_round
        provenance = self._active_round_random_provenance

        if round_state.phase is not RoundPhase.FINISHED:
            raise RuntimeError("the active round has not finished")
        result = round_state.result
        if result is None:
            raise RuntimeError("a finished round must have a result")

        if round_state.rules != self._rules:
            raise ValueError("the active round's rules do not match MatchState.rules")
        if round_state.dealer_seat is not self._position.dealer_seat:
            raise ValueError(
                "the active round's dealer_seat does not match the current position"
            )
        if round_state.prevailing_wind is not self._position.prevailing_wind:
            raise ValueError(
                "the active round's prevailing_wind does not match the current position"
            )
        if SeatPoints.from_mapping(round_state.round_start_points) != self._scores:
            raise ValueError(
                "the active round's round_start_points do not match MatchState.scores"
            )
        if provenance.match_seed != self._match_seed:
            raise ValueError("the active round's provenance match_seed is inconsistent")
        if provenance.round_ordinal != self._started_round_count:
            raise ValueError(
                "the active round's provenance round_ordinal is inconsistent"
            )

        settlement = calculate_round_settlement(
            result,
            dealer_seat=self._position.dealer_seat,
            honba=self._position.honba,
            riichi_sticks_before=self._position.riichi_sticks,
            riichi_contributions=round_state.riichi_contributions,
            rules=self._rules,
        )

        scores_after = self._scores.add(settlement.point_deltas)
        dealer_continues = _dealer_continues(result, self._position.dealer_seat)
        end_reason = _match_end_reason(
            self._position,
            result,
            scores_after,
            dealer_continues,
            self._rules,
        )

        if end_reason is None:
            return self._commit_non_terminal_settlement(
                provenance=provenance,
                result=result,
                settlement=settlement,
                scores_after=scores_after,
                dealer_continues=dealer_continues,
            )

        return self._commit_terminal_settlement(
            provenance=provenance,
            result=result,
            settlement=settlement,
            scores_after=scores_after,
            dealer_continues=dealer_continues,
            end_reason=end_reason,
        )

    def _commit_non_terminal_settlement(
        self,
        *,
        provenance: RoundRandomProvenance,
        result: RoundResult,
        settlement: RoundSettlement,
        scores_after: SeatPoints,
        dealer_continues: bool,
    ) -> CompletedRound:
        next_position = _next_round_position(
            self._position,
            result,
            dealer_continues,
            riichi_sticks=settlement.riichi_sticks_after,
        )

        completed_round = CompletedRound(
            random_provenance=provenance,
            position_before=self._position,
            result=result,
            settlement=settlement,
            scores_after_settlement=scores_after,
            dealer_continues=dealer_continues,
            next_position=next_position,
        )
        history_after = self._history + (completed_round,)

        self._scores = scores_after
        self._position = next_position
        self._history = history_after
        self._active_round = None
        self._active_round_random_provenance = None
        self._phase = MatchPhase.AWAITING_ROUND

        return completed_round

    def _commit_terminal_settlement(
        self,
        *,
        provenance: RoundRandomProvenance,
        result: RoundResult,
        settlement: RoundSettlement,
        scores_after: SeatPoints,
        dealer_continues: bool,
        end_reason: MatchEndReason,
    ) -> CompletedRound:
        bankruptcy_points = (
            calculate_bankruptcy_points_from_transfers(
                _bankrupt_seats(scores_after, self._rules),
                settlement.transfers,
                rules=self._rules,
            )
            if end_reason is MatchEndReason.BANKRUPTCY
            else None
        )

        final_riichi_stick_awards = calculate_final_riichi_stick_awards(
            scores_after,
            settlement.riichi_sticks_after,
            rules=self._rules,
        )
        final_raw_scores = scores_after.add(
            _riichi_stick_award_deltas(final_riichi_stick_awards)
        )

        final_score = calculate_final_scores(
            final_raw_scores.as_dict(),
            rules=self._rules,
            bankruptcy_points=bankruptcy_points,
        )

        completed_round = CompletedRound(
            random_provenance=provenance,
            position_before=self._position,
            result=result,
            settlement=settlement,
            scores_after_settlement=scores_after,
            dealer_continues=dealer_continues,
            next_position=None,
        )
        history_after = self._history + (completed_round,)

        completed_match = CompletedMatch(
            end_reason=end_reason,
            final_riichi_stick_awards=final_riichi_stick_awards,
            final_raw_scores=final_raw_scores,
            final_score=final_score,
            history=history_after,
        )

        self._scores = final_raw_scores
        self._history = history_after
        self._active_round = None
        self._active_round_random_provenance = None
        self._completed_match = completed_match
        self._phase = MatchPhase.FINISHED

        return completed_round


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


def _dealer_continues(
    result: RoundResult,
    dealer_seat: Seat,
) -> bool:
    """局終了resultから、親が継続するかどうかをpureに判定する。

    和了はdealerがwinnerに含まれる場合（複数ロンでも同様）だけ継続する。
    途中流局は理由に関わらず常に継続する。荒牌流局はdealerが
    `tenpai_seats`に含まれる場合だけ継続する。
    """
    if not isinstance(result, RoundResult):
        raise TypeError("result must be a RoundResult")
    if not isinstance(dealer_seat, Seat):
        raise TypeError("dealer_seat must be a Seat")

    if isinstance(result, WinResult):
        return any(winner.seat is dealer_seat for winner in result.winners)
    if isinstance(result, AbortiveDrawResult):
        return True
    return dealer_seat in result.tenpai_seats


def _next_round_position(
    position: RoundPosition,
    result: RoundResult,
    dealer_continues: bool,
    *,
    riichi_sticks: int,
) -> RoundPosition:
    """現在positionと局終了factから、続行する場合のnext positionをpureに計算する。

    親が流れる場合の本場は、和了によるものなら0へ戻り、荒牌流局・途中流局
    によるものなら+1する。`riichi_sticks`はcallerがsettlement後に卓上へ
    残ると判断した本数をそのまま引き継ぐだけで、本helper自身は供託の
    増減を計算しない。

    West4での親流れのように、そもそも成立しない`RoundPosition`（本
    contractでは北場を対局位置として扱わない）を要求された場合は、
    `RoundPosition`自身のvalidationにより`ValueError`でfail closedする。
    仮想的なNorth1を代わりに生成することはしない。
    """
    if not isinstance(position, RoundPosition):
        raise TypeError("position must be a RoundPosition")
    if not isinstance(result, RoundResult):
        raise TypeError("result must be a RoundResult")
    if type(dealer_continues) is not bool:
        raise TypeError("dealer_continues must be a bool")
    if type(riichi_sticks) is not int:
        raise TypeError("riichi_sticks must be an int")
    if riichi_sticks < 0:
        raise ValueError("riichi_sticks must be non-negative")

    if dealer_continues:
        prevailing_wind = position.prevailing_wind
        hand_number = position.hand_number
        dealer_seat = position.dealer_seat
    else:
        dealer_seat = position.dealer_seat.next()
        if position.hand_number == 4:
            prevailing_wind = position.prevailing_wind.next()
            hand_number = 1
        else:
            prevailing_wind = position.prevailing_wind
            hand_number = position.hand_number + 1

    honba = (
        position.honba + 1
        if dealer_continues
        or isinstance(result, (ExhaustiveDrawResult, AbortiveDrawResult))
        else 0
    )

    return RoundPosition(
        prevailing_wind=prevailing_wind,
        hand_number=hand_number,
        dealer_seat=dealer_seat,
        honba=honba,
        riichi_sticks=riichi_sticks,
    )


def _riichi_stick_award_deltas(
    awards: tuple[RiichiStickAward, ...],
) -> SeatPoints:
    """final riichi stick awardのrecipient別合計を`SeatPoints`へ集約するだけの
    pure helper。

    誰へいくら配るかは`calculate_final_riichi_stick_awards()`（F1）の責務で
    あり、ここではその結果をraw scoreへ足し込むための単純な合算だけを行う。
    """
    try:
        award_tuple = tuple(awards)
    except TypeError:
        raise TypeError(
            "awards must be an iterable of RiichiStickAward values"
        ) from None
    if any(not isinstance(award, RiichiStickAward) for award in award_tuple):
        raise TypeError("awards must contain only RiichiStickAward values")

    deltas = {seat: 0 for seat in Seat}
    for award in award_tuple:
        deltas[award.recipient] += award.amount
    return SeatPoints.from_mapping(deltas)


def _first_place_seat(scores: SeatPoints) -> Seat:
    """東1局開始時の固定席順（東→南→西→北）をtie-breakとした1位席を返す。

    `FinalRankTiePolicy`（最終順位点の分配規則）とは別の、match進行判定
    専用のtie-break契約であり、`calculate_final_scores()`は呼ばない。
    """
    if not isinstance(scores, SeatPoints):
        raise TypeError("scores must be SeatPoints")

    return max(
        _SEAT_ORDER,
        key=lambda seat: (scores[seat], -_SEAT_ORDER.index(seat)),
    )


def _bankrupt_seats(
    scores: SeatPoints,
    rules: RuleSet,
) -> tuple[Seat, ...]:
    """局精算適用後のraw scoreから、破産済み席を固定席順でpureに抽出する。"""
    if not isinstance(scores, SeatPoints):
        raise TypeError("scores must be SeatPoints")
    if not isinstance(rules, RuleSet):
        raise TypeError("rules must be a RuleSet")

    if not rules.bankruptcy_enabled:
        return ()

    return tuple(
        seat for seat in _SEAT_ORDER if scores[seat] < rules.bankruptcy_threshold
    )


def _match_end_reason(
    position: RoundPosition,
    result: RoundResult,
    scores_after: SeatPoints,
    dealer_continues: bool,
    rules: RuleSet,
) -> MatchEndReason | None:
    """局精算後のfactから、半荘が終了するかどうかをpureに判定する。

    判定順序は次で固定する。

    1. bankruptcy（局位置に関係なく最優先）
    2. West4は親継続の有無に関わらず必ず最大局として`FINAL_ROUND`
    3. South4 / West1〜3でのdealer win・dealer tenpai stop
    4. dealer流れ時の`TARGET_REACHED`
    5. South4で親流れかつtarget未達なら、`west_round_enabled`次第で
       `None`（西入）または`FINAL_ROUND`
    6. West1〜3で親流れかつtarget未達なら`None`（次のWest handへ進む）

    `return_points`は最終score計算専用の値であり、ここでは一切参照しない。
    判定に使う基準点は常に`rules.first_place_target_points`である。
    """
    if not isinstance(position, RoundPosition):
        raise TypeError("position must be a RoundPosition")
    if not isinstance(result, RoundResult):
        raise TypeError("result must be a RoundResult")
    if not isinstance(scores_after, SeatPoints):
        raise TypeError("scores_after must be SeatPoints")
    if type(dealer_continues) is not bool:
        raise TypeError("dealer_continues must be a bool")
    if not isinstance(rules, RuleSet):
        raise TypeError("rules must be a RuleSet")

    expected_dealer_continues = _dealer_continues(result, position.dealer_seat)
    if dealer_continues != expected_dealer_continues:
        raise ValueError(
            "dealer_continues is inconsistent with result and position.dealer_seat"
        )

    if _bankrupt_seats(scores_after, rules):
        return MatchEndReason.BANKRUPTCY

    is_west_four = position.prevailing_wind is Wind.WEST and position.hand_number == 4
    if is_west_four:
        return MatchEndReason.FINAL_ROUND

    is_south_four = position.prevailing_wind is Wind.SOUTH and position.hand_number == 4
    is_west_before_four = (
        position.prevailing_wind is Wind.WEST and position.hand_number < 4
    )
    if not (is_south_four or is_west_before_four):
        return None

    dealer_seat = position.dealer_seat
    dealer_is_top = _first_place_seat(scores_after) is dealer_seat
    dealer_reached_target = scores_after[dealer_seat] >= rules.first_place_target_points

    if dealer_continues and dealer_is_top and dealer_reached_target:
        if (
            isinstance(result, WinResult)
            and rules.dealer_win_end_enabled
            and any(winner.seat is dealer_seat for winner in result.winners)
        ):
            return MatchEndReason.DEALER_WIN
        if (
            isinstance(result, ExhaustiveDrawResult)
            and rules.dealer_tenpai_end_enabled
            and dealer_seat in result.tenpai_seats
        ):
            return MatchEndReason.DEALER_TENPAI
        return None

    if not dealer_continues:
        if any(scores_after[seat] >= rules.first_place_target_points for seat in Seat):
            return MatchEndReason.TARGET_REACHED
        if is_south_four and not rules.west_round_enabled:
            return MatchEndReason.FINAL_ROUND

    return None
