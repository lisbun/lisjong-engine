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
整数handleを持たない。actionの同一性は物理牌IDとaction種別だけで判別する。

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

### Seat-specific Observation boundary

外部caller、AI、UIへ局面を渡す際は、`MatchState` / `RoundState` の内部完全状態を
直接公開せず、意思決定を要求された席ごとのimmutableな `SeatObservation` へ射影する。

```text
MatchState + active RoundState + viewer seat
    -> build_seat_observation()
    -> SeatObservation
```

builderは `MatchPhase.ROUND_IN_PROGRESS` のactive roundがdecision phaseにあり、viewerが
そのdecisionを要求されている場合だけ成功するpure projectionである。`SeatObservation`は
**現在のplayer-safeなdecision snapshot**であり、そのsnapshotを解釈するために必要な
engine-owned public stateをconsumer側の履歴再構築へ委ねない。

> `SeatObservation` is a current player-safe decision snapshot.
> Engine-owned public state required to interpret that snapshot must not require
> consumer-side history reconstruction.

viewer自身の手牌に加えて、通常turnと`RIICHI_DISCARD`ではcurrent drawn tileを
physical identityのない`PublicTile | None`として返す。チー・ポン後のdrawless discardでは
`None`であり、discard・加槓・暗槓へのreaction observationには、宣言者側でdrawn tileを
保持していても公開しない。non-`None`のdrawn tileは赤牌区分を含むsemantic equalityで
必ずviewerの`hand_tiles`に含まれる。

全席の河では、各`PublicDiscard`が局全体で共有する0始まりのchronological `order`を持つ。
orderはseat内river indexではなく、calledされたdiscardも河に残ったまま同じ値を維持する。
`is_riichi_declaration`は立直成立可否ではなく、actual declaration discardとして打たれた
historical factを表すため、宣言牌適用直後のreaction windowから`True`になる。

成立済み副露の`PublicMeld.called_tile`はチー・ポン・大明槓のcalled tileを保持し、加槓では
added tileではなく元ポンのcalled tileとsource seatを維持する。暗槓の`from_seat`と
`called_tile`はともに`None`である。立直のcurrent stateは`PublicRiichiStatus.NONE` /
`PublicRiichiStatus.PENDING` / `PublicRiichiStatus.ESTABLISHED`の単一canonical valueで
表し、立直選択後の
`AWAITING_RIICHI_DISCARD`と宣言牌reaction未解決中を`PENDING`とする。

Observationのhidden information boundaryでは、次を公開しない。

- 他家concealed handとその枚数
- live wallの牌種・順序、dead wall内部、裏ドラ表示牌、未公開の槓ドラ表示牌
- physical tile ID / copy index、`Tile`等の内部physical object
- match seed、round seed、`RoundRandomProvenance`
- `MatchState` / `RoundState` / `PlayerState`等のmutable内部object

自手牌、drawn tile、副露内の牌は `TileType + is_red` というpublic meaningで決定的に
正規化するため、物理copyやhidden wall順、random provenanceだけが異なる同一公開局面は
同じObservationになる。discard orderと立直宣言牌flagはengine-owned internal event historyから
losslessに射影するが、そのhistoryやphysical tile identity自体はpublic contractへ公開しない。
projection元と河が不整合なら未知値へ丸めずfail closedにする。ドラ表示牌は
`RoundState.revealed_dora_indicators`だけを入力とし、遅延中の大明槓ドラを推測しない。

局中のplayer-visible scoreは、Matchのauthoritative scoreを変更せず次で導出する。

```text
visible score = MatchState.scores + active RoundState.riichi_payment_deltas
```

同様に、player-visibleな供託本数は、局開始前からcarryされたMatch authorityと今局の
成立済み供託factを合成する。

```text
visible riichi sticks
    = MatchState.position.riichi_sticks
    + len(active RoundState.riichi_contributions)
```

`SeatObservation`は見えている局面情報だけを担当し、`LegalActionSnapshot`とは別境界にする。
Observationへaction ID、action option、physical `LegalAction`を埋め込まない。G1はdriver、
selector、Player / Policy、action translationを持たず、既存pull APIも変更しない。

