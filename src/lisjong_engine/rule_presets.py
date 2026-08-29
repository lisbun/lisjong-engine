"""具体的な`RuleSet`presetと、その外部ルール由来のprovenanceを保持するmodule。

`rules.py`が「ルール設定を表現する型」の正本であるのに対し、本moduleは
「実際に使う設定値の組み合わせ」の正本である。engine mechanicsは今までどおり
`RuleSet`の具体fieldとpolicy enumだけを参照し、preset名やサービス名では
分岐しない。`name`・`version`はidentity / provenance / ログ・再現性のための
metadataであり、mechanicsの分岐条件ではない。

presetは4つある。

- `PROJECT_STANDARD_RULES`: `RuleSet.default()`が表すproject標準ルール
- `TENHOU_RULES`: 天鳳・四人東南喰赤段位戦
- `MAHJONG_SOUL_RULES`: 雀魂・四人東南喰赤段位戦
- `M_LEAGUE_RULES`: Mリーグ・四人東南戦

外部サービスの3 presetは`dataclasses.replace(RuleSet.default(), ...)`で作らず、
独立した完全定義とする。project標準を将来変更しても外部サービスのルールへ
暗黙に伝播させないため、また外部presetそのものを独立した契約として保持する
ためである。外部サービスのルールが将来変わった場合は、既存presetの意味を
黙って書き換えず、`version`を上げた別presetとして追加する。

各presetのprovenanceは、そのpresetの直前のコメントに記載する。値だけを写して
出典を失わないこと、および出典を推測で補わないことを、本moduleの契約とする。
"""

from lisjong_engine.rules import (
    FinalPointsRounding,
    FinalRankTiePolicy,
    KanDoraRevealPolicy,
    MatchFormat,
    MultipleRonAwardPolicy,
    PaoCompoundYakumanPolicy,
    RiichiAnkanPolicy,
    RonResolutionPolicy,
    RuleSet,
)
from lisjong_engine.yaku import Yaku

# project標準ルール`project-standard-v1`。`RuleSet.default()`の契約そのもので
# あり、本moduleはその別名を提供するだけでルールの意味を再定義しない。
# `RuleSet.default()`は呼び出しごとに等価な値を返すため、
# `PROJECT_STANDARD_RULES == RuleSet.default()`は成立するが、同一instanceで
# あることは契約しない。
PROJECT_STANDARD_RULES = RuleSet.default()


# 天鳳・四人打ち・東南戦・喰いタンあり・赤あり段位戦。
#
# provenance: 旧`python-study`では、2026-08-08時点の天鳳公式マニュアル
# （https://tenhou.net/man/index.html）を正本として値を確定した。本presetは
# その確定値をそのまま移管したものであり、engine側で新たに外部sourceを参照
# したり、未確認のルールを推測で補ったりしていない。
TENHOU_RULES = RuleSet(
    name="tenhou-4p-east-south-red-v1",
    version=1,
    match_format=MatchFormat.HANCHAN,
    player_count=4,
    starting_points=25_000,
    return_points=30_000,
    first_place_target_points=30_000,
    uma=(20, 10, -10, -20),
    bankruptcy_enabled=True,
    bankruptcy_threshold=0,
    west_round_enabled=True,
    dealer_win_end_enabled=True,
    dealer_tenpai_end_enabled=True,
    rounded_mangan_enabled=False,
    counted_yakuman_enabled=True,
    multiple_yakuman_enabled=True,
    ron_honba_points=300,
    tsumo_honba_points_per_payer=100,
    riichi_stick_points=1_000,
    noten_penalty_total=3_000,
    nagashi_mangan_enabled=True,
    pao_enabled=True,
    pao_yaku=frozenset({Yaku.DAISANGEN, Yaku.DAISUUSHII}),
    pao_compound_yakuman_policy=PaoCompoundYakumanPolicy.FULL_HAND,
    double_ron_enabled=True,
    ron_resolution_policy=RonResolutionPolicy.MULTIPLE_RON,
    triple_ron_abortive_draw=True,
    multiple_ron_honba_policy=MultipleRonAwardPolicy.NEAREST_WINNER_TO_DISCARDER,
    multiple_ron_riichi_stick_policy=(
        MultipleRonAwardPolicy.NEAREST_WINNER_TO_DISCARDER
    ),
    nine_terminals_abortive_draw_enabled=True,
    four_winds_abortive_draw_enabled=True,
    four_kans_abortive_draw_enabled=True,
    four_riichi_abortive_draw_enabled=True,
    final_points_rounding=FinalPointsRounding.EXACT_NO_ROUNDING,
    final_rank_tie_policy=FinalRankTiePolicy.SEAT_ORDER,
    bankruptcy_bonus_points=0,
    bankrupt_player_penalty_points=0,
    riichi_ankan_policy=RiichiAnkanPolicy.PRESERVE_WAIT_ONLY,
    kan_dora_reveal_policy=KanDoraRevealPolicy.DELAY_OPEN_KAN_DORA,
    kokushi_ankan_chankan_enabled=False,
    riichi_minimum_points=1_000,
    riichi_minimum_live_wall_tiles=4,
    double_yakuman_variants=frozenset(),
    double_wind_pair_fu=4,
)


