# 会社別文面のHuman承認・メール予約基盤

## 今回のゴール

月間10,000件を目指すため、既存の会社別Draft、A2承認基盤、EmailDelivery、SMTP、ワーカーを接続する。企業収集や文面生成と実送信を分離し、承認済みの固定文面だけを予約する。実メール・実フォーム・外部Agent接続・Production展開は実施しない。

これは到達率や月間10,000件の実送信を保証するものではない。配信サービスからの到達・バウンス・苦情イベント、返信照合の改善、実送信の負荷測定は別工程。

## 利用手順

1. 企業一覧または営業準備で、登録済みメールアドレスと会社別の文面を準備する。
2. 運用設定でSMTP送信者名・送信者メールを設定する。配信停止用の公開HTTPS URLは `PUBLIC_APP_URL` に設定する。キー・パスワードを文面や監査ログへ含めない。
3. 「承認キュー」でプロジェクトを選び「準備済みメール文面を取得」。対象の本文を開いて確認し、選択文面を承認待ちへ追加する。メールアドレスがない文面は追加できない。
4. 対象ごとの宛先・送信者・件名・本文・期限を確認し、チェックする。ログインパスワードで再認証し「一括Human承認」。単独承認・却下・取消も引き続き利用できる。
5. 承認済み項目を選び、予約名、24時間上限、1時間上限を入力して「送信予約」。承認操作だけでは予約・送信しない。
6. 予約の一時停止・再開・未実行の取消は同じ画面で行う。すでにSMTP通信へ進んだメールを取り消す機能ではない。
7. 「メール配信状況」で結果を確認する。結果不明はSMTP提供元の履歴を人が確認し、再送しない。

画面は50件ずつ確認し、APIは一括再認証・承認提案化を最大500件、一括予約を最大10,000件に制限する。月間運用は日々の新しい対象・新しい承認を小分けに扱う。既定の予約上限は24時間500件・1時間60件だが、実際にはSMTP設定の全体上限・間隔も適用する。既定SMTP上限100件/24時間を自動で増やすことはない。

## 承認期限と日次分割

承認期限は提案作成から最大24時間。長期予約のために期限を伸ばさない。日次上限に達した項目は待機し、有効期限に達すると `blocked` / `EXPIRED` となる。停止後の再開でも期限・取消を迂回できない。

期限切れ・却下・取消の元Draftは、再度承認待ち提案として登録できる。送信に消費済みの承認は再利用できず、既知のSMTP拒否に対する再実行も新しい提案・Human承認が必要。結果不明・送信済みの宛先は新しい承認を作っても予約を拒否する。この工程には、結果不明を解除するAPIや自動リトライを含めない。

## Feature flagと既存運用

`HUMAN_APPROVED_EMAIL_ENABLED=false` が既定。新しい予約は作れるが、このflagと既存の `OUTBOUND_ENABLED=true` の両方が有効になるまで新経路はSMTPを呼ばない。ローカル検証環境は両方OFFのまま。

新flagがONの場合、従来の `confirmed=true` によるメール予約・キャンペーン作成を409で拒否し、ワーカーは新しいHuman承認予約だけを実行する。従来の予約は保持される。flagがOFFの場合は従来ワーカーの選択条件を維持し、新予約は選択しない。既存のフォーム機能・Agent scope・認証分離は変更しない。従来メールにも、SMTP受付不明・ワーカー中断の `unknown` と再送禁止を適用する。

## 固定内容と安全確認

- ApprovalRequestの既存snapshot / SHA-256 / version / Human proofを再利用。
- 予約は別の固定envelopeを持ち、承認hash/version、会社、宛先、件名、本文、送信者、配信停止URLを含む。DB triggerで予約のUPDATE/DELETEを禁止。
- 送信前に承認の有効性、会社・元Draftの変更、承認者の現在のowner/editor権限、連絡禁止、登録済み宛先、連絡先品質、suppression、送信者一致を再確認。
- SMTP送信者が単一の現行構造に合わせ、同じ設置環境の宛先メール・宛先ドメインのsuppression / 同一メールの連絡禁止をプロジェクト横断でも適用する。権限のないプロジェクトの詳細は応答しない。Organization別SMTP設計は今回追加しない。
- 宛先の待機中・送信中・送信済み・結果不明を横断確認し、再予約を拒否。現段階の重複禁止には解除期間を設けず、保守的に停止する。
- 新経路では承認済み本文をそのまま送る。本文への配信停止URLの後付けはしない。固定配信停止URLを `List-Unsubscribe` / `List-Unsubscribe-Post` に設定する。本文に案内を入れる場合は承認前に含める。
- 配信停止URLのGETは確認画面のみ。POSTで停止。リンクスキャナーのGETで配信停止しない。
- 添付・emailのfield_values・件名300文字超・ヘッダー改行は未対応として予約を拒否し、黙って内容を落とさない。

## 実行と結果

1. PostgreSQL advisory lockで全体のclaim・送信予約を直列化。行ロック、承認IDのunique、予約キーのunique、予約当たり試行のuniqueを併用。
2. 全体の24時間上限・送信間隔、予約の24時間/1時間上限でclaimを制御。消費試行・結果不明も上限に含め、別予約で二重送信しない。送信直前にも現在の件数上限を確認。
3. `EmailSendAttempt=STARTED` と `ApprovalRequest=CONSUMED` と監査記録を同一transactionでcommitする。DB triggerは一致する試行証跡なしのCONSUMEDを拒否する。
4. このcommit後に初めてSMTP通信。Message-IDは予約のdelivery UUIDから固定する。ただしMessage-IDだけで外部SMTPの重複を防ぐと主張しない。
5. 結果を保存。受付後のDB障害・タイムアウト・ワーカー中断は保守的にUNKNOWNへ送る。UNKNOWNを自動再送しない。

