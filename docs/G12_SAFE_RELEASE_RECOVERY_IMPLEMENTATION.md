# G1.2 安全な配布・更新・復元

実装日: 2026-10-03。branch: `codex/integration`。
基準commit: `f5885b7707536b4b7a7d8f50edeb724430933c58`。G1.1に追加するローカル変更。commit/push、本番配布・導入は未実施。

## 完成した範囲

1. 配布はcleanなcommitのみ。変更・未追跡ファイルがあれば拒否し、`git archive`から必要ファイルを取り出す。
2. ZIP名は短縮commit、VERSIONには完全40桁commitを保存。manifest/checksumを検証し、環境ファイル・dumpを除外する。
3. 保守操作はpackage manifestを検査する。実行ディレクトリに未登録ファイルがある場合も停止する。開発ソースを配布物として扱わない。
4. 環境ID単位のWindows global mutexでbackup/update/restore/import/repair/resumeを排他制御する。
5. 保守開始時に永続envのworker pause・maintenance requiredを記録し、api/worker/webを停止する。失敗時はその状態を維持する。
6. backupは停止中にUUID付き固有pathへpg_dumpし、dump/env/identityを一組にする。途中失敗したdumpは`.incomplete`にし、通常選択から除外する。
7. G1.2 metadataはformat 2。環境ID、キー照合値、dump SHA-256、検証ツールのrelease commit、DB名、schema revision、全テーブル件数・内容ハッシュを記録する。
8. restoreは新規DBへpg_restoreする。元DBへ`--clean`を実行しない。内容ハッシュ一致、秘密情報の復号、Migration upgrade/check後に復元した認証・承認を失効し、新DBを採用する。
9. 復元・migration・検証失敗時は元DB名に戻す。元DB、失敗した隔離DB、backupを残し、サービスを自動再開しない。
10. 正常終了後はapi/webだけ再開。worker pauseは通常Start/Installにも引き継ぐ。worker自身もpause時にDBを開かず停止する。
11. 明示的なResumeでは未処理/失敗配送・campaign/batchを検査し、該当があれば拒否する。ゼロ件でもHumanの確認文字列と再検査が必要。
12. 新PC Importは検証済みbundle、元PC停止確認、環境ID/キー保持、新規DB検証を必須とする。同じ未完了環境のretryだけ許可する。
13. 初回identity登録の失敗は、残存volumeのinstance/security labelが一致する場合だけRepairで完了できる。秘密や業務データは作り直さない。

## 追加・変更した境界

- `backend/app/maintenance.py`: read-only DB報告・秘密復号検査・再開blocker集計。送信executorや外部Providerを呼ばない。
- `backend/app/maintenance_recovery.py`: 隔離復元DBのみでsession/challengeを失効、Agent credentialを失効、PENDING/APPROVEDをREVOKEDにする。既存のsnapshot/hash/承認者・承認日時は保持し、SYSTEMの失効イベントを同一transactionへ追加する。
- `backend/app/config.py` / `worker.py`: WORKER_PAUSEDでmain/run_onceを停止する。
- `compose.local.yaml`:接続DB名を環境で選択し、workerへpauseを渡す。data volume/instanceはG1.1のまま。
- `scripts/windows/Maintenance.ps1`: lock、atomic env更新、release検証、backup、隔離復元、再開前検査。
- Update/Backup/Restore/Start/Install:保守状態を引き継ぎ、失敗後の通常起動とworker自動再開を防ぐ。
- Import/Repair/Resumeの3 commandとPS1を追加。packageへ同梱する。

DB Model、Migration、API、Human Approvalの通常操作、Agent scopes、SMTP/Form executorは変更しない。復元時だけ古い認可を無効化する。
Agent OFF既定を維持。G1.3の全送信経路guard・収集workerと送信の分離は実装していない。

## 保守フロー

### Update

instance/release検査 → lock → pause永続化 → api/worker/web停止 → build → safety backup → migration → model差分check → api/web再開・health → maintenance required解除。
workerは明示Resumeまで停止。失敗した場合、再Updateまたは検証済みbackupと適切な旧packageによる復旧へ進む。

### Backup

instance/release検査 → lock → 全アプリ停止 → dump/環境/報告 → api/web再開。
業務停止を伴う。G1.2ではオンラインbackupや自動worker再開にしない。元データの静止状態を前提とし、外部DB管理者による同時書き込みは許可しない。

### Restore

