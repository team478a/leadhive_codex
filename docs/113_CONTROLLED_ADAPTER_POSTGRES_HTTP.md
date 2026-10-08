# 管理下フォームとPostgreSQL承認・UNKNOWN基盤の接続実証

## ゴールと対象

110の工程3。基準codex/integration@7ba8c3f。保存済み計画のHuman承認と予約を、管理下HTTPサーバーの単回POSTへ接続して検証する。実CF7、実企業、JavaScript確認画面、SMTP、Codex-assisted実行、Dots、AUTONOMOUS、利用中環境とWindows配布の更新は対象外。

## 実行境界

- `form_adapter_lab_execution_enabled` は既定false。準備flag、outbound、human_approved_formのすべてと、設定DB・実接続先DBの `_test` 条件を要求する。
- 通常workerの `claim(db)` は引き続きform_directだけを選ぶ。テスト側が明示して呼ぶ `claim(db, controlled_lab=True)` と `controlled_form_execution.run` に限って新方式を扱う。worker registryへ登録しない。公開send APIも追加しない。
- appにはtransportのProtocolだけを置く。具体的HTTP transportとプロセス起動は `backend/tests/controlled_adapter_transport.py` / `controlled_adapter_process.py` に限定する。appからtestsをimportしない。
- 試験transportは `FORM_ADAPTER_LAB=1` を必要とし、固定fixture URLを一時HTTPサーバーの127.0.0.1へ置換する。HTTP retry=0、proxy環境参照なし、redirect追従なし、timeout 0.5秒、POST応答64,000 bytes上限。任意URL・caller指定portを公開APIへ出さない。Production SSRF guardにlocalhost例外は追加しない。
- 112のUIは予約専用のまま。試験bridgeを通常UIの送信機能へ接続せず、実行器未接続・予約専用の表示を維持する。

## 共通処理との接続

1. 保存済み承認・sourceを検証しtransactionを閉じる。
2. 管理下サーバーの固定GET /contactでfixtureの構造情報を観測する。これは合成descriptorであり、実DOM解析の代替証拠ではない。
3. 共通 `approved_form_worker.begin` が共有advisory lockと予約lockを取得する。新方式のProject/Member/Company/Draft/profile/fields/senderをlockし、権限・両payload/plan hashとversion・有効期限・Human証明・source変更・suppression・営業可否・CAPTCHA・重複・共通上限とsite間隔を再照合する。
4. `FormDelivery=unknown`、`ApprovedFormDispatch=unknown/started_at/delivery_id`、`ApprovalRequest=CONSUMED`、開始auditを同じtransactionでcommitする。失敗ならPOSTしない。
5. immutableな計画とattempt IDだけをtest transportへ渡してPOSTする。明確な合成受付証拠だけsubmittedにする。
6. 共通 `finish` が同worker/UNKNOWNを再照合して結果・Activity・auditを保存する。結果保存に失敗しても開始時UNKNOWNを保持する。

`FormDelivery.delivery_method=adapter`、`OutreachDraftApproval.approval_type=form_adapter` と記録し、directやCodexの実績へ偽装しない。既存参照APIのenumとフロント型も対応する。企業画面では「管理下テストフォーム」と表示する。

## DBと証拠保護

additive Migration `fe409dbf5326`（親fd3f8cae4215）。既存Migrationを変更しない。

- FormDeliveryへnullable `execution_authorization` を追加。approval ID、外側payload hash/version、adapter plan hashのみを保存し、credential・cookie・応答全文を保存しない。
- fixtureのCONSUMED禁止は維持。adapterは `_test` DBだけで開始可能とし、対応するUNKNOWN予約とUNKNOWN送信記録・Project/Company/Draft/profile・固定endpoint/adapter版・Human再認証証拠・承認hash/version・execution_authorizationが一致しないCONSUMEDをtriggerで拒否する。直接INSERTによるCONSUMED偽造も拒否する。
- adapter送信記録は試験DBとauthorizationを必要とする。記録の対象・方式・構造・authorizationは変更/削除不可。UNKNOWN→pendingへの変更を禁止する。既存予約snapshotとauditのimmutable/append-only制御も維持する。
- DBはcanonical JSONのSHA-256を独自再計算しない。DBの対応証拠照合と、Serviceのcanonicalization・hash検証を区別する。DB管理者によるtrigger無効化まで防ぐ仕組みではない。
- checking中の停止・取消ではadapterのworker所有権を解除する。未開始停止はblocked/cancelledで保存でき、UNKNOWNをqueuedに戻さない。

