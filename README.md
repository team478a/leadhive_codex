# LeadHive V2

LeadHive V2 は、業種ごとの営業先候補を収集し、企業情報を解析し、AIで営業適性を判定して優先順位付きリストを作成するBtoB営業リスト収集基盤です。

メール・フォーム送信と追客の運用手順は [`docs/41_SMTP_SETTINGS_MANAGEMENT.md`](docs/41_SMTP_SETTINGS_MANAGEMENT.md) から [`docs/65_BULK_FORM_DELIVERY.md`](docs/66_DELIVERY_CAMPAIGNS_AND_PIPELINE.md) を参照してください。

## 開発方針

- 開発主体: Codex
- 旧版: https://github.com/stockbusiness/leadhive
- 旧版は参照専用
- V2は新規設計
- 業種固有ロジックは Target Profile / Sales Objective で差し替える
- Phase単位で実装・検証する

## ドキュメント

仕様は `docs/00_INDEX.md` から順番に確認してください。

最初の実装指示は `docs/09_CODEX_INITIAL_INSTRUCTION.md` です。

## Phase 1〜6・運用改善 実装

React / TypeScript / Vite / Tailwind CSS、FastAPI / SQLAlchemy / PostgreSQLを使用。
ログイン、Project CRUD、TargetProfile CRUD・複製、標準プロファイル2件、
Serper / Google Places / URL / CSVからの企業収集とCollection Job管理まで実装しています。
Webサイト解析、企業情報・SNS・問い合わせ先抽出まで実装しています。
Target ProfileとSales Objectiveを使った構造化AI判定まで実装しています。
企業一覧・詳細、フィルター、営業状況・メモ、CSV出力、簡易ダッシュボードまで実装しています。