# 雀魂・四人打ち・東南戦・喰いタンあり・赤あり段位戦。
#
# provenance: 旧`python-study`では、ユーザーが確認・転記した「段位戦ルール
# 説明」を正本として値を確定した。公開URLを正本として記録していないため、
# engine側でも外部source URLを新たに推測・補完しない。ルール確認をやり直す
# 場合は、同じ「段位戦ルール説明」を改めて確認する必要がある。
#
# `return_points`（25,000）と`first_place_target_points`（30,000）が分かれる
# 唯一のpresetであり、この2 fieldが独立した概念であることの実例でもある。
MAHJONG_SOUL_RULES = RuleSet(
    name="mahjong-soul-4p-east-south-red-v1",
    version=1,
    match_format=MatchFormat.HANCHAN,
    player_count=4,
    starting_points=25_000,
    return_points=25_000,
    first_place_target_points=30_000,
    uma=(15, 5, -5, -15),
    bankruptcy_enabled=True,
    bankruptcy_threshold=0,
    west_round_enabled=True,
    dealer_win_end_enabled=True,
    dealer_tenpai_end_enabled=True,
    rounded_mangan_enabled=False,
    counted_yakuman_enabled=True,
    multiple_yakuman_enabled=True,
    ron_honba_points=300,
    tsumo_honba_points_per_payer=100,
    riichi_stick_points=1_000,
    noten_penalty_total=3_000,
    nagashi_mangan_enabled=True,
    pao_enabled=True,
    pao_yaku=frozenset({Yaku.DAISANGEN, Yaku.DAISUUSHII}),
    pao_compound_yakuman_policy=PaoCompoundYakumanPolicy.FULL_HAND,
    double_ron_enabled=True,
    ron_resolution_policy=RonResolutionPolicy.MULTIPLE_RON,
    # 三家和を途中流局にせず、通常の複数ロンとして3人全員を成立させる。
    triple_ron_abortive_draw=False,
    multiple_ron_honba_policy=MultipleRonAwardPolicy.NEAREST_WINNER_TO_DISCARDER,
    multiple_ron_riichi_stick_policy=(
        MultipleRonAwardPolicy.NEAREST_WINNER_TO_DISCARDER
    ),
    nine_terminals_abortive_draw_enabled=True,
    four_winds_abortive_draw_enabled=True,
    four_kans_abortive_draw_enabled=True,
    four_riichi_abortive_draw_enabled=True,
    final_points_rounding=FinalPointsRounding.EXACT_NO_ROUNDING,
    final_rank_tie_policy=FinalRankTiePolicy.SEAT_ORDER,
    bankruptcy_bonus_points=0,
    bankrupt_player_penalty_points=0,
    riichi_ankan_policy=RiichiAnkanPolicy.PRESERVE_WAIT_ONLY,
    kan_dora_reveal_policy=KanDoraRevealPolicy.DELAY_OPEN_KAN_DORA,
    kokushi_ankan_chankan_enabled=True,
    riichi_minimum_points=1_000,
    riichi_minimum_live_wall_tiles=4,
    # 旧`python-study`の`MAHJONG_SOUL_RANKED_YAKU_RULES`が採用していた
    # ダブル役満4種。4 preset中、ダブル役満を採用するのは雀魂だけである。
    double_yakuman_variants=frozenset(
        {
            Yaku.SUUANKOU_TANKI,
            Yaku.KOKUSHI_MUSOU_13_WAIT,
            Yaku.DAISUUSHII,
            Yaku.JUNSEI_CHUUREN_POUTOU,
        }
    ),
    double_wind_pair_fu=4,
)


