import unittest
from dataclasses import replace

from lisjong_engine.rules import RuleSet
from lisjong_engine.yaku import Yaku

_EXPECTED_YAKU_NAMES = frozenset(
    {
        "MENZEN_TSUMO",
        "RIICHI",
        "IPPATSU",
        "DOUBLE_RIICHI",
        "CHANKAN",
        "RINSHAN_KAIHOU",
        "HAITEI",
        "HOUTEI",
        "TANYAO",
        "SEAT_WIND",
        "PREVAILING_WIND",
        "WHITE_DRAGON",
        "GREEN_DRAGON",
        "RED_DRAGON",
        "PINFU",
        "IIPEIKOU",
        "CHANTA",
        "ITTSUU",
        "SANSHOKU_DOUJUN",
        "SANSHOKU_DOUKOU",
        "SANKANTSU",
        "TOITOI",
        "SANANKOU",
        "SHOUSANGEN",
        "HONROUTOU",
        "CHIITOITSU",
        "JUNCHAN",
        "HONITSU",
        "RYANPEIKOU",
        "CHINITSU",
        "TENHOU",
        "CHIIHOU",
        "DAISANGEN",
        "SUUANKOU",
        "SUUANKOU_TANKI",
        "TSUUIISOU",
        "RYUUIISOU",
        "CHINROUTOU",
        "KOKUSHI_MUSOU",
        "KOKUSHI_MUSOU_13_WAIT",
        "DAISUUSHII",
        "SHOUSUUSHII",
        "SUUKANTSU",
        "CHUUREN_POUTOU",
        "JUNSEI_CHUUREN_POUTOU",
    }
)


class YakuIdentifierTest(unittest.TestCase):
    """`Yaku`は識別子契約だけを固定する。役の成立判定はIssue D以降が担う。"""

    def test_expected_identifiers_exist(self) -> None:
        self.assertEqual(
            frozenset(member.name for member in Yaku),
            _EXPECTED_YAKU_NAMES,
        )

    def test_values_follow_the_existing_naming_contract(self) -> None:
        # 旧`python-study`の`Yaku`と同じ値を維持し、将来のlog・永続化で
        # 識別子が変わらないようにする。
        for member in Yaku:
            with self.subTest(name=member.name):
                self.assertEqual(member.value, member.name.lower())

    def test_values_are_unique(self) -> None:
        self.assertEqual(len(frozenset(member.value for member in Yaku)), len(Yaku))


class YakuUsedByRuleSetTest(unittest.TestCase):
    def test_default_pao_yaku_uses_yaku_identifiers(self) -> None:
        self.assertEqual(
            RuleSet.default().pao_yaku,
            frozenset({Yaku.DAISANGEN, Yaku.DAISUUSHII}),
        )

    def test_double_yakuman_variants_use_yaku_identifiers(self) -> None:
        rules = replace(
            RuleSet.default(),
            double_yakuman_variants=frozenset({Yaku.SUUANKOU_TANKI}),
        )
        self.assertEqual(
            rules.double_yakuman_variants,
            frozenset({Yaku.SUUANKOU_TANKI}),
        )


if __name__ == "__main__":
    unittest.main()
