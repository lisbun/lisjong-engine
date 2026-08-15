# Python-study Migration Plan

## Purpose

本書は、`lisbun/python-study` に蓄積された麻雀実装・test・設計知見を、
`lisjong-engine` の責務境界に合わせて選択的に移行するための正本である
（Issue #3）。

この文書が答えるのは次の3点である。

1. `python-study/mahjong` の各資産を、どこへ置き、どの程度再利用するか
2. どの順序で移行すれば、依存関係の逆流と手戻りを避けられるか
3. 後続の実装Issueをどの責務単位で分割するか

本書は棚卸しと移行判断だけを扱い、production codeの移植は行わない。
public APIの先行固定も行わない。個々のAPIは各後続Issueで確定する。

### 調査の基準点

| 項目 | 値 |
| --- | --- |
| 調査対象 | `lisbun/python-study` `main` = `1f8f74d` |
| `lisjong-engine` | `main` = `953cd51` |
| 調査日 | 2026-08-15 |

実測した規模は次のとおり。ファイル名ではなく実内容と依存関係を確認した。

| 区分 | ファイル数 | LOC |
| --- | ---: | ---: |
| production module | 63 | 18,300 |
| test module | 57 | 41,253 |
| shared fixture | 2 | 295 |

test methodは1,809件。`python-study` repository全体のfull test
（麻雀以外を含む1,899件）は、調査時にPython 3.11.15で成功を確認した。
以下の `Status: completed` は、この実行結果を根拠とする。

**`completed` の意味の範囲。** 本書の `completed` は、`python-study` で現在
実装されている契約について既存testが成功していることを示すに過ぎない。
麻雀ルール全体として未確認事項・未実装事項・外部サービス固有差分が存在
しないことは意味しない。未実装・未確定の項目は
`docs/mahjong-rules.md` 19〜20節に明記されており、本書でも
Open questionとして引き継いでいる。

test LOCがproduction LOCの約2.25倍である点は、本移行計画の中心的な前提で
ある。**この repository で最も価値が高い資産はproduction codeではなく、
麻雀ルールの契約を固定しているtestである。**

## Fixed responsibility boundary

Issue #1 と `docs/architecture.md` で確定済みの責務境界は、本Issueの入力条件
であり再設計しない。判断基準は次の一点に集約する。

> その機能がなくても麻雀ゲームを正しく進行できるか

進行できるなら、原則としてengineの外に置く。

```text
lisjong -> lisjong-engine
lisjong-engine -X-> lisjong
```

本書では、この境界を各資産へ機械的に適用した結果だけを記録する。境界そのもの
の是非は扱わない。

### 再利用方針の4分類

| 記号 | 意味 | 本書での運用 |
| --- | --- | --- |
| A | ほぼそのまま移植可能 | logic・testともに移送し、package名と型名の調整に留める |
| B | 設計を維持して修正・書き直す | 責務分割・API・signatureを変更するが、振る舞いとtestの契約は保持する |
| C | test・設計・知見だけを参考にする | codeは移送せず、仕様・edge case・失敗事例だけを新実装へ反映する |
| D | 移行しない | engineの責務外。`lisjong` または `python-study` に残す |

A/Bを分ける基準は「新しい責務境界のもとで、signature以外を変えずに動くか」
である。A判定でも、後述の `RuleSet` 統合による引数変更は共通して発生する。

## Inventory summary

責務単位の集計。詳細は次節以降の個別tableを参照。

| 責務group | production LOC | test LOC | Destination | 主な Reuse |
| --- | ---: | ---: | --- | --- |
| Domain model | 660 | 1,293 | lisjong-engine | A |
| Winning / scoring | 2,633 | 6,329 | lisjong-engine | A |
| Legal actions / round state | 4,337 | 9,714 | lisjong-engine | B |
| Rules | 592 | 714 | lisjong-engine | B |
| Match / settlement | 2,698 | 5,885 | lisjong-engine | A / B |
| Game-layer gray zones | 2,577 | 5,996 | 分割（後述） | B / C / D |
| mjai / adapter / transport | 1,500 | 1,340 | lisjong | D |
| CLI | 1,603 | 4,999 | python-study | D |
| Replay / verification / dataset | 1,700 | 4,983 | python-study / lisjong | C / D |
| Shared fixture | 295 | - | lisjong-engine（再構築） | B / C |

engine中核となる上位5group（Domain model / Winning・scoring /
Legal・round state / Rules / Match・settlement）は production 10,920 LOC・
test 23,935 LOC。`python-study/mahjong` 全体の production LOCの約60%、
test LOCの約58%に相当する（group単位の概算であり、Match groupには
engineへ移さないmoduleも含む）。

残る約40%（game layer上位・mjai・CLI・replay・dataset）は、engineの責務外
または `lisjong` 側の関心である。**directory単位でコピーした場合、engineは
初日から責務境界を破ることになる。**

### 依存構造の実測

production moduleの `import` を解析した結果（`__init__.py`・`__main__.py`・
共有fixtureを除く61 module）、**循環依存は存在しない**。
18層の有向非巡回グラフを構成している。

engine中核にとって重要な性質は次の2点である。

1. `mahjong/*.py` のドメイン層は `mahjong/game/` へ依存しない。
   ドメイン層は上位層から独立して切り出せる。
2. 例外は `replay_engine.py`・`replay_projection.py`・
   `decision_verification.py`・`decision_dataset.py`・
   `terminal_delivery_verification.py` の5つで、これらはtop-levelに
   置かれながら `game/`・`match/` へ**上向きに**依存している。
   package配置と依存方向が一致していない既存の層構造の乱れであり、
   engineへ持ち込まない（いずれもD/C判定）。

## Production asset inventory

### Domain model

物理牌・席・手牌・河・副露・山。engine中核であり、最も移植コストが低い。

| Source | Responsibility | Dest | Status | Tests | Reuse | Dependencies | Phase | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `tile.py` | 牌種・物理牌・34種/136枚ID・赤5 | engine | completed | `test_tile.py` (20) | A | なし | P1 | 依存ゼロ。136枚IDと34種IDの併存契約をそのまま維持する |
| `seat.py` | 固定席 | engine | completed | 上位testで被覆 | A | なし | P1 | 8行。`Wind` と別型に保つ設計は維持する |
| `wind.py` | 場風・自風 | engine | completed | 上位testで被覆 | A | なし | P1 | `Seat` と分離済み。`next()` のみ |
| `hand.py` | 手牌集合・14枚上限・物理ID一意 | engine | completed | `test_hand.py` (13) | A | `tile` | P1 | 可変class。不変値型にするかはP1で判断（Open question 3） |
| `discard.py` | 捨て牌・河・鳴かれ記録 | engine | completed | `test_discard.py` (17) | A | `seat`,`tile` | P1 | `Discard.called_by` による鳴かれ追跡は流し満貫・振聴判定の前提 |
| `meld.py` | ポン・チー・大明槓・加槓・暗槓 | engine | completed | `test_meld.py` (47) | A | `seat`,`tile` | P1 | 加槓が元ポンを保持する構造は符計算・槍槓で必要 |
| `wall.py` | 山・王牌・嶺上・ドラ/裏ドラ表示牌 | engine | completed | `test_wall.py` (22) | A | `tile` | P1 | 嶺上ツモ時の王牌補充と `draw_end_index` の扱いが要点 |
| `round_phase.py` | 局内phase enum | engine | completed | 上位testで被覆 | A | なし | P1 | 12行。8状態。状態機械の骨格 |
| `settlement.py` | 点数移動・供託授与の値型 | engine | completed | `test_match_settlement.py` 経由 | A | `seat` | P6 | 値型のみ。計算は `match_state.py` 側にある（後述の分割対象） |
| `furiten.py` | 振聴理由enum | engine | completed | `test_round_state.py` 経由 | A | なし | P5 | 7行。実際の振聴判定は `round_state.PlayerState` にある |