実装範囲・判断・検証結果は[Phase 1実装記録](docs/11_PHASE1_IMPLEMENTATION.md)を参照してください。
Phase 2の詳細は[Phase 2実装記録](docs/12_PHASE2_IMPLEMENTATION.md)を参照してください。
Phase 3の詳細は[Phase 3実装記録](docs/13_PHASE3_IMPLEMENTATION.md)を参照してください。
Phase 4の詳細は[Phase 4実装記録](docs/14_PHASE4_IMPLEMENTATION.md)を参照してください。
Phase 5の詳細は[Phase 5実装記録](docs/15_PHASE5_IMPLEMENTATION.md)を参照してください。
実データ検証手順は[Phase 6検証手順](docs/16_PHASE6_VALIDATION_RUNBOOK.md)、営業運用改善は
[Operations 1実装記録](docs/17_OPERATIONS_1_IMPLEMENTATION.md)、バックグラウンド処理は
[実装記録](docs/18_BACKGROUND_JOBS_IMPLEMENTATION.md)を参照してください。
ワーカー停止時の自動回収は[実装記録](docs/19_JOB_RECOVERY_IMPLEMENTATION.md)を参照してください。
失敗通知と監視画面は[実装記録](docs/20_OPERATION_MONITORING_IMPLEMENTATION.md)を参照してください。
検索画面の非同期化は[実装記録](docs/21_ASYNC_SEARCH_COLLECTION_IMPLEMENTATION.md)を参照してください。
検索テンプレートと定期実行は[実装記録](docs/22_SEARCH_SCHEDULES_IMPLEMENTATION.md)を参照してください。
テンプレート別成果分析は[実装記録](docs/23_SEARCH_ANALYTICS_IMPLEMENTATION.md)を参照してください。
企業データ品質管理は[実装記録](docs/24_DATA_QUALITY_IMPLEMENTATION.md)を参照してください。
保存フィルターと担当者別営業成果は[実装記録](docs/27_SAVED_FILTERS_ASSIGNEE_ANALYTICS.md)を参照してください。
手動修正項目の再解析保護は[実装記録](docs/28_MANUAL_FIELD_PROTECTION.md)を参照してください。
CSV取込プレビューと列対応付けは[実装記録](docs/29_CSV_IMPORT_WORKFLOW.md)を参照してください。
期間別の営業活動成果は[実装記録](docs/30_SALES_ACTIVITY_ANALYTICS.md)を参照してください。
連絡禁止と連絡先品質管理は[実装記録](docs/31_CONTACT_SUPPRESSION_QUALITY.md)を参照してください。
検索収集の精度・速度改善は[実装記録](docs/32_COLLECTION_ACCURACY_SPEED.md)を参照してください。
営業アプローチキューは[実装記録](docs/33_OUTREACH_QUEUE.md)を参照してください。
相手企業の担当者管理は[実装記録](docs/34_COMPANY_CONTACT_PEOPLE.md)を参照してください。
アプリ内通知センターは[実装記録](docs/35_IN_APP_NOTIFICATIONS.md)を参照してください。
重要ページの巡回解析は[実装記録](docs/36_MULTIPAGE_WEB_ANALYSIS.md)を参照してください。
企業情報の自動再解析は[実装記録](docs/37_ANALYSIS_REFRESH_SCHEDULES.md)を参照してください。
プロジェクトメンバーと権限は[実装記録](docs/38_PROJECT_MEMBERS.md)を参照してください。
AI営業文面は[実装記録](docs/39_OUTREACH_DRAFTS.md)を参照してください。
承認付きメール送信は[実装記録](docs/40_APPROVED_EMAIL_DELIVERY.md)を参照してください。
SMTP設定の管理画面とテスト送信は[実装記録](docs/41_SMTP_SETTINGS_MANAGEMENT.md)を参照してください。
重複候補の検出と企業統合は[実装記録](docs/25_COMPANY_DEDUPLICATION_IMPLEMENTATION.md)を参照してください。
担当者とフォロー期限管理は[実装記録](docs/26_ASSIGNEE_FOLLOWUP_IMPLEMENTATION.md)を参照してください。
追客通知からの直接操作は[実装記録](docs/62_FOLLOWUP_NOTIFICATION_ACTIONS.md)、収集精度・速度の実績比較は[実装記録](docs/63_COLLECTION_PERFORMANCE_INSIGHTS.md)を参照してください。
AI判定レビュー、文面A/Bテスト、案件管理、gBizINFO収集は[継続改善ワークフロー](docs/64_CONTINUOUS_IMPROVEMENT_WORKFLOWS.md)を参照してください。
一括フォームDMは[実装記録](docs/66_DELIVERY_CAMPAIGNS_AND_PIPELINE.md)を参照してください。
全体サービス設定（APIキー、収集、AI、SMTP、IMAP）は[運用設定](docs/67_APPLICATION_SETTINGS_MANAGEMENT.md)を参照してください。
バックグラウンド処理とAPIの共通サービス化は[サービス層の分離](docs/68_SERVICE_LAYER_REFACTOR.md)を参照してください。
初回利用者向けの画面内案内は[オンボーディングガイド](docs/69_ONBOARDING_GUIDE.md)を参照してください。

構成:

- `backend/app`: 設定、DBモデル、認証、REST API、ユーザー作成CLI
- `backend/app/services/collection.py`: 外部検索Provider、URL正規化、CSV解析
- `backend/app/services/scraper.py`: 安全なHTML取得、企業情報・SNS・問い合わせ先抽出
- `backend/app/services/ai.py`: AI Provider、構造化出力、ランク判定
- `backend/app/company_routes.py`: 企業一覧・詳細・営業管理・CSV・ダッシュボードAPI
- `backend/migrations`: Alembicスキーマと初期データMigration
- `backend/tests`: 実PostgreSQLに対するAPI・権限テスト
- `frontend/src`: ログイン、プロジェクト管理、プロファイル管理、共通APIクライアント
- `frontend/src/CollectionPage.tsx`: 企業収集とCollection Job結果
- `frontend/tests`: デスクトップ・モバイルのブラウザ操作テスト

## ローカル起動（PowerShell）

