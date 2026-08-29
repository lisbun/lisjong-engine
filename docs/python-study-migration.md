# Python-study Migration Ledger

## Purpose

本書は、`lisbun/python-study` に蓄積された麻雀実装・test・設計知見について、
**`python-study` から `lisjong-engine` への移行実績を記録する migration ledger**
である。

初版（Issue #3）は、移行前の inventory と P1〜P7 の移行計画を確定するために
作成した。Issue #32 の post-migration audit 以降は、初版の `Reuse` 判断を
履歴として保持しつつ、現在の `lisjong-engine` に対して次を追跡する。

1. 旧資産の必要な責務・契約・edge caseが移行済みか
2. 旧contractが別設計へ置き換えられたか
3. engine migration sourceとして旧資産を保持する必要があるか
4. 後続の `python-study` cleanup auditへ渡すべき判断が何か

本書は lisjong ecosystem 全体の移行・cleanup判断の正本ではない。
`lisjong`、`lisjong-arena`、Human Play、Replay / Visualization の最終配置や、
`python-study` からの最終削除可否は、各repositoryまたは後続の
cross-repository cleanup auditで判断する。

現在の engine contract は [`architecture.md`](architecture.md) と
[`rules.md`](rules.md) を正本とし、post-v0.1 の発展方向は
[`roadmap.md`](roadmap.md) を正本とする。旧 `python-study` のpackage構造や
APIをそのまま再現することは目的にしない。

