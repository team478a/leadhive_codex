# CF7候補 P3 — 同意確認画面・改訂・失効案内

## ゴール

2026-10-06、基準 `codex/integration@57abc4f`。実装commitは `f25c90f`。[120の設計](120_CF7_CANDIDATE_APPROVAL_PREPARATION_DESIGN.md)のP3として、[P2](122_CF7_CANDIDATE_STORED_PREPARATION_API.md)の候補準備をHuman UIから操作し、immutableな改訂履歴を維持する。

**候補内容の承認まで。CF7は送信・予約・承認消費・Codex送信に使えない。** 管理下fixture証拠、専用 `_test` DB、準備flag既定OFFを維持した。実サイト用observer、証拠アップロード、実行用契約、dispatchは追加していない。

## 利用手順（専用検証環境のみ）

1. owner/editorで承認キューを開き、Projectを選ぶ。
2. 「CF7候補を準備」で会社と保存済みフォームDraftを選ぶ。
3. 「CF7証拠・同意欄を取得」で保存済み同意labelを確認する。
4. 必須・任意の欄すべてで「選択する／選択しない」を明示する。必須は選択が必要。任意購読欄は自動選択しない。
5. 「CF7選択済み内容を確認」でURL・REST endpoint・送信者・本文・フォーム順の入力値・同意・観察日時・期限を読む。同意を変更すると準備済みhashと確認済み状態を消す。
6. 入力値・同意・期限の確認欄にチェックし、承認待ちへ保存する。
7. 下の候補一覧から対象を選ぶ。証拠詳細とpayload version/hashを確認し、CF7確認欄にチェックしてログインパスワードで再認証する。「CF7候補内容を承認（送信不可）」で内容の承認だけを記録する。
8. 内容を変える場合、元のDraft・送信者設定で修正し、選択した候補の「CF7候補を改訂・再準備」から同意を選び直す。新しいversionを保存し、新たな再認証・承認を行う。

画面が表示されない場合、準備flag OFFまたは専用検証環境ではない。稼働環境でflagをONにする案内ではない。営業禁止・suppression等で止まった場合、解除して続行する機能はこの画面にない。

## 画面と安全境界

- `CF7CandidatePreparationPanel`：会社/Draftの選択、同意の未選択状態、選択済みpreview、確認、候補保存、専用改訂。別Projectへ移ると状態を破棄し、unmount後の応答は適用しない。
- `CF7CandidateDetails`：controlsの保存順でlabel/name/required/valueを表示し、checkboxの選択/非選択を明示する。送信者・本文・URL・観察日時・期限、snapshot/contract/evidence/wire hash、fingerprintを確認できる。
- `ApprovalQueuePage`：履歴ID/改訂元、失効後の再準備案内、CF7専用の承認文言。証拠表示不足・確認前は承認ボタンを無効にする。step-up失敗時にも状態を再取得する。
- 取得した文字列はReactでtextとして表示する。HTMLとして実行しない。外部URLを開く操作を追加していない。
- UI確認checkboxは操作補助。認可の根拠はサーバーのHuman session/owner/editor/単回step-up/hash/version/期限/現在source検証。UIだけで認可しない。
- Viewerは閲覧できるが、準備・改訂・承認はできない。Agent credential/混在cookie拒否を維持する。
- `ApprovedFormPanel` / 一括フォーム画面は候補を除外し、API・DBの非実行制約も維持する。

## 改訂API

| API | 内容 |
|---|---|
| GET `/api/approval-requests/{id}/cf7-revision-preview` | 最新版か確認して、現在の証拠と必要な同意選択を取得 |
| POST 同URL | expected_hash/version、同意name/checkedだけで次versionのpreviewを生成 |
| POST `/api/approval-requests/{id}/cf7-revisions` | 上記入力とexpected_preparation_hashを照合して新PENDINGを保存 |

自由なtarget/body/sender/URL/hidden/期限/confirmedの入力は禁止。既存汎用revisionからCF7へ変換しない。

Project/Member・request・sourceの既存lockを再利用し、proposal_idの最新版のみ改訂可能。旧versionからの二度目の改訂は409。DBの既存 `proposal_id + payload_version` unique constraintも維持する。

新requestは同じproposal_id、payload_version+1、supersedes_request_id=旧request。inner/outer hashとversionを同時に更新する。旧PENDING/APPROVEDはREVOKED、期限切れならEXPIREDとしてSYSTEMの失効監査を記録する。新requestはPENDINGでHuman approval情報を持たない。失効・取消・却下済み最新版は、現在の証拠・permissionが有効であれば再準備できるが、その履歴状態を書き換えない。