### Public action descriptorと決定的最小driver

外部callerが席ごとの意思決定を行いながら半荘を完走できるよう、G2では
`SeatObservation`と内部`LegalActionSnapshot`の間に、物理牌identityを持たない
immutableな`ActionDescriptor`境界を置く。

```text
MatchState + active RoundState
        ├─ build_seat_observation() -> SeatObservation
        └─ legal_actions()          -> LegalActionSnapshot（engine内部）
                                            ↓ public projection / collapse
                                  tuple[ActionDescriptor, ...]
                                            ↓
                             external seat-specific selector
                                            ↓ snapshot-local resolve
                                  canonical internal LegalAction
                                            ↓
                              RoundState.apply() / resolve_reactions()
                                            ↓
                                MatchState.settle_active_round()
                                            ↓
                                      CompletedMatch
```

立直だけは、1手番のなかで2つのselector decisionへ分かれる（Issue #36）。詳細は
「立直の2段階selector decision」を参照する。

driverはPolicyではなく、既存state machine APIを正しい順序で呼ぶorchestrationである。
AI、RandomPlayer、牌効率等の選択logicは所有せず、4席それぞれのselectorをcallerから
注入する。selectorへ渡すのは`SeatObservation`とpublic descriptorだけであり、raw
`LegalAction`、physical tile ID、`RoundState` / `MatchState`、seed、random provenance、
hidden wall情報は公開しない。

同じ公開意味になる複数の内部actionは1 descriptorへcollapseする。適用する内部actionは
physical tile IDを使う明示的なinternal keyで決定的に選ぶ一方、selectorへ提示するoption
tupleはaction kind、`PublicTile`、tsumogiri、source seat、consumed public tiles等の公開情報
だけを使う明示的なkeyでsortする。これにより、physical copyの割当だけが異なる同じ公開
局面では、selectorが受け取るoption tuple全体も等しくなる。descriptorから内部actionへの
解決はselector呼出前に取得した同じ`LegalActionSnapshot`のlocal mappingだけを使い、
selector後に合法手を再取得しない。stale / legal membershipの最終検証は既存core APIへ委譲する。

reaction windowでは、既存のreacting seat順に従いつつ、3席すべてのObservation、合法手
snapshot、public options、local mappingをcallback開始前に構築する。その後に全selectorを
呼び、全choiceを検証してから、shared revisionを指定した`resolve_reactions()`を1回だけ
呼ぶ。Passしかない席もcallback対象であり、途中のselector exceptionやinvalid choiceでは
driver自身はstateをmutationしない。Ron / Pon / Chi / Daiminkanのpriorityは既存resolverへ
完全に委譲する。

forced draw、嶺上draw、pending Ron finalization、局精算はそれぞれ既存`RoundState` /
`MatchState` APIを呼ぶだけとし、driverは合法手導出、reaction priority、得点、流局、精算、
連荘、終局条件、seed導出、Wall生成、Observation射影を再実装しない。validな
`AWAITING_ROUND` / `ROUND_IN_PROGRESS`からresumeでき、`FINISHED`では既存
`CompletedMatch`を返す。不整合な内部phaseを推測で補修しない。

G2の決定的最小driver完了を、現在の移行ロードマップにおける`lisjong-engine` v0.1の
到達点とする。

### Consumer向けordered progressとplayer-safe completion delivery

Human Play等の外部consumerが、前回decisionから次回decisionまでに成立した
objective public factを順序付きで受け取り、round / match完了時にはplayer-safeな
完了factを受け取れるよう、`run_hanchan()`へoptionalなdelivery境界を追加する
（Issue #34）。

```text
SeatObservation          = 今このdecisionで見えるcurrent state
ordered progress facts   = 前回snapshotから何が起きたか
```

snapshotの解釈に必要なcurrent public stateは`SeatObservation`自身が保持する。一方、ordered
progressはsnapshot間の出来事を通知する別責務であり、snapshotへ履歴を埋め込まず、consumerへ
current stateの再構築も要求しない。Issue #38のsnapshot補強は、ここで定義するprogress /
completion schemaやdelivery timingを変更しない。

