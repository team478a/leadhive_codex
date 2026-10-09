# Phase 3: 管理用確認処理と永続レビューledger

## 基準・範囲

基準 `main@25b494dea4223c0496404707aff1839ea64f70f0`（PR #31統合後）。ブランチ `codex/controlled-confirmation-ledger`。

二段階フォームを既存single-post実行契約へ隠して追加しない。今回は外部送信OFFの専用試験環境に限定した、匿名fixtureの確認結果を扱う内部サービスを実装する。HTTP transport、public API、UI、worker登録、dispatch、ApprovalRequestのCONSUMED遷移は追加しない。

最初のPOST前の承認制御を準備する工程だが、POSTそのものは未実装である。サービスの戻り値はPOST権限として使えない。

## 再利用

- ApprovalRequest: 承認済みpayload、hash/version、期限、依存元変更時の失効。
- HumanApprovalProof: 実行者と同一Human・同一有効sessionの再認証証跡。
- Contact permission: suppression、連絡禁止、営業禁止、CAPTCHA、未解析・UNKNOWN等を既存の正本で判定。
- OutreachAuditEvent: 追記専用ledger。新規テーブル・migrationなし。
- PR #30の匿名HTML parser: `controlled_confirmation_contract.py`へ移動。既存テストは互換importを使用。

## 有効化条件

すべて必要:

1. `form_confirmation_lab_enabled=True`（新規設定の既定値はFalse）。
2. `FORM_ADAPTER_LAB=1`。
3. 接続中のPostgreSQL DB名が `_test` で終わる。
4. outbound / legacy form deliveryともFalse。
5. 有効なBrowser AuthSession、owner/editor、同じHuman/sessionに結びついた使用済み再認証proof。
6. 有効なAPPROVED payloadと、二段階confirm_postの匿名ExecutionPlan。
7. 現在のCore permissionがALLOWED。

Agent tokenをHuman sessionへ変換する処理はない。公開Agent APIへは接続しない。条件を満たしても送信はできない。

## 処理

`start`: ApprovalRequestを行ロックし、expected payload hash/versionを照合する。開始ledgerを同じtransactionに保存してcommit後にreview IDを返す。同じ承認の再開始は拒否する。

`record`: 保存済み開始IDを照合し、匿名確認応答を既存parserで検査する。確認期限はサーバー側の開始時刻から5分とApproval期限の早い方。結果はREVIEW_REQUIRED / BLOCKED / UNKNOWNであり、execution_allowedは常にFalse。生HTML、本文、tokenは保存せず、token hashと固定reason/statusのみledgerへ記録する。結果の再登録を拒否する。

`consume_review_token`: 同じ承認行をロックし、Human/session、現在の承認とCore permission、結果、期限、token hash、使用済みledgerを再確認する。一回だけレビュー終了イベントをcommitする。ApprovalRequestはAPPROVEDのまま、dispatchやDeliveryは作らない。

UNKNOWN / BLOCKEDではtoken消費・再開始を拒否する。確認結果が欠落した場合でも自動retryしない。確認途中のpayload改訂・失効・Core permission変更でも停止する。

## 安全性の限界

このAPIのない内部サービスは**匿名fixtureのレビュー**である。HTMLとtokenを呼び出し側から受け取るため、実サイトが発行した信頼済み応答・token bindingの証明にはならない。外部GET/POST前のrate limit、sender/destinationの実行検証、multipart wire bytes、ネットワークのSSRF保護、確認後の最終POSTは未実装。

行ロックと同一transactionのledger書き込みでレビューtokenの競合を直列化する設計。今回のテストは同一sessionでの再取得・再利用とcommit失敗を確認し、独立プロセスの並列競合や実運用DB再起動を実測したものではない。これらはHTTP実行接続前の必須検証として残る。

本番フォームには転用しない。実候補の用途・予算・必須入力に関するHuman確認も別途必要。通常workerや既存のsingle-post adapterの契約を変更しない。

## 検証

新規16ケースで正常レビュー、一回限りの結果登録/token消費、UNKNOWN、内容変更、外部URL、未承認、flag OFF、outbound ON、無効session、hash/version不一致、連絡禁止、CAPTCHA、期限、誤ID、他Project/viewer、commit失敗、default OFFを確認。

関連承認・multipart・A2 securityスイート134件PASS。Backend全体Ruff / format（468ファイル）と、新規サービス2ファイルのmypy PASS。DB test fixtureの既存migration upgrade / Alembic model diff PASS。新規サービスのmypyもCIへ追加した。GitHub ActionsはPRで全体回帰・E2E・migration往復・配布チェックを確認する。

## 次の実装境界

次工程では、draft/profile/senderに結びついた別の二段階実行契約、信頼できる管理下応答、POST前のCore safety/上限、独立processの同時実行テストを先に完成させる。既存single-post adapterをそのまま二段階化しない。

今回の判定: 管理用の非送信レビュー基盤はGO。実フォーム送信はNO-GO。

実サイトアクセス、検索/AI API、実営業Approval、メール/フォーム送信、送信worker起動、merge/deployは0。テストDBの匿名Approval/proof/ledgerのみ使用。