instance/bundle検査 → Human確認 → lock・再検査 → 停止 → safety backup → 新規DB作成 → pg_restore → 全テーブルのhash・schema revision比較と秘密復号 → migration/check → 復元認証・承認失効 → api/web再開。
成功時は`LEADHIVE_DATABASE_NAME`を隔離復元DBへ切り替える。data volumeと環境IDは同じ。失敗時は元のDB名を保持する。
全件fingerprintは安定したprimary key順で計算し、JSON/日時/IDを正規化して比較する。Report CLIはREPEATABLE READ / READ ONLY transactionで動作する。明示的な`--invalidate-restored-auth`は例外で、`leadhive_recovery_<32桁ID>`の新規復元DBに限定した書込みtransactionを使う。通常DB名は書込み前に拒否する。
復元前の内容一致とMigration後のmodel整合性は別々に検証する。履歴のhashや承認payloadを再計算・書き換えない。復元後は再ログイン、Agent credential再発行、必要な提案の再作成・Human再承認が必要。過去の承認をSYSTEMが再承認しない。

### Import / Repair / Resume

Importは専用の空環境で元PC停止を確認し、同一会社のID/キーを保持して移行する。G1.1旧固定volumeも新host上ではID由来の名前に正規化する。
未完了のImportは同じID/キーとmaintenance状態でだけretryできる。通常運用中の別環境をImportで上書きしない。
RepairはG1.2が付与したsecurity labelを持つ残存volumeに限定。旧固定volume、消失volume、不一致キーは自動修復しない。
Resumeはメールqueued/running/failed、フォームpending/failed、未完了campaign/batch、未完了form operationをblockerとする。
失敗履歴には結果不明が含まれ得るため、現段階では保守的にすべて止める。Humanレビュー済み履歴を安全に解除する専用UI/照合基盤は未実装。削除や単純retryで回避しない。

## 互換性と限界

- G1.1形式backupはinstance識別の検査には使えるが、DB内容報告がないためG1.2通常restore/importには使わない。元ファイルは保持する。
- 本機能は誤操作・保守失敗への制御。Organization/tenant隔離や全APIからの送信禁止ではない。
- maintenance中はapiも停止する。完了後のapi/web再開は既存Human送信APIを無効化する意味ではない。共通送信停止はG1.3で追加する。
- backupを戻しても外部で既に送信されたメール/Form POSTを取り消せない。元PC停止と外部履歴の突合を必須とし、自動retryしない。
- source停止の確認はHuman入力であり、別PCの稼働をnetwork越しに証明しない。
- dump/envは機密。暗号化保管・提供先別アクセス制限が必要。checksum/manifest/metadataは電子署名ではなく、host管理者の改ざんに対する認可境界でもない。
- metadataのrelease commitは**backupを検証したツールのソース版**。更新前に稼働していた旧binaryの版を推測しない。旧package・Docker imageは別途保管する。
- ソースcommitは固定するが、Docker base imageのdigest固定や再現可能build全体は未対応。requirements/package lockとCI検証を再利用する。
- 旧版でG1.2保守ツールがない場合、対応する新しい検証済みpackageのUpdateがbuild後に安全backupを作成する。通常rollbackでMigrationをdowngradeしない。
- 旧版互換性がないMigrationのrollbackは、旧verified packageとbackupを隔離環境で検証してから行う。自動rollback/DB削除は実装しない。

## 検証結果

| 検証 | 結果 |
| --- | --- |
| Windows PowerShell 5.1 mock tests | 42 passed。G1.1回帰、排他、壊れたrelease、復元失敗/hash不一致、更新失敗、新PC移行/retry、登録repair、再開拒否/許可 |
| Backend全回帰 | 218 passed。新規maintenance tests 7件を含む（失効処理とledger同一transactionのrollbackを検証） |
| Frontend typecheck/lint/build | pass |
| desktop/mobile E2E | 6 passed。API起動を含む、テストDB・送信mockのみ |
| Backend Ruff / compile | lint/compile成功。変更したPythonのformat成功 |
| native PostgreSQL dump→新規DB restore | 42テーブルの報告一致。承認request 14件、audit event 44件一致。復元後のledger UPDATE拒否も確認 |
| 復元時認可 | 隔離native PostgreSQLでCLI実行・payload/承認履歴保持を確認。通常DB拒否確認。有効session/proof/credential/approvalの失効とatomic rollbackは7件のDB testで検証 |
| 配布試験 | 隔離したclean test repositoryでZIP/manifest/checksum/parser/Compose config成功。dirty/untracked release拒否確認 |
| Migration | 変更なし。pytest fixtureのupgrade/check成功。旧Migrationの書換えなし |

標準`ruff format --check backend`は、変更していないA2 Migrationの混在改行で1件失敗する。Git HEAD版は整形に適合しており、今回の変更とは分離して記録する。
Docker実機上の新規Windows導入・containerでの全保守フローは未実行。Windows orchestrationはmock、DB復元は隔離native PostgreSQLで検証した。3社の端末受入は別工程。
実送信、外部API、Dots接続、本番DB更新、production deploymentを実施していない。

## 次のゴール

**G1.3 収集運用と送信停止の分離**。収集workerを利用しながら、legacy・SMTP test・Form・Campaign・Batch・Codex支援を含む全送信経路をserver側で停止できる状態を作る。
G1.2で3社への送信運用準備が全て完了したとは扱わない。本工程完了で停止する。
