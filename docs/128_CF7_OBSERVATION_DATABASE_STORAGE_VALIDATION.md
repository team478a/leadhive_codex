# O3-B — 管理下の非認可観察証拠・DB保存

## 1. 範囲と基準

基準 `codex/integration@8dde886e854615362e87f9adcf09596628146ebd`、実装commit `8f3dcfa`。O3-A2の保存契約を使い、専用test DBへ診断証拠・保存/退役履歴を保存するserviceとDB guardを追加した。稼働DBへmigrationは適用せず、HTTP取得・UI・Agent・承認・配送へ接続していない。

O3全体や実サイト用Observerの完了ではない。保存serviceは未登録lab `scripts/cf7_observer_lab/store.py` に置き、applicationのrouter/workerからimportしない。実行には `CF7_OBSERVER_STORAGE_LAB=1` とDB名末尾 `_test` が必要。既定OFF。

## 2. Model・Migration

- `backend/app/model_form_observation.py`: FormObservationEvidence / FormObservationEvent。既存modelsへ登録。
- 新revision `0263cd208659`、parent `0152bc1f7548`。既存revisionの変更なし。
- OperationJobに `cf7_observation` typeをadditiveに許可。active同Project/type一件の既存制約は維持。
- CF7ObservationのCONTROLLED_FIXTURE CHECK、候補の非実行・予約・CONSUMED禁止は変更していない。

証拠はProject/Company/Job/run/attempt/lease worker/開始Human、観察時刻・期限、診断snapshotとcanonical text・SHA-256を保存する。JSONB snapshotとcanonical textの内容一致・native PostgreSQL SHA-256一致をDBで確認する。canonical文字列が送信認可を意味することはない。

期限24時間上限、byte上限、false固定、unknown状態、source/版、reason/decision、structure/controlのallowlistと整合性を検査する。INSERTは専用test DBだけ。fixture IPは検査用8.8.8.8/1.1.1.1のみを受理し、実通信の証明として扱わない。

## 3. 保存とatomic ledger

`save` はenvelopeを再検証し、Project編集権限と開始Humanを確認する。Job→Company→Projectとmembershipをlockし、現行source、Job type/status、cancel、worker/attempt/lease、payloadのCompany/run/Humanとの一致を確認する。DB INSERT triggerも現在の行と権限を再確認し、直接SQLからの迂回を拒否する。

現在Company source hashはProject/Company/website URL/contact URLを含むserver SQLで生成する。営業メモ変更では失効させず、URL/Project変更では旧sourceを使用できない。

証拠INSERT、SYSTEMのSAVED event、Job completed/countsを同一transactionにstageする。serviceはcommitせず、呼出側がcommit/rollbackする。DBのdeferred constraint triggerはSAVED一件とJob完了を要求し、service内でも明示検査する。SAVEDのunique index、Jobの結果変更guardで履歴と結果の不整合を防ぐ。

同じJob/run/attemptの同一hash/id再保存は既存行を返し、違う結果は停止する。実DBのrow lockとunique制約を使用するが、今回の重複試験は順次再呼出しと直接SQLの競合制約確認。複数プロセスによる同時保存の全障害パターンを検証済みとは扱わない。

## 4. 退役・親データ・rollback

`retire` はowner/editorとexpected hashを確認し、HUMANのRETIRED eventを追加する。証拠snapshotを更新しない。退役後の再使用を保存serviceが拒否する。保存判定/履歴時刻はDB clockを使い、PC/DBの微小な時計差で正当なeventを未来扱いする問題を避ける。

両tableはUPDATE/DELETE/TRUNCATEをstatement triggerで拒否する。actor/project/company/job/evidence/hash、principal、event/reasonの整合をDBで確認し、Agent表記や不正actor等を拒否する。SYSTEM eventのactor_user_idは開始Humanの識別で、principal_type=SYSTEMと区別する。Human Approvalに成りすまさない。

親Company/Jobの削除はFKで拒否。証拠ありCompanyのProject移動、JobのProject/type/payload付替え、完了結果/counters/leaseの変更も拒否する。通常の営業メモなど観察依存外の編集は維持する。merge/delete APIの専用409案内・保持方針は次工程で確認する。

