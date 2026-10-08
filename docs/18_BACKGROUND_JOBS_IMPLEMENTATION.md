# バックグラウンド処理 実装記録

## 目的

検索収集、複数企業のWeb解析、複数企業のAI判定をHTTPリクエストから分離し、件数が増えても
画面を待たせず、進捗確認・キャンセル・再実行ができるようにする。

## 実装範囲

- PostgreSQL永続キュー `operation_jobs`
- 検索収集、Web解析、AI判定の3処理種別
- 登録、一覧、キャンセル、再実行API
- `FOR UPDATE SKIP LOCKED`で1件ずつ確保する独立ワーカー
- 処理総数、処理済み数、成功数、失敗数、開始・終了日時の記録
- 一括Web解析・一括AI判定の画面登録と2秒間隔の進捗更新
- 失敗理由の安全な表示と、例外内容を含めないユーザー向けメッセージ

URLとCSVの取込は外部通信を伴わず短時間で完了するため、既存の同期APIを維持した。

## 起動

APIとは別のターミナルで次を実行する。

```powershell
backend/.venv/Scripts/python -m app.worker
```

動作確認やプロセス監視からの単発起動には次を使用できる。

```powershell
backend/.venv/Scripts/python -m app.worker --once
```

待機中ジョブがなければ常駐ワーカーは既定2秒で再確認する。`--poll-seconds`には0.5〜30秒の
範囲が実際の待機時間として適用される。

## 状態と障害時の挙動

状態は `queued`、`running`、`completed`、`failed`、`cancelled` の5種類。
待機中のキャンセルは即時終了し、実行中は現在の企業またはキーワードの処理後に停止する。
失敗・キャンセル済みジョブは元の入力を引き継いだ新しいジョブとして再登録する。

同じプロジェクト・同じ処理種別に待機中または実行中のジョブがある場合、APIは409を返す。
外部サービスの失敗は個別件数へ反映し、ジョブは失敗で完了する。予期しない例外はログへ例外型と
ジョブIDだけを残し、画面へ内部例外や機密情報を返さない。

## API

| Method | Path | 内容 |
| --- | --- | --- |
| POST | `/api/projects/{project_id}/operations` | 処理を登録 |
| GET | `/api/projects/{project_id}/operations` | 新しい順に最大100件取得 |
| POST | `/api/operations/{job_id}/cancel` | 待機中または実行中をキャンセル |
| POST | `/api/operations/{job_id}/retry` | 失敗・キャンセル済みを再登録 |

すべて認証必須で、プロジェクト所有者以外からは404として扱う。1ジョブの対象企業は最大100社、
検索キーワードは最大20件に制限する。

## 検証結果

- Ruff check / format
- バックエンドAPI・権限・ワーカー処理テスト 52件
- Alembic downgrade / upgrade / model差分確認
- フロントエンド typecheck / lint / production build

## 今後の運用課題

本番環境ではAPIとワーカーを別プロセスとして常時監視し、異常終了時に再起動する必要がある。
停止ジョブの回収は後続のジョブ回収実装で追加した。外部通知は今回の範囲外。