このgroupは、`RuleSet` にも `RoundState` にも依存しない。**最初に移行すべき
層であり、A判定に異論の余地はない。**

`furiten.py` と `settlement.py` は「enum・値型だけがmoduleとして独立し、
判定・計算本体は巨大moduleの中にある」という既存の分割の非対称を示している。
新engineでは、判定と値型を同じ責務moduleへ寄せることを推奨する。

### Winning / scoring

和了形解析・役・符・ドラ・点数。**純粋関数が中心で、testが最も厚い。**

| Source | Responsibility | Dest | Status | Tests | Reuse | Dependencies | Phase | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `winning.py` | 和了形解析（通常形・七対子・国士）、待ち形 | engine | completed | `test_winning.py` (49) | A | `meld`,`tile` | P2 | 純粋関数。全面子分解の列挙を返す設計は符・役の複数候補評価の前提 |
| `win_context.py` | 和了局面の入力値型（手牌・副露・風・ツモロン等） | engine | completed | `test_win_context.py` (8) | A | `meld`,`seat`,`tile`,`wind` | P2 | 評価系すべての入口。物理牌一意性を検証する |
| `interpretation_analysis.py` | 面子分解の意味解析（暗刻判定・雀頭種別） | engine | completed | `test_fu.py` 経由 | A | `win_context`,`winning`,`meld`,`wind` | P2 | 符と役の共通前処理。単体testがない（下記参照） |
| `yaku.py` | 役判定・役満・`Yaku` enum・`YakuRules` | engine | completed | `test_yaku.py` (40) | A/B | `win_context`,`winning`,`meld`,`wind`,`tile` | P3/P4 | `Yaku` enumのみ先行分離を推奨（後述） |
| `fu.py` | 符計算・`FuRules` | engine | completed | `test_fu.py` (32) | A/B | `interpretation_analysis`,`winning` | P4 | 符の内訳（`FuComponent`）を保持する設計は人間監査に有効 |
| `dora.py` | 表・裏・カンドラ計数 | engine | completed | `test_dora.py` (20) | A | `tile`,`win_context` | P4 | 赤5を含む集計契約 |
| `hand_value.py` | 翻・符の統合評価 | engine | completed | `test_hand_value.py` (6) | A | `dora`,`fu`,`yaku`,`winning` | P4 | 単体testは薄いが `test_winning_score.py` が実質的に被覆 |
| `score.py` | 基本点・満貫〜役満・親子別支払 | engine | completed | `test_score.py` (18) | A | `rules`,`win_context` | P4 | 切り上げ満貫・数え役満・複合役満のON/OFFを持つ |
| `winning_score.py` | 複数解釈の候補列挙と最大選択 | engine | completed | `test_winning_score.py` (38) | A | `hand_value`,`score`,`dora`,`fu`,`yaku` | P4 | 同点候補を保持する契約が重要。最高点だけを返さない |

このgroupは `RoundState` に依存せず、入力値型（`WinningContext`）だけを受け取る
純粋な評価層である。**engineへそのまま移送でき、testもそのまま回帰oracleとして
使える。移行リスクが最も低い。**

`interpretation_analysis.py` は166行で、符計算と役判定が共有する前処理を担う
にもかかわらず専用の単体testを持たない。`test_fu.py` を通じた間接的な被覆で
あるため、P2で移送する際に単体testを追加することを推奨する。

### Legal actions / round state

1局の状態遷移。**engineの心臓部であり、最大かつ最も判断が必要な領域。**

| Source | Responsibility | Dest | Status | Tests | Reuse | Dependencies | Phase | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `legal_action.py` | 合法手の判別可能union・席別snapshot | engine | completed | `test_legal_action.py` (22) | A | `round_phase`,`seat` | P5 | 物理牌IDで表現。dataclass unionの設計は維持する |
| `reaction.py` | 捨て牌・加槓・暗槓への反応候補と優先順位解決 | engine | completed | `test_reaction.py` (14) | A/B | `discard`,`meld`,`rules`,`seat` | P5 | 3種の反応（通常・加槓・暗槓）が並行した型群として重複気味。統合余地あり |
| `riichi_event.py` | 立直宣言と成立/不成立の確定 | engine | completed | `test_riichi_event.py` (30) | A | `discard`,`reaction`,`seat`,`tile` | P5 | 宣言と成立の分離は、鳴きが割り込む場合の1,000点拠出タイミングに必要 |
| `round_event.py` | 局内イベントlogとsnapshot | engine | completed | `test_round_event.py` (46) | A/B | `meld`,`reaction`,`riichi_event`,`round_result` | P5 | engineは進行の副産物として保持。外部牌譜形式とは分離する |
| `round_result.py` | 和了・荒牌流局・途中流局の結果型 | engine | completed | `test_round_result.py` (14) | A | `winning_score`,`dora`,`win_context`,`winning` | P5 | 確定済み得点評価を結果へ保存する契約 |
| `round_state.py` | **1局の状態機械全体** | engine | completed | `test_round_state.py` (122), `test_round_winning.py` (66), `test_abortive_draw.py` (12) | **B** | 20 module | P5 | 2,980行。分割が必須（後述） |

`round_state.py` は単一moduleとして2,980行あり、内訳は次のとおりである。

| 要素 | 行数 | 責務 |
| --- | ---: | --- |
| `RoundState` | 2,125 | 局進行・合法手生成・反応解決・和了確定 |
| `PlayerState` | 375 | 席別の手牌・河・副露・振聴・立直状態 |
| `_DiscardReactionWorkingState` | 87 | 反応解決中の一時状態（原子的commit） |
| module関数 | 約390 | 立直後暗槓の面子分解維持判定等 |

`RoundState` 内の大きなmethodは、`_turn_legal_actions` (71行)、
`_create_reaction_candidates` (79行)、`_apply_ron_resolution_in_place` (71行)、
`resolve_ankan_chankan` (66行)、`resolve_chankan` (62行) である。

**判定: B。振る舞いは維持し、module構成を分割する。**

理由は次の3点である。

1. 合法手生成（`get_legal_actions` と補助を合わせて約250行）は、状態遷移
   本体から独立して検証できる純粋な導出であり、分離するとtestが書きやすい
2. 振聴判定は `PlayerState` に埋め込まれている一方で、`furiten.py` は
   enumだけを持つ。判定と値型を同じmoduleへ寄せるべきである
3. 反応解決（通常・加槓・暗槓の3経路）はそれぞれ独立した解決手続きを持ち、
   `resolve_*` 系methodだけで約400行を占める

ただし、**分割は振る舞いを変えないrefactorとして行う。**
`test_round_state.py`・`test_round_winning.py`・`test_abortive_draw.py` の
200 test（6,160 LOC）が、分割の正しさを判定する唯一のoracleである。

`_DiscardReactionWorkingState` が示す「反応解決を一時状態で組み立て、成功時
にのみ本体へcommitする」設計は、複数ロン・槍槓・大明槓が絡む局面で部分的な
状態更新を防ぐためのものであり、**新engineでも維持すべき重要な設計知見**で
ある。

### Rules

| Source | Responsibility | Dest | Status | Tests | Reuse | Dependencies | Phase | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `rules.py` | `MahjongRules` (42 field) + 8 enum + 4 preset | engine | completed | `test_rules.py` (49) | **B** | `yaku` | P3 | `RuleSet` へ統合。詳細は後述 |
| `rule_preset.py` | 3 rule objectの束ね役 | engine | completed | `test_rule_preset.py` (13) | **C/D** | `fu`,`rules`,`yaku` | P3 | `RuleSet` 統合により存在理由が消える |

詳細は「RuleSet migration considerations」を参照。

### Match / settlement

