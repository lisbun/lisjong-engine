# RuleSet と公式ルールpreset

## 1. 本書の目的

本書は `lisjong-engine` の麻雀ルール設定契約（`RuleSet`）と、
first-partyに提供する具体的なルールpresetの正本である。

`RuleSet.default()` は標準ルールセット `project-standard-v1` を表し、
`rule_presets.py` は project-standard / Tenhou / Mahjong Soul / M League の
具体的な `RuleSet` 値を提供する。

ルール仕様そのものの由来は `python-study` の `docs/mahjong-rules.md` にあるが、
本書はそれを丸ごと引き継いだものではなく、現在の `lisjong-engine` の
package構成と責務境界に合わせて再構成したものである。

## 2. RuleSetの役割

`RuleSet` は **麻雀ルールの設定値** だけを保持するfrozenな値型である。

`RuleSet` が持つもの。

- 対局形式、配給原点、返し点、終局条件
- 連荘、本場、供託、罰符
- 複数ロン、途中流局
- 立直、槓、鳴きに関するルール設定
- パオ（責任払い）
- 最終順位、順位点、端数処理
- 役判定・符計算が参照するconfig

`RuleSet` が持たないもの。

- ゲーム状態（手牌、山、河、局、席の状態）
- 状態遷移logic（合法手生成、反応解決、局進行）
- 役判定、符計算、ドラ計算、点数計算そのもの
- Policy、AI戦略

言い換えると、`RuleSet` は「どのルールで打つか」だけを表し、
「いま何が起きているか」「その結果いくらか」は表さない。
後者は、`RuleSet` を入力として受け取る別の層の責務である。

### mechanicsとconfigの分離

ゲームmechanicsは、必ず `RuleSet` の具体的なfieldまたはpolicy enumの値で分岐する。
ルールセット名では分岐しない。

```python
# NG: preset名による分岐
if rules.name == "mleague":
    ...

# OK: policy値による分岐
if rules.ron_resolution_policy is RonResolutionPolicy.HEAD_BUMP:
    ...
```

`name` と `version` は、ルールセットの識別、version管理、ログ、
deterministicな再現性の補助情報としてのみ使用する。
`name` に許可リストはなく、空でない任意の文字列を受理する。

## 3. module構成と依存方向

```text
src/lisjong_engine/
    yaku.py             # Yaku identifier（役の名前だけ）
    rules.py            # RuleSet と policy enum
    rule_presets.py     # first-party concrete RuleSet preset
    yaku_evaluation.py  # 役の成立判定と翻・役満倍率
    fu.py               # 符の内訳と最終符
    dora.py             # 表示牌snapshotからのドラ計数
    hand_value.py       # 役・符・ドラの統合評価
    score.py            # 支払点
    winning_score.py    # 得点候補の列挙と最高得点候補の選択
```

`rules.py` は「どのルール設定を表現できるか」という型・policyの正本、
`rule_presets.py` は「first-partyに提供する具体的な設定値の組み合わせ」の正本である。
mechanicsはどちらのpresetを使ったかを知らず、渡された `RuleSet` のfieldだけを見る。

`yaku.py` は役の **識別子** だけを定義し、翻数、日本語名、成立条件、
役判定logicを持たない。役の評価は `yaku_evaluation.py` が担当する。

```text
Yaku identifier -> RuleSet
Yaku identifier -> yaku evaluation
RuleSet -X-> yaku evaluation
```

`RuleSet` はパオ対象役やダブル役満の種類を役の識別子で指定するだけなので、
この分離により、設定型が評価logicへ依存する構造を避けられる。

得点評価層の詳細は「9. 得点評価とRuleSet」を参照。

`lisjong_engine.__init__` からの一括re-exportは行わない。利用側は責務moduleから
直接importする。

```python
from lisjong_engine.rules import RuleSet
from lisjong_engine.rule_presets import TENHOU_RULES
from lisjong_engine.yaku import Yaku
```

## 4. RuleSet.default() と first-party preset

`RuleSet.default()` は標準ルールセット `project-standard-v1`（version 1）を返す。
`rule_presets.py` の `PROJECT_STANDARD_RULES` はこのcontractをそのまま公開する。

```python
PROJECT_STANDARD_RULES == RuleSet.default()  # 保証する
RuleSet.default() == RuleSet.default()        # 保証する
RuleSet.default() is RuleSet.default()        # 保証しない
```

first-partyに提供するconcrete presetは次の4つである。

