# LeadHive × Dots — Human Approval Foundation Design

Phase A / 設計日: 2026-10-03 / DESIGN ONLY

基準: `codex/integration@0092a2288ed5f31fba4f8a3675ce741c05fcfe75`。実装コードは監査対象`d5f86a52922750f190d20091ad750169120eb4d8`から変更されていない。主根拠は`DOTS_EXTERNAL_ORCHESTRATION_READINESS_AUDIT.md`、`backend/app/security.py`、`project_access.py`、`model_outreach.py`、送信routes、worker、form services、Codex handoff。

本書のModel、列、制約、API、状態、テストは**将来の設計**であり現在の実装ではない。文書だけを作成し、コード・Migration・DB・API・UI・設定を変更せず、外部API、送信、テスト送信を実行していない。

## 1. Current Problem

現在、owner/editorが`confirmed=true`を送れば承認となる。同じsessionを持つ外部Agentも承認できる。OutreachDraftApprovalは承認イベントを記録するが、HumanとAgentの識別、承認待ち/失効、payload版を扱わない。

メールはEmailDeliveryへ宛先・本文をcopyする一方、form batchはworker実行時のDraft/senderを読み、承認本文が固定されない。direct formは外部POST後にDeliveryを保存するため、同時呼出しをunique constraintだけでは防げない。通信断やworker停止で送信結果が不明な場合も、failedとの区別が不足する。

目的は既存LeadHiveの上に**承認・dispatchの共通業務境界**を追加すること。SMTP、Form Intelligence、UI、worker、campaign、batch、Codex支援を維持し、全経路からこの境界を通す。

```text
Agent又はHumanが準備 → ApprovalRequest PENDING
 → Humanが正確な宛先・内容を確認して承認
 → APPROVED（不変snapshot）→ 内部workerの最終検査
 → CONSUMED（1回のdispatch権限をDB確定）→ 外部実行
 → SENT / FAILED / UNKNOWN → 監査台帳と既存UI
```

**ApprovalRequestの作成とApprovalの付与は別操作**。Agentは前者だけ可能。confirmed bool、User-Agent、任意HTTP header、payload内の「承認済み」をHuman Approvalの証拠にしない。

## 2. Threat Model

| 脅威 | 設計上の防御 |
| --- | --- |
| AgentがHuman Cookieを再利用／principalを偽装 | 認証経路分離。Agent requestでCookie/複数credential拒否、serverがprincipal確定 |
| Agentがconfirmed/approved_by/statusを入力 | strict request schemaで拒否。approval route/serviceはHuman限定 |
| Web本文・返信のprompt injection | 全取得情報をUntrusted Data。tool scope・承認・宛先制約を文章で変更できない |
| 承認後の本文/宛先/sender変更 | canonical snapshot、hash/version、依存版検査、失効と再承認 |
| 同時request/worker/recoveryによる二重送信 | dispatch前のDB原子的consume、unique attempt、外部callの自動再実行なし |
| 結果不明のretry | UNKNOWNを隔離、人の照合・新規承認。旧attemptをrequeueしない |
| 抑止解除・別Project迂回 | Agent scopeから解除除外。project binding、最終permission再照合 |
| 旧API/Skill/テスト送信からの迂回 | 全副作用経路を台帳化、legacy confirmedではAgent承認不可、未対応経路は停止 |
| 管理者・内部executor・DB侵害 | 権限分離、append-only ledger、secrets最小化。DB superuser等の侵害を完全保証とはしない |

保護対象はLeadHiveが管理する外部送信。人が別ツールで送ったメールや、端末を完全制御する攻撃者による送信を防ぐ設計ではない。人が自分のsession/認証器をAgentへ渡した場合、serverだけで「人の意思」を証明できない。Cookie非共有に加え、承認時の明示確認とstep-upを必要とし、この運用・端末の信頼境界をAcceptanceで確認する。

## 3. Human / Agent Principal Model

| principal | 認証・帰属 | 許可される役割 |
| --- | --- | --- |
| HUMAN | 既存User＋ブラウザAuthSession。approval用途には明示的step-up証明 | 準備、閲覧、権限内の承認/拒否/取消、人の復旧 |
| AGENT | AgentIdentity＋有効なAgentCredential。Human sessionと独立 | grantされたprojectの読取・収集・提案・準備のみ |
| SYSTEM（内部実行主体） | 非公開worker実行context。外部tokenで選択不可 | 既にHuman承認されたrequestの検査・consume・executor呼出し |

SYSTEMはHuman/Agentを混ぜるための例外ではない。AgentをSYSTEMへ昇格するAPIはない。SYSTEMもAPPROVEDを作れず、権限の根拠は既存のHuman承認である。

serverの認証結果は`principal_type, principal_id, project_grants, capabilities, credential_id`。HTTP bodyや`X-Principal-Type`等で指定不可。Agentは`Authorization: Bearer <opaque token>`等の専用認証候補を使い、tokenはDBにdigestのみ保存し、expiry/revocation/rotationを持つ。JWTは必須にしない。認証方式の詳細実装は後続工程。

Human routeでBearer Agent credentialを認識した場合は403 `agent_operation_forbidden`。Agent routeにHuman Cookie又はCookieとBearerが混在する場合はcredential ambiguityとして拒否。既存browser routeへAgent tokenを渡してもHuman Userへ変換しない。未認証は401、別Projectは現行404方針を維持する。