**internal `RoundEvent`とplayer-facing progress projectionは別contractである。**
`round_event.py`の`RoundEvent` / `RoundEventSnapshot`はengine内部のaudit /
test / `RoundResult`構築用contractのままであり、player-facing public contractへ
昇格しない。`round_progress.py`が、局内で成立したfactのうち次のwhitelistだけを
`RoundProgressFact`（`DiscardProgress` / `MeldCalledProgress` /
`KanDeclaredProgress` / `KanConfirmedProgress` / `RiichiDeclaredProgress` /
`RiichiEstablishedProgress` / `RiichiFailedProgress` /
`DoraIndicatorRevealedProgress`）へ射影する。

```text
TileDiscardedEvent           -> DiscardProgress
MeldCalledEvent               -> MeldCalledProgress（チー・ポン・大明槓成立）
KanDeclaredEvent               -> KanDeclaredProgress（加槓・暗槓宣言）
KanConfirmedEvent（大明槓以外） -> KanConfirmedProgress（加槓・暗槓成立）
RiichiDeclaredEvent            -> RiichiDeclaredProgress
RiichiFinalizedEvent           -> RiichiEstablishedProgress / RiichiFailedProgress
DoraIndicatorRevealedEvent     -> DoraIndicatorRevealedProgress
```

成立済みチー・ポン・大明槓の通知sourceは`MeldCalledEvent`だけとし、
`ReactionsResolvedEvent`からは重複して生成しない。`ReactionsResolvedEvent`
自体は、各seatのron capable / selected / passed、鳴きのcandidate等の
hidden decision factを保持するため、一切progress factを生成しない。
`RoundStartedEvent` / `TilesDealtEvent`（他家配牌） / `TileDrawnEvent`
（他家ツモを含む） / `MissedRonRecordedEvent` / `RoundEndedEvent`も
同様にwhitelist対象外である。projectionは既存の`PublicTile` /
`PublicMeld`（`public_state.py`の`public_tile()` / `public_meld()`）を
再利用し、Observationと同じphysical-identity-freeなboundaryを維持する。

**raw internal object / result / provenanceをconsumerへ公開しない。**
`RoundEvent` / `RoundEventSnapshot` / `ReactionResolution` / `RoundResult` /
`CompletedRound` / `CompletedMatch` / `Tile` / `LegalAction` /
`RoundRandomProvenance` / seed / mutable `RoundState` / `MatchState` /
`PlayerState`は、delivery境界を経由してconsumerへ到達しない。round /
match completionも同様にwhitelist方式で構築する。`round_completion.py`の
`project_round_completion()` / `project_match_completion()`が、
`CompletedRound` / `CompletedMatch`から`RoundCompletionFact` /
`MatchCompletionFact`（和了 / 荒牌流局 / 途中流局の種別、winner席と
win method、source seat、席別point delta、精算後score、dealer
continuation、次局有無、`MatchEndReason`、最終score・順位）だけを構築する。
`CompletedRound.random_provenance`や`CompletedMatch.history`のような
内部監査専用fieldは対応する公開fieldを持たない。役・符・ドラの内訳等、
既存型の内部構造を無理にすべて再現する必要がない情報は、本Issueの
minimum scopeへ含めない。

**ordered progress deliveryのminimum boundary。**
`RoundState.revision`だけをevent cursorとして扱うと、1 transactionが
複数eventを追加した場合に欠落が起こり得るため、driver（`driver.py`）は
transaction前後の`RoundState.events`の長さから、そのtransactionが実際に
追加したevent sliceを欠落なく取得する。

```text
successful engine transaction
    -> 新しく追加されたinternal RoundEvent slice
    -> project_round_progress() でplayer-safe projection
    -> 空でなければ1つのordered batchとしてdelivery
    -> callback return
    -> 次のengine transition
```

