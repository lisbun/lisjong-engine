# lisjong-engine

Personal Japanese riichi mahjong game engine.

## 概要

`lisjong-engine` は、日本式リーチ麻雀そのものを正しく動かすための個人開発ゲームエンジンです。
AIの強さや戦略ではなく、ルール判定、状態管理、合法手、和了・点数計算、局・ゲーム進行を担当します。

現在は初期開発段階です。まずPython package、test、CI、責務境界を整備し、その後
`python-study` に残っている麻雀基盤を棚卸しして選択的に移行します。

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
- `python-study` のコードは単純コピーせず、棚卸し後に現在採用する設計だけを移行する

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

最初の到達目標候補は、指定された`RuleSet`に従い、4人日本式リーチ麻雀の半荘を
合法手だけで開始から最終結果まで決定的に完走できることです。

現在の進捗・完了条件はGitHub Issuesを正本とします。

## License

`lisjong-engine` 自身のsource codeはMIT Licenseで公開します。
外部library、牌譜、データ等を利用する場合は、それぞれの提供元のlicenseと利用条件を確認します。
