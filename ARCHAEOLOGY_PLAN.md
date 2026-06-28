# 発掘計画書 (ARCHAEOLOGY_PLAN.md)

このドキュメントは、[DESIGN_PHILOSOPHY.md](file:///Users/sirosiro/project/ThrumTerm/DESIGN_PHILOSOPHY.md) の Step 4 に基づき、既存プロジェクトのアーキテクチャ解析（考古学アプローチ）を進めるための発掘計画を定義したものです。

---

## 1. ドメインの特定 (Domain Identification)

- **プロジェクト名**: ThrumTerm
- **ドメイン定義**: **Aiderおよびtmuxを活用した、対話型マルチエージェントによる自律技術討論（ディスカッション）制御フレームワーク。**
- **主要な目的**:
  異なる人格（ペルソナ・マニフェスト）を持った2つの独立したAiderプロセスを個別のtmuxペインで立ち上げ、ディスク上のファイル操作を契機として、人間が介入することなく自律的にラリーを繰り返しながら技術的論点を深める討論プロセスを統制・記録すること。

---

## 2. マニフェスト配置マップ (Fractal Configuration Map)

プロジェクトのモジュール構造と責務を明確にするため、以下のフラクタル（階層型）なマニフェスト配置ツリーを提案します。

```text
/Users/sirosiro/project/ThrumTerm/
├── ARCHITECTURE_MANIFEST.md (ルート・マニフェスト)
├── agent_configs/
│   └── ARCHITECTURE_MANIFEST.md (設定定義ドメイン・マニフェスト)
└── sandbox/
    └── ARCHITECTURE_MANIFEST.md (実行環境ドメイン・マニフェスト)
```

---

## 3. 各階層の推定責務 (Hierarchical Responsibilities)

1. **`./ARCHITECTURE_MANIFEST.md` (ルート・マニフェスト)**
   - **推定責務**: システム全体のアーキテクチャ（tmuxセッションおよびAiderクライアントの並行制御）、メインオーケストレーターである `DiscussionCoordinator` の設計憲章、およびプロジェクト全体の統一的な開発・ライセンス原則の定義。
2. **`./agent_configs/ARCHITECTURE_MANIFEST.md` (設定定義ドメイン)**
   - **推定責務**: ディスカッションの対立軸を形成するペルソナ（Innovator/Analyst）およびマニフェストファイルの構造化、多言語（日本語・英語）ローカライズ設計方針の定義。
3. **`./sandbox/ARCHITECTURE_MANIFEST.md` (実行環境ドメイン)**
   - **推定責務**: Aiderの実行独立性を保証するための隔離されたクリーンルーム（LeaderAI/WorkerAI）のライフサイクル管理、キャッシュクリア手順、および一時ファイル（`AGENTS.md`, `input.txt`, `output.txt`）の排他制御方針の定義。

---

## 4. 次のステップ

この計画（`ARCHAEOLOGY_PLAN.md`）について人間（ユーザー）の承認を得た後、各モジュールのコード詳細解析に着手し、推定思想レポート（`ARCHAEOLOGY_REPORT.md`）の作成と各マニフェストの具体的起草を行います。
