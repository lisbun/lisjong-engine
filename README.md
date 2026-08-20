# lisjong-engine

Personal Japanese riichi mahjong game engine.

## 概要

`lisjong-engine` は、日本式リーチ麻雀そのものを正しく動かすための個人開発ゲームエンジンです。
AIの強さや戦略ではなく、ルール判定、状態管理、合法手、和了・点数計算、局・ゲーム進行を担当します。

現在は、指定された`RuleSet`とdeterministicな入力のもとで、seat-specificな観測・公開action選択境界を通じて半荘を最終結果まで進行できる、v0.1相当の基礎engineが成立しています。
現在実装済みの具体的なengine contractは[`docs/architecture.md`](docs/architecture.md)、post-v0.1の長期的な発展方向は[`docs/roadmap.md`](docs/roadmap.md)を参照してください。
現在の作業進捗・完了条件はGitHub Issues / Pull Requestsを正本とします。

lisjong ecosystem全体のrepository責務、repository間依存方向、長期ロードマップは
[`lisjong-project`](https://github.com/lisbun/lisjong-project) を正本とします。
本repositoryでは `lisjong-engine` 内部のgame engine architectureと実装を管理します。

## lisjongとの関係

```text
lisjong:
    麻雀をどう打つか考える

lisjong-engine:
    麻雀を正しく動かす
```

将来的には `lisjong` の同じPolicyをRiichiEnv、RiichiLab、`lisjong-engine`で動かすことを目指します。
依存方向は一方向です。

```text
lisjong -> lisjong-engine
lisjong-engine -X-> lisjong
```

`lisjong-engine` はRiichiEnv、RiichiLab、AI実装、online通信へ依存しません。

## 主な責務

- 牌・手牌・山・河・副露などのドメインモデル
- ゲーム状態管理と合法手生成
- 和了判定、役判定、符計算、点数計算
- チー、ポン、槓、リーチ、流局、途中流局
- 本場、供託、連荘、局進行、東風戦・半荘などのゲーム進行
- 最終点数・順位処理
- `RuleSet` とルール差分/preset
- deterministicな実行に必要なseed管理

向聴数、受け入れ枚数、牌効率、安全度、押し引き等はAI・評価側の責務とし、engineには含めません。

## 開発方針

- 通常版CPython 3.14を初期基準とする
- Python-firstで実装し、性能最適化はprofiling後に検討する
- runtime dependencyは必要になるまで追加しない
- 麻雀ルール機構と個別設定を`RuleSet`で分離する
- deterministicなgame実行と再現性を重視する
- 未確認のRiichiLab等の固有ルールを推測で実装しない
- 初期移行時の`python-study`棚卸し・設計判断は[`docs/python-study-migration.md`](docs/python-study-migration.md)を参照する

## 開発環境

初期基準は通常版CPython 3.14です。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

macOS / Linuxではactivateコマンドを次のように読み替えます。

```bash
source .venv/bin/activate
```

### 品質確認

```text
python -m ruff format --check .
python -m ruff check .
python -m unittest discover -s tests -v
```

ローカルとGitHub Actions CIで同じ品質確認commandを使用します。

## ロードマップ

v0.1相当の基礎完成後は、現在のrule-correct / deterministicなgame executionを維持しながら、validation、recordability support、consumer / interoperability readiness、performance、RuleSet evolution等を具体的なuse caseに応じて成熟させます。

長期的な方向は[`docs/roadmap.md`](docs/roadmap.md)、現在の実装contractは[`docs/architecture.md`](docs/architecture.md)、進行中の作業はGitHub Issues / Pull Requestsを参照してください。

## License

`lisjong-engine` 自身のsource codeはMIT Licenseで公開します。
外部library、牌譜、データ等を利用する場合は、それぞれの提供元のlicenseと利用条件を確認します。
