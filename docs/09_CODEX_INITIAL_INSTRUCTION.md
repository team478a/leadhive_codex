# LeadHive V2 - Codex 初回開発指示

## 目的

既存LeadHiveを改修するのではなく、LeadHive V2を新規構築してください。

V2リポジトリ:

`https://github.com/team478a/leadhive_codex`

既存リポジトリ:

`https://github.com/stockbusiness/leadhive`

旧版は参考コードとしてのみ使用し、丸ごとコピーしないでください。

LeadHive V2のV1目的は次の通りです。

> 業種と営業目的を指定し、企業を収集し、Webサイトを解析し、AIで営業適性を判定し、優先順位付き営業リストを作成する。

## 最初に行うこと

実装を始める前に、まず以下を確認してください。

1. 現在のV2リポジトリ構成
2. 既存コードの有無
3. 使用中のNode / Pythonバージョン
4. PostgreSQL接続方法
5. `.env.example` の有無
6. lint / typecheck / test / build の実行方法
7. 旧LeadHiveから再利用できるコード候補

確認結果を短くまとめた後、Phase 1の実装を開始してください。

## 技術構成

Frontend:
- React
- TypeScript
- Vite
- Tailwind CSS

Backend:
- FastAPI
- Python 3.11+

Database:
- PostgreSQL
- SQLAlchemy

AI:
- AI ProviderをService層で分離する
- 初期ProviderはOpenAIで可

Search:
- Serper
- Google Places API

## 最重要設計

SNS、運送、ECなどの業種ロジックをPythonコードに直接固定しないでください。

以下を `TargetProfile` としてDB管理してください。

- search_keywords
- positive_keywords
- negative_keywords
- exclusion_keywords
- scoring_rules
- ai_instruction

`Project` には以下を持たせてください。

- target_profile_id
- sales_objective
- region

同じ運送会社でも、採用支援と車両販売では評価条件が異なるため、
`TargetProfile + SalesObjective` の組み合わせでAI判定できるようにしてください。

## 初期DB

必要テーブル:

- users
- projects
- target_profiles
- companies
- collection_jobs
- activities

詳細は `docs/04_DATABASE_DESIGN.md` を参照してください。

## Phase 1 実装範囲

今回はPhase 1だけ実装してください。

### Backend

- FastAPI基本構成
- PostgreSQL接続
- SQLAlchemyモデル
- DB migration方式の確立
- User
- Project
- TargetProfile
- 認証
- CRUD API
- health check

### Frontend

- React + TypeScript + Vite
- Tailwind
- Login
- Project一覧
- Project作成
- TargetProfile一覧
- TargetProfile作成・編集
- API client共通化

### 初期TargetProfile

初期データとして以下2件を投入してください。

#### SNS運用事業者

検索キーワード:
- SNS運用代行
- Instagram運用代行
- TikTok運用代行
- SNSマーケティング
- SNSコンサル

#### トラック・運送事業者

検索キーワード:
- 運送会社
- トラック運送
- 一般貨物自動車運送事業
- 物流会社
- 配送会社

## 旧LeadHiveから参照してよいもの

以下は設計・実装の参考にしてください。

- `server/services/serper_search.py`
- `server/services/google_places.py`
- `server/services/scraper.py`
- domain normalize関連
- aggregator判定
- 重複排除

ただしPhase 1ではまだ収集機能を実装しないでください。

## 持ち込まないもの

- EC collector
- EC専用 scorer
- AutoMaster
- billing
- Stripe
- Founder
- tele apo
- notification scheduler
- MRR / ARR
- EC platform detection
- Shopify / Amazon / 楽天専用判定
- 2FA
- Customer Portal
- 自動DM
- 自動フォーム送信

## セキュリティ

以下を必ず実施してください。

- `.env` をGit管理しない
- `.env.example` を作る
- APIキーをコードへ直書きしない
- パスワードは安全にハッシュ化する
- CORSを環境変数で制御可能にする
- SQLインジェクションを避ける
- 認証必須APIを明確に分ける

## 品質チェック

Phase 1完了前に必ず以下を実行してください。

Frontend:
- typecheck
- lint
- build

Backend:
- import check
- tests
- API起動確認

問題があれば修正してから完了扱いにしてください。

## 完了時の報告形式

以下を報告してください。

1. 実装した内容
2. 作成・変更した主要ファイル
3. DBテーブル
4. API一覧
5. 画面一覧
6. テスト結果
7. 残課題
8. 次のPhaseで実装する内容

## 重要

一度にV1全体を実装しないでください。

今回はPhase 1だけです。

Phase 1が安定したことを確認してから、Phase 2の企業収集機能へ進みます。