approval step-upは、サーバーが発行した使い捨てchallengeにrequest ID/hash/version/actionを結び付け、Humanの再認証又は認証器による確認を要求する設計。ブラウザからの同意と認証器のユーザー確認を含む方式を推奨し、単なるCookie保持を人の承認証明にしない。challengeは短期、単回、session/user/actionにbound。Agentにはchallenge取得・response代理生成権限を与えない。ブラウザorigin/CSRF保護も維持する。

承認許可は`HUMAN ∧ 現在のProject owner/editor ∧ approval権限 ∧ step-up成立`。初期は既存owner/editorを承認可能なHumanに対応させ、viewerは不可。権限喪失・User無効化・Agent grant失効はdispatch時も検査する。ownerによる別Humanの再承認は新requestで記録し、旧承認者を差し替えない。

step-up challengeの短期期限は承認操作の期限であり、保存済み承認証跡の期限とは分ける。承認成功後はchallengeを消費し、証跡をrequestへ固定する。通常browser sessionの期限切れだけでは予約送信の承認を失効させない。dispatchではUser/権限/proofとApprovalRequest.expires_atを確認する。

## 4. Scope Model

有効権限は`credential scopes ∩ AgentIdentity許可 ∩ project grant ∩ server allowlist`。project IDは認証grantから検証し、入力IDだけを信用しない。scopeは任意文字列を受け入れず、発行時もunknown/禁止scopeを拒否する。

| Agent scope候補 | 操作範囲 |
| --- | --- |
| collection:create | 許可Provider/件数/地域/予算内のjob登録。予約・継続実行条件も上限内 |
| collection:read | 許可Projectの収集結果・出典 |
| job:read | 自Projectの状態/進捗/公開可能なエラー。送信実行権限なし |
| company:read | 許可Project・必要fieldに限定。返信個人情報等は自動で含めない |
| analysis:read | 保存結果と根拠の読取 |
| analysis:propose | 外部評価の提案保存。確定営業状態/抑止/承認を変更しない |
| outreach:prepare | Draft/候補/ApprovalRequest PENDINGの作成、承認前の編集・新version提案 |
| outreach:read | Draft/request公開状態/結果。secrets・execution ticketを返さない |

**発行禁止**: outreach:approve、email:send、form:send、suppression:remove、optout:remove、credentials:read/update、user:manage、destructive:delete。

outreach:prepareは送信job登録・consume・retry・campaign resume・Codex submit権限を含まない。Agentはapproved requestを更新不可。変更したい場合は新しいPENDING版を提案し、旧承認の失効を引き起こしてもAPPROVEDへは進めない。

Agentに許されるのはscopeのあるAPIだけで、既存editor User権限へのfallbackなし。Agentをmemberに登録して承認権限を作ることも不可。budget/件数limitはpermissionと独立に適用する。

## 5. ApprovalRequest Model

新規候補`approval_requests`。会社/channelごとの一件の実行意図を表す。campaign/batchの承認も対象ごとのrequestに展開し、単一boolで将来追加企業まで承認しない。

| field候補 | 意味・制約 |
| --- | --- |
| id / project_id / company_id | UUID。Companyのproject一致をservice・DB関連で検証 |
| channel / delivery_method | email又はform。formはdirect/codex_assistedを固定。SNSはexecutor未対応のため承認送信対象外 |
| source_draft_id / campaign_id / batch_item_id | 既存準備データ参照。どの準備から作られたか |
| recipient / form_url | email宛先又はform URL。channelに必要な値を必須、不要値は空。表記名もsnapshot |
| subject / body / sender / field_values | レビュー用表示値。不変payloadから導出し、二重更新不可 |
| payload_snapshot | 型検証済みcanonical payload JSONB。secretsを含めない |
| payload_hash / payload_version / canonicalization_version | SHA-256、論理提案内単調増加version、serialization契約版 |
| proposal_id / supersedes_request_id | 提案系列と旧request。新versionでも旧rowを破壊しない |
| created_by_principal_type / created_by_agent_id / created_by_user_id | Human単体運用を含む作成者。排他的制約。created_by_agent boolだけにしない |
| created_at / expires_at / scheduled_for | server UTC。最大承認期間と期限を設定、Agentが無期限にしない |
| status | PENDING/APPROVED/REJECTED/EXPIRED/REVOKED/CONSUMED |
| approved_by_user_id / approved_at / approved_payload_hash / approved_payload_version | APPROVED/CONSUMED等の承認証跡。Humanのみserver設定 |
| approval_proof_id / permission_context | step-up証明への参照、承認時の可否根拠。現在の可否を代替しない |
| consumed_at / consumption_attempt_id | 一回の実行権利消費。outcomeとは別 |
| revoked_at / rejection_reason / invalidation_reason | 状態変更の理由。履歴の完全形はLedger |

requestは作成時からpayloadを不変にする。Humanが編集した場合も新version/new requestとし、承認challengeを取り直す。APIにJSON patchでsnapshotを書換える経路は作らない。PENDINGは実行不可で、Human approval eventとは異なる。