初回の長文migration planと詳細な判断理由は、Issue #32着手直前の
[`cbfc5df` 時点の本書](https://github.com/lisbun/lisjong-engine/blob/cbfc5dfbecbd9ec8bee4395a27c1cdd902efbddd/docs/python-study-migration.md)
にGit historyとして保持する。post-migration ledgerでは、staleな未来形を残すより、
現在の判断とcleanup handoffを優先する。

## Audit baselines

### Initial inventory

Issue #3 で行った初回棚卸しの基準点を履歴として残す。

| 項目 | 値 |
| --- | --- |
| `python-study` | `main` = `1f8f74dd58dfbcd108a3949b43b95f4307f0f913` |
| `lisjong-engine` | `main` = `953cd51` |
| 調査日 | 2026-08-15 |
| production module | 63 files / 18,300 LOC |
| test module | 57 files / 41,253 LOC |
| shared fixture | 2 files / 295 LOC |
| test method | 1,809 |
| `python-study` full test | 1,899 tests success on Python 3.11.15 |

初回棚卸しで最も重要だった知見は、production codeよりも、麻雀ルールの
contract / edge caseを固定したtest資産の価値が高いことである。この原則は
post-migration auditでも維持する。

### Post-migration audit

Issue #32 の基準点。

| 項目 | 値 |
| --- | --- |
| `python-study` | `main` = `1f8f74dd58dfbcd108a3949b43b95f4307f0f913` |
| `lisjong-engine` | `main` = `cbfc5dfbecbd9ec8bee4395a27c1cdd902efbddd` |
| 調査日 | 2026-08-21 |
| engine current foundation | deterministic minimal hanchan driverまで接続済み（v0.1相当） |

`python-study/main` は初回棚卸し基準から変わっていない。このため今回の監査は、
旧sourceの全面再調査ではなく、主として初回inventoryと現在のengine実装・test・
確定済み設計契約を再照合する形で行った。

### External preset migration

Issue #44 で external rule preset を first-party 化した際の基準点。

| 項目 | 値 |
| --- | --- |
| `python-study` | `main` = `7face9b94ad25797c0e5944f2e74219e6af966ef` |
| `lisjong-engine` | `main` = `0ba2e83d01beeeaf9e0c5c62a290ddc54a4ce5cc` |
| 調査日 | 2026-08-29 |
| 対象 | project-standard / Tenhou / Mahjong Soul / M League |

current `python-study` の `mahjong/rules.py` / `yaku.py` / `fu.py` と関連docs・testsを
再確認し、旧 `MahjongRules` 全42 fieldに加えて `double_yakuman_variants` と
`double_wind_pair_fu` を単一 `RuleSet` presetへ移管した。external 3 presetは
project-standardから暗黙継承せず、独立した完全定義として固定した。

## Status semantics

### Initial `Status`

初回inventoryの `Status: completed` は、**初回調査時点の `python-study` で
その資産の既存contractに対するtestが成功していた**ことを示す。

これは `lisjong-engine` への移行完了を意味しない。

したがって、

```text
Status: completed != Migration state: migrated
```

である。混同を避けるため、post-migration ledgerの個別tableでは旧 `Status`
columnを繰り返さない。初回inventoryに列挙したproduction assetは、特記がない限り
旧 `Status: completed` だったものとして扱う。

### Initial `Reuse`

初回棚卸しの `Reuse` は、当時の「どう再利用する予定か」を表す履歴値である。

| Reuse | 初回判断 |
| --- | --- |
| A | logic・testをほぼそのまま移植可能 |
| B | 設計を維持しつつ責務分割・API変更・書き直しを行う |
| C | codeは直接移送せず、test・設計・edge case・失敗事例を参考にする |
| D | engineへ移行しない |

`Reuse` は今回の `Migration state` / `Cleanup readiness` に置き換えない。
たとえば `Reuse = C` でも、新しいcontractで必要責務を満たした結果
`Migration state = superseded` になり得る。

### Migration state

| State | 意味 |
| --- | --- |
| `migrated` | 旧資産の主要contract / behavior / edge caseが現在のengine設計でも維持されている。renameやmodule分割は問わない |
| `superseded` | 必要責務は満たされているが、旧contract自体を意図的に別設計へ置き換えた |
| `partial` | 必要な旧contract / test / edge caseがまだmigration sourceとして残っている |
| `not migrated` | 現在もengine責務である必要機能が未移行 |
| `—` | engine責務外、または本Issueだけではengine migration stateを定義しない |

現在のコードに同名fileがないことだけを根拠として、旧contractを不要または
`superseded` と判定しない。現在の責務境界・確定済み設計契約を判断基準とし、
implementation / testを移行実績の証拠として使う。

### Cleanup readiness

| Cleanup readiness | 意味 |
| --- | --- |
| `ready for cleanup review` | engine migration sourceとして保持する必要はない。後続cleanup auditへ進められる |
| `retain as migration source` | engine側の将来判断・未移行contract・test / fixture / specification referenceのため、まだ保持する価値がある |
| `needs decision` | engine責務外・mixed responsibility・Replay等、この文書だけではcleanup方針を決めない |

`ready for cleanup review` は `python-study` から直ちに削除可能という意味ではない。
最終削除前に、`python-study` 内の残存依存、engine以外のconsumer、他repositoryへの
移行状況、将来利用・廃止方針を確認する。

個別ledgerの `Relevant test` は、現在のengine側でmigration判定の証拠として確認した
testを示す。`—` は「test不要」ではなく、engine責務外・consumer依存・未採用contract等の
理由でcurrent engine testをmigration evidenceとして紐付けないことを示す。`Notes` には、
特に `superseded` / `partial` / `—` / readiness例外の判定理由を残す。

## Responsibility boundary

engineが担うのは、日本リーチ麻雀を正しく進行するためのrule / state /
legal action / scoring / settlement / match executionと、それらを外部consumerへ
安全に渡すための最小boundaryである。

```text
lisjong -> lisjong-engine
lisjong-engine -X-> lisjong
```

engineに含めない主な関心は次のとおり。

- Policy / AI戦略
- 向聴数・受け入れ・牌効率・期待値・安全度
- RiichiEnv / RiichiLab adapter
- mjai等の通信protocol・process transport
- credential / bot token / 認証
- 学習dataset / decision log
- CLI / GUI / Human Play UI
- arena固有のevaluation metrics / provenance

一方、**どの席が何を知ってよいか**はengineが判定する必要があるため、
`SeatObservation` とpublic action boundaryはengine責務である。

## Audit summary

初回inventoryのgroupを、現在の実績へ再照合した結果。

| Group | Initial destination / reuse | Post-migration result | Cleanup direction |
| --- | --- | --- | --- |
| Domain model | engine / A | 中核contractは移行済み | 大半が `ready for cleanup review` |
| Winning / scoring | engine / A中心 | pure scoring layerは移行済み。`yaku.py` は識別子・評価・RuleSetへ分割 | 大半が `ready for cleanup review` |
| Legal actions / round state | engine / B中心 | pull API、revision、transactional reaction等を含む新構成へ移行 | `migrated` / `superseded`、cleanup review可 |
| Rules | engine / B | 単一 `RuleSet` へ置換し、4 concrete presetをfirst-party化 | `rules.py` / preset資料とも `ready for cleanup review` |
| Match / settlement | engine / A/B | state / settlement / final score / deterministic allocationへ再構成 | coreはcleanup review可。record/replay系は別判断 |
| Game-layer gray zones | 分割 / B/C/D | SeatObservation、public ActionDescriptor、external selector driverを採用 | engine core分はcleanup review可。visible-event / decision / Player実装は別判断 |
| mjai / adapter / transport | lisjong / D | engineへ移行しない | `needs decision` |
| CLI | python-study / D | engineへ移行しない | `needs decision` |
| Replay / verification / dataset | python-study / lisjong / C/D | historical replayはengine determinismとは別能力 | `needs decision` |
| Shared fixtures | engineで再構築 / B/C | explicit deterministic fixture手法を採用 | scenarioごとにreview |

## Production asset ledger

### Domain model

| Source | Responsibility | Dest | Reuse | Migration state | Current replacement | Relevant test | Cleanup readiness | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `tile.py` | 牌種・物理牌・34種/136枚ID・赤5 | engine | A | `migrated` | `src/lisjong_engine/tile.py` | `tests/test_tile.py` | `ready for cleanup review` | 物理牌ID・34種ID・赤5の主要contractを維持 |
| `seat.py` | 固定席 | engine | A | `migrated` | `src/lisjong_engine/seat.py` | `tests/test_seat.py` | `ready for cleanup review` | 固定4席の値contractを維持 |
| `wind.py` | 場風・自風 | engine | A | `migrated` | `src/lisjong_engine/wind.py` | `tests/test_wind.py` | `ready for cleanup review` | 風の値contractを維持 |
| `hand.py` | 手牌集合・物理牌ownership | engine | A | `migrated` | `src/lisjong_engine/hand.py` | `tests/test_hand.py` | `ready for cleanup review` | 物理牌ownershipをcore内部で維持 |
| `discard.py` | 捨て牌・河・鳴かれ記録 | engine | A | `migrated` | `src/lisjong_engine/discard.py` | `tests/test_discard.py` | `ready for cleanup review` | 河・鳴かれ状態のcontractを維持 |
| `meld.py` | ポン・チー・槓 | engine | A | `migrated` | `src/lisjong_engine/meld.py` | `tests/test_meld.py` | `ready for cleanup review` | 副露variantと物理牌構成を維持 |
| `wall.py` | live wall・dead wall・嶺上・表示牌 | engine | A | `migrated` | `src/lisjong_engine/wall.py` + `random_source.py` | `tests/test_wall.py`, `tests/test_random_source.py` | `ready for cleanup review` | 旧wall contractにdeterministic random sourceを追加 |
| `round_phase.py` | 局内phase | engine | A | `migrated` | `src/lisjong_engine/round_phase.py` | `tests/test_round_phase.py` | `ready for cleanup review` | current state machineでphase contractを維持 |
| `settlement.py` | 点数移動・供託授与の値型 | engine | A | `migrated` | `src/lisjong_engine/settlement.py` | `tests/test_settlement.py`, `tests/test_win_settlement.py`, `tests/test_draw_settlement.py` | `ready for cleanup review` | 値型に加えpure settlement logicも集約 |
| `furiten.py` | 振聴理由enum | engine | A | `migrated` | `src/lisjong_engine/furiten.py` + `player_state.py` | `tests/test_furiten.py`, `tests/test_player_state.py` | `ready for cleanup review` | 振聴理由とplayer状態への反映を維持 |

P1では旧domain modelを移行しただけでなく、旧sourceに正式contractがなかった
`RandomSource` / deterministic wall generationも新規に追加した。これは旧資産の
cleanupを妨げるものではない。

### Winning / scoring

| Source | Responsibility | Dest | Reuse | Migration state | Current replacement | Relevant test | Cleanup readiness | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `winning.py` | 和了形解析・待ち形 | engine | A | `migrated` | `winning.py` | `tests/test_winning.py` | `ready for cleanup review` | 通常形・七対子・国士等の解析contractを維持 |
| `win_context.py` | 和了時点のimmutable入力fact | engine | A | `migrated` | `win_context.py` | `tests/test_win_context.py` | `ready for cleanup review` | scoring入力factをimmutable boundaryとして維持 |
| `interpretation_analysis.py` | 面子分解の意味解析 | engine | A | `migrated` | `interpretation_analysis.py` | `tests/test_interpretation_analysis.py` | `ready for cleanup review` | 面子解釈の分析責務を維持 |
| `yaku.py` | Yaku identifier + 役判定 + `YakuRules` | engine | A/B | `superseded` | `yaku.py` + `yaku_evaluation.py` + `rules.py` | `tests/test_yaku.py`, `tests/test_yaku_evaluation.py`, `tests/test_rules.py` | `ready for cleanup review` | identifier・判定・設定へ意図的に責務分割 |
| `fu.py` | 符計算 + `FuRules` | engine | A/B | `migrated` | `fu.py` + `RuleSet` | `tests/test_fu.py`, `tests/test_rules.py` | `ready for cleanup review` | 符計算は維持し設定だけ`RuleSet`へ統合 |
| `dora.py` | 表・裏・カンドラ計数 | engine | A | `migrated` | `dora.py` | `tests/test_dora.py` | `ready for cleanup review` | indicator / ura / kan dora contractを維持 |
| `hand_value.py` | 翻・符の統合評価 | engine | A | `migrated` | `hand_value.py` | `tests/test_hand_value.py` | `ready for cleanup review` | hand valueの統合contractを維持 |
| `score.py` | 基本点・親子別支払 | engine | A | `migrated` | `score.py` + `RuleSet` | `tests/test_score.py`, `tests/test_rules.py` | `ready for cleanup review` | rule設定を注入しつつ得点contractを維持 |
| `winning_score.py` | 複数解釈の候補列挙・最大選択 | engine | A | `migrated` | `winning_score.py` | `tests/test_winning_score.py` | `ready for cleanup review` | 最大候補選択と同点候補保持を維持 |

現行architectureでも、得点評価層は `RoundState` から独立したpure layerであり、
成立役、翻・役満倍率、符・ドラ内訳を監査可能な形で保持する。この点は初回inventory
で高価値と判断したtest contractを維持している。

### Legal actions / round state

| Source | Responsibility | Dest | Reuse | Migration state | Current replacement | Relevant test | Cleanup readiness | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `legal_action.py` | internal合法手domain値・snapshot | engine | A | `migrated` | `legal_action.py` + `legal_actions.py` | `tests/test_legal_action.py`, `tests/test_legal_actions.py` | `ready for cleanup review` | stale snapshot拒否をrevision contractとして追加 |
| `reaction.py` | 捨て牌・加槓・暗槓への反応とpriority | engine | A/B | `superseded` | `reaction.py` + `reaction_boundary.py` + `kan.py` + `ron_legality.py` | `tests/test_reaction.py`, `tests/test_reaction_boundary.py`, `tests/test_kan.py`, `tests/test_ron_legality.py` | `ready for cleanup review` | batch atomic resolutionへ責務を再構成 |
| `riichi_event.py` | 立直宣言と成立確定 | engine | A | `migrated` | `riichi_event.py` + `round_state.py` | `tests/test_riichi_event.py`, `tests/test_round_state.py` | `ready for cleanup review` | contribution factとscore authorityを分離しつつ契約維持 |
| `round_event.py` | 局内objective event log | engine | A/B | `migrated` | `round_event.py` | `tests/test_round_event.py` | `ready for cleanup review` | objective factは維持しexternal canonical recordとは分離 |
| `round_result.py` | 和了・荒牌・途中流局結果 | engine | A | `migrated` | `round_result.py` + `winning_finalization.py` + `draw_resolution.py` | `tests/test_round_result.py`, `tests/test_winning_finalization.py`, `tests/test_draw_resolution.py` | `ready for cleanup review` | terminal result責務をfinalization/resolutionへ分割 |
| `round_state.py` | 1局の巨大状態機械 | engine | B | `superseded` | `round_state.py` + `player_state.py` + `legal_actions.py` + `reaction.py` + `kan.py` + `draw_resolution.py` + `winning_finalization.py` | `tests/test_round_state.py`, `tests/test_round_winning.py`, `tests/test_round_draw.py` | `ready for cleanup review` | pull API / revision / transactional mutationを採用したmany-to-many置換 |

旧 `round_state.py` は単一file 2,980行で、状態機械、PlayerState、合法手生成、
反応解決、和了確定等を抱えていた。現在は責務を複数moduleへ分割しつつ、
`RoundState` 自体はmutable coreとして維持している。したがって1対1のfile移植ではなく、
旧責務集合をmany-to-manyで置き換えた `superseded` と判定する。

### Rules

| Source | Responsibility | Dest | Reuse | Migration state | Current replacement | Relevant test | Cleanup readiness | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `rules.py` | `MahjongRules` + policy enum + external preset data | engine | B | `superseded` | frozen `RuleSet` + policy enum + `rule_presets.py` + `docs/rules.md` | `tests/test_rules.py`, `tests/test_rule_presets.py` | `ready for cleanup review` | defaultに加えexternal preset data / provenance / regression knowledgeもIssue #44で退避済み |
| `rule_preset.py` | `MahjongRules` / `YakuRules` / `FuRules`の束ね直し | engine | C/D | `superseded` | `RuleSet` | `tests/test_rules.py`, `tests/test_rule_presets.py` | `ready for cleanup review` | bundle型を廃止し単一設定contractへ統合 |

`rules.py` の旧contractは、単一 `RuleSet` とfirst-party concrete presetへ置換した。
Issue #44 ではproject-standard / Tenhou / Mahjong Soul / M Leagueについて、current
`python-study` の42 rule fieldと、旧 `YakuRules` / `FuRules` に分かれていた2 configを
再照合し、具体値・provenance・代表的なbehavior regressionをengine側へ退避した。

このため旧 `python-study/mahjong/rules.py` を **engine migration sourceとして保持する
必要はなくなった**。`ready for cleanup review` は直ちに削除可能という意味ではなく、
`python-study` 内の残存importやengine外consumerを後続cleanup auditで確認してから
実際の削除可否を決める。

### Match / settlement

| Source | Responsibility | Dest | Reuse | Migration state | Current replacement | Relevant test | Cleanup readiness | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `match_state.py` | 半荘状態機械 + 精算計算 | engine | B | `superseded` | `match_state.py` + `settlement.py` + `round_allocation.py` | `tests/test_match_state.py`, `tests/test_settlement.py`, `tests/test_round_allocation.py` | `ready for cleanup review` | Matchをscore authorityとしpure settlement / seed allocationを分離 |
| `final_score.py` | 順位・ウマ・オカ・端数・飛び賞 | engine | A | `migrated` | `final_score.py` | `tests/test_final_score.py` | `ready for cleanup review` | final score契約をcurrent RuleSet下で維持 |
| `match/initial_state.py` | historical Replay用の局開始状態 | python-study | C | `—` | current engine replacementなし | `—` | `needs decision` | historical replay concernでありdeterministic executionとは別能力 |
| `match/record.py` | `RoundRecord` / `MatchRecord` | lisjong | C | `—` | current engine replacementなし | `—` | `needs decision` | canonical `GameRecord`はcurrent engine責務として固定していない |
| `match/terminal_delivery_record.py` | Player終端配送の監査 | lisjong | D | `—` | current engine replacementなし | `—` | `needs decision` | Player delivery contractはengine責務外 |
| `match/terminal_event_projection.py` | 終端factの席別event射影 | engine（一部・保留） | C | `—` | current result / observationが一部factを提供 | `tests/test_round_result.py`, `tests/test_observation_builder.py` | `needs decision` | 差分deliveryはcurrent必須engine contractではなく、具体consumerで必要性を再評価 |
| `match/controller.py` | Playerを駆動する半荘orchestration | engine（縮小） | B/C | `superseded` | `driver.py` + `match_state.py` + `action_projection.py` | `tests/test_driver.py`, `tests/test_match_state.py` | `ready for cleanup review` | push型Player orchestrationをexternal selector型driverへ置換 |

`match_state.py` の旧「状態機械＋pure settlement」の混在は、current engineで
`match_state.py` と `settlement.py` へ明確化された。さらに半荘seedから局seedを
deterministicに割り当てる責務は `round_allocation.py` / random provenance側で
engine contractとして確立した。

### Game-layer gray zones

| Source | Responsibility | Initial dest | Reuse | Migration state | Current replacement | Relevant test | Cleanup readiness | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `game/public_state.py` | 公開河・副露等のpublic値型 | engine | B | `migrated` | `public_state.py` | `tests/test_public_state.py` | `ready for cleanup review` | public stateの値contractを維持 |
| `game/observation.py` | `PlayerObservation` + action options | engine | B | `superseded` | `SeatObservation` (`observation.py`) | `tests/test_observation.py` | `ready for cleanup review` | action boundaryを分離しphysical IDをObservationから排除 |
| `game/observation_builder.py` | 席別snapshot射影 | engine | B | `superseded` | `observation_builder.py` | `tests/test_observation_builder.py` | `ready for cleanup review` | Match + active Roundからpure projectionしhidden情報をfail closedで除外 |
| `game/player.py` | `Player` ABC | engine（概念のみ） | C | `superseded` | `driver.py` のseat-specific selector callable | `tests/test_driver.py` | `ready for cleanup review` | engineはPlayer class hierarchyを所有しない設計へ確定 |
| `game/controller.py` | push型1局Player loop | engine（縮小） | B/C | `superseded` | `RoundState` pull API + `driver.py` | `tests/test_round_state.py`, `tests/test_driver.py` | `ready for cleanup review` | rule priorityはcore resolverに残しorchestrationをthin化 |
| `game/action_descriptor.py` | physical IDを隠した合法手表現 | engine | C | `superseded` | `action_descriptor.py` + `action_projection.py` | `tests/test_action_descriptor.py`, `tests/test_action_projection.py` | `ready for cleanup review` | initial planの不要判断から、public boundaryとして新contractへ再設計 |
| `game/action_translation.py` | process-global action_id ↔ internal action | 廃止 | D | `superseded` | snapshot-local descriptor resolution | `tests/test_action_projection.py`, `tests/test_driver.py` | `needs decision` | process-global IDは廃止したが旧fileのengine外利用有無は後続cleanupで確認 |
| `game/player_visible_event.py` | 席別差分event union | engine（保留） | C | `—` | current snapshot observation boundary | `tests/test_observation.py`, `tests/test_observation_builder.py` | `needs decision` | 差分eventはcurrent必須engine contractではなくrecord/replay/interoperability PoCで再評価 |
| `game/visible_event_translation.py` | `RoundEventLog` → 席別差分event | engine（保留） | C | `—` | current snapshot observation boundary | `tests/test_observation_builder.py` | `needs decision` | differential delivery自体をv0.1 contractとして採用していないため`not migrated`とはしない |
| `game/decision.py` | DecisionRecord / DecisionLog | lisjong | D | `—` | current engine replacementなし | `—` | `needs decision` | AI / learning / audit側の関心 |
| `game/decision_input.py` | observation + 差分event入力 | lisjong | D | `—` | current engine replacementなし | `—` | `needs decision` | Player / Policy integration側の関心 |
| `game/event_input.py` | Decision外event delivery batch | lisjong | D | `—` | current engine replacementなし | `—` | `needs decision` | engineはPlayer delivery contractを所有しない |
| `game/human_player.py` | CLI向けPlayer | python-study | D | `—` | current engine replacementなし | `—` | `needs decision` | Human Play / UI側の関心 |
| `game/random_player.py` | random意思決定主体 | lisjong / python-study | C | `—` | test-only selector pattern | `tests/test_driver.py` | `needs decision` | engineはPolicyを所有せず、seed明示・決定的test手法だけを引き継ぐ |

特に `game/action_descriptor.py` は初回計画からの重要な設計変化である。
初回は「internal `LegalAction` を直接公開できるなら不要」と評価したが、G1/G2の
実装でhidden physical tile identityを外部へ漏らさず、外部selectorが合法手を選択する
必要が具体化した。その結果、current engineでは **public `ActionDescriptor` を採用**した。
これは旧fileの単純移植ではなく、具体consumer boundaryから再設計した
`superseded` と記録する。

### Engine-external assets

以下はengineへ移行しない判断自体は維持するが、この文書だけで
`python-study` からの削除可否を決めない。

| Assets | Initial destination | Reuse | Current engine judgment | Relevant test | Cleanup readiness | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `game/mjai_protocol.py`, `game/mjai_adapter.py`, `game/mjai_process_transport.py`, `game/_mjai_test_bot.py` | lisjong | D | protocol / adapter / process transportはengine責務外 | `—` | `needs decision` | engine migration stateを定義しない |
| `cli/main.py`, `cli/renderer.py`, `cli/action_chooser.py`, `cli/match_summary.py`, `cli/seat_display.py` | python-study | D | CLI / Human Play UIはengine責務外 | `—` | `needs decision` | future Human Play側で保存・移行・廃止を判断 |
| `decision_dataset.py` | lisjong | D | learning datasetはengine責務外 | `—` | `needs decision` | lisjong側の学習data contractと照合が必要 |
| `terminal_delivery_verification.py` | python-study | D | Player delivery監査はengine責務外 | `—` | `needs decision` | delivery consumerの存否を後続auditで確認 |

## Replay / verification correction

初回文書では、`replay_engine.py` / `replay_projection.py` をengineへ移さない理由を
「seed基盤の決定性で代替」と説明していた。post-v0.1 architectureでは、この説明を
そのまま現在の正本にはしない。

```text
same initial conditions + same actions
        -> deterministic re-execution
```

と、

```text
saved historical evidence
        -> historical replay / analysis
```

は別能力である。

current engineは deterministic executionを確立したが、それは「当時実際に起きたこと」
を保存したhistorical evidenceの代替ではない。engine versionやRuleSet semanticsが
将来変われば、再実行結果とhistorical recordは一致する保証がない。

したがって次の資産は、**engine v0.1へ未移植だから不要**とは判定しない。

| Source | Initial reuse | Migration state | Post-migration judgment | Relevant test | Cleanup readiness | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `replay_engine.py` | C | `—` | historical replay concern。current deterministic executionとは別 | `—` | `needs decision` | record / replay consumer PoCで必要性を評価 |
| `replay_projection.py` | C | `—` | replayからplayer-facing stateを再構成するconsumer concern | `—` | `needs decision` | snapshot observationで代替済みとは判定しない |
| `decision_verification.py` | C | `—` | recorded decision / dataset品質保証。engine determinism testとは目的が異なる | `—` | `needs decision` | lisjong / dataset側の監査contractと照合が必要 |
| `match/initial_state.py` | C | `—` | historical replayの初期evidence modelとして再評価対象 | `—` | `needs decision` | deterministic initial state生成とは別のpersistence concern |
| `match/record.py` | C | `—` | record / replay / analysis consumer PoCで再評価 | `—` | `needs decision` | canonical record schemaを先行固定しない |

`roadmap.md` の Recordability Support に従い、巨大なcanonical `GameEvent` /
`GameRecord` schemaを先行移植しない。まずcurrent engineのobjective factsを
具体的なrecord / replay / analysis consumer PoCで評価し、不足が実証された場合だけ
minimum contractを追加する。

## Test / fixture migration

### High-value regression contracts

初回inventoryで特に価値が高いと判断したtest contractは、現在のengine test suiteへ
責務単位で引き継いだ。test file名やfixture構造の1対1一致は要求しない。

| Initial test / concern | Initial reuse | Current evidence | Migration state |
| --- | --- | --- | --- |
| `test_round_state.py` / `test_round_winning.py` / `test_abortive_draw.py` | B | current round / reaction / kan / winning / draw tests、`tests/_round_fixtures.py` | `migrated` |
| `test_yaku.py` | A | current yaku / yaku evaluation tests | `migrated` |
| `test_winning_score.py` | A | current winning score tests | `migrated` |
| `test_winning.py` | A | `tests/test_winning.py` | `migrated` |
| `test_match_settlement.py` | B | current settlement / draw settlement / match tests | `migrated` |
| `test_match_state.py` | B | current match state tests | `migrated` |
| `test_riichi_event.py` | A | current riichi / round tests | `migrated` |
| `test_legal_action.py` | A | current legal action / legal actions tests | `migrated` |
| `test_round_event.py` | A/B | current round event / terminal result tests | `migrated` |
| `test_final_score.py` | A | `tests/test_final_score.py` | `migrated` |
| `test_fu.py` / `test_dora.py` / `test_score.py` | A | current scoring tests | `migrated` |
| external preset / `test_rules.py` / `test_rule_preset.py` | B/C | `tests/test_rules.py` + `tests/test_rule_presets.py` | `migrated` |

### Shared fixtures

| Source | Initial reuse | Current replacement / judgment | Relevant test | Migration state | Cleanup readiness | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `_ankan_chankan_round_fixture.py` | B/C | explicit tile-name / wall constructionは `tests/_round_fixtures.py` に採用。旧record型は移さない | `tests/_round_fixtures.py`, `tests/test_kan.py`, `tests/test_round_winning.py` | `partial` | `retain as migration source` | fixture固有edge caseがcurrent testsへ全て対応したか最終照合が残る |
| `_kakan_round_fixture.py` | C/D | RandomPlayer seed探索をやめ、明示的初期wall + public API駆動へ置換 | `tests/_round_fixtures.py`, `tests/test_kan.py`, `tests/test_round_state.py` | `superseded` | `ready for cleanup review` | fixture手法自体をdeterministic explicit setupへ置換済み |

fixtureのcleanupでは「旧helper fileがあるか」ではなく、そのfixtureが唯一保持していた
rule edge caseがcurrent testsで固定されているかを確認する。

## Document migration

| Source | Initial reuse | Current replacement / judgment | Relevant test | Migration state | Cleanup readiness | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `python-study/docs/mahjong-rules.md` | B | `docs/rules.md` + `rule_presets.py` + current implementation contractへ再構成 | `tests/test_rules.py`, `tests/test_rule_presets.py` + rule/scoring/round tests | `superseded` | `ready for cleanup review` | project-standardに加えexternal preset provenance / 情報源 / intentional差分もIssue #44で退避済み |
| `python-study/mahjong/README.md` | C | engine READMEへ丸ごと移さない | `—` | `—` | `needs decision` | learning history / old runtime説明が混在 |
| `python-study/docs/mahjong-architecture.md` | C | engine知見は `architecture.md` / `rules.md` / 本ledgerへ抽出 | `—` | `—` | `needs decision` | lisjong・mjai・進捗履歴も混在するためcross-repo判断が必要 |

`python-study` 側の学習履歴を保持するか、active mahjong runtimeとしての記述を
cleanupするかは、このIssueでは決めない。`mahjong-rules.md` の
`ready for cleanup review` も、engine migration sourceとしての保持理由がなくなった
ことだけを意味する。

## Initial migration phases -> actual results

初回のP1〜P7は、現在は「今後の提案」ではなくhistorical migration planである。
実績との対応を次に固定する。

| Initial phase | Initial scope | Actual result | Tracking |
| --- | --- | --- | --- |
| P1 | Domain model + seed基盤 | complete | Issue #5 / PR #6 |
| P2 | 和了形解析 | complete | Issue #9 / PR #10 |
| P3 | `RuleSet`統合 | complete（default + external preset migration） | Issue #11 / PR #12、Issue #44 / PR #45 |
| P4 | 得点評価 | complete | Issue #13 / PR #14 |
| P5 | 合法手・1局状態遷移 | splitしてcomplete | Issue #15 / PR #16、Issue #17 / PR #18、Issue #19 / PR #20 |
| P6 | 精算・半荘状態管理 | splitしてcomplete | Issue #21 / PR #22・#23、Issue #24 / PR #25 |
| P7 | 席別観測 + public action + deterministic driver | splitしてcomplete | Issue #26 / PR #28、Issue #29 / PR #30 |

P7は初回計画から設計が具体化した。G1で `SeatObservation` を確立し、G2 / driverで
public `ActionDescriptor`、snapshot-local resolution、external selector boundaryを
追加した。engineはPolicy / Player ABCを所有しない。

`docs/roadmap.md` は、このP1〜P7で成立したdeterministic minimal hanchan driverまでを
v0.1相当のcurrent foundationとして扱う。以降のcorrectness hardening、
recordability、consumer readiness、performance、RuleSet evolutionは
**migration phaseの未完了項目ではなくpost-v0.1 track**である。

## Initial open questions -> current status

初回文書のfuture-facing Open questionsは、現在実績と次のように同期する。

| Initial question | Current status | Judgment |
| --- | --- | --- |
| Python 3.14 compatibility | resolved for current engine foundation | lisjong-engineはPython 3.14 contractのもとP1〜P7を実装・testしている。旧python-studyの3.11 runtime移植自体を要求しない |
| `RoundState` の分割単位 | resolved for v0.1 | `player_state.py`, `legal_actions.py`, `reaction*`, `kan.py`, `winning_finalization.py`, `draw_resolution.py`等へ責務を抽出。今後のさらなる分割はhardening |
| `Hand` / `River` のmutability | resolved in P1 | current mutable domain modelをcore mutation boundary内で使用 |
| seed APIの粒度 | resolved for current foundation | `RandomSource`、Match / round allocation、random provenanceでdeterministic executionを確立 |
| 終局基準ちょうど30,000点等のexternal rule差 | resolved for migrated presets | Tenhou / Mahjong Soul / M Leagueの確認済み差分はconcrete first-party presetとして固定。未追加service / variantは引き続きevidence-drivenで扱う |
| RiichiLab固有rule preset | external dependency / not fixed | `lisjong`側の実測等で確定するまで推測で追加しない |
| reactionの3経路統合 | resolved by current implementation for v0.1 | current `reaction.py` / `reaction_boundary.py` / `kan.py`等のcontractを正本とする |
| external preset追加時の検証手段 | established for current presets | current source / provenanceを再確認し、独立完全定義・field差分・representative behavior regressionで固定する。未確認値は推測しない |

Open questionが解消したことは「その実装を永久に変更しない」という意味ではない。
post-v0.1 hardeningは `roadmap.md` に従う。

## Cleanup handoff

このledgerは、次の `python-study` cleanup auditへの入力である。

### `ready for cleanup review`

engine migration sourceとしては保持不要と判断した資産。**まだ削除しない。**

主な候補:

- domain modelの旧source
- winning / scoringの大部分
- legal action / round stateの旧source
- `rules.py` / `rule_preset.py` とexternal preset runtime data
- `docs/mahjong-rules.md` のengine rule / external preset migration sourceとしての役割
- core `match_state.py` / `final_score.py`
- old `game/public_state.py` / observation / controller / Player-ABC concept source
- old `game/action_descriptor.py`
- `_kakan_round_fixture.py` の旧seed探索fixture

後続auditでは、`python-study` 内のCLI / Replay等がこれらをimportしていないか、
あるいは同じfileにengine外の未移行情報が混在していないかを確認してから削除する。

### `retain as migration source`

現時点でengine migration/referenceの価値が残るもの。

- `_ankan_chankan_round_fixture.py` のspecific edge-case coverage（current testとの最終照合まで）

Issue #44 により、`python-study/mahjong/rules.py` と
`python-study/docs/mahjong-rules.md` のexternal preset data / provenanceはこのlistから
外れた。必要情報は `rule_presets.py`、`tests/test_rule_presets.py`、`docs/rules.md` に
退避済みである。

### `needs decision`

engineだけでは最終cleanup方針を決めないもの。

- mjai / adapter / transport
- CLI / Human Play
- Decision / dataset / delivery verification
- Replay / record / verification
- player-visible differential event
- mixed-purpose historical docs

後続auditでは、`lisjong` / `lisjong-arena` / future Human Play /
Visualization・Analysis等の現在責務と突き合わせ、移行・保存・廃止を決める。

## Audit conclusion

初回P1〜P7の**engine core migrationはv0.1相当まで完了している**。
さらにIssue #44でexternal rule preset data / provenance / representative regressionも
first-party `RuleSet` presetへ退避した。このため `python-study/mahjong` はもはや
engine実装全体やexternal presetの恒久的なmigration sourceとして保持する必要はない。

一方で、次を理由に `python-study/mahjong` directory全体を一括削除してはならない。

- CLI / Human Play、mjai、Decision / dataset等はengine責務外であり、別repositoryの
  migration状況を確認する必要がある
- deterministic re-executionはhistorical Replay / recordabilityの代替ではない
- shared fixture / testにはproduction codeとは独立したrule edge-case資産がある
- mixed-purpose historical docsにはengine migration以外の学習履歴・設計履歴が残り得る

次の工程は、本ledgerの `Cleanup readiness` を入力として `python-study` 側で
dependency-aware cleanup auditを行い、実際の削除scopeを決めることである。
