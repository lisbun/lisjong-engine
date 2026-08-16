"""局のtestで共有する、決定的な局面fixtureとdriver helper。

山の並びを固定して配牌とツモ順を指定できるようにし、test側が
`RoundState`のcore API（`legal_actions()` / `apply()` /
`resolve_reactions()`）だけで目的の局面へ到達できるようにする。

内部状態を直接書き換えるbackdoorは用意しない。fixtureが作るのは初期の
山とMatchからの入力（局開始時点の持ち点snapshot）までであり、そこから
先はすべて公開APIで駆動する。
"""

from lisjong_engine.legal_action import (
    ChiLegalAction,
    DaiminkanLegalAction,
    DiscardDeclaration,
    DiscardLegalAction,
    LegalAction,
    PassLegalAction,
    PonLegalAction,
    RonLegalAction,
)
from lisjong_engine.reaction import ReactionResolution
from lisjong_engine.round_phase import RoundPhase
from lisjong_engine.round_state import RoundState
from lisjong_engine.rules import RuleSet
from lisjong_engine.seat import Seat
from lisjong_engine.tile import STANDARD_TILES, Tile, TileCategory, TileType
from lisjong_engine.wall import Wall

TILE_CATEGORIES = {
    "m": TileCategory.MANZU,
    "p": TileCategory.PINZU,
    "s": TileCategory.SOUZU,
    "z": TileCategory.HONOR,
}
LIVE_WALL_SIZE = 70
FIRST_DRAW_POSITION = 52
DEAD_WALL_SIZE = 14

# 誰も反応できない局面を作るための配牌。各席は同じ牌種を2枚以上持たず、
# 白（5z）・發（6z）を1枚も持たない。ツモ牌をすべて白・發にすることで、
# ポン・チー・大明槓・ロンのいずれの必要条件も満たさなくなる。
QUIET_HANDS = {
    Seat.EAST: (
        "1m",
        "4m",
        "7m",
        "1p",
        "4p",
        "7p",
        "1s",
        "4s",
        "7s",
        "1z",
        "2z",
        "3z",
        "4z",
    ),
    Seat.SOUTH: (
        "2m",
        "5m",
        "8m",
        "2p",
        "5p",
        "8p",
        "2s",
        "5s",
        "8s",
        "1z",
        "2z",
        "3z",
        "4z",
    ),
    Seat.WEST: (
        "3m",
        "6m",
        "9m",
        "3p",
        "6p",
        "9p",
        "3s",
        "6s",
        "9s",
        "1z",
        "2z",
        "3z",
        "4z",
    ),
    Seat.NORTH: (
        "1m",
        "4m",
        "7m",
        "1p",
        "4p",
        "7p",
        "1s",
        "4s",
        "7s",
        "1z",
        "2z",
        "3z",
        "4z",
    ),
}
QUIET_DRAWS = ("5z", "5z", "5z", "5z", "6z", "6z", "6z", "6z")

# 反応できない席へ配る、局面を汚さない13枚。同じ牌種を2枚以上持たず、
# 順子候補も作らない。
INERT_HAND = (
    "1m",
    "4m",
    "7m",
    "1p",
    "4p",
    "7p",
    "1s",
    "4s",
    "7s",
    "1z",
    "2z",
    "3z",
    "4z",
)


def tile_type(name: str) -> TileType:
    return TileType(TILE_CATEGORIES[name[-1]], int(name[:-1]))


def tiles(*names: str) -> tuple[Tile, ...]:
    """牌種名の並びから、同種は別copyになる物理牌を作る。"""
    copy_counts: dict[TileType, int] = {}
    built = []
    for name in names:
        target = tile_type(name)
        copy_index = copy_counts.get(target, 0)
        built.append(STANDARD_TILES[target.id * 4 + copy_index])
        copy_counts[target] = copy_index + 1
    return tuple(built)


def take(pool: list[Tile], names: tuple[str, ...]) -> tuple[Tile, ...]:
    """`pool`から牌種名の並びどおりに物理牌を取り出す。"""
    taken = []
    for name in names:
        expected = tile_type(name)
        index = next(
            index for index, tile in enumerate(pool) if tile.tile_type == expected
        )
        taken.append(pool.pop(index))
    return tuple(taken)