progress、round completion、match completionはすべて同じ
`tuple[RoundProgressFact | RoundCompletionFact | MatchCompletionFact, ...]`
という1つのordered batch abstraction（`DeliveryItem` / `DeliveryCallback`、
`run_hanchan(..., on_delivery=...)`）で扱い、round用APIとmatch用APIを
分裂させない。

**round settlement後・next round開始前のcompletion boundary。**
`MatchState.settle_active_round()`が成功commitした直後、`start_round()`が
次局を開始するより前に、driverはround completion（terminalなら続けて
match completion）を同じbatchでdeliveryする。

```text
RoundPhase.FINISHED
    -> MatchState.settle_active_round()（成功commit）
    -> project_round_completion() [+ project_match_completion()]
    -> 1つのordered batchとしてdelivery
    -> callback return
    -> non-terminalなら次のstart_round()、terminalならCompletedMatchを返す
```

terminal局ではround completionとmatch completionを同じbatch・同じ呼び出しで
順序どおりにdeliveryし、別呼び出しに分けたり重複させたりしない。

**synchronous / fail-fast / no rollback / no automatic retry semantics。**
`on_delivery`はsynchronousである。成功commitしたengine transactionの後にだけ
呼ばれ、callbackがreturnするまでdriverは次のtransition（次局の
`start_round()`を含む）へ進まない。callbackが例外を送出した場合、
その例外はfail-fastでそのまま`run_hanchan()`の呼び出し元へ伝播し、
既に成功commitしたengine state（settlement、局進行）をrollbackしない。
自動retry、自動replay、durable queue、acknowledgement protocolは提供しない。
callback失敗後に同じ`run_hanchan()`呼び出しを安全にresumeできることは
保証しない。

**Human Play固有UI interactionはconsumer責務である。** Enter待ち、prompt、
menu番号、CLI文字列、GUI widget、KeyboardInterrupt等のfrontend固有
cancellation、Human seat assignmentはengine契約に含めない。`SeatObservation`
と`ActionDescriptor`にはprogress historyを混入させず、snapshot / choice
contractとprogress / completion deliveryを別関心のまま維持する。

**generic event / replay schemaを今回固定していない。** 本境界はconcrete
Human Play requirementから導いた最小差分であり、generic `GameEvent` /
`GameRecord` / observer framework / pub-sub / JSON event schema / replay
formatを新設しない。将来複数consumerが必要とする場合も、この最小boundaryを
起点に再検討する。

### Ordered player-safe round evidence

HandBelief等の将来consumerが「そのviewerに何が合法的に観測可能だったか」を
順序付きで受け取れるよう、engine内部の完全state / event historyからviewerごとの
ordered player-safe evidenceをpureに射影する（Issue #42）。

```text
complete engine state / internal events
    -> engine-owned pure player-safe projection
    -> ordered player-safe round evidence
```

`SeatObservation`はcurrent decision snapshot、`RoundProgressFact`は前回decisionからの
差分delivery、`round_evidence.py`は局内の順序付きevidence historyであり、責務が異なる。
`RoundEvent` / `RoundEventSnapshot`は引き続きengine内部のomniscient recordであり、
consumer-facing contractへ昇格しない。`round_evidence.py`が、そこからwhitelistした
evidenceだけを構築する。

**player-safeはpublic-onlyと同義ではない。**

```text
player-safe evidence
├─ globally public evidence / context
└─ viewer-private legitimate observation（viewer自身のツモ牌）
```

`DrawEvidence.tile`はviewer自身のツモのときだけ値を持ち、他家のツモでは常に`None`に
なる。ツモが起きたこと自体と`DrawSource`（live wall / 嶺上）はpublicである。

**structural response epochをruntime reaction activationから導出しない。**
current engineは打牌後に`has_possible_reaction()`で他家のhidden handを見てから
`AWAITING_REACTIONS`へ入るか決め、暗槓も`kokushi_ankan_chankan_enabled`と実際の
国士無双候補の有無でreaction windowを開くかどうかが変わる。したがって
**reaction windowが開いたというruntime factそのものがhidden capabilityを漏らし得る**。

