"""局のimmutableな事実から合法手を導出するpure moduleである。

状態mutationからは独立しており、`RoundState`は薄いfacadeとして本module
を呼ぶ。`RoundState`側の巨大methodへ導出logicを埋め戻さない。

導出の入口は`RoundView`という読み取り専用viewである。`RoundState`は
commit済みstateからこのviewを組み立てて渡すだけであり、本moduleは
`RoundView`を書き換えない。

phaseごとの導出は次のpure関数へ分ける。

```text
derive_turn_actions              打牌・立直宣言打牌・暗槓・加槓
derive_discard_reaction_actions  パス・ロン・ポン・チー・大明槓
derive_kakan_reaction_actions    パス・ロン（槍槓）
derive_ankan_reaction_actions    パス・ロン（国士無双限定の槍槓）
```

ツモ和了・九種九牌はどちらもshared winning finalization / draw resolutionへ
immutable factを渡してprobeする。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations

from lisjong_engine.discard import Discard
from lisjong_engine.draw_resolution import nine_terminals_eligible
from lisjong_engine.kan import (
    PendingAnkan,
    PendingKakan,
    find_kakan_pon,
    is_riichi_ankan_allowed,
)
from lisjong_engine.legal_action import (
    AnkanLegalAction,
    ChiLegalAction,
    DaiminkanLegalAction,
    DiscardDeclaration,
    DiscardLegalAction,
    KakanLegalAction,
    LegalAction,
    NineTerminalsLegalAction,
    PassLegalAction,
    PonLegalAction,
    ReactionOrigin,
    RonLegalAction,
    TsumoLegalAction,
)
from lisjong_engine.meld import Chi, Daiminkan, Pon
from lisjong_engine.player_state import PlayerState
from lisjong_engine.reaction import reaction_action_sort_key, reaction_seat_order
from lisjong_engine.ron_legality import can_declare_ron, is_kokushi_win
from lisjong_engine.round_event import DrawSource
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.rules import RuleSet
from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile, TileType
from lisjong_engine.win_context import WinMethod, WinOrigin
from lisjong_engine.wind import Wind
from lisjong_engine.winning import find_winning_tile_types
from lisjong_engine.winning_finalization import (
    DoraIndicatorState,
    WinningClaim,
    has_winning_score,
)

_SUITED_RANK_RANGE = range(1, 10)


@dataclass(frozen=True)
class RoundView:
    """合法手導出に必要な、局の読み取り専用view。

    `PlayerState`はmutableだが、本moduleは読み出しだけを行う。導出のために
    局stateを書き換えたい場合は、必ず`copy()`したうえで試算する。
    """

    phase: RoundPhase
    current_seat: Seat | None
    players: Mapping[Seat, PlayerState]
    seat_winds: Mapping[Seat, Wind]
    prevailing_wind: Wind
    rules: RuleSet
    round_start_points: Mapping[Seat, int]
    remaining_count: int
    can_draw_rinshan: bool
    drawn_tile_id: int | None = None
    drawn_tile_source: DrawSource | None = None
    pending_discarder: Seat | None = None
    pending_discard: Discard | None = None
    pending_discard_source: DrawSource | None = None
    pending_kakan: PendingKakan | None = None
    pending_ankan: PendingAnkan | None = None
    dora_indicator_tiles: tuple[Tile, ...] = ()
    ura_dora_indicator_tiles: tuple[Tile, ...] = ()
    revealed_dora_indicator_count: int = 0
    pending_kan_dora_reveals: tuple[Seat, ...] = ()
    suukantsu_pao_seats: Mapping[Seat, Seat] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.phase, RoundPhase):
            raise TypeError("phase must be a RoundPhase")
        if self.current_seat is not None and not isinstance(self.current_seat, Seat):
            raise TypeError("current_seat must be a Seat or None")
        if set(self.players) != set(Seat):
            raise ValueError("players must contain every seat")
        if any(not isinstance(player, PlayerState) for player in self.players.values()):
            raise TypeError("players must contain only PlayerState instances")
        if not isinstance(self.rules, RuleSet):
            raise TypeError("rules must be a RuleSet")
        if self.drawn_tile_source is not None and not isinstance(
            self.drawn_tile_source, DrawSource
        ):
            raise TypeError("drawn_tile_source must be a DrawSource or None")


def derive_legal_actions(view: RoundView, seat: Seat) -> tuple[LegalAction, ...]:
    """`seat`が今選べる合法手をdeterministicな順序で返す。

    合法手を持たない席・phaseでは、暫定fallbackを作らず空のtupleを返す。
    """
    if not isinstance(view, RoundView):
        raise TypeError("view must be a RoundView")
    if not isinstance(seat, Seat):
        raise TypeError("seat must be a Seat")

    if view.phase is RoundPhase.AWAITING_DISCARD:
        if seat is not view.current_seat:
            return ()
        return derive_turn_actions(view, seat)
    if view.phase is RoundPhase.AWAITING_REACTIONS:
        return derive_discard_reaction_actions(view, seat)
    if view.phase is RoundPhase.AWAITING_KAKAN_REACTIONS:
        return derive_kakan_reaction_actions(view, seat)
    if view.phase is RoundPhase.AWAITING_ANKAN_REACTIONS:
        return derive_ankan_reaction_actions(view, seat)
    return ()


def derive_turn_actions(view: RoundView, seat: Seat) -> tuple[LegalAction, ...]:
    """打牌・立直宣言打牌・暗槓・加槓・ツモ・九種九牌を、この順序で列挙する。"""
    player = view.players[seat]
    hand_tiles = _sorted_hand(player)
    actions: list[LegalAction] = [
        DiscardLegalAction(tile.id) for tile in derive_discardable_tiles(view, seat)
    ]
    actions.extend(
        DiscardLegalAction(tile.id, DiscardDeclaration.RIICHI)
        for tile in derive_riichi_discard_tiles(view, seat)
    )

    if view.drawn_tile_id is not None and view.can_draw_rinshan:
        actions.extend(_derive_ankan_actions(view, seat, hand_tiles))
        actions.extend(_derive_kakan_actions(player, hand_tiles))
    claim = derive_tsumo_claim(view, seat)
    if claim is not None and has_winning_score(
        claim,
        dora_indicator_state(view),
        view.rules,
    ):
        actions.append(TsumoLegalAction())
    if derive_nine_terminals_eligibility(view, seat):
        actions.append(NineTerminalsLegalAction())
    return tuple(actions)


def _is_global_first_uninterrupted_turn(view: RoundView, seat: Seat) -> bool:
    """`seat`自身がまだ打牌しておらず、局全体でも鳴きが起きていないかを返す。

    天和・地和相当のツモcontextと九種九牌の第一巡条件が共有する事実。
    """
    player = view.players[seat]
    return not player.has_discarded and not any(
        other.melds for other in view.players.values()
    )


def derive_tsumo_claim(view: RoundView, seat: Seat) -> WinningClaim | None:
    """current drawから、ツモprobe/finalizationで共有するclaimを構築する。"""
    if view.drawn_tile_id is None or view.drawn_tile_source is None:
        return None
    player = view.players[seat]
    winning_tile = next(
        (tile for tile in player.hand_tiles if tile.id == view.drawn_tile_id),
        None,
    )
    if winning_tile is None:
        return None
    origin = (
        WinOrigin.RINSHAN
        if view.drawn_tile_source is DrawSource.RINSHAN
        else WinOrigin.LIVE_WALL
    )
    pao_seats = view.suukantsu_pao_seats or {}
    return WinningClaim(
        seat=seat,
        concealed_tiles=player.hand_tiles,
        winning_tile=winning_tile,
        method=WinMethod.TSUMO,
        origin=origin,
        seat_wind=view.seat_winds[seat],
        prevailing_wind=view.prevailing_wind,
        declared_melds=player.melds,
        riichi_status=player.riichi_status,
        is_ippatsu=player.is_ippatsu,
        is_last_tile=(
            view.drawn_tile_source is DrawSource.LIVE_WALL and view.remaining_count == 0
        ),
        is_first_uninterrupted_turn=(
            origin is WinOrigin.LIVE_WALL
            and _is_global_first_uninterrupted_turn(view, seat)
        ),
        suukantsu_pao_seat=pao_seats.get(seat),
    )


def derive_nine_terminals_eligibility(view: RoundView, seat: Seat) -> bool:
    """`seat`が今、九種九牌を宣言できるかを返す。

    生成側（合法手probe）とapply側（strict revalidation）の両方が本関数を
    通ることで、判定logicを二重実装しない。
    """
    if not view.rules.nine_terminals_abortive_draw_enabled:
        return False
    if view.drawn_tile_id is None or view.drawn_tile_source is not DrawSource.LIVE_WALL:
        return False
    if not _is_global_first_uninterrupted_turn(view, seat):
        return False
    return nine_terminals_eligible(view.players[seat].hand_tiles)


def dora_indicator_state(view: RoundView) -> DoraIndicatorState:
    """RoundViewのWall由来factをimmutableなpure-helper入力へ変換する。"""
    return DoraIndicatorState(
        dora_indicator_tiles=view.dora_indicator_tiles,
        ura_dora_indicator_tiles=view.ura_dora_indicator_tiles,
        revealed_dora_indicator_count=view.revealed_dora_indicator_count,
        pending_kan_dora_reveal_seats=view.pending_kan_dora_reveals,
    )


def derive_discardable_tiles(view: RoundView, seat: Seat) -> tuple[Tile, ...]:
    """宣言を伴わない打牌の候補牌を、物理牌IDの昇順で返す。

    立直が成立している席はツモ切りしか選べない。直前のチー・ポンでは
    喰い替えとなる牌種を除く。
    """
    player = view.players[seat]
    hand_tiles = _sorted_hand(player)
    if player.is_riichi_established and view.drawn_tile_id is not None:
        return tuple(tile for tile in hand_tiles if tile.id == view.drawn_tile_id)

    forbidden_types = derive_kuikae_forbidden_tile_types(view, seat)
    return tuple(tile for tile in hand_tiles if tile.tile_type not in forbidden_types)


def derive_riichi_discard_tiles(view: RoundView, seat: Seat) -> tuple[Tile, ...]:
    """立直を宣言して打てる牌を、物理牌IDの昇順で返す。

    点数条件は局開始時点のsnapshotで判定する。`riichi_minimum_points`が
    Noneのルールでは点数条件なしとして扱う。
    """
    player = view.players[seat]
    if player.is_riichi_established or not player.is_menzen:
        return ()
    if view.remaining_count < view.rules.riichi_minimum_live_wall_tiles:
        return ()

    minimum_points = view.rules.riichi_minimum_points
    if minimum_points is not None and view.round_start_points[seat] < minimum_points:
        return ()

    return tuple(
        tile
        for tile in derive_discardable_tiles(view, seat)
        if _leaves_tenpai(player, tile.id)
    )


def derive_kuikae_forbidden_tile_types(
    view: RoundView,
    seat: Seat,
) -> frozenset[TileType]:
    """喰い替え制限により、直前のチー・ポン後の打牌で禁止される牌種。

    チー・ポン直後（ツモを挟まない打牌）に限り、鳴いた牌と同一の牌種を
    打牌候補から除く。チーで両面待ちを使った場合は、もう一方の待ち側の
    牌種（筋喰い替え）も合わせて除く。ポンにはこの筋の制限はない。
    """
    player = view.players[seat]
    if view.drawn_tile_id is not None or not player.melds:
        return frozenset()

    last_meld = player.melds[-1]
    if isinstance(last_meld, Pon):
        return frozenset({last_meld.called_tile.tile_type})
    if not isinstance(last_meld, Chi):
        return frozenset()

    called_rank = last_meld.called_tile.tile_type.rank
    category = last_meld.called_tile.tile_type.category
    all_ranks = sorted(
        (called_rank, *(tile.tile_type.rank for tile in last_meld.consumed_tiles))
    )
    forbidden_ranks = {called_rank}
    if called_rank == all_ranks[0]:
        forbidden_ranks.add(all_ranks[-1] + 1)
    elif called_rank == all_ranks[-1]:
        forbidden_ranks.add(all_ranks[0] - 1)
    return frozenset(
        TileType(category, rank)
        for rank in forbidden_ranks
        if rank in _SUITED_RANK_RANGE
    )


def derive_discard_reaction_actions(
    view: RoundView,
    seat: Seat,
) -> tuple[LegalAction, ...]:
    """打牌への反応を列挙する。

    打牌した席以外の3席には、実際に反応できなくても必ずパスを提示する。
    「非パスの反応がある席だけが反応対象になる」という意味にはしない。
    """
    discarder = view.pending_discarder
    discard = view.pending_discard
    if discarder is None or discard is None:
        raise ValueError("a discard reaction requires a pending discard")
    if seat is discarder:
        return ()

    target_tile = discard.tile
    player = view.players[seat]
    actions: list[LegalAction] = [
        PassLegalAction(ReactionOrigin.DISCARD, target_tile.id)
    ]
    if _can_ron(
        view,
        seat,
        target_tile,
        origin=WinOrigin.DISCARD,
        is_last_tile=(
            view.pending_discard_source is DrawSource.LIVE_WALL
            and view.remaining_count == 0
        ),
    ):
        actions.append(RonLegalAction(ReactionOrigin.DISCARD, target_tile.id))

    if not player.is_riichi_established:
        actions.extend(_derive_call_actions(view, seat, discarder, target_tile))
    return tuple(sorted(actions, key=reaction_action_sort_key))


def derive_kakan_reaction_actions(
    view: RoundView,
    seat: Seat,
) -> tuple[LegalAction, ...]:
    """加槓への槍槓反応を列挙する。宣言者以外はパスを必ず持つ。"""
    pending = view.pending_kakan
    if pending is None:
        raise ValueError("a kakan reaction requires a pending kakan")
    if seat is pending.seat:
        return ()

    target_tile = pending.target_tile
    actions: list[LegalAction] = [PassLegalAction(ReactionOrigin.KAKAN, target_tile.id)]
    if _can_ron(
        view,
        seat,
        target_tile,
        origin=WinOrigin.KAKAN,
        is_last_tile=False,
    ):
        actions.append(RonLegalAction(ReactionOrigin.KAKAN, target_tile.id))
    return tuple(sorted(actions, key=reaction_action_sort_key))


def derive_ankan_reaction_actions(
    view: RoundView,
    seat: Seat,
) -> tuple[LegalAction, ...]:
    """暗槓への槍槓反応を列挙する。

    暗槓ロンは`RuleSet.kokushi_ankan_chankan_enabled`が有効な場合の、
    国士無双として和了できる席だけに限る。通常形・七対子では、フリテン等の
    他条件を見るまでもなく候補にしない。
    """
    pending = view.pending_ankan
    if pending is None:
        raise ValueError("an ankan reaction requires a pending ankan")
    if seat is pending.seat:
        return ()

    target_tile = pending.target_tile
    actions: list[LegalAction] = [PassLegalAction(ReactionOrigin.ANKAN, target_tile.id)]
    if view.rules.kokushi_ankan_chankan_enabled and _is_kokushi_ankan_ron(
        view,
        seat,
        target_tile,
    ):
        actions.append(RonLegalAction(ReactionOrigin.ANKAN, target_tile.id))
    return tuple(sorted(actions, key=reaction_action_sort_key))


def _derive_call_actions(
    view: RoundView,
    seat: Seat,
    discarder: Seat,
    target_tile: Tile,
) -> tuple[LegalAction, ...]:
    player = view.players[seat]
    hand_tiles = _sorted_hand(player)
    matching_tiles = tuple(
        tile for tile in hand_tiles if tile.tile_type == target_tile.tile_type
    )
    actions: list[LegalAction] = []

    if view.remaining_count > 0:
        actions.extend(
            PonLegalAction(target_tile.id, tuple(tile.id for tile in consumed))
            for consumed in combinations(matching_tiles, 2)
            if _is_constructible(Pon, target_tile, consumed, discarder)
        )
    if view.can_draw_rinshan:
        actions.extend(
            DaiminkanLegalAction(target_tile.id, tuple(tile.id for tile in consumed))
            for consumed in combinations(matching_tiles, 3)
            if _is_constructible(Daiminkan, target_tile, consumed, discarder)
        )
    if seat is reaction_seat_order(discarder)[0] and view.remaining_count > 0:
        actions.extend(
            ChiLegalAction(target_tile.id, tuple(tile.id for tile in consumed))
            for consumed in combinations(hand_tiles, 2)
            if _is_constructible(Chi, target_tile, consumed, discarder)
        )
    return tuple(actions)


def _derive_ankan_actions(
    view: RoundView,
    seat: Seat,
    hand_tiles: tuple[Tile, ...],
) -> tuple[LegalAction, ...]:
    player = view.players[seat]
    tile_ids_by_type: dict[TileType, list[int]] = {}
    for tile in hand_tiles:
        tile_ids_by_type.setdefault(tile.tile_type, []).append(tile.id)

    actions: list[LegalAction] = []
    for tile_ids in sorted(tile_ids_by_type.values(), key=lambda ids: ids[0]):
        if len(tile_ids) != 4:
            continue
        if player.is_riichi_established and not _is_riichi_ankan_allowed(
            view,
            player,
            tuple(tile_ids),
        ):
            continue
        actions.append(AnkanLegalAction(tuple(tile_ids)))
    return tuple(actions)


def _derive_kakan_actions(
    player: PlayerState,
    hand_tiles: tuple[Tile, ...],
) -> tuple[LegalAction, ...]:
    if player.is_riichi_established:
        # ポンがあれば門前ではないため、立直中の席が加槓候補を持つことは
        # 構造上ない。ここはその不変が崩れた場合に非合法手を提示しない
        # ためのfail closedである。
        return ()
    return tuple(
        KakanLegalAction(tile.id)
        for tile in hand_tiles
        if find_kakan_pon(player.melds, tile) is not None
    )


def _is_riichi_ankan_allowed(
    view: RoundView,
    player: PlayerState,
    tile_ids: tuple[int, int, int, int],
) -> bool:
    drawn_tile = next(
        (tile for tile in player.hand_tiles if tile.id == view.drawn_tile_id),
        None,
    )
    if drawn_tile is None:
        return False
    return is_riichi_ankan_allowed(
        hand_tiles=player.hand_tiles,
        melds=player.melds,
        drawn_tile=drawn_tile,
        tile_ids=tile_ids,
        policy=view.rules.riichi_ankan_policy,
    )


def _can_ron(
    view: RoundView,
    seat: Seat,
    target_tile: Tile,
    *,
    origin: WinOrigin,
    is_last_tile: bool,
) -> bool:
    player = view.players[seat]
    return can_declare_ron(
        concealed_tiles=(*player.hand_tiles, target_tile),
        winning_tile=target_tile,
        melds=player.melds,
        seat_wind=view.seat_winds[seat],
        prevailing_wind=view.prevailing_wind,
        riichi_status=player.riichi_status,
        is_ippatsu=player.is_ippatsu,
        is_furiten=player.is_furiten,
        origin=origin,
        is_last_tile=is_last_tile,
        rules=view.rules,
    )


def _is_kokushi_ankan_ron(view: RoundView, seat: Seat, target_tile: Tile) -> bool:
    player = view.players[seat]
    if not is_kokushi_win((*player.hand_tiles, target_tile), player.melds):
        return False
    return _can_ron(
        view,
        seat,
        target_tile,
        origin=WinOrigin.ANKAN,
        is_last_tile=False,
    )


def _leaves_tenpai(player: PlayerState, tile_id: int) -> bool:
    trial_player = player.copy()
    trial_player.discard_tile(tile_id, is_tsumogiri=False)
    return bool(find_winning_tile_types(trial_player.hand_tiles, trial_player.melds))


def _is_constructible(
    meld_type: type,
    called_tile: Tile,
    consumed_tiles: tuple[Tile, ...],
    source_seat: Seat,
) -> bool:
    try:
        meld_type(called_tile, consumed_tiles, source_seat)
    except ValueError:
        return False
    return True


def _sorted_hand(player: PlayerState) -> tuple[Tile, ...]:
    return tuple(sorted(player.hand_tiles, key=lambda tile: tile.id))
