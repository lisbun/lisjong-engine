from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from lisjong_engine.meld import Ankan, Meld
from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile
from lisjong_engine.wind import Wind


class WinMethod(Enum):
    TSUMO = "tsumo"
    RON = "ron"


class WinOrigin(Enum):
    LIVE_WALL = "live_wall"
    RINSHAN = "rinshan"
    DISCARD = "discard"
    KAKAN = "kakan"
    # 国士無双限定の暗槓ロン（槍槓）。どのruleで発生を許すかはRuleSetの、
    # 実際に発生させるかは局進行の責務であり、ここでは和了元がどこだったか
    # という事実だけを表す。
    ANKAN = "ankan"


class RiichiStatus(Enum):
    NONE = "none"
    RIICHI = "riichi"
    DOUBLE_RIICHI = "double_riichi"


@dataclass(frozen=True)
class WinningContext:
    """和了成立時点で確定している事実を保持する、変更不能な入力値。

    役・符・ドラ・点数の評価はこの値型を入口とする。ここでは局進行状態や
    rule設定を保持せず、評価側が後から復元できない事実だけを受け取る。
    """

    concealed_tiles: tuple[Tile, ...]
    winning_tile: Tile
    method: WinMethod
    origin: WinOrigin
    seat_wind: Wind
    prevailing_wind: Wind
    declared_melds: tuple[Meld, ...] = ()
    riichi_status: RiichiStatus = RiichiStatus.NONE
    is_ippatsu: bool = False
    is_last_tile: bool = False
    is_first_uninterrupted_turn: bool = False
    # 四槓子パオの責任者席。加槓は元のポンの位置のまま差し替わるため、
    # 最終的な`declared_melds`の並び順からは「大明槓成立時点で既に3槓
    # あったか」を復元できない。そのため責任成立は大明槓の成立時点で
    # 判定し、その結果を和了時点の事実としてここへ保持する。
    suukantsu_pao_seat: Seat | None = None

    def __post_init__(self) -> None:
        concealed_tiles = _normalize_tiles(self.concealed_tiles)
        declared_melds = _normalize_melds(self.declared_melds)

        if not isinstance(self.winning_tile, Tile):
            raise TypeError("winning_tile must be a Tile")
        if all(tile.id != self.winning_tile.id for tile in concealed_tiles):
            raise ValueError("winning_tile must be in concealed_tiles")
        if not isinstance(self.method, WinMethod):
            raise TypeError("method must be a WinMethod")
        if not isinstance(self.origin, WinOrigin):
            raise TypeError("origin must be a WinOrigin")
        if not isinstance(self.seat_wind, Wind):
            raise TypeError("seat_wind must be a Wind")
        if not isinstance(self.prevailing_wind, Wind):
            raise TypeError("prevailing_wind must be a Wind")
        if not isinstance(self.riichi_status, RiichiStatus):
            raise TypeError("riichi_status must be a RiichiStatus")
        if self.suukantsu_pao_seat is not None and not isinstance(
            self.suukantsu_pao_seat, Seat
        ):
            raise TypeError("suukantsu_pao_seat must be a Seat or None")
        if any(
            type(value) is not bool
            for value in (
                self.is_ippatsu,
                self.is_last_tile,
                self.is_first_uninterrupted_turn,
            )
        ):
            raise TypeError("winning context flags must be bools")

        _validate_unique_physical_tiles(
            concealed_tiles,
            declared_melds,
        )
        _validate_method_and_origin(self.method, self.origin)

        object.__setattr__(self, "concealed_tiles", concealed_tiles)
        object.__setattr__(self, "declared_melds", declared_melds)

        if self.riichi_status is not RiichiStatus.NONE and not self.is_menzen:
            raise ValueError("riichi requires a menzen hand")
        if self.is_ippatsu and self.riichi_status is RiichiStatus.NONE:
            raise ValueError("ippatsu requires riichi")
        if self.is_ippatsu and self.origin is WinOrigin.RINSHAN:
            raise ValueError("ippatsu and rinshan cannot coexist")
        if self.is_last_tile and self.origin not in (
            WinOrigin.LIVE_WALL,
            WinOrigin.DISCARD,
        ):
            raise ValueError(
                "last-tile win must originate from the live wall or discard"
            )
        if self.is_first_uninterrupted_turn:
            if (
                self.method is not WinMethod.TSUMO
                or self.origin is not WinOrigin.LIVE_WALL
                or declared_melds
            ):
                raise ValueError(
                    "first uninterrupted turn must be an uncalled live-wall tsumo"
                )
            if (
                self.riichi_status is not RiichiStatus.NONE
                or self.is_ippatsu
                or self.is_last_tile
            ):
                raise ValueError("first uninterrupted turn has incompatible flags")

    @property
    def is_menzen(self) -> bool:
        """暗槓だけは門前を崩さない。"""
        return all(isinstance(meld, Ankan) for meld in self.declared_melds)

    @property
    def all_tiles(self) -> tuple[Tile, ...]:
        return self.concealed_tiles + tuple(
            tile for meld in self.declared_melds for tile in meld.tiles
        )


def _normalize_tiles(tiles: Iterable[Tile]) -> tuple[Tile, ...]:
    try:
        tile_sequence = tuple(tiles)
    except TypeError:
        raise TypeError(
            "concealed_tiles must be an iterable of Tile instances"
        ) from None
    if any(not isinstance(tile, Tile) for tile in tile_sequence):
        raise TypeError("concealed_tiles must contain only Tile instances")
    return tile_sequence


def _normalize_melds(melds: Iterable[Meld]) -> tuple[Meld, ...]:
    try:
        meld_sequence = tuple(melds)
    except TypeError:
        raise TypeError(
            "declared_melds must be an iterable of meld instances"
        ) from None
    if any(not isinstance(meld, Meld) for meld in meld_sequence):
        raise TypeError(
            "declared_melds must contain only Pon, Kakan, Chi, "
            "Daiminkan, or Ankan instances"
        )
    return meld_sequence


def _validate_unique_physical_tiles(
    concealed_tiles: tuple[Tile, ...],
    declared_melds: tuple[Meld, ...],
) -> None:
    tile_ids = tuple(tile.id for tile in concealed_tiles) + tuple(
        tile.id for meld in declared_melds for tile in meld.tiles
    )
    if len(set(tile_ids)) != len(tile_ids):
        raise ValueError(
            "concealed tiles and declared melds must not contain "
            "duplicate physical tile IDs"
        )


def _validate_method_and_origin(
    method: WinMethod,
    origin: WinOrigin,
) -> None:
    if method is WinMethod.TSUMO and origin not in (
        WinOrigin.LIVE_WALL,
        WinOrigin.RINSHAN,
    ):
        raise ValueError("tsumo must originate from a wall draw")
    if method is WinMethod.RON and origin not in (
        WinOrigin.DISCARD,
        WinOrigin.KAKAN,
        WinOrigin.ANKAN,
    ):
        raise ValueError("ron must originate from a discard, kakan, or ankan")
