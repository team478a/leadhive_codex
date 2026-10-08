# 実サイトCF7：別のHuman再承認と予約のみの保存

## 範囲

基準は`codex/integration@bf5d4d9`。既存の候補内容承認を削除・変更せず、別の予約用承認を追加する。
実装commit：`e184f44`。

今回のゴールは「候補内容の承認 → 予約用の別提案 → Human再認証・再承認 → 予約だけ保存」。
実行器・SMTP・Form POST・Codex送信には接続しない。予約は設定ONでも実行できない。
予約を保存したことを、送信可能性や実サイト受付の検証完了として扱わない。

## 承認の分離

- 元の`cf7_real_candidate_only`は永久に非実行。旧候補のCONSUMED・直接予約・送信接続禁止を維持する。
- 新しい`delivery_method=cf7_real_reservation`を既存ApprovalRequestへ保存。新規Modelは不要。
- 保存済みの候補内容承認がAPPROVEDで、hash/version一致・使用済みHuman proof・現在のProject権限が有効であることを要求。
- snapshotは元の承認ID/hash/version/承認者/日時、入力確認・静的契約・encodingを保持する。
- `cf7_reservation_plan.environment=RESERVATION_ONLY`、`execution_allowed=false`。
- 新しい提案はHUMANのPENDINGとして作成し、別ID/hashのstep-upを必要とする。元のchallengeは流用できない。
- 上限24時間かつ元の承認・証拠期限以下。入力値・文面・sender・観測・権限・連絡可否・元承認の変更/取消/期限切れで無効。
- payloadの汎用改訂とbulk承認は禁止。変更時は専用準備から新しい提案を作る。
- 技術対応に関するUNCERTAINをALLOWEDへ変更しない。将来の実行には別の実行契約、Core permission再確認、新しいHuman承認が必要。

## API・UI

- `GET /api/approval-requests/{source_id}/cf7-reservation-preview`
  - 保存済みデータの準備確認のみ。外部GETやPOSTを行わない。
- `POST /api/approval-requests/{source_id}/cf7-reservation-request`
  - strictな`expected_preparation_hash`だけを受け付ける。clientのpayload/confirmedで承認を代替しない。
- 既存challenge/verify/approve/reject/revokeとappend-only ledgerを再利用。
- 新しい予約用承認に対して既存`POST /api/approval-requests/{id}/form-dispatch`を利用。
- Human session・Project境界・owner/editor必須。Viewerは確認のみ、Agent/Bearer混在は拒否。
- 画面で「候補内容」と「予約のみ」を区別。元の候補から準備内容を確認し、別の承認待ち提案を開いて再認証する。
- 宛先・文面・入力値・証拠期限を確認するcheckboxとパスワード再認証を要求。
- 予約画面は「この予約から送信は始まりません」を表示し、取消を可能にする。

## 予約・DB保護

既存ApprovedFormDispatch、宛先重複チェック、advisory lock、idempotency key、site records、ledgerを再利用。
同じ予約キー/内容は同じ予約を返す。異なるキーによる同一承認や既存宛先への予約は409。
UNKNOWNを既存の重複チェックから除外しない。

Additive Migration `07ab219ec430`、親は`0596fa531982`。既存Migrationは変更しない。

- 新方式のApprovalRequestはCONSUMED不可。payload・scope・principal・期限は不変。
- 元の承認・入力packetとのbinding、元の使用済みHuman proofを検査。
- 予約は新しい承認snapshot/hashと一致し、新しいHuman proofを必要とする。
- 予約statusはqueued/blocked/cancelledのみ。started_at/worker_id/lease/delivery_idは常にNULL。
- method/markerを削除して既存実行方式へ付け替える変更も拒否。
- Email reservationやFormDeliveryへの参照・markerコピーを拒否。
- flag ONや`_test` DBによる例外を設けない。
- 通常workerはform_direct、管理下lab workerはform_adapterだけを取得する。新方式は取得対象外。
- 未保護の新方式履歴があればupgrade停止。履歴が残るdowngradeは拒否し、履歴を消して戻す運用は採用しない。

## 検証・制限

- Backend関連120件PASS（候補承認・引き継ぎ・既存フォーム予約を含む）。
- 追加security test後、予約23件を含む承認基盤・運用・上限制御113件PASS。両suiteの重複を合算しない。
- 元challenge流用、Agent/Viewer/他Project、未承認、hash/version不一致、期限/文面/禁止/元承認取消を拒否。
- 新方式のDB不変性、実行/配送への参照・markerコピー拒否、flags ONのworker非取得、取消、冪等性を確認。
- dedicated test DBのhead upgrade/Alembic model diff、履歴なしdowngrade/upgrade、履歴ありdowngrade拒否PASS。
- Ruff/format PASS。新サービスのmypy（`--follow-imports=silent`）PASS。全体mypy既存エラーは未修正。
- Frontend typecheck/lint/build PASS。bundle size警告（約662KB）が残る。
- Desktop/Mobile E2E計6件PASS（既存Human承認、実サイト候補、別再承認→予約）。
- 最初の新規UI testは承認HTTP応答より先にカウンターをassertして失敗。応答完了を待つassertへ修正し、全6件を再実行してPASS。
UI E2EのCF7経路はsynthetic API応答で画面操作を確認し、実際の再認証・DB guard・worker拒否は専用test DBのBackend testsで確認する。
既存Human承認UIは実際のtest DBを使うE2Eでも回帰確認する。

実運用データにHuman承認や送信予約を自動作成しない。
このPCのDBへMigrationを適用し、適用前後でCompany26、Raw Snapshot80、Raw Review0、ApprovalRequest0、EmailDelivery0、FormDelivery0を維持。
outbound OFF、送信worker未起動を維持する。

GitHub Actionsは未実行、pushは未実施。既存の全体mypyエラーとbundle size警告は今回の新サービス検証とは分けて扱う。

## 次工程

実サイト向け送信直前のfresh observation、ALLOWEDの最終確認、版別実行契約、atomic consume/idempotency/UNKNOWN保護を独立して検討する。
今回の予約をflag変更だけで実行可能にしない。実行対象へ進める場合は、新しいpayloadとHuman再承認を必要とする。
