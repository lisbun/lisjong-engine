from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from lisjong_engine.rules import (
    FinalPointsRounding,
    FinalRankTiePolicy,
    RuleSet,
)
from lisjong_engine.seat import Seat

_SEAT_ORDER = tuple(Seat)


@dataclass(frozen=True)
class FinalPlayerScore:
    """半荘終了時の1人分の最終結果。

    ``base_points`` / ``uma_points`` / ``oka_points`` / ``bankruptcy_points`` /
    ``final_points`` は、いずれも内部単位 ``1 = 0.1ポイント`` の ``int`` として
    保持する（例: 人間向け ``+11.0pt`` は内部値 ``110``）。
    ``RuleSet.uma`` 等のルール定義側は人間向けの1ポイント単位のまま
    変わらず、Rule値から本内部単位への変換は
    ``final_score.py`` 内の ``_to_internal_points`` へ集約する。
    """

    seat: Seat
    # `FinalRankTiePolicy.SEAT_ORDER`では常に一意な1〜4。
    # `FinalRankTiePolicy.SPLIT_RANK_POINTS`では同点者が同じ値を共有する
    # 標準競技順位（例: 1位・2位同点なら双方rank=1、次点はrank=3）。
    rank: int
    score: int
    base_points: int
    uma_points: int
    oka_points: int
    bankruptcy_points: int
    final_points: int

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        integer_fields = (
            "rank",
            "score",
            "base_points",
            "uma_points",
            "oka_points",
            "bankruptcy_points",
            "final_points",
        )
        for field_name in integer_fields:
            if type(getattr(self, field_name)) is not int:
                raise TypeError(f"{field_name} must be an int")
        if not 1 <= self.rank <= 4:
            raise ValueError("rank must be between 1 and 4")
        if self.final_points != sum(
            (
                self.base_points,
                self.uma_points,
                self.oka_points,
                self.bankruptcy_points,
            )
        ):
            raise ValueError("final_points must equal the sum of all components")


@dataclass(frozen=True)
class FinalScoreCalculation:
    players: tuple[FinalPlayerScore, ...]

    def __post_init__(self) -> None:
        try:
            players = tuple(self.players)
        except TypeError:
            raise TypeError(
                "players must be an iterable of FinalPlayerScore instances"
            ) from None
        if any(not isinstance(player, FinalPlayerScore) for player in players):
            raise TypeError("players must contain only FinalPlayerScore instances")
        if not _is_valid_final_rank_sequence(tuple(player.rank for player in players)):
            raise ValueError(
                "players must be ordered by standard competition ranking "
                "(ties share the group's starting rank, e.g. (1, 1, 3, 4))"
            )
        if {player.seat for player in players} != set(Seat):
            raise ValueError("players must contain each seat exactly once")
        if sum(player.final_points for player in players) != 0:
            raise ValueError("final points must sum to zero")
        object.__setattr__(self, "players", players)

    def for_seat(self, seat: Seat) -> FinalPlayerScore:
        if not isinstance(seat, Seat):
            raise TypeError("seat must be a Seat")
        return next(player for player in self.players if player.seat is seat)


def _is_valid_final_rank_sequence(ranks: tuple[int, ...]) -> bool:
    """標準競技順位（同順位者は順位帯の先頭順位を共有し、以降の順位は
    その人数分飛ぶ、例: (1, 1, 3, 4) や (1, 2, 2, 4)）として妥当かを返す。

    `FinalRankTiePolicy.SEAT_ORDER`は常に一意な(1, 2, 3, 4)を生成するため、
    この検証はその特殊ケースとして常に成立し、既存契約を変えない。
    """
    previous_rank: int | None = None
    for position, rank in enumerate(ranks, start=1):
        if rank == previous_rank:
            continue
        if rank != position:
            return False
        previous_rank = rank
    return True


