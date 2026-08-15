# Architecture

## 目的

`lisjong-engine` は、日本式リーチ麻雀を正しく進行するための独立したゲームエンジンである。
AI戦略や外部実行環境との通信を担当せず、麻雀ルールと状態遷移の正しさを責務とする。

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
