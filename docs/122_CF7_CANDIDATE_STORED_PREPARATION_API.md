# CF7候補 P2 — 証拠保存・Human承認API

## ゴールと範囲

2026-10-06、`codex/integration@d0044f4` のP1を維持し、[120の設計](120_CF7_CANDIDATE_APPROVAL_PREPARATION_DESIGN.md)のP2を実装した。実装commitは `7b4e77b`。保存した管理下fixture証拠と既存Draft・送信者設定からNON_EXECUTABLE候補を作り、既存Human Approval Foundationへ接続する。

**専用test DB限定、feature flag既定OFF。実サイト用observerや証拠アップロードAPIはない。** CF7が送信可能になったという意味ではない。P3の専用準備・同意確認画面、改訂lineage、実サイト取得・実行用契約・送信接続には進んでいない。

## 保存Modelとmigration

- `CF7Observation` / `cf7_observations`：Project、Company、FormProfile、登録Human、source_kind、observer_version、observed_at/expires_at、evidence_snapshot/hashを保存。
- source_kindはCONTROLLED_FIXTUREのみ。証拠期限は観察後24時間以内。初期observer versionは `cf7-controlled-v1`。
- 技術証拠はURL/root/endpoint、CF7 ID、hidden6項目、controlの順序・label・type・required・checkbox値、field mapping、DOM fingerprint。profile source hashに解析version/更新日時/最終解析日時と保存済みProfile/Fieldの内容を結合する。
- body/senderは証拠へ複製せず、準備時に現在のDraft/設定から取得する。cookie、認証header、未知token、raw HTMLを保存する入口はない。登録は内部test fixtureのみで、実サイトを観察したとは扱わない。
- 新additive migration `0152bc1f7548_cf7_observations.py`、親 `ff51ac0e6437`。所有関係をINSERT triggerで確認し、UPDATE/DELETE/TRUNCATEをDBで拒否する。証拠がある場合downgradeを拒否する。
- P1の承認消費・form/email予約・配送認可の拒否制約は変更していない。

## 追加API

| API | 用途 |
|---|---|
| GET `/api/cf7-candidate-preparation-status` | Human認証。enabledとnon_executable=trueを返す |
| GET `/api/outreach-drafts/{id}/cf7-candidate-preview` | 未選択preview。checkboxがある場合は必要な選択一覧を返し、保存用hashは発行しない |
| POST `/api/outreach-drafts/{id}/cf7-candidate-preview` | name/checkedだけの明示的選択を反映し、検証済みsnapshotとpreparation_hashを返す |
| POST `/api/outreach-drafts/{id}/cf7-candidate-request` | 同じ選択とexpected_preparation_hashを照合してPENDING保存 |

設定は `CF7_CANDIDATE_PREPARATION_ENABLED=false` が既定。ONでもDB名が `_test` でなければ準備を拒否する。Agent flagと独立している。入口OFFでも既存候補のread/reject/revokeとDB非実行guardは維持される。保存済み候補のHuman承認も既存共通APIで検証し、専用test DB以外の候補は有効とは認めない。

owner/editor限定。Agent credential・Human cookie混在は既存境界で拒否。URL、body、sender、hidden、confirmed、無期限expires_at等の入力を受け付けない。checkedは厳密なboolean、nameはcontrol名の形式・長さ制限付き。未知/重複/不足checkbox、必須未選択を拒否し、任意購読欄の未選択を勝手に選択へ変えない。

GET/POSTは保存済みデータだけを使い、外部GET/POSTしない。自由入力の汎用Proposal schemaへ新方式を追加していない。Agent API、bulk approval、汎用revisionから新方式を作成・転用する経路もない。

## 二層snapshotとHuman承認

外側は既存json-v1 envelopeを維持し、既存方式のhash形状を変えていない。新方式だけcf7_observation_id/hash、cf7_candidate_snapshot、cf7_candidate_snapshot_hashを加える。

内側は既存pure `CF7Candidate` / `snapshot()` を利用する。contract_hash、snapshot全体のhash、外側ApprovalRequest.payload_hashを分ける。Humanの5分単回password step-upは既存のrequest ID/session/action/外側hash/versionへbindする。

challenge/verify/approve/readで現在の証拠・Draft・送信者・permissionから再構築し、外側全体と内側wire metadata、サーバー解決のID/versionを照合する。証拠、解析日時、mapping/label、文面、送信者、会社、同意、営業禁止・suppression/opt-out/do_not_contactが変わると旧PENDING/APPROVEDをREVOKEDへ移す。期限切れはEXPIRED。状態と監査は既存の同一transactionを利用する。

