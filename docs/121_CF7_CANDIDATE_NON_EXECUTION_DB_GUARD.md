# CF7候補 P1 — 非実行DB guard

## ゴール

2026-10-06。[120の設計](120_CF7_CANDIDATE_APPROVAL_PREPARATION_DESIGN.md)のP1だけを実装した。CF7候補を既存送信方式へ流用できないDB境界を先に追加する。候補保存API・Human承認UIの拡張・observer・実送信接続はP2以降であり、今回公開していない。

## 実装

- 新additive migration：`ff51ac0e6437_cf7_candidate_non_execution.py`。親は `fe409dbf5326`。既存migrationは変更していない。
- ApprovalRequestに `ck_cf7_candidate_not_consumed` CHECKを追加。`cf7_candidate_only` は全DBでCONSUMED不可。test DBやfeature flagの例外なし。
- 専用INSERT/UPDATE triggerで候補snapshotの基本形状、NON_EXECUTABLE、専用version、外側/内側のProject・Company・Draft・payload version・URL・文面と列の一致を検査。CompanyのProject、DraftのCompany/form channel、ProfileのCompanyも確認する。
- 欠落/JSON null/型違いを `IS DISTINCT FROM` 等で拒否。hashは文字列64桁hex、wire_sizeは正の数で64KiB以下。完全なcanonical契約検証・hash再計算・sender/field対応の詳細検証は既存pure validatorとP2 serviceの責務であり、SQL形状検査だけを暗号的証明とはしない。
- `cf7_candidate_marker()` は新方式名に加え専用snapshot/hash keyの存在を検出。方式名だけをform_direct等へ偽装しても候補bindingを要求する。
- `approved_form_dispatches` と `approved_email_reservations` のINSERT/UPDATEで、コピーしたsnapshot/envelopeのmarkerと、approval_idの参照先の両方を検査。候補は予約自体を拒否する。
- `form_deliveries.execution_authorization.approval_id` の参照も拒否。UUIDとして照合するため、大文字やハイフンなし表記でも同一候補を検出する。配送方式をdirect/adapter/codex_assistedへ変更しても候補承認を流用できない。
- その他の `approval_id` / `outreach_approval_id` は旧OutreachDraftApprovalへの参照であり、ApprovalRequestへのFKではない。そこへ新方式を追加していない。EmailSendAttemptは予約を介するため、新候補の予約拒否を継承する。
- 既存immutable approval・append-only ledger・配送方式の制約・worker方式allowlistは維持した。DB管理者によるtrigger無効化や権限外DDLまで防ぐとは保証しない。

## Migrationとrollback

旧schemaに既に新候補方式/markerの記録がある場合、upgradeを停止する。未保護記録を黙って安全な候補と認定したり、削除/書き換えたりしない。

P1適用後に候補記録がある場合、downgradeを拒否する。記録がない場合だけP1のCHECKと4本のtrigger・関連functionを戻せる。運用rollbackは入口の停止を基本とし、承認/監査記録を消して戻さない。

## 検証範囲

`backend/tests/test_cf7_candidate_db_guard.py` は実PostgreSQLの専用test DBで、内部synthetic fixtureを使う。fixture作成は公開APIではない。APPROVED fixtureもDB拒否を試すための特権SQLデータであり、Human承認を代替する機能ではない。

試験対象：PENDING保存、CONSUMED INSERT/UPDATE拒否、APPROVEDからの消費/文面/version変更拒否、NULL/欠落/型/ID不一致、協調したProject偽装、旧方式偽装、form/email予約の参照・コピー偽装、配送3方式への認可転用、配送UPDATE、upgrade前の未保護証拠、証拠ありdowngrade拒否、証拠なし往復。

全関連flagをONにした試験でも汎用APIで新方式を作れない。既存validateは新方式を拒否し、通常/control lab workerへ新方式を登録していない。新しい予約/消費/配送APIは存在しない。

最終Backend対象8ファイル：**281 passed、50 subtests passed、139.39秒**。281件の中に新guardの50件を含む。subtest数は通常test数へ加算しない。リポジトリ全Backend試験を実行したという意味ではなく、承認・通常フォーム・adapter・fixture・新CF7契約・承認付きメールの関連回帰を選んだ。

空の専用PostgreSQL DBで全migrationをheadまでupgrade→model差分check→P1だけdowngrade→upgrade→check成功。headは `ff51ac0e6437`、4本のtriggerを確認し、作成した検証DBは削除した。既存の専用test DBでも最終migrationを再適用し、model差分なし。

Ruffはapp/tests/migrations全体で成功。変更3ファイルのformat確認・app/migrationsのcompileall成功。mypyは変更Model/migrationの2ファイルを `--check-untyped-defs --follow-imports=silent` で成功（全Backend strict型検証ではない）。Frontend lint、build内のtsc typecheck、Vite build成功。

既存Human承認/管理下adapterのdesktop/mobile E2E：**4 passed、47.8秒**。専用test APIの起動も成功。これは既存UIの回帰であり、未実装のCF7 UIの試験と混同しない。

## 運用状態と残り

稼働DBへmigrationを適用していない。稼働API・Web・Windows配布物は更新していない。workerは停止状態を維持。実企業アクセス、メール/Form POST、Codex送信タスクは行っていない。

次はP2：専用test証拠の保存、二層snapshotのservice結合、保存済みDraftからの専用準備APIと失効検証。その後P3でHuman確認画面を追加する。今回P2/P3には進んでいない。
