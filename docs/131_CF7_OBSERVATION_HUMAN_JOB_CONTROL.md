# O3-C2b — 管理下観察のHuman開始・停止・監査境界

## 1. ゴールと基準

基準は `codex/integration@d57218aab914308f923d6fb22519a15c401cdc81`。C2aの未登録runnerを維持し、管理下専用のHuman queue API、停止・期限切れ回収、append-only lifecycle ledger、診断画面の操作、独立OSプロセスによるclaim検証を追加する。

APIリクエストはJob登録・状態参照・停止・回収だけを行う。GET取得をAPI内で起動しない。通常worker/schedulerへの登録、実企業URLの許可、Form POST、メール送信、Human Approval/dispatch接続、稼働環境のmigration・設定・配布物更新は行わない。

## 2. APIとHuman境界

| API | 動作 | 権限 |
| --- | --- | --- |
| GET `/api/companies/{id}/form-observation-jobs` | 直近Job、固定理由、直近50件の監査記録、操作可否 | Project閲覧者 |
| POST 同URL | queuedの登録だけ、202 | Human owner/editor |
| POST `/api/form-observation-jobs/{id}/cancel` | queuedをcancelled、runningに停止要求 | Human owner/editor |
| POST `/api/form-observation-jobs/{id}/recover` | lease失効/欠落のrunningをfailed/cancelledへ終了 | Human owner/editor |

既存Browser AuthSession/current_userを使用する。Agent Authorization、Human Cookieとの混在、未ログイン、他Project、viewerの更新を拒否する。POST bodyは空objectのみ。URL、HTML、run ID、worker、任意payload、confirmed等は受け取らない。Job ID/run ID/開始者はserver側で確定する。

開始には3つの `CF7_OBSERVER_*_LAB` flagがすべて1、実DB名が `_test`、新台帳導入済み、website/contactが既存のmanaged.example固定URLであることが必要。default OFF。DB名だけでは無害なデータである保証にならないため、専用DB・合成Companyだけで検証する。

停止・回収はflagがOFFになっても可能。ただし専用DBと新台帳、現行Human権限は必須。Job rowをlockして更新し、Project/既存membershipのshare lockと最新権限の再読込を行う。停止を繰り返してもeventを増やさない。既存 `/operations/{id}/cancel` もcf7_observationだけ同serviceへ委譲し、台帳を抜けない。既存retry APIの拒否は維持する。

## 3. 台帳・migration

additive revision `0374de319760`、親 `0263cd208659`。既存revisionは書き換えない。

`FormObservationJobEvent` / `form_observation_job_events` を追加。project/company/job/run/attempt/worker、HUMANまたはSYSTEM、Human actor ID、event、固定reason、before/after status、DB時刻を保存する。body、URL本文、credentials、例外文字列は保存しない。

- QUEUED / CLAIMED / CANCEL_REQUESTED / CANCELLED / COMPLETED / FAILED / RECOVERED。
- Humanの登録・停止・回収と、runnerの開始・保存・失敗・回収を区別する。
- 各serviceはJob更新とevent insertを同じtransactionで行う。成功時は証拠、既存SAVED台帳、Job completed、新COMPLETED台帳をまとめてcommitする。
- DB triggerでupdate/delete/truncateを拒否し、insert時に専用DB・現行Job/company/project/run/attempt/worker/after statusを確認する。
- 生SQLによるすべてのJob更新を自動記録するtriggerではない。通常の公開操作と専用runnerのservice境界を記録する。DB特権者の操作や将来の新経路は別途監査が必要。
- 旧workerのrun/type/worker/attempt競合時は後継Jobを変更しない。結合情報が壊れたJobの自動修復・再実行は追加しない。

既存 `FormObservationEvent` のSAVED/RETIRED、証拠契約、非認可固定値は維持する。台帳の外部キーにより対象Project/User/Job等の削除が制約される。将来の保持期間・削除設計は別工程であり、既存ログを削除可能に緩めない。

## 4. 画面

既存の静的フォーム観察履歴に、検証対象・操作権限がある場合だけ登録/状態更新/停止/期限切れ終了を表示する。通常企業・旧API/旧schemaの未対応状態では操作を出さず、従来の履歴表示を維持する。

「登録だけでは取得は始まらない」「専用検証runnerが必要」を明記する。自動polling・常駐runner・送信ボタンはない。Job状態と診断証拠の有効性、営業可否は別表示のまま。

HTTP/TLS/robots/parser/保存失敗は現時点ではOBSERVATION_FAILEDに集約する。画面でも詳細分類未対応と明記し、理由が特定できたかのように表示しない。

## 5. 検証

2026-10-06、`leadhive_o3c2b_20261006_test` と画面専用 `leadhive_o3c2b_ui_20261006_test` で検証。

- 新API/独立process/runner/storage/read/operations/worker concurrency/contact permissionの選択回帰107件passed（131.27秒）。追加したDB結合偽装4件を含む最終API suiteは20件passed（18.60秒）。
- desktop/mobileの観察履歴・操作E2E 4件passed（1.9分）。画面操作APIはmock。
- Backend/lab Ruff、変更ファイルformat、3ファイルのmypy（check-untyped-defs / follow-imports=silent）成功。Frontend typecheck/lint/build成功。
- 新revisionのupgrade → downgrade親revision → upgrade → model差分check成功。独立process用の空DB全体upgradeも成功。
- TestClient API起動と画面専用API起動を確認。稼働中APIのread-only healthはstatus/databaseともok、通常workerはexitedを維持。
- 2つの専用DBでUser/Company/Project/証拠/台帳/承認/EmailDelivery/FormDeliveryの0件と接続残存なしを確認して、今回作成したDBのみ削除。独立process用DBの残存も0件。

初回の重複登録後Sessionエラー、process用DB名のPostgreSQL長さ制限、画面専用空DBのmigration未適用を修正して再検証した。GitHub全体検証はpush後の完了報告のrunを参照する。

追加APIテストはHuman/Agent/mixed、Project/role、default OFF、空body以外拒否、重複登録後の停止、flag停止後のcancel、recover条件、繰返し、台帳rollback、update/delete/truncate拒否、旧schema、pagination、内部文字列の非公開を確認する。

独立プロセスのテストはUUIDを含む専用DBを新規作成・migrationし、同じcommitted Jobに対し2つのPythonプロセスと独立接続から同時claimする。1つだけが取得してattempt=1/CLAIMED一件となること、勝者がGETせず終了した後にleaseを失効させてHuman回収できること、証拠・承認・配送が0件であることを確認して、作成したDBのみ削除する。強制killの全タイミングやネットワーク中断を網羅するテストではない。

画面テストはdesktop/mobileで操作・理由表示・二重登録防止・送信操作の不存在を検証する。操作APIはmockで、実APIの認証/DB保証はBackendテストで別に確認する。

## 6. 次の停止点

管理下のqueue/controlまで。稼働中API/UI/DBには適用していない。

次候補は管理下runnerの明示起動・終了手順と失敗理由分類、実プロセスのclaim/cancel/commit競合・強制終了の拡張検証。実サイトの開放には、新観察negative/review holdをCore permissionへ結合すること、Organization/保持・削除、parse隔離、実サイトの許可管理等が先に必要。送信・通常worker再開・Dots接続へ進まない。