player-safe evidenceのresponse epochはこの分岐を入力にせず、次だけから構成する。

```text
public triggering action + RuleSet + seat topology
    -> ResponseEpochOpenedEvidence / responder topology
```

```text
打牌   publicに打牌が起きた時点で必ずstructural epochを開く
加槓   public kakan declarationで必ずstructural chankan epochを開く
暗槓   kokushi_ankan_chankan_enabledだけで開閉を決める
```

responder topologyはいずれもsource seat以外の3席であり、`reaction_seat_order()`という
seat topologyだけで決まる。「その席が合法な反応を持っていた」ことは意味しない。

epochのoutcome（`ResponseOutcome`）は、実際にpublicへ現れた進行（鳴き成立、和了、
次の進行）だけから決める。epochの解決がまだpublicに現れていない間は
`ResponseEpochClosedEvidence`を出さず、その解決を前提とする槓ドラ公開・立直成立も
fail closedで保留する。これにより、hidden candidateの有無でruntimeのreaction window
が開いた場合と開かなかった場合とで、同じ公開進行に対して同じevidenceになる。

```text
kan宣言 -> structural response epoch -> response / no public response
    -> kan confirmation -> 嶺上ツモ -> 槓ドラ公開
riichi宣言牌の打牌 -> RiichiDeclaredEvidence -> structural response epoch
    -> response / no public response -> RiichiEstablishedEvidence / RiichiFailedEvidence
```

打牌と鳴きのcalled-by関係は、過去のevidenceを書き換えず
`MeldCalledEvidence.called_discard_order`で保持する。`DiscardEvidence.order`は
`PublicDiscard.order`と同じ、局全体で0始まりのchronological identityである。
`is_riichi_declaration`も同じく、成立可否ではなく宣言牌として打たれたhistorical factを表す。

**hidden情報はfail closedで落とす。** 他家concealed hand、他家のツモ牌、live / dead wallの
tile truth、`ron_capable_seats` / `ron_passed_seats`、pon / chi capable等のactual per-player
legal opportunity、hidden-dependent pass、フリテン、ron legality、
`MissedRonRecordedEvent`、`ReactionResolution`自体、physical tile identityはevidenceへ
含めない。`TilesDealtEvent`（全席の配牌）も対象外である。九種九牌のように
eligibilityがhidden handへ依存するterminalでも、実際に宣言されて終局したことと
その理由だけをpublicとして扱う。

consumerがomniscientな`RoundState.events`へ直接触れずに済むよう、engine側の唯一の
入口を`round_evidence_builder.py`の`build_round_evidence(round_state, viewer_seat)`とする。
`build_seat_observation()`と違いdecision phaseを要求しない。evidenceは意思決定snapshot
ではなく、局のどの時点でも参照できる観測履歴だからである。

HandBelief / ML / dataset feature semanticsはengineへ持ち込まない。どのevidenceをどう
HandBelief featureへ解釈するかは`lisjong`の責務であり、この境界は
`lisjong` / `lisjong-arena`への依存を導入しない。

### 合法手導出と反応境界

合法手の導出は状態mutationから分離したpure moduleに置き、`RoundState` 側は
薄いfacadeとする。

反応windowでは現在stateから各seatの合法手を再導出し、callerが渡したchoiceを再検証する。
反応のpriority解決自体もpureなresolverへ分離し、mappingのiteration順に結果を依存させない。

鳴き後の打牌はdrawを伴わないため、pending discardのprovenanceである
`pending_discard_source` はoptionalである。`LIVE_WALL` / `RINSHAN` はdraw由来の打牌を表し、
`None` はChi / Pon後等のツモなし打牌を表す。provenanceが無いことを理由にreaction windowを
失わない。

### 立直の2段階selector decision

立直は「立直を宣言すること」と「どの牌を宣言牌として打つか」という、2つの独立した
selector decisionである（Issue #36）。

**Riichi selection and declaration discard are separate selector decisions.**

**The engine never chooses a declaration discard on behalf of an external selector.**

