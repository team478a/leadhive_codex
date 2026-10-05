# フォーム一括Human承認・予約と共通送信上限

## 今回のゴール

既存の個別フォーム承認・予約を残し、承認キューで複数企業の入力内容を一括確認・再認証・予約できるようにする。環境管理者がフォーム送信上限と一時停止を保存できるようにする。実送信は引き続きOFFで検証する。

## 利用手順

1. 解析済みのフォームと営業用Draftから承認待ち提案を作る。確認画面なし・CAPTCHAなしの既存対応範囲を維持する。
2. 承認キューの「フォームの一括Human承認・予約」で、企業ごとの宛先・POST先・送信者・文面・全入力値・期限を確認する。
3. 対象を選択し、ログインパスワードを再入力して一括Human承認する。承認と予約は別操作。Agentは操作できない。
4. 承認済みの対象を一括予約する。このページは最大50提案、APIは1要求100件まで。ページを移って必要な分を処理する。
5. 成功件数と未予約件数、個別エラーを確認する。一部不備があっても、他の有効な予約は保存される。再取得後も下の予約一覧で確認できる。
6. 実行OFFの間は送信しない。結果不明の自動再送は禁止。未試行の取消は既存画面を使う。

予約キーと承認IDから企業ごとのUUIDを生成する。同じキー・同じhash/versionの再要求は同じ予約を返す。内容違いは拒否し、別キーでも同じ承認の二重予約を拒否する。「予約済みとして確認」の件数には既に保存された同一予約も含む。ページ再読み込み後の別キーによる再予約は重複として拒否され、既存予約は残る。

## 共通上限と一時停止

全Projectでフォーム送信環境を共有しているため、今回は環境全体の設定。既定は直近24時間30件、直近1時間5件、試行間隔60秒。一時停止はfalse、外部送信のfeature flagは従来どおりOFF。

管理画面では保存済み設定と編集中の入力を区別する。User.is_adminのHuman管理者だけがパスワード再認証して変更できる。Project owner/editorの権限だけでは変更不可。Agent、混在認証は拒否する。変更にはexpected_versionが必要で、他の更新と競合すれば409で停止する。再認証はユーザーごとに5分間5回まで。パスワードを監査ログへ保存しない。

設定範囲は24時間1〜1,000件、1時間1〜100件、間隔60〜86,400秒。上限増加・一時停止解除は今後の予約に反映されるため、人が保存内容を確認する。上限を変更してもOUTBOUND_ENABLED／HUMAN_APPROVED_FORM_ENABLEDは変わらない。

workerはclaim時とPOST開始直前の両方で、DBの最新上限・停止状態を確認する。更新・開始判定は同じ短いadvisory transaction lockで直列化する。設定欠落では実行しない。UNKNOWNや失敗も開始済み試行として上限に数える。既にPOSTが始まった処理を一時停止で取り消すことはできない。事前確認中に停止・上限変更された予約は安全条件でblockedとなり、再承認が必要。

## 既存承認の再利用

メールで使用していたBulkApprovalProofを変更せず再利用する。Human・session・Project・選択されたID/hash/versionに結び付いた5分期限・単回利用の再認証でAPPROVEDへ変更する。予約・workerは個別HumanApprovalProofまたは一致する検証済み/使用済みBulkApprovalProofの永続証拠を確認する。証明の期限は再認証操作の期限であり、成立済みの承認期限はApprovalRequestの最大24時間で判定する。

snapshot、immutable payload、送信直前の再検証、suppression、重複防止、UNKNOWN保護、既存監査ledgerは維持する。PolicyAuthorizationやAgentによる承認は追加しない。

## DB・API

追加Migration `f9c36fb4d750`、親`f8b25ea3c649`。新規FormDispatchLimitsにsingleton行を作成する。既存Migration・承認Model・送信履歴を書き換えない。downgradeは設定テーブルのみ削除し、既存承認・予約・監査ログは保持する。戻した状態で新workerを使っても設定欠落で送信停止する。

- GET `/api/form-dispatch-limits`：Human利用者へ保存済み上限、version、can_manage、実行flagを返す。
- PUT `/api/form-dispatch-limits`：Human環境管理者専用。passwordとexpected_versionを要求する。
- GET `/api/form-dispatch-limits/audit`：管理者専用、直近20件の変更履歴。変更者、日時、変更前後とversionを保存する。
- POST `/api/projects/{project_id}/approved-form-dispatches`：Human owner/editorによる一括予約。企業ごとにreservationまたはerrorを返す。全件atomicではない。
- 既存 `/bulk-approval/challenge`、`verify`、`approve`：フォーム選択にも利用する。

## 月10,000件について

30日運用なら平均約334試行/日。たとえば上限500/日・30/時という設定を保存できるが、到達件数・送信成功件数を保証するものではない。1社1フォームの対応率、確認画面/CAPTCHAの比率、承認期限、Web取得時間、宛先の重複、営業禁止、例外対応量が実運用の制約となる。上限設定は余力を与えるだけで、不対応フォームの自動化や安全条件の回避は行わない。

次工程候補はサイト別の間隔制御、架空フォームを用いた大量処理/中断復旧の検証、期限切れ・結果不明・blockedをまとめて扱う運用画面。tenant別送信者/枠、配布パッケージの再生成、Production、実送信の有効化は今回の範囲外。

## 検証

2026-10-05、専用PostgreSQLとHTTP mockのみで実施。実企業への通信・実メール/フォーム送信は行っていない。

- 新規Governanceテスト15件成功：一括再認証、replay拒否、予約の冪等性、部分失敗、mock実行、Agent/混在認証拒否、他Project/viewer拒否、管理者再認証、設定version競合、範囲検証、再認証回数制限、停止直前検証、UNKNOWNの上限計上、設定欠落時停止。
- 既存の承認済みフォーム33件・承認済みメール31件の関連回帰テスト成功。全Backendテスト一括実行の結果ではない。
- PC／mobile E2E 4件成功。一括承認、再操作で同じ予約キー、保存前後の上限表示、一時停止、実送信OFF、取消・UNKNOWN保護を確認。候補読込前のまとめて選択を無効にし、読込競合を修正した。
- Backend Ruff・compileall、Frontend typecheck・lint・build成功。API／Web Dockerビルド成功。
- 専用DBでupgrade→downgrade `f8b25ea3c649`→upgrade→Alembic check成功。専用テストDBでもModel差分なし。
- ローカルプレビューはバックアップ後にrevision `f9c36fb4d750`へ適用。API／worker／Webを更新し、API/DB healthと新しい画面assetを確認。
- 企業100件を維持し、フォーム予約・フォーム送信・メール送信記録は各0件。保存済み上限は30/日・5/時・60秒・version 1のまま。API/workerの外部送信・承認済みフォーム・legacyフォーム・Agent flagはすべてfalse。

月10,000件の実処理性能、実サイトでの成功率、サイト別制御、配布zip再生成は未検証/未実施。