| constant | `name` | モデル化対象 |
| --- | --- | --- |
| `PROJECT_STANDARD_RULES` | `project-standard-v1` | project標準 |
| `TENHOU_RULES` | `tenhou-4p-east-south-red-v1` | 天鳳 四人打ち東南戦・喰いタンあり・赤あり段位戦 |
| `MAHJONG_SOUL_RULES` | `mahjong-soul-4p-east-south-red-v1` | 雀魂 四人東南喰赤段位戦 |
| `M_LEAGUE_RULES` | `m-league-4p-east-south-v1` | Mリーグ 四人東南戦（project上の意図的差分を含む） |

external 3 presetは `RuleSet.default()` から `dataclasses.replace()` で派生させず、
すべてのfieldを明示した独立完全定義とする。project-standardの将来変更が
external presetへ暗黙伝播しないようにするためである。

一方、callerが一時的・実験的な設定を作る用途では `dataclasses.replace()` を使ってよい。
これはcanonical external preset definitionとは別の用途である。

```python
from dataclasses import replace

rules = replace(RuleSet.default(), return_points=25_000)
```

`RuleSet` はすべてのfieldを明示的に指定して構築する（field defaultを持たない）。
将来first-party presetを追加する場合も、既存presetからの派生ではなく独立した完全定義とし、
既存ルールの変更が他のpresetへ暗黙に伝播しないようにする。

外部サービスのルールが将来変わる場合、既存presetの意味を黙って変更せず、
必要に応じて `name` / `version` を更新した新しいpresetとして扱う。

### project-standard の主要値

| 分類 | field | 値 |
| --- | --- | --- |
| 識別 | `name` | `"project-standard-v1"` |
| 識別 | `version` | `1` |
| 対局形式 | `match_format` | `MatchFormat.HANCHAN` |
| 対局形式 | `player_count` | `4` |
| 点数 | `starting_points` | `25_000` |
| 点数 | `return_points` | `30_000` |
| 点数 | `first_place_target_points` | `30_000` |
| 点数 | `uma` | `(30, 10, -10, -30)` |
| 終局 | `bankruptcy_enabled` | `True` |
| 終局 | `bankruptcy_threshold` | `0` |
| 終局 | `west_round_enabled` | `True` |
| 終局 | `dealer_win_end_enabled` | `True` |
| 終局 | `dealer_tenpai_end_enabled` | `True` |
| 得点 | `rounded_mangan_enabled` | `False` |
| 得点 | `counted_yakuman_enabled` | `True` |
| 得点 | `multiple_yakuman_enabled` | `True` |
| 本場・供託 | `ron_honba_points` | `300` |
| 本場・供託 | `tsumo_honba_points_per_payer` | `100` |
| 本場・供託 | `riichi_stick_points` | `1_000` |
| 本場・供託 | `noten_penalty_total` | `3_000` |
| 本場・供託 | `nagashi_mangan_enabled` | `True` |
| パオ | `pao_enabled` | `True` |
| パオ | `pao_yaku` | `{DAISANGEN, DAISUUSHII}` |
| パオ | `pao_compound_yakuman_policy` | `FULL_HAND` |
| 複数ロン | `double_ron_enabled` | `True` |
| 複数ロン | `ron_resolution_policy` | `MULTIPLE_RON` |
| 複数ロン | `triple_ron_abortive_draw` | `True` |
| 複数ロン | `multiple_ron_honba_policy` | `NEAREST_WINNER_TO_DISCARDER` |
| 複数ロン | `multiple_ron_riichi_stick_policy` | `NEAREST_WINNER_TO_DISCARDER` |
| 途中流局 | `nine_terminals_abortive_draw_enabled` | `True` |
| 途中流局 | `four_winds_abortive_draw_enabled` | `True` |
| 途中流局 | `four_kans_abortive_draw_enabled` | `True` |
| 途中流局 | `four_riichi_abortive_draw_enabled` | `True` |
| 最終順位 | `final_points_rounding` | `TOWARD_ZERO_REMAINDER_TO_FIRST` |
| 最終順位 | `final_rank_tie_policy` | `SEAT_ORDER` |
| 最終順位 | `bankruptcy_bonus_points` | `10` |
| 最終順位 | `bankrupt_player_penalty_points` | `-10` |
| 立直・槓 | `riichi_ankan_policy` | `PRESERVE_WAIT_AND_DECOMPOSITION` |
| 立直・槓 | `kan_dora_reveal_policy` | `DELAY_OPEN_KAN_DORA` |
| 立直・槓 | `kokushi_ankan_chankan_enabled` | `False` |
| 立直・槓 | `riichi_minimum_points` | `1_000` |
| 立直・槓 | `riichi_minimum_live_wall_tiles` | `4` |
| 役config | `double_yakuman_variants` | `frozenset()` |
| 符config | `double_wind_pair_fu` | `4` |