def calculate_final_scores(
    scores: Mapping[Seat, int],
    *,
    rules: RuleSet | None = None,
    bankruptcy_points: Mapping[Seat, int] | None = None,
) -> FinalScoreCalculation:
    if not isinstance(scores, Mapping):
        raise TypeError("scores must be a mapping")
    if set(scores) != set(Seat):
        raise ValueError("scores must contain exactly all four seats")
    if any(type(scores[seat]) is not int for seat in Seat):
        raise TypeError("scores must contain only int values")

    if rules is None:
        rules = RuleSet.default()
    elif not isinstance(rules, RuleSet):
        raise TypeError("rules must be RuleSet")

    adjustments = _normalize_bankruptcy_points(bankruptcy_points)
    ranked_seats = tuple(
        sorted(Seat, key=lambda seat: (-scores[seat], _SEAT_ORDER.index(seat)))
    )
    base_points = _calculate_base_points(scores, ranked_seats, rules)
    rank_points = _calculate_rank_points(scores, ranked_seats, rules)

    players = tuple(
        FinalPlayerScore(
            seat=seat,
            rank=rank_points[seat][0],
            score=scores[seat],
            base_points=base_points[seat],
            uma_points=rank_points[seat][1],
            oka_points=rank_points[seat][2],
            bankruptcy_points=_to_internal_points(adjustments[seat]),
            final_points=(
                base_points[seat]
                + rank_points[seat][1]
                + rank_points[seat][2]
                + _to_internal_points(adjustments[seat])
            ),
        )
        for seat in ranked_seats
    )
    return FinalScoreCalculation(players)


def _calculate_rank_points(
    scores: Mapping[Seat, int],
    ranked_seats: tuple[Seat, ...],
    rules: RuleSet,
) -> dict[Seat, tuple[int, int, int]]:
    """席ごとの`(rank, uma_points, oka_points)`をtie policyに応じて計算する。

    `uma_points`/`oka_points`はいずれもFinalScore内部単位
    （1 = 0.1ポイント）。
    """
    if rules.final_rank_tie_policy is FinalRankTiePolicy.SEAT_ORDER:
        return {
            seat: (
                rank,
                _to_internal_points(rules.uma[rank - 1]),
                _to_internal_points(rules.oka_rank_points) if rank == 1 else 0,
            )
            for rank, seat in enumerate(ranked_seats, start=1)
        }
    if rules.final_rank_tie_policy is FinalRankTiePolicy.SPLIT_RANK_POINTS:
        return _calculate_split_rank_points(scores, ranked_seats, rules)
    raise ValueError("unsupported final rank tie policy")


def _calculate_split_rank_points(
    scores: Mapping[Seat, int],
    ranked_seats: tuple[Seat, ...],
    rules: RuleSet,
) -> dict[Seat, tuple[int, int, int]]:
    """同点者を同順位（標準競技順位）として扱い、該当する複数順位の
    ウマ合計・オカを、それぞれ人数で均等分配する。

    各席の`uma_points + oka_points`を、修正前の「ウマ＋オカを合算して
    から按分する」実装と同じ値へ一致させる必要があるため（Issue #127
    レビュー指摘、決定B）、まず合算目標をこれまでどおり算出してから
    ウマの内訳を差し引いてオカを逆算する。

    1. ウマは同点グループが占める順位帯の`rules.uma`を合算し、
       `_to_internal_points()`で内部単位へ変換したうえでグループ人数で
       按分する。端数は`group`内で起家に近い席から内部1単位ずつ配分する
       （`_split_internal_points()`）。
    2. 合算目標は、ウマ合計へ（1位を含むグループでは）
       `rules.oka_rank_points`を加えたうえで内部単位へ変換し、同じ按分
       規則で算出する。合算目標のグループ内合計は、修正前の実装が
       生成していた値と一致する。
    3. 各席のオカは「合算目標 − ウマ」として求める。オカ単体の総額は
       保存されるが、両成分で同時に端数が生じる場合、オカの端数配分は
       起家順という優先順を必ずしも満たさない（ウマの端数配分を優先
       するため）。
    """
    result: dict[Seat, tuple[int, int, int]] = {}
    index = 0
    while index < len(ranked_seats):
        rank_start = index + 1
        group_score = scores[ranked_seats[index]]
        group_end = index + 1
        while (
            group_end < len(ranked_seats)
            and scores[ranked_seats[group_end]] == group_score
        ):
            group_end += 1
        group = ranked_seats[index:group_end]
        rank_end = group_end
        uma_total = sum(rules.uma[rank - 1] for rank in range(rank_start, rank_end + 1))
        oka_total = rules.oka_rank_points if rank_start == 1 else 0
        uma_shares = _split_internal_points(_to_internal_points(uma_total), group)
        combined_shares = _split_internal_points(
            _to_internal_points(uma_total + oka_total), group
        )
        for seat in group:
            result[seat] = (
                rank_start,
                uma_shares[seat],
                combined_shares[seat] - uma_shares[seat],
            )
        index = group_end
    return result