def deal_positions(dealer_seat: Seat) -> dict[Seat, tuple[int, ...]]:
    """配牌順（親から4枚ずつ3巡＋1枚ずつ）に対応する山のindexを返す。"""
    seats = tuple(Seat)
    start = seats.index(dealer_seat)
    deal_order = tuple(seats[(start + offset) % len(seats)] for offset in range(4))
    return {
        seat: (
            *range(order * 4, order * 4 + 4),
            *range(16 + order * 4, 16 + order * 4 + 4),
            *range(32 + order * 4, 32 + order * 4 + 4),
            48 + order,
        )
        for order, seat in enumerate(deal_order)
    }


def build_wall(
    *,
    hands: dict[Seat, tuple[str, ...]],
    draws: tuple[str, ...] = (),
    dealer_seat: Seat = Seat.EAST,
    with_dead_wall: bool = False,
    dead_wall: tuple[str, ...] = (),
) -> Wall:
    """指定した配牌とツモ順になる山を組み立てる。

    `dead_wall`を指定した場合、先頭4枚が嶺上牌の取得順、続く10枚が
    表・裏表示牌の5組になる。
    """
    pool = list(STANDARD_TILES)
    dead_wall_tiles = take(pool, dead_wall) if dead_wall else ()
    drawn_tiles = take(pool, draws)
    hand_tiles = {seat: take(pool, names) for seat, names in hands.items()}

    wall_tiles: list[Tile | None] = [None] * LIVE_WALL_SIZE
    for seat, positions in deal_positions(dealer_seat).items():
        for position, tile in zip(positions, hand_tiles[seat], strict=True):
            wall_tiles[position] = tile
    for offset, tile in enumerate(drawn_tiles):
        wall_tiles[FIRST_DRAW_POSITION + offset] = tile
    for index, tile in enumerate(wall_tiles):
        if tile is None:
            wall_tiles[index] = pool.pop(0)

    if not dead_wall_tiles and with_dead_wall:
        dead_wall_tiles = tuple(pool.pop(0) for _ in range(DEAD_WALL_SIZE))
    return Wall(tuple(wall_tiles), dead_wall_tiles)


def starting_points(rules: RuleSet | None = None) -> dict[Seat, int]:
    """東1局相当の、全席が配給原点の持ち点snapshot。"""
    resolved_rules = RuleSet.default() if rules is None else rules
    return {seat: resolved_rules.starting_points for seat in Seat}


def new_state(
    wall: Wall,
    *,
    round_start_points: dict[Seat, int] | None = None,
    rules: RuleSet | None = None,
    **kwargs,
) -> RoundState:
    return RoundState(
        wall,
        round_start_points=(
            starting_points(rules) if round_start_points is None else round_start_points
        ),
        rules=rules,
        **kwargs,
    )


def dealt_state(
    *,
    round_start_points: dict[Seat, int] | None = None,
    rules: RuleSet | None = None,
    dealer_seat: Seat = Seat.EAST,
    **wall_kwargs,
) -> RoundState:
    state = new_state(
        build_wall(dealer_seat=dealer_seat, **wall_kwargs),
        round_start_points=round_start_points,
        rules=rules,
        dealer_seat=dealer_seat,
    )
    state.deal()
    return state


def quiet_state(**kwargs) -> RoundState:
    return dealt_state(hands=QUIET_HANDS, draws=QUIET_DRAWS, **kwargs)


def capture(state: RoundState) -> tuple:
    """failure atomicityの確認に使う、観測可能な状態のすべて。"""
    return (
        state.phase,
        state.current_seat,
        state.revision,
        state.drawn_tile_id,
        state.drawn_tile_source,
        state.remaining_tiles,
        state.dead_wall_tiles,
        state.revealed_dora_indicators,
        state.pending_discarder,
        state.pending_discard,
        state.pending_discard_source,
        state.pending_kakan,
        state.pending_ankan,
        state.pending_riichi_declaration,
        state.pending_ron_resolution,
        state.pending_kan_dora_reveals,
        state.riichi_finalizations,
        state.riichi_contributions,
        dict(state.riichi_payment_deltas),
        dict(state.round_start_points),
        tuple(state.hand_tiles(seat) for seat in Seat),
        tuple(state.discards(seat) for seat in Seat),
        tuple(state.melds(seat) for seat in Seat),
        tuple(state.riichi_status(seat) for seat in Seat),
        tuple(state.is_ippatsu(seat) for seat in Seat),
        tuple(state.furiten_reasons(seat) for seat in Seat),
        tuple(state.suukantsu_pao_seat(seat) for seat in Seat),
        state.events,
    )