### 派生値

`RuleSet` は状態遷移logicを持たないが、設定値から一意に定まるpureな派生値を
propertyとして提供する。

- `oka_points`: `(return_points - starting_points) * player_count`。
  標準ルールでは 20,000点
- `oka_rank_points`: `oka_points` を1,000点単位の順位点へ換算した値。
  標準ルールでは 20

オカは独立設定ではなく、`starting_points` と `return_points` の差から導出する。

## 5. 意味が紛らわしいfield

### return_points と first_place_target_points

同じ値になるルールが多いが、意味が異なるため統合しない。

- `return_points`: 最終精算（オカ計算）の基準点。終局判定には使用しない
- `first_place_target_points`: 南4局以降の終局判定で、一位に必要な点数。
  最終精算には使用しない

例えば「25,000点返し・一位必要点数30,000」のように、両者が異なるルールは実在する。
`RuleSet` はこの組み合わせを表現できる。
`MAHJONG_SOUL_RULES` は `return_points=25_000`、
`first_place_target_points=30_000` を持つfirst-partyの実例である。

### bankruptcy_bonus_points と bankrupt_player_penalty_points

飛び賞は対局中の持ち点ではなく、終局後の順位ポイントへ適用する。
両者はゼロサムでなければならず、`bankruptcy_bonus_points >= 0`、
`bankrupt_player_penalty_points <= 0`、合計0を構築時に検証する。

標準ルールは飛んだプレイヤー -10、飛ばした側 合計 +10 とする。

### riichi_minimum_points と riichi_minimum_live_wall_tiles

- `riichi_minimum_points`: 立直宣言に必要な最低持ち点。`None` は下限なしを表し、
  マイナス点でも立直を許すルールを表現する
- `riichi_minimum_live_wall_tiles`: 立直宣言に必要なlive wall（山の残り生牌）の
  最低残枚数。`1` を指定すると、海底牌をツモった直後の立直だけを禁止し、
  次巡の自摸番の有無自体は立直可否条件にしない

## 6. policy enum

単純なon/offで意味が十分な設定はboolのままとし、複数の意味を持つ設定は
policy enumで表現する。

### MatchFormat

対局形式。現在は `HANCHAN`（半荘戦）のみ。東風戦・三人麻雀は未実装。

### RonResolutionPolicy

複数席が同じ牌へロンを選択したときに、**何人を和了者として成立させるか**。

- `MULTIPLE_RON`: ロンを選択した席すべてを和了者として成立させる
- `HEAD_BUMP`: 頭ハネ。放銃者から見て最も近い1名だけを成立させる

`HEAD_BUMP` は常に和了者を1名へ確定させるため、複数ロン成立を前提とする
三家和途中流局（`triple_ron_abortive_draw`）とは併用できない。構築時に拒否する。

### MultipleRonAwardPolicy

複数ロンが成立した後、**本場と供託を誰が受け取るか**。
`RonResolutionPolicy` とは別の軸のpolicyである。

- `NEAREST_WINNER_TO_DISCARDER`: 上家取り。放銃者の下家を起点とする通常のツモ順で、
  最も近い和了者へ与える

本場と供託は独立したfield（`multiple_ron_honba_policy` /
`multiple_ron_riichi_stick_policy`）で指定する。

### KanDoraRevealPolicy

大明槓・加槓成立時の槓ドラ公開タイミング。

- `DELAY_OPEN_KAN_DORA`: 大明槓はその直後の打牌がロン以外で解決するまで、
  加槓は槍槓が全員パスされるまで公開を保留する
- `IMMEDIATE_ON_KAN_CONFIRMATION`: 成立が確定した時点で直ちに公開する

暗槓は（国士無双の暗槓ロンを除き）槍槓の対象ではないため、このpolicyに関わらず
成立と同時に公開する。槍槓で加槓自体が成立しなかった場合は、どちらのpolicyでも
公開しない。

### RiichiAnkanPolicy

立直後の暗槓をどこまで許容するか。

