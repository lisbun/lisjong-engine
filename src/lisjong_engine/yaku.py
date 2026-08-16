"""役の識別子だけを定義するmodule。

`Yaku`は「どの役か」を指す名前であり、翻数、日本語名、成立条件、
和了手からの役判定logicは持たない。役の評価は後続の得点評価層が担当し、
本moduleへ依存する。

この分離により、依存方向を次で固定する。

```text
Yaku identifier -> RuleSet
Yaku identifier -> yaku evaluation
RuleSet -X-> yaku evaluation
```

`RuleSet`はパオ対象役やダブル役満の種類を役の識別子で指定するだけであり、
役判定logicへは依存しない。
"""

from enum import Enum


class Yaku(Enum):
    MENZEN_TSUMO = "menzen_tsumo"
    RIICHI = "riichi"
    IPPATSU = "ippatsu"
    DOUBLE_RIICHI = "double_riichi"
    CHANKAN = "chankan"
    RINSHAN_KAIHOU = "rinshan_kaihou"
    HAITEI = "haitei"
    HOUTEI = "houtei"
    TANYAO = "tanyao"
    SEAT_WIND = "seat_wind"
    PREVAILING_WIND = "prevailing_wind"
    WHITE_DRAGON = "white_dragon"
    GREEN_DRAGON = "green_dragon"
    RED_DRAGON = "red_dragon"
    PINFU = "pinfu"
    IIPEIKOU = "iipeikou"
    CHANTA = "chanta"
    ITTSUU = "ittsuu"
    SANSHOKU_DOUJUN = "sanshoku_doujun"
    SANSHOKU_DOUKOU = "sanshoku_doukou"
    SANKANTSU = "sankantsu"
    TOITOI = "toitoi"
    SANANKOU = "sanankou"
    SHOUSANGEN = "shousangen"
    HONROUTOU = "honroutou"
    CHIITOITSU = "chiitoitsu"
    JUNCHAN = "junchan"
    HONITSU = "honitsu"
    RYANPEIKOU = "ryanpeikou"
    CHINITSU = "chinitsu"
    TENHOU = "tenhou"
    CHIIHOU = "chiihou"
    DAISANGEN = "daisangen"
    SUUANKOU = "suuankou"
    SUUANKOU_TANKI = "suuankou_tanki"
    TSUUIISOU = "tsuuiisou"
    RYUUIISOU = "ryuuiisou"
    CHINROUTOU = "chinroutou"
    KOKUSHI_MUSOU = "kokushi_musou"
    KOKUSHI_MUSOU_13_WAIT = "kokushi_musou_13_wait"
    DAISUUSHII = "daisuushii"
    SHOUSUUSHII = "shousuushii"
    SUUKANTSU = "suukantsu"
    CHUUREN_POUTOU = "chuuren_poutou"
    JUNSEI_CHUUREN_POUTOU = "junsei_chuuren_poutou"