前提: Node.js 22、Python 3.11以上（検証環境3.12）、Docker Compose。
以下はリポジトリ直下で実行します。`.env`はGit管理されません。

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

`.env`の`POSTGRES_PASSWORD`と`DATABASE_URL`内のパスワードを同じ値に設定してください。
初期値はローカル開発専用です。ポート競合時は`POSTGRES_PORT`と`DATABASE_URL`のポートを
両方変更してください（今回の検証環境では15439を使用）。
既存の`.env`がある場合は上書きせず設定を確認してください。

```powershell
docker compose -p leadhive-phase1 up -d --wait
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements.lock
backend/.venv/Scripts/python -m pip install --no-deps -e backend
backend/.venv/Scripts/python -m alembic -c backend/alembic.ini upgrade head
backend/.venv/Scripts/python -m app.cli your-address@example.com
```

CLIはパスワードを非表示で2回入力します（12文字以上）。初期ユーザーや共通パスワードは
自動作成しません。公開サインアップ機能は設けていません。

バックエンド:

```powershell
backend/.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

検索収集・一括Web解析・一括AI判定を処理するワーカーも別ターミナルで起動します。

```powershell
backend/.venv/Scripts/python -m app.worker
```

ワーカーを起動していない間も登録済みジョブはDBに保持され、次回起動時に古いものから処理されます。

別のターミナルでフロントエンド:

```powershell
cd frontend
npm ci
npm run dev
```

画面: http://localhost:5173 / API仕様: http://127.0.0.1:8000/docs
Viteが`/api`をバックエンドへ転送します。ログイン後、標準プロファイルを選んでプロジェクトを
作成できます。条件を変更する場合は標準プロファイルを複製して編集してください。

macOS / LinuxではPython実行パスを`backend/.venv/bin/python`に読み替えてください。

## 設定・セキュリティ

| 変数 | 用途 |
| --- | --- |
| `DATABASE_URL` | PostgreSQL接続先。`postgresql://`もpsycopgドライバへ正規化 |
| `CORS_ORIGINS` | 許可するブラウザOriginのカンマ区切り。書き込み時のOrigin検証にも使用 |
| `COOKIE_SECURE` | HTTPS運用では`true`。ローカルHTTPのみ`false` |
| `SESSION_HOURS` | セッション有効時間（1〜168時間、既定12時間） |
| `POSTGRES_PASSWORD` / `POSTGRES_PORT` | ローカルCompose用のDB設定 |
| `SERPER_API_KEY` | Google検索に使用するSerper APIキー |
| `GOOGLE_PLACES_API_KEY` | Places API (New)のAPIキー |
| `EXTERNAL_API_TIMEOUT_SECONDS` | 外部APIのタイムアウト（1〜60秒、既定20秒） |
| `SCRAPER_TIMEOUT_SECONDS` | Webサイト取得タイムアウト（1〜60秒、既定15秒） |
| `SCRAPER_MAX_BYTES` | 1ページの取得上限（既定2MB） |
| `SCRAPER_USER_AGENT` | robots.txt判定とHTTP取得に使うUser-Agent |
| `OPENAI_API_KEY` | OpenAI APIキー（Git管理しない） |
| `OPENAI_MODEL` | AI判定モデル（既定`gpt-5.6-luna`） |
| `AI_TIMEOUT_SECONDS` | AI APIタイムアウト（1〜120秒、既定45秒） |
| `AI_MAX_WEBSITE_CHARS` | AIへ渡すWeb本文の最大文字数（既定30000） |
| `WORKER_LEASE_SECONDS` | 実行中ジョブのリース秒数（60〜3600、既定300） |
| `WORKER_MAX_ATTEMPTS` | ワーカー停止時の最大試行回数（1〜10、既定3） |
| `PUBLIC_APP_URL` | メールの配信停止リンクに使う公開アプリURL |

