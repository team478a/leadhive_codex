# G1.5 固定commitのWindows配布候補

2026-10-03 / codex/integration。

本工程はG1.1〜G1.4のレビュー、工程別ローカルcommit、最終回帰、固定commitの配布候補作成まで。3社への導入完了ではない。push、deploy、外部API利用、実メール・実フォーム送信は実施していない。A2 Human Approvalを維持し、A3 Dispatchや自動運用は開始していない。

## 工程別commit

基準は `f5885b7707536b4b7a7d8f50edeb724430933c58`。以下は同一branch上の順序。

| commit | 内容 |
| --- | --- |
| `8ae81e27b5465464ee747208c38d7aafb267848a` | Governance方向修正、3社専用環境の提供範囲 |
| `2a8abbc7a57775e52beee0e347b67215c8dd15bc` | 固有instance/volume/key、旧環境の検証付き引継ぎ |
| `87bf2b6d6312bf62e9b1d2d51e9b1217faf7a197` | 固定commit配布、backup検証、隔離DB復元、保守停止 |
| `5d6e039d5c94b35c338c2e9357c27065f509f5a7` | 収集を維持した送信OFF、API/worker/送信直前guard |
| `62f7e0584f9bb10df407a877bb051ce12fd3fa86` | 3社受入記録、初心者ガイド、配布物の検査 |
| `f52608ee2e809a1cc2ddd1de21f7a0fbbf5fc0ce` | Importの設定書込前に設置先とinstanceをロック |

本書追加後の配布元commitはZIP内の `VERSION.txt` とローカル `dist/G15_RELEASE_CANDIDATE_VALIDATION.json` に記録する。本書に自分自身のcommit/hashを埋め込まず、成果物作成後の検証記録を正本とする。G1.1〜G1.4文書の「未commit」は各工程を実施した時点の記録。

## レビューで解消した問題

新PCへのImportが保守ロック取得前に設定を書き込む競合を修正した。未設定の設置先でもenvパスから共通ロックを取得し、次に元instance IDのロックを取得する。別bundleの同時Importも同じ設置先で直列化する。取消・例外時にもロックを解放する。競合試験と書込順序の検査を追加した。

既存Migrationの内容・revision chain・Modelは変更していない。Ruff確認のため作業コピーの改行をGit管理内容へ揃え、Git上のMigration差分がないことを確認した。

## 最終確認

最終コードの内容を維持して工程別にcommitした。以下はローカルで実行した結果。

| 確認 | 結果 |
| --- | --- |
| Backend pytest | 243 passed |
| Backend Ruff check | PASS |
| Backend Ruff format --check | 158 files / PASS |
| Windows PowerShell試験 | 51 passed |
| Frontend typecheck / lint / build | PASS |
| Playwright desktop/mobile | 6 passed（承認・Form Intelligence・基本業務） |
| Migration | 専用破棄可能DBでupgrade → downgrade base → upgrade → alembic check / PASS |
| API起動 | E2E用テストAPIで確認 |

Migration試験DBは `leadhive_g15_migration_5afcb94c_test`。稼働DBを変更していない。試験用PostgreSQLは終了した。外部送信はテストダブルまたは送信OFFで検証した。

GitHub Actionsは未実行。ローカルの成功をremote CI成功と扱わない。PowerShellのDocker試験にはmockを使っている。実Docker Engineを用いた新規導入・更新・復元・移設試験は未実施。

## 配布候補の作成・検査

cleanなcommitから `scripts/package-windows.ps1` でGit archiveを作成する。ZIPには固定commit、SHA-256 manifest、checksum、初心者ガイド、ダミーCSVを含める。内部の全社導入台帳・受入結果、環境設定、秘密情報、DB dumpを含めない。

作成後、ZIPを別ディレクトリへ展開して `Assert-LeadHiveRelease` でmanifestと固定commitを検証する。送信guard・復旧処理・送信停止コマンド・初心者ガイド・サンプルCSVの存在、内部記録票の非同梱、ZIP checksumを確認する。検証結果と正確なartifact名/hashは `dist/G15_RELEASE_CANDIDATE_VALIDATION.json` に保存する。`dist` はGit管理外。記録が成功を示すまでは配布作成完了と扱わない。

## 残る提供gate

1. 提供元の専用Windows/VMで実Dockerによる新規導入・更新・失敗時停止・復元・移設を検証する。
2. 3つの独立OS/VMでinstance/volume/key/管理者の非共有を確認する。同一PCのフォルダー違いをtenant隔離としない。
3. remote CI確認とA社pilotの受入後、B社・C社へ順に進める。

具体的な受入項目は [G1.4受入手順](G14_THREE_COMPANY_ACCEPTANCE.md)。記録票は引き続きNOT_RUN。現在の成果物は **RELEASE CANDIDATE / 実機受入待ち**。送信はOFF、AgentはOFFを維持し、資格情報や送信機能の有効化を本工程に含めない。
