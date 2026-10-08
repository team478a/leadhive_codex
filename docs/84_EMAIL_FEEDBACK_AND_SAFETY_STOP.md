# メール配信結果・安全停止

## ゴールと範囲

月間10,000件へ拡大する前に、SMTP受付と到達通知を分け、恒久不達・苦情・配信停止を記録し、異常時にProjectのメール予約を停止する。既存Human Approval、固定payload、UNKNOWN再送禁止、SMTP上限、IMAP、フォームは維持する。実メール・実フォーム・配信サービス接続・公開URL設定変更は実施しない。

この工程は共通通知境界の実装であり、特定のメール配信サービスのAPIとの接続完了ではない。通常SMTPだけでは到達・苦情通知は取得できない。利用サービス決定後、提供元の署名・通知形式を検証して共通形式へ変換するadapterと、公開HTTPS受信URLが必要。今回の通知受信はdefault OFF。

## 操作

「メール配信状況」でProjectを選び、配信結果・停止理由・最新50件の証跡を確認する。

1. 人が配信サービスの履歴を確認した場合は「確認済みの配信結果を登録」を開く。
2. 送信履歴のメールと宛先、結果を選択して登録。日時は人が確認した時点を記録する。
3. 誤登録を含め証跡を削除・更新するAPIはない。訂正は追加証跡で残し、連絡禁止を自動解除しない。
4. 安全停止中は、所有者が原因・履歴・対象を確認し、ログインパスワードで再認証して停止を解除する。
5. 解除後も各予約は一時停止のまま。必要な予約を承認キューから別途再開する。期限・権限・suppression・重複確認を迂回しない。

Editorは確認結果を登録できる。Viewerは参照のみ。停止解除はProject所有者のみ。Agent credentialは登録・解除不可。解除の失敗5回で15分停止。停止日時をexpected値として照合し、古い画面からの解除と再実行を拒否する。

## 状態の分離

EmailDeliveryとEmailSendAttemptはSMTP通信の正本。EmailFeedbackEventは配信結果の追加証跡。`delivered` を登録してもUNKNOWNをSENTに変えず、自動再送も可能にしない。

|結果|扱い|
|---|---|
|delivered|相手サーバーへの到達通知。受信箱への格納・開封・読了・営業成果の保証ではない|
|hard_bounce|恒久不達。該当宛先メールをSuppressionEntryへ追加|
|soft_bounce|一時不達。証跡のみ。自動再送・連絡禁止解除はしない|
|complaint|苦情。該当宛先を連絡禁止にしProjectのメールを停止|
|unsubscribe|該当宛先を連絡禁止にする|

メール1件の不達で会社ドメイン全体・電話番号まで禁止しない。新経路の既存送信前guardは同じSMTP設置環境の宛先suppressionも確認する。後からdeliveredが届いても過去の苦情や連絡禁止を解除しない。通知の到着順に依存した楽観的な状態上書きをしない。

既存IMAPのbounce/unsubscribe分類と連絡禁止処理は引き続き動作する。正確な送信IDが確認できない受信をこの台帳へ推測で紐付けない。既存公開配信停止URLも独立した連絡禁止の正本として維持する。IMAP・公開URLの全記録を新台帳へ移し替える工程ではない。

## 初期の安全停止条件

LeadHive独自の保守的な初期値であり、配信サービスの利用条件を代替しない。

- 苦情通知が1件以上。
- 結果不明の送信履歴が3件以上。
- 送信試行10件以上、恒久不達3件以上、かつ恒久不達/試行が5%以上。

直近24時間を対象とする。通知は受信日時、試行・UNKNOWNはstarted_atを使う。通知件数は送信ID単位で重複排除する。同一通知IDの再要求は同じ証跡を返し、内容変更は409。解除後は解除時点以降を新たな監視区間とするが、過去の証跡・UNKNOWN・suppressionは保持する。停止は時間経過で自動解除しない。

停止時は該当Projectのqueued承認メール予約をpausedへ変更。同じ状態を新予約・再開・送信直前にも強制する。従来メール経路も停止中は送信しない。送信前チェックと新通知の書込みはProjectロックと既存予約ロックで直列化する。既にDB commitを終えてSMTPへ進んだ通信を取り消せるとは保証しない。別Projectまで自動停止する機能はこの工程に含まない。

## 通知API

Human CookieとProject権限:

- GET `/api/projects/{id}/email-health`
- GET `/api/projects/{id}/email-feedback?limit=50&offset=0`
- POST `/api/projects/{id}/email-feedback`
- POST `/api/projects/{id}/email-health/review`

共通署名通知:

- POST `/api/webhooks/email-feedback`
- `EMAIL_FEEDBACK_WEBHOOK_ENABLED=false`、`EMAIL_FEEDBACK_WEBHOOK_SECRET`は32文字以上の専用secret。空・短い・無効なら404。SMTP/APIキーを使い回さない。
- Cookie・Authorizationを持つ要求は拒否。Human/Agent認証とは別の通知専用境界。
- `X-LeadHive-Timestamp`: 現在Unix秒。時刻差最大300秒。
- `X-LeadHive-Signature`: HMAC-SHA256(secret, timestamp + "." + **送信したraw JSON bytes**) の小文字64桁hex。
- JSON最大16KiB。未知フィールド拒否。本文・パスワード・生のprovider通知を保存しない。

JSON: `event_key`（adapterで安定した通知ID、英数字/_.:-、100文字以内）、`delivery_id`、`recipient`、`kind`、timezone付き`occurred_at`、`message_id`。Providerの場合、永続化済みEmailSendAttemptの固定Message-IDと宛先を必須照合。送信前の日時、未来5分超、未知の送信履歴を拒否する。通知IDの再送で状態や件数を増やさない。

通知のHMACを再計算する中継adapter自身は信頼境界である。任意の受信JSONへ署名を付けるだけの公開中継にしない。提供元の署名・account・destination・Message-IDの照合が必要。現時点では具体的providerを実接続していない。

## DB・監査・復旧

追加Migration `f6e03c81f427`（parent `f5d92b70e316`）。既存Migrationは変更しない。

- EmailFeedbackEvent: Project、送信ID、source HUMAN/PROVIDER、通知ID、結果、宛先、発生/受信日時、確認者。DB triggerでUPDATE/DELETE拒否。
- EmailHealthState: Project、安全停止、理由、停止日時、確認者・確認日時、再認証失敗制御。
- 既存OutreachAuditEventへ結果・停止・解除・再認証失敗を記録。同じtransactionで証跡・suppression・停止を保存する。

履歴のあるdowngradeは拒否する。復旧は送信停止・backup・旧イメージの手順を維持する。復元しても外部サービスに存在する配信結果を消したことにはならず、再開前にサービス履歴と照合する。

## 未実施

実配信・サービス固有adapter・外部webhook到達・10,000件負荷測定・送信者全体/Organization全体の停止・開封追跡は未実施。今回の安全停止はProject単位である。実送信、Agent、通知受信のflagはローカル環境でOFFを維持する。

## 2026-10-05 検証結果

- Backend全体308件の実行で306件成功。新規の閾値テスト2件は、同じDraftに複数EmailDeliveryを作る誤ったfixtureで失敗した。fixtureを分け、追加12件の全再実行が成功。既存296件は全体実行で成功している。最終308件の単一全件再実行とは区別する。
- 署名・期限・Message-ID・宛先・入力サイズ・未知フィールド・再受信・Human Cookie混在・Agent拒否・viewer/editor権限・再認証失敗制限・append-only・UNKNOWN保持・停止・閾値を検証。実SMTPは呼ばず模擬送信のみ。
- E2E全14ケースの初回は12件成功。連絡禁止の宛先をテスト間で共有するfixtureと、実行中のファイル更新によるログイン確認失敗を修正し、関連6件を再実行。5件成功、スマートフォンの配信登録は表示幅の問題で失敗した。
- 長いメールアドレスで送信履歴のflex行が端末幅を超える問題を修正。入力の展開はReactのボタンで制御し、タッチ操作と実際の端末幅を確認する。修正後のPC/モバイル配信結果テスト2件はすべて成功。その他の12ケースは上記実行で成功。最終14件の単一全件再実行とは区別する。
- Backend Ruff/compile、Frontend typecheck/lint/build成功。空の専用DBでupgrade → downgrade → upgrade、Alembic model差分確認成功。Compose構文を設定の検証用placeholderで確認（起動・送信なし）。
- ローカルDBをバックアップしてから追加Migration適用。企業100件、AI解析済み9件を保持。メール/フォーム送信と配信結果は0件。API/worker/Webの起動と送信・通知受信flagのOFFを確認。