|状態|意味|
|---|---|
|queued|期限・上限の範囲で待機|
|running|ワーカーが取得済み|
|sent / SMTP_ACCEPTED|SMTP DATA受付を確認。相手への到達は未確認|
|failed / FAILED|接続前の失敗、またはSMTPの明示拒否|
|unknown / UNKNOWN|送信されたか確定できない。自動/既存retry禁止|
|blocked|承認・権限・送信者・連絡禁止等で停止|
|cancelled|未実行を取消|

明示的なrecipient/sender/DATA拒否はFAILED。DATA送信中の切断はUNKNOWN。DATA受付後にQUITだけ失敗した場合は受付済みとして扱う。事業上の到達・返信・商談とは分離する。

## 追加構造

Migration `f4c83a61d205`（parent `e3b7d92f410a`）、`f5d92b70e316`（宛先重複確認のindex）。既存Migrationは変更しない。

- BulkApprovalProof: Human / session / 対象hash-version集合にbind。5分、single-use、失敗でも消費。ユーザーごと5分間に5challengeまで。
- ApprovedEmailBatch: Project、Human作成者、予約キー、要求hash、名前、状態、日次/毎時上限。
- ApprovedEmailReservation: EmailDelivery、ApprovalRequestへの一対一参照、固定envelope、hash。
- EmailSendAttempt: 予約当たり一回の試行、固定Message-ID、payload hash/version、結果と時刻。
- 既存OutreachAuditEventへ承認・予約・実行消費・結果・停止・一時停止/再開/取消を追記。

Migrationのdowngradeは承認proof/予約履歴がある場合に拒否し、証跡を削除しない。戻す場合は送信を停止し、Migration前backupと旧イメージを復元する。既存のDBや配布パッケージを自動で入れ替えない。

バックアップ復元時には一括再認証challengeも失効する。復元したSTARTED試行はUNKNOWNにし、メールの再開判定にUNKNOWN/blockedも含める。別PCの旧稼働環境や古いバックアップとSMTP側履歴の差分は、人が照合する。バックアップに残っていない外部送信をDBだけで復元・否定できるとは扱わない。

## API

すべて既存Human Cookie認証とProject owner/editorを要求（一覧はviewer可）。Agent credentialまたはCookieとの混在を拒否する。

- GET `/api/projects/{id}/approval-email-drafts?limit=50&offset=0`
- POST `/api/projects/{id}/approval-requests/from-drafts`
- POST `/api/projects/{id}/bulk-approval/challenge`
- POST `/api/projects/{id}/bulk-approval/verify`
- POST `/api/projects/{id}/bulk-approval/approve`
- POST `/api/projects/{id}/approved-email-batches`
- GET `/api/projects/{id}/approved-email-batches?limit=50&offset=0`
- POST `/api/approved-email-batches/{id}/pause|resume|cancel`

予約要求は `items=[{request_id,expected_hash,expected_version}]`、`name`、`idempotency_key`、`daily_limit`、`hourly_limit`、任意のtimezone付き `scheduled_for`。同じキーと同じ内容の再要求は同じ予約を返し、異なる内容では409。

## 検証と限界

検証は専用PostgreSQL `_test` DB、模擬SMTP、外部送信OFFのPC/モバイルE2Eで行う。実企業・実SMTP・実フォームへ送信しない。10,000件のschema上限を、10,000件の実配信完了と混同しない。

月間運用開始前の次工程は、送信サービス側の到達・バウンス・苦情イベントと、自動停止基準の接続。SMTP受付数だけで運用を拡大しない。DNS認証・配信サービスの利用条件・宛先収集方法の適合性は送信者側の運用設定として確認する。

### 2026-10-05 検証結果

- Backend全体の途中実行: 287件中284件成功、3件失敗。Migration head固定、送信OFF時のretry、送信OFF時のworker呼出の3件を修正した。
- 承認基盤・worker等の関連126件: 124件成功、2件失敗。期限切れテストのworker lease条件、復元処理のSQL結果参照の2件を修正した。
- 修正後の承認メール・送信OFF・バックアップ/復元テスト: 63件すべて成功。最終的な再認証監査追加後にも、一括承認の7件を再実行して成功。
- 新規承認メールテストは31件。最終状態の全体収集は296件。最終296件を一度の全件実行で完走したとは扱わず、上記全体実行と修正後の関連再実行を区別する。
- PC/モバイルE2E: 12件すべて成功。一括承認、予約、一時停止、再開、取消、未送信、既存の認証・フォーム解析・CSV取込・営業準備を確認。
- Backend Ruff、Python compile、Frontend typecheck/lint/build成功。追加ファイルのRuff format check成功。
- 空の専用DBでupgrade → downgrade → upgrade、Alembic model差分確認成功。監査・予約履歴があるDBへのdowngrade拒否もテスト。
- API/worker/WebのDocker buildとローカル起動を確認。ローカルDBは事前バックアップ後に `f5d92b70e316` へ更新。企業100件、AI解析完了9件を保持。メール/フォーム送信、予約、試行は0件。実送信・新経路実行・Agent feature flagはいずれもOFF。

10,000件の実データ負荷試験、実SMTP受付、到達・バウンス・苦情の接続、公開配信停止URLへの外部到達確認は未実施。今回の合格範囲は承認・予約・制御と模擬SMTPの安全性である。
