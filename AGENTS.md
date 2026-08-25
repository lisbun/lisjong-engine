# AGENTS.md

## 適用範囲

このファイルはrepository全体へ適用する恒常的な作業規則である。
Issueまたはユーザーの明示的な指示が本書と異なる場合は、その指示を優先する。

以下の作業分担は現時点のdefault responsibilityであり、恒久的なtool制約や禁止ではない。
利用可能なtool、credit、作業内容、学習目的に応じて担当や作業場所を変更できる。
一方、本書でmandatoryとする安全境界と承認境界は維持する。

## Repositoryの責務

`lisjong-engine` は、日本式リーチ麻雀のルール判定・状態管理・対局進行を担当する。
AI戦略、Policy、RiichiEnv、RiichiLab、mjai通信、online通信、認証、学習・推論には依存しない。

責務判断では「その機能がなくても麻雀ゲームを正しく進行できるか」を基準とする。
なくても進行できる評価・戦略機能は原則としてengineへ持ち込まない。

## デフォルトの作業分担

- Git変更を伴わない方針・設計相談、Issue整理、実装方針・PR・実測結果のレビュー、
  GitHubへ記録する内容の作成は、通常のChatGPT conversationをdefaultとする
- source code、test、refactor、実装と不可分な小規模文書、品質確認、Git作業は、
  現時点ではClaude Codeをdefaultの変更担当とする
- `AGENTS.md`、README、設計・調査文書、文書間整合やstale documentationの整理は、
  現時点ではChatGPT WORKをdefaultの変更担当とする
- 上記は専属担当を定めない。必要に応じてAI間で担当を入れ替えられる

## 開発フロー

### Issue、branch、Pull Request

- GitHub Issueを作業の目的、scope、完了条件の正本とする
- `main`へ直接pushせず、実際にGit上の変更を担当する作業主体が対応Issueの主作業branchを作成する
- 原則として1 Issueにつき1つの主作業branchを使い、概ね1つのPull Requestで完結させる
- 1つのPull Requestでは1つの主目的を扱い、無関係な変更を混ぜない
- Git変更担当AIは、必要なIssue作成、branch作成、ファイル変更、品質確認、commit、push、
  Pull Request作成、Issueとの関連付け、Ready for review化までを追加承認なしで進めてよい
- PRのmergeでIssue全体が完了する場合は`Closes #123`等を使用し、途中PRでは`Refs #123`等を使う

### mergeと完了後cleanup

- Pull Requestのmergeにはユーザーの明示的な承認を必要とする
- ユーザーがmergeを承認した時点で、そのmergeに伴う定型cleanupも承認済みとみなす
- merge後は完了条件と不要branchのcleanupを確認する

### repository settingsとその他の承認境界

- repository settings変更には個別のユーザー承認を必要とする
- visibility、branch protection、Actions・security・permission、secret、外部公開、課金に影響する操作は、対象と影響を示して承認を得る
- 破壊的操作、外部公開、課金、認証情報の使用も同様に個別承認を必要とする

## AI code review

- AI reviewはcurrent Issueのscope / acceptance criteria、existing contract、repository architectureに対する
  correctness確認を主目的とする。review中に新しい機能要求を暗黙に追加しない
- correctness defect、regression、existing contract violation、architecture / dependency boundary violation、
  concrete changed behaviorに必要なtest不足を優先して確認する
- current Issueとexisting contractを完全に満たす最小の変更を優先する。concrete requirementがない
  future extensibility、hypothetical consumer、additional abstraction、schema expansion、persistence、
  extra defensive layer、unrelated cleanup / refactor、toolingで判定済みのstyle preferenceはblockingにしない
- findingは`blocking`と`non-blocking`を区別する。blockingはcurrent Issueのcorrectness / contract /
  architecture / regressionに影響する事項とし、optional improvementやfuture workをreview通過の必須変更へ
  昇格させない。scope外で価値がある事項は必要ならfollow-up Issue候補へ分離する
- format、lint、unit / integration tests、`git diff --check`等のdeterministic checkはtool / CIを正本とする。
  LLM reviewは同じmechanical findingの再探索より、testの意味やcoverageを含むsemantic / architecture /
  correctness reviewへ集中する
- 標準的にはimplementation self-review、CI / automated checks、one broad semantic / architecture reviewを
  基本形とする。同じPR headへ理由なく複数AIのopen-ended broad reviewを重ねない。review修正後は変更箇所、
  既知findingの解消、その変更から生じるregressionを中心にfocused re-reviewする
- blockingな問題が解消しacceptance criteriaを満たした時点でreviewを終了する。追加commentを作るためだけに
  改善点探索を続けず、`blockingなし / merge可能`を正常なreview結果として扱う
- public API / stable contract、cross-repository ownership migration、data loss / destructive behavior、security /
  information-flow boundary、high-impact persistence / migration等のhigh-risk changeでは追加・independent reviewを
  合理的に利用できる。review回数そのものは品質指標にしない
- `lisjong-engine`では特にgame rule / state transition correctness、legal action contract、deterministic execution、
  AI / external integration dependencyの逆流防止をsemantic reviewの重点とする

## 実装規則

- 通常版CPython 3.14を初期基準とし、free-threaded build（3.14t）は互換性を個別に検証するまで対象外とする
- 初期runtime dependenciesは空とし、外部library追加時は必要性、license、version、保守状況を確認する
- RiichiEnv、RiichiLab、`lisjong`、AI実装へ依存しない
- `RuleSet`により麻雀ルール機構と個別ルール設定を分離する方向を維持する
- deterministicなgame実行と再現可能なseed管理を重視する
- 未確認の外部サービス固有ルールを推測で実装しない
- Rust等の高速化はprofilingで必要性が確認され、Issueで合意されるまで導入しない

## テストと品質確認

変更内容に応じて、Pull Request前に次を実行する。

```text
python -m ruff format --check .
python -m ruff check .
python -m unittest discover -s tests -v
```

- 文書だけの変更では最低限`git diff --check`を実行する
- testは正常系だけでなく、合法手境界、状態遷移、異常入力、determinismを優先して固定する
- 実行できなかった確認は、理由と影響をPull RequestまたはIssueへ記録する
- code変更により利用方法、設計、制約が変わる場合は関連文書も更新する

## 秘密情報と外部成果物

次をrepositoryへcommitしない。

- `.env`、token、API key、credential
- 外部model weightおよび生成model
- 利用条件を確認していない牌譜・raw data
- 実験artifact、run出力、coverageやcache等の生成物

秘密情報らしき値や大容量binaryを発見した場合は変更を止め、内容を出力せずにユーザーへ報告する。
