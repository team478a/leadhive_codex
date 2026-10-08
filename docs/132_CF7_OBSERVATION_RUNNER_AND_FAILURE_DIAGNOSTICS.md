# O3-C2c: 管理下runnerの起動・終了と失敗診断

## 1. 範囲

基準は `codex/integration@d5a67520b75217991eae793e3d687ab9972b5ae1`。
Humanによる管理下観察の登録・停止・回収、非認可証拠、append-only台帳を再利用する。
今回は合成サイト専用の1件実行CLIと固定失敗分類を追加する。
実サイトの開放、常駐処理、通常worker、送信、承認生成、Dots接続は対象外。
稼働中API/UI/DB、配布パッケージには適用しない。

## 2. 失敗分類

API・DB・画面では例外文字列や取得本文を公開せず、閉じた理由コードのみ扱う。

| 理由コード | 意味 |
| --- | --- |
| RUNNER_STOPPED | runnerの協調終了要求でcancelled |
| OBSERVATION_TIMEOUT | 取得deadline超過 |
| OBSERVATION_DNS_FAILED | resolverが失敗 |
| OBSERVATION_UNSAFE_DNS | 公開IP制約を満たさない |
| OBSERVATION_TLS_FAILED | TLS証明書・接続検証失敗 |
| OBSERVATION_NETWORK_FAILED | その他のネットワーク接続失敗 |
| OBSERVATION_HTTP_REJECTED | HTTP 200以外。redirectも追従しない |
| OBSERVATION_RESPONSE_INVALID | header、media type、encoding、長さ、サイズ等の不整合 |
| OBSERVATION_ROBOTS_DENIED | robotsがcontactの取得を禁止 |
| OBSERVATION_ROBOTS_INVALID | robotsの規則を安全に判定できない |
| OBSERVATION_PARSE_FAILED | 静的HTML解析が例外終了 |
| OBSERVATION_CONTRACT_INVALID | 保存envelope生成に不整合 |
| OBSERVATION_STORAGE_FAILED | DBアクセス・保存段階の失敗 |
| OBSERVATION_FAILED | 詳細分類できない失敗。既存履歴も維持 |

TLS/timeoutは型付き例外の有限context chainから区別する。サイト文章やエラー本文の部分一致による分類はしない。
HTTPの具体的status番号はこのコードだけから断定できない。
静的解析が未対応フォームという診断を返した場合、解析例外とは区別し、非認可の診断として保存できる。
DBが停止して失敗記録自体ができない場合、failed保存を保証できない。復旧後にlease失効とHuman回収を確認する。

## 3. CLIの前提と再現方法

`scripts/cf7_observer_lab/owned_runner.py` は常駐workerではない。
既にHuman APIで登録されたqueued Jobを1件だけclaimし、終了する。
DB作成、migration、User/Companyの作成、queue登録、retry、recoverはCLIが行わない。

必要条件:

- `TEST_DATABASE_URL` と `DATABASE_URL` は同じローカルPostgreSQL専用DB。
- DB名は `leadhive_observation_run_<12〜24桁のhex>_test`。接続query optionは拒否する。
- additive migration `0485ef420871` 適用済み。
- 合成Companyのwebsite/contactは既存 `managed.example` 固定値。
- 3つのlab flagがすべて1。default OFFは維持する。
- Human owner/editorが既存Browser AuthSessionで登録した、未claimのJob ID。

準備済みの専用環境でのみ、リポジトリrootから実行する（秘密値は引数へ渡さない）。

```powershell
$env:CF7_OBSERVER_GET_LAB = '1'
$env:CF7_OBSERVER_STORAGE_LAB = '1'
$env:CF7_OBSERVER_JOB_LAB = '1'
backend/.venv/Scripts/python.exe scripts/cf7_observer_lab/owned_runner.py --owned-fixture --job-id <queued-job-UUID>
```

実行時に自分でloopback TLS fixtureを起動・破棄する。合成public pin `8.8.8.8` は証拠の検証用値で、dialはfixtureのloopback socketへ限定される。外部DNS・実サイトへの接続は行わない。
TLS検証は無効化しない。成功ケースではfixtureのCAだけを信頼し、TLS失敗ケースでは未信頼CAの拒否を検証する。
シナリオは `success / robots-denied / http-rejected / response-invalid / tls-failed / timeout` の固定選択。
URL、method、body、credentials、任意接続先の指定はできない。GETのrobots→contact以外は実行しない。

