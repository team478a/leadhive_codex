# フォーム実行アダプターと承認・予約基盤の接続設計

## 1. 結論・範囲

基準は codex/integration@68009468d8e9da2e98720312c840712bc8ebc865。今回は設計のみ。コード、Migration、API、DB、worker、利用中環境、配布パッケージを変更しない。実サイトGET・入力・POST、SMTP、外部AIを実行しない。

既存Human承認・固定payload・予約・送信開始前UNKNOWN保存を再利用する。非実行型 `form_plan_fixture` は永久に非実行型として維持する。実行可能な契約を別に追加し、新しいHuman承認を必要とする。最初の接続実証は専用PostgreSQLと管理下HTTPサーバーだけで行う。実CF7・JavaScriptフォームへの対応完了を意味しない。

## 2. 現在の根拠と再利用範囲

| 根拠ファイル | 現状 | 接続時の扱い |
|---|---|---|
| backend/app/services/form_execution_plan.py | 固定fixture URL・adapterの厳密契約、計画hash/version | version 1の許可URLを広げず、別の実行契約を追加 |
| backend/app/schema_approval.py / services/human_approval.py | Proposal、snapshot/hash、Human step-up、失効・revision | 既存Human/Agent分離を維持し、実行計画を別方式でbind |
| backend/app/model_approval.py | fixture承認のCONSUMED禁止 | 制約を維持 |
| backend/migrations/versions/fb1d6a8c2093_fixture_plan_approval_guard.py | 上記DB制約 | 書き換え・解除禁止 |
| backend/app/services/approved_form.py | form_direct限定、Human証明、予約key、重複・共有lock/上限 | 共通guardを維持し、方式別検証だけ追加 |
| backend/app/model_approved_form.py | immutable予約snapshot、approval/key unique、site links | 原則再利用、別の試行台帳を本番に作らない |
| backend/app/services/approved_form_worker.py | GET preflight、UNKNOWNとCONSUMEDをcommit後POST | 実行contextを方式別に構築し、共通begin/result処理を利用 |
| backend/app/services/form_submission_guard.py | FormDeliveryをUNKNOWNで保存、方式direct固定 | 既知方式の明示引数を追加する設計。adapterをdirectと偽記録しない |
| backend/app/services/form_site_rate.py / form_operations.py | 共通site制御、未開始予約の整理、UNKNOWNを再queueしない | 全adapterと共有、UNKNOWN再準備禁止 |
| backend/migrations/versions/f8b25ea3c649_approved_form_dispatch.py | consumption証拠・予約不変性のDB trigger | 既存制御を残し、新方式には追加の証拠照合が必要 |
| backend/app/services/form_profile_delivery.py | READY + delivery_supported等を通常経路の条件にする | CF7を通常経路READYに偽装しない |
| frontend/src/ApprovalQueuePage.tsx | 検証用計画の内容・hash表示、Human承認 | 実行可能な計画との明確な区別と確認項目を追加 |
| backend/tests/fixture_plan_runner.py | SQLite試験台帳と固定loopback HTTP実行 | appからimportしない。応答fixture・停止試験の考え方だけ再利用 |

109の30件成功はSQLite試験であり、PostgreSQL・Human証明・worker接続の成功ではない。

## 3. 契約と方式の分離

| 方式 | 承認 | 実行 |
|---|---|---|
| form_direct（既存） | 現行契約 | 現行の単回通常フォーム経路 |
| form_plan_fixture（既存） | 合成計画の検証 | 常に不可。予約・消費・worker登録なし |
| form_adapter（追加案） | 新しい実行契約をHuman承認 | registryに登録した版・環境だけ。既定OFF |

追加案 `ExecutableFormPlan` はfixture契約と別schemaにする。adapter ID/version、contract/canonicalization version、Project/Company/Draft/FormProfile、channel、方式、送信者、文面、入力値、計画version、許可操作順、宛先、構造/経路fingerprintを固定する。既存外側payload hashと内側plan hashの両方を検証する。

任意JavaScript、任意HTTP header、任意URL操作、caller指定loopback portを公開しない。registryは既知ID/versionと有限な操作の組合せを定義し、未知版・無効版は拒否する。最初は `controlled_lab_single_post` のみ。これは実CF7 adapterではない。JS確認画面と実CF7は別の後続工程。

既存fixture承認・direct承認を実行用へ変換しない。既存payloadの書き換えもしない。方式変更は新しいProposal/revisionとHuman再承認で行う。

## 4. 準備・承認・API境界

準備Serviceは保存済み解析証拠とDraftから計画を生成する。callerの完成済み任意計画を無検証で採用しない。サイト観測は別の明示操作とし、準備/承認APIが暗黙に外部アクセスしない。

