"""局のimmutableな事実から合法手を導出するpure moduleである。

状態mutationからは独立しており、`RoundState`は薄いfacadeとして本module
を呼ぶ。`RoundState`側の巨大methodへ導出logicを埋め戻さない。

E1が導出するのは通常turnの打牌だけである。立直宣言、暗槓、加槓、ツモ
和了、九種九牌、および反応（チー・ポン・大明槓・ロン・パス）の合法手
生成はE2/E3の責務であり、本moduleでは生成しない。生成しないactionは
`RoundState.apply()`でillegalとして拒否される。
"""

from lisjong_engine.legal_action import DiscardLegalAction, LegalAction
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile


def derive_legal_actions(
    *,
    phase: RoundPhase,
    seat: Seat,
    current_seat: Seat | None,
    hand_tiles: tuple[Tile, ...],
) -> tuple[LegalAction, ...]:
    """`seat`が今選べる合法手を、物理牌IDの昇順で返す。

    `current_seat`以外の席へturn actionを提示しない。E1で状態遷移を
    実装していないphaseでは、暫定fallbackを作らず空のtupleを返す。
    """
    if not isinstance(phase, RoundPhase):
        raise TypeError("phase must be a RoundPhase")
    if not isinstance(seat, Seat):
        raise TypeError("seat must be a Seat")
    if current_seat is not None and not isinstance(current_seat, Seat):
        raise TypeError("current_seat must be a Seat or None")

    tiles = tuple(hand_tiles)
    if any(not isinstance(tile, Tile) for tile in tiles):
        raise TypeError("hand_tiles must contain only Tile instances")

    if phase is not RoundPhase.AWAITING_DISCARD or seat is not current_seat:
        return ()

    return derive_discard_actions(tiles)


def derive_discard_actions(hand_tiles: tuple[Tile, ...]) -> tuple[LegalAction, ...]:
    """手牌にある物理牌そのものを打牌候補として列挙する。

    同じ牌種でも物理牌identityを保持し、牌IDの昇順というdeterministicな
    順序で返す。立直・喰い替え等による打牌制限はE2で追加する。
    """
    return tuple(
        DiscardLegalAction(tile.id)
        for tile in sorted(hand_tiles, key=lambda tile: tile.id)
    )
