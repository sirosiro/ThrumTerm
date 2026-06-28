# 推定思想レポート (ARCHAEOLOGY_REPORT.md)

本レポートは、[DESIGN_PHILOSOPHY.md](file:///Users/sirosiro/project/ThrumTerm/DESIGN_PHILOSOPHY.md) の Step 5 に基づき、既存リポジトリ内のコード（主に [bridge.py](file:///Users/sirosiro/project/ThrumTerm/bridge.py)）から抽出した設計思想と技術的課題を整理したものです。

---

## 0. ドメインの特定と外部規約の宣言

- **適用ドメイン**: **Aider CLIおよびtmuxセッション連携による、自律的マルチエージェント討論実行制御フレームワーク。**
- **準拠すべき外部規約**:
  - **Aider CLI (v0.86.2以上)**: `--read` オプションによる読込専用ファイルインプット規約、`--file` オプションによる単一ファイル編集追跡規約、およびMarkdown（```）形式のコード編集命令フォーマット。
  - **tmux CLI**: 擬似ターミナル（PTY）制御、ペイン分割（`split-window`）、文字列送信（`send-keys`）、画面バッファ取得（`capture-pane`）。

---

## 1. 推定される設計原則

- **フラクタルな独立設定の維持 (AGENTS.md)**
  Aiderがカレントディレクトリの `AGENTS.md` を優先的に読み込む仕様を利用し、`sandbox/LeaderAI` および `sandbox/WorkerAI` のそれぞれにマージされた `AGENTS.md` を配置して個別プロセスを自律制御している。
- **ファイル移動型メッセージ・パッシング (I/O隔離)**
  `output.txt` を相手の `input.txt` に物理的に `shutil.move()`（移動）することで、余分なメタヘッダーの混入を防ぐとともに、送信元の空き状態を作って差分適用の混同を防いでいる。
- **状態ロックによる防壁の構築**
  LLMがコンテキストとして与えられた指示書（`AGENTS.md`）や入力（`input.txt`）を自身で書き換えるのを防ぐため、OSのパーミッション制御（`chmod 0o444`）を用いて読込専用としてロックしている。

---

## 2. 既存のアーキテクチャ制約

- **環境依存性**: 動作中の `tmux` セッション内から実行されることが前提。
- **プロセス同期の遅延**: tmux内の画面状態（シェルプロンプト `>` の安定）を 1 秒間隔でポーリング監視するため、ディスクI/OおよびLLM推論速度に比例した実行遅延が発生する。
- **軽量モデルでの指示従属性**: Ollama経由のローカルモデル（Gemma2やLlama3等）の従属性に依存しているため、プロンプトの否定文（「〜するな」）が過剰に効いてファイル生成を停止するリスクを常に抱えている。

---

## 3. 発見された例外と矛盾

- **バグ: ログ追記先の表示矛盾**
  `bridge.py` の 449行目において、出力先が `discussion_log.md` にリネームされているにもかかわらず、ユーザー画面への出力表示が `conversation.md に追記されました` のまま古い状態で残っている。
- **.gitignore への sandbox 内の一時ファイルの欠落**
  Aiderのメタファイル（`.aider.chat.history.md` 等）は各 sandbox ディレクトリ内にあるが、git追跡対象外とするための指定が、プロジェクトルートの `.gitignore` ですべて正確にカバーされているか確認が必要。

---

## 4. 利用されていないコード (Dead Code) の可能性

- **古いルート直下設定ファイルの自動移行ロジック**
  `bridge.py` の 461〜464行目にある `_prepare_configs` 内で、プロジェクトルートにある古い `persona_a.txt` 等を `agent_configs/` に物理移動するコードがある。これらはリファクタリングが完了している現在、デッドコード化している可能性がある。

---

## 5. コメントと実装の乖離

- `bridge.py` の 181〜183行目のコメントで `Aider doesn't report file not found or drop output.txt` と記述されているが、以前の 352行目の `delete_output()` から `create_empty_output()` への変更に伴う挙動変化の履歴と完全に一致している。

---

## 6. 提案されるインテント・コメント (Intent Comments)

[bridge.py](file:///Users/sirosiro/project/ThrumTerm/bridge.py) の主要コンポーネントに対し、設計意図を明示する以下のインテント・コメントをコードへ追加することを提案します。

```python
# @intent:responsibility 討論テーマの言語を自動検知し、英語と日本語のプロンプト・設定を切り替える責責を負う。
class LanguageDetector: ...

# @intent:responsibility tmuxの擬似端末セッションとペインを操作し、プロンプトの状態変化を監視する責務を負う。
class TmuxSession: ...

# @intent:responsibility ペルソナとマニフェストを統合してAGENTS.mdを生成し、かつLLMによる改変を防ぐロック制御を行う。
class AgentConfig: ...

# @intent:responsibility ディスカッション中のメッセージのバトン渡し（shutil.move）および空出力ファイルのライフサイクルを管理する。
class InputOutputController: ...
```

---

## 7. コンポーネント設計仕様の具体化

本プロジェクトの各マニフェストファイルを生成するにあたり、以下のモジュールAPI仕様を設計の「正」として合意形成します。

### 7.1. ルートドメイン (DiscussionCoordinator)
- **責務**: 全体のオーケストレーション、tmuxの3ペイン分割、およびディスカッションループの実行統制。
- **提供する主要API**:
  - `setup_environment()`: ログファイル初期化とサンドボックスの完全クリーンアップ。
  - `start_panes_and_aider()`: tmuxペイン分割およびAiderコマンドの非同期立ち上げ。
  - `run_discussion()`: A/Bエージェント間のラリー制御。
  - `generate_summary()`: 討論全ログを LeaderAI に引き渡し、要約を作成させて追記する。

### 7.2. エージェント設定定義ドメイン (AgentConfig / agent_configs/)
- **責務**: エージェントの性格および行動規範（二重警告ルールを含む）の合成。
- **提供する主要API**:
  - `restore()`: `persona_x` と `manifest_x` を合流させ、最先頭にテーマヘッダー `# ディスカッションテーマ: 「...」` を挿入した上で、`0o444` 属性の `AGENTS.md` を書き出す。

### 7.3. 実行環境ドメイン (InputOutputController / sandbox/)
- **責務**: エージェントごとの作業ディレクトリの管理とファイルI/O。
- **提供する主要API**:
  - `write_raw_input(content)`: メタヘッダーなしで生ログを書き込み、`0o444` で保護する。
  - `move_to_opponent_input(opponent_io)`: 自身の `output.txt` を相手の `input.txt` に `shutil.move` で直接上書き移動し、所有権をロックする。
  - `create_empty_output()`: 差分パッチを抑止するためにサイズ0の空ファイルを事前に `touch` 配置する。