承認期限はcreate時の上限以内、承認時にも期限を確認する。dispatch時にexpires_atを超えたらEXPIRED。予約日時が期限を超える場合は承認前にエラーとし、人に予約/期限の見直しを求める。

## 6. Immutable Payload

emailのenvelope recipientと送信者identityを固定し、未承認のCC/BCCやReply-Toを後から追加しない。

hashの対象は**実際に送る意味的内容と許可された送信先・手順**。Agentの文章hashやForm構造hashだけでは不足する。

| 固定対象 | snapshot内容 |
| --- | --- |
| target | project/company/contact IDと確認用会社名、対象系列 |
| channel/method | email/form、direct/codex、実行方式 |
| recipient/form destination | email、form URL、action URL、form_index、許可origin、確認画面の制約 |
| subject/body | 実際に送る最終件名/本文。署名・配信停止案内の追加を含め承認前に確定 |
| sender | 送信元mail/name、会社/氏名/住所等の入力値。SMTP/IMAP/APIパスワードは含めない |
| field values | named fieldの最終値、選択肢・同意checkbox、mapping snapshot、必須値 |
| attachment metadata | 初期は空配列のみ許可。添付自体が未対応なら非空を拒否。将来はimmutable blob ID/内容hash/サイズ/MIME/名称を固定 |
| form facts | profile_id/fingerprint/analysis_version、sales可否、captcha状態、review根拠 |
| scheduling/policy | scheduled_for、承認期限、source version/dependency revision、logical action/許容確認画面 |

canonicalizationは版付き仕様として確定する。UTF-8、key順序固定、日時UTC固定形式、null/空文字/booleanの区別、配列順序、改行の扱いを明示。hash前だけの変換を送信時に再適用しない。実送信と同じ検証済み値をhashし、表示・executorもこの値を使う。未定義のfloat、重複key、unknown field、型不正を拒否。idempotency_key/hashはserverが計算する。

現行formの各値2,000文字切詰めを、承認後に黙って行ってはならない。実際のchannel上限を準備時に検証し、超過はエラー又はHuman編集。送信値とApprovalが一致することを確認する。hidden CSRF/session tokenは**実行時取得値**として別allowlistに置き、本文・宛先・sender・同意等を動的値として扱わない。

form hidden tokenは一回のsessionで新取得するが、origin・form構造・映る意味値が一致する場合だけ注入可。tokenの変化だけを理由に新承認は不要。token取得で意味的fieldが追加/変更された場合は失効。確認画面で引き継ぐhidden値も承認済み意味値との整合を検証し、異なる値や宛先へPOSTしない。

unsubscribe token/公開URLによる最終本文はPENDING作成時に確定する（token作成だけでは送信しない）。workerが新しい文面を付け加えない。SMTP credentialの正常rotationはpayload変更にしないが、送信元identity・許可transport policy変更は依存版検査対象とする。

### 編集と失効

Draft本文、Company target/宛先、sender identity、form profile/mapping/優先form、意味的fieldsが変わったら、関連APPROVEDをREVOKEDにし、新PENDING版から再承認する。実行時もsource revisionと再構築hashを照合し、イベント通知の取り漏れだけで古い承認を使わない。

Templateはrequest作成時にcopyする。後からTemplateの既定値を更新しても既存requestの内容を自動適用しない。適用操作をした場合はDraft/version変更として失効。payloadに反映されない表示・分類変更と、送信内容に影響する変更をdependency契約で区別する。

CONSUMED後の変更は過去承認や送信snapshotを書換えない。まだ残る処理の停止を要求し、記録する。送信済みを未承認に戻すことはしない。

## 7. Approval State Machine

新版作成・旧版失効・version進行・Ledger記録は同一transactionで行う。proposal系列のrow lock/CASとversion uniqueで、同時編集・承認・consumeを直列化し、新旧両版が承認有効となる状態を防ぐ。

```text
PENDING ──Human approve──> APPROVED ──SYSTEM consume──> CONSUMED
   │                         │
   ├─Human reject──> REJECTED ├─期限──> EXPIRED
   ├─期限────────> EXPIRED  └─取消/内容変更/制約変更──> REVOKED
   └─取消/新版作成──> REVOKED

REJECTED / EXPIRED / REVOKED / CONSUMED → 同じrowをAPPROVEDへ戻さない
新しい意図又は再試行 → new request/version → PENDING → Human再承認
```

| 遷移 | 主体 | 条件 |
| --- | --- | --- |
| 作成→PENDING | scope付きAgent又はHuman | 型/Project/budget検証、expires設定、hash確定 |
| PENDING→APPROVED | Humanのみ | project権限、step-up、hash/version一致、未失効、現在の可否/支援要件 |
| PENDING→REJECTED | Humanのみ | reason記録、Agentに状態を返す |
| PENDING/APPROVED→EXPIRED | SYSTEM | server clockで期限判定。cron未実行でもAPI/dispatchで検査 |
| PENDING/APPROVED→REVOKED | Human又は安全なSYSTEM invalidation | 取消、新版/依存変更、抑止・権限失効。Agentの編集はSYSTEM invalidationを通す |
| APPROVED→CONSUMED | 内部SYSTEMのみ | dispatch前の全検査、原子的予約、1 attempt |