def _split_internal_points(
    internal_total: int, group: tuple[Seat, ...]
) -> dict[Seat, int]:
    """内部単位の合計値をグループ内で均等分配する。

    割り切れない端数は、`group`内の先頭（起家に近い席）から内部1単位ずつ
    配分する。
    """
    quotient, remainder = divmod(internal_total, len(group))
    return {
        seat: quotient + (1 if offset < remainder else 0)
        for offset, seat in enumerate(group)
    }


def _calculate_base_points(
    scores: Mapping[Seat, int],
    ranked_seats: tuple[Seat, ...],
    rules: RuleSet,
) -> dict[Seat, int]:
    """粗点をルールの計算方式に応じて計算する。

    戻り値はいずれの方式でもFinalScore内部単位（1 = 0.1ポイント）の
    ``dict[Seat, int]``。
    """
    if (
        rules.final_points_rounding
        is FinalPointsRounding.TOWARD_ZERO_REMAINDER_TO_FIRST
    ):
        return _calculate_toward_zero_remainder_to_first(scores, ranked_seats, rules)
    elif rules.final_points_rounding is FinalPointsRounding.EXACT_NO_ROUNDING:
        return _calculate_exact_no_rounding(scores, rules)
    raise ValueError("unsupported final points rounding rule")


def _calculate_toward_zero_remainder_to_first(
    scores: Mapping[Seat, int],
    ranked_seats: tuple[Seat, ...],
    rules: RuleSet,
) -> dict[Seat, int]:
    """現行マイルール方式で粗点を計算する。

    2位以下は ``(score - return_points)`` を1000点単位で0方向へ丸め、
    1位はオカ適用前の粗点合計が ``-oka_rank_points`` となるよう残差を
    受け取る。戻り値はFinalScore内部単位（1 = 0.1ポイント）。
    """
    first_seat, *other_seats = ranked_seats
    base_points_by_rule_unit = {
        seat: _round_toward_zero(scores[seat] - rules.return_points)
        for seat in other_seats
    }
    base_points_by_rule_unit[first_seat] = -rules.oka_rank_points - sum(
        base_points_by_rule_unit.values()
    )
    return {
        seat: _to_internal_points(value)
        for seat, value in base_points_by_rule_unit.items()
    }


def _calculate_exact_no_rounding(
    scores: Mapping[Seat, int],
    rules: RuleSet,
) -> dict[Seat, int]:
    """1位への残差配分を行わず、各席を独立に計算する粗点計算方式。

    100持ち点 = 0.1ポイント = FinalScore内部1単位であるため、
    ``(score - return_points) // 100`` をそのまま内部単位の粗点として返す。
    1位への残差吸収は行わないため、入力総点が理論値からずれていても
    ここでは補正しない。その不整合は最終的に
    ``FinalScoreCalculation`` のゼロサム不変条件（
    ``sum(final_points) == 0``）で検出される。
    """
    base_points = {}
    for seat in Seat:
        difference = scores[seat] - rules.return_points
        if difference % 100 != 0:
            raise ValueError(
                "scores must be expressible in 100-point units for EXACT_NO_ROUNDING"
            )
        base_points[seat] = difference // 100
    return base_points


def _to_internal_points(points: int) -> int:
    """人間向けの1ポイント単位を、FinalScore内部の0.1ポイント単位へ変換する。"""
    return points * 10


def _round_toward_zero(point_difference: int) -> int:
    """1000点単位の粗点を0方向(原点側)へ丸め、人間向けの1ポイント単位で返す。"""
    magnitude = abs(point_difference) // 1_000
    return magnitude if point_difference >= 0 else -magnitude


