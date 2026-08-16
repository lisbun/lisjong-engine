import unittest

from _round_fixtures import tiles

from lisjong_engine.meld import Chi
from lisjong_engine.ron_legality import can_declare_ron, is_kokushi_win
from lisjong_engine.rules import RuleSet
from lisjong_engine.seat import Seat
from lisjong_engine.win_context import RiichiStatus, WinOrigin
from lisjong_engine.wind import Wind

_RULES = RuleSet.default()

# 2m3m4m 5m6m7m 2p3p4p 5p6p7p 2s2s。7pでのロンでタンヤオが付く。
_TANYAO_HAND = tiles(
    "2m", "3m", "4m", "5m", "6m", "7m", "2p", "3p", "4p", "5p", "6p", "7p", "2s", "2s"
)
_TANYAO_WINNING_TILE = _TANYAO_HAND[11]

# 1m2m3mのチーを含み、9pのロンでも役が付かない開かれた手。
_OPEN_MELD = Chi(tiles("1m")[0], tiles("2m", "3m"), Seat.EAST)
_NO_YAKU_HAND = tiles("5m", "6m", "7m", "2p", "3p", "4p", "7p", "8p", "9p", "1s", "1s")
_NO_YAKU_WINNING_TILE = _NO_YAKU_HAND[8]

# 9mが2枚の国士無双単騎。1mでのみ和了できる。
_KOKUSHI_HAND = tiles(
    "1m", "9m", "9m", "1p", "9p", "1s", "9s", "1z", "2z", "3z", "4z", "5z", "6z", "7z"
)
_KOKUSHI_WINNING_TILE = _KOKUSHI_HAND[0]


def _can_ron(
    *,
    concealed_tiles=_TANYAO_HAND,
    winning_tile=_TANYAO_WINNING_TILE,
    melds=(),
    riichi_status=RiichiStatus.NONE,
    is_ippatsu=False,
    is_furiten=False,
    origin=WinOrigin.DISCARD,
    is_last_tile=False,
    rules=_RULES,
) -> bool:
    return can_declare_ron(
        concealed_tiles=concealed_tiles,
        winning_tile=winning_tile,
        melds=melds,
        seat_wind=Wind.SOUTH,
        prevailing_wind=Wind.EAST,
        riichi_status=riichi_status,
        is_ippatsu=is_ippatsu,
        is_furiten=is_furiten,
        origin=origin,
        is_last_tile=is_last_tile,
        rules=rules,
    )


class CanDeclareRonTest(unittest.TestCase):
    def test_accepts_a_complete_hand_with_a_yaku(self) -> None:
        self.assertTrue(_can_ron())

    def test_a_furiten_seat_cannot_ron(self) -> None:
        self.assertFalse(_can_ron(is_furiten=True))

    def test_an_incomplete_hand_cannot_ron(self) -> None:
        self.assertFalse(
            _can_ron(
                concealed_tiles=_TANYAO_HAND[:-1] + tiles("9s"),
                winning_tile=_TANYAO_WINNING_TILE,
            )
        )

    def test_a_complete_hand_without_a_yaku_cannot_ron(self) -> None:
        self.assertFalse(
            _can_ron(
                concealed_tiles=_NO_YAKU_HAND,
                winning_tile=_NO_YAKU_WINNING_TILE,
                melds=(_OPEN_MELD,),
            )
        )

    def test_riichi_alone_is_enough_for_a_closed_hand(self) -> None:
        closed_no_yaku = tiles(
            "1m",
            "2m",
            "3m",
            "5m",
            "6m",
            "7m",
            "2p",
            "3p",
            "4p",
            "7p",
            "8p",
            "9p",
            "1s",
            "1s",
        )

        # 8pの嵌張待ちにして、平和が付かない形にする。
        winning_tile = closed_no_yaku[10]

        self.assertFalse(
            _can_ron(concealed_tiles=closed_no_yaku, winning_tile=winning_tile)
        )
        self.assertTrue(
            _can_ron(
                concealed_tiles=closed_no_yaku,
                winning_tile=winning_tile,
                riichi_status=RiichiStatus.RIICHI,
            )
        )

    def test_a_kakan_ron_always_has_the_chankan_yaku(self) -> None:
        self.assertTrue(
            _can_ron(
                concealed_tiles=_NO_YAKU_HAND,
                winning_tile=_NO_YAKU_WINNING_TILE,
                melds=(_OPEN_MELD,),
                origin=WinOrigin.KAKAN,
            )
        )

    def test_an_ankan_ron_needs_a_yaku_of_its_own(self) -> None:
        self.assertFalse(
            _can_ron(
                concealed_tiles=_NO_YAKU_HAND,
                winning_tile=_NO_YAKU_WINNING_TILE,
                melds=(_OPEN_MELD,),
                origin=WinOrigin.ANKAN,
            )
        )
        self.assertTrue(
            _can_ron(
                concealed_tiles=_KOKUSHI_HAND,
                winning_tile=_KOKUSHI_WINNING_TILE,
                origin=WinOrigin.ANKAN,
            )
        )

    def test_contradictory_facts_are_rejected_as_illegal(self) -> None:
        """立直していない一発など、和了として矛盾する事実は候補にならない。"""
        self.assertFalse(_can_ron(is_ippatsu=True))
        self.assertFalse(_can_ron(origin=WinOrigin.KAKAN, is_last_tile=True))

    def test_rejects_invalid_arguments(self) -> None:
        with self.assertRaises(TypeError):
            _can_ron(is_furiten="no")
        with self.assertRaises(TypeError):
            _can_ron(rules="standard")


class IsKokushiWinTest(unittest.TestCase):
    def test_recognises_a_completed_thirteen_orphans(self) -> None:
        self.assertTrue(is_kokushi_win(_KOKUSHI_HAND))

    def test_rejects_a_standard_winning_hand(self) -> None:
        self.assertFalse(is_kokushi_win(_TANYAO_HAND))

    def test_rejects_an_incomplete_hand(self) -> None:
        self.assertFalse(is_kokushi_win(_KOKUSHI_HAND[:-1]))


if __name__ == "__main__":
    unittest.main()
