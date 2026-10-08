# G1.6 Windows Docker実行確認

2026-10-03 / codex/integration。

## 対象・範囲

配布候補 `8757c1e9824c278e938e9612c2bdb3dcbf277d6c` を実Dockerで検査し、Windows起動処理の不具合を発見した。修正版の対象commitは `188a2eb0a03c75bba90c7b7fb851ecabf436c74b`。

本試験は提供元の既存Windows PC上で行った。専用VM・新規PCでのインストーラー全体、3社独立OSでの非共有、利用者署名は未実施。単一ホスト内の独立Compose/volumeはtenant隔離の証明ではない。

Docker Desktopを起動したところ、既存LeadHiveもrestart policyによって起動した。既存worker `leadhive-worker-1` は試験中のジョブ実行を防ぐため停止した。既存DB/volume/環境設定は変更していない。既存workerの自動再開は行わない。

## 発見した不具合と修正

`Invoke-LeadHiveCompose` はPowerShellのcommon parameterを持つため、位置引数の `up -d api web` では `-d` がPowerShellの `Debug` と解釈され、Dockerへ渡らない。実際のDockerプロセスは `up api web` となり、起動後にattachしてinstaller/maintenanceが終了しない。

Start、Install、Import、Maintenance、Resumeの全detach呼び出しを `-ComposeArguments @('up', '-d', ...)` に変更した。Migration・Model・API・Human Approvalに変更はない。

Windows PowerShell試験は **53 passed**。実際の引数binding経由でDocker mockへ `-d` が渡ること、production scriptに位置引数のdetach呼び出しが残らないことを追加検証した。Backend/Frontendコードは変更していないため、G1.5の既存回帰結果は履歴として参照し、本工程で再実行したと扱わない。

旧ZIP `LeadHive-Windows-Local-8757c1e9824c.zip` は提供に使わない。

## 修正版配布候補

- ファイル: `dist/LeadHive-Windows-Local-188a2eb0a03c.zip`
- 固定commit: `188a2eb0a03c75bba90c7b7fb851ecabf436c74b`
- SHA-256: `4a78e1b3536c2f4f9f91a924941672d7bc2568e841525a320da331f7cc706b95`
- `scripts/package-windows.ps1` によるGit archive、manifest全件、必須ファイル、PowerShell parse、Compose config検査: PASS。
- remote CI、push、production deployment: 未実施。

## 実Docker試験の隔離

既存のlegacy volumeを検知し、`New-LeadHiveEnvironment` が新規導入を拒否することを確認した。既存の秘密情報を使って自動Adoptしない。

試験fixtureにはランダムな新規ID・volume・暗号化キー・DB passwordを生成し、productionのRegister/Assert境界で登録した。localhostの別ポートを使用。Agent OFF、送信OFF、worker pause、実provider/SMTP設定なし。

配布ファイルは固定commit/manifestを維持する。試験harnessがCompose overrideでdefault networkを `internal: true` にし、API/worker/DBの外部通信を遮断する。Docker Desktopでinternal networkだけではlocalhostの公開ポートに届かなかったため、画面用Nginxだけを追加のingress networkへ接続した。API/worker/DBはinternal networkのみ。これは試験専用overrideであり、配布版の通信設定変更ではない。runtime確認にはZIP作成と同じmanifest付きstageのコピーを使用し、完成ZIPは別途packagerが全件検証した。

ダミーfixtureのみを使う。実際の承認操作や外部送信をharnessが代替しない。DBへ投入する失効確認用のsession/Agent credential/PENDING requestは実認証・実送信に利用しない。

## 実行結果

修正版の固定commit/manifestを検証し、以下を実Dockerで確認した。

| 項目 | 結果 |
| --- | --- |
| Docker build / Migration | PASS（固定commitのbackend/frontend） |
| production Startコマンド | PASS（detachが維持され、起動後に返る） |
| localhost /api/health | PASS（status=ok、database=ok） |
| Agent / 送信フラグ | OFF（実行中APIのSettingsで検証） |
| executor network | API/DBはinternal networkのみ（Docker inspectで検証）、workerは停止 |
| Backupコマンド | PASS（dump/env/identity、42テーブルのfingerprint、ダミー暗号化設定） |
| 隔離DB復元 | PASS（復元前後の42テーブルfingerprint一致、upgrade/check成功） |
| 元DB保持 | PASS（`leadhive_v2` を残し、別DBへ切替） |
| 復元後データ | 企業1件・連絡禁止・ダミー設定の復号を確認 |
| 認証/承認失効 | session期限切れ、Agent credential revoked、PENDING request → REVOKED |
| immutable payload | payload snapshotからのhash一致、version=1維持 |
| Audit Ledger | 元のHUMAN proposalを保持し、SYSTEMの復元取消・全体認証失効を追記（計3件） |
| 保守状態 | maintenance=false、送信OFF、worker pause=true、稼働test workerなし |
| 終了処理 | 試験用api/web/dbを停止。ダミーvolume/元DB/復元DBを保全 |

試験fixture IDは `0ba0112bfde841418a120b1dae7a6137`、復元DBは `leadhive_recovery_9286715ad7304ce5afdc5b39a88b2002`。結果はGit管理外の `dist/G16-runtime/result.json`、harnessは `dist/g16-runtime.ps1` / `dist/g16-final-verify.ps1` / `dist/g16-fixture.py`。秘密情報は結果JSONへ記録していない。backup bundleのenvはダミー設定でも秘密として保管し、配布しない。

試験側で台帳を2件と仮定して一度停止したが、実装は復元取消と全体認証失効の両方を記録するため3件が正しい。コードを変えず、件数・イベント内容・payload保全を再検証して成功した。Python `-c` のWindows quotingも試験harness側を修正した。これらは配布版の不具合修正ではない。

Human ApprovalProofの非空fixture、APPROVED状態の復元、送信待ち・job再開等をこの実Docker試験で新たに網羅したとは扱わない。G1.5やnative/mocked試験と区別し、専用OS受入に残す。

判定: **修正版の起動・Backup・隔離復元スモーク確認完了 / 専用OSでの全体受入待ち**。実企業へのアクセス、実送信、test email/form、production deployment、pushは行っていない。既存workerは停止したままなので、既存環境で収集を再開する前に当該環境の設定・待機ジョブを確認する。

## 残る受入gate

- 専用の新規Windows/VMで、Docker/WSL導入、再起動、初回管理者作成を含むinstaller全体。
- 旧環境の確認付きAdopt/更新、失敗からの復旧、別OSへのImport/移設。
- 3つの独立OSでのデータ・キー・volume・管理者非共有と各社20項目の受入/署名。
- remote CIとA社pilot。

本工程で3社の台帳/受入票をPASSに変更しない。実Serper/Places/AI/IMAP品質・Phase 6実データ、送信有効化、A3 Dispatch、AutomationPolicy、Dots接続も範囲外。
