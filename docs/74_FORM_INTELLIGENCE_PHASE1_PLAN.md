# Form Intelligence Phase 1 調査・実装計画

## 1. 調査結果

### 現在の構成

- Frontend: React 19 / TypeScript / Vite / Tailwind CSS 4
- Backend: FastAPI / Python 3.11+ / SQLAlchemy 2 / Alembic
- Database: PostgreSQL 16
- ローカル配布: Docker Compose と Windowsインストーラー
- 認証: HttpOnly CookieによるDBセッション
- 権限: プロジェクト所有者、editor、viewer
- バックグラウンド処理: PostgreSQLの `operation_jobs` と常駐worker

### 既存機能との関係

既存のWeb解析は公式サイトと最大4件の主要ページを取得し、問い合わせURLを1件だけ `companies.contact_url` に保存する。robots.txt確認、SSRF対策、リダイレクト上限、取得サイズ上限、タイムアウトは既に実装されている。

フォーム機能として、静的HTMLの最初のPOSTフォームを読み取り、担当者の承認後に送信する単発送信と一括送信が存在する。CAPTCHA、radio、checkbox、外部ドメイン送信などは自動処理せず、Codex支援キューへ回す。

今回必要な次の機能は存在しない。

- 複数の問い合わせページ候補と複数フォームの保存
- フォーム項目の標準キーへの正規化
- 営業禁止表現、CAPTCHA種別、確認画面可能性の事前判定
- Form StatusとFingerprint
- 判定根拠、confidence、解析イベント、AI利用量の保存
- 人間によるマッピング修正と修正履歴
- 保存済みForm Profileの一覧・詳細表示

既存のフォーム送信処理は送信時に毎回フォームを読み直しており、Form Profileを利用していない。Phase 1では送信処理へ自動接続せず、解析・保存・確認・修正だけを追加する。

### PlaywrightとDecision Provider

FrontendのE2EテストにはPlaywrightがあるが、BackendのWeb解析にはブラウザエンジンがない。Phase 1では既存の `SafeFetcher` による静的HTML解析を主経路とする。JavaScript実行が必要なフォームは `REVIEW_REQUIRED` として記録する。ブラウザ取得を差し替えられる境界を設け、実証結果で必要性を確認してからBackend用Playwrightを追加する。これによりWindows配布パッケージとDockerイメージの急な肥大化を避ける。

既存の `AiProvider` は企業評価と営業文面生成に特化しているため、そのまま流用しない。Form Intelligence専用の `FormDecisionProvider` を追加する。Rule Providerを常時使用し、OpenAI Providerはルールで判断できない項目だけを受け取る。JEVは接続仕様が未提示のため、Phase 1ではProvider登録口と入出力契約までを実装し、実通信は追加しない。

## 2. Phase 1の実装範囲

1. 公式サイトとサイト内リンクから問い合わせページ候補を探索する。
2. 候補ページ内の複数フォームと入力項目を解析する。
3. DOM情報、変更可能なルール辞書、必要時のみDecision Providerの順で標準キーへ割り当てる。
4. select、radio、checkboxの選択肢と推奨値を保存する。
5. 営業禁止表現とCAPTCHA種別を判定する。
6. Form FingerprintとForm Statusを生成する。
7. 解析結果、判定根拠、処理時間、AI利用量、エラーを保存する。
8. 単社再解析と最大100社のバックグラウンド解析を提供する。
9. 企業一覧で状態を表示し、企業詳細で項目確認と手動修正を可能にする。

大量送信、CAPTCHA突破、無人送信、Form Profileを使った自動入力と送信は実装しない。

## 3. DB migration案

現在のAlembic head `f4c9d42b786e` から新しいmigrationを1件追加する。

### `form_profiles`

- `id`
- `company_id`
- `form_url`
- `form_index`
- `form_status`
- `sales_contact_status`
- `captcha_type`
- `confirmation_page`（nullable boolean。nullはunknown）
- `is_primary`
- `form_found`
- `page_kind`
- `fingerprint`
- `analysis_version`
- `analysis_provider`
- `last_analyzed_at`
- `analysis_duration_ms`
- `error_message`
- `created_at` / `updated_at`

`company_id + form_url + form_index` を一意にする。1社に複数Form Profileを許可し、最も営業目的に適する候補を `is_primary` で示す。

### `form_profile_fields`

- `id`
- `form_profile_id`
- `position`
- `selector`
- `label`
- `name`
- `field_type`
- `required`
- `mapped_key`
- `confidence`
- `decision_source`
- `recommended_value`
- `options`（JSONB）
- `placeholder`
- `aria_label`
- `surrounding_text`
- `created_at` / `updated_at`

### `form_analysis_logs`

- `id`
- `company_id`
- `form_profile_id`（nullable）
- `event_type`
- `provider`
- `duration_ms`
- `usage`（JSONB）
- `estimated_cost`
- `confidence`
- `details`（JSONB。秘密情報や入力予定の個人情報は保存しない）
- `created_at`

手動修正は `manual_corrected` イベントとして変更前後、修正者ID、理由を `details` に保存する。

`operation_jobs.operation_type` に `form_intelligence` を追加する。

## 4. 状態判定