def calculate_bankruptcy_points(
    bankrupt_seat: Seat,
    recipient_seats: Iterable[Seat],
    *,
    rules: RuleSet | None = None,
) -> dict[Seat, int]:
    if not isinstance(bankrupt_seat, Seat):
        raise TypeError("bankrupt_seat must be a Seat")
    return calculate_bankruptcy_points_for_seats(
        (bankrupt_seat,), recipient_seats, rules=rules
    )


def calculate_bankruptcy_points_for_seats(
    bankrupt_seats: Iterable[Seat],
    recipient_seats: Iterable[Seat],
    *,
    rules: RuleSet | None = None,
) -> dict[Seat, int]:
    try:
        bankrupts = tuple(bankrupt_seats)
    except TypeError:
        raise TypeError("bankrupt_seats must be an iterable of Seat values") from None
    if any(not isinstance(seat, Seat) for seat in bankrupts):
        raise TypeError("bankrupt_seats must contain only Seat values")
    if len(set(bankrupts)) != len(bankrupts):
        raise ValueError("bankrupt_seats must be unique")
    try:
        recipients = tuple(recipient_seats)
    except TypeError:
        raise TypeError("recipient_seats must be an iterable of Seat values") from None
    return calculate_bankruptcy_points_by_seat(
        {seat: recipients for seat in bankrupts}, rules=rules
    )


def calculate_bankruptcy_points_by_seat(
    recipient_seats_by_bankrupt: Mapping[Seat, Iterable[Seat]],
    *,
    rules: RuleSet | None = None,
) -> dict[Seat, int]:
    if not isinstance(recipient_seats_by_bankrupt, Mapping):
        raise TypeError("recipient_seats_by_bankrupt must be a mapping")
    if any(not isinstance(seat, Seat) for seat in recipient_seats_by_bankrupt):
        raise TypeError("recipient_seats_by_bankrupt keys must be Seat values")
    if rules is None:
        rules = RuleSet.default()
    elif not isinstance(rules, RuleSet):
        raise TypeError("rules must be RuleSet")

    adjustments = {seat: 0 for seat in Seat}
    for bankrupt_seat in Seat:
        if bankrupt_seat not in recipient_seats_by_bankrupt:
            continue
        try:
            recipients = tuple(recipient_seats_by_bankrupt[bankrupt_seat])
        except TypeError:
            raise TypeError(
                "bankruptcy recipients must be iterables of Seat values"
            ) from None
        if any(not isinstance(seat, Seat) for seat in recipients):
            raise TypeError("bankruptcy recipients must contain only Seat values")
        if len(set(recipients)) != len(recipients):
            raise ValueError("bankruptcy recipients must be unique")
        eligible_recipients = tuple(
            seat for seat in recipients if seat is not bankrupt_seat
        )
        if not eligible_recipients:
            raise ValueError(
                "each bankrupt seat must have at least one eligible recipient"
            )
        ordered_recipients = tuple(
            seat
            for distance in range(1, len(_SEAT_ORDER))
            if (
                seat := _SEAT_ORDER[
                    (_SEAT_ORDER.index(bankrupt_seat) + distance) % len(_SEAT_ORDER)
                ]
            )
            in eligible_recipients
        )
        quotient, remainder = divmod(
            rules.bankruptcy_bonus_points, len(eligible_recipients)
        )
        adjustments[bankrupt_seat] += rules.bankrupt_player_penalty_points
        for index, seat in enumerate(ordered_recipients):
            adjustments[seat] += quotient + (1 if index < remainder else 0)
    return adjustments


def _normalize_bankruptcy_points(
    bankruptcy_points: Mapping[Seat, int] | None,
) -> dict[Seat, int]:
    if bankruptcy_points is None:
        return {seat: 0 for seat in Seat}
    if not isinstance(bankruptcy_points, Mapping):
        raise TypeError("bankruptcy_points must be a mapping or None")
    if set(bankruptcy_points) != set(Seat):
        raise ValueError("bankruptcy_points must contain exactly all four seats")
    if any(type(bankruptcy_points[seat]) is not int for seat in Seat):
        raise TypeError("bankruptcy_points must contain only int values")
    if sum(bankruptcy_points.values()) != 0:
        raise ValueError("bankruptcy_points must sum to zero")
    return {seat: bankruptcy_points[seat] for seat in Seat}