approval outcomeとdelivery outcomeを混同しない。CONSUMEDは「送信成功」でなく「この承認のdispatch権を使用済み」。CONSUMED後のFAILED/UNKNOWNも同じ承認で再dispatchしない。

bulk approveはHumanが対象ID/hash/versionの固定manifestを確認し、選択した各requestを同一transaction又は明示的な部分成功responseで承認する。batch後追加企業、Agentのtarget差替えはmanifest外としてPENDINGに残す。複数requestの承認が必要な範囲をUIで隠さない。

## 8. Send Execution

外部Agentにexecute/send/consume endpointは公開しない。Human承認後に内部queueが既存workerへ渡す。予約・rate待ちも既存workerを使い、API handlerの同期POSTは共通dispatchを通す方式へ移行する設計。

### 実行順

1. 内部workerが候補requestをclaim。APPROVED、予約時刻到達、Project/承認者/Agent grantの有効性を検査する。
2. snapshot/hash/version/依存版を照合。Company/contact/destinationが同Project、channelとexecutorが一致することを確認する。
3. `evaluate_contact_permission`を再利用し、suppression/opt-out/品質/フォーム禁止を再確認。通常formはREADY/ALLOWED/CAPTCHA_NONE。支援formはHuman review根拠付きの別methodに限定する。
4. formは安全に再取得し、fingerprint・action/確認手順・mapping・意味値を再確認。変更ならREVOKED、外部送信せず新PENDINGへ誘導する。
5. DB最終transactionでrequestと関連dispatch reservationをlock。expires、approval proof、hash/version、permission revision、duplicate guard、rate capacityを再確認する。必要なら事前検査をやり直す。
6. **同一transactionで** APPROVED→CONSUMED、SendAttempt DISPATCHING、unique dispatch reservation、rate reservation、Ledger eventをcommitする。失敗なら外部送信しない。
7. 同じ実行主体が一回の承認済みworkflowをdispatchする。workerはlatest Draft/senderから内容を再生成しない。channel executorの外部副作用に対するautomatic retryを無効化する。
8. SENT/FAILED/UNKNOWNと証跡をSendAttempt、既存Delivery projection、Ledgerへ保存する。成功だけをActivity/営業状態へ反映する。

rate未到達時はAPPROVEDのまま待つ。待機中も取消・expiry可能。意味的検査失敗は失効、取得通信失敗など**副作用前と確実に分かる**一時失敗は承認期限内のpreflight再試行可。DISPATCHING commit後は自動re-dispatch不可。

### 競合と取消

worker leaseはpreflight担当の回復用。古いworkerにはfencing generation検査を要求し、consume成功前に外部callを許可しない。consume/dispatch予約はlease失効で再発行しない。

suppression/opt-out更新とconsumeは同じCompany/permission lock規約・policy revisionで直列化する。禁止更新が先にcommitした場合はdispatch不可。consumeが先の場合は既に実行認可済みのため、後からの取消・opt-outで相手側の送信を取り消せるとは保証しない。dispatch直前にも最新状態を確認し、可能な限り停止するが、DBと相手サービス間の原子的取消は不可能。UIに「送信開始後は停止できない場合がある」と表示する。

一件のform workflowが確認画面を含む場合、承認済みplanに限り初回POST＋最終確認POSTを許す。これは同じ最終送信のretryではない。各step開始をattempt step ledgerへ記録し、同じstepを再POSTしない。307/308等のPOST再要求、想定外の確認・宛先・意味値変更で停止する。最終受付の有無が不明ならUNKNOWN。

## 9. Idempotency

**アプリ内の同一承認からの重複dispatch防止**と**相手側でのexactly-once**を分ける。後者はSMTP/一般formがキーを受け入れないため保証できない。結果不明でも再送しないことにより、少なくともLeadHiveが同一承認で再度送信する経路を閉じる。

| 制約候補 | 目的 |
| --- | --- |
| unique SendAttempt.approval_request_id | 一承認につき一dispatch attempt |
| unique SendAttempt.idempotency_key | server生成keyの重複予約拒否 |
| conditional update status=APPROVED＋version＋未consumed | concurrent consumeで一者だけ成功 |
| unique ApprovalGrant.request_id | 同requestの承認イベントの二重付与防止 |
| request idempotency registry | 同principal/project/client key＋payload hash→同じPENDING結果、異なるpayloadなら409 |
| active/success/unknown target reservation | 別Draft/別campaignから同一宛先・目的への同時/重複送信も防止 |

server key例は`approval:<request UUID>:<payload version>`。clientが任意keyで新attemptを作れない。tokenを送れば承認できるbearer capabilityとして扱わない。使用済みkeyの再依頼は既存attempt/statusを返し、外部callなし。

target reservationは初期Project scopeで`project_id, company_id, channel, normalized destination, outreach purpose/cycle`を固定し、dispatch時にDB予約する。cycleはHuman承認済み意図へboundし、Agentがcycleを変えて既送信checkを迂回できない。同channelのUNKNOWNはreservationを保持する。cross-channel/cross-projectの抑止は別policy決定が必要で、全社同一法人判定が現状ないことを隠さない。