Human承認画面では会社、送信者、文面、全入力値、form URL、実際のPOST先、操作順、adapter版、hash/version、有効期限を表示する。検証用と実行用を区別する。既存step-upを承認request/hash/version/action/sessionにbindする。Agentは準備までで、approve/reserve/send不可。confirmed=trueは承認証明にならない。

既存予約APIの方式別Service分岐を検討する。予約requestから受け取るのは承認ID、expected hash/version、idempotency keyのみ。本文・対象・endpoint・adapterを上書きさせない。Project owner/editor、有効Human sessionと承認証明を再確認する。APIパス追加の要否は契約工程で確定し、今回は追加しない。

## 5. DB変更案（additiveのみ）

新しいSendAttempt/DispatchReservationを別に作らず、ApprovedFormDispatchとFormDeliveryを正本とする。planとadapter版はimmutable payload_snapshotへ保存し、別の更新可能列を正本にしない。必要な方式enum/checkの拡張は現行定義確認後に最小化する。

新方式のCONSUMED遷移には追加DB guardを設ける。対応予約・deliveryのProject/Company/Draft、方式、approval ID、payload hash/version、plan hash、UNKNOWN、started_at、deliveryリンクが一致することを要求する。既存consumption triggerも維持する。fixture禁止制約は独立して維持する。未知方式・不足snapshotはfail closed。

計画完全性の複雑な検証はServiceでも行い、DBには方式と証拠一致の不変条件を置く。JSON計画のhash計算をDBが再現できない場合は、DB証拠照合だけを完全なcanonicalization検証と呼ばない。Migration実装前に直接SQLによる改ざん試験を設計する。

FormDeliveryとOutreachDraftApprovalには実際のadapter方式を記録できるようにする。append-only OutreachAuditEventは予約・開始・結果の状態変更と同一transactionで追記する。秘密token・応答全文を監査台帳へ保存しない。

実サイト用adapter能力証拠は、後続工程でFormProfileへadditiveな版付きdescriptorを追加する案。通常経路delivery_supportedと別にする。単なるCF7検出は実行能力の証拠ではない。UNKNOWN permission、同意未確定、必須欄未解決、CAPTCHA、営業禁止をdescriptorで解除しない。

## 6. 予約・重複・site制御

現行shared advisory lock、approval unique、idempotency key unique、Company/form URLの重複検査を共有する。同key・同requestは既存予約を返し、異なる内容は409。別方式・別keyでもUNKNOWN/送信済みを迂回できない。

site linksはform URLだけでなく、全承認済み実行endpointを含める。hostname bucketは頻度管理用であり、scheme/port/pathを含む宛先許可検証の代わりにしない。adapter専用の別上限bucketを作って通常経路の上限をすり抜けない。試験開始もUNKNOWNや失敗も上限へ算入する。

## 7. workerと通信の順序

1. 方式・registry版・feature flag・専用環境を検証する。
2. 副作用のないpreflightだけを行い、fingerprint・経路・宛先・入力schemaを確認する。network I/O中にDB lockを保持しない。
3. 共通beginで予約lease/owner、権限、承認期限・証明、両hash/version、現在のsuppression/opt-out/do_not_contact/営業禁止/CAPTCHA、重複・上限・site間隔を再確認する。
4. FormDelivery UNKNOWN、予約UNKNOWN/started_at、Approval CONSUMED、開始auditを同一transactionでcommitする。commit失敗なら実行しない。
5. commit成功後に限り、固定contextをadapterへ渡す。adapterにはDB承認更新権限・任意再予約能力を渡さない。
6. HTTP retry=0、redirect禁止、timeout/サイズ上限付きで許可操作を実行する。
7. 同じworker/予約とUNKNOWN状態を照合して結果・auditを保存する。保存失敗でも開始時のUNKNOWNが残る。

最初の接続は単回POSTだけ。確認POST、ブラウザ入力イベントなど副作用を起こし得る操作を導入する場合は、その最初の操作より前に手順4が必要。GET preflightという名前だけで副作用なしと判断しない。

実サイト用tokenは、承認した宛先・adapter・構造・許可されたtoken欄の範囲でだけ取得する設計が必要。token更新を文面変更の口実にしない。承認対象に固定する値と実行時変動値の区別・hash規則が未確定の間は実サイトを許可しない。

## 8. 結果・停止・復旧

UNKNOWNは「未送信」の意味ではない。曖昧な200、通信断、timeout、結果保存失敗、commit後のprocess消失はUNKNOWNを維持する。自動retry、direct/別adapter/Codexへのfallback、新承認による重複回避を禁止する。Human Reviewは観測記録であり、再送許可ではない。

管理下試験のfixture_acceptedは合成受付証拠だけ。submittedは受付確認であり、相手のメール到達・閲覧を保証しない。実CF7のmail_sentをfixture成功へ読み替えない。受付前失敗を確実に証明できる場合だけfailedとするが、承認を自動的に再利用しない。

