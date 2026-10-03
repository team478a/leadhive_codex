# Human Approval Foundation — A2実装

基準: `codex/integration@0092a2288ed5f31fba4f8a3675ce741c05fcfe75`。
設計基準: [Human Approval Foundation Design](DOTS_HUMAN_APPROVAL_FOUNDATION_DESIGN.md) とA2実装指示。

## 範囲

提案の準備、Human再認証、承認・却下・取消・期限切れ、監査記録まで。
新しい承認APIは配送モデル、worker、SMTP、Form POST、Campaign、Batch、Codex送信を呼ばない。
`CONSUMED`は状態名の予約だけで、遷移はAPIにもServiceにもない。DB triggerも遷移を拒否する。
SendAttempt、DispatchReservation、atomic consume、idempotency、UNKNOWN結果処理はA3以降の未実装項目。

**既存のHuman向け配送APIはA2 ApprovalRequestへ移行していない。** 既存UIを維持し、Agent credentialでは既存のHuman APIを使用できないguardを追加した。
新しい承認を付与しても、既存配送workerがそれを読んで送信することはない。
A2は既存のHuman配送処理全体を新承認方式で保護したリリースではない。

## Model / Migration

追加Migration: `a2f0c6d8e913_human_approval_foundation.py`。
親revision: `c1d9f6a2b4e8`。既存Migrationは変更しない。

| Model | 用途 |
| --- | --- |
| AgentIdentity | Userと別のAgent主体。作成Human、名称、有効状態 |
| AgentCredential | opaque bearer tokenのSHA-256 digest、scope、最大30日の期限、失効状態 |
| AgentProjectGrant | AgentとProjectの権限関係。credential scopeとgrant scopeの積集合 |
| ApprovalRequest | 対象・内容の不変snapshot、SHA-256、版、提案系統、承認状態・証跡 |
| HumanApprovalProof | request/hash/version/action/User/sessionへbindした再認証challengeと消費記録 |
| OutreachAuditEvent | 追記専用の提案・承認・失効・拒否等の台帳 |

既存Company、Project、User、OutreachDraftにはFKで接続する。既存配送Modelは変更しない。
台帳・承認の保存を優先してFKにCASCADE削除を付けない。監査記録のあるProject/Company/Draft/Userを物理削除しようとすると409になる。Projectはarchiveで保持する。
台帳のUPDATE、DELETE、TRUNCATEと、提案のpayload更新・削除をPostgreSQL triggerで拒否する。
承認後は取消・失効後も承認者、日時、承認hash/versionを更新できない。
DB superuserやtriggerを変更できる管理者の侵害に対する完全な耐改ざん保証ではない。

## Principal / scope

- Human: 既存User + 有効Browser AuthSession。
- Agent: AgentIdentity + AgentCredential。有効なcredential、identity、Project grantが必要。
- Agent tokenをUserへ変換しない。Human CookieをAgent認証に利用しない。
- AuthorizationとHuman Cookieを同時に持つrequestは公開APIを含め403。
- Human向けAPIへAuthorizationを渡した場合も403。`confirmed=true`はこのguardを回避できない。
- scopeは`collection:create`, `collection:read`, `job:read`, `company:read`, `analysis:read`, `analysis:propose`, `outreach:prepare`, `outreach:read`だけを発行可能。
- approve/send/suppression解除/opt-out解除/credential管理/user管理/delete等のscopeとunknown scopeは発行拒否。
- A2でAgentに公開する操作は提案作成・改訂・参照のみ。他の登録可能scopeに対応するAgent APIは今回は追加していない。

`AGENT_FEATURES_ENABLED=false`が既定。Humanの承認キューとcredential混在/誤用guardはflagの値に依存しない。
AgentをOFFにしてもHumanは提案を作成・承認できる。
flagはserver環境変数であり、Agent自身が変更するAPIはない。

## API

すべて`/api`配下。Human操作は既存のOrigin/CSRF guardとBrowser session認証を継承する。

