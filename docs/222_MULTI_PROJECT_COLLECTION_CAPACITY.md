# 複数プロジェクト収集：実行環境調査（第1部）

## 状態

- 調査日: 2026-10-26
- 開始SHA: `e1e172bcaa78f557b9c31324cfbcc468db5839de`
- ブランチ: `codex/multi-project-capacity`
- 指示書の前提である「フォーム中心の収集を速くする」変更は `origin/main` に未マージだった。
- 指示どおり第1部だけを実装した。複数収集worker、プロセス間ホスト間隔、外部APIの全体レート制限など、第2部には着手していない。
- DB migration、送信・承認・送信可否、本番設定は変更していない。

## 追加した診断

- 管理者専用 `GET /api/admin/runtime-capacity`
  - 直近5分のworker heartbeat、版、ホスト、実行中のOperationJobとプロジェクト
  - OSから見たCPU数、cgroup CPU上限、cgroupメモリ上限・使用量
  - PostgreSQLの `max_connections`、`shared_buffers`、現在の接続数、DB容量
  - APIプロセスの `DATABASE_POOL_SIZE` / `DATABASE_MAX_OVERFLOW`
  - 直近24時間の仕事種類別件数、合計実行時間、平均待ち時間
- 管理画面の「運用設定」に「実行環境」を追加した。
- `Diagnose-LeadHive.ps1` にLeadHiveコンテナの `docker stats --no-stream` と、APIコンテナ内で生成する同じ診断要約を追加した。
- OperationJobの実行記録にworker instance IDを保存し、実行中の仕事をheartbeatへ対応付けられるようにした。
- APIレスポンスと診断要約には、DB接続文字列、パスワード、APIキーを含めない。

`WORKER_OPERATION_TYPES` / `WORKER_EXCLUDE_OPERATION_TYPES` は前提PR側の設定であり、現在の `origin/main` には存在しない。そのため第1部の画面は未記録として表示する。前提PRのマージ後、第2部でheartbeatへの永続記録を接続する。

## 2026-10-26のローカル調査

- OS: Windows 11 Home 10.0.26300
- 物理メモリ: 15.6GB
- Docker Desktop: 8 CPU、約7.6GiBメモリ
- 稼働中のローカルLeadHive DB: `max_connections=100`、`shared_buffers=128MB`、確認時7接続、DB容量11MB
- 確認時のローカルLeadHive API: 約140MiB
- 確認時は収集workerが起動していなかったため、収集中、および収集＋サイト解析中のworker実測値は未取得

## 暫定判断

- DB接続上限だけを見ると、既定pool 2・overflow 0で収集worker 2個を追加しても余裕がある。
- Docker Desktopへ約7.6GiBが割り当てられているため、まず収集worker 2個から始める方針は妥当。ただし収集中のworkerメモリ実測がないため、2個を超える推奨はしない。
- `DATABASE_POOL_SIZE=2` / `DATABASE_MAX_OVERFLOW=0` とPostgreSQL `max_connections=100` は現時点で変更不要。
- Docker Desktopの推奨メモリは当面8GB。収集とサイト解析を同時に動かした `docker stats --no-stream` を採取してから増減を判断する。
- 本番環境のサービス名・プラン・実測値は未共有のため、本番のworker数はまだ判断しない。

## 本番で確認する手順

1. この第1部を反映後、管理者で「運用設定」→「実行環境」を開く。
2. worker数、最終heartbeat、CPU・メモリ上限、DB接続数を記録する。
3. 収集中に1回、収集とサイト解析が両方動いている時に1回更新し、数値を記録する。
4. Windows配布版では `Diagnose-LeadHive.cmd` も実行し、生成ファイルの `Windows`、`Docker engine`、`LeadHive container CPU and memory`、`LeadHive runtime capacity summary` だけを共有する。
5. 本番がクラウド/VPSの場合は、サービス名とプランも共有する。

## 検証

- backend対象テスト: `6 passed`
- Ruff lint / format: 成功
- frontend ESLint: 成功
- frontend TypeScript / Vite build: 成功
- PowerShell構文解析: 成功
- 診断CLIのJSON生成と秘密語の非包含: 成功
- backend全体テストも実行したが、差分と無関係な実プロセス試験 `test_parallel_workers_post_only_once` が子プロセスの20秒待機上限を超えて停止した。単独再実行でも同じタイムアウトを再現した。今回の変更対象テストには失敗なし。

## 次の開始条件

「フォーム中心の収集を速くする」PRが `origin/main` にマージされた後、最新mainから第2部用の専用worktreeを作り直す。前提PRのworker絞り込み、`worker-collect`、所要時間記録を確認してから、複数workerとDBベースのホスト間隔を実装する。