パスワードはArgon2idでハッシュ化。認証はランダムな不透明トークンをHttpOnly / SameSite=Lax
Cookieで保持し、DBにはそのSHA-256のみ保存します。JWTは使用しないため`JWT_SECRET`は不要です。
ログアウトと再ログイン時は該当セッションを失効させます。期限切れセッションはログイン時に清掃します。
ユーザー所有データへのアクセスを毎回検証し、標準プロファイルは全ユーザーが参照・複製のみ可能です。
SQLはSQLAlchemyのパラメータ化クエリを使用。入力値・パスワード・接続文字列はログに出力しません。
外部サービスのキーはPhase 1では使用しません。

本番公開時には、HTTPSと同一Originの`/api`リバースプロキシを構成し、
`COOKIE_SECURE=true`、`CORS_ORIGINS`を実サイトのOriginに設定してください。
認証試行のレート制限はリバースプロキシ側で設定します。

## DBとMigration

テーブルは`users`、`projects`、`target_profiles`、`auth_sessions`、`companies`、
`collection_jobs`、`operation_jobs`、`activities`。
Alembic管理用の`alembic_version`も作成されます。
`activities`は利用する後続Phaseで追加します。
起動時のDDL実行や`create_all()`は行いません。

```powershell
backend/.venv/Scripts/python -m alembic -c backend/alembic.ini current
backend/.venv/Scripts/python -m alembic -c backend/alembic.ini check
# モデル変更時
backend/.venv/Scripts/python -m alembic -c backend/alembic.ini revision --autogenerate -m "describe change"
```

生成された差分をレビューしてから`upgrade head`を実行します。
初期プロファイルはバージョン固定のJSONデータとしてMigrationで投入します。
適用済みMigration・JSONは書き換えず、新しいMigrationを追加してください。
`upgrade head`の再実行で重複登録はされません。
`downgrade base`はテーブルを削除するため、破棄可能なテストDB以外では実行しないでください。
プロジェクトから参照中の初期プロファイルを削除するdowngradeは外部キーで拒否されます。

## API一覧