| Method / path | Principal / 権限 | 内容 |
| --- | --- | --- |
| POST `/projects/{project_id}/agents` | Human owner | Agent + credential + Project grant。tokenは発行時のみ返す |
| POST `/projects/{project_id}/agents/{agent_id}/revoke` | Human owner | Project grant失効 |
| POST `/projects/{project_id}/approval-requests` | Human owner/editor | PENDING作成 |
| GET `/projects/{project_id}/approval-requests` | Human Project member | 状態filter、limit≤100、offset、作成日時順 |
| GET `/approval-requests/{request_id}` | Human Project member | snapshot・証跡・現状態 |
| POST `/approval-requests/{request_id}/revisions` | Human owner/editor | 新版PENDING、旧版REVOKED |
| POST `/approval-requests/{request_id}/challenge` | Human owner/editor | 5分のchallenge作成。expected hash/version必須 |
| POST `/approval-requests/{request_id}/challenge/verify` | Human owner/editor | パスワード再認証 |
| POST `/approval-requests/{request_id}/approve` | Human owner/editor | verified challenge + expected hash/versionで承認 |
| POST `/approval-requests/{request_id}/reject` | Human owner/editor | PENDINGを却下 |
| POST `/approval-requests/{request_id}/revoke` | Human owner/editor | PENDING/APPROVEDを取消 |
| GET `/projects/{project_id}/approval-audit` | Human Project member | 追記専用台帳のページ取得 |
| POST `/agent/projects/{project_id}/approval-requests` | Agent + outreach:prepare | PENDINGだけ作成 |
| GET `/agent/projects/{project_id}/approval-requests` | Agent + outreach:read | grantされたProjectだけ参照 |
| POST `/agent/projects/{project_id}/approval-requests/{request_id}/revisions` | Agent + outreach:prepare | 新版PENDING。旧承認は引継がない |

Agent用approve/reject/revoke/challenge APIはない。Humanの同名APIへAgent tokenを渡すと403。
提案入力はunknown fieldを拒否する。status、approved_by、confirmed等は入力不可。
会社とDraftのProject所属、Draftと提案の会社/channel/subject/body一致を確認する。
ledgerのupdate/delete endpointはない。

## payload / 状態

`json-v1`: 型検証した値をUTF-8、key順序固定、compact JSON、非ASCII文字そのまま、NaN禁止でSHA-256化。
文字列の改行・空白・Unicodeは保存値のまま。nullと空文字は区別し、配列順を保持する。
snapshotにはproject/company、proposal/version、channel、delivery method、recipient/form URL、subject/body、sender、field values、attachment metadata、元Draft fingerprint、会社の連絡先/対象情報hash、保存済みForm Profile/Mapping hashを含める。
UI表示と将来のexecutorは保存済みsnapshotを基準にし、再度live Draftから本文を組み立てない。

作成時からpayload列を不変にする。変更は新しいApprovalRequestを作成し、同じproposal_idにversion+1とsupersedes_request_idを保存する。
旧版は同じtransactionでREVOKEDとし、旧Human証跡を新版に流用しない。
同じproposal/versionと同じsupersedes_request_idの重複をunique constraintで防ぐ。
元Draftの本文等、会社名・Web/domain・email・phone・contact URL、保存済みForm Profile/Mappingが後で変わった場合、参照・承認・有効性検査時にhash不一致を検出して失効する。Form依存は会社の全保存済みprofileを比較する保守的な方式で、再解析によるmapping変更も再承認を必要とする。外部の実際のDOMを取得して再確認する処理はA3の範囲。

許可する遷移:

```text
PENDING → APPROVED / REJECTED / EXPIRED / REVOKED
APPROVED → EXPIRED / REVOKED
REJECTED / EXPIRED / REVOKED → 終端（新規提案を作成）
CONSUMED → A2では到達不可
```

期限はserver側で作成から最大24時間。無期限・25時間以上・0時間の入力は拒否。
期限切れ判定はqueue/個別参照・承認操作・有効性検査で行う。定時に状態を書換えるworkerは追加していない。
`valid_approved_payload()`はexpiry、snapshot、Draft依存、承認hash/versionを確認するService境界であり、consumeもdispatchも行わない。

## Step-up / transaction

初期方式は既存のArgon2 password verifierによるHuman再認証。
`PasswordStepUpVerifier`境界を将来WebAuthn/Passkey verifierへ交換できる。
challenge tokenは高エントロピーで、DBにはdigestのみ保存。5分で失効する。
request ID、hash、version、APPROVE action、User、session digestにbindする。
verify成功後だけ承認可能。失敗したchallengeは使用済みにし、成功challengeも承認時に使用済みにする。
challenge発行はUserごとに5分で最大5件。User行lockで並行発行の上限迂回を防ぐ。
承認request、proof、session、Project/member等をlockして検証する。
状態変更・proof消費・台帳追加を同一DB transactionでcommitする。

パスワードとsessionをHumanがAgentへ渡した場合、password方式だけで物理的な人間操作を証明することはできない。credential非共有の運用を前提とし、将来の認証器への交換境界を残した。
再認証password、challenge token、Agent token、SMTP/API credentials、本文は監査台帳へ保存しない。

## UI / 利用手順

1. ログイン後、左メニューの「承認キュー」を開く。
2. Projectを選択。「承認待ち提案を作成」から会社・チャネル・宛先・送信者・本文を保存する。AgentがOFFでも利用可能。
3. 提案を開き、会社、宛先、送信者、件名、本文、field values、提案者、版、期限を確認する。
4. 「承認用パスワード」にログインpasswordを入力し、「内容を確認して承認」。challenge→verify→approveをUIが実行する。
5. 必要なら理由を入力して却下/取消する。viewerにはこれらの操作を表示しない。
6. 「監査記録」で最新100件を参照する。承認キューは50件ずつ移動できる。