明確な未送信FAILEDを再試行する場合もnew ApprovalRequest/new SendAttempt、新しいHuman再承認を必要とする。旧keyは再利用しない。新requestにはretry_of_attempt_idを記録する。dup guardの解除はその失敗を人が確認したことに限定し、履歴を消さない。

DB commit後・外部送信前にworkerが停止しても、回復workerはdispatch予約を引き継いで送らずUNKNOWNへ送る。未送信かもしれないが、重複より人の照合を優先する。外部成功後・結果保存前の停止も同様。Message-IDだけをSMTPの冪等保証としない。

## 10. Unknown Result Handling

SendAttemptのstate候補はPREPARING（dispatch前）、DISPATCHING、SENT、FAILED、UNKNOWN、CANCELLED_BEFORE_DISPATCH。approval statusとは別。

| outcome | 意味 | 次操作 |
| --- | --- | --- |
| SENT | emailはSMTP受付成功、formは規定の完了証跡。inbox到達・相手の処理完了とは別 | 既存Activity/成果へ連携 |
| FAILED | 外部副作用が起きていないと確認できる拒否/失敗 | Human review後に新承認でretry可能 |
| UNKNOWN | 送信/受付された可能性を否定できない | queueへ戻さず、Human review通知。dup reservation維持 |

UNKNOWN例: SMTP本文転送後の通信断、form POST後timeout、想定外完了ページ、dispatch後worker停止、最終POST前後の中断、Codex結果証跡不足。HTTP 500や曖昧なvalidation文言だけで「未送信」と断定しない。確実性を確認できない例外はUNKNOWNへ倒す。

Human Reviewはreceipt/SMTP log/正規画面等の根拠を記録し、`SENT_CONFIRMED`又は`NOT_SENT_CONFIRMED`のresolution eventを追加する。元のUNKNOWNイベントを消さない。確認できない場合はUNKNOWN維持、再送不可。NOT_SENTが確定した場合だけHumanが新PENDING retry requestを作り、新承認する。Agentは解決結果を提案できても確定・retry承認不可。

既存UIでUNKNOWNをfailedとまとめない。既存Deliveryへの投影もunknown新状態を用意し、既存workerのstale recoveryからfailed/requeueへ落ちないようにする設計。成功/失敗/不明のmetricsを分離する。

## 11. Audit Ledger

新規候補`outreach_audit_events`はappend-only。request/attemptとイベントが一つのDB transactionで記録され、ledger書込に失敗した場合は承認・consumeをcommitしない。

| 記録項目 | 内容 |
| --- | --- |
| event_id / server sequence / occurred_at | 不変ID、request内順序、server UTC |
| actor | HUMAN/AGENT/SYSTEM、user/agent/credential/worker ID、代理実行関係 |
| request/attempt/proposal/project/company | 対象と関連ID。source IDsのsnapshotも保存 |
| event_type | proposal_created/superseded、approval_granted/rejected/expired/revoked、dispatch_reserved/started、step、sent/failed/unknown、review_resolved、retry_requested等 |
| payload hash/version | どの内容を扱ったか。承認済み内容の固定snapshot参照 |
| transition/reason/correlation | before/after status、reason code、client request key、内部job、retry_of、completion evidence |
| access decision | 認可拒否もcredential/route/projectをsafeに記録。secrets/bodyをエラーログへ反射しない |

Activityは利用者向け業務履歴として維持し、全監査の正本とはしない。Ledgerはowner/editor/Agentからupdate/delete不可。DB application roleもappendに限定し、管理保守手順と権限を分離する。必要に応じイベントhash chain/外部保全を検討できるが、DB管理者の侵害に対する完全なtamper-proofとは主張しない。

payloadの個人情報はアクセス制御・保存期間・暗号化方針を設ける。台帳にSMTP/API秘密値・hidden session token・Cookieを保存しない。Company/Project/Draft削除cascadeでledger/snapshotが失われない。保持と個人情報削除の両立は、redactionイベント/別保管と監査メタデータ維持を規程で決める。Agentへdestructive deleteを公開しない。

## 12. Existing Model Reuse

| 既存 | 再利用方針・追加接点 |
| --- | --- |
| OutreachDraft | 編集可能な準備。source revisionを持ち、承認後編集は新request/旧失効。Draftそのものを不変にする必要はない |
| OutreachDraftApproval | Humanの実承認イベントとして再利用。request/hash/version/proofを紐付け、送信後に初めて承認を記録する経路を廃止する設計 |
| EmailDelivery | 既存SMTP queue/宛先/本文/時刻/UI projection。request/attempt FKとunknown、旧retryは新承認へ接続 |
| FormDelivery | 結果・fingerprint/mapping/完了証跡。POST前attemptの予約を新台帳に置く。profile snapshotと実値の参照追加 |
| EmailCampaign | グループ/停止/成果集計を維持。prepare状態とrequest manifestを追加し、各宛先Human承認後だけqueue |
| FormDeliveryBatch/Item | ready/支援queue/最大20実行を維持。各itemのrequest/attemptを固定、latest Draftを送信しない |
| SuppressionEntry | 正本を維持し共通permission serviceで照合。Agent解除不可、revision/lock規約を共通化 |
| Activity | 成功・拒否・review等のユーザー向け表示。ledgerから必要な業務結果だけ投影 |
| FormProfile/Field/Log | mapping・可否・CAPTCHA・構造版を再利用。承認snapshotと照合、manual修正で関連承認失効 |
| worker / OperationJob | 実行基盤を維持。approval ID中心のjob、consume後の送信retry禁止。通常収集/解析retryと分離 |