```text
AWAITING_DISCARD
    ├─ DiscardLegalAction(tile_id)
    ├─ AnkanLegalAction / KakanLegalAction
    ├─ TsumoLegalAction / NineTerminalsLegalAction
    └─ RiichiLegalAction()
            ↓ selected
AWAITING_RIICHI_DISCARD
    └─ DiscardLegalAction(tile_id)  立直宣言可能な打牌だけ
            ↓ selected
discard + RiichiDeclaration
            ↓
reaction / riichi finalization
```

`RiichiLegalAction`（public boundaryでは`RiichiActionDescriptor`）は宣言牌を持たない。
通常turnでは、立直宣言できる打牌が1件以上存在するときだけ、宣言牌候補の数に関わらず
ちょうど1件提示する。`DiscardLegalAction`はriichi declarationと結合せず、打牌そのもの
だけを表す。

`AWAITING_RIICHI_DISCARD`中は、current seatを立直を選んだ席のまま保持し、手牌・河・
drawn tile metadataを変更しない。他席はactionを持たず、current seatへ提示するのは
`derive_riichi_discard_tiles()`が返す宣言牌の打牌だけである。通常の非立直打牌・槓・
ツモ・九種九牌・再度の立直は混在させない。立直可能牌の判定は通常turnと同じ関数を
唯一のsource of truthとして再利用する。

`RiichiLegalAction`の適用は1つの成功したengine transactionであり、revisionを1だけ
進める。したがって通常turnで取得した`LegalActionSnapshot` / `ActionProjection`は
follow-up decisionではstaleであり、宣言牌は新しいrevisionのfresh snapshot / fresh
`ActionProjection`から選ぶ。

`RiichiDeclaration`は従来どおり「宣言牌を打った時点で確定する事実」である。したがって
最初の`RiichiLegalAction`選択時には`RiichiDeclaration` / `RiichiDeclaredEvent` /
`RiichiDeclaredProgress`を生成せず、供託も作らず、playerをriichi established扱いに
しない。selector stagingのためだけのsynthetic progress factも追加しない。宣言牌が
確定した時点で、既存のdeclaration → reaction → finalization pathへ接続する。

follow-up decisionは`ObservationDecisionKind.RIICHI_DISCARD`として通常turnと区別する。
consumerが候補集合やsnapshot差分から推測する必要はない。`ActionSelector` signature自体は
変えず、同じseatのselectorが連続して2回呼ばれることを正規のcontractとする。宣言牌候補が
1件しかない場合もdriverは自動選択せず、必ずselectorを呼ぶ。

この分離は`lisjong-engine`自身のselector-facing execution semanticであり、`lisjong` /
`lisjong-arena`へのdependencyを導入するものではない。立直可能条件、宣言牌へのRon /
Chi / Pon / Daiminkanの既存成立semantics、`RiichiContribution`、visible score / riichi
sticksへの反映timing、double riichi、一発、riichi failure、reaction priorityは変更しない。

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

これらはIssue #24でF2として実装済みである。詳細は本書「MatchState（F2）」
を参照。

## MatchState（F2）

`match_state.py` の `MatchState` は、複数の `RoundState` を1つの半荘として
束ね、指定match seedと（呼び出し側が選んだ合法action列の結果である）
`RoundResult`から、東1局開始から半荘終了・最終score確定までを決定的に
進行するstate machineである（Issue #24）。F1（局精算・最終score計算）の
pure calculationを再実装せず、それらを正しい順序で呼び出すorchestration
層に徹する。

### 所有するauthoritative state

`MatchState` が所有するauthoritative factは次のとおり。

- `RuleSet`
- 4席のraw score（`SeatPoints`）
- 現在（または半荘終了時点で最後に実際に開始された）`RoundPosition`
- `MatchPhase`（`AWAITING_ROUND` / `ROUND_IN_PROGRESS` / `FINISHED`）
- 進行中の `RoundState | None`
- 完了した局の履歴 `tuple[CompletedRound, ...]`
- deterministic round allocationに必要な内部state
  （match seed、成功裏に開始した局数）
- 半荘終了後の `CompletedMatch | None`

