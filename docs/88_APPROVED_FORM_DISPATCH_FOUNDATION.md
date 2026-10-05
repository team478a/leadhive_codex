# Human承認済みフォームの送信予約・実行基盤

## 今回のゴール

基準 `codex/integration@c714c4b`。前工程のフォーム承認準備を、送信予約と一度だけのワーカー試行へ接続する。実行は既定OFFを維持し、検証は架空フォームと専用DBのみ。Production deployment、実企業へのアクセス、メール/Form POST/テスト送信、Codex送信タスク起動は実施しない。

## 利用手順

1. 運用設定でフォーム送信者情報を保存する。
2. 企業のフォーム解析とフォーム用Draftを保存する。今回から解析結果にPOST先URLを保存する。旧解析結果のPOST先が空の場合は再解析が必要。
3. 承認キューのフォーム準備で、会社・文面・送信者・入力値・フォームURL・POST先を確認して提案を保存する。
4. パスワード再認証でHuman承認する。承認は最大24時間。
5. 「承認済みフォームの送信予約」で対象の内容を確認し予約する。初期設定では「実行OFF・送信されません」と表示され、外部通信なしで予約を保存する。
6. 未開始・事前確認中は取消可能。結果不明は再送しない。failed/blockedも自動再試行せず、新しい準備・Human承認が必要。

## 対応範囲と停止条件

対応は、保存済み解析がREADY/営業ALLOWED/CAPTCHAなし/通常処理対応、POST先確定、確認画面なし（confirmation_page=false）のフォームのみ。確認画面あり・段階未確定・JS/iframe/添付/CAPTCHA等はこの予約基盤で実行しない。確認画面の後の送信先と値は事前に固定できないため、既存の確認画面送信処理へ無条件に接続しない。

送信直前にstep-up証明、承認者と予約者のProject owner/editor権限、承認状態・期限・hash/version、Company/Draft/送信者/フォーム解析の変更、contact permission（Suppression・opt-out・連絡禁止・結果不明）、宛先の既存予約/送信、送信上限、実フォーム構造・POST先を再確認する。新しい提案の入力値を呼び出し側が上書きするAPIはない。Web上の文言は命令として扱わない。既存の営業禁止検出規則を実ページにも適用し、CAPTCHAは回避しない。

フォーム変更は保守的に停止する。旧snapshotに必要な送信者hash/POST先がない場合、新しい準備・再承認が必要。今回、form dependency hashにPOST先・確認画面状態・form_foundを含めるため、旧版のform提案も検証時に失効し得る。既存snapshotやMigrationは書き換えない。

## 原子的な予約と結果不明

`ApprovedFormDispatch`を追加。approval_idとidempotency_keyをそれぞれ一意にする。予約時にApprovalRequestのpayloadを複製しhashで固定。DB triggerで予約内容と試行開始日時・delivery紐付けの変更、履歴削除、終了済み予約の再キュー化を拒否する。

同じidempotency key・同じ内容の再要求は同じ予約を返す。キーの内容違い、同じapprovalの別キー、同じcompany/完全一致form URLの既存予約・送信・結果不明を拒否する。短いPostgreSQL advisory transaction lock（既存FormDeliveryと共通）で予約/試行開始を直列化する。外部I/O中にはlockを保持しない。

状態はqueued→checking→unknown→submitted/failed。checkingからblocked/cancelledも可能。POST開始前に、FormDelivery unknown保存・dispatch開始記録・ApprovalRequest CONSUMED・監査eventを同一transactionでcommitする。DBの承認triggerも、hash/versionの一致する永続送信記録なしのCONSUMEDを拒否する。送信後DB保存が失敗してもunknownが残る。

unknownは実行中・受付不明・中断を保守的に含む。期限経過・再起動でretryしない。通信/応答検証段階で受付を確認できなければunknownのまま。POST前の入力・構造エラーだけfailedとして区別する。checkingでworkerが失われた場合はlease期限後にblockedとし、自動再試行しない。取消はPOST開始前だけ可能。

外部サイト側のidempotency対応は仮定しない。保証するのは「同一Human承認からの重複試行を開始しない」こと。相手サイト内の処理、ネットワーク/OSの全障害、実機での複数worker競争を完全に実証したとは扱わない。

## API・既存機能の再利用

