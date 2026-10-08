# G1.1 専用instance識別・誤接続防止

実装日: 2026-10-03。branch: `codex/integration`。
基準commit: `f5885b7707536b4b7a7d8f50edeb724430933c58`。本変更はローカル作業差分で、commit/push・実環境導入は未実施。

## 完了した範囲

- 新規環境はランダム32桁環境ID、ID由来のCompose名とDB volume名を`.env.local`へ保存する。
- data volumeは事前登録したexternal volumeとし、Composeが別DBを暗黙作成しない。
- Docker側の識別用volumeにはinstance ID、project、data volume、DBパスワード+暗号化キーのSHA-256照合値を登録する。秘密の値は登録しない。
- 共通Compose関数は環境設定、Docker登録、DB container mountを毎回確認。不一致、欠落、検査エラーなら停止する。
- Composeのenv-fileを上書きする継承環境変数も、不一致なら拒否する。
- install/start/stop/update/backup/restoreが共通guardを使用する。updateはSkill配置前にもguardを確認する。
- 初回インストールだけが新規volumeを作成できる。既存envでDB/bindingがなくなった場合、再インストールでも空DBを自動作成しない。
- backupには`.dump.identity.json`を追加し、環境ID、volume、key照合値、dump SHA-256を記録する。
- restoreは対象backup、対応する`.dump.env.local`、現在の環境/Docker登録を復元確認・安全backup・サービス停止より前に照合する。
- 新しい`Adopt-LeadHive.cmd`は元の設定と既存DB containerを照合し、Humanの確認入力後に旧環境を登録する。元キー、DB、稼働サービスは変更しない。
- 既存固定volumeのラベルは変更せず、識別用の空volumeを追加する。DBへの書き込み・Migrationは不要。

## 既存環境の引継ぎ

対応する旧volumeは`leadhive-local-postgres-data`。所有Compose projectは`leadhive`または`leadhive-local`。
DB containerは1件だけで、data mountと元のDB passwordが一致する必要がある。
元の`.env.local`を新版へコピーしてAdoptを実行する。元`.env`を明示指定する方法もWindows導入ガイドへ記載した。
元`.env.local`は`.env.local.pre-identity`に保持する。これも秘密ファイルであり、Git/配布物に含めない。
暗号化キーの元データに対する復号成功はこの照合だけでは保証しない。元キーを保持し、実導入時に別途復号を検証する。

## セキュリティ境界と制限

これは誤接続防止でありOrganization/tenant認可の実装ではない。各社は専用PC/VMで利用する。
同じlocalhostのポート違いはCookie隔離にならないため、複数社の共用構成として提供しない。
Docker管理権限やenvを保有する攻撃者に対する改ざん耐性・backup署名は提供しない。envやbackupは従来どおり機密として保管する。

以下は安全側に停止し、自動修復しない:

- 環境IDなしの通常起動/更新。
- instance ID・設定・volume・container mount・キーの不一致。
- dataまたはidentity volumeの消失、初回登録途中の失敗。
- metadataなしの旧backup、他環境backup、破損dump、対応envの不足。
- 新規PCの未登録環境への単純なenvコピーによる復元。

元の設定/volume/backupを保持して管理担当者が確認する。新規PCへの隔離復元ウィザードやkey rotationはG1.2以降の別工程。
既存送信経路、workerの起動方式、Human Approval A2は変更しない。Agent機能の既定OFFを維持するが、それをHuman配送停止の保証とは扱わない。
復元スクリプトの実DB復元・worker再開安全性はG1.2、全送信停止と収集workerの分離はG1.3で検証・実装する。

## 主要ファイル

- `scripts/windows/InstanceIdentity.ps1`: 設定解析、Docker照合、volume登録、backup identity。
- `scripts/windows/Common.ps1`: 自動legacy検索を廃止、guard、新規ID生成。
- `scripts/windows/Adopt-LeadHive.ps1` / `Adopt-LeadHive.cmd`: 明示的な旧環境引継ぎ。
- `scripts/windows/Install-LeadHive.ps1`, `Update-LeadHive.ps1`, `Backup-LeadHive.ps1`, `Restore-LeadHive.ps1`: 境界接続。
- `compose.local.yaml`: explicit external DB volume。
- `scripts/package-windows.ps1`: 引継ぎcommand/helperの同梱と必須ファイル検証。
- `scripts/tests/instance-identity.tests.ps1`: Docker/DBをmockした隔離テスト。
- `.github/workflows/ci.yml`: Windows isolation testをpackage job前に追加。
- Windows導入ガイド/利用マニュアル/配布README: 新規・引継ぎ・backupの説明。

## 検証結果

| 検証 | 結果 |
| --- | --- |
| Windows PowerShell 5.1 isolation tests | 24 passed。Docker/DBをmock、別会社・キー・mount・継承変数・旧環境確認等 |
| PowerShell構文解析 | 全scriptのparser checkを実行 |
| Backend Ruff lint | pass |
| Python compileall | pass |
| Backend全回帰 | 211 passed、専用`leadhive_a2_regression_test` DB |
| Frontend typecheck/lint/build | pass |
| desktop/mobile E2E | 6 passed、別の専用`leadhive_a2_test` DB、API起動成功も確認 |
| Model/Migration一致 | Backend pytestのfixtureによるAlembic upgrade/check成功。Migration変更なし |
| Windows package | 一時リポジトリで生成、ZIP/hash/manifest/必須script/parser/Compose config検証成功。配布releaseではない |
| git diff --check | pass |

作業コピーのRuff format --checkは、変更していない`config.py`と既存A2 Migrationの混在改行で失敗した。
両ファイルのGit HEAD blobをstdinで検証するとpass。今回Backend/Migrationを変更せず、このローカル改行問題は区別して記録する。
最初の回帰起動では一時PostgreSQLが別portで起動し接続失敗した。15483を明示して再起動し、独立DBで全件再実行して上記passを確認した。
PythonからWindows PowerShellを起動した初回package試験は継承PSModulePathによりGet-FileHash解決に失敗した。Windows PowerShell標準のmodule pathで再実行して成功した。製品scriptには試験launcherの環境差への回避コードを追加していない。

Docker実機上での新規Windows導入、実DB backup/restore、3社端末での受入は未実行。
本稼働DBの変更、SMTP/Form送信、外部サービス疎通、Agent接続、production deploymentは実施していない。

## 次の工程

**G1.2 安全な配布・更新・復元**。clean release固定、backup排他/metadata、隔離DB復元、初回登録失敗の安全復旧、新PC移行、worker再開gateを実装・検証する。
今回G1.2の実装は開始しない。
