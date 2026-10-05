# 匿名CF7相当契約のHTTP・プロセス停止試験

2026-10-06、基準 `codex/integration@3cbd0c3`。前工程の匿名契約を実際のloopback TCP/HTTPで試し、永続UNKNOWNと同一試行からの再POST禁止を確認する。実CF7プロトコルの実装、LeadHiveの承認・ワーカー接続、本番のフォーム対応拡大ではない。

## 実装位置と隔離

追加コードはすべてbackend/tests内。

| ファイル | 役割 |
|---|---|
| fixture_plan_runner.py | 明示的opt-inの試験用実行器、固定loopback transport、試行台帳 |
| fixture_plan_http.py | 匿名JSON契約を受付する127.0.0.1の一時サーバー |
| fixture_plan_process.py | 台帳保存後／受付後に終了させる専用subprocess |
| test_fixture_plan_http.py | HTTP応答・競合・再要求・プロセス停止の受入試験 |

FORM_PLAN_LAB=1を明示しない限り実行器は拒否し、受入試験もskipする。既存のFORM_HTTP_LABや外部送信flagsは有効化しない。appからのimport、API公開、worker登録はない。匿名ExecutionPlanのfixture_cf7/version1/単回submitだけを使う。JS確認画面の契約はこの実行器では拒否。

transportは論理URL https://fixture.example/submit のPOST一種類のみを受け付け、物理的には固定127.0.0.1:試験サーバーportへHTTPで接続する。未知origin/scheme/path/query、GET、実サイト宛先は拒否。DNS/proxy設定を使わず、HTTPTransport retries=0、follow_redirects=false。これは論理URLをfixtureへ置き換える試験であり、TLS証明書・実サイトDNS・Production SSRF guardの実証ではない。

本番APIへ任意URLや操作scriptを渡せる機能は追加しない。実行器のloopback portは試験コードのみが供給する。

## 台帳と外部試行の順序

tmp_path配下の *_fixture_test.sqlite にSQLite試験台帳を作る。これは一時的な試験用schemaであり、LeadHive DBのModel/Migrationではない。

1. 計画hash/version、adapter、試行ID、key、port、requestサイズを検証する。
2. BEGIN IMMEDIATEとunique制約で同一key/attempt、company、form URLの競合を止める。
3. UNKNOWN行をcommitし、connectionを閉じる。ここまでHTTP clientを作らない。
4. 固定URLへ一回だけPOSTする。
5. 同じform ID/attempt ID、final、fixture_acceptedという完全一致の合成証拠を受けた場合だけSUBMITTEDへ更新。

同じkey・同じhash・同じattempt IDの再要求は既存状態を返し、通信しない。別key、別attempt、変更payloadの再試行は拒否する。台帳にはID・key・宛先・digest・statusだけを保存し、本文・sender・tokenは保存しない。サーバーの入力記録は合成データだけをメモリに保持する。

試験台帳のUNKNOWNは実行中・未受付のままのprocess消失も含む。一度予約したら受付0でも自動retryしない。結果書き込み失敗後も、新しいconnectionからUNKNOWNを参照して再POSTしない。

## 応答契約と停止条件

成功はHTTP200・application/json・サイズ64KB以内・既知の厳密schemaだけ。JSONの重複keyを拒否。確認段階、validation_error、実CF7を連想させるmail_sentも合成契約では成功と扱わない。既知のfixture_acceptedを実CF7の応答と同一視しない。

201、HTML、未知status、別form/attempt、曖昧な200、破損JSON、巨大応答、Content-Length不一致、受付後切断、timeout、307 redirectはUNKNOWN。例外から再POSTや別adapterへのfallbackを行わない。request/response上限64KB、HTTP timeout0.5秒は試験用の固定条件であり、本番性能や実サイトtimeout設定の提案ではない。

## 検証結果

FORM_PLAN_LAB=1、専用PostgreSQL _test DBを指定してpytestを起動。通常conftestのMigration/model差分確認は既存構造について実行されるが、この試験の試行台帳はtmp_pathのSQLiteを使用する。

新規30ケース成功（29.99秒）：

- 受付成功と15種類の失敗/曖昧応答で、保存状態・再起動相当の台帳再open・3回の再要求を確認。全て受付記録1回のまま。
- 4並列clientで同じ試行を要求して受付1回。別key/attemptやpayload変更も追加受付なし。
- POST前の台帳commit、結果保存失敗後のUNKNOWN維持、事前検証失敗時の台帳0/受付0、opt-in拒否、未知通信6パターンの拒否。
- 実subprocessを予約commit直後とサーバー受付直後にkill。新しいconnectionでUNKNOWN永続を確認し、再要求後も受付0/1回を維持。

FORM_PLAN_LABを解除した最終回帰はtest_form_execution_plan.py / test_execution_plan_approval.py / test_fixture_plan_http.pyで73件成功・lab 30件skip（64.04秒）。opt-in時の30件成功と、既定OFF時のskipを区別する。既存fixture承認の非消費性・送信予約拒否も維持。全Backend・全E2Eの実行結果として扱わない。

Backend全app/testsのRuff、新規4ファイルformat check、app/tests compileall、Frontend typecheck/lint/build成功。UI・アプリ実行経路に変更がないためブラウザE2Eは再実行していない。Production import/登録がないこともソース参照で確認した。

利用中API health/database=ok。読み取りruntime検証で解析1.7・保留2、企業100、FormProfile139、active job0、送信関連3テーブル各0、flags全OFF、worker=exitedを維持。利用中DBへの書き込みなし。

## 達成していないこと

SQLiteの試験結果は、Production PostgreSQLのtransaction、既存ApprovalRequest消費、HumanApprovalProof、OutreachAuditEvent、rate/site制御、worker lease、Project/tenant権限の接続実証ではない。ここにはHuman承認を偽装する記録もPolicyAuthorizationも作らない。OS全体の障害・電源断・バックアップ復旧は試験対象外。

前工程のform_plan_fixtureは引き続き非実行型。DBのCONSUMED禁止や通常フォーム予約の拒否を緩めず、このHTTP試験へ接続しない。旧direct承認を転用しない。実CF7のAPI・nonce・hook・CAPTCHA・受付成功・メール到達は未検証。相手側のexactly-onceも保証しない。

アプリコード・DB Model・Migration・API・UIは今回変更なし。利用中DB/API/Web/worker、Windowsパッケージも未更新。実企業GET・入力・POST、SMTP、Codex送信、外部AIは行わない。Cecil/PALIOの技術保留は維持する。

## 次の工程

試験で確認した一回の実行条件を、既存PostgreSQLの承認・予約・UNKNOWN基盤へ接続する最小設計を作る。非実行型fixture承認を消費可能に変更するのではなく、別の実行契約・新しい承認が必要。安全条件・DB不変条件・通信境界の受入基準が固まるまで、実サイト対応やワーカー登録は開始しない。
