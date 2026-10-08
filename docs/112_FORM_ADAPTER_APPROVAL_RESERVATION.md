# 管理下フォームの準備・Human承認・非実行予約

この文書は工程2時点の実装記録。工程3のテスト専用実行・追加のDB証拠制御は [113_CONTROLLED_ADAPTER_POSTGRES_HTTP.md](113_CONTROLLED_ADAPTER_POSTGRES_HTTP.md) を参照する。通常worker・利用中環境・工程2のUIは引き続き新方式を実行しない。

## 今回のゴール

110の工程2をまとめて実装する。保存済みDraftと解析情報から計画を準備し、Humanが計画と入力値を確認して再認証・承認し、既存フォーム予約台帳に保存できる状態。基準はcodex/integration@f328f3d。

実行器、HTTP transport、worker実行登録、実CF7、確認POST、SMTP、Codex送信は接続しない。新方式のCONSUMED禁止は維持する。利用中環境と配布パッケージは更新しない。

## 利用可能な範囲

新設定 `form_adapter_preparation_enabled` は既定false。trueでもDB名が `_test` で終わる専用試験環境だけで準備・予約できる。実企業向け機能のリリースではない。

CONTROLLED_LAB / controlled_lab_single_post / version 1、固定fixture.exampleのcontactとsubmitという111の契約だけを利用する。通常のFormProfile READY、安全な入力mapping、ALLOWED、CAPTCHA_NONE、確認画面なし、送信者/Draft/連絡禁止の共通検証を要求する。実CF7をdelivery_supported=trueへ変更して通す処理は追加していない。

## API

| API | 役割 |
|---|---|
| GET /api/form-adapter-preparation-status | Human認証付きで準備可否と予約専用状態を返す |
| GET /api/outreach-drafts/{id}/form-adapter-preview | 保存データから計画・入力値・確認用hashを生成 |
| POST /api/outreach-drafts/{id}/form-adapter-request | expected_preparation_hashだけを受け取り、保存データを再照合してPENDING作成 |
| 既存challenge / verify / approve / reject / revoke | 既存Human step-up・期限・hash/version・台帳を再利用 |
| 既存POST /api/approval-requests/{id}/form-dispatch | 新方式を予約のみとして既存台帳へ保存 |
| 既存一覧 / cancel | 予約専用表示、開始前取消 |

準備はHuman owner/editorのみ。Agent credentialと混在Cookieは既存principal境界で拒否する。通常の汎用Proposal/Revision APIから任意adapter計画を登録することも拒否する。新方式のAgent準備APIは今回公開しない。本文・sender・endpoint・操作scriptを予約requestから上書きさせない。

## snapshot・証明・権限

新方式のProposalには独立したadapter_planを持たせる。Human ApprovalRequestのsnapshotへcanonical planとadapter_plan_hashを保存し、外側payload hashにも含める。Project/Company/Draft、文面、sender、入力値、form URL/POST先、profile fingerprint、plan版の一致を確認する。

既存のcompany/draft/profile/sender source hashを維持する。変更・期限切れは旧承認を失効させ、予約を拒否する。step-up証明はrequest/hash/version/Human/sessionにbindした既存方式を利用する。

準備保存時にProject/MemberとCompany/解析/送信者をlockし、予約時にも新方式のProject/Member権限を再照合する。役割変更後の古いキャッシュを使用しない。これは新しいOrganization/tenant実装ではなく、既存Project境界の維持である。

## 共有予約と実行禁止

ApprovedFormDispatch / FormDispatchSite、同じadvisory lock、承認unique・key unique、Company/form URLの重複保護、site間隔・共通上限を再利用する。別keyや通常フォームへ切り替えても既存予約・送信・UNKNOWNを迂回できない。確認POSTを持たない固定単回計画なので、form URLとPOST先で全siteを覆う。

予約作成は上限を増やしたり実行枠を消費したりしない。通常予約と同様、送信上限は共通設定で表示・管理し、開始時の制御は既存基盤に残す。今回の新方式は開始自体を許可しないため、送信上限内で実行できることの検証ではない。

worker claimはform_directの予約だけを取得する。worker側validateは既定でadapterを拒否する。新方式の出力は送信flagsがONでもexecution_enabled=false / reservation_only=true。

