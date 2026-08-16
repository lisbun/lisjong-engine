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

```text
snapshot = state.legal_actions(seat)
chosen = snapshot.actions[0]
state.apply(seat, chosen, expected_revision=snapshot.revision)
```

engine自身はactionを選択しない。`apply()` はcallerの「さきほど合法だった」という
主張を信用せず、必ず現在の状態から合法手を再導出して照合する。

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

### mutation boundary

`RoundState` はmutableだが、状態を進める操作はtransactionalとする。
validationまたは遷移が失敗した場合、本体へpartial mutationを残さない。

```text
seat / phase / revision validation
    -> 現在stateから合法手を再導出
    -> action membership validation
    -> working copyへ遷移
    -> invariant validation
    -> 成功時のみcommit
```

外部へ公開する状態はtuple等のimmutable viewに限り、`Hand` / `River` / `Wall` を
直接渡さない。core APIを迂回した状態書き換えを構造的に防ぐためである。

物理牌の不変条件は「どのobjectを通しても1回しか現れない」ではなく、
**ownership上の重複・消失がない**ことと定義する。河の捨て牌と鳴きmeldが同じ
物理牌を参照する局面でも破綻しない定義を維持するためである。

### 合法手導出と反応境界

合法手の導出は状態mutationから分離したpure moduleに置き、`RoundState` 側は
薄いfacadeとする。

反応（チー・ポン・槓・ロン）の解決を実装していない段階でも、反応が起こり得る
局面を無視して次turnへ進めない。存在検知はfail-safeな過大評価とし、
false positiveで停止することは許容し、false negativeで反応を飛ばさない。

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