まだ送信ボタンはない。承認後も「承認済み（未送信）」と表示する。
会社の新規提案selectorは直近100社を表示する。全社を対象にするAgent/Human APIではcompany_idを指定できる。

## 検証

実行環境: Python 3.12、隔離したPostgreSQL 16.4、既存Node/Vite/Playwright環境。

| 確認 | 結果 |
| --- | --- |
| Backend Ruff | PASS |
| Backend typecheck相当 | compileall、import、Model差分検証、API起動がPASS |
| Backend全体 | 210件PASS（会社/Form依存検査追加まで）。最後のmapping比較検査は承認専用テストで再確認 |
| A2 security / Foundation | 最終コードで61件PASS。Form fingerprintとmapping変更失効を含む |
| 既存Backend回帰 | 150件PASS。実送信はmockで置換 |
| Migration | 初回upgrade、A2 downgrade→upgrade、alembic check、単一headがPASS |
| Frontend typecheck / lint / build | PASS |
| Frontend E2E | 6件PASS。desktop/mobileの承認・却下・取消・viewer表示、既存workflow、Form Intelligence |
| API起動 | 専用DBのUvicorn起動とhealth応答がPASS |
| 実送信防止 | 新承認にEmailDelivery/FormDeliveryが作られず、UIテストでも送信/dispatch API呼出しなし |

最初の全体テストではブラウザfixtureと同じDBを使い、データ件数検査が失敗した。別の空DBに分離して全体テストをやり直し、PASSを確認した。テスト/運用DBは混用していない。

| A2 Acceptance Criteria | 判定 / 根拠 |
| --- | --- |
| 1. Agent credentialだけではApproval不可 | PASS: approve/reject/revoke/challenge全て403 |
| 2. HumanのみAPPROVED | PASS: owner/editor成功、viewer/別Project拒否 |
| 3. step-up必須 | PASS: 未検証・expired・別User/session/request・replayを拒否 |
| 4. hash/version固定 | PASS: canonical snapshot、DB変更拒否、expected値の不一致409 |
| 5. 承認後変更の検知 | PASS: 改訂、Draft、会社、Form Profile依存変更で旧承認REVOKED |
| 6. expiration | PASS: PENDING/APPROVED期限切れ、24時間超/無期限の入力拒否 |
| 7. reject/revoke | PASS: APIとdesktop/mobile UIで確認 |
| 8. audit ledger | PASS: state/proofと同一transaction、更新・削除・TRUNCATE拒否、secrets非保存 |
| 9. Agent scope制限 | PASS: 8種allowlist、禁止/unknown拒否、grant/credential失効拒否 |
| 10. 既存Human UI | PASS: 左メニュー承認キュー。viewerは閲覧のみ |
| 11. Dots未接続 | PASS: Agent default OFFでもHuman提案・承認可能 |
| 12. 実送信なし | PASS: 新Serviceにexecutorなし、配送行なし、送信API呼出しなし |

テストは隔離したPostgreSQL `_test` DBで実行する。運用DBのmigrationや運用worker起動は行わない。
SMTP/Form送信の既存回帰テストはmockを使い、外部送信を行わない。
ブラウザE2Eの不変台帳fixtureは削除guardを解除せず、専用の使い捨てtest DB内に保持する。
そのためBackend回帰用DBとブラウザ用DBを分離する。

再実行例（URLは専用test DBだけを指定する）:

```powershell
# backendで実行
$env:TEST_DATABASE_URL = 'postgresql+psycopg://postgres@127.0.0.1:15483/leadhive_a2_regression_test'
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m compileall -q app migrations tests
.venv/Scripts/python.exe -m pytest -q

# frontendで実行。別の使い捨てDBを指定する
$env:TEST_DATABASE_URL = 'postgresql+psycopg://postgres@127.0.0.1:15483/leadhive_a2_test'
npm run typecheck
npm run lint
npm run build
npm test
```

test DB以外へMigrationを適用していない。本運用への適用はバックアップ後に別作業で行う。
本運用で承認/台帳データができた後のdowngradeはこれらを失うため、通常のrollbackではテーブルを保持しコードだけを戻す。今回のdowngrade検証は空の専用DBのみで実施した。

## A3への引継ぎ / 停止

A2の承認基盤が通っても、外部Agentから配送可能な状態にはしない。
A3では別指示のもと、全配送経路の共通guard、原子的consume、dispatch reservation/attempt、idempotency、実行時suppression/opt-out/重複/rate/form fingerprint再確認、UNKNOWNのHuman reviewを実装・検証する必要がある。
既存`confirmed`経路、Campaign/Batch/worker/Codex補助経路は、その段階で監査・移行する。
今回A3、Dots接続、MCP、deployment、外部送信は実施しない。