| Method | Path | 内容 |
| --- | --- | --- |
| GET | `/api/health` | DB疎通、障害時503（認証不要） |
| POST | `/api/auth/login` | メール・パスワード認証、Cookie発行 |
| POST | `/api/auth/logout` | セッション失効、Cookie削除 |
| GET | `/api/auth/me` | 現在のユーザー |
| GET / POST | `/api/projects` | 自分の一覧 / 作成 |
| GET / PUT / DELETE | `/api/projects/{id}` | 自分の取得 / 全項目更新 / 削除 |
| GET / POST | `/api/target-profiles` | 標準＋自分の一覧 / 作成 |
| GET / PUT / DELETE | `/api/target-profiles/{id}` | 取得 / 全項目更新 / 削除 |
| POST | `/api/target-profiles/{id}/clone` | 自分専用の複製を作成 |
| GET | `/api/projects/{id}/companies` | プロジェクト内の収集済み企業 |
| GET | `/api/projects/{id}/collection-jobs` | 収集ジョブ一覧 |
| GET | `/api/collection-jobs/{id}` | 収集ジョブ詳細 |
| POST | `/api/projects/{id}/collection-jobs/search` | Serper / Places検索 |
| POST | `/api/projects/{id}/collection-jobs/urls` | URLを最大100件登録 |
| POST | `/api/projects/{id}/collection-jobs/csv` | UTF-8 CSVを取込 |
| POST | `/api/projects/{id}/collection-jobs/csv/preview` | CSVの列・先頭行を事前確認 |
| GET | `/api/collection-jobs/{id}/errors.csv` | CSV取込の行別エラーを出力 |
| POST | `/api/companies/{id}/analyze` | 企業1社のWebサイト解析 |
| POST | `/api/projects/{id}/web-analysis` | 未解析企業を最大20社解析 |
| POST | `/api/companies/{id}/ai-analysis` | 企業1社のAI判定 |
| POST | `/api/projects/{id}/ai-analysis` | 企業を最大20社AI判定 |
| GET | `/api/projects/{id}/company-list` | フィルター・並び替え対応の企業一覧 |
| GET | `/api/companies/{id}` | 企業詳細 |
| PATCH | `/api/companies/{id}/sales` | 営業状況・メモ更新 |
| GET | `/api/projects/{id}/companies.csv` | 現在の条件でCSV出力 |
| GET | `/api/dashboard` | ランク・営業状況・直近収集の集計 |
| GET | `/api/sales-activity-analytics` | 期間別の営業成果率・担当者別集計 |
| PUT | `/api/companies/{id}` | 企業基本情報・連絡先の手動修正 |
| PATCH | `/api/companies/{id}/contact-control` | 連絡禁止・除外理由・連絡先品質を更新 |
| PATCH | `/api/projects/{id}/companies/bulk-sales` | 最大100社の営業状況一括更新 |
| GET / POST | `/api/companies/{id}/activities` | 営業活動履歴の一覧 / 追加 |
| GET / POST | `/api/projects/{id}/operations` | バックグラウンド処理の一覧 / 登録 |
| POST | `/api/operations/{id}/cancel` | 待機中・実行中処理のキャンセル |
| POST | `/api/operations/{id}/retry` | 失敗・キャンセル済み処理の再登録 |
| POST | `/api/operations/{id}/acknowledge` | 失敗通知を確認済みに更新 |
| GET / POST | `/api/projects/{id}/search-schedules` | 定期検索の一覧 / 作成 |
| PUT / DELETE | `/api/search-schedules/{id}` | 定期検索の更新 / 削除 |
| POST | `/api/search-schedules/{id}/run` | 保存条件を今すぐ実行 |
| GET | `/api/projects/{id}/search-analytics` | テンプレート別の収集成果 |
| GET | `/api/projects/{id}/data-quality` | 欠損情報・解析更新状況の集計 |
| POST | `/api/projects/{id}/data-quality/reanalyze` | 失敗・期限切れ企業を再解析 |
| GET | `/api/projects/{id}/duplicate-candidates` | 重複企業候補と一致理由 |
| POST | `/api/projects/{id}/companies/merge` | 指定した企業へ重複企業を統合 |
| PATCH | `/api/projects/{id}/companies/bulk-assignee` | 最大100社の担当者を一括更新 |
| GET / POST | `/api/projects/{id}/saved-company-filters` | 企業一覧の保存フィルター一覧 / 作成 |
| PUT / DELETE | `/api/saved-company-filters/{id}` | 保存フィルターを更新 / 削除 |
| GET | `/api/projects/{id}/assignee-analytics` | 担当者別の営業状況・期限超過集計 |

health / login / logout以外はログイン必須。logoutは未ログイン時も204。
一覧は`offset`（0以上）と`limit`（1〜100）を受け付けます。
Projectのstatusは`draft` / `active` / `archived`。
非アクティブのプロファイルは新規選択できませんが、既存案件の編集はできます。
使用中のプロファイル削除は409。所有者・is_systemはリクエストで指定できません。
案件専用の上書きはプロファイルを複製し、そのプロジェクトへ割り当てる運用です。

画面からのSerper・Places検索はバックグラウンド処理へ登録するため、登録後も他の画面を操作できます。
ワーカーはキーワードごとに収集ジョブを作り、`found_count`、`saved_count`、
`duplicate_count`、`error_count`を記録します。外部API失敗もジョブを`failed`として保存します。
CSVは5MB・1000行までで、`company_name, website_url, phone, email, address`列が必要です。
同一プロジェクトではドメイン、URL、会社名＋住所で重複登録を防ぎます。

Web解析は会社名、住所、都道府県、市区町村、電話、メール、問い合わせURL、
Instagram、X、TikTok、Facebook、YouTube、LINE、事業概要、サイト本文を保存します。
robots.txtを確認し、HTML以外・容量超過・標準外ポート・プライベートIPへの取得を拒否します。
解析後のドメインや会社名＋住所が重複した場合は`duplicate`として既存企業へ関連付けます。

