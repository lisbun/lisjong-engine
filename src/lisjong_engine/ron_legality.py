"""ロン宣言の合法性だけをpureに判定するmodule。

ロンは和了形が完成しているだけでは成立しない。役が1つ以上あり、その席が
フリテンでないことまで満たして初めて合法な反応actionになる。本moduleは
その判定だけを行い、最終的な点数選択・`RoundResult`構築へは踏み込まない。
点数の確定はE3の責務である。

判定は`WinningContext`と`evaluate_yaku()`という既存の得点評価層の入口を
そのまま使う。合法手生成のためにロン成立条件を別実装しない。
"""

from collections.abc import Iterable

from lisjong_engine.meld import Meld
from lisjong_engine.rules import RuleSet
from lisjong_engine.tile import Tile
from lisjong_engine.win_context import (
    RiichiStatus,
    WinMethod,
    WinningContext,
    WinOrigin,
)
from lisjong_engine.wind import Wind
from lisjong_engine.winning import WinningShape, find_winning_shapes
from lisjong_engine.yaku_evaluation import evaluate_yaku


def can_declare_ron(
    *,
    concealed_tiles: Iterable[Tile],
    winning_tile: Tile,
    melds: Iterable[Meld],
    seat_wind: Wind,
    prevailing_wind: Wind,
    riichi_status: RiichiStatus,
    is_ippatsu: bool,
    is_furiten: bool,
    origin: WinOrigin,
    is_last_tile: bool,
    rules: RuleSet,
) -> bool:
    """`concealed_tiles`が`winning_tile`でロン和了できるかを返す。

    `concealed_tiles`は和了牌を含めた手牌である。フリテン、和了形の
    完成、役の有無をこの順で確認し、いずれかを満たさなければ合法な
    ロンにはならない。
    """
    if type(is_furiten) is not bool:
        raise TypeError("is_furiten must be a bool")
    if not isinstance(rules, RuleSet):
        raise TypeError("rules must be a RuleSet")
    if is_furiten:
        return False

    try:
        context = WinningContext(
            concealed_tiles=tuple(concealed_tiles),
            winning_tile=winning_tile,
            method=WinMethod.RON,
            origin=origin,
            seat_wind=seat_wind,
            prevailing_wind=prevailing_wind,
            declared_melds=tuple(melds),
            riichi_status=riichi_status,
            is_ippatsu=is_ippatsu,
            is_last_tile=is_last_tile,
        )
    except ValueError:
        # 和了として矛盾する事実の組み合わせ（立直中でない一発など）は
        # そもそもロン候補にならない。
        return False

    return bool(evaluate_yaku(context, rules))


def is_kokushi_win(
    concealed_tiles: Iterable[Tile],
    melds: Iterable[Meld] = (),
) -> bool:
    """和了牌を含めた牌姿が国士無双として完成しているかを返す。

    暗槓に対する槍槓は国士無双だけに許されるため、暗槓反応の候補生成は
    この判定で解釈を先に絞る。暗槓に使われた4枚は常に同じ席へ揃うため、
    国士無双と通常形・七対子が同じ牌で同時に成立することは構造上ない。
    """
    return WinningShape.THIRTEEN_ORPHANS in find_winning_shapes(concealed_tiles, melds)