### Codex-assisted path

UIと専用Skillは維持するが、`submission_authorized:true`だけを根拠に送信する旧handoffをFoundationの承認保証として利用しない。Humanが承認したsnapshot/request/hash/versionを参照する1件の作業を作り、**最終クリック前にオンラインで** serverのclaim/未使用/期限/禁止を確認する経路が必要。

Codex支援runnerは一般Dots Agentではなく、Humanが起動した一件専用の限定execution contextとする。承認付与や任意宛先送信権限を持たず、server SYSTEMがconsumeした一attempt/stepだけを実行する。結果reportはattempt identityと証跡にboundし、一般Agentのsubmitted boolで確定しない。

CAPTCHAはHumanが正規画面で操作する。操作後、最終送信前に期限・内容・可否を再検査する。送信済みか不明ならSkillもretryせずUNKNOWNにする。stale/禁止なら停止。コピーされた平文taskや署名ticketの検証だけでは取消・単回性を保証できないため、オンラインclaimがない支援経路は新承認体系下で送信を許さない。

外部browserを完全に技術制御できるとは限らない。オンライン検証を実装・受入できるまで、旧Skillの送信は互換性優先で抜け道として残さず停止し、Humanの通常UI reviewへ回す。支援の準備・表示・結果照合機能は維持する。Dots自身には支援execution contextを発行しない。

## 13. Required DB Changes

Migrationは今回作成しない。必要な追加候補を以下に限定して整理する。

| 変更候補 | 目的 |
| --- | --- |
| AgentIdentity / AgentCredential / AgentProjectGrant | 独立principal、token digest/expiry/revoke、scope/project allowlist |
| ApprovalRequest | 不変payloadと承認state、依存version、Human proof/作成者、期限 |
| HumanApprovalProof | 単回step-up challenge/証明とrequest/hash/version/action binding。秘密responseの無期限保存なし |
| SendAttempt | 一承認一attempt、idempotency、outcome/UNKNOWN、dispatch境界、executor evidence |
| DispatchReservation | 別requestからの宛先/目的重複とrate reservation。UNKNOWNの保留 |
| OutreachAuditEvent | append-only ledger、snapshot/主体/transition/correlation |
| RequestIdempotencyRecord | Agent prepare/createのkey、hash、結果ID、保持期間 |
| 既存modelのFK/状態/版 | Draft/source revisions、Approval request binding、Delivery attempt/request、unknown、campaign prepare/manifest、Company/permission revision |

SQLの単純CHECKで関連tableのprincipalや会社所属まで検査できるとは考えない。DBのFK/unique/compound relationと、共通domain serviceの認可・transaction検査を組み合わせる。payload update禁止はservice/DB権限又はguardで保護し、status transitionのみ許す。

既存EmailDelivery/FormDeliveryのunique(draft_id)は初期移行で維持する。新SendAttemptをretryの正本とし、既存Deliveryは同Draftの最新表示projectionへ接続可能とする。全attemptは新台帳に残る。既存uniqueを即削除して重複経路を増やさない。

FKは監査snapshotをcascade削除しない。source削除をRESTRICT/論理削除又はSET NULL＋不変source ID snapshotへ変更する必要がある。保持ポリシーと既存delete UIの動作変更を移行時に明示する。

## 14. Required API Changes

下記は候補契約であり、API追加・変更は実施していない。Agent-facing Thin APIは既存サービスを再利用する。

| endpoint候補 | principal | 契約 |
| --- | --- | --- |
| POST `/api/agent/approval-requests` | outreach:prepare Agent | typed proposal/snapshot sourceを受けPENDING生成。status/approved_by/consume/confirmed入力拒否 |
| GET `/api/agent/approval-requests/{id}` | outreach:read Agent | grant内状態と公開理由。Human proof/ticket/credentials非開示 |
| POST `/api/agent/approval-requests/{id}/revisions` | outreach:prepare Agent | 新PENDING作成、旧未consumed requestの失効。approval変更不可 |
| GET `/api/approval-requests`、`/{id}` | Human read | Project/状態/期限filter、stable pagination、正確なsnapshot |
| POST `/api/approval-requests/{id}/approval-challenge` | Human approve権限 | request/hash/version/actionにboundしたstep-up開始 |
| POST `/api/approval-requests/{id}/approve` | Humanのみ | expected_hash/version、challenge proof。row lock/CAS、APPROVED＋Ledger＋OutreachDraftApproval |
| POST `/{id}/reject`、`/{id}/revoke`（同prefix） | Human権限 | 状態・理由を記録。dispatch開始後の取消限界を返す |
| GET `/api/send-attempts/{id}` | Human又はscoped Agent read | outcome/公開evidenceのみ。再dispatch機能なし |
| POST `/api/send-attempts/{id}/review` | Humanのみ | UNKNOWN解決の証跡。NOT_SENT確定前はretry不可 |
| POST `/api/send-attempts/{id}/retry-request` | Humanのみ | new PENDING生成。再承認は別操作 |