requestの期限は作成から24時間と証拠期限の早い方。証拠期限が作成中に切れた場合も保存を拒否する。最初のpayload_versionは1。改訂は未公開として明確に拒否し、再準備は新request/proposal ID・新step-upを必要とする。新requestを旧Human proofで承認できない。

## Safetyと互換性

通常フォームのREADY/送信対応条件や共通contact permissionを緩めていない。候補専用経路ではREVIEW_REQUIRED・delivery_supported=false・ALLOWED・CAPTCHA_NONE・確認画面なしの管理下証拠を要求する。共通permissionが返す技術的な `form_review_required` だけを非実行準備として受け付け、送信可能とは判定しない。連絡禁止、suppression、UNKNOWN、共有店舗宛先等の拒否は維持する。

Project/Member→Company/Draft→Sender/Profile/Fieldのsource lockと再読み込みを共通準備へ揃えた。初期Draft取得時に先にDraftだけをlockする方式をやめ、Project lockとの逆順を避ける。Human承認でもCF7 sourceをlockし、現在の権限を再確認する。型確認で既存Revision入力との型不整合が見つかったため、共通expected()の型注釈をExpectedPayload | Revisionへ修正した。既存request schemaや動作は変えていない。

新しいUI操作フローは未実装。ただし候補が既存Queueに表示されても送信と誤認しないよう「候補内容の承認のみ・送信不可」を表示し、フォーム予約画面は対応方式のallowlistに変更して候補を除外した。サーバー・DB拒否も維持する。

OutreachAuditEventにはproposal created、approval granted、拒否/取消/失効等の固定理由・actor・外側hash/versionを記録する。文面、パスワード、challenge/token、秘密情報をledgerへ複製しない。承認は送信実績へ加算しない。

## 品質確認

Backend関連10ファイル：**344 passed、50 subtests passed、143.25秒**。344件の中にP2の32件とP1 DB guardの50件を含む。通常test数とsubtest数を加算しない。リポジトリ全Backend試験を実行したという意味ではない。

Backendは実PostgreSQL、APIはTestClientで実際のsession/step-up/承認を使用した。外部HTTP transport・SMTPをtrapした非送信試験を含む。owner/editorの承認、Agent/混在cookie/viewer/他Projectの拒否、step-up/hash/version/期限、必須同意・任意購読、source変更による失効、snapshot改変、証拠append-only/所有関係/downgradeを確認した。

新規専用DBで全chainのupgrade→check→P2 downgrade→upgrade→check成功。headは `0152bc1f7548`、証拠guard2本を確認し、検証DBを削除した。稼働DBは対象外。

Ruff app/tests/migrations、compileall app/migrations成功。変更Backend 10ファイルのmypy `--check-untyped-defs --follow-imports=silent` 成功（全Backend strict型検証ではない）。Frontend lint、build内tsc typecheck、Vite build成功。

FrontendのCF7 safety試験はリスト応答をmockして警告・予約ボタン不在を確認する表示試験であり、CF7証拠やHuman承認をDBへ偽造するものではない。実際の証拠保存・承認bindingはBackend試験で確認する。専用CF7準備UIのE2E完了とは呼ばない。

Playwright関連5 specをdesktop/mobileで実行し、12シナリオ中11件成功、1件は既存テストのHTTP到着待ち不足で失敗した。修正後に該当 `approved-form.spec.ts` のdesktop/mobile全4件を再実行し、**4 passed（55.0秒）**。他の8シナリオは先の実行で成功しており、CF7 safetyはdesktop/mobileとも成功した。12件を単一の最終実行で全件成功した、という記録ではない。試験回数を足してシナリオ数を増やさない。

既存のフォーム予約E2E fixtureへ、サーバー応答に含まれる `delivery_method=form_direct` を明示した。方式がない候補を予約対象に戻すためにUIのallowlistを緩めていない。また、モバイルの一括予約試験では2回目のHTTP request到着を待ってから同一idempotency keyを検証する。固定sleepは使わない。

## 運用状態と次の工程

稼働DB、API/Web、送信設定、Windows配布物は更新していない。workerは停止状態を維持する。実企業へのアクセス、メール/Form送信、Codex送信タスク起動は行っていない。

次はP3：同意label/入力値/証拠期限/hash/versionを確認する専用Human画面と改訂・失効の案内、desktop/mobile受入。実送信やproduction observerは別ゴール。