# Mリーグ・四人打ち・東南戦。
#
# provenance: 旧`python-study`では、同repositoryのIssue #74本文に整理した
# 設定一覧を正本として値を確定した。本presetはその確定値の移管である。
#
# Mリーグ公式ルールの完全再現ではなく、次のproject差分を意図的に持つ。
#
# - 荒牌流局時の聴牌・ノーテン申告用の専用Actionは実装しない。申告ではなく
#   実手牌の聴牌状態をそのまま使って流局時の精算を行う。
#
# この差分は`RuleSet`のfieldでは表現しない実装方針上の差分であり、preset値の
# 更新で消えるものではない。将来Mリーグpresetを見直す場合も、この差分を
# 意図せず失わないこと。
M_LEAGUE_RULES = RuleSet(
    name="m-league-4p-east-south-v1",
    version=1,
    match_format=MatchFormat.HANCHAN,
    player_count=4,
    starting_points=25_000,
    return_points=30_000,
    first_place_target_points=30_000,
    uma=(30, 10, -10, -30),
    bankruptcy_enabled=False,
    bankruptcy_threshold=0,
    west_round_enabled=False,
    dealer_win_end_enabled=False,
    dealer_tenpai_end_enabled=False,
    rounded_mangan_enabled=True,
    counted_yakuman_enabled=False,
    multiple_yakuman_enabled=True,
    ron_honba_points=300,
    tsumo_honba_points_per_payer=100,
    riichi_stick_points=1_000,
    noten_penalty_total=3_000,
    nagashi_mangan_enabled=False,
    pao_enabled=True,
    pao_yaku=frozenset({Yaku.DAISANGEN, Yaku.DAISUUSHII, Yaku.SUUKANTSU}),
    pao_compound_yakuman_policy=PaoCompoundYakumanPolicy.RESPONSIBLE_YAKUMAN_ONLY,
    # 頭ハネでは和了者が常に1名へ確定し、ダブロン自体が起こり得ないため、
    # `double_ron_enabled`・`triple_ron_abortive_draw`も意味的に整合させる。
    double_ron_enabled=False,
    ron_resolution_policy=RonResolutionPolicy.HEAD_BUMP,
    triple_ron_abortive_draw=False,
    multiple_ron_honba_policy=MultipleRonAwardPolicy.NEAREST_WINNER_TO_DISCARDER,
    multiple_ron_riichi_stick_policy=(
        MultipleRonAwardPolicy.NEAREST_WINNER_TO_DISCARDER
    ),
    nine_terminals_abortive_draw_enabled=False,
    four_winds_abortive_draw_enabled=False,
    four_kans_abortive_draw_enabled=False,
    four_riichi_abortive_draw_enabled=False,
    final_points_rounding=FinalPointsRounding.EXACT_NO_ROUNDING,
    final_rank_tie_policy=FinalRankTiePolicy.SPLIT_RANK_POINTS,
    bankruptcy_bonus_points=0,
    bankrupt_player_penalty_points=0,
    riichi_ankan_policy=RiichiAnkanPolicy.PRESERVE_WAIT_AND_DECOMPOSITION,
    kan_dora_reveal_policy=KanDoraRevealPolicy.IMMEDIATE_ON_KAN_CONFIRMATION,
    kokushi_ankan_chankan_enabled=False,
    # 持ち点の下限なし。0点未満でも立直を宣言できる。
    riichi_minimum_points=None,
    # 海底牌をツモった直後の立直だけを禁止する。
    riichi_minimum_live_wall_tiles=1,
    double_yakuman_variants=frozenset(),
    double_wind_pair_fu=2,
)