`MatchState.scores` が対局中のraw scoreのauthorityである。`RoundState`へは
局開始時に、その時点の `scores` のimmutable snapshotを
`round_start_points` として渡すだけであり、局中の立直等でMatchStateを
逐次mutationしない（本書「Matchとの点数境界」参照）。

### 局開始: `start_round()`

`MatchPhase.AWAITING_ROUND`のときだけ成功する。

```text
round ordinal = 成功裏に開始した局数 + 1
    -> create_round_random_provenance(match_seed, round_ordinal)
    -> create_round_wall(provenance)
    -> RoundState構築（round_start_points = 現在のscores snapshot）
    -> RoundState.deal()
    -> 成功後だけauthoritative stateへcommit
```

Wall生成・`RoundState`構築・`deal()`はすべてlocal candidateとして行い、
すべて成功した場合だけ`active_round` / `active_round`のprovenance /
成功裏に開始した局数 / `phase`をまとめてcommitする。途中で失敗した場合、
`MatchState`は一切mutationされず、次に`start_round()`を呼んだときの
round ordinalも進まない。callerはWall生成や`RoundState.deal()`を自分で
呼ばず、常に配牌済み（`AWAITING_DRAW`）の`RoundState`を受け取る。

### 局終了: `settle_active_round()`

public settlement入口はこの1メソッドへ集約する。`finish()`のような別の
終了APIは存在しない。`MatchPhase.ROUND_IN_PROGRESS`かつ、active round
が`RoundPhase.FINISHED`で`result`を確定しているときだけ成功する。

```text
active RoundStateのcontext / provenance validation
    -> calculate_round_settlement(...)   # F1
    -> scores_after_settlement = scores.add(settlement.point_deltas)
    -> dealer_continues = _dealer_continues(result, dealer_seat)
    -> end_reason = _match_end_reason(position, result, scores_after_settlement,
                                       dealer_continues, rules)
```

ここまでは`self`を一切mutationしない。`end_reason`の有無でnon-terminalと
terminalの2つのpathへ分岐する。

**non-terminal**（`end_reason is None`）: `_next_round_position()`で次局
positionを計算し、`CompletedRound(next_position=...)`を構築してから、
`scores` / `position` / `history` / `active_round` / provenance / `phase`
（`AWAITING_ROUND`へ）をまとめてcommitする。

**terminal**（`end_reason is not None`）: `_next_round_position()`を一切
呼ばない。西4終了後の仮想North1のような、実際には開始されない次局
positionを生成しないためである。代わりに次の順序でfinalizationを行う。

```text
1. RoundSettlementの適用は既に済んでいる（scores_after_settlement）
2. end_reasonがBANKRUPTCYの場合だけ、_bankrupt_seats()で破産席を
   抽出し、calculate_bankruptcy_points_from_transfers()（F1）で
   その局のSettlementTransferから飛び賞recipientを導出する
3. calculate_final_riichi_stick_awards()（F1）で残存供託を
   scores_after_settlementベースの最終1位席群へ配分する
4. 配分結果をscores_after_settlementへ加算し、final_raw_scoresとする
5. calculate_final_scores(final_raw_scores, rules, bankruptcy_points)
   （F1）で最終score（粗点・ウマ・オカ・順位点・bankruptcy調整）を確定する
6. CompletedRound(next_position=None) / CompletedMatchを構築する
7. すべて成功した場合だけ、scores / history / active_round / provenance /
   completed_match / phase（FINISHEDへ）をまとめてcommitする
```

bankruptcyのrecipientをMatchState側で推測すること（winner・top席・dealer
等へのfallback）は禁止する。F1が監査可能な`SettlementTransfer`から
recipientを導出できない場合はfail closedとし、その場合`MatchState`は
一切mutationしない（終了済みのactive roundはattachedのまま残る）。

### `scores_after_settlement` と `final_raw_scores` の違い

`CompletedRound.scores_after_settlement`は、F1 `RoundSettlement`適用直後・
Match終端のfinal riichi award適用前のraw scoreである。terminal時に残存
供託を最終配分しても、この値は書き換えない。一方
`CompletedMatch.final_raw_scores`はfinal riichi award適用後のraw score
であり、terminal commit後の`MatchState.scores`はこの値と一致する。