証拠/eventまたはcf7_observation Jobがあるdowngradeを拒否する。空の専用DBだけmigration往復を行う。稼働環境rollbackはflag OFF・実行入口未接続を維持し、将来証拠のあるschemaをdropしない方針。DB owner/superuserによるtrigger削除まで防ぐものではない。

## 5. worker・APIの停止境界

通常workerのclaim/recoveryから新typeを明示除外する。outbound flagがONでも観察Jobを実行・自動再queueしない。既存 `/api/operations/{job_id}/retry` も新typeを409で拒否する。既存のJob一覧/cancel/acknowledgeの権限境界は維持する。

観察を開始するAPI、receipt upload API、read API、Agent API、診断UIは追加していない。保存serviceのreceiptはO3-A2のsynthetic生成データで、O2 GET→取得receipt→DBのadapterも未実装。機能flagだけで実サイト取得や送信を開始できない。

## 6. 検証記録

専用DB `leadhive_o3b_20261006_test` を今回新規作成し、稼働DB/既存専用DBとは分離して検証した。接続情報・passwordは出力していない。

- 最終Backend選択回帰 **209 tests成功（313.18秒）**。新保存40件を含む。新規試験では保存と台帳/Job完了、順次重複/異なるhash停止、現行cancel/lease/worker/attempt/source/Project/type、flag OFF/viewer、raw SQLでの偽権限/未知状態/NULL/余分なvalue/hash/所有関係、append-only三操作、台帳なし拒否、rollback、退役、actor/Agent表記/重複SAVED、権限変更/営業メモ、worker除外、API retry拒否、親データ/Job binding/downgrade保護を確認した。
- 上記実行後、親保護試験へ完了Jobのsuccess_count変更を追加し、該当 **1 test再実行成功（4.52秒）**。209件と重複するため210件へ加算しない。
- O1/O2/O3-A2 lab **40 tests成功（15.493秒）**。新保存DB群と別の試験。管理下loopback GETまたはofflineだけで、GET→DB→UIの通し試験ではない。
- 新migrationのupgrade→downgrade→upgrade成功、Alembic checkでModel差分なし。最終checkも成功。headは0263cd208659一つ。
- model_form_observation/storeの2ファイルにmypy `--check-untyped-defs --follow-imports=silent` 成功。Backend app全体と新migration/test、observer labのRuff lint、変更ファイルformat、compileall、diff確認成功。全アプリのmypy成功とは扱わない。
- 新保存の初回試験でPL/pgSQLのCASE括弧不足、次の試験で退役時刻のPC/DB差による拒否を検出し、修正後に上記209件を実行した。失敗した初回を成功件数へ加算しない。
- 専用DBで証拠/event/利用者が0件、他接続なしを確認して、今回作成したDBだけを削除した。稼働DB・既存専用DBは変更していない。
- 最終稼働API healthはstatus/databaseともok、送信workerはexited。実企業DNS/HTTP、実メール/Form送信、deployment、配布物更新なし。

Backend regressionの対象：新保存試験、worker concurrency、operations、Human Approval Foundation、CF7 candidate DB guard/preparation/revision、contact permission。O1/O2/O3-A2のlab試験も確認。Frontendは変更がないためbuild/E2Eを再実行しない。新保存serviceは既存DBの権限境界を再利用するが、HTTPのHuman/Agent認証分離を新endpointで検証したものではない。

## 7. 残る作業と次のゴール

次はO3-Cの管理下専用Job/read API・取得receipt生成・診断表示への接続。最初にread境界と非認可表示を固め、trusted GET境界が生む時刻/hash/TLS/robots結果と現行DB情報を結合する。任意clientのverified=trueを信頼しない。

今回の台帳はSAVED/RETIREDのみ。開始/取得失敗/cancel/lease回収のstage eventはJob接続工程に残る。stale観察Jobは通常workerで自動回収せず、手動診断・停止が必要。専用claim/recovery・admission・完全な並行障害試験・read APIでの鮮度判定・親削除/merge案内は未実装。

Organization/tenantモデルは追加していない。実企業の禁止/CAPTCHA観察を既存送信permissionへ反映するnegative/review hold、一般URL取得・robots完全対応・parse隔離・保持/削除方針も別blockerのまま。新保存結果を既存FormProfile/CF7Observation/ApprovalRequestへ自動昇格しない。実サイト取得・配信worker再開・予約・consume・実送信へ進まない。