- `BLOCKED`: 営業禁止表現が明確
- `REVIEW_REQUIRED`: 営業可否が不明、CAPTCHAあり、必須項目がunknown、動的フォームの疑い、確認画面がunknown
- `READY`: フォームあり、営業禁止なし、必須項目がすべて確定、必須項目のconfidenceが0.80以上、CAPTCHAなし
- `UNANALYZED`: 未解析
- `STALE`: 再解析時にFingerprintが変化
- `ERROR`: 候補ページ取得または解析に失敗

Fingerprintは、項目の順序、name、id、label、type、required、select/radio/checkbox optionsを正規化したJSONのSHA-256とする。Fingerprint変更時は新しい解析結果を保存し、以前の手動修正を同じname・selectorへ再適用できる場合だけ引き継ぐ。

## 5. API設計

- `GET /api/companies/{company_id}/form-profiles`
- `GET /api/form-profiles/{profile_id}`
- `POST /api/companies/{company_id}/form-intelligence/analyze`
- `POST /api/projects/{project_id}/form-intelligence/jobs`
- `PATCH /api/form-profile-fields/{field_id}`
- `POST /api/form-profiles/{profile_id}/select-primary`
- `GET /api/form-profiles/{profile_id}/logs`

すべて既存の `company_access` / `project_access` を利用する。viewerは参照のみ、所有者とeditorが解析・修正できる。

## 6. 画面変更

### 企業一覧

- Form Status
- フォーム有無
- 営業可否
- CAPTCHA
- 最終解析日時
- 選択企業を対象にした「フォーム解析」

### 企業詳細

- 候補フォーム一覧とprimary表示
- フォーム項目、元ラベル、標準マッピング、必須、confidence、decision source
- 再解析
- ブラウザで開く
- mapped keyと推奨optionの手動修正
- 解析ログとエラー

## 7. 変更予定ファイル

### 新規

- `backend/app/model_form_intelligence.py`
- `backend/app/schema_form_intelligence.py`
- `backend/app/form_intelligence_routes.py`
- `backend/app/services/form_intelligence/__init__.py`
- `backend/app/services/form_intelligence/analyzer.py`
- `backend/app/services/form_intelligence/discovery.py`
- `backend/app/services/form_intelligence/fingerprint.py`
- `backend/app/services/form_intelligence/rules.py`
- `backend/app/services/form_intelligence/providers.py`
- `backend/migrations/versions/<revision>_add_form_intelligence_phase1.py`
- `backend/tests/test_form_intelligence.py`
- `frontend/src/CompanyFormIntelligencePanel.tsx`

### 変更

- `backend/app/models.py`
- `backend/app/schemas.py`
- `backend/app/main.py`
- `backend/app/model_operations.py`
- `backend/app/schema_workflow.py`
- `backend/app/worker.py`
- `frontend/src/types.ts`
- `frontend/src/CompaniesPage.tsx`
- `frontend/src/CompanyList.tsx`
- `frontend/src/DashboardPage.tsx`
- `frontend/src/styles.css`
- `frontend/tests/workflow.spec.ts`
- `docs/00_INDEX.md`

既存の `form_delivery.py` と一括送信処理はPhase 1では変更しない。

## 8. テスト計画

### Backend

- 問い合わせ候補URL探索と同一オリジン制限
- input、textarea、select、radio、checkbox解析
- DOM判定と日本語ルール辞書
- 不明項目だけDecision Providerへ渡ること
- 営業禁止表現と各CAPTCHA種別
- Fingerprintの安定性と変更検出
- READY / REVIEW_REQUIRED / BLOCKED / ERROR判定
- 複数Form Profileとprimary選択
- 手動修正履歴
- 認証、viewer/editor、別プロジェクトからの隔離
- ジョブの進捗、失敗、再試行、キャンセル
- 既存フォーム送信テストの回帰確認

### Frontend

- typecheck
- lint
- build
- 企業一覧の状態表示
- 複数選択からの解析ジョブ登録
- 詳細表示、再解析、手動修正のPlaywright E2E

### 完了確認

- `alembic upgrade head`
- `alembic check`
- Backend全pytest
- Frontend typecheck / lint / build / E2E
- Docker ComposeでAPI health、worker、画面表示

## 9. リスクと対処

- JavaScript生成フォーム: Phase 1では人間確認へ回し、解析率を測定してBackend Playwright導入を判断する。
- 外部サイト負荷: 1ジョブ最大100社、workerでは逐次処理、既存のrobots.txt・タイムアウト・サイズ制限を維持する。
- 誤った営業可否判定: 禁止辞書を優先し、曖昧な場合は必ず `UNCERTAIN` とする。
- AIコスト: DOMとルールで確定した項目をAIへ送らず、入力文字数と対象項目数を制限する。
- 既存送信機能との競合: Phase 1ではForm Profileを送信判断に使わず、連携は別Phaseでテストを伴って行う。
- JEV仕様未確定: 共通Provider契約だけ用意し、接続先、認証、モデル、料金、usage形式が決まるまで実通信しない。

## 10. 現在の品質基準確認

- Frontend typecheck: 成功
- Frontend lint: 成功
- Frontend build: 成功
- Backend: ローカルPython環境に依存パッケージがないため未実行。実装時にDockerのPostgreSQLテストDBで全件実行する。

