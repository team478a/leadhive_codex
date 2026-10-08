# Phase 2 実装記録

検証日: 2026-09-19

## 1. 実装範囲

- SerperによるGoogle検索
- Google Places API (New) Text Search
- URLの複数直接登録
- UTF-8 CSVインポート
- Company / CollectionJobモデルとMigration
- 収集開始・終了・外部APIエラーのログ
- プロジェクト所有者に限定した企業・ジョブAPI
- 同一プロジェクト内の重複排除
- 企業収集画面、保存件数・重複件数・エラー件数・ジョブ履歴表示

Phase 3のWeb取得・本文解析・SNS抽出・問い合わせ先抽出、Phase 4のAI判定、
Phase 5の営業リスト・企業詳細・CSV出力は実装していません。

## 2. 旧版からの扱い

旧版の`serper_search.py`と`google_places.py`を参照しました。
組織設定、暗号化設定、旧DBモデルなどV2に不要な依存は持ち込まず、Providerを新規実装しました。
Google Placesは旧版のLegacy APIではなく、POST・FieldMaskを使うPlaces API (New)へ更新しています。
旧EC判定への依存はありません。

## 3. DB

### companies

- `id`, `project_id`
- `company_name`, `website_url`, `domain`
- `address`, `phone`, `email`
- `source`, `source_keyword`, `status`
- `created_at`, `updated_at`

同一プロジェクト内の`domain`と`website_url`に一意制約を設定。
住所がある場合は`company_name + address`にも部分一意Indexを設定しています。
別プロジェクトでは同じ企業を登録できます。

### collection_jobs

- `id`, `project_id`, `source`, `keyword`, `region`, `status`
- `found_count`, `saved_count`, `duplicate_count`, `error_count`
- `error_message`, `created_at`, `finished_at`

状態は`running`、`completed`、`failed`。件数は0以上のDB制約があります。
Project削除時は関連するCompanyとCollectionJobをDBのCASCADEで削除します。

## 4. API

| Method | Path | 内容 |
| --- | --- | --- |
| GET | `/api/projects/{id}/companies` | 収集済み企業一覧 |
| GET | `/api/projects/{id}/collection-jobs` | ジョブ一覧 |
| GET | `/api/collection-jobs/{id}` | ジョブ詳細 |
| POST | `/api/projects/{id}/collection-jobs/search` | Serper / Places検索 |
| POST | `/api/projects/{id}/collection-jobs/urls` | URL直接登録 |
| POST | `/api/projects/{id}/collection-jobs/csv` | CSVアップロード |

すべて認証必須で、Project所有者だけが利用できます。
検索は1〜20キーワード、キーワードごと1〜100件です。PlacesはAPI仕様上最大60件です。
URL直接登録は最大100件。CSVは5MB、1000行までです。

## 5. エラー処理

- APIキー未設定、HTTP障害、JSON応答異常を外部APIエラーとして分離
- APIキーや外部応答本文をログ・画面へ出さない
- 外部API失敗時もCollectionJobを`failed`として完了
- CSVの列不足、文字コード、容量、拡張子、行ごとの不正URLを検証
- 不正行は`error_count`、同一企業は`duplicate_count`として記録

## 6. 検証

- API・CLI・収集サービステスト（32件成功）
- Providerのリクエスト形式・レスポンス変換をモックで検証
- URL正規化、IDN、CSV解析、容量・文字コード制限
- プロジェクトをまたぐ登録と、同一プロジェクト内の重複排除
- 他ユーザーのCompany / CollectionJobへのアクセス拒否
- Project削除時の関連データ削除
- デスクトップ・モバイルのブラウザ操作（2件成功）
- typecheck、ESLint、production build、Ruff、import check
- Migration upgrade / downgrade / upgrade、モデルとの差分検査
- Uvicorn起動とhealth check

外部APIの実キーは開発環境に設定していないため、有料APIへの実リクエストは行っていません。
Provider契約はモックで検証し、APIキー未設定の運用画面をブラウザで確認しています。

## 7. 次のPhase

Phase 3でWebスクレイピング、企業情報抽出、SNS・問い合わせ先抽出、
より詳細なドメイン正規化と重複判定を実装します。
