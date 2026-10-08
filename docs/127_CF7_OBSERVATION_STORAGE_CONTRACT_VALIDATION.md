# O3-A2 — 非認可の観察保存契約・offline検証

## 1. 完了範囲

基準 `codex/integration@396692f4c54ec9faea927d64d644f3f5248aced2`、実装commit `1eb6b1c`。docs/126のO3-A2として、純粋な保存envelope・診断projection・canonical hash・current binding比較を実装した。O3全体の保存/API/UI実装完了ではない。

追加：

- `scripts/cf7_observer_lab/storage_contract.py`: Pydanticのstrict/extra forbid/frozen契約、サイズ制限、診断用projection、hash、保存bytes再検証。
- `scripts/cf7_observer_lab/test_storage_contract.py`: 架空HTML/取得receiptによるoffline試験。

O1/O2のコードを変更していない。applicationから未登録。DB/HTTP/worker/Agent/API/承認/送信には接続していない。

## 2. データと不変条件

BindingはProject/Company/Job、CompanyとJobそれぞれのProject、run/lease worker/attempt/開始Human、現在Company source hashを保持する。同Project、非zero UUID、正のattempt、固定job type `cf7_observation`、固定管理下URLを要求する。

Snapshotは観察の版、時刻、decision/reason、未検証状態、取得summary、原文/robots/parserのhash、診断summaryを結合する。Envelopeのsnapshot_hashはsort_keys/compact UTF-8 JSONのSHA-256。原文parser hashと保存snapshot hashを区別する。

- source=STATIC_HTML_UNVERIFIED、provenance=OWNED_TLS_FIXTURE、各版はallowlist。
- eligible_for_approval=false / execution_allowed=false。ALLOWED / CAPTCHA_NONE / CONTROLLED_FIXTURE / 未知版を受け付けない。
- decision/reason/sales/CAPTCHA/structure有無の整合性を検査する。禁止・CAPTCHA・未対応の結果には実行structureを付けない。
- UTC、観察時間0〜30秒、観察後0より大きく24時間以内の期限。未来の結果、期限切れ、retiredはcurrentとして拒否する。
- private/mixed等のIPを拒否。取得summaryのstatus/media/body bytes/robots bytes/durationを制約する。

`build` は既製Observation JSONを受け取らず、渡されたbytesをO1 parserへ送り、projectionを生成する。`decode` は保存bytesを型・版・hash・expected binding・期限と照合する。`encode` / `check_current` も再検証し、通常のfrozenだけでなくmodel_copy等で未検証値を混入させた場合に停止する。

これはpureな比較で、実DBのProject権限・lease・cancel・最新sourceを取得したりlockしたりするものではない。将来の保存serviceがexpected binding/server時刻/retirementを信頼できるDBから読み、同一transactionで検査する必要がある。

## 3. 保存projection・上限

form_count、CF7版、mapping=HUMAN_REQUIRED、controlの順序/name/label/type/required/初期checked、redacted/truncatedを保存する。最大50controls、name100文字、label250文字。hidden値、checkbox_value等の入力value、REST root/feedback/declared action、raw HTML、robots原文は保存用JSONに含めない。

秘密を示す語、メールらしい文字列、電話番号らしい数字列、制御文字をname/labelで検出した場合は `[REDACTED]`。長い安全な文字列は上限で切り詰める。**全個人情報を検出できる保証はない。** 日本語の個人名/住所や未知の機密値など、パターンだけで判断できないtextは残り得るため、実データ保管前に保持/削除/アクセス方針の追加確認が必要。hashに原文を復元できる内容は入らないが、hash自体もアクセス制御の対象にする。

JSON envelopeはUTF-8最大32KiB。decodeはJSON parser前にdepth8/構造要素カウント2048を制約し、duplicate keyを拒否する。未知field、hash改ざん、schema不整合は固定エラーで停止し、Pydanticのraw input付き例外をuserへ渡さない。50controlsの小さな診断は受理、長い日本語labelで32KiBを超えるprojectionは拒否する。件数制限だけでbyte上限を代替しない。

## 4. 取得receiptの信頼境界（未接続）

今回の `build` のbody/robots/pinned IP/時刻/mediaは**offline試験のsynthetic取得receipt**である。robots許可・TLS identityのsummaryフィールドは契約上固定だが、この関数が実際のrobotsやTLSを確認した証明ではない。取得を行わないため、その安全確認は呼出元の信頼境界の責任となる。

O2のFetchResultからこのenvelopeを生成する自動adapterは未実装。一般clientからのJSON upload/receipt upload APIもない。外部clientがhashを再計算してもexpected binding/schemaを迂回できない一方、SHA-256は署名や認証ではなく、信頼されたserverと同等の記録を自称するcallerを識別する機能でもない。

O3-B/Cで保存へ接続する前に、実GET境界で生成する時刻/body hash/metadata/robots判断と、DBのProject/Job/lease/source情報をserver側で結合する必要がある。Agent提供のtls_verified=trueやrobots_allowed=trueを信頼して保存してはならない。

## 5. 検証結果

Windows / Python 3.12、既存backend開発環境。依存追加なし。

- observer lab **40 tests成功（最終11.241秒）**。既存O1解析14件、O2管理下GET13件、新保存契約13件。subcaseは別件数へ加算しない。
- 新13件：roundtrip/決定的hash、入力value/hidden/endpoint除外、機密name/label、切詰め/初期checked、禁止/CAPTCHA/未対応の非認可結果、偽権限/未知版/未知field/状態矛盾、hash改ざん/frozen/model_copy、Project/Company/Job/run/lease/attempt/Human/sourceの現行binding、他Projectへ付替えて再hashした偽装、期限/退役/未来/UTC/時間上限、取得bytes/media/private IP、JSON bytes/depth/要素/duplicate/malformed/秘密を含まないerror、50controlsとUTF-8上限、原文/robots/取得metadata変更へのhash結合を確認。
- 新保存契約試験はsocket.getaddrinfo/socket.connectを失敗させて実行。HTTP/DNSを必要としない。既存O2試験だけは管理下loopback TLS/HTTPを利用し、実企業へは接続しない。
- observer/fetch/storageの3ファイルにmypy `--strict --follow-imports=silent` 成功。Ruff lint/format、compileall、git diff確認成功。
- 既存pinned TLS/DNS全33件はO2時点の検証を維持し、今回は再実行していない。基盤コード変更なし。
- Backend全回帰、Frontend tests/build/E2E、migration往復は今回再実行していない。application/Frontend/DB/migration変更なし。
- 稼働API status/databaseともok、送信workerはexitedのまま。設定・配布物・稼働DBを変更していない。

## 6. 次のゴールと残る境界

次はO3-B：専用test DBで新証拠/eventモデルとadditive migration・保存serviceを実装し、append-only/Project/Job/lease/idempotency/期限をDBレベルで検証する。今回のschemaを既存CF7Observationへ押し込まず、CONTROLLED_FIXTUREや候補非実行ガードを維持する。

Job type追加・親削除/mergeとの整合・証拠ありdowngrade拒否・現行lease/cancel/sourceをlock下で再確認・証拠/event/job状態の同一transactionはまだ未実装。診断UI/APIも未実装。

docs/126で指摘した、新観察の禁止/CAPTCHA結果を既存送信permissionへ反映する境界は未解決。保存契約だけでその問題を修正済みとは扱わない。O3-B/Cも管理下test専用、実企業取得・予約・consume・送信・配信worker再開には進まない。