| Source | Responsibility | Dest | Status | Tests | Reuse | Dependencies | Phase | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `match_state.py` | **半荘状態機械＋精算計算** | engine | completed | `test_match_state.py` (46), `test_match_settlement.py` (53) | **B** | 14 module | P6 | 1,404行。責務が2つ同居（後述） |
| `final_score.py` | 順位・ウマ・オカ・端数処理・飛び賞 | engine | completed | `test_final_score.py` (38) | A | `rules`,`seat` | P6 | `round_state` に依存しない。単独で移送可能 |
| `match/initial_state.py` | Replay用の局開始状態復元 | python-study | completed | `match/test_initial_state.py` (17) | C | `match_state`,`round_state`,`wall` | - | seed基盤の決定性で代替する（後述） |
| `match/record.py` | `RoundRecord`・`MatchRecord` 集約 | lisjong | completed | `match/test_record.py` (15) | C | `game.decision`,`match.initial_state` | - | 牌譜・dataset側の関心 |
| `match/terminal_delivery_record.py` | 終端イベント配送の監査記録 | lisjong | completed | `match/test_terminal_delivery_record.py` (19) | D | `game.event_input`,`match.record` | - | Playerへの配送成否の監査。engine責務外 |
| `match/terminal_event_projection.py` | 局終了・半荘終了の席別公開イベント射影 | engine（一部） | completed | `match/test_terminal_event_projection.py` (25) | C | `final_score`,`game.player_visible_event`,`match_state` | P7 | 席別可視化はengine責務だが、現形はPlayer配送前提 |
| `match/controller.py` | 半荘進行のorchestration | engine（縮小） | completed | `match/test_controller.py` (48) | B/C | `game.controller`,`match.*` | P7 | 最小driverとして再設計（後述） |

`match_state.py` の1,404行は、意味の異なる2つの責務が同居している。

| 責務 | 該当 | 行数の目安 |
| --- | --- | ---: |
| 半荘状態機械 | `MatchState` class（局開始・精算・終局判定・次局位置） | 360 |
| 精算計算（純粋関数） | `calculate_win_point_deltas`、`_ron_transfers` (128)、`_tsumo_transfers` (122)、パオ責任判定、供託授与、飛び点 | 約700 |

**判定: B。P6で2つのmoduleへ分割する。**
精算計算は `RoundResult` と `RuleSet` だけを入力とする純粋関数群であり、
`MatchState` の可変状態に依存しない。分離すれば、`test_match_settlement.py`
の53 testが状態機械を経由せず直接適用できる。

`final_score.py` は `rules` と `seat` にしか依存せず（依存層5）、
`round_state` を必要としない。**P6の中で最初に移送できる。**

### Game-layer gray zones

Issueが個別判断を求めた領域。ここでの判断は「既存の抽象名を維持しない」
という方針に従い、責務から再構成した。

#### 判断の軸

engineが必ず担わなければならないのは、次の一点である。

> **どの席が何を知ってよいかは、engineにしか判定できない。**

呼び出し側は隠蔽情報（他家手牌・山）へアクセスできないため、席別の観測情報
を自力で構成できない。したがって**席別観測の射影はengineの責務**である。

一方で、次の3つはengineの責務ではない。

- **制御の流れ**（engineがPlayerを呼ぶか、呼び出し側がengineを進めるか）
- **action_idのような整数handle**（menu番号・protocol encodingの都合）
- **意思決定の記録**（学習data・監査の関心）

| Source | Responsibility | Dest | Status | Tests | Reuse | Dependencies | Phase | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `game/public_state.py` | 公開牌・公開副露・席別公開情報の値型 | engine | completed | `game/test_public_state.py` (31) | B | `seat`,`tile` | P7 | 席別観測の基礎型。engineが担う |
| `game/observation.py` | `PlayerObservation`（席別局面snapshot） | engine | completed | `game/test_observation.py` (31) | B | `game.public_state`,`game.action_descriptor` | P7 | 情報境界の正本。`action_options` の設計だけ変更（後述） |
| `game/observation_builder.py` | `RoundState` → 席別observationの射影 | engine | completed | `game/test_observation_builder.py` (15) | B | `round_state`,`game.observation` | P7 | 隠蔽情報を落とす射影本体。engineが担う |
| `game/player.py` | `Player` ABC（意思決定境界） | engine（概念のみ） | completed | `game/test_player.py` (5) | **C** | `game.decision_input`,`game.observation` | P7 | 概念は採用、ABCは採用しない（後述） |
| `game/controller.py` | 1局のPlayer駆動loop | engine（縮小） | completed | `game/test_controller.py` (67) | **B/C** | 15 module | P7 | pull型APIへ再設計。testの局面網羅は再利用価値が高い |
| `game/action_descriptor.py` | 合法手の公開表現（物理ID非公開） | engine | completed | `game/test_action_descriptor.py` (21) | **C** | `game.public_state`,`seat` | P7 | `LegalAction` を直接公開するなら不要 |
| `game/action_translation.py` | action_id ↔ `LegalAction` 対応 | 廃止 | completed | `game/test_action_translation.py` (40) | **D** | `round_state`,`game.observation_builder` | - | 決定性上の問題あり（後述） |
| `game/player_visible_event.py` | 席別公開イベントのunion（621行） | engine（保留） | completed | `game/test_player_visible_event.py` (45) | **C** | `dora`,`match_state`,`round_result`,`settlement` | P7以降 | v0.1では不要。差分配送が必要になった時点で再評価 |
| `game/visible_event_translation.py` | `RoundEventLog` → 席別イベント列 | engine（保留） | completed | `game/test_visible_event_translation.py` (29) | **C** | `game.player_visible_event`,`round_event` | P7以降 | 同上 |
| `game/decision.py` | `DecisionRecord`・`DecisionLog` | lisjong | completed | `game/test_decision.py` (21) | **D** | `game.action_descriptor`,`game.observation` | - | 学習data・監査の関心 |
| `game/decision_input.py` | observation + 差分イベントの束 | lisjong | completed | `game/test_event_input.py` 周辺 | **D** | `game.observation` | - | 同上 |
| `game/event_input.py` | Decision外イベント配送のbatch型 | lisjong | completed | `game/test_event_input.py` (7) | **D** | `game.player_visible_event` | - | Player配送契約。engine責務外 |
| `game/human_player.py` | CLI向けPlayer実装 | python-study | completed | `game/test_human_player.py` (10) | **D** | `game.player` | - | CLIの関心 |
| `game/random_player.py` | ランダム選択Player | lisjong / python-study | completed | `game/test_random_player.py` (12) | **C** | `game.player` | - | `action_options` から `random.choice()` で選ぶ意思決定主体はPolicyであり、engine責務外（Issue #1 / `docs/architecture.md`）。seed注入による再現性とtest選択手法だけを知見として引き継ぐ（後述） |

#### `Player` と `GameController` についての判断

**既存の `Player` ABC と push型 `GameController` loopは、engineの中心抽象と
して採用しない。**

`Player` ABC自体はよく設計されている（内部 `LegalAction`・`RoundState` を
公開せず、観測可能範囲だけを渡す契約が明文化されている）。問題は設計の質
ではなく**配置**である。

- `Player` は「麻雀を打つ主体」の抽象であり、`lisjong` 側のPolicyが自然に
  実装する概念である。engineがこのABCを公開契約として固定すると、
  `lisjong` のPolicy設計がengineの都合に縛られる
- push型loop（engineがPlayerを呼び出す）では、engineが制御を保持する。
  RiichiEnv・RiichiLab等の外部環境は逆にpull型（環境が進行を持つ）であり、
  Adapter側で制御反転が必要になる
- engineがtestに必要とするのは「合法手を列挙し、選ばれた1手を適用する」
  能力だけで、Player abstractionは必須ではない

**推奨する形:**