lease回収は未開始checkingだけを対象にする。started_at/deliveryありのUNKNOWNはqueueに戻さない。cancel/revokeは開始前にのみ実行を止められる。commit後は取消が相手の受付を取り消すと表示しない。

## 9. 環境とfeature flag

新adapter flagは既定OFF。既存outbound/human_approved_form flagを迂回しない。本番条件と試験条件を独立させる。

管理下試験は専用 *_test PostgreSQL・合成Project/Company/Draft・一時HTTPサーバーのみ。loopback置換はテスト注入境界だけに限定する。Production SSRF guardへlocalhost例外を追加しない。通常workerが試験adapterを選択できないことも試験する。

利用中環境のflags、停止worker、保留企業、DBを維持する。実CF7を有効化する前にTLS/DNS/redirect/危険URLと実protocolを別途検証する。

## 10. Migration・rollback

既存Migrationは編集しない。現在のheadを確認してadditive migrationを作る。専用DBでupgrade → downgrade → upgrade、Model差分、直接SQLのfixture CONSUMED拒否、新方式の不正消費拒否を確認する。

rollbackはまず新adapter flag OFF、新規予約停止、未開始予約停止。UNKNOWN・CONSUMED・auditは削除しない。新方式の証拠があるDBは無条件downgradeしない。旧アプリが未知方式をclaimしないことを事前確認し、保証できなければworker停止を維持する。安全な復旧が確認されるまでschemaを残す。

## 11. 接続受入基準（未実行）

| 領域 | 必須検証 |
|---|---|
| Principal | Agent approve/reserve拒否、混在Cookie拒否、viewer/別Project拒否、権限剥奪後の開始拒否 |
| Human証明 | step-upなし/期限切れ/replay/hash/version相違を拒否 |
| fixture隔離 | form_plan_fixtureはAPI予約不可・SQL消費不可・worker実行不可 |
| payload | sender/対象/文面/全endpoint/操作順/adapter版/構造変更は開始不可、再承認必須 |
| transaction | commit前POST 0、消費・UNKNOWN・auditの原子性、commit失敗POST 0 |
| 競合 | 同key/別key/別方式/並列workerで追加POSTなし、別siteでも同Company保護 |
| 安全guard | suppression/opt-out/営業禁止/CAPTCHA/上限/期限/flag変更をbeginで再確認 |
| process停止 | commit直後killと受付直後kill、別DB接続からUNKNOWN確認、再起動後追加POST 0 |
| 応答 | 曖昧応答/redirect/timeout/切断/巨大応答/結果保存失敗はUNKNOWN、fallbackなし |
| 回帰 | direct承認・予約・worker・rate・復旧、既存UI/E2E、fixture非実行制約を維持 |
| DB | Migration往復、Model差分、不正直接SQL、immutable予約・append-only台帳 |

Backend lint/typecheck相当/tests/API起動、Frontend typecheck/lint/tests/build、必要なE2Eを各実装工程で実行する。今回は設計文書の参照とdiff確認のみであり、上記接続受入が通ったとは報告しない。

## 12. 実装工程と停止点

1. **接続契約・DB guard**：新方式/schema、snapshot/hash、registry検証、additive DB guardと専用PostgreSQL試験。通信器・worker登録・実サイト対応なし。完了後停止。
2. **Human準備・承認UI・予約**：新方式を明示表示し、step-upと共通予約/site制御へ接続。通信なし。完了後停止。
3. **管理下HTTPとworker接続実証**：テスト限定adapter、既存PostgreSQL begin/result処理、実process停止・競合・UNKNOWN試験。実サイトなし。完了後停止。
4. **実CF7事前設計・protocol検証**：公式protocol、endpoint/nonce、fingerprint、受付証拠、SSRF、同意の扱いを確認。対応可能と判断するまで登録・有効化しない。
5. **限定実サイト対応の判断**：別の明示指示と対象/操作範囲の承認が必要。JS確認画面・大量運用は別工程。

次に実装すべき工程は1のみ。工程3の試験成功を月間10,000件の実運用達成や実CF7送信成功と扱わない。

## 13. 残る論点・blocker

- 実CF7の受付protocol・tokenと動的値のhash境界は未検証。
- 本番でのadapter能力証拠と通常経路READYの区別は未実装。
- 全endpointのsite管理・危険URL検査と構造変化の検出を接続する必要がある。
- PostgreSQLの証拠guardとworker停止耐性は新方式で未実証。
- 現行送信上限・重複制御にはinstance全体の制御がある。複数組織のtenant隔離を完成済みと扱わず、別組織共有運用やAUTONOMOUSをこの工程で有効化しない。

設計上、既存Human Approvalを削除せず、PolicyAuthorizationも今回追加しない。Codex-assisted、Human Required、Blockedの境界は維持する。Cecil/PALIOの保留解除は今回の成果に含めない。
