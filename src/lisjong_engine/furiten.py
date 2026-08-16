"""フリテンの理由と、その導出・更新をpureに扱うmodule。

旧実装ではフリテンの理由enumだけが独立moduleにあり、判定logicは
`PlayerState`と`RoundState`へ分散していた。本moduleは、理由enumと
「どの事実からどの理由が立つか」「見逃し由来の理由をいつ更新・解除
するか」というpureな判定を1か所へまとめる。

フリテン状態そのものを保持するのは`PlayerState`の責務であり、本module
は値の写像だけを行う。

理由は次の3つに分かれる。

```text
DISCARD   自分の河に自分の和了牌がある（河が変わらない限り継続する）
TEMPORARY 未立直でロンを見逃した（自分の次のツモまで継続する）
RIICHI    立直後にロンを見逃した（局が終わるまで継続する）
```

`DISCARD`は河と待ちから毎回導出できるため状態として保持しない。
`TEMPORARY`と`RIICHI`は見逃しという過去の事実であり、河からは復元
できないため`PlayerState`が保持する。
"""

from collections.abc import Iterable
from enum import Enum

from lisjong_engine.tile import TileType


class FuritenReason(Enum):
    DISCARD = "discard"
    TEMPORARY = "temporary"
    RIICHI = "riichi"


# 見逃し由来として保持できる理由。`DISCARD`は河から導出するものであり、
# 見逃しの記録としては保持しない。
MISSED_RON_REASONS = (FuritenReason.TEMPORARY, FuritenReason.RIICHI)


def validate_missed_ron_reason(reason: FuritenReason | None) -> None:
    """見逃し由来として保持できる理由かどうかを検証する。"""
    if reason is None:
        return
    if not isinstance(reason, FuritenReason):
        raise TypeError("missed_ron_furiten must be a FuritenReason or None")
    if reason not in MISSED_RON_REASONS:
        raise ValueError("discard furiten must be derived from the river")


def derive_furiten_reasons(
    *,
    discarded_tile_types: Iterable[TileType],
    winning_tile_types: Iterable[TileType],
    missed_ron_reason: FuritenReason | None,
) -> frozenset[FuritenReason]:
    """河・待ち・見逃し記録から、現在成立しているフリテン理由を返す。"""
    validate_missed_ron_reason(missed_ron_reason)

    waits = frozenset(winning_tile_types)
    reasons = set()
    if waits & frozenset(discarded_tile_types):
        reasons.add(FuritenReason.DISCARD)
    if missed_ron_reason is not None:
        reasons.add(missed_ron_reason)
    return frozenset(reasons)


def next_missed_ron_reason(
    current: FuritenReason | None,
    *,
    is_riichi_established: bool,
) -> FuritenReason:
    """ロンを見逃した席の、更新後の見逃し理由を返す。

    立直後の見逃しは局が終わるまで解除されないため、一度`RIICHI`に
    なった席はその後の見逃しで`TEMPORARY`へ弱くならない。
    """
    validate_missed_ron_reason(current)
    if type(is_riichi_established) is not bool:
        raise TypeError("is_riichi_established must be a bool")

    if current is FuritenReason.RIICHI:
        return FuritenReason.RIICHI
    return FuritenReason.RIICHI if is_riichi_established else FuritenReason.TEMPORARY


def cleared_temporary_reason(current: FuritenReason | None) -> FuritenReason | None:
    """自分のツモ番が来たときの、更新後の見逃し理由を返す。

    同巡内の一時フリテンだけが解除され、立直後の見逃しは維持する。
    """
    validate_missed_ron_reason(current)
    return None if current is FuritenReason.TEMPORARY else current