- `PRESERVE_WAIT_AND_DECOMPOSITION`: 待ち牌の種類に加えて、和了可能な面子分解の
  維持まで要求する
- `PRESERVE_WAIT_ONLY`: 待ち牌の種類の不変までを要求する

送り槓禁止（暗槓にツモ牌を含むこと）と待ち牌種類の不変は、全policy共通の必須条件で
あり、このenumの対象外である。

### FinalPointsRounding

最終粗点の計算方式。丸め粒度だけでなく、1位への残差配分の有無を含む。

- `TOWARD_ZERO_REMAINDER_TO_FIRST`: 2位以下は返し点との差を1,000点単位で0方向
  （原点側）へ丸め、1位はオカ適用前の素点合計がゼロサム残差となる値とする
- `EXACT_NO_ROUNDING`: 丸めを行わない

### FinalRankTiePolicy

半荘終了時の同点順位処理。

- `SEAT_ORDER`: 東1局開始時の風順（東→南→西→北）で同点を一意な順位へ分解する
- `SPLIT_RANK_POINTS`: 同点者を同順位（例: 1,1,3,4）として扱い、該当する複数順位の
  順位点合計を人数で均等分配する

### PaoCompoundYakumanPolicy

パオ対象役満と対象外の役満が複合したときの、責任払いの範囲。

- `FULL_HAND`: 複合役満の点数を含め、和了手全体を責任者が支払う
- `RESPONSIBLE_YAKUMAN_ONLY`: パオ対象役満の分（本場を含む）だけを責任払いとし、
  対象外の役満分は通常の精算で扱う

## 7. 役・符に関するconfig

旧 `python-study` では役設定と符設定が `YakuRules` / `FuRules` という別の型に
分かれ、`RulePreset` がそれらを束ね直していた。両者は1 fieldずつしか持たない
過剰分割だったため、`lisjong-engine` では `RuleSet` 自身へ統合した。

### double_yakuman_variants

2倍役満として扱う役の集合。`frozenset[Yaku]` へ正規化する。
空集合ならダブル役満を採用しない（標準ルール）。

指定できるのは次の候補のsubsetだけであり、それ以外は構築時に拒否する。

```text
Yaku.SUUANKOU_TANKI
Yaku.KOKUSHI_MUSOU_13_WAIT
Yaku.DAISUUSHII
Yaku.JUNSEI_CHUUREN_POUTOU
```

### double_wind_pair_fu

連風牌（場風かつ門風）の雀頭に与える符。`2` または `4` だけを受理する。
標準ルールは `4`。

### pao_yaku

パオ（責任払い）の対象となる役の集合。`frozenset[Yaku]` へ正規化する。
指定できるのは次の候補のsubsetだけである。

```text
Yaku.DAISANGEN
Yaku.DAISUUSHII
Yaku.SUUKANTSU
```

`pao_enabled` が `True` のとき、`pao_yaku` は空であってはならない。

## 8. 構築時のvalidation

`RuleSet` は矛盾した設定を構築時にfail fastで拒否する。
検証は `__post_init__()` の1箇所へ集約し、旧3型に分かれていた検証も統合した。

### 型

- `name` は `str`、整数fieldは `int`（`bool` は不可）、真偽値fieldは `bool`
- `riichi_minimum_points` は `int` または `None`
- policy fieldは対応するenum型
- `uma` はintのiterable、`pao_yaku` と `double_yakuman_variants` は `Yaku` のiterable

型違反は `TypeError` を送出する。

### 値と相互整合

- `name` が空でない
- `version > 0`
- `player_count == 4`（四人麻雀のみ）
- `starting_points > 0`、`return_points > 0`、`first_place_target_points > 0`
- `return_points >= starting_points`
- オカが1,000点単位の順位点として表現できる
- `uma` の要素数がプレイヤー数と一致し、合計が0
- `bankruptcy_threshold == 0`
- 本場の支払いが非負、`riichi_stick_points > 0`
- `noten_penalty_total > 0` かつ 6の倍数
- `pao_yaku` がサポート対象のsubsetであり、`pao_enabled` なら空でない
- `double_yakuman_variants` がサポート対象のsubset
- `double_wind_pair_fu` が `2` または `4`
- `triple_ron_abortive_draw` は `double_ron_enabled` を要求する
- `HEAD_BUMP` と `triple_ron_abortive_draw` は併用できない
- 飛び賞と飛び罰の符号が正しく、合計が0
- `riichi_minimum_live_wall_tiles >= 1`