AI判定はWeb情報、Target Profile、Sales Objectiveを入力とし、score、rank、判定理由、
強み、懸念、推奨アプローチを構造化して保存します。rank境界はProfileの
`scoring_rules.rank_thresholds`から読み込みます。Web情報がない企業、重複、対象外企業は
AI判定をスキップします。

企業一覧はrank、最低score、地域、営業状況、収集元、キーワードで絞り込み、score順・新着順・
会社名順で並べ替えられます。CSVは同じ条件を反映し、UTF-8 BOMと数式インジェクション対策を
適用します。営業状況は未確認、営業対象、アプローチ済、返信あり、商談、成約、失注、対象外です。

企業一覧は25社単位でページ移動でき、総件数を表示します。表示中企業の複数選択と営業状況の
一括更新、基本情報・連絡先の手動修正、次回対応日時、電話・メール・フォーム・SNS・商談などの
活動履歴を管理できます。営業状況の変更は活動履歴へ自動記録します。

一括Web解析と一括AI判定はバックグラウンド処理として登録され、画面から進捗確認、キャンセル、
失敗時の再実行ができます。検索収集も同じジョブAPIに対応しています。URL・CSV取込は入力検証と
重複判定だけで完了するため同期処理のままです。同じプロジェクト・同じ処理種別の同時登録は拒否します。
失敗ジョブはダッシュボードの未確認件数へ反映され、理由・進捗・試行回数を確認して既読化できます。

## 検証

フロントエンド:

```powershell
cd frontend
npm run typecheck
npm run lint
npm run build
```

バックエンド（リポジトリ直下）:

```powershell
backend/.venv/Scripts/python -m ruff check backend
backend/.venv/Scripts/python -m ruff format --check backend
backend/.venv/Scripts/python -c "from app.main import app; print(app.title)"
docker compose -p leadhive-phase1 exec -T db createdb -U postgres leadhive_test
$env:TEST_DATABASE_URL = 'postgresql+psycopg://postgres:local-development-only@127.0.0.1:5432/leadhive_test'
backend/.venv/Scripts/python -m pytest backend/tests -q
```

テストURLのパスワード・ポートは自身の`.env`設定に合わせます。
テストDBは必ず末尾`_test`の専用DBを指定してください。存在する場合は`createdb`を省略します。
APIテストはMigrationを適用し、各ケースの変更をトランザクションでロールバックします。
Migrationの差分がモデルと一致することも検証します。

ブラウザE2E（同じ`TEST_DATABASE_URL`を設定したターミナル）:

```powershell
cd frontend
npx playwright install chromium
npm test
```

APIを18039、Viteを15173で自動起動・停止します。一時アカウントも自動作成・削除します。
ログイン失敗・成功、標準プロファイル、複製・編集・新規作成・削除、JSON検証、
Project作成・編集・永続化・削除、URL収集・重複・入力エラー・外部API設定エラー、
ログアウトをデスクトップとモバイルで確認します。
GitHub Actionsでも同じ検証とMigrationのupgrade / downgrade / upgradeを実行します。

## Phase 6 実データ検証

検索APIキー設定後、既存ユーザーを指定して再開可能な検証ランナーを実行できます。
`--stage preflight`では、キーの値を表示せずPhase 6の必要条件を一括診断できます。

```powershell
cd backend
.venv/Scripts/python -m app.phase6 --user your-address@example.com --stage all
```

SNS運用事業者100社、運送事業者100社を収集し、運送事業者は採用支援と車両販売の2つの
Sales Objectiveで判定します。途中で停止した場合は `--stage collect`、`web`、`ai`、`export`
を個別に再実行できます。出力先は既定で `backend/phase6-results` です。

`phase6-review.csv` の `review_is_target` と `review_rank_correct` を人手で記入した後、
次のコマンドで精度指標を再集計します。`report` はレビューCSVを上書きしません。

```powershell
.venv/Scripts/python -m app.phase6 --user your-address@example.com --stage report
```