```text
pull型core API:
    round_state.legal_actions(seat) -> LegalActionSnapshot
    round_state.apply(seat, action) -> None
    engine.observation(seat)        -> Observation   # 情報境界はengineが保証

最小driver（engine自身のtest用）:
    座席ごとの Callable[[Observation, LegalActions], Action] を受け取り、
    seed固定で半荘を完走させる関数
```

ABC class階層ではなくcallableを受け取ることで、engineは意思決定主体を
モデル化せずに済み、`lisjong` は自由に `Player` 抽象を定義できる。

`RandomPlayer`（`game/random_player.py`）はこの原則の具体例である。
「`action_options` から `random.choice()` で1つ選ぶ」という処理自体は
単純だが、**合法手集合から実際に1手を選ぶ意思決定を行っている時点で
Policyである**。単純さは責務の所在を変えない。したがってengineへ
再実装せず、`lisjong` / `python-study` 側の実装、または最小driverへ
渡すtest用callableの参考実装として引き継ぐ（C）。

engine自身のtestや半荘完走の回帰testでランダムな合法手選択が必要な場合は、
`RandomPlayer` からは次の3点だけを知見として引き継ぎ、production package
のPolicyとしては公開しない。

- `random.Random` インスタンスを明示注入し、既定値の暗黙生成
  （`random.Random()`）に頼らないことで選択を再現可能にする考え方
- 合法手集合から1つ選んでengineの状態遷移を進めるtest手法
- 決定的driverの回帰testに使える、seed固定の選択方法

具体的には、`tests/` 配下のtest helperとして実装する（production APIには
しない）。実装する場合は、production packageのPolicyとして公開しない、
seedまたは`random.Random`を明示注入する、暗黙のglobal random stateへ
依存しない、test helperであることが分かる配置・命名にする、の4点を
満たす。ただしIssue #3ではproduction code実装を行わないため、実際の
helper実装は行わない。

`game/controller.py` の**test（67 test・2,054 LOC）は局面網羅の資産として
価値が高い**。立直・暗槓・チー・大明槓・ロン・槍槓・加槓/嶺上ツモの各経路を
統合的に通しており、driverの形が変わっても局面自体は再利用できる（C）。

#### `action_translation.py` を移行しない理由

このmoduleは合法手へ整数 `action_id` を割り当て、選択を `LegalAction` へ
解決し直す。engineへ持ち込まない理由は2つある。

1. **決定性の問題。** `action_id` は
   `_ACTION_ID_COUNTER = itertools.count()` というprocess-global counterから
   採番される。同じseed・同じ入力でも、process内の実行順序が変われば
   `action_id` の値が変わる。`lisjong-engine` は
   「同じversion・`RuleSet`・seed・入力系列から同じ状態遷移と結果を再現できる」
   ことを設計方針としており、process-global stateに依存する識別子は
   この方針と整合しない。

   `python-study` 側もこの問題を認識しており、
   `decision_verification.py` は比較前に
   `_observation_without_action_options()` で `action_options` を除去して
   いる。**既存実装が回避策を必要としている事実自体が、この設計を
   engineの公開契約にすべきでない根拠である。**

2. **責務の所在。** 整数handleが必要なのは、CLIのmenu番号とmjaiのaction
   encodingという2つのadapterの都合である。engineは型付き `LegalAction` を
   直接返せばよく、handle化は利用側の関心である。

「そのobservation由来のIDだけを解決し、他局面のIDを構造的に拒否する」という
安全性の考え方は良い設計であり、`lisjong` 側でhandleを導入する際に
知見として引き継ぐ（C）。

#### `player_visible_event` 系を v0.1 で保留する理由

`player_visible_event.py` (621行) と `visible_event_translation.py` (217行)
は、席別の**差分**イベント列を配送するための機構である。

v0.1の完成条件は「合法手だけで半荘を決定的に完走する」ことであり、これは
各Decision時点の**snapshot** observationで達成できる。差分イベント配送が
必要になるのは、外部Adapter（mjai等）が逐次イベントを要求する場合であり、
それは `lisjong` 側の関心である。

加えて、`player_visible_event.py` は `match_state` へ依存している（依存層11）。
局内イベント型が半荘状態へ依存する構造は、engine内部の層構成として望ましく
ない。v0.1では導入せず、必要が生じた時点で層を整理して再設計する。

### mjai / adapter / transport

| Source | Responsibility | Dest | Status | Tests | Reuse | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `game/mjai_protocol.py` | mjai event/actionのPython表現（551行） | lisjong | completed | `game/test_mjai_protocol.py` (29) | **D** | protocol型定義。engine責務外 |
| `game/mjai_adapter.py` | Player契約 ↔ mjai契約の変換（640行） | lisjong | completed | `game/test_mjai_adapter.py` (47) | **D** | 変換境界。engine責務外 |
| `game/mjai_process_transport.py` | 外部processとのJSON Lines transport | lisjong | completed | `game/test_mjai_process_transport.py` (23) | **D** | `subprocess`・`threading`・`queue`。engine責務外 |
| `game/_mjai_test_bot.py` | transport test用の簡易bot | lisjong | completed | 上記testが使用 | **D** | test support |

**4moduleすべてD。** mjai protocol / transportを `lisjong-engine` へ導入
しない。これはIssue #3およびengineの確定済み責務境界による。

ただし、次の設計知見はengineの公開API設計に有用であり、参照値として記録する（C）。

- `mjai_adapter.py` は、engineの公開表現（`ActionDescriptor` + 席別observation）
  だけを入力としてmjai形式へ変換できている。**engineが物理牌IDや内部状態を
  公開しなくても、外部protocolへの変換が成立することの実証**である
- 変換に必要だったengine側の情報（席番号の相対化、点数差分の席別tuple化、
  未公開牌のmask）は、engineの公開observationが満たすべき最小要件の
  参考になる
- Issue #146で実測されたMortal processの契約（`docs/mahjong-architecture.md`
  21.3節）は `lisjong` 側の資産であり、engineへは持ち込まない

### CLI / dataset / replay / verification

| Source | Responsibility | Dest | Status | Tests | Reuse | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `cli/main.py` | 対局起動・preset選択・局間制御 | python-study | completed | `cli/test_main.py` (33) | **D** | 入出力境界 |
| `cli/renderer.py` | 盤面・河・menu描画（639行） | python-study | completed | `cli/test_renderer.py` (97) | **D** | 全角幅計算等の表示関心 |
| `cli/action_chooser.py` | menu番号→action_id | python-study | completed | `cli/test_action_chooser.py` (70) | **D** | 表示・入力の関心 |
| `cli/match_summary.py` | 局終了・半荘終了の人間向け表示 | python-study | completed | `cli/test_match_summary.py` (26) | **D** | 人間監査用の表示 |
| `cli/seat_display.py` | 席名・自風表示のhelper | python-study | completed | `cli/test_seat_display.py` (7) | **D** | 表示の関心 |
| `replay_engine.py` | イベント列からの`RoundState`再構成（690行） | python-study | completed | `test_replay_engine.py` (26) | **C** | 決定性の代替手段（後述） |
| `replay_projection.py` | Replayからのobservation列再生 | python-study | completed | `test_replay_projection.py` (27) | **C** | 同上 |
| `decision_verification.py` | Replay observationとDecision列の同値検証 | python-study | completed | `test_decision_verification.py` (37) | **C** | dataset品質保証の関心 |
| `decision_dataset.py` | 検証済みDecision datasetの構築 | lisjong | completed | `test_decision_dataset.py` (23) | **D** | 学習data生成。engine責務外 |
| `terminal_delivery_verification.py` | 終端イベント配送の照合 | python-study | completed | `test_terminal_delivery_verification.py` (51) | **D** | Player配送の監査 |

CLI群（1,603 production LOC / 4,999 test LOC）は表示・入出力の関心であり、
engineへは移さない。**engineは文字列表現を持たない。**

#### Replay系をengineへ移さない理由