値違反・矛盾は `ValueError` を送出する。

新しいvalidationは、麻雀ルールとして明らかに矛盾する組み合わせに限定する。
「現在のdefaultでは使わない」という理由だけで、将来使い得る組み合わせを
拒否しない。

### 正規化

`RuleSet` はfrozenな値型である。入力ではiterableを許容し、内部では不変型へ
正規化する。

```text
uma                      -> tuple
pao_yaku                 -> frozenset
double_yakuman_variants  -> frozenset
```

正規化後の `RuleSet` はhashableである。

## 9. 得点評価とRuleSet

得点評価層は、和了時点で確定した事実と `RuleSet` から評価結果を作る、
局状態機械に依存しないpureな層である。

```text
WinningContext + DoraIndicators + winning interpretations + RuleSet
    -> WinningScoreSelection
```

最上位の境界は `winning_score.evaluate_winning_scores()` であり、
rule設定は単一の `RuleSet` だけを受け取る。`rules` を省略した場合は
`RuleSet.default()` を使う。

### 各moduleが参照するRuleSet field

| module | 参照するfield |
| --- | --- |
| `yaku_evaluation` | `double_yakuman_variants` |
| `fu` | `double_wind_pair_fu` |
| `score` | `rounded_mangan_enabled` / `counted_yakuman_enabled` / `multiple_yakuman_enabled` |
| `dora` | なし |
| `hand_value` / `winning_score` | 下位moduleへ受け渡すのみ |

各moduleは必要なfieldだけを参照し、preset名では分岐しない。

### 入力境界

`WinningContext` は和了そのものの事実（手牌・副露・和了牌・ツモ/ロン・風・
立直・一発など）を持つ。ドラ表示牌は和了そのものの事実ではないため、
`WinningContext` へは持たせず `DoraIndicators` として別入力にする。

`DoraIndicators` は和了時点で **既に確定している** 表示牌のsnapshotである。
どの槓ドラ表示牌が有効かを決めるのは局進行の責務であり、`dora.py` は
`kan_dora_reveal_policy` を解釈しない。裏ドラ・槓裏ドラを数えるかどうかは
`WinningContext.riichi_status` から判断する。

### 符の内訳

`FuCalculation` は最終符だけでなく `FuComponent` の内訳を保持する。
主要な契約は次のとおり。

- 七対子は固定25符とし、切り上げない
- 平和ツモは20符（ツモ符を加えない）
- それ以外の通常形は10符単位で切り上げ、最低30符
- ロンで完成した刻子は暗刻として数えない
- 暗槓はclosed quadとして評価する
- 連風牌雀頭の符は `double_wind_pair_fu` に従う

面子のopen/concealed、ロン完成刻子、么九牌、雀頭の価値、待ち形は
`interpretation_analysis` の結果を役側・符側で共有し、どちらでも再推測しない。

### ドラの内訳

`DoraCount` は `visible` / `ura` / `red` / `kan` / `kan_ura` を個別に保持し、
`total` でbonus翻へ換算する。翻数へ潰す前の根拠を残すため、上位APIでは
opaqueなbonus翻を受け取らず `DoraCount` で表現する。

**ドラは役ではない。** 構造上は和了形でも役が1つも成立しなければ、ドラだけでは
得点付き和了にならない。

```text
winning shape exists != legal scored win
```

### limitとrounding

基本点は満貫2,000、跳満3,000、倍満4,000、三倍満6,000、役満8,000とする。
支払点は100点単位へ切り上げ、ツモは支払者ごとに個別へ切り上げる。

- `rounded_mangan_enabled`: 4翻30符・3翻60符を満貫として扱うか
- `counted_yakuman_enabled`: 13翻以上を数え役満（常に1倍役満）として扱うか
- `multiple_yakuman_enabled`: 明示的な複合役満の倍率を加算するか

明示的な役満は通常翻と混在させず、符を持たず、ドラを倍率へ加算しない。
数え役満は倍率に関わらず常に1倍役満とし、実際の符を保持する。

### 得点候補の選択

`winning.py` が列挙するすべての和了形・和了解釈を個別に評価し、途中で代表候補へ
絞らない。候補の比較は翻数ではなく最終的な `winner_points` で行う。

最大点が同じ候補は1つへ潰さず、`max_score_candidates` にすべて保持する。
候補集合は `frozenset` であり、順序に意味を持たせない。

