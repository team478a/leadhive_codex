# Phase 1 実装記録

検証日: 2026-09-19

## 1. 実装した内容

- FastAPI / SQLAlchemy / PostgreSQL、Alembicの基盤
- User作成CLI、メール・パスワードによるログイン、ログアウト、現在ユーザー取得
- Argon2idパスワードハッシュ、HttpOnly Cookie、DB側で失効可能なセッション
- Projectの一覧・取得・作成・更新・削除
- TargetProfileの一覧・取得・作成・更新・削除・複製
- 所有者によるアクセス制御、標準プロファイルの保護、関連データの削除制約
- SNS運用事業者、トラック・運送事業者の初期設定データ
- React / TypeScript / Vite / Tailwind CSSによる管理画面
- 実PostgreSQLのAPIテスト、ブラウザE2E、GitHub Actions設定

初期状態は仕様書・README・`.env.example`のみ。Node 22.15.0、Python 3.12.3、
Dockerが利用可能でした。既存PostgreSQLへの接続指定がなかったため、
専用Composeプロジェクト`leadhive-phase1`を作成し、ホストポート15439で検証しました。

旧版の`serper_search.py`、`google_places.py`、`scraper.py`を参照しました。
検索系はrequests依存、scraperにはECスコア依存があることを確認。
Phase 1にはこれらのコードを移植していません。

## 2. 主要ファイル

| ファイル | 内容 |
| --- | --- |
| `backend/app/main.py` | API、CORS、Origin検証、エラー応答 |
| `backend/app/routes.py` | 認証・Project・TargetProfile API |
| `backend/app/models.py` | SQLAlchemyモデル |
| `backend/app/schemas.py` | 入出力型、入力検証 |
| `backend/app/security.py` | パスワード、セッション検証 |
| `backend/app/cli.py` | 非公開のユーザー作成手順 |
| `backend/app/config.py` / `database.py` | 環境設定、DB接続 |
| `backend/migrations/versions/*` | スキーマ・初期データMigration |
| `backend/migrations/data/0002_system_profiles.json` | 業種ごとの初期設定 |
| `frontend/src/App.tsx` | ログイン・一覧・画面切替 |
| `frontend/src/forms.tsx` | プロジェクト・プロファイルの作成・編集 |
| `frontend/src/api.ts` | 共通APIクライアント、セッション切れ処理 |
| `backend/tests/*` / `frontend/tests/*` | API・CLI・ブラウザテスト |
| `compose.yaml` / `.env.example` | ローカルDB、設定例 |
| `.github/workflows/ci.yml` | 継続検証 |
| `README.md` | 起動、ユーザー作成、API、Migration、検証手順 |

## 3. DBテーブル

- `users`: メール、ハッシュ化パスワード、作成・更新日時
- `projects`: 所有者、TargetProfile、営業目的、地域、状態
- `target_profiles`: 所有者、検索条件、評価条件JSON、AI指示、標準・有効フラグ
- `auth_sessions`: トークンのSHA-256、所有者、有効期限
- `alembic_version`: Migration管理用

`docs/04_DATABASE_DESIGN.md`にある`companies`、`collection_jobs`、`activities`は
後続Phaseのデータです。Phase 1を越えないよう、今回は作成していません。
`auth_sessions`はログアウトによる即時失効のための補助テーブルです。

## 4. API一覧

| Method | Path |
| --- | --- |
| GET | `/api/health` |
| POST | `/api/auth/login` |
| POST | `/api/auth/logout` |
| GET | `/api/auth/me` |
| GET / POST | `/api/projects` |
| GET / PUT / DELETE | `/api/projects/{id}` |
| GET / POST | `/api/target-profiles` |
| GET / PUT / DELETE | `/api/target-profiles/{id}` |
| POST | `/api/target-profiles/{id}/clone` |

health / login / logout以外は認証必須。User登録はCLIで行います。
Projectのstatusは`draft` / `active` / `archived`としました。
標準プロファイルは共有の読み取り専用設定で、複製後に自由に編集できます。
案件別の条件は、複製したTargetProfileを案件に割り当てて上書きします。
業種スコアの実行処理や外部AI呼び出しは実装していません。

## 5. 画面一覧

- ログイン（認証失敗・セッション切れ表示）
- Project一覧、作成、編集、削除確認
- TargetProfile一覧、作成、編集、複製、削除確認
- データ読み込み中・空一覧・通信エラー・再読み込みの表示

デスクトップ・モバイル双方に対応しています。

## 6. テスト結果

| 検証 | 結果 |
| --- | --- |
| Frontend typecheck | 成功 |
| Frontend ESLint | 成功 |
| Frontend production build | 成功 |
| Backend import check | 成功 |
| Backend Ruff lint / format | 成功 |
| PostgreSQL API・CLIテスト | 20 passed |
| Playwright E2E（desktop / mobile） | 2 passed |
| Migration upgrade → downgrade → upgrade（専用テストDB） | 成功 |
| Migration upgrade再実行、モデルとの差分検査 | 成功、差分なし |
| Uvicorn起動、`GET /api/health` | 成功、HTTP 200 |
| 実画面のスクリーンショット確認 | 実施 |

APIテストでは、他ユーザーのデータの読取・変更・削除・参照を拒否すること、
セッションの期限・再ログイン・ログアウト、入力検証、削除制約、
SQLインジェクション文字列、DB障害時の機密情報非表示を検証しました。
CLIはユーザー作成、重複拒否、短いパスワード・確認不一致の拒否を検証しました。

ブラウザでは実際のAPIとDBを使い、認証、複製・編集・新規作成・削除、JSONエラー、
案件作成・編集・再読込での永続化・削除、ログアウトを検証しました。
検証中に見つかったselectのラベル関連付けを修正後、両デバイスで再実行して通過しました。

Starlette依存側からhttpxとAnyIO APIに関する非推奨警告が2件あります。
テスト失敗はありません。GitHub Actionsは定義済みで、リモート実行は未確認です。

## 7. 残課題・運用準備

- 使用するアカウントはREADMEのCLIで発行してください。共通初期パスワードはありません。
- 本番公開・リモートDBへの適用は行っていません。本番ではHTTPS、Secure Cookie、
  CORS、リバースプロキシの認証レート制限を設定してください。
- Phase 1の開発環境・自動テストまで検証済みです。実ユーザーによる受入確認は未実施です。

## 8. 次のPhase

Phase 2でSerper、Google Places、URL登録、CSVインポート、Collection Job管理を実装します。
今回の変更には含めていません。Web解析はPhase 3、AI判定はPhase 4です。