`replay_engine.py` は、`InitialState`（配牌・王牌・山）と `RoundEvent` 列から
`RoundState` を再構成し、イベント単位で再適用する機構である。設計品質は高く、
「`RoundState` 側にReplay専用APIを追加しない」という制約を守って実装されている。

engineへ移さない判断は、品質ではなく**必要性**による。

`python-study` にはseedを起点とした決定的実行の基盤がなく、山は
`create_shuffled_wall(random.Random())` としてCLI境界で生成される。seed管理の
公式なAPIは存在しない（fixtureが `random.Random(match_seed)` を手動で組み立てて
いるのが実態）。そのため、過去の局を再現する唯一の手段がイベント列からの
再構成だった。

`lisjong-engine` は最初からseed管理をengine内部に持つ。
**seed + `RuleSet` + 行動系列があれば局は再現できるため、690行のReplay
engineは決定性の確保には不要になる。**

Replay系が保持している次の知見は、決定性testの設計へ反映する（C）。

- 再構成した状態と記録された結果を突き合わせ、不一致をevent index・
  event型・phase付きで報告する検証手法
- 失敗したReplay sessionを `poisoned` として以後の操作を拒否する設計
- 局単位と半荘単位で検証の粒度を分ける設計

## Test and fixture inventory

**testはproduction codeとは独立に評価する。** B判定でproduction codeを
書き直す場合でも、testが保持する麻雀ルール上の契約は移行資産として扱う。

### 回帰oracleとしての価値評価

| Test | 件数 | LOC | 保護している責務 | 固定している契約 | Reuse |
| --- | ---: | ---: | --- | --- | --- |
| `test_round_state.py` | 122 | 2,809 | 1局の状態遷移全体 | phase遷移、合法手生成、鳴き、立直、槓、振聴 | **B（最高価値）** |
| `test_round_winning.py` | 66 | 2,932 | 局内の和了確定経路 | ツモ/ロン、槍槓、嶺上開花、複数ロン、点数確定 | **B（最高価値）** |
| `test_yaku.py` | 40 | 1,685 | 役判定 | 全役・役満・複合・門前条件 | **A** |
| `test_winning_score.py` | 38 | 1,316 | 得点候補評価 | 複数解釈の候補列挙と同点保持 | **A** |
| `test_winning.py` | 49 | 1,192 | 和了形解析 | 通常形/七対子/国士、待ち形、多重分解 | **A** |
| `test_match_settlement.py` | 53 | 1,350 | 精算計算 | 本場・供託・パオ・ダブロン上家取り・流し満貫 | **B** |
| `test_match_state.py` | 46 | 1,088 | 半荘状態機械 | 連荘、西入、終局判定、飛び | **B** |
| `test_riichi_event.py` | 30 | 1,166 | 立直の宣言と成立 | 鳴き割込み時の成立タイミング、1,000点拠出 | **A** |
| `test_legal_action.py` | 22 | 854 | 合法手の型契約 | 判別可能union、席別snapshot | **A** |
| `test_round_event.py` | 46 | 846 | イベントlog | 追記順序、snapshot不変性 | **A/B** |
| `test_final_score.py` | 38 | 813 | 最終順位 | ウマ・オカ・端数・同点順位・飛び賞 | **A** |
| `test_fu.py` | 32 | 699 | 符計算 | 符の内訳、平和、七対子、連風牌 | **A** |
| `test_rules.py` | 49 | 588 | ルール設定の検証 | フィールド検証、policy整合性 | **B** |
| `test_meld.py` | 47 | 475 | 副露型 | 加槓の元ポン保持、物理ID一意 | **A** |
| `test_dora.py` | 20 | 483 | ドラ計数 | 表・裏・カン・赤 | **A** |
| `test_abortive_draw.py` | 12 | 419 | 途中流局 | 九種九牌、四風連打、四槓散了、四家立直、三家和 | **B（高価値）** |
| `test_score.py` | 18 | 403 | 点数計算 | 満貫〜役満、切り上げ、親子別 | **A** |
| `test_reaction.py` | 14 | 365 | 反応解決 | 優先順位、複数席の同時反応 | **A/B** |
| `test_wall.py` | 22 | 334 | 山操作 | 嶺上ツモ時の王牌補充、ドラ公開 | **A** |
| `test_round_result.py` | 14 | 323 | 結果型 | 和了・流局結果の不変条件 | **A** |
| `test_win_context.py` | 8 | 304 | 和了入力の検証 | 物理牌一意性、ツモ/ロン整合 | **A** |
| `test_hand_value.py` | 6 | 247 | 翻符統合 | - | **A** |
| `test_tile.py` / `test_hand.py` / `test_discard.py` | 50 | 484 | 基礎ドメイン | ID契約、上限、一意性 | **A** |
| `test_rule_preset.py` | 13 | 126 | preset束ね | - | **D** |

#### 特に重要な3つのtest module

1. **`test_round_winning.py`（66 test / 2,932 LOC）** — 単一test moduleとして
   最大。production moduleと1対1対応しない**横断的な振る舞いtest**であり、
   `RoundState`・和了判定・役・符・点数・精算をまたぐ経路を固定している。
   `round_state.py` を分割する際、**分割が振る舞いを変えていないことを判定
   できる唯一のoracle**である。

2. **`test_match_settlement.py`（53 test / 1,350 LOC）** — 精算計算の
   edge caseを網羅する。`match_state.py` の分割後は、状態機械を経由せず
   精算関数へ直接適用できるようになるため、**分割によって価値が上がる**。

3. **`test_abortive_draw.py`（12 test / 419 LOC）** — 途中流局5種を固定する。
   test件数は少ないが、**実装漏れが最も起きやすい領域**であり、
   1 testあたりの価値が高い。

これら3つはいずれもproduction moduleと同名でない。**module単位の移送計画
だけを立てると見落とされる資産**であるため、明示的に記録する。

### Fixture評価

| Fixture | LOC | 内容 | 手法 | Reuse |
| --- | ---: | --- | --- | --- |
| `_ankan_chankan_round_fixture.py` | 227 | 国士無双限定の暗槓ロン（槍槓）局 | 手牌・山を直接構築した完全決定的な1局 | **B/C** |
| `_kakan_round_fixture.py` | 68 | 加槓を含む局 | `match_seed=0` のRandomPlayer半荘の5局目に加槓が出現する性質へ依存 | **C/D** |

この2つは**対照的な例**であり、新engineのtest設計方針を導く。

`_ankan_chankan_round_fixture.py` は、乱数を使わず手牌と山を明示的に構築して
局面を作る。国士無双の暗槓に対する槍槓という、ランダム試行では事実上発生
しない局面を決定的に再現できる。**この構築手法（`_take` による牌の名前指定
取得と `_ankan_chankan_wall` による山の組み立て）は新engineでも直接使える。**
仕様資産としても価値が高く、`kokushi_ankan_chankan_enabled` という
ruleフィールドの唯一の実証局面である。

`_kakan_round_fixture.py` は、seed固定の半荘simulationを回して「加槓を含む
局」を探索する。docstringは `match_seed=0` の5局目に必ず加槓が含まれることを
前提として明記している。この手法は次の点で脆い。

- `MatchController` + `RandomPlayer` の全stackへ依存する
- 合法手の生成順序・`RandomPlayer` の消費するrandom streamが少しでも変われば、
  出現局が変わり fixture が壊れる
- 「加槓が起きる局」という意図が、seed値という間接表現に隠れる

**新engineでは、加槓局も `_ankan_chankan_round_fixture.py` と同じ明示的構築で
再現することを推奨する（C）。** seed探索に依存するfixtureは作らない。

なお、両fixtureは現在 `replay_engine` / `decision_verification` /
`decision_dataset` のtest（いずれもC/D判定）向けに作られている。
**局面そのものはengineのtest資産として価値があるが、fixtureが返す型
（`RoundRecord`・`RoundDecisionRecord`）はengineへ移さない。**