外部send/execute/consume APIは追加しない。approved requestのdispatchは内部workerが担当する。Agentに内部executor credential/ticketを渡さない。

全既存email/form/campaign/batch/retry/Codex result APIにもprincipal guardを適用する。旧confirmed値を送ってもAgentに403。Humanの既存操作は共通ApprovalRequestフローへ橋渡しし、独立snapshot/version/step-upを省略しない。既存routeから共通dispatcherを迂回した直接SMTP/POSTを呼べない構造にする。

SMTP test等のadmin副作用もHuman限定。UI/SMTP接続確認機能は維持し、営業ApprovalRequestとはpurposeを分けたHuman confirmation＋attempt/ledgerで記録する。Agentにglobal adminを与えない。outbound provider keysはM2M認証と別管理。

## 15. Required UI Changes

既存会社・Draft・メール・フォーム・batch/campaign画面を維持し、共通承認panel/queueを追加する設計。

- PENDINGを「承認待ち」と表示。対象会社・channel・宛先・form URL・sender・最終件名/本文・選択値/同意・添付なし・期限を確認できる。
- Agent提案の作成者と根拠を表示し、提案内容は信用済み指示として扱わない。
- 承認時はpreviewに表示したrequest hash/versionでstep-up。確認中の変更は409で止め、diffを見せる。
- 承認後編集は「承認を失効し新版を作る」と明示。フォームfieldの直接上書きで旧承認を流用しない。
- campaign/batchは会社ごとのsnapshot manifestと除外理由を表示。選択した確定対象のみ承認する。
- APPROVEDは送信済みと区別。rate待ち/予約/expired/revokedを表示。CONSUMED以降の取消は結果不明の可能性を伝える。
- UNKNOWNは独立した人のreview queue。ワンクリック再送を出さない。証跡確認→NOT_SENT確定→新承認の順とする。
- Codexは一件の承認snapshot、オンラインclaim、CAPTCHAの人操作、結果reportへ接続する。古いコピーtaskを最終承認扱いにしない。

UIを隠すだけでは認可にならない。viewer/Agentの制限はAPI/serviceにも適用し、UIはそれを説明する役割とする。

## 16. Migration Strategy

設計段階の順序であり、今回は実行しない。

1. isolated DB/backupで現行schema・queue・記録・cascadeを確認し、移行対象と停止時間を決める。
2. additive schema、nullable FK、new states/index/ledgerを追加する将来Migrationを作る。既存Migrationを書換えない。
3. historical sent/failed/cancelledはLEGACY_IMPORTEDの証跡として台帳へ取り込み、後からHuman承認済みと偽装しない。新requestのAPPROVEDは付与しない。
4. queued email/ready form/既存Codex taskは移行時に送信を停止し、固定内容をPENDINGとして再承認する。running/dispatch途中はUNKNOWNとして人が照合する。旧queuedを自動で承認済みにbackfillしない。
5. 共通認可/承認/consumeを全経路へ接続した後にconstraints・非null・更新禁止を段階強化する。未接続executorをfail-closedとする。
6. 新方式でHuman単体UI、worker、SMTP/form、batch、Skill経路を隔離fixtureで検証した後に送信再開を判断する。Agent credential発行はさらに後である。

移行作業中は既存workerの送信をpauseし、旧worker binaryと新schema/新承認workerが同時に送らないよう互換version gateを設ける。code rollback時は送信停止を維持し、旧confirmed経路へ戻して自動送信を再開しない。DB downgradeで台帳を消すrollbackはしない。backup/forward repairを基本とする。

## 17. Backward Compatibility

LeadHiveの再構築は不要。既存User login、Project/TargetProfile、収集/解析、SMTP/IMAP、Form Intelligence、営業一覧・Activity・返信/Dealの利用を維持する。Dots未接続でもHumanがDraft→PENDING→承認→worker実行できる。

安全に関わる互換性は意図的に変更する: confirmed boolだけの送信、latest Draftを送るbatch、旧送信retry、平文Skill taskによる単独最終承認は互換送信として残さない。旧route/pathを維持する場合も新承認の橋渡し又は明示的な再承認required errorを返す。

過去Approval/Delivery/Activityは履歴として表示し、legacy印を付ける。新しいapproved payload/hashを過去記録へ捏造しない。新attemptは旧Deliveryと関連し、成果集計はattempt数と実送信数を分け、retryで過去成果を二重加算しない。

Agent機能はfeature flagで無効にできるが、Foundationのdispatch guardは外せない。既存SYSTEM内部処理からAPPROVEDを偽造するfallbackなし。Codex online gate未完成ならその送信経路を停止し、通常UI運用は維持する。

## 18. Security Tests

以下は実装時のテスト計画。今回はテストコード・fixtureを追加せず、実行していない。SMTP/Formは隔離fake executor、実企業に接続しない。