def actions_of(state: RoundState, seat: Seat) -> tuple[LegalAction, ...]:
    return state.legal_actions(seat).actions


def action_of_type(
    state: RoundState,
    seat: Seat,
    action_type: type,
) -> LegalAction:
    """`seat`の合法手から、指定した種別の最初のactionを返す。"""
    return next(
        action for action in actions_of(state, seat) if isinstance(action, action_type)
    )


def has_action_of_type(state: RoundState, seat: Seat, action_type: type) -> bool:
    return any(isinstance(action, action_type) for action in actions_of(state, seat))


def pass_action(state: RoundState, seat: Seat) -> PassLegalAction:
    return action_of_type(state, seat, PassLegalAction)


def ron_action(state: RoundState, seat: Seat) -> RonLegalAction:
    return action_of_type(state, seat, RonLegalAction)


def pon_action(state: RoundState, seat: Seat) -> PonLegalAction:
    return action_of_type(state, seat, PonLegalAction)


def chi_action(state: RoundState, seat: Seat) -> ChiLegalAction:
    return action_of_type(state, seat, ChiLegalAction)


def daiminkan_action(state: RoundState, seat: Seat) -> DaiminkanLegalAction:
    return action_of_type(state, seat, DaiminkanLegalAction)


def draw_and_discard(
    state: RoundState,
    seat: Seat,
    tile_name: str | None = None,
    *,
    declaration: DiscardDeclaration = DiscardDeclaration.NONE,
) -> Tile:
    """`seat`がツモり、指定した牌種（省略時はツモ切り）を打つ。"""
    drawn_tile = state.draw(seat)
    if tile_name is None:
        target = drawn_tile
    else:
        expected = tile_type(tile_name)
        target = next(
            tile for tile in state.hand_tiles(seat) if tile.tile_type == expected
        )
    snapshot = state.legal_actions(seat)
    state.apply(
        seat,
        DiscardLegalAction(target.id, declaration),
        expected_revision=snapshot.revision,
    )
    return target


def discard_drawn_tile(state: RoundState, seat: Seat) -> Tile:
    """ツモった牌をそのまま打つ。嶺上ツモ後の打牌でも使える。"""
    target = next(
        tile for tile in state.hand_tiles(seat) if tile.id == state.drawn_tile_id
    )
    snapshot = state.legal_actions(seat)
    state.apply(
        seat,
        DiscardLegalAction(target.id),
        expected_revision=snapshot.revision,
    )
    return target


def discard(
    state: RoundState,
    seat: Seat,
    tile_name: str,
    *,
    declaration: DiscardDeclaration = DiscardDeclaration.NONE,
) -> Tile:
    """ツモを伴わない打牌（鳴き直後など）を行う。"""
    expected = tile_type(tile_name)
    target = next(tile for tile in state.hand_tiles(seat) if tile.tile_type == expected)
    snapshot = state.legal_actions(seat)
    state.apply(
        seat,
        DiscardLegalAction(target.id, declaration),
        expected_revision=snapshot.revision,
    )
    return target


def all_pass_choices(state: RoundState) -> dict[Seat, LegalAction]:
    return {seat: pass_action(state, seat) for seat in state.reacting_seats}


def resolve_all_pass(state: RoundState) -> ReactionResolution:
    return state.resolve_reactions(
        all_pass_choices(state),
        expected_revision=state.revision,
    )


def resolve_with(
    state: RoundState,
    overrides: dict[Seat, LegalAction],
) -> ReactionResolution:
    """指定した席だけ非パスにし、残りはパスで反応windowを解決する。"""
    choices = all_pass_choices(state)
    choices.update(overrides)
    return state.resolve_reactions(choices, expected_revision=state.revision)


def play_quiet_turn(state: RoundState) -> None:
    """現在の席がツモ切りし、反応windowが開けば全員パスで閉じる。"""
    draw_and_discard(state, state.current_seat)
    if state.phase is RoundPhase.AWAITING_REACTIONS:
        resolve_all_pass(state)


def advance_to_seat(state: RoundState, seat: Seat) -> None:
    """`seat`のツモ番になるまで、他家をツモ切りで進める。"""
    while state.current_seat is not seat:
        play_quiet_turn(state)