## Document inventory

| Document | LOC | 評価 | Destination | Reuse |
| --- | ---: | --- | --- | --- |
| `python-study/docs/mahjong-rules.md` | 332 | 大部分が現在も正しいルール仕様 | 内容をengineの新規rules specへ再構成 | **B** |
| `python-study/mahjong/README.md` | 408 | 仕様説明は有効、進捗・test件数記録はstale | python-studyに残す | **C** |
| `python-study/docs/mahjong-architecture.md` | 4,043 | 設計知見・進捗記録・lisjong側の関心が混在 | python-studyに残す | **C** |

### `docs/mahjong-rules.md`

**engineへの移行価値が最も高い文書。** `project-standard-v1` というルール
セットの正本であり、`RuleSet.default()` が encode すべき内容そのものである。

| 節 | 内容 | 扱い |
| --- | --- | --- |
| 2〜13 | 対局形式、局進行、終局条件、得点、本場・供託、複数ロン、連荘、順位点、端数処理、飛び | **engineへ再構成** |
| 14〜17 | 立直後の行動制限、喰い替え、フリテン、槓ドラ公開 | **engineへ再構成**（「標準ルール／LegalAction生成／コンフィグ」の3分類は有用な記述形式） |
| 18 | 実装済み項目一覧 | python-studyの実装状況。engineへは移さない |
| 19〜21 | 未実装・未確定・将来設定候補 | **Open questionとして引き継ぐ** |
| 22〜23 | 情報源、変更履歴 | 情報源はengineでも参照する |

ただし、**現時点ではコピーしない。** 本文中に `RoundState`・`MahjongRules`・
`FuRules`・`YakuRules` といった旧module名が実装契約として埋め込まれており、
`RuleSet` 統合後の名前と一致しなくなる。P3（`RuleSet`実装）のIssueで、
確定した名前に合わせて新規に書き起こす。

### `python-study/mahjong/README.md`

仕様説明（実装済み責務、1局の状態管理、終局結果、役判定、複数局管理、
主な不変条件）は現在も正確である。一方で、Phase番号への言及、
「676件」「826件」「837件」といった過去時点のtest件数記録が混在しており、
これは学習履歴としての価値はあるが engine の文書としては不要である。

**python-studyに残す（C）。** engineのREADMEは既に独自の責務記述を持つ。

### `python-study/docs/mahjong-architecture.md`

4,043行・21章。3種類の内容が混在している。

| 分類 | 該当章 | engineから見た扱い |
| --- | --- | --- |
| engine設計知見 | 13（合法操作interface）、14.4/14.11（情報境界）、15（module責務）、16.3/16.4（イベント設計・槓とドラ公開）、18〜20（preset設計） | **参照する（C）** |
| lisjong側の関心 | 3.4〜3.6（mjai/RiichiEnv/RiichiLab adapter）、4.2/4.3（オンライン対局・外部process境界）、21（mjai External Player境界） | engine対象外 |
| 進捗・履歴記録 | 10（実装の現在地）、12（Phase 6A現在地）、14.7（Phase 6B初期方針）、16.18（AI実装一時保留） | staleまたはengine対象外 |

**丸ごとコピーしない。** engineへ持ち込む価値がある知見は、本書の各節と
後続Issueへ抽出済みである。特に次の3点は本書で明示的に引き継いだ。

- 13.5節「判断支援情報との分離」— 向聴数・受け入れ等をengineに含めない根拠
- 14.4節「Playerへ渡す情報の境界」— 席別観測の情報境界
- 16.4節「槓とドラ公開イベントの設計方針」— `KanDoraRevealPolicy` の背景

## RuleSet migration considerations

### 現状の構造

`python-study` は3つのrule objectを持ち、4つ目の型がそれらを束ねている。

| 型 | フィールド数 | 内容 |
| --- | ---: | --- |
| `MahjongRules` | 42 | 対局形式、点数、終局条件、途中流局、パオ、複数ロン、順位点、端数、立直条件、槓ドラ公開 |
| `YakuRules` | **1** | `double_yakuman_variants`（ダブル役満の種類） |
| `FuRules` | **1** | `double_wind_pair_fu`（連風牌雀頭の符：2 or 4） |
| `RulePreset` | 3 | 上記3つを束ねるだけ。判定logicを持たない |

### 判断: 3分割は過剰分割である

**`YakuRules` と `FuRules` は、それぞれ1フィールドしか持たない。**
それにもかかわらず、この3つは11個のproduction moduleへ引数として引き回され
（`hand_value`、`winning_score`、`round_state`、`match_state`、
`replay_engine` 等）、production codeだけで57箇所に出現する。

さらに `RulePreset` は、分割した3つを再び1つに束ね直すためだけに存在する。
そのdocstringも「ルール判定ロジックは持たず、CLI等の構築境界で個別ルールへ
分解して渡すための入れ物に過ぎない」と明記している。

**分割してから束ね直す型が必要になっている時点で、分割の粒度が誤っている。**

### 推奨する統合

```text
RuleSet（単一のfrozen値型）
    - 対局形式・点数・終局条件
    - 局進行・連荘・本場・供託
    - 和了・得点・役・符に関する設定（旧 YakuRules / FuRules を吸収）
    - 途中流局・パオ・複数ロン
    - 順位点・端数処理
```

利点は次の3点である。

1. 引数が1つになり、11 module・57箇所の引き回しが単純化する
2. `RulePreset` が不要になる
3. ルール整合性の検証を1箇所へ集約できる。現状 `MahjongRules.__post_init__`
   は45フィールドの相互整合（例: 頭ハネと三家和の排他）を検証しているが、
   `YakuRules`・`FuRules` との組み合わせ整合は誰も検証していない

### rule mechanicsとconfigの分離

`python-study` が既に達成している優れた分離を維持する。

- **preset名でゲームロジックを分岐させない。** `RulePreset.name` は表示・
  識別専用であり、判定は必ずpolicy enumの値で行う。この規律は
  `docs/mahjong-architecture.md` 18.3節で明文化され、実装でも守られている
- **policyは真偽値ではなくenumで表現する。** `RonResolutionPolicy`・
  `KanDoraRevealPolicy`・`RiichiAnkanPolicy`・`FinalPointsRounding`・
  `FinalRankTiePolicy`・`PaoCompoundYakumanPolicy` は、いずれも
  「どちらのルールか」を意味のある名前で表現し、docstringで各値の意味を
  説明している。**この設計は全面的に維持する**
- **意味が異なる値を同じフィールドへ寄せない。** `return_points`（最終精算
  の基準点）と `first_place_target_points`（終局判定の一位必要点数）は、
  多くのルールで同値だが意味が異なるため独立フィールドとして分離されている。
  雀魂（25,000 / 30,000）がその実例である

### 依存順序上の制約

**`rules.py` は `yaku.py` へ依存する**（`MahjongRules.pao_yaku:
frozenset[Yaku]`）。一方で `reaction.py` と `round_state.py` は `rules.py` へ
依存する。したがって次の順序制約が生じる。

```text
Yaku enum -> RuleSet -> reaction / round_state
```

**Issue本文の仮案では `RuleSet` が第4段階（合法手・`RoundState`の後）に
置かれていたが、依存関係上これは成立しない。** `RuleSet` は
`RoundState` より前に必要である。

推奨する解決は、`Yaku` enum（役の識別子）を役判定logicから分離することで
ある。`RuleSet` が必要とするのは役の**識別子**だけであり、役の**判定**
ではない。分離すれば、設定型が評価logicへ依存する構造がなくなる。

```text
分離前: RuleSet -> yaku.py（識別子 + 判定logic 856行）
分離後: RuleSet -> yaku種別（識別子のみ）
        yaku評価 -> yaku種別
```