| テスト | 必須検証 |
| --- | --- |
| principal/scope | Agentのapprove/send/legacy confirmed/admin/解除/delete全経路403。Cookie混在拒否、principal偽装不可 |
| Human権限 | viewer/other project/期限切れsession/step-upなし拒否。owner/editorの正しい承認だけ成功 |
| approval challenge | hash/version/user/session/action/expiry/単回検査、別request/replay/CSRFで失敗 |
| strict input | approved_by/status/hash/権限のmass assignment拒否。unknown scopeのtoken発行不可 |
| immutable payload | Draft/target/recipient/sender/form/mapping変更でREVOKED、新version再承認。切詰め・署名付加が承認後に起こらない |
| template/version | source revision競合、更新通知漏れでもdispatch最終検査で止まる |
| concurrency | 同承認100並列consume＋複数workerで外部dispatch一回。別campaign/Draft同宛先競合も予約で防ぐ |
| crash windows | consume前/commit後送信前/送信中/成功直後DB記録前のfault injection、復帰workerがre-dispatchしない |
| suppression/opt-out | approval後更新・解除試行・raceのcommit順で送信可否を検証。Agent解除は不可 |
| rate | 並列workerでemail/form quota超過しない、UNKNOWN reservationを数える、expiry中待機失効 |
| form workflow | live fingerprint/営業禁止/CAPTCHA/確認画面意味値/redirect変更で停止。各step再POSTなし |
| UNKNOWN | ambiguous SMTP/form/fake Codex evidenceでUNKNOWN。自動/Agent retry不可、Humanの証跡resolveのみ |
| ledger/retention | business状態とledger原子性、update/delete拒否、cascadeで消えない、秘密非保存 |
| Codex | 平文true/replayed ticket/expired/revoked/別target/オフラインclaimで送信不可。CAPTCHA人介在 |
| compatibility | Dotsなし、Human UI/worker、legacy再承認、campaign/batch、migration/backfill/rollback-stop |

副作用のカウントはDB row数ではなくfake SMTP acceptance/各form POSTの実行回数で検証する。blocker B3の回帰テストはDB conflict後にすでに二度POSTされていないことを確認する。

## 19. Acceptance Criteria

| ID | 完了条件 |
| --- | --- |
| AC01 | Agent credentialだけでは既存/新API・worker経路のいずれからも未承認送信できない |
| AC02 | AgentはPENDING requestを作れるがApproval grant/APPROVED/proof/consumeを作れない |
| AC03 | 有効権限とstep-upを持つHumanだけがAPPROVEDへ変更できる |
| AC04 | 承認後の意味的target/payload変更は旧承認を失効し、新versionの再承認を必要とする |
| AC05 | 同じapprovalに対する並列request/recovery/replayでLeadHiveから同じ外部dispatchを二度開始しない |
| AC06 | Agentがsuppression/opt-outを解除・迂回できず、実行直前にも再照合される |
| AC07 | UNKNOWNを自動retryせず、人の照合が終わるまで新dispatchを許可しない |
| AC08 | 提案・承認内容・主体・hash/version・dispatch・結果・retry・拒否・取消を台帳で追跡できる |
| AC09 | 既存LeadHive UIからHuman Approvalでき、Dots未接続でも単体運用できる |
| AC10 | email/form/campaign/batch/retry/Codex/admin testの副作用経路が共通guardを迂回できない |
| AC11 | 旧queued/running/taskを暗黙承認せず移行し、旧worker/rollbackで送信が再開しない |
| AC12 | 同意した本文・sender・宛先・fieldsと実送信値が一致し、snapshotが編集/削除で失われない |

AC05はLeadHiveのdispatch単回保証。第三者サービスが内部で複製することや、結果不明を人が誤って未送信と判断することまでexactly-once保証とはしない。AC03はHumanのsession/認証器非共有と信頼されたUI/端末を前提とし、AgentをHuman sessionへ偽装してよい例外を設けない。

## 20. Implementation Phases

実装開始の許可ではなく、将来着手時の分割案。各段階で別途受入確認し、承認/送信Foundation完了前にAgent接続を有効化しない。

| 段階 | 将来作業 | 完了条件・停止点 |
| --- | --- | --- |
| A1 設計確定 | principal/step-up、canonical payload、dup scope、expiry、UNKNOWN、保持をreview | HumanとAgentの境界を合意。今回の成果はここまでの設計案 |
| A2 承認基盤 | additive DB、PENDING、Human approval、ledger、既存UI bridge | fake executorでAC01〜04/08/09、送信は停止 |
| A3 dispatch基盤 | atomic consume、idempotency、reservation、email/form snapshot、UNKNOWN | fault/concurrencyでAC05〜07/10/12、実送信なし |
| A4 互換移行 | legacy queues/history、campaign/batch/retry、worker version gate、Codex online gate | AC10/11。未対応経路は停止、旧経路へfallbackなし |
| A5 Agent準備境界 | credential/scopes、Thin API read/propose/prepareのみ | forbidden matrix全件拒否。最初は非送信PoCだけ |
| A6 運用受入 | backup/retention/権限/取消の説明、Human単体運用、承認された隔離検証 | 本書の受入条件を満たした後、別指示で運用開始判断 |

未確定の設計判断は、step-up認証器/配布方式、Human approval期間、重複抑止のProject/全社scope、監査保持期間、Codex online runnerの信頼境界である。これらを固定せずに「confirmedから新boolへ置換」する実装を開始しない。

**STOP: 本書の作成・整合確認で終了する。コード変更、Migration作成、API/UI追加、DB変更、deploy、send、test send、外部API実行、PoC実行は行わない。commit/pushも今回の指示には含めず実施していない。**
