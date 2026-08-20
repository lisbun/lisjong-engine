# lisjong-engine roadmap

`lisjong-engine` は、日本リーチ麻雀の rule / state / game execution を担当する独立した game engine です。

この文書は、v0.1 相当の基礎 engine が成立した現在地点から、game engine をどの方向へ成熟させるかを整理します。現在実装済みの具体的な contract は [`architecture.md`](architecture.md) を正本とし、この文書では長期的な発展方向を扱います。

lisjong ecosystem 全体の repository 責務、依存方向、OSS 活用、Visualization / Analysis、Human Play、Learning Policy 等の横断原則は [`lisjong-project`](https://github.com/lisbun/lisjong-project) を正本とします。

## Current foundation

旧移行ロードマップ上の v0.1 到達条件である deterministic minimal hanchan driver まで接続され、概ね次の foundation が成立しています。

```text
RuleSet / domain / scoring / settlement
        ↓
deterministic Round / Match execution
        ↓
SeatObservation + public action descriptors
        ↓
external seat selectors
        ↓
deterministic hanchan driver
        ↓
CompletedMatch
```

これは正式な release version や「すべての correctness 検証が完了した」ことを意味しません。以降の roadmap は、この v0.1 相当の基礎を出発点として、correctness、validation、recordability、interoperability、performance、consumer readiness を継続的に成熟させるものです。

roadmap は厳密な直列 Phase ではなく、次の Track を必要に応じて並行・反復して進めます。

```text
Current v0.1 foundation
        │
        ├─ Core Execution Hardening
        ├─ Stable Contracts
        ├─ Validation
        ├─ Recordability Support
        ├─ Consumer / Interoperability Readiness
        ├─ Performance
        └─ RuleSet Evolution
```

## Core Execution Hardening

Core Execution は新規にゼロから構築する対象ではありません。現在の rule-correct / deterministic execution を維持しながら、rule / state semantics、fail-closed behavior、transactional transition、error diagnosability 等を継続的に hardening します。

AI / Policy decision logic は引き続き engine の責務に含めません。consumer convenience のために core state model や rule semantics を歪めることも避けます。

## Stable Contracts

外部 consumer が engine 内部 implementation detail へ依存せず利用できる stable boundary を継続的に育てます。

現在の foundation には `RuleSet`、Round / Match state、result / settlement、`SeatObservation`、public action descriptor、deterministic driver、random provenance 等が存在します。具体 API と現行 contract は `docs/architecture.md` を正本とします。

新しい contract は、想像上の将来 consumer から先回りして作るのではなく、具体的な use case で不足が確認された最小単位で追加します。

```text
concrete use case
      ↓
missing requirement
      ↓
minimum engine contract
```

`lisjong`、`lisjong-arena`、viewer、CLI / GUI、MJAI 等の固有型を engine core model へそのまま逆流させません。

## Validation

Validation は post-v0.1 の主要な継続 Track です。Core Execution Hardening が rule / state semantics 自体を改善する責務であるのに対し、Validation は correctness を確認する evidence と手段を強化します。

```text
Validation
├─ example / regression tests
├─ invariants / property-oriented validation
├─ differential validation
└─ external conformance cases
```

候補には、tile / score conservation、legal-action consistency、turn ownership、meld consistency、terminal-state consistency、settlement consistency、deterministic progression 等があります。特定の property-based testing framework はここでは固定しません。

Differential validation では、意味的に独立した implementation を reference として利用できます。ただし、

```text
implementation agreement != correctness proof
```

とします。同一 backend の thin wrapper を独立 reference として数えず、差異があれば implementation bug、RuleSet difference、configuration difference、unsupported case、semantic mismatch 等を調査します。majority vote を oracle として扱いません。

## Recordability Support

engine が所有するのは「GameRecord そのもの」ではなく、**record を構成できる objective execution facts を安全に提供できる能力**です。

現在すでに event / result / settlement / completed history / random provenance 等の客観的 fact が存在します。ただし、それらすべてを外部 consumer 向けの stable record API とみなしません。まず既存 fact を棚卸しし、具体的な record / replay / analysis consumer PoC で再利用可能な情報と不足情報を確認します。

```text
existing engine facts
        ↓
concrete record / replay / analysis PoC
        ↓
missing informationを確認
        ↓
minimum record-supporting contract
```

巨大な canonical `GameEvent` / `GameRecord` schema、JSON / JSONL、database、viewer、dataset pipeline 等を先行設計しません。

### Deterministic re-execution と historical record

次は別能力です。

```text
same initial conditions + same actions
        ↓
deterministic re-execution
```

```text
saved historical evidence
        ↓
historical replay / analysis
```

Deterministic re-execution は historical evidence の代替ではありません。将来 engine version や RuleSet semantics が変化した場合にも、「当時実際に起きたこと」と「現在の engine で同じ入力を再実行した結果」を混同しません。

### Player-facing information と privileged ground truth

`SeatObservation` は player / Policy が合法的に知り得る情報の boundary です。研究・validation 用途で hidden hands、wall / dead-wall、random provenance 等が必要になっても `SeatObservation` へ混ぜません。

```text
SeatObservation
    !=
purpose-specific privileged immutable projection
    !=
engine internal mutable state
```

privileged information が必要な場合も、mutable な `RoundState` / `MatchState` をそのまま外部公開することを既定方針としません。visibility / persistence contract は concrete use case から設計します。

AI 固有の HandBelief、danger / value、candidate reasoning 等は `lisjong` の責務です。`lisjong-arena` 固有の evaluation metrics / provenance も game-engine facts とは分離します。

## Consumer / Interoperability Readiness

`lisjong-engine` 自身へ各 consumer implementation を取り込むのではなく、stable boundary から自然に利用できる状態を目指します。

想定 consumer には `lisjong`、`lisjong-arena`、CLI、GUI、viewer / replay tooling、human-play frontend、external adapters 等があります。ただし roadmap は次 Issue の固定順序を規定しません。

MJAI、RiichiEnv 等は engine core contract ではなく external adapter / PoC 候補として扱います。

```text
lisjong-engine
      ↓
stable engine boundary
      ↓
external adapter / consumer PoC
      ↓
external ecosystem
```

PoC では information loss、RuleSet / semantic differences、replay fidelity、external tooling compatibility 等を確認し、engine 側の不足が実証された場合だけ minimum contract 追加を検討します。特定 OSS / protocol を mandatory dependency や canonical representation として固定しません。

recorder / viewer / telemetry / adapter 等の failure によって engine state へ partial mutation や corruption を生じさせないことを重要な原則とします。ただし consumer failure 時に execution を継続するか abort するかは、具体的な integration contract で決定します。

## Performance

性能は重要ですが、correctness より先に大規模最適化しません。

```text
Correctness
    ↓
Baseline measurement
    ↓
Actual bottleneck identification
    ↓
Targeted optimization
```

測定候補には actions / steps per second、rounds per second、games per second、legal-action generation、state transition、scoring、observation construction、将来の recordability overhead 等があります。

Rust 化、native backend、backend replacement 等は実測前に roadmap へ固定しません。外部 engine より遅いこと自体ではなく、lisjong ecosystem の具体的用途に対して十分かどうかを判断します。

## RuleSet Evolution

RuleSet の追加・拡張は継続可能としますが、rule variation を増やすこと自体を目的にしません。

```text
concrete ecosystem requirement
        ↓
missing / different rule semantics
        ↓
RuleSet extension / preset
        ↓
validation
```

external platform、Arena、Human Play 等の concrete requirement から必要性が確認されたものを優先します。既存 mechanics を未実装 feature として再掲せず、未確認の external service rule を推測で追加しません。

## Human Play readiness

Human Play 自体は engine の責務ではありません。ただし現在の `SeatObservation + public action options + external selector` boundary は、人間の入力主体にも応用可能です。

将来 CLI / GUI frontend が、

```text
observable state
    ↓
legal public actions
    ↓
human chooses
    ↓
engine applies
```

という自然な interaction を構築できることを Consumer Readiness の一部として考慮します。UI、input handling、network session、authentication 等は engine の責務にしません。

## Now / Next / Later

これらは優先方向であり、固定された Issue 順序ではありません。

### Now

- current contract / docs の整合
- correctness hardening
- regression / invariant validation 強化
- external validation 候補の検討
- performance baseline measurement
- concrete consumer usage から不足 boundary を発見

### Next

- record / replay / analysis consumer PoC
- external adapter / interoperability PoC
- privileged ground-truth evaluation use case
- concrete consumer integration PoC（必要に応じて `lisjong` / `lisjong-arena` を含む）
- PoC から判明した minimum contract 追加

これらすべてを同時に実施することや、次 Issue の順序を固定することは要求しません。

### Later

- targeted performance optimization
- mature record / replay ecosystem support
- broader consumer readiness
- use-case driven RuleSet expansion
- external ecosystem integration の拡張

## Source-of-truth boundary

project-wide の以下の原則は `lisjong-project` を正本とし、この roadmap では再定義しません。

- repository 間 responsibility
- OSS / external ecosystem の一般的活用方針
- correctness → validation → measurement → optimization
- concrete requirements より先に canonical event schema を設計しない原則
- Visualization / Analysis Track 全体
- Human Play 全体の ecosystem architecture
- Learning Policy
- project-wide evaluation hierarchy

`lisjong-engine` の roadmap は、それらを game-engine 責務として具体化することに集中します。

## Non-goals

この roadmap 自体は次を設計・実装するものではありません。

- game engine implementation / public API 変更
- RuleSet 追加
- GameRecord / canonical GameEvent schema 新設
- privileged ground-truth schema 設計
- persistence / JSON / JSONL format 設計
- event bus / observer API 設計
- MJAI / RiichiEnv / `lisjong` / `lisjong-arena` integration 実装
- differential test / property-based testing framework 導入
- training dataset 生成
- viewer / replay UI / CLI / GUI / Human Play 実装
- network / session 実装
- performance optimization / Rust / native backend 導入
- external OSS dependency 追加

これらは concrete need が確認されたものから個別 Issue として扱います。

## Guiding loop

v0.1 相当の基礎完成後は、次の loop で engine を成熟させます。

```text
correct execution
      ↓
validation / hardening
      ↓
concrete consumer usage
      ↓
missing requirements発見
      ↓
minimum contract extension
      ↓
measurement / further validation
```

`lisjong-engine` は、将来必要そうなものをすべて先回りして実装する repository ではありません。game-engine 固有の rule correctness と stable contract を所有し、具体的 consumer requirements に応じて必要最小限の能力を育てる基盤として発展させます。
