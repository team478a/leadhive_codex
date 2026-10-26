# 223 複数プロジェクト収集の並行実行

作成: 2026-10-26。開始SHA: `81e15edbd454d60b35168d940408ccb9e8d8591d`。

## 変更

- 配布版の`worker-collect`を`LEADHIVE_COLLECT_WORKERS`で増減可能にし、既定2個とした。通常workerは収集を扱わず、収集workerは`collect_search`以外を含む設定なら起動を拒否する。
- `host_access_slots`を追加し、同一サイトへの1秒間隔を全processで共有した。予約後の待機中はDB接続を保持しない。30秒を超える候補は`RETRY_HOST_RATE_LIMIT`として保存し、DB障害時はprocess内制御へ退避する。1日以上古い予約は定期清掃する。
- Serperを既定2回/秒、gBizINFOを既定1回/秒で全worker合計に制限した。既存の429再試行情報は維持し、直近24時間の429件数を実行環境へ追加した。
- worker heartbeatへ対象・除外処理種別を保存し、管理画面で複数workerを区別する。収集待ちは全プロジェクトの登録順による順位を表示する。
- 起動時にworker数と各processのpool上限からDB接続需要を見積もり、`max_connections`超過時は警告する。候補取得threadは共有予約の短い接続以外にDB sessionを持たない。

## 安全境界

- 同一プロジェクトの収集は既存の`uq_operation_jobs_active_project_type`により1件だけである。
- 送信、承認、送信可否、予約、検索上限、総上限、continuation、leaseの契約は変更していない。通常workerは1個のまま。
- browser workerは既存のPostgreSQL advisory lockと`pg_sleep(1)`による別の同一サイト間隔を持つため、本変更の共有表には接続していない。
- migrationは`224a00000001`の1件だけ。本番設定は変更していない。

## 実行環境判断

第1部のローカル診断はDocker Desktop 8 CPU・約7.6GiB、PostgreSQL `max_connections=100`、API約140MiBだった。各processのpool既定2・overflow 0を維持し、収集workerは2個から開始する。本番では反映後に管理画面の実測を確認し、2個を超えて増やす前にCPU・メモリ・DB接続・429件数を確認する。

## 検証

- 合成データと専用PostgreSQLだけを使用する。実サイト、実Serper、実gBizINFO、送信は使用しない。
- 共有サイト間隔、別サイト非待機、30秒超の後回し、DB障害時fallback、API全体上限をテストする。
- 2 workerが別プロジェクトを同時取得し、同一プロジェクトの重複を既存制約が拒否すること、収集workerが送信処理を扱えないことをテストする。
- 管理者診断、heartbeatの処理種別、待機順位、migration、Compose、バックエンド、フロントエンドの標準検証を実行する。

## マージ後の確認

1. 管理画面の「運用設定」→「実行環境」で収集workerが2個表示されることを確認する。
2. 2プロジェクトで収集を開始し、両方が実行中になることを確認する。
3. 1〜2時間後に各プロジェクトの直近50検索、workerのCPU・メモリ、DB接続、Serper 429を記録する。
4. worker数を増やす場合は、上記実測を確認してから`.env.local`の`LEADHIVE_COLLECT_WORKERS`を変更して再起動する。