同様に、final riichi awardは最後の`RoundSettlement`（`settlement`
field）へ混ぜない。`RoundSettlement.riichi_stick_awards`は局内winnerへの
供託授与だけを表し、match終了時の残存供託配分は
`CompletedMatch.final_riichi_stick_awards`という別のMatch終端factとして
保持する。bankruptcy adjustmentも同様に、final raw scoresへ直接加算せず、
`FinalScoreCalculation`側のadjustmentとしてのみ反映する。

### terminal時の `MatchState.position`

terminalになっても`MatchState.position`は上書きしない。半荘終了時点の
`position`は、最後に実際に`start_round()`で開始された局の位置のままで
ある（例: 西4で終了した場合は西4のまま、南4の親流れで終了した場合は
南4のまま）。半荘の最終結果の正本は常に`MatchState.completed_match`
である。

### match end判定の意味

`_match_end_reason()`の判定順序と各`MatchEndReason`の意味は次のとおり。

```text
1. BANKRUPTCY   : score < rules.bankruptcy_threshold（<=ではない）。
                  局位置に関係なく最優先。
2. FINAL_ROUND  : 西4は親継続の有無・dealer stop条件に関わらず必ず最大局。
3. DEALER_WIN /
   DEALER_TENPAI: 南4・西1〜3で、親が起家順tie-break込み1位かつ
                  first_place_target_points以上で継続する場合の停止条件
                  （それぞれdealer_win_end_enabled /
                    dealer_tenpai_end_enabledに従う）。
4. TARGET_REACHED: 南4・西1〜3で親が流れ、誰かがfirst_place_target_points
                   以上に達した場合。
5. 南4で親が流れ誰も未達なら、west_round_enabledに応じてNone（西入）
   またはFINAL_ROUND。
6. 西1〜3で親が流れ誰も未達ならNone（次のWest handへ進む）。
```

`rules.return_points`（最終score / オカ計算専用の値）はmatch終了判定へ
一切使用しない。使用するのは常に`rules.first_place_target_points`である。
この2つのfieldは意味も用途も異なる別概念であり、値がたまたま一致する
presetがあっても、match進行判定は`first_place_target_points`だけを
参照する。

## Determinism

engineのテスト・回帰確認・AI評価へ利用できるよう、同じversion、`RuleSet`、seed、入力系列から
同じ状態遷移と結果を再現できる設計を重視する。

乱数の利用箇所はengine内部で管理し、暗黙のglobal random stateへ依存しない。

初期seed境界は次のとおり確定している（Issue #5）。

```text
seed: int -> RandomSource -> shuffled Wall
```

`RandomSource` はseedから決定的に生成されるengine-ownedな乱数sourceであり、
`Wall`自身はseed管理責務を持たない。

match seedから各局のround seedを導出する規則は、`round_allocation.py`
（Issue #24第1段階）で確定している。

```text
match seed + 1-based round ordinal
    -> SHA-256 domain-separated derivation
    -> round seed
    -> RandomSource(round_seed)
    -> create_shuffled_wall(...)
    -> Wall
```

`derive_round_seed(match_seed, round_ordinal)` は、Pythonの
`hash()`（process間で不安定）へ依存せず、stdlibの`hashlib.sha256`だけを
使ったpureな導出である。同じ`match_seed` + 同じ`round_ordinal`からは常に
同じround seedを得る。連荘で場・局・本場が同じ`RoundPosition`が続いても、
ordinalが増えれば別のround seed・別のWallになる。

`round_ordinal`は「何局目として実際に開始されたか」を表すfactであり、その
保持・incrementはMatchState（F2）の責務である。本moduleはmutableな
allocation stateを持たず、次のordinalを自動的に決めるglobal counter等も
持たない。`RoundRandomProvenance`は`match_seed` / `round_ordinal` /
`round_seed`をimmutableに保持し、replay / artifactでの監査に使う。

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
