# Architecture

## 目的

`lisjong-engine` は、日本式リーチ麻雀を正しく進行するための独立したゲームエンジンである。
AI戦略や外部実行環境との通信を担当せず、麻雀ルールと状態遷移の正しさを責務とする。

lisjong ecosystem全体のrepository責務とrepository間依存方向は、
[`lisjong-project` のArchitecture](https://github.com/lisbun/lisjong-project/blob/main/docs/architecture.md)を正本とする。
本書は、その横断境界の内側にある `lisjong-engine` 固有のarchitectureを正本として扱う。

## 責務境界

### engineに含める

- 牌、手牌、山、河、副露等のドメインモデル
- game / round / turnの状態管理
- 合法手判定・合法手生成
- 和了可能性、役、符、点数の判定・計算
- 鳴き、リーチ、流局、途中流局、本場、供託、連荘
- 東風戦・半荘等の対局進行
- 最終点数・順位処理
- `RuleSet` とpreset
- 再現可能なgame実行に必要なseed管理
- engine自身のtestに必要な最小driver

### engineに含めない

- Policyや麻雀AI戦略
- 向聴数、受け入れ枚数、牌効率、期待値、安全度、放銃リスク、押し引き
- RiichiEnv Adapter
- RiichiLab WebSocket client
- mjai等の通信protocol処理
- credential / bot token / 認証処理
- 学習・推論・ニューラルネットワーク

責務判断では、**その機能がなくても麻雀ゲームを正しく進行できるか**を基準とする。
進行できるなら、原則としてAI・評価側の機能とする。

## 依存方向

```text
lisjong -> lisjong-engine
lisjong-engine -X-> lisjong
```

`lisjong-engine` は `lisjong`、RiichiEnv、RiichiLabへ依存しない。
外部環境との接続は利用側がAdapter等で吸収する。

## RuleSet

麻雀ルールの実装機構と個別ルール設定を分離する。

```text
rule mechanics + RuleSet
```

将来的には `RuleSet.default()` や `RuleSet.riichilab()` のようなpresetを追加できる構成を目指す。
ただし、初期段階から多数のpresetを用意しない。

外部サービス固有presetへ反映する項目は、公式仕様、公開実装、実測等で確認できたものに限定する。
未確認のルールを推測で埋めない。

## 得点評価層

役、符、ドラ、点数の評価は、局状態機械から独立したpureな評価層として実装する（Issue #13）。

```text
immutable scoring facts + RuleSet -> immutable evaluation result
```

入力は和了時点で確定した事実だけであり、`RoundState` を参照しない。

```text
WinningContext + DoraIndicators + winning interpretations + RuleSet
    -> WinningScoreSelection
```

`Yaku` identifier（`yaku.py`）と役の成立判定（`yaku_evaluation.py`）は別moduleとし、
`RuleSet` から評価logicへの逆依存を作らない。役・符は `interpretation_analysis` の
正規化結果を共有し、面子のopen/concealedやロン完成刻子を各層で再推測しない。

評価結果は最終点数へ潰さず、成立役、役ごとの翻・役満倍率、符の内訳、ドラの内訳を
保持して、評価根拠を人間が監査できる形を維持する。複数の和了解釈はすべて個別に
評価し、最高得点候補が同点の場合も1つへ潰さない。

得点評価層が担当するのは、1人の和了に対する基本支払点までである。本場、供託、
複数ロンの支払配分、パオの最終精算、流し満貫の局精算はRound / Match層の責務とする。

詳細な契約は `docs/rules.md` の「9. 得点評価とRuleSet」を正本とする。

## 局のcore API

局の状態機械は、engineがPlayer / Policyを呼び出すpush型controllerではなく、
呼び出し側が合法手を見て選び、engineへ適用するpull型境界とする（Issue #15）。

通常手番では次の形をとる。

```text
snapshot = state.legal_actions(seat)
chosen = snapshot.actions[0]
state.apply(seat, chosen, expected_revision=snapshot.revision)
```

engine自身はactionを選択しない。`apply()` はcallerの「さきほど合法だった」という
主張を信用せず、必ず現在の状態から合法手を再導出して照合する。

捨て牌・加槓・暗槓に対する反応は、複数seatのchoiceをcaller側で集めてから
1 transactionとして解決する（Issue #17）。

```text
choices = {
    seat: choose(state.legal_actions(seat))
    for seat in state.reacting_seats
}
resolution = state.resolve_reactions(
    choices,
    expected_revision=state.revision,
)
```

`reacting_seats` はsource / declarer以外の3席すべてを返し、実質的に反応できない席にも
`PassLegalAction` を提示する。seatごとの逐次commitは行わず、Ron / Pon / Chi /
Daiminkan等のpriorityはengine側のpureなresolverでdeterministicに確定する。

### action identityとstaleness

`LegalAction` はdomain値であり、process-globalなaction ID、UUID、adapter用の
整数handleを持たない。actionの同一性は物理牌IDと宣言内容だけで判別する。

一方、古いsnapshotから取り出したactionの検出には、局内の**state revision**を使う。
revisionは局ローカルかつ単調増加で、同じ初期状態と同じaction sequenceからは常に
同じprogressionになる。偶然同じdomain valueが現在も合法な場合でも、revisionが
一致しなければfail closedで拒否する。

```text
LegalAction identity = domain data
staleness            = RoundState revision
```

通常action、reaction batchのいずれも、成功した1 transactionにつきrevisionは1だけ増える。

### mutation boundary

`RoundState` はmutableだが、状態を進める操作はtransactionalとする。
validationまたは遷移が失敗した場合、本体へpartial mutationを残さない。

通常actionは概ね次の順序で処理する。

```text
seat / phase / revision validation
    -> 現在stateから合法手を再導出
    -> action membership validation
    -> working copyへ遷移
    -> invariant validation
    -> 成功時のみcommit
```

reaction batchも同じ原則に従い、全seatのchoiceを検証してpriorityを解決した後、
working copy上で一発・フリテン・立直・副露・槓ドラ等をまとめて更新し、
invariantを満たした場合だけ1回commitする。missing / extra / illegal choiceやstale revisionで
失敗した場合、player state、phase、pending fact、event、revisionのいずれも変更しない。

外部へ公開する状態はtuple等のimmutable viewに限り、`Hand` / `River` / `Wall` を
直接渡さない。core APIを迂回した状態書き換えを構造的に防ぐためである。

物理牌の不変条件は「どのobjectを通しても1回しか現れない」ではなく、
**ownership上の重複・消失がない**ことと定義する。河の捨て牌と鳴きmeldが同じ
物理牌を参照する局面でも破綻しない定義を維持するためである。

### Matchとの点数境界

`RoundState` は局開始時の持ち点を、必須のimmutable snapshotとして受け取る。

```text
RoundState(
    wall,
    round_start_points={Seat.EAST: ..., Seat.SOUTH: ..., Seat.WEST: ..., Seat.NORTH: ...},
)
```

`round_start_points` は立直可能条件等、その局の合法手判定に必要な入力factであり、
`RoundState` がMatch全体のauthoritativeな現在点を所有することを意味しない。

立直成立時もRoundState自身は持ち点を減算せず、`RiichiContribution` と
`riichi_payment_deltas` を記録する。実際の点数移動と供託本数の管理はMatch層が担当する。
これによりRoundの合法手・状態遷移と、Matchの継続的な点数authorityを分離する。

### 合法手導出と反応境界

合法手の導出は状態mutationから分離したpure moduleに置き、`RoundState` 側は
薄いfacadeとする。

反応windowでは現在stateから各seatの合法手を再導出し、callerが渡したchoiceを再検証する。
反応のpriority解決自体もpureなresolverへ分離し、mappingのiteration順に結果を依存させない。

鳴き後の打牌はdrawを伴わないため、pending discardのprovenanceである
`pending_discard_source` はoptionalである。`LIVE_WALL` / `RINSHAN` はdraw由来の打牌を表し、
`None` はChi / Pon後等のツモなし打牌を表す。provenanceが無いことを理由にreaction windowを
失わない。

### 槓と一発のconfirmation境界

Kakanは必ず槍槓reaction windowを開き、宣言factをpendingとして保持する。元のPonは
`AWAITING_KAKAN_REACTIONS`中には破壊的に置換せず、RonならKakanを成立させない。
all-passで初めてKakanをconfirmationし、PonをKakanへ置換する。

Ankanがpending reactionを経由するのは、`kokushi_ankan_chankan_enabled`が有効で、かつ
合法な国士無双による暗槓槍槓候補が存在する場合だけである。この場合は宣言factをpendingとして
保持して`AWAITING_ANKAN_REACTIONS`へ入り、Ronなら不成立、all-passならconfirmationする。
合法な候補が存在しない場合は、宣言と同じtransactionでAnkanをconfirmationし、
`AWAITING_RINSHAN_DRAW`へ移る。

一発を終了するのも槓の宣言ではなく成立時点である。したがって槍槓Ronで成立しなかった
Kakan / Ankanでは一発factを維持し、E3が `RIICHI + IPPATSU + CHANKAN` を含む
`WinningContext` を構築できる。reaction候補のないAnkanは宣言と同じtransactionで成立するため、
そのtransactionの完了時には一発も終了する。成立したChi / Pon / Daiminkan / Kakan / Ankanは
一発を終了する。

槓ドラの公開タイミングは`RuleSet.kan_dora_reveal_policy`へ従う。暗槓と加槓は成立時に公開し、
`DELAY_OPEN_KAN_DORA`における大明槓だけは直後の打牌がRon以外で解決するまで保留する。

### E2と和了確定の境界

Issue #17（E2）は、Ronの合法性・reaction priority・成立者とprovenanceを確定するところまでを
担当する。Ron成立後は `RoundPhase.AWAITING_WIN_FINALIZATION` へ移り、immutableな
`PendingRonResolution` にsource、target tile、成立者、chankan / last-tile判定に必要なfactを保持する。

```text
reaction resolution
    -> AWAITING_WIN_FINALIZATION
    -> PendingRonResolution
    -> E3: scoring / RoundResult
```

E2では点数確定や`RoundResult`構築を先取りしない。同じreaction windowの二重解決はphaseと
pending factのinvariantで拒否する。

### RoundResultとterminal event

E3の局終了値は`round_result` moduleのimmutable contractとして定義する。
`RoundResult`は`WinResult | ExhaustiveDrawResult | AbortiveDrawResult`であり、流し満貫は
独立variantにせず`ExhaustiveDrawResult.nagashi_mangan_seats`へ保持する。

`WinningPlayerResult`は席、`WinningContext`、選択済みの`WinningScoreSelection`だけを保持する。
役・符等は`WinningScoreSelection`が参照する`HandValueEvaluation`に既に含まれるため、
terminal resultへ重複して保持しない。`WinResult.dora_indicators`は各和了の得点評価で有効だった
表示牌snapshotであり、その構築規則やWallのmutationは本value objectの責務ではない。

局終了eventは結果種別ごとに分けず、`RoundEndedEvent(result)`の1種類とする。本場、供託、
実際の点数mutation、複数Ronの支払配分、match進行はこのcontractへ含めない。これらの型は
責務moduleから直接importし、package top-levelへ一括re-exportしない。

### 和了finalization境界

和了評価のpure境界は、winner単位のimmutableな`WinningClaim`と、Wallからコピーした
`DoraIndicatorState`を入力とする。どちらもmutableな`RoundState`、`PlayerState`、`Wall`を
保持しない。`winning_finalization` moduleが、このfactから`WinningContext`、claim時点で有効な
`DoraIndicators`、`WinningScoreSelection`、`WinResult`を構築する。

ツモ合法手の導出は候補列挙をnon-throwing probeとして利用し、得点候補が無い場合は
`TsumoLegalAction`を提示しない。action適用時とRon確定時は`evaluate_winning_scores()`で
strictに再評価する。Ron牌は評価用の`WinningContext.concealed_tiles`へだけ追加し、
winnerの`PlayerState`へは追加しない。

Ronは`AWAITING_WIN_FINALIZATION`の`PendingRonResolution`を
`finalize_pending_win(expected_revision=...)`で消費する。通常winnerはE2の
`ron_awarded_seats`をそのまま使用し、reaction priorityを再計算しない。三家和判定だけは、
3席が実際にRonを選んだ`ron_selected_seats`と`RuleSet.triple_ron_abortive_draw`を使う。

indicatorは通常表示牌を`visible`、公開済み槓表示牌を`kan`へ分離し、それぞれ対応する
`ura` / `kan_ura`も同じ位置から構築する。未公開の遅延大明槓表示牌は、その宣言席自身の
RINSHAN claimにだけscoring上追加する。直後の打牌Ronには追加せず、いずれの場合も
scoring snapshotのためにWallを公開・mutationしない。

和了terminal commitはworking copy上でresult、単一の`RoundEndedEvent`、pending cleanup、
`FINISHED`をまとめて構築する。`FINISHED`ではresultとterminal eventが一意に一致し、eventは
logの最後で、進行中factとpending槓ドラは残らない。非`FINISHED`ではresultもterminal eventも
存在しない。

### 流局判定境界

九種九牌・四風連打・四槓散了・四家立直・荒牌流局・流し満貫の成立可否は`draw_resolution`
moduleへ分離する。`RoundState` / `PlayerState` / `Wall`のmutable objectは受け取らず、
`WinningClaim` / `DoraIndicatorState`と同様に、席別のimmutableな最小factだけを入力とする。

`NineTerminalsLegalAction`は他のturn actionと同じpull契約に従う。callerが選択したときだけ
`AbortiveDrawResult(NINE_TERMINALS)`へ終局し、engineが自動的に選ぶことはない。合法手probe
とapply時のstrict revalidationは同じ`derive_nine_terminals_eligibility()`を共有し、判定logicを
二重実装しない。

自動判定される途中流局・荒牌流局は、それぞれ次の時点でだけ判定する。

```text
四風連打・四家立直   最後の打牌のreaction windowがRon・鳴きなしで解決した後
四槓散了             槓が実際に確定した直後（槍槓で流れた未成立の槓は数えない）
荒牌流局             最後の打牌のreaction windowがRonなしで解決した後
```

`_finish_discard_without_ron()`が、reaction不要のfast pathとexplicit all-pass pathの両方から
呼ばれる共通の後処理として、この判定を一箇所へ集約する。live wallが尽きた瞬間には終局せず、
海底ツモ・最終打牌・河底ロンの機会を必ず経てから荒牌流局を確定する。

荒牌流局のtenpaiは、向聴数・受け入れ枚数等の牌効率judgementではなく、既存の和了形解析
（`find_winning_tile_types` / `PlayerState.winning_tile_types`）が返す待ちの有無で判定する
semantic tenpaiであり、役の有無では判定しない。流し満貫は独立したterminal causeにせず、
`ExhaustiveDrawResult.nagashi_mangan_seats`として扱う。

## 局精算（Round settlement）

E3が確定する `RoundResult` から、1局分の点数移動をpureに計算する層を
`settlement.py` へ置く（Issue #21）。`RoundState` や `Wall` 等のmutable
objectは受け取らず、局終了時点で確定済みのfactだけを入力とする。

```text
RoundResult
+ dealer seat
+ honba
+ riichi sticks before round settlement
+ current-round RiichiContribution
+ RuleSet
        ↓
calculate_round_settlement(...)
        ↓
RoundSettlement
```

`RoundSettlement` から、呼び出し側は少なくとも次を取得できる。

- 席別 `point_deltas`（`SeatPoints`）
- player間の `SettlementTransfer`（Ron / Tsumo / Pao Ron / Pao Tsumo / 本場 /
  ノーテン罰符 / 流し満貫を含む、監査可能な個別移動）
- 今局で成立した `RiichiContribution`
- 今局で確定した `RiichiStickAward`（和了による供託獲得）
- settlement後にcarryされる供託本数 `riichi_sticks_after`

`calculate_round_settlement()` は、返す `RoundSettlement` について

```text
sum(point_deltas) + (riichi_sticks_after - riichi_sticks_before) * riichi_stick_points = 0
```

という価値保存を自ら検証し、崩れていれば `ValueError` でfail closedする。
供託棒はplayerの点数そのものではなく、卓上に留保された価値だからである。

Ron / Tsumoの通常精算に加え、大三元・大四喜・四槓子のパオ（責任払い）も
この層が扱う。`RuleSet.pao_compound_yakuman_policy` により、パオ対象役満と
対象外役満が複合したときの責任範囲を `FULL_HAND` と
`RESPONSIBLE_YAKUMAN_ONLY` から選べる。`RESPONSIBLE_YAKUMAN_ONLY` かつ
`multiple_yakuman_enabled=False` で複合役満を分割できない場合は、
黙って1つを選ばずfail closedする。

### scoringとの責務境界

局精算は、和了確定時に`WinningScoreSelection`へ保持された評価済みの

```text
WinningScoreSelection.max_score_candidates
```

を使用し、役・符・ドラを局精算層で再評価しない。パオの責任対象判定も、
`HandValueEvaluation` / `YakuEvaluation` が既に保持している成立役・
役満倍率のfactを参照するだけであり、`evaluate_yaku()` 等のscoring
そのものを再実行しない。

同点の最高得点候補が複数存在しても、精算に必要な支払額（`ron_payment`、
`tsumo_dealer_payment`、`tsumo_non_dealer_payment`）が候補間で一致しない
場合は、局精算側が任意の1件を選ばず `ValueError` で拒否する。得点評価層が
複数の和了解釈を意図的に潰さずに保持する契約（本書「得点評価層」参照）を、
精算層が誤った代表選択で壊さないためのfail-closed境界である。

### F1 / F2 境界

Issue #21のscopeはF1（局精算のpure計算）のみであり、MatchState等の状態機械や
半荘進行そのものは含まない。

```text
RoundSettlement apply
 -> scores_after_round
 -> F2 determines continuation / match end / bankruptcy
 -> bankruptcy adjustment
 -> final remaining riichi stick award
 -> calculate_final_scores()
```

F1が提供するのは次のpure calculation layerである。

- `calculate_round_settlement()`
- `calculate_final_riichi_stick_awards()`（半荘終了確定後の残存供託棒配分）
- bankruptcy adjustment pure helpers（`calculate_bankruptcy_points_by_seat()`
  等、飛びによる点数調整の計算だけを行い、飛び自体の判定は行わない）
- `calculate_final_scores()`（粗点・ウマ・オカ・順位点の最終計算）

一方、次はF2の責務としてF1へ持ち込まない。

- `MatchState`
- 局番号進行
- 親継続判定
- 本場更新
- match終了判定
- 飛び判定そのもの（飛んだ席が生じたかどうかの判定）
- deterministic round seed allocation

## Determinism

engineのテスト・回帰確認・AI評価へ利用できるよう、同じversion、`RuleSet`、seed、入力系列から
同じ状態遷移と結果を再現できる設計を重視する。

乱数の利用箇所はengine内部で管理し、暗黙のglobal random stateへ依存しない。

初期seed境界は次のとおり確定している（Issue #5）。

```text
seed: int -> RandomSource -> shuffled Wall
```

`RandomSource` はseedから決定的に生成されるengine-ownedな乱数sourceであり、
`Wall`自身はseed管理責務を持たない。半荘seedと局seedの配分規則はまだ固定せず、
Match層で確定する。

## python-studyからの移行

`python-study` に存在する麻雀コード・文書は単純コピーしない。
棚卸し時に各要素を次へ分類する。

1. `lisjong-engine`へ移す
2. `lisjong`側に属する
3. 学習履歴・参考資料として`python-study`に残す
4. 不要・廃止

さらに、完成済み、実装途中、設計のみ、test不足、staleな設計を区別する。
`lisjong-engine` では現在採用する設計だけを正本として整理する。

## 初期完成目標

v0.1の完成条件候補は、指定された`RuleSet`に従い、4人日本式リーチ麻雀の半荘を
合法手だけで開始から最終結果まで決定的に完走できることである。

強いAIを持つことはengineの完成条件に含めない。