### RoundStateとの責務境界

得点評価層が扱うのは、1人の和了に対する基本支払点までである。
本場、供託、複数ロンの支払配分、パオの最終精算、流し満貫の局精算は
後続のRound / Match層が扱う。

## 10. 未実装・未確定事項

### 後続Issueへ送った内容

`RuleSet` は設定値だけを表すため、次はいずれも本ルール契約の外にある。
このうち局の状態遷移・局精算・最終順位計算・半荘の状態管理は、Issue #15
〜#24で `round_state.py` / `settlement.py` / `final_score.py` /
`match_state.py` として実装済みである（本書「9. 得点評価とRuleSet」、
`docs/architecture.md` の「局のcore API」「局精算（Round settlement）」
「MatchState（F2）」を参照）。後続Issueへ送るのは次のみ。

- 席別観測、外部action selectorを呼び出す対局driver、AI / Policy

役判定logic、符計算、ドラ計算、翻・符の統合、点数計算は得点評価層として
実装済みであり、「9. 得点評価とRuleSet」で扱う。それ以外のfieldは現時点では
「設定値として表現できる」ことまでが固定されており、実際にmechanicsへ
接続されるのは後続Issue以降である。

### ルール自体の未実装・未確定事項

- 東風戦、三人麻雀など、標準半荘以外の対局形式は未実装
- 赤牌枚数、喰い断などは、現時点では `RuleSet` のconfig対象にしていない

## 11. 外部サービスのルール

Issue #44 で、旧 `python-study` に残っていたexternal preset data / provenance /
regression knowledgeをfirst-party `RuleSet` presetへ移管した。

現在first-partyに固定しているexternal presetは次の3つである。

- `TENHOU_RULES`: 天鳳 四人打ち東南戦・喰いタンあり・赤あり段位戦
- `MAHJONG_SOUL_RULES`: 雀魂 四人東南喰赤段位戦
- `M_LEAGUE_RULES`: Mリーグ 四人東南戦

各presetの具体値とprovenanceは `src/lisjong_engine/rule_presets.py` を正本とし、
重要差分とrepresentative mechanics behaviorは `tests/test_rule_presets.py` で固定する。

provenanceは値と同じくversioned contractの一部として扱う。

- Tenhou: 旧 `python-study` で2026-08-08時点の天鳳公式マニュアルを確認して確定した値
- Mahjong Soul: ユーザーが確認・転記した「段位戦ルール説明」を正本として確定した値。
  正本として記録されていない公開URLを推測で補わない
- M League: 旧 `python-study` Issue #74 に確定した設定一覧を移管した値。
  荒牌流局時の聴牌/ノーテン申告専用Actionを追加せず、実手牌の聴牌状態を使うという
  project上の意図的差分を維持する

これらは外部サービスが現在提供するすべてのルールを動的に追従するものではない。
外部側の変更が確認された場合も既存presetを黙って変更せず、source確認とversion更新を行う。

RiichiLabについては、公式仕様または実測でルールを十分に確認したpresetをまだ固定していない。
未確認値を推測で補うことはしない。

## 12. 移行履歴

`python-study` では、ルール設定が次の4型へ分かれていた。

| 旧型 | field数 | 内容 |
| --- | ---: | --- |
| `MahjongRules` | 42 | 対局形式、点数、終局条件、途中流局、パオ、複数ロン、順位点、端数、立直条件、槓ドラ公開 |
| `YakuRules` | 1 | `double_yakuman_variants` |
| `FuRules` | 1 | `double_wind_pair_fu` |
| `RulePreset` | 3 | 上記3つを束ねるだけ |

`YakuRules` と `FuRules` はそれぞれ1 fieldしか持たないにもかかわらず多数のmoduleへ
引き回され、`RulePreset` は分割した3つを再び束ね直すためだけに存在していた。
分割してから束ね直す型が必要になっている時点で、分割の粒度が誤っている。

`lisjong-engine` ではこれらを単一の `RuleSet` へ統合し、`RulePreset` 相当の型は
導入しない。これらの旧型名は移行元の説明としてのみ登場し、本engineの現行public
contractではない。

Issue #44 では、旧runtime型を復活させず、残っていたproject-standard / Tenhou /
Mahjong Soul / M Leagueのpreset data・provenance・unique regression knowledgeを
`rule_presets.py` / `test_rule_presets.py` へ移管した。

詳細な棚卸し結果は `docs/python-study-migration.md` を参照。