### default presetの最小範囲

**v0.1では `RuleSet.default()` の1つだけを提供する。**
内容は `project-standard-v1`（`docs/mahjong-rules.md`）相当とする。

天鳳・雀魂・Mリーグの3presetは、`python-study` で公式マニュアル・
ルール説明・Issue本文を出典として検証された値であり、**データとしての価値は
高い**。ただし次の理由で v0.1 の公開契約には含めない。

- preset数だけ検証の組み合わせが増え、`RoundState` 移行と並行すると
  失敗原因の切り分けが難しくなる
- `RuleSet` 統合後のフィールド構成が確定してから移すほうが手戻りが少ない
- `docs/architecture.md` が「初期段階から多数のpresetを用意しない」と
  明記している

3presetの値は `python-study` に残るため失われない。`RuleSet` 確定後の
後続Issueで、出典を再確認したうえで追加する。

### RiichiLab preset

**未確認事項を推測で埋めない。** RiichiLab固有ルールは、本Issueの調査対象
（`python-study`）には存在しない。`lisjong` 側での実測を経て確定するまで、
engineへpresetを追加しない。Open question 6を参照。

## Dependency / migration phases

### 実測に基づく順序の確定

全63 moduleの依存解析（循環なし・18層のDAG）から、Issue本文の仮案を
次の2点で修正する。

| # | 仮案 | 実測 | 修正 |
| --- | --- | --- | --- |
| 1 | `RuleSet` は第4段階 | `rules` → `yaku` 依存、`reaction`/`round_state` → `rules` 依存 | **`RuleSet` を `RoundState` より前へ移動** |
| 2 | 和了・得点評価は1段階 | `round_result` → `winning_score` 依存（層7）、`winning_score` → `score` → `rules` 依存（層6→5→4） | **和了形解析と得点評価を分割**し、間に `RuleSet` を挟む |

その他に確認した依存上の要点。

- `final_score.py` は `rules` と `seat` にしか依存しない（層5）。
  `round_state`・`match_state` を待たずに移送できる
- `player_visible_event.py` は `match_state` へ依存する（層11）。
  局内イベント型が半荘状態へ依存しており、この向きは新engineでは避ける
- `settlement.py`（値型・層1）と精算計算（`match_state.py` 内・層10）が
  分離されている。値型だけ先に移送できる

### 確定した移行フェーズ

```text
P1  ドメインモデル + seed基盤
    tile / seat / wind / hand / discard / meld / wall / round_phase
    + seed管理（新規実装）
        依存: なし

P2  和了形解析
    winning / win_context / interpretation_analysis
        依存: P1

P3  RuleSet
    Yaku識別子の分離 + RuleSet統合 + default preset
        依存: P1
        ※ P2と並行可能

P4  得点評価
    yaku評価 / fu / dora / hand_value / score / winning_score
        依存: P2, P3

P5  合法手・1局状態遷移
    legal_action / reaction / riichi_event / round_event /
    round_result / RoundState（分割して実装）
        依存: P1, P3, P4

P6  精算・半荘状態管理
    settlement計算 / final_score / MatchState（分割して実装）
        依存: P4, P5

P7  席別観測境界 + 決定的最小driver
    observation射影 + seed固定の半荘完走driver
        依存: P5, P6
```

P2とP3は依存関係がなく並行できる。それ以外は直列である。

### 新規実装が必要な領域

移行ではなく**新規実装**が必要な項目を明示する。`python-study` に対応資産が
ないため、移植として計画すると見積もりを誤る。

| 項目 | 現状 | 必要な作業 |
| --- | --- | --- |
| **seed管理** | 公式APIなし。`create_shuffled_wall(random.Random())` をCLI境界で呼ぶだけ。fixtureが `random.Random(match_seed)` を手動構築 | engine内部でのseed管理と、seedから局・半荘を再現するAPIを新規設計（P1） |
| **決定的driver** | `MatchController` はあるが、選択主体は `RandomPlayer`（Policy、非決定的な既定値 `random.Random()`）へ委ねられている | engineはPolicyを所有せず、外部から渡されたaction selector/callableで進行するdriverを新規実装（P7）。callable自体はengine外（`lisjong` / test helper）が提供する |
| **pull型 core API** | push型 `GameController` のみ | `legal_actions` / `apply` 形式のAPIを新規設計（P5） |

seed管理は `docs/architecture.md` が「乱数の利用箇所はengine内部で管理し、
暗黙のglobal random stateへ依存しない方向とする」と定めた方針の実装であり、
**P1で基盤を置かないと後段すべてが非決定的になる。**

## Proposed follow-up issues

本書のレビュー後に起票する想定。GitHubへの起票は本Issueでは行わない。
各Issueは実装・test・レビューまで1単位で完結する粒度とした。

### Issue A: ドメインモデルとseed基盤

- **scope**: 牌・席・風・手牌・河・副露・山の移送と、engine内部のseed管理基盤
- **対象**: `tile` / `seat` / `wind` / `hand` / `discard` / `meld` /
  `wall` / `round_phase` + seed管理（新規）
- **prerequisite**: なし
- **完了条件**: 全ドメイン型が `src/lisjong_engine/` に存在し、
  `test_tile` / `test_hand` / `test_discard` / `test_meld` / `test_wall`
  相当のtestが通る。同一seedから同一の山が再現できる
- **次との依存**: B・Cの前提

### Issue B: 和了形解析

- **scope**: 和了形の判定と面子分解、待ち形、和了入力の値型
- **対象**: `winning` / `win_context` / `interpretation_analysis`
- **prerequisite**: A
- **完了条件**: 通常形・七対子・国士の判定と多重分解の列挙が
  `test_winning`（49 test）相当で固定される。
  `interpretation_analysis` の単体testを新規追加する
- **次との依存**: Dの前提。Cと並行可能

### Issue C: RuleSetの統合

- **scope**: `MahjongRules` / `YakuRules` / `FuRules` / `RulePreset` を
  単一 `RuleSet` へ統合し、default presetを1つ定義する。
  `Yaku` 識別子を役判定logicから分離する
- **対象**: `rules` / `rule_preset` / `yaku`（識別子部分のみ）
- **prerequisite**: A
- **完了条件**: `RuleSet.default()` が `project-standard-v1` を表現し、
  フィールド相互の整合性検証が `test_rules`（49 test）相当で固定される。
  ルール仕様文書をengine側に新規作成する
- **次との依存**: Dの前提。Bと並行可能
- **注意**: 天鳳・雀魂・Mリーグpresetはこの段階では追加しない

### Issue D: 得点評価

- **scope**: 役・符・ドラ・点数計算と、複数解釈の候補評価
- **対象**: `yaku`（評価logic）/ `fu` / `dora` / `hand_value` /
  `score` / `winning_score`
- **prerequisite**: B, C
- **完了条件**: `test_yaku`(40) / `test_fu`(32) / `test_dora`(20) /
  `test_score`(18) / `test_winning_score`(38) 相当が通る。
  同点候補を保持する契約が維持される
- **次との依存**: Eの前提

### Issue E: 合法手生成と1局の状態遷移

- **scope**: 合法手・反応解決・立直・イベントlog・局結果・`RoundState`
- **対象**: `legal_action` / `reaction` / `riichi_event` / `round_event` /
  `round_result` / `round_state`（責務ごとに分割して実装）
- **prerequisite**: A, C, D
- **完了条件**: `test_round_state`(122) / `test_round_winning`(66) /
  `test_abortive_draw`(12) 相当が通る。pull型のcore API
  （合法手列挙と適用）が動作する
- **次との依存**: Fの前提
- **注意**: 本Issueが最大。分割が必要な場合は
  「合法手生成」「反応解決」「和了確定・流局」で分ける。
  `_DiscardReactionWorkingState` の原子的commit設計を維持する

