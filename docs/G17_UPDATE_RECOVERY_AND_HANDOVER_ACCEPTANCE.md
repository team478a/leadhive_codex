# G1.7 更新失敗・再開・移設境界の受入確認

2026-10-03 / codex/integration。

## 対象

固定commit `188a2eb0a03c75bba90c7b7fb851ecabf436c74b` の配布候補を対象に、G1.6の独立ダミーDocker環境で確認する。既存業務DB・既存workerは操作しない。送信OFF、Agent OFF、API/worker/DBは外部へ出られないinternal network、Nginxのみlocalhost公開用ingress。

本工程は受入試験と手順整理。productionコード・API・Model・Migration・UIに変更はない。実メール/フォーム、provider API、Dots接続、deployment、pushを行わない。

## 結果

| 項目 | 判定 | 確認内容 |
| --- | --- | --- |
| 更新失敗時の停止 | PASS | ダミー環境のMigration呼出しにexit 77を注入。api/web/worker停止、maintenance=true、worker pause、送信OFF |
| 起動による停止解除の拒否 | PASS | production Startコマンドが未完了保守を拒否 |
| 更新失敗時のDB保全 | PASS | 失敗前後42テーブルのfingerprint一致 |
| 更新再実行 | PASS | 同じ配布候補のUpdate処理を再実行、Migration/check、health成功 |
| 再実行後のDB保全 | PASS | DB切替なし、42テーブルfingerprint一致、worker pause、送信OFF |
| 既存環境へのImport | PASS（拒否） | 完成ZIPを新しい空フォルダーに展開し、production Importで拒否。環境ファイルは作られない |
| 送信待ちを残した収集worker再開 | PASS | 送信OFFの実workerを起動。queued form operationのstatus/attempt_count/worker_idが変わらない |
| 送信停止コマンド | PASS | production StopOutbound後、送信OFF・worker pause・maintenance=false |
| 終了処理 | PASS | 試験用api/worker/web/db停止、volume・backup保全 |

Updateの試験はproduction scriptをharnessで読み込み、Commonの参照先を固定したうえで実行した。ただし既存利用者の個人Skillを上書きしないため `Install-LeadHiveCodexSkill` だけ除外した。Migration失敗だけはharnessで注入し、それ以外のDocker build/backup/DB/health/停止は実Docker。実際に失敗する新Migrationを追加したり、DBを破壊したりしていない。

Update成功は同じ候補commitの再実行であり、旧schemaから新schemaへのupgrade互換性を新たに証明したものではない。新規Skill導入・旧版Adoptの実Docker確認も未実施。

Import拒否は、同じホストにsource IDのvolumeとlegacy volumeが存在する場合の保護確認。別OSへの正常なImport成功とは区別する。source volumeや既存legacy volumeを削除して試験を無理に通さない。

記録はGit管理外の `dist/G17-acceptance/update-recovery.json` / `import-guard.json` / `resume.json`。harnessは `dist/g17-acceptance.ps1` / `g17-pending-job.py`。結果票には秘密情報を保存しない。

Resumeの確認入力は、実業務ではないダミー環境の試験harnessで供給した。A2のHuman Approvalやstep-upを代替したものではない。worker起動後12秒待ち、実workerのSettingsで送信OFF/Agent OFF/worker pause解除と、DBのqueued form operationの試行回数0・worker未割当を検証した。その後production StopOutbound、最後に全試験サービス停止を実行した。実providerを使う収集や送信成功の試験ではない。

Backend/Frontendのコードは変更していないため、G1.5/G1.6の回帰テストは履歴として参照する。本工程で243件/53件/6件を再実行したとは報告しない。配布候補も更新不要で、G1.6の `188a2eb` ZIPを継続利用する。

判定: **このPCで実施できる更新失敗・再実行・既存環境への移設拒否・送信OFFでのworker再開は確認完了**。新規PC/別OSでの正常Importとinstaller全体は未実施。3社へ提供済み・全受入完了とはしない。

## 次の専用Windows/VM受入手順

1. 業務データ・既存LeadHive・既存volumeのない専用Windows PC/VMを用意する。同一PCの別フォルダーを別企業の隔離にしない。
2. `LeadHive-Windows-Local-188a2eb0a03c.zip` と `.sha256` を渡す。PowerShellの `Get-FileHash -Algorithm SHA256` が `4a78e1b3536c2f4f9f91a924941672d7bc2568e841525a320da331f7cc706b95` と一致することを確認する。旧ZIP `8757c1e` は使わない。
3. ZIPを展開し `Open-QuickStart.cmd` を読む。実APIキー・SMTP/IMAP設定を入れず、`Install-LeadHive.cmd` を実行する。Docker/WSL導入の同意・管理者操作・再起動が必要なら端末のHuman管理者が行う。再起動後は同じフォルダーで再実行する。
4. 初回管理者を作成し、ログイン・送信停止表示・ダミーCSV2社取込・再取込重複防止・A2承認/取消を確認する。承認後も送信しない。送信停止・Agent OFFを維持する。
5. `Backup-LeadHive.cmd` 後、dump/env/identityの3点を同じ安全な保管場所へ保存する。秘密を含むenvやbundleをチャット・全社共通資料へ貼らない。`Resume-LeadHive.cmd` は待機ジョブを確認して収集のみ再開する。
6. 更新・失敗時停止・隔離復元をダミーデータで実施する。元DB・元env・元キーを保全し、factory reset、volume削除、キー再生成を復旧方法にしない。
7. 別の空の専用OSで移設試験を行う。元PCのapi/worker/web/dbが停止したことを確認してから、backupの3点を安全に移し、`Import-LeadHiveBackup.cmd` にdumpを指定する。復号・内容・認証/承認失効・送信OFF・worker停止を確認する。元PCと同じinstanceを同時運用しない。
8. 失敗した場合は元PCとbackupを保全し、移設先を停止する。元PCへ戻す前に移設先が動いていないことを確認する。自動再開・同時稼働をしない。
9. 全項目の証跡・実施者・日時を [3社受入票](acceptance/THREE_COMPANY_ACCEPTANCE_RESULTS.csv) に記録する。提供元検証の成功をA/B/C社のPASSに転記しない。A社pilotの責任者確認後、B/C社へ順に進める。

## 完了と残課題の区別

既存Windows PC上の隔離Docker試験と、専用の新規Windowsで初心者がinstaller全体を操作する受入は別工程。専用Windows/VMや別OSのDocker接続先は本セッションで確保できていない。全社受入票は引き続きNOT_RUN。

残るものは新規Docker/WSL導入、OS再起動、初回管理者作成を含むinstaller全体、別OSでのImport成功、旧版Adopt/更新、3社の独立OS隔離・利用者実演/署名、remote CI。実providerでの収集品質/速度やPhase 6実データ検証も今回の結果に含めない。
