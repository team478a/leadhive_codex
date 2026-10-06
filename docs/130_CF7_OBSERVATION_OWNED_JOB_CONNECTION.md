# O3-C2a — 管理下TLS取得と観察Job保存の接続

## 1. 基準・今回のゴール

基準commitは `bf9f81a16c41ff45879c266704c9c0df8251a8cf`。O3-C2を、C2a（専用Job serviceと取得・保存の接続）とC2b（公開開始API、追加監査台帳、運用上の権限・中断・競合確認）に分割した。今回完成させるのはC2aのみ。

既存のHuman Approval Foundation、通常worker、Core permission、フォーム送信、Model、migration、Frontend、稼働DB、配布物は変更しない。通常workerによる `cf7_observation` のclaim/recovery除外と、既存retry APIの拒否を維持する。

## 2. 実装位置と実行境界

`scripts/cf7_observer_lab/job_runner.py` は未登録の内部検証用service。app/router/通常worker/schedulerからimportしない。CLI、公開開始API、Agent API、常駐workerは追加しない。

必要な条件は以下すべて。

- `CF7_OBSERVER_JOB_LAB=1`
- `CF7_OBSERVER_GET_LAB=1`
- `CF7_OBSERVER_STORAGE_LAB=1`
- 接続DB名が `_test` で終わる
- websiteが `https://managed.example/`、contact URLが `https://managed.example/contact/`
- 開始者が現行Projectのowner/editor

flagは未設定ならOFF。DB名検査は汎用sandboxや実データの不存在の保証ではないため、今回作成した専用DBと管理下合成データだけで検証する。service引数のUser IDは内部呼出しの識別子であり、Browser AuthSessionを検証する公開Human APIではない。将来の公開APIではcurrent_userとAgent/mixed拒否を必須にする。

## 3. Jobの状態・競合

`enqueue` は既存OperationJobをqueuedで作り、project/company/run/開始者を結合する。既存の同Project/type active unique indexを利用する。queued時のsource hashを別途保存しない。claim時に現在の固定URL条件を再確認してBindingを確定する。

`claim` は指定Job ID/type/queuedをrow lock + SKIP LOCKEDで取得する。worker UUID、attempt、開始時刻、60秒leaseを設定する。cancel済みはcancelled、権限・source・binding不整合はfailed/CLAIM_REJECTED。すでにrunning/completed/failedのJobはclaimしない。

`run` は5秒の既存GET予算を使用し、robots→contact→静的解析→保存契約→DB保存の順に実行する。HTTPの前後・chunk境界で短い新Sessionからflags、lease、worker、attempt、run、Project、開始者の権限、Company source hashを照合する。ネットワーク待機中にservice側のDB transaction/row lockを保持しない。

保存時は既存storeとDB guardで再照合し、証拠・SAVED event・Job completed/countsを同一transactionでcommitする。解析結果がBLOCKED/HUMAN_REQUIRED/UNSUPPORTEDでも診断保存としてcompletedになり得る。success_countは送信可能件数ではない。

失敗はtransactionをrollbackし、同一Project/type/run/worker/attemptのrunning Jobだけをfailed/cancelledへ変更する。旧workerは引き継がれたJob、別type、別runの状態を変更しない。例外本文、HTML、credentialsをerror_messageへ保存せず、固定codeを使う。network/robots/TLS/parser/DB保存失敗の詳細分類は未実装でOBSERVATION_FAILEDへ集約する。

`recover` は専用serviceの明示呼出しのみ。lease失効または欠落したrunning観察JobをWORKER_LOST、cancel済みをCANCELLEDで終了し、requeue・retry・GET・成功証拠生成を一切行わない。heartbeat、常駐回収、queued timeout、自動新runは実装しない。

## 4. 実取得receiptと保存内容

既存 `fetch.py` のFetchResultに、実際にGETしたbody/robots bytesと検査済みmedia typeを一時的なメモリ内receiptとして追加した。body/robots/解析objectはreprから除外する。これらはAPI response・DB・Job payloadへ保存しない。

serviceがDB clockから時刻を生成し、既存contract.buildでhash、bounded/redacted projection、非認可の固定値を生成する。caller提供のbody/HTTP成功/verifiedフラグを公開APIから受け入れる経路はない。

GET-only、固定host/path、TLS hostname/certificate verification、public DNS検査とpin、redirect/retry/proxy/cookie/Authorization禁止、robots保守判定、サイズ・header・encoding上限を維持する。テストのDNSは8.8.8.8として合成し、実際のdialだけをループバックTLS fixtureへ置換する。実企業・8.8.8.8への接続ではない。保存metadata/hashは承認証明や送信権限ではない。

キャンセルは協調式であり、active socketは共有deadlineまで待つ可能性がある。DB問い合わせやHTML parseをOS/process timeoutで強制停止する保証はない。

## 5. 確認するテスト

`backend/tests/test_form_observation_runner.py` は実TLS fixture + PostgreSQLを利用し、以下を確認する。

- 実GETのbody/robots hashとbyte count、非認可固定値、台帳/Job完了のatomic保存。
- 再claim・completedの再runでGET・証拠が増えないこと。
- 3flagのdefault OFF、他Project/viewer、固定URL、active一件制約。
- robots取得後のcancel/source/role/lease/worker/flag/run/type/payload変更でcontact GETを止め、旧workerが後継状態を変更しないこと。
- TLS不信・robots禁止・HTTP失敗の停止と自動retryなし。
- lease失効を処理中断に見立てた明示recovery、遅れて戻るworkerの停止、queued cancel。
- 取得後のsource変更でreceiptを破棄、保存後commit前の例外で証拠・台帳・完了状態をrollback。
- ApprovalRequest/EmailDelivery/FormDeliveryが新規生成されないこと。

DBテストは外側rollback transactionに隔離する。claim競合の確認は逐次二重claimとunique制約であり、複数実プロセスの同時claim/crash検証ではない。success ledgerのみ既存append-onlyを利用する。開始・停止・回収のappend-only台帳は未実装で、失敗codeは既存のmutable OperationJobに残る。

## 6. 検証記録

2026-10-06、専用DB `leadhive_o3c2a_20261006_test` で確認。

- 新規runner 21件とstorage/read/worker concurrency/operations/contact permissionの回帰を合わせ、90件passed（61.88秒）。
- 管理下TLS取得・保存契約等のlab unittest 40件passed。
- BackendとlabのRuff、変更ファイルformat検査、runner/fetchのmypy（check-untyped-defs / follow-imports=silent）成功。
- 専用DBのmigration upgrade/check、API回帰のTestClient起動、稼働中APIのread-only health確認成功。
- 検証DBのUser・観察証拠・台帳・EmailDelivery・FormDeliveryは0件、接続残存なしを確認して、この工程の専用DBのみ削除。通常workerは停止を維持。

Frontendは変更しないため、ローカルのUI build/E2Eを再実行しない。push後のGitHub全体検証は完了報告のrunを参照する。

## 7. 次工程と停止点

次はC2b：管理下専用の公開開始境界、開始/停止/recovery台帳のadditive設計、現行Human sessionからの権限・cancel操作、複数Session/実プロセスでのlease/commit競合、固定理由の診断表示をまとめる。

C2aだけでO3-C2全体や実運用の取得機能が完成したとは扱わない。Core permissionが新観察のnegative/review holdを参照しない問題、実データ保持/削除、Organization境界、実サイト許可、parse隔離は未解決。実サイト開放・メール/Form送信・通常worker再開・Dots接続へ進まない。