### Issue F: 精算と半荘状態管理

- **scope**: 点数移動計算、半荘の状態機械、最終順位
- **対象**: `settlement` / `final_score` / `match_state`
  （精算計算と状態機械を別moduleへ分割）
- **prerequisite**: D, E
- **完了条件**: `test_match_settlement`(53) / `test_match_state`(46) /
  `test_final_score`(38) 相当が通る。精算計算が状態機械を経由せず
  直接testできる
- **次との依存**: Gの前提

### Issue G: 席別観測境界と決定的最小driver

- **scope**: 席別観測の射影と、seed固定で半荘を完走する最小driver。
  **engineはPolicyを所有しない**。driverは座席ごとのaction selector/
  callableを外部から受け取って進行するだけで、選択logicそのもの
  （`RandomPlayer`相当のPolicy実装）はengineのproduction APIとして
  持たない
- **対象**: `public_state` / `observation` / `observation_builder` 相当を
  再設計。driverは新規実装
- **prerequisite**: E, F
- **完了条件**: 観測に隠蔽情報が含まれないことがtestで固定される。
  同一seed・同一 `RuleSet`・同一行動系列から半荘の全状態遷移と最終結果が
  再現できる。**これが v0.1 の到達条件に相当する**。driver自身のtestで
  決定的な選択が必要な場合は、`tests/` 配下のseed付きtest helperとして
  実装し、production packageのPolicyとして公開しない
- **次との依存**: なし（v0.1完成）
- **注意**: `Player` ABCを公開契約にしない。座席ごとのcallableを受け取る。
  `RandomPlayer` はengineへ再実装しない（C、Game-layer gray zones参照）

### 起票時に判断する事項

- Issue Eの分割要否は、Issue D完了時点の実装量を見て判断する
- 天鳳・雀魂・Mリーグpresetの追加は、Issue G完了後の別Issueとする
- `player_visible_event` 系（差分イベント配送）は v0.1 の scope外。
  外部Adapter接続が具体化した時点で改めて評価する

## Assets intentionally not migrated

engineへ移さないと判断した主要資産。判断根拠を明示する。

| 資産 | LOC(prod/test) | 判断 | 根拠 |
| --- | --- | --- | --- |
| mjai protocol / adapter / transport | 1,500 / 1,340 | **D** | 通信protocolはengine責務外（確定済み境界）。`lisjong` の関心 |
| CLI一式 | 1,603 / 4,999 | **D** | 表示・入出力。engineは文字列表現を持たない |
| `action_translation.py` | 309 / 856 | **D** | process-global counterによるaction_id採番が決定性方針と整合しない。整数handleはadapterの関心 |
| `decision.py` / `decision_input.py` / `event_input.py` | 211 / 287 | **D** | 意思決定の記録・配送契約。学習data・監査の関心 |
| `decision_dataset.py` | 75 / 523 | **D** | 学習dataset生成。engine責務外 |
| `terminal_delivery_verification.py` | 470 / 1,438 | **D** | Playerへの配送成否の監査。engine責務外 |
| `match/terminal_delivery_record.py` | 134 / 221 | **D** | 同上 |
| `human_player.py` | 52 / 147 | **D** | CLIの関心 |
| `rule_preset.py` | 76 / 126 | **C/D** | `RuleSet` 統合により存在理由が消える |
| `replay_engine.py` / `replay_projection.py` | 823 / 1,907 | **C** | seed基盤の決定性で代替。検証手法の知見のみ引き継ぐ |
| `decision_verification.py` | 332 / 1,115 | **C** | dataset品質保証の関心。engineの決定性testとは目的が異なる |
| `match/initial_state.py` | 118 / 206 | **C** | Replay前提の型。seed起点の再現で代替 |
| `player_visible_event.py` / `visible_event_translation.py` | 838 / 1,313 | **C** | v0.1では差分配送が不要。`match_state` への依存も整理が必要 |
| `action_descriptor.py` | 220 / 395 | **C** | `LegalAction` を直接公開するなら不要 |
| 天鳳 / 雀魂 / Mリーグ preset | （`rules.py` 内） | **C** | 検証済みデータとして価値があるが v0.1 の公開契約に含めない |
| `docs/mahjong-architecture.md` | 4,043行 | **C** | 進捗記録・lisjong側の関心が混在。知見は本書へ抽出済み |

合計すると、production LOCの約40%・test LOCの約42%はengineへ移らない。
**これは損失ではなく、責務境界が機能していることの確認である。**

`python-study` 側のコードは本Issueでは削除しない。学習履歴および参考実装
として残す。

## Open questions

推測で埋めず、担当Issueで確定する。

1. **Python 3.14での動作未検証**
   `python-study` はPython 3.11を基準としCIも3.11で動作している
   （調査時のfull test 1,899件成功は3.11.15での結果）。
   `lisjong-engine` は `requires-python = ">=3.14,<3.15"`。
   移送する各moduleが3.14で動作するかは未確認。
   → Issue A（#5）で移送済みのdomain model
   （`tile` / `seat` / `wind` / `hand` / `discard` / `meld` / `wall` /
   `round_phase`）についてPython 3.14で解消。3.14向けの互換修正は不要だった。
   未移送のmodule（`winning` / `rules` / `round_state` 等）は各移送Issueで確認する。

2. **`RoundState` の分割単位**
   2,980行を分割することは確定だが、具体的な境界（合法手生成 /
   反応解決 / 和了確定 / 席別状態）は実装時に確定する。
   分割は振る舞いを変えないrefactorとして行い、
   `test_round_winning.py` 相当を判定基準とする。
   → Issue Eで確定。

3. **`Hand` / `River` を可変classのままにするか**
   現状はどちらも可変（`add` / `remove` / `mark_called`）。
   決定性と状態復元の観点では不変値型が扱いやすいが、
   1局の進行では可変のほうが自然な場面もある。
   → Issue A（#5）で可変classのまま移行すると決定。不変値型への変更は
   後続 `RoundState` の都合の先取りになるため行わない。

4. **seed APIの粒度**
   半荘単位の単一seedから各局の山を導出するか、局ごとにseedを持つか。
   `docs/architecture.md` は「具体的なseed APIは実装Issueで確定する」と
   している。途中局からの再現可能性に影響する。
   → Issue A（#5）で `seed: int` → `RandomSource` → `create_shuffled_wall()`
   の境界までを確定し、`Wall` へseed管理責務を持たせない形とした。
   半荘seedと局seedの配分規則はどちらの方式も妨げないよう未固定で残し、
   Match層（Issue F）で確定する。

5. **終局基準がちょうど30,000点の場合の扱い**
   `docs/mahjong-rules.md` 20節が未確定事項として明示している。
   天鳳公式の表現に「原点以上」と「原点を超えた」が併記されており、
   牌譜等による追加確認が必要とされている。
   `python-study` から未確定のまま引き継ぐ。
   → 確認手段が得られるまで保留。

6. **RiichiLab固有ルール**
   本Issueの調査対象に情報が存在しない。`lisjong` 側での実測を経て
   確定するまで、engineへpresetを追加しない。
   → `lisjong` 側の接続Issueに依存。

7. **`reaction.py` の3経路統合の可否**
   通常の捨て牌反応・加槓への槍槓・暗槓への槍槓が、それぞれ
   `ReactionCandidate` / `KakanReactionCandidate` / `AnkanReactionCandidate`
   という並行した型群として実装されている（694行）。統合できる可能性が
   あるが、暗槓槍槓が国士無双限定である等の差異があり、
   実装時に判断する。
   → Issue Eで判断。

8. **外部サービスpresetを追加する際の検証手段**
   `python-study` の3presetは公式マニュアル・ルール説明・Issue本文を
   出典としている。engineへ追加する際に同じ出典を再確認するか、
   実測（牌譜等）を要求するかは未確定。
   → preset追加Issueで確定。
