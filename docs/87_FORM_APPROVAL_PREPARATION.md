# フォームDraftとHuman Approvalの準備接続

追補：次工程で承認済みの1段階フォーム送信予約を接続した。現在の手順・制限は `88_APPROVED_FORM_DISPATCH_FOUNDATION.md` を参照。以下は準備工程完了時点の記録。

## この工程でできること

承認キューの「フォームDraftから承認候補を準備」で会社と保存済みのフォームDraftを選択し、保存済みForm Intelligenceと運用設定のフォーム送信者情報から入力内容を確認する。確認後「フォーム提案を承認待ちに追加」で既存ApprovalRequestに保存する。下の承認待ち一覧で対象・文面・入力項目を確認し、既存のパスワード再認証で承認・却下・取消できる。

準備ではWeb取得、解析AI、SMTP、Form POST、worker job、Codexタスクを実行しない。Human承認は送信実行ではない。フォームの承認済み送信予約・原子的使用・送信量制御は次工程。

## APIと整合性

- GET `/api/outreach-drafts/{draft_id}/form-approval-preview`：保存済みの入力値、フォームURL、profile/fingerprint、送信者、Draftと準備hashを取得。
- POST `/api/outreach-drafts/{draft_id}/form-approval-request`：`expected_preparation_hash`のみ受け付ける。serverで再構築し、表示後の変更は409。`confirmed`や任意の宛先・文面上書きは422。
- 両APIとも既存Human sessionとproject owner/editorが必要。Agent credentialをHumanへ変換しない。viewer・別projectのユーザーは準備できない。
- READY、営業ALLOWED、CAPTCHAなし、解析fingerprint確定の通常フォームが対象。共通contact permissionで連絡禁止・Suppression・結果不明を拒否。必須値不足、添付ファイル、同名入力、本文mapping未確定は停止する。hidden/submit/button/resetは固定入力に含めない。変動するCSRF等の扱いは将来のdispatch検証に残す。
- Draft本文は切り詰めず保存。宛先・送信者・入力値を既存canonical payload/SHA-256/versionへ固定する。24時間以内の期限とstep-upは既存基盤を再利用。
- 新しく作成するform提案に`sender_source_hash`を追加。送信者設定変更でもPENDING/APPROVEDをREVOKEDへ変更し同一transactionで監査する。既存のDraft、Company、フォームmapping/fingerprint変更による失効も維持する。古い提案のsnapshotは書き換えない。
- Model/DB columnの変更なし。Migration追加なし。既存append-only監査台帳にproposal created/approval granted/revoked等を記録する。

## 未完了の境界

この工程は承認**準備**の接続であり、全フォーム送信経路の承認強制ではない。既存通常送信・batch・Codexのlegacy confirmed経路は今回改変しない。OUTBOUND_ENABLED=falseのまま利用する。承認済みフォームを既存送信APIへ渡してはいけない。

次工程で承認に固定したpayloadだけを実行するフォームdispatch基盤、原子的予約、承認の一度だけの使用、送信直前のsuppression/fingerprint再確認を追加し、legacy送信経路の迂回を閉じる。その後に日次/毎時/サイト別上限と承認済み残件の継続処理を行う。月10,000件の稼働実証は未実施。

将来のフォームdispatchは準備snapshotの必須項目を検査し、古いsnapshotを自動補完して送信しない。必要なhash/準備情報がない提案は新しい準備・再承認へ戻す。

FormSenderSettingsは現状インストール全体の設定を再利用する。複数企業が同じインストールを共有する場合のtenant別送信者設定は別課題であり、今回の変更でtenant対応完了とは扱わない。

## 検証

Backendは専用PostgreSQLで準備→step-up→承認、設定/Draft/mapping/fingerprint変更の409と失効、禁止・CAPTCHA・必須不足・添付・同名入力・他ユーザー・confirmed拒否を検証する。既存A2 security testsと併せて実行する。Frontendはtypecheck/lint/build、およびdesktop/mobileの準備操作と既存Human承認のE2Eを実行する。画面準備のE2EはHTTP mock、整合性と権限はBackend実APIで検証する。外部フォーム・メールへ送信しない。

- 既存A2 security testsと初期準備テストの74件成功。最終の参照データlock・追加Agent/混在/viewer拒否テストを含む準備16件と既存UNKNOWN4件、計20件も成功。テストが重複しており全Backend suiteの単一実行ではない。
- 各テスト起動でAlembic upgrade/check成功、Model差分なし。DB変更は不要。Ruffとcompileall成功。
- Frontend typecheck/lint/build成功。フォーム準備E2Eはdesktop/mobileとも成功。既存Human承認E2Eは初回desktop成功、mobileは再認証待ち中に60秒の総時間制限超過。Backend検証終了後の再実行ではdesktop 12.6秒、mobile 8.0秒で両方成功。アプリの承認guardを緩める変更はしていない。
- ローカルAPI/workerのソースとWebを反映し再起動。healthでAPI/DB正常、OUTBOUND_ENABLED=false・Agent機能falseを確認。今回メール/Form POST/テスト送信/Codex送信は実行していない。
- Backend/Web Docker image buildも成功。配布用のzip/USBフォルダの再生成はこの工程の対象外。