最も簡単な再現は、専用 `_test` DBを `TEST_DATABASE_URL` に指定してbackendから以下を実行する方法。
テストfixtureが別のUUID付きDBを作成し、migration、合成User/Project/Company、Human login/queue、CLI実行、API読取、配送0件確認、DB削除まで行う。

```powershell
.venv/Scripts/python.exe -m pytest tests/test_form_observation_launcher.py -q
```

既存の営業データ入りDBや稼働中APIへlab flagを設定しない。

## 4. 終了・回収

Ctrl+C / POSIX SIGTERMは終了Eventを設定する。stage/chunk境界で確認し、同じJobのlease/worker/run/attemptが有効な場合だけ、SYSTEMのRUNNER_STOPPEDとcancelledを同一transactionで記録する。
ネットワーク待ちは共有deadlineまで待つことがある。DBやparser全体のOSレベル停止時間を保証するものではない。

SIGKILLやWindows TerminateProcessでは終了処理が動かない。runningが残った場合、lease失効後にHuman owner/editorが既存recover API/画面操作で終了させる。
回収はretryや取得を開始しない。遅延workerは結合/lease変更を検出して後継状態を変更しない。
停止前にclaimされなかったJobはqueuedのまま残る。fixture初期化失敗やDB停止も、必要に応じてHuman回収を行う。

stdoutは固定JSONコードのみ。DSN、証明書、本文、内部例外は出さない。

| exit | 意味 |
| --- | --- |
| 0 | DIAGNOSTIC_SAVED |
| 2 | 引数・環境拒否、またはJOB_NOT_CLAIMED |
| 3 | DIAGNOSTIC_FAILED。具体的理由はHuman読取API/画面 |
| 4 | RUNNER_STOPPED |
| 5 | DATABASE_UNAVAILABLE / RUNNER_FIXTURE_FAILED |
| 1 | 未分類の内部失敗。固定RUNNER_INTERNAL_ERROR |

二度目の同じJob実行はclaimされない。自動retryは追加しない。
観察結果は引き続き `eligible_for_approval=false / execution_allowed=false`。

## 5. Migrationと互換性

revision `0485ef420871`、親 `0374de319760`。
既存reason check constraintに13コードを追加するだけで、新Modelや履歴の書換えはない。
append-only trigger、Job結合、同一transaction保存、非認可固定値は維持する。
新理由の履歴があるDBのdowngradeは明示拒否する。履歴を書換え・削除してdowngrade可能にする操作は行わない。
空DBでは親revisionへのdowngrade→upgradeとmodel差分検証が可能。
通常企業・旧schema・flag OFFの互換性と既存Human/Agent境界を維持する。

## 6. 検証と次の停止点

2026-10-06、すべて合成サイト・専用DBのみで検証した。

- 独立CLI/failure/runner: 37 passed / 1 skipped（239.39秒）。WindowsのPOSIX SIGTERMだけskip。
- 新しいdowngrade保護を含むfailure/job API/storage/read/process/worker concurrency/contact permission/operations回帰: 99 passed（77.26秒）。
- 接続queryによるhost上書き拒否を追加した最終CLI guard: 1 passed（21.34秒）。
- lab単体40件成功。7変更ファイルのmypy（check-untyped-defs / follow-imports=silent）、backend/lab Ruff、変更format成功。
- Frontend typecheck/lint/build成功。desktop/mobileの観察画面E2E 4 passed（1.3分）。TLS/robots理由表示を含む。
- upgrade→downgrade親revision→upgrade→model差分check成功。新理由の履歴がある場合のdowngrade拒否と履歴維持も成功。
- 専用API起動、稼働中APIのread-only health正常、通常worker exitedを確認。
- 今回作成したbackend/UIの2つのDBはUser/Project/Company/観察証拠/台帳/承認/配送0件と接続残存なしを確認して削除。独立process用DBの残存0件。
- GitHub全体CIはpush後の完了報告のrunを参照する。

独立CLIの成功・固定失敗・同一Job再実行拒否、強制終了後のHuman回収と遅延worker停止、協調終了、downgrade時の履歴保護を検証する。
WindowsではPOSIX SIGTERM試験をskipし、Eventによる協調終了と実process強制終了を別々に検証する。
画面の操作APIはmock、実APIの認証/DB保証はbackend試験で確認する。

次候補は、新観察のnegative/review holdをCore permissionへ結合する設計・管理下検証。
実サイトへの開放にはOrganization/保持・削除、parser隔離、実サイト許可管理等も残る。
今回の完了を実サイト観察・フォーム送信・通常worker再開の許可と扱わない。