## UNKNOWNと受付証拠

form ID・attempt IDが一致し、stage=final / status=fixture_accepted / HTTP 200 / JSON schemaが正しい場合だけsubmittedとする。曖昧な200、別form/attempt、確認段階、mail_sent、validation error、redirect、切断、timeout、巨大/重複キー/壊れた/truncated応答はUNKNOWNを維持する。

fixture_acceptedは管理下試験だけの受付証拠。実CF7のmail_sent、相手のメール到達、閲覧を確認したとは扱わない。UNKNOWNは未送信ではなく、人間による受付確認が必要な状態。自動retry・方式fallback・新承認による再送はしない。

## 検証

2026-10-06の確認結果。通常の試験は専用DB上のtransactionでrollbackする。実commit/process停止/競合試験だけは試験ごとに新しい `leadhive_lab_<uuid>_test` DBを作り、Human session/step-upと承認・予約を実APIで作成し、別connection/別processから確認する。終了時に当該fixtureが作成したDBだけを廃棄する。利用中DBを削除・初期化しない。

| 確認 | 結果 |
|---|---|
| 対象Backend回帰 | 324 passed（422.54秒）。既存契約・Human承認・準備・予約・運用・site制御と新方式を含む。既存opt-in HTTP試験30件はこのrunではskip |
| 新方式の最終再検証 | 41 passed（231.34秒）。上のrunと一部重複。実行直前の変更検知、API結果参照、audit/commit失敗、downgrade拒否を追加して再確認 |
| 既存opt-in HTTP試験 | FORM_PLAN_LAB=1で別途実行し30 passed（49.31秒）。SQLite試験と新しいPostgreSQL試験を混同しない |
| 実プロセス停止・競合 | 41件のうち3件。実commit直後/POST前のkillで追加POST 0、HTTP受付直後のkillでPOST 1・再POST 0。別connectionで予約/送信UNKNOWN・承認CONSUMEDを確認。並列2workerでもPOST 1 |
| Migration | 専用DBでhead→fd3f8cae4215→headとAlembic check成功。新しい試験DBも各回全Migrationを適用・check。試行証拠ありのdowngradeは拒否 |
| Backend静的確認 | Ruff lint、変更21ファイルformat、compileall成功。compileallは静的型検査ではない。Alembic checkの列/型差分確認とDB制約の実SQL試験を区別する |
| Frontend | typecheck・lint・build成功 |
| 画面E2E | desktop/mobile計8 passed（1.7分）。既存Human承認、fixtureの非実行、通常Draft準備、新方式の準備→step-up→承認→予約→取消 |
| API起動 | 専用DBでUvicorn起動成功、実APIを使った上記E2E成功 |
| 利用中環境 | 読み取り確認でアプリ/DB healthともok、送信workerはexited。コード・Migration・flags・配布パッケージを更新していない |

リポジトリ全Backend試験を通したという報告ではない。管理下HTTPの成功を実CF7への送信成功・実運用速度・月間10,000件の達成証拠として扱わない。

初回検証で、checkingからblockedへ移す際のworker IDと工程2の非開始制約が衝突したため、adapter未開始停止時にworker IDを解除する処理を追加した。回帰試験の全DB件数assertが以前の取消済みE2E予約も数えていた箇所は、対象Company/Projectへ限定した。証拠を削除して試験を通す方法は採らない。

## rollback・停止点・次のゴール

lab実行flag OFFと通常worker非登録により試験経路を停止できる。新Migrationのdowngradeはadapter試行・CONSUMED・worker取得の証拠が残る場合に拒否する。証拠があるDBではschemaを保持し、監査台帳を削除してdowngradeしない。

利用中DB・flags・停止worker・保留企業・Windows配布は維持する。工程3で停止する。次は工程4の「実CF7 protocol・token・受付証拠・fingerprint・SSRF・同意の事前設計と検証」であり、実企業への有効化や月間10,000件の送信達成を意味しない。
