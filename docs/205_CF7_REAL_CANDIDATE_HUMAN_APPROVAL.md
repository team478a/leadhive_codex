# 実サイトCF7候補のHuman承認接続（送信不可）

## 基準・範囲

`codex/integration@0742970`の引き継ぎプレビューを既存Human Approval Foundationへ接続する。
実装commit：`3094dfd`。
候補のPENDING作成、再認証による内容承認、却下・取消、変更・期限切れ失効まで。
SMTP・Form POST・送信予約・worker実行には接続しない。
既存のテスト専用`cf7_candidate_only`と実サイト候補を混在させない。

## API・UI

- `POST /api/form-profiles/{id}/approval-handoff-request`
- 入力は`expected_handoff_hash`のみ。本文・宛先・sender・confirmed等の追加フィールドは禁止。
- Human session、owner/editor、同じProject、保存済み入力確認と最新の静的証拠が必要。
- Agent/Bearer認証、Cookieとの混在、他Project、Viewerの作成/承認を拒否。
- Company・Project membership・Draft・sender・profile・fieldsをロックし、最新値を再取得。
- 同じHuman・Company・引き継ぎhashの有効PENDING/APPROVEDは再利用。重複作成しない。
- 入力確認票から候補をキューへ追加。キューで宛先・文面・入力値・証拠期限・wireサイズを確認。
- パスワード再認証と既存の単回challengeを必須とする。request/hash/version/user/session/action/期限へのbindingを再利用。
- 個別承認のみ。bulk承認からは除外し、送信予約画面の候補にも含めない。

## 保存・失効

既存ApprovalRequest/Proof/Auditを再利用し、新しいModelは追加しない。

- `delivery_method=cf7_real_candidate_only`、`payload_version=1`、`canonicalization_version=json-v1`。
- server再生成した引き継ぎsnapshot、contract・encoding、Company/Draft/profile/sender hashを固定。
- 作成者はHUMANのみ。APPROVEDは既存step-up成功時のみ。
- 承認者・承認時刻・承認hash/version・使用済みProofを保存。
- 上限24時間かつ証拠/入力確認期限以下。request期限超過はEXPIRED。
- 入力確認・観測・宛先・文面・sender・scope・連絡可否が変わった場合はREVOKED。
- generic revisionで他方式へ変更不可。変更後は企業詳細で再確認して新しい候補を作成する。
- proposal created、approval granted、expired、revoked、rejected、authentication deniedを既存append-only ledgerへ保存。
- snapshot内の`eligible_for_approval=false`は元の静的証拠が送信権限ではないことを示す。今回のAPPROVEDは非実行候補内容へのHuman承認である。

## 連絡可否

Core permissionを変更しない。営業可否ALLOWED、CAPTCHA_NONEを要求。
営業禁止、DNC、Suppression、UNKNOWN、共有窓口禁止、観測の安全保留等は拒否する。
技術対応の`form_review_required`/`form_ready`保留だけは候補内容の承認対象にできる。
その場合もUNCERTAINをALLOWEDへ変更しない。連絡可否のstatus/reasonもsnapshotに固定する。

## Additive Migration

`0596fa531982`、親は確認済みの既存head `75d9c210ab34`。既存Migrationは変更しない。

- `ck_cf7_real_candidate_not_consumed`でCONSUMED禁止。
- DB triggerでpayload、hash/version、宛先・文面・sender、作成principal、期限等を不変にする。
- method付け替えやmarker削除による旧送信方式への変換も禁止。
- form/email reservationおよびFormDeliveryへの参照・markerコピーを拒否。flagやDB名による例外なし。
- 未保護の実サイト候補履歴が既に存在する場合はupgradeを停止する。
- 候補履歴が残っている場合はdowngradeを拒否。監査記録を削除して戻す運用は採用しない。
- 履歴なしでのdowngrade/upgradeは専用test DBで検証。

## 検証結果

- 既存承認基盤・fixture専用CF7・引き継ぎを含むBackend関連179件PASS。
- request期限/step-up期限の追加後、実サイト候補単独24件PASS。
- DB不変性、CONSUMED禁止、予約3経路の参照/marker拒否、downgrade履歴保護/空状態往復を確認。
- Ruff/format、新サービスのmypy（`--follow-imports=silent`）PASS。
- 通常の依存先込みmypyは既存7ファイル13件のエラー。今回の新サービスのエラーと区別し、全体成功とは報告しない。
- Frontend typecheck・lint・build PASS。既存bundle size警告あり。
- dedicated test DBのhead upgradeとAlembic model diff確認成功。
- UI E2Eは実サイト候補表示/操作をsynthetic応答、実際のHuman step-up/DB制約をBackendと既存承認UIテストで検証する。
- Desktop/Mobile計8件PASS。入力確認→候補作成、キュー再認証、承認/取消、予約候補への非表示を確認。
- 実サイト用の静的HTML証拠はruntime JS実行の保証ではない。候補承認を実行許可へ読み替えない。
- GitHub Actionsは未実行、GitHub pushは未実施。

## 実運用データ・次工程

実運用DBには候補/承認を自動作成しない。outbound OFF、送信worker未起動を維持する。
このPCのDBへ追加Migrationを適用済み。適用前後でCompany26、Raw Snapshot80、Raw Review0、ApprovalRequest0、EmailDelivery0、FormDelivery0を維持。
次工程は実サイト向けdispatch契約・送信直前再検証を独立して設計/検証する。
今回の候補は永久に非実行であり、flag変更だけで送信できるようにしない。
実行方式へ進む場合は、新しい実行用payloadと明示的なHuman再承認が必要。