旧payload/hash/承認情報は上書きしない。旧step-up tokenは新requestへ使用できない。改訂保存失敗時は新requestや旧承認取消を途中commitしない。新候補保存と旧候補の取消・revision created監査は同一transaction。未知結果・送信履歴へは接続していない。

証拠の期限切れは新しい有効な内部fixture証拠が必要。時計や期限を書き換えて復活させない。営業禁止・suppression・opt-out・do_not_contact等は改訂でも再検証する。

## DB・互換性

新Model・migrationなし。P1/P2のDB guardと既存ApprovalRequest/HumanApprovalProof/OutreachAuditEventを再利用した。既存方式のcanonical payloadや汎用revisionの動作を変えない。P2 previewへ観察日時・証拠hash・snapshot hashを追加し、CF7の承認取得応答へ証拠表示用の項目を追加した。

rollbackは準備flag OFFで入口を停止する。証拠、承認履歴、監査、非実行guardを残す。flag OFFでも既存候補の取消・却下は既存APIで行える。

## 検証方法

Backendは専用PostgreSQLのAPI試験。Human proof・改訂lineage・旧承認失効・新step-up・stale hash/version・旧版改訂拒否・Agent/Viewer/越境拒否・連絡禁止・証拠期限更新を確認する。既存P1/P2およびHuman/adapter/通常フォーム/メールの回帰も対象。

`cf7-candidate-preparation.spec.ts` はmockなしの実API＋PostgreSQLによるdesktop/mobile試験。同意の明示選択、任意購読の非選択、保存、Human再認証、Draft変更によるREVOKED、version2の改訂・再承認・取消、予約ボタン不在、外部requestなし、横幅を確認する。

この試験だけは `CF7_E2E_DISPOSABLE_DATABASE=true` と `leadhive_cf7_p3_e2e_*_test` 名の専用DBが必要。DBを新規作成して事前に `alembic upgrade head` / `alembic check` を実行し、Playwright起動前に用意する。通常E2Eでは新試験をskipし、CF7準備flagはOFF。証拠/ledgerのDB triggerを無効化せず、試験終了後に作成した専用DB全体を削除する。稼働DB名を渡して実行しない。

## 検証結果

- Backend関連11 spec：**351 passed / 50 subtests passed（545.78秒）**。その後、未閲覧の期限切れ候補の扱いと境界試験を追加し、最終service変更後の改訂specは **10 passed（17.00秒）**。7件が前の351件と重複し、3件が追加。単純加算しない。全Backendリポジトリの試験ではない。
- 期限切れ試験は時計を進め、有効な新しいObservationを追加する。immutableなrequestのexpires_atをUPDATEして試験都合でguardを迂回しない。新証拠のない改訂は拒否する。
- Frontend関連6 spec、desktop/mobile計14シナリオを実行。13件成功、新CF7 desktopのfixture importが失敗。スクリプトのbackend root解決を修正し、新CF7のdesktop/mobile両方を再実行して **2 passed（2.1分）**。他の12シナリオは先の実行で成功。14件を単一の最終実行で全件成功したという記録ではない。
- 新CF7画面試験はmockなし。日本語本文、必須同意、任意購読の明示的非選択、候補内容の確認、実session/password step-up、APPROVED、Draft変更によるREVOKED、version2・新step-up・取消を確認した。外部request/送信予約なし、desktop/mobileで横方向のはみ出しなし。
- 新規専用DBで全chain `upgrade head` → `alembic check` 成功、headは既存 `0152bc1f7548`。初回の未migration DBでの起動は失敗し、事前upgrade後にE2E APIが正常起動した。試験で保存したCF7証拠は3件、FormDelivery / EmailDeliveryは各0件。fixture/ledgerのguardを無効化せず、終了後に今回作成した専用DBだけを削除した。
- Ruff app/tests/migrations、compileall app/migrations成功。変更Backend service/APIの3ファイルをmypy `--check-untyped-defs --follow-imports=silent` で確認し成功。全Backend strict型検証ではない。
- Frontend eslint、tsc typecheck、Vite build成功。CF7実フロー試験の上限は120秒で、locator待ちは既存設定を維持し、固定sleepを追加していない。
- 稼働API `/api/health` はstatus/databaseともok。稼働workerはexitedを維持した。

## 停止点

稼働DB/API/Web、worker、Windows配布パッケージを更新していない。実企業へのHTTPアクセス、SMTP/Form POST、Codex送信タスクを実行していない。

次は別ゴールとして、実サイトから安全に証拠を取得するproduction observerの設計・検証。P3完了を「実CF7送信対応完了」と扱わず、送信接続へ自動的には進まない。
