# Phase 3: 確認レビューの独立プロセス・障害検証

## 基準・範囲

基準: `main@0b2e2da89203b57d0ee4a95c2d87b0f2b4899937`（PR #32統合後）。ブランチ `codex/confirmation-process-safety`。

既存の管理用確認サービスの行ロック、commit、一回限りのledgerを、独立したPythonプロセスで検証する。変更はテスト2ファイルと文書のみ。本番コード・API・UI・migration・送信契約の変更なし。

## 環境

既存 `test_controlled_form_process.db` fixtureを再利用し、各テストでランダム名の使い捨てPostgreSQL `_test` DBを作成する。既存DBを削除しない。実際にcommitするSessionと独立した接続を使用し、通常テストのnested savepoint内だけで成功した結果とは区別する。

子プロセスには専用DBの接続情報を環境変数で渡す。session hash等の入力はpytestのprivate一時ファイルに置き、CLI引数・stdout・stderr・Git成果物へ表示しない。匿名fixture tokenだけを使用する。`PYTHONPATH`は検証中のcheckoutへ固定し、別checkoutのeditable installを参照しない。

outbound / legacy form deliveryは親子ともOFF。子プロセスは送信transport・workerを起動しない。

## 検証項目

| ケース | 合格条件 |
| --- | --- |
| startの競合 | commit直前で先行processを停止し、後続がPostgreSQL上でLock待機することを観測。解放後は成功1件、409拒否1件、開始ledger1件 |
| recordの競合 | 同じ条件で結果ledger1件。後続は再登録不可 |
| token消費の競合 | 同じ条件で消費ledger1件。後続は再消費不可 |
| startのcommit前process kill | 未commitの開始ledgerなし。別processが開始可能 |
| startのcommit後process kill | 開始ledgerが残り、別processの再開始は409 |
| consumeのcommit前process kill | 未commitの消費ledgerなし。別processが消費可能 |
| consumeのcommit後process kill | 消費ledgerが残り、別processの再消費は409 |
| UNKNOWNの再接続 | 別processでstart / record / consumeすべて409。結果ledgerはUNKNOWNの1件、消費ledger0件 |

競合は単に2プロセスを起動するだけではなく、先行のcommitをファイルbarrierで止め、`pg_stat_activity.wait_event_type='Lock'`を確認してから解放する。子の異常終了・timeout時には全子processを回収する。

全ケースで、新しいSessionからApprovalRequestがAPPROVEDのままであること、ApprovedFormDispatch / FormDelivery / EmailDeliveryが0件であることを確認する。レビューtoken消費をApprovalRequestのCONSUMEDや外部送信と混同しない。

## 限界と残工程

## 検証結果

- 新規processテスト4件と、確認レビュー・承認境界・multipart parserの関連テスト: 59件PASS（74.56秒）。
- Backend全体Ruff / format: PASS（470ファイル）。
- 新規テスト2ファイルのmypy `--check-untyped-defs --follow-imports=silent`: PASS。
- 使い捨てDBのmigration upgrade / Alembic model diff: PASS。
- GitHub Actionsの全体回帰・E2E・migration往復・配布チェックはPRで確認する。

## 限界と残工程

今回実測する再起動はアプリケーションのPythonプロセス終了と新しいプロセス・接続の起動。PostgreSQLサーバー自体の再起動・ストレージ障害・ネットワーク分断は試験しない。

匿名fixtureの結果は実サイトのtrusted responseではない。HTTPへの接続、multipartの二段階実行契約、draft/profile/sender binding、最初のPOST前のrate/safety checks、確認後payload変更時の再承認、最終POSTのUNKNOWN処理は引き続き未実装。既存single-post adapterへ二段階操作を追加しない。

今回のGO対象は管理用非送信レビューledgerの独立process検証だけ。実フォーム送信はNO-GOのまま。

## 安全確認

実サイトGET / POST、検索API、AI API、実営業Human Approval、メール・フォーム送信、送信worker起動、merge/deployは0。使い捨てテストDBの匿名User / Approval / ledgerのみ使用。
