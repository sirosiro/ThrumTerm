# 実行環境ドメイン・マニフェスト (sandbox/ARCHITECTURE_MANIFEST.md)

---

## Part 1: このマニフェストの取扱説明書 (Guide)

### 1. 目的 (Purpose)
本ドキュメントは、Aiderエージェントが動作する個別の作業用サンドボックスディレクトリの構造、一時ファイルのライフサイクル、およびセキュリティとキャッシュ管理方針を定義するサブ・マニフェストです。

### 2. 憲章の書き方 (Guidelines)
- サンドボックス内で発生する一時ファイル（Aiderのチャット履歴や一時キャッシュ等）の削除ロジックを変更する際は、必ず本マニフェストにその手順と理由を追記してください。
- 実行時のプロセス隔離（他のディレクトリのファイルを誤って編集しないようにする防衛策）を維持するための原則を定義します。

### 3. リスクと対策 (Risks and Mitigations)
- **リスク**: Aiderがサンドボックスを脱出してルートリポジトリのソースコードを勝手に書き換えてしまう。
  - **対策**: Aider起動時のカレントディレクトリを `sandbox/LeaderAI` または `sandbox/WorkerAI` に完全に固定し、プロジェクトルートへの書き込み権限を間接的に遮断します（`--no-git` オプションによる追跡範囲の制限）。

---

## Source Analysis Metadata

- **Source Repository**: ThrumTerm/sandbox
- **Detected License**: MIT License
- **Structural Similarity Risk**: Low (動的に生成・クリアされる一時サンドボックス領域)
- **Attribution Required**: None

---

## Part 2: マニフェスト本体 (Content)

### 1. 核となる原則 (Core Principles)
- **原則: 実行空間の完全なクリーンルーム化**
  - *理由*: 前の実行時のキャッシュやチャット履歴が残っていると、LLMが過去の文脈を引きずって同じ発言を繰り返したり、ファイルの変更適用（パッチ）で混乱したりするため、起動時にキャッシュおよび履歴ファイルを物理削除する。
- **原則: 一時ファイルの排他制御**
  - *理由*: `input.txt` や `AGENTS.md` などの制御ファイルをAiderプロセスに書き換えられないよう、`0o444`（読込専用）で権限を保護する。また、応答を書き込ませる `output.txt` は、送信前にサイズ0の空ファイルを配置してAiderのドロップエラーを防ぐ。

### 2. 主要なアーキテクチャ決定 of 記録 (Key Architectural Decisions)
- **2026-06-28: .DS_Store のGit追跡排除と物理削除の徹底**
  - *Decision*: サンドボックス内外から `.DS_Store` ファイルを完全に削除し、`.gitignore` に除外パターンを適用する。
  - *Rationale*: macOS環境特有の一時ファイルがAiderのインデックスやファイルの移動（shutil.move）時に干渉して予期せぬエラーを引き起こすのを防ぐため。
- **2026-06-28: Aiderキャッシュディレクトリの強制削除**
  - *Decision*: サンドボックス内の `.aider.tags.cache.v4` ディレクトリを起動時に `shutil.rmtree()` で強制削除する。
  - *Rationale*: リポジトリマップのキャッシュが残っていると、起動動作が不安定になったり古いファイルを勝手に追加したりするため。

### 3. AIとの協調に関する指針 (AI Collaboration Policy)
- AIエージェントは、自身のサンドボックス（`sandbox/LeaderAI` または `sandbox/WorkerAI`）から一歩も出てはならない。
- サンドボックス外のファイルを書き換えるコマンド（`rm`, `mv` 等）をAiderのチャット内から実行することは、規約上厳重に禁止する。変更はすべて `DiscussionCoordinator`（親プロセス）側の安全なファイルI/O機能に委ねること。

### 4. コンポーネント設計仕様 (Component Design Specifications)

本ドメインは、以下の実行空間およびファイル制御を担当します。

```text
sandbox/
├── ARCHITECTURE_MANIFEST.md  (本マニフェスト)
├── LeaderAI/                  (LeaderAI用の独立サンドボックス)
│   ├── input.txt             (対話相手から届いた最新の生発言 - 0o444)
│   ├── output.txt            (これから自身が書き込むべき意見ファイル - 0o644)
│   ├── AGENTS.md             (マージされた人格ガイドライン - 0o444)
│   └── .aider.chat.history.md (Aiderのセッション履歴ログ)
└── WorkerAI/                  (WorkerAI用の独立サンドボックス)
    ├── input.txt             (同上)
    ├── output.txt            (同上)
    ├── AGENTS.md             (同上)
    └── .aider.chat.history.md (同上)
```

- **InputOutputController (実行環境コントローラー)**
  - **責務**: 各サンドボックス内の入力・出力ファイルの作成、読込、クリア、および所有権のパーミッション変更。
  - **提供する主要API**:
    - `write_raw_input(content)`: `input.txt` のパーミッションを一時的に解除して内容を上書きし、`0o444` で再ロックする。
    - `create_empty_output()`: `output.txt` のパーミッションを解除して削除し、サイズ0の空ファイルを新規作成する。
    - `move_to_opponent_input(opponent_io)`: 自身の `output.txt` を相手の `input.txt` に上書き `shutil.move` で移動させ、自動的に送信元ファイルを消去する。
    - `read_output()`: 自ペインが書き出した `output.txt` の内容を読み込み、余計なプレフィックス（「了解しました」「相手の意見：」等）を除去してプレーンなテキストとして返す。

### 5. 既知の未解決課題と保留事項 (Known Open Issues & Deferred Decisions)
- **Issue: sandbox 内の git 管理の有効化**
  - *Status*: 保留。
  - *Rationale*: Aiderが各 sandbox 内で独自の git コミットを自動生成すると、ルートの git ツリーと衝突して追跡が難しくなるため、現在は `--no-git` オプションで git 追跡を完全に無効化している。