additive Migration `fd3f8cae4215`（親fc2e7b9d3104）で `ck_adapter_reservation_not_started` を追加する。adapter予約はqueued/blocked/cancelledだけを許可し、started_at・delivery_id・worker_idをNULLに固定する。既存fixture承認の非消費性とadapter承認のCONSUMED禁止を変更しない。

未開始予約の取消・期限切れ整理は既存処理で扱う。既存の通常フォーム向け再準備へadapterを流さない。再準備するときは予約を停止し、新しい保存データのpreviewから再承認する。UNKNOWNをリセットする機能は追加しない。

## UI

専用環境で有効なときだけ、保存済みフォーム準備に「管理下フォーム・予約のみ」を表示する。準備画面とHuman承認画面で計画JSON・hash・操作順・adapter版・対象を確認できる。送信者・文面・入力値は既存確認欄を使う。

承認後は単件予約でき、一覧には「予約のみ・実行未接続」と表示する。送信ボタンは追加しない。既存の一括通常フォーム操作から新方式を除外し、意図しない混在を防ぐ。

## 検証と既存互換性

専用PostgreSQLと合成データを使用した。新規試験はAPI準備→Human step-up→予約→取消、DBの開始禁止、flags ON時のclaim除外、変更/期限/権限/Agent/混在request、通常方式との重複、契約不一致の公開エラーを確認した。

2026-10-06の確認結果：

| 確認 | 結果 |
|---|---|
| Backend対象回帰9ファイル | 290 passed（151.60秒）。新規準備22件と既存契約・Human承認・予約・運用・site制御を含む。リポジトリ全テストの実行ではない |
| downgrade証拠保護 | 予約ありでdowngradeを拒否し、開始禁止制約を維持。追加後に対象試験を再実行し1 passed |
| Migration | 専用DBでhead → fc2e7b9d3104 → head成功、Alembic checkでModel差分なし。証拠がない状態の往復と、証拠ありの拒否を区別して確認 |
| Backend静的確認 | Ruff lint・変更ファイルformat・compileall成功。compileallは静的型検査の代替ではない |
| Frontend | typecheck・lint・build成功 |
| 画面E2E | desktop/mobile計8 passed（3.8分）。既存承認・fixture非実行・保存済み通常準備・新方式の準備→再認証→承認→予約→取消 |
| API起動 | 専用DBのUvicorn起動と実API経由のE2E成功。APIのmockで代用していない |
| 利用中環境の読み取り確認 | /api/healthはアプリ・DBともok、送信workerはexited。コード・DB・flagsを更新していない |

予約取得SQLにJSON条件を追加した初回検証では、3,000件の合成キューで取得が遅くなった。承認テーブルのdelivery_methodをjoinしてform_directだけを取得する条件へ修正した。修正後の専用負荷試験は2 passed：300件で20回取得の平均0.0406秒・最大0.0525秒、3,000件で平均0.0712秒・最大0.1093秒。UNKNOWNの再試行と外部リクエストは0。これは予約取得だけの合成測定であり、実フォーム送信速度・月間10,000件の達成証拠ではない。

初回のテスト失敗には、残存E2Eデータを含めた全体件数のassert、fixtureのCAPTCHA enum指定、画面内の複数ボタンに一致する確認selectorも含まれた。試験をProject単位と正しいenum・完全一致selectorへ修正し、画面試験中のソース変更を止めて8件を再実行した。上表は修正後の結果。

既存legacy payloadではadapter_plan=Noneをsnapshotから除外し、旧canonical形を維持する。既存ExecutionPlan v1とform_plan_fixtureを実行用へ転用しない。

## rollbackと次の工程

新設定OFFで準備・新規予約を停止できる。既存adapter予約があるDBのdowngradeは新Migrationが拒否する。監査や予約を削除して制約を外さず、schemaを保持する。利用中DBには適用していない。

次は110の工程3：管理下HTTPサーバーと既存PostgreSQLの開始/UNKNOWN/結果保存を接続する受入試験。新しい証拠guardを追加し、承認消費とUNKNOWN保存の原子性・競合・process停止・再POST禁止を確認する。今回はこの実行工程へ進まず停止する。