- POST `/api/approval-requests/{request_id}/form-dispatch`：expected_hash/versionとidempotency_keyのみ。Human owner/editor専用。準備・承認・予約では外部I/Oなし。
- GET `/api/projects/{project_id}/approved-form-dispatches`：50件既定、最大100件、offset付き。viewerは参照だけ可能。
- POST `/api/approved-form-dispatches/{dispatch_id}/cancel`：未開始/事前確認中の取消。Human owner/editor専用。
- Agent credential・Human Cookie混在・Agentによる予約/取消は既存principal境界で拒否する。
- FormDelivery、OutreachDraftApproval、Activity、既存フォームparser、SafeFetcher、完了判定、workerを再利用。成功時は実Humanの承認者/承認日時を既存営業履歴へ記録し、未対応/ターゲットの企業をアプローチ済へ更新する。SYSTEMをHumanとして承認した記録は作らない。
- 承認した本文を2,000文字で切り詰める処理を解消。送信ボタンの値が承認入力を上書きする場合はPOST前に停止する。hiddenのCSRF等と送信ボタン制御は既存parserから取得し、Human承認した営業入力とは区別する。

## 実行設定と初期上限

更新：一括承認・予約、DBに保存する管理者上限設定・一時停止を追加した。現在の操作は [89_FORM_BULK_APPROVAL_AND_LIMITS.md](89_FORM_BULK_APPROVAL_AND_LIMITS.md) を参照。以下の固定上限はこの基盤実装時の記録で、現在は同じ値を初期既定として変更可能。

`OUTBOUND_ENABLED=false`、`HUMAN_APPROVED_FORM_ENABLED=false`が既定。両方trueでなければ予約を実行しない。UIから有効化する機能は追加しない。初期は環境全体で直近24時間30試行、直近1時間5試行、最小間隔60秒、同時checking 1件。unknown/失敗した試行も上限に数える。

`LEGACY_FORM_DELIVERY_ENABLED=false`が既定。従来confirmedだけの通常送信、batch execute/retry、Codex送信タスク生成/結果更新、旧worker処理を停止する。古いコードは削除しない。旧処理の回帰テストだけが専用DBでlegacy opt-inする。承認済みフォーム実行が有効な場合はlegacy flagがtrueでも旧経路を拒否する。legacy opt-inは承認境界の保証対象外であり、今回のローカル運用では使用しない。

月10,000件の上限や継続運用は未達。次工程でフォーム候補の一括Human承認/予約、管理者による上限設定、サイト/送信者別制御、停止/休止、運用可視化を追加し、架空フォームで負荷・例外率を測定する。上限を増やす前に承認期限と例外対応量を検証する。

## Migration・復旧

追加revision `f8b25ea3c649`、親`f7a14d92b538`。ApprovedFormDispatchとFormProfile.action_urlを追加し、既存承認triggerにフォームの永続証拠を追加する。既存Migrationファイルは変更しない。downgradeはdispatch記録がある場合に拒否する。バックアップ復旧は相手サイトの受付を取り消さないため、復旧後にunknownを解除して送信しない。

この工程はインストール全体の送信者設定/上限を再利用する。tenant別送信者・tenant別枠の整備完了ではない。配布zipの再生成、Production導入、Dots/MCP接続は別工程。

## 検証記録

2026-10-05、専用PostgreSQL、HTTP/フォームmockで検証。実企業へのアクセス・実送信は行っていない。

- 新基盤テスト32件成功。最終追加の旧Codexキュー参照テストと既存batchテスト5件も成功。Agent拒否、Human step-up、hash/version競合、承認失効、二重予約、永続UNKNOWN、取消、DB不変条件、上限、確認画面の停止を含む。
- 関連Backend回帰テスト134件成功。その後の変更も含むフォーム関連56件成功。これらは対象が重複するため合算しない。全Backendテスト一括実行の結果ではない。
- PC／mobileの承認・準備・予約E2Eは6件成功。実フォームPOSTはmockのみ。
- Backend Ruff・compileall、Frontend typecheck・lint・build成功。
- 空の専用DBでupgrade→downgrade→upgradeとAlembic check成功。専用テストDBでもMigration/model差分検証成功。
- ローカルプレビューはバックアップ後にrevision `f8b25ea3c649`まで適用し、API／worker／Webを更新。API起動・DB接続を確認。企業100件を維持し、フォーム予約・フォーム送信・メール送信記録は各0件。
- APIとworkerのOUTBOUND／HUMAN_APPROVED_FORM／LEGACY_FORM_DELIVERY／AGENT_FEATURESはすべてfalse。実送信OFFを維持。

実サイトでの成功率・月10,000件の性能・外部サービス/OSを含む障害時の挙動は未検証。
