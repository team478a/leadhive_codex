# LeadHive — Agent & Automation Governance Direction Correction

設計・影響分析のみ / 2026-10-03。

監査branch: `codex/integration`。実装baseline: `f5885b7707536b4b7a7d8f50edeb724430933c58`。
既存A2設計・実装を保持する。本書は追加設計であり、Policy、tenant、dispatchの実装完了を意味しない。
今回、コード・既存設計書・Migration・DB・設定を変更せず、サービス起動、送信、Dots接続、deployment、commit/pushを行わない。

## 1. Executive Summary

LeadHive Coreを正本・実行主体とし、Dots/ChatGPT/Codex/第三者Agentは同じClient Boundaryを利用する。
Human Approval FoundationはMANUALモードの個別承認として維持する。自動実行には別のPolicyAuthorizationを追加し、SYSTEMがHuman承認を偽造する経路を作らない。

既存コードのAgent認証、scope、REST path、Modelは既に製品中立。Dots固有なのは主に設計書名・説明・過去PoCの前提であり、認証を作り直す必要はない。
一方、Organization、Organization管理権限、組織別credentials/settings、AutomationPolicy、PolicyAuthorization、共通SendAttemptは存在しない。
**A2は承認までで、既存の配送API/workerはA2に未接続。安全な自動送信を現在有効にできる状態ではない。**

推奨: G1で再利用範囲、tenant契約、共通dispatchの前提を確定し、その後段階的にPolicyを追加する。G2/G3では判断・証跡だけを実装できるが、G4/G5で配送を有効にする前にtenant隔離と全配送経路の共通Safety/Dispatch Foundationが必須。

## 2. Current Implementation

確認根拠:

| ファイル | 確認した実装 |
| --- | --- |
| `backend/app/model_approval.py` | AgentIdentity/Credential/ProjectGrant、ApprovalRequest、HumanApprovalProof、OutreachAuditEvent |
| `backend/app/schema_approval.py` | 8種scope allowlist、unknown/禁止scope拒否、strict提案入力、expected hash/version |
| `backend/app/services/approval_principals.py` | Cookie/Bearer分離、feature flag、credential/grant/scope照合、拒否台帳 |
| `backend/app/services/human_approval.py` | canonical snapshot、SHA-256、改訂・依存変更失効、24時間上限、5分step-up、Human専用承認 |
| `backend/app/approval_routes.py` | Human承認API、Agent提案作成/改訂/参照API、Project権限と行lock |
| `backend/migrations/versions/a2f0c6d8e913_human_approval_foundation.py` | append-only台帳、payload不変、承認証跡不変、CONSUMED遷移禁止 |
| `frontend/src/ApprovalQueuePage.tsx` | Human承認キュー、再認証、却下/取消、viewer閲覧、送信ボタンなし |
| `backend/app/model_core.py`, `project_access.py`, `security.py` | User、Project owner/editor/viewer、Browser AuthSession、global is_admin |
| `backend/app/model_outreach.py`, `outreach_draft_routes.py`, `campaign_routes.py`, `form_batch_routes.py`, `worker.py` | 既存Draft/Approval、メール/フォーム/Campaign/Batch、confirmed経路、配送lease/limit |
| `backend/app/services/contact_permission.py`, `inbound_email.py`, `model_operations.py` | Project別Suppression、Company連絡禁止、opt-out取込、可否判定 |
| `backend/app/services/form_profile_delivery.py`, `form_delivery.py`, `form_delivery_result.py` | Form Intelligence参照、fingerprint/URL/CAPTCHA等の検査と配送結果確認 |
| `backend/app/model_settings.py`, `services/application_settings.py`, `services/email_delivery.py` | 単一settings行、process共有設定、SMTP/送信者/受信設定 |
| `backend/tests/test_approval_foundation.py`, `frontend/tests/approval.spec.ts` | A2のprincipal/scope/step-up/payload/台帳/失効のテストコード |
| `docs/DOTS_HUMAN_APPROVAL_FOUNDATION_DESIGN.md`, `DOTS_HUMAN_APPROVAL_A2_IMPLEMENTATION.md` | A1/A2の設計・既存検証結果・A3未接続の制限 |

Organization/Tenant、AutomationPolicy、PolicyAuthorization、SendAttempt Modelはコード検索で未検出。
EmailDeliveryの状態はqueued/running/sent/failed/cancelled、FormDeliveryはpending/submitted/failedで、共通UNKNOWN状態はない。
A2のApprovalRequestにCONSUMEDという状態名はあるが、Service/APIは実装せずDB triggerも遷移を禁止する。
本監査ではテストを再実行していない。A2文書の既存PASS結果と、今回コードから確認した事実を区別する。

## 3. Direction Correction

```text
Users / Organizations
 ├ LeadHive Web UI
 ├ Dots / ChatGPT / custom Agent / Future LeadHive Agent
 └ Codex（準備Client又はExecution Assistant。権限は用途ごとに別）
         ↓ Human / Agent principal + tenant + Project grant
LeadHive Agent / Client Boundary
         ↓ immutable proposal（prepareのみ）
Automation Governance
 ├ Core Safety Rules → BLOCK / Human handling / eligible
 └ Deterministic Policy Decision
      ├ MANUAL / 条件外 → Human Approval
      └ 条件内 → PolicyAuthorization
         ↓ 共通Execution Guard / atomic reservation
LeadHive Core → Email / Form / Codex-assisted → 結果・返信・監査
```

モードはprincipalの種類と独立。AgentがMANUALの提案を作っても、RULE_BASEDの提案を作ってもHumanには変換しない。
AUTONOMOUSは事前に許可されたworkflow範囲の拡大であり、外部Agentへsend権限を渡すモードではない。

## 4. Existing Foundation Reuse

分類は要素単位。同じModelでもMANUALの挙動はREUSE AS-IS、tenant contextの追加はEXTENDになる。

| 要素 | 分類 | 再利用・変更方針 |
| --- | --- | --- |
| Human/Agent credential分離、Cookie混在拒否 | REUSE AS-IS | 認証方式を維持。AgentをUserへ変換しない |
| scope allowlist、Agentからapprove/reject/revoke拒否 | REUSE AS-IS | Policy導入でも維持。send/解除/policy変更をAgentに発行しない |
| Human step-up、ApprovalRequestのHuman証跡 | REUSE AS-IS | MANUAL個別承認に利用。policy管理にも別actionで同じVerifier境界を利用 |
| canonical snapshot/hash/version、改訂・依存変更失効 | REUSE AS-IS | 共通prepareに利用。不変payloadを再度live Draftから組み直さない |
| expiration、reject/revoke、Human-only APPROVED | REUSE AS-IS | Policy経路の追加を理由にHuman state machineを緩めない |
| AgentIdentity/Credential/ProjectGrant | EXTEND | Organization binding、Client metadata、組織/grant失効、権限監査 |
| ApprovalRequest / HumanApprovalProof | EXTEND | 不変tenant binding、認可参照。既存snapshot/hashを変更しない |
| OutreachAuditEvent | EXTEND | Policy/authorization/tenant/attemptを示す追記又は不変context。過去台帳は更新しない |
| 承認キュー | EXTEND | Human review対象とPolicy authorizedを別表示。Agent flag OFFでもMANUALを維持 |
| contact_permission、URL/form validation | EXTEND | 基本判定を再利用し、全配送経路・tenantに共通適用する |
| Dots名の設計書/PoC説明 | GENERALIZE | 新文書・新API説明をLeadHive Agent APIへ。既存文書名/pathは互換のため残す |
| `/api/agent/...`, `Agent*`名称 | REUSE AS-IS | 既に中立的。無益なリネームはしない |
| 「全Agent提案は必ずHuman承認」という唯一の認可前提 | CONFLICT | MANUAL内に限定し、別PolicyAuthorizationを追加する |
| `valid_approved_payload()`だけを共通dispatch資格にする案 | CONFLICT | Human資格検査として保持。Policy資格は別Verifier、共通Guardで統合 |
| User.is_adminとsingleton SMTP/API/送信者設定 | CONFLICT | 複数企業のOrg admin/credentialsとしては利用不可。platform権限とOrg権限を分離 |
| legacy confirmed配送、結果不明をfailedにまとめる処理 | CONFLICT | 新共通認可/Safety/UNKNOWN経路への移行が必要。今回は維持 |
| legacy OutreachDraftApproval/confirmed入力 | DEPRECATE LATER | 共通配送へ移行後に書込経路を段階停止。履歴・参照互換は維持 |

## 5. Multi-user / Multi-tenant Requirements

現状は複数User/Project memberに対応しているが、企業単位のtenant隔離はない。Project隔離をtenant隔離と同一視しない。
Userはグローバルなログインidentityとし、OrganizationMembershipで複数Organizationへ所属可能にする。session内の選択Orgは認可根拠にせず、毎requestでmembershipを検証する。
Organization owner/adminとProject owner/editor/viewerは別Role。global is_adminをOrganization adminと読み替えない。

| 対象 | 現在の境界 | 必要なtenant境界 |
| --- | --- | --- |
| Organization / Tenant | なし | Organization + Membership、状態、失効、Org選択 |
| User | global identity、global is_admin | Membership/Org role。別企業の管理権限を自動付与しない |
| Project | User owner + ProjectMember | 1 Project = 1 Org。不変ProjectOrganization binding |
| AgentIdentity | 作成Userのみ | 1 identity = 1 Org。同じClientでもOrgごとに別identity |
| AgentCredential | identity、scope、期限 | 発行時のOrg binding固定、Client失効、Project grantsとの一致 |
| AutomationPolicy | 未実装 | Orgの上限 + Project policy version。Orgを跨ぐ参照を拒否 |
| ApprovalRequest / Proof | Project/User | Project由来のOrg binding、現在membership/Project role再確認 |
| PolicyAuthorization | 未実装 | Org/Project/company/policy版/payload版へ固定 |
| SendAttempt / reservation | 未実装 | Org/Project/authorization/payload、同一業務intentの重複防止 |
| Suppression / opt-out | Project/Company別 | Organization単位の禁止正本 + Project追加禁止。Project変更で回避不可 |
| Audit Event | Projectはnullable、actor UUID | Org別閲覧、platform security eventsの隔離、append-only context |
| SMTP/IMAP/API keys/送信者 | singleton/process共有 | Org別credential設定。cache/worker/API clientもOrgで分離 |

最初の互換導入では既存デプロイ全体を一つのLegacy Organizationへ紐付ける。owner Userごとに別Orgを自動作成すると、既存の共同Project/共有settingsを誤分割する。
複数企業の既存データが混在している場合は移行対応表をHumanが確認し、それまでは新Org/自動配送を有効にしない。
既存Project ID、User ID、ProjectMember、payload、hashを維持し、移動は通常編集にしない。履歴/未使用認可を持つProjectのOrg変更は専用移管・再認可工程とする。

## 6. Automation Modes

| Mode | 判断・workflow | 配送の認可 | 条件外 |
| --- | --- | --- | --- |
| MANUAL（default） | Human/Agentがprepare | Human個別承認 + Core Safety | Human review又はBLOCK |
| RULE_BASED | 候補/Draftごとに確定済みruleを評価 | 条件一致時だけPolicyAuthorization + Core Safety | REQUIRE_HUMAN_APPROVAL |
| AUTONOMOUS | 許可された収集/分析/選定/Draft workflowをSYSTEMが継続 | 各候補ごとに同じrule、PolicyAuthorization、予算、Core Safety | review/BLOCK/一時停止 |

AUTONOMOUSもrule閾値やsender/template許可を持つ。AIが「送るべき」と説明しただけでは認可しない。
未設定・無効・失効Policyは自動実行不可でMANUAL相当へ戻す。Organization停止/kill switchは全dispatchをBLOCK。
rate不足は外部call前の待機/DEFERとし、再評価前提。3値のPolicy Decisionとは別の実行状態にする。

## 7. AutomationPolicy

最小構造案: policy identity + append-only AutomationPolicyVersion + Projectの有効版参照。
評価可能なpublished versionは不変。変更は新versionを作り、Human管理者の再認証を経てactivateする。

| 項目 | 最小案 |
| --- | --- |
| id / organization_id / project_id | Project policy。Org上限は別の管理設定。Org一致をDB/APIで検査 |
| mode / enabled | MANUAL既定。無効化は自動実行停止 |
| allowed_channels | 初期email/formのみ。delivery_methodも限定しCodex権限をchannel許可から推測しない |
| allowed_senders / allowed_templates | 同じOrg/Projectのidentity ID + 承認済みversion/digest。単なる編集可能IDでは不十分 |
| minimum_score / allowed_ranks | optional閾値。ただし自動化で未設定なら許可範囲を明示承認する |
| daily_limit / per_hour_limit | 必須の有限上限。Org/Project/sender/provider各上限の最小値を適用 |
| duplicate_window | Core最低window以上。UNKNOWNの未解決intentはwindow満了でも送信しない |
| require_sales_permission / require_form_ready | 自動formはALLOWED/READY必須。Core hard rulesをfalseで無効化できない |
| allow_unknown_permission | 初期自動配送ではfalse固定。trueは未知候補のHuman review受理だけを意味し、自動配送許可にしない |
| human_review_conditions | version付きtyped predicate。任意Python/SQL/AI自由文は禁止 |
| effective_from / expires_at | 必須の有限期間。最長期間はOrg上限で決定。A2個別承認の24時間とは独立 |
| created_by / approved_by / approved_at / version | Human管理者とPolicy publication証跡、policy_hash、step-up proof |
| workflow_constraints | AUTONOMOUSの地域・source・収集/AI予算・並行数・cycle上限。G2では予約しG5で確定 |

AgentはPolicy変更案をproposeできるだけ。適用、approve、activate、上限緩和、mode変更のAPIにはHuman管理者＋Org権限＋step-upが必要。
Project ownerのpolicy管理権限はOrg管理者から委譲する。Project editorが営業操作できることだけでPolicyを緩和できない。
restrictionを強める停止/revokeもAgentには直接公開せず、Human管理者又は限定された内部Safety SYSTEMが実行する。
無期限・wildcard sender/template・不明predicate・閾値欠落によるimplicit allowを拒否する。

## 8. Policy Decision Engine

Coreのdeterministic evaluator。入力はtenant、Project、Company、確定解析版、sealed payload、Policy version、現在のSafety事実、server time。
Web本文、Agent instruction、分析理由の自由文はruleやscopeを変更できないUntrusted Data。
Agentの`analysis:propose`は提案保存だけ。Agentがscore/rankを自己書換えして自動認可を得ないよう、評価は信頼された解析pipelineの確定値・provenance/versionを使う。外部提案を確定値へ昇格する契約はG2/G6で別に定義する。

評価優先順位:

1. tenant/資格/Org停止/宛先等のCore hard violation → BLOCK。
2. CAPTCHAや未確認permission/profile → REQUIRE_HUMAN_APPROVAL又は専用Human handling。Human承認だけではCAPTCHA自動化を許可しない。
3. MANUAL又は有効Policyなし → REQUIRE_HUMAN_APPROVAL。
4. 有効Policyでもscore/rank/template/sender/channel等の条件不一致 → REQUIRE_HUMAN_APPROVAL。
5. 全条件一致 → ALLOW_AUTOMATED。G3以降だけPolicyAuthorizationを生成可能。

結果はdecision、安定reason_code、判定値/閾値、matched_rules、ruleset_version、policy_hash/version、payload_hash/version、解析/安全情報参照、評価日時として保存する。
例: `REQUIRE_HUMAN_APPROVAL / score_below_threshold / observed=82 / minimum=85`、`BLOCK / company_suppressed`。
評価error・データ不足は自動許可せず、review又はBLOCKへ。UI文言はreason_codeから生成し、AIに判定を任せない。

## 9. Human Approval

`authorization_type=HUMAN_APPROVAL`。既存ApprovalRequest APPROVED、HumanApprovalProof、承認者・日時・hash/versionをそのまま利用する。
MANUALの個別承認者は既存owner/editor方針を維持し、追加tenant membershipを検査する。Policyの管理者権限とは区別する。
個別承認はPolicy条件外の候補を検討する経路であり、suppression等のCore hard BLOCKを上書きする例外ではない。
承認済みでも実行時Safety、scope/資格、期限、依存変更、重複、予算を再確認する。
SYSTEM/Agent/PolicyはAPPROVEDに遷移できない。CONSUMEDへの実装は別のDispatch Foundation工程で行う。

## 10. Policy Authorization

`authorization_type=POLICY_AUTHORIZATION`。Humanのapproved_byを付けず、PolicyPublicationのHuman管理者と自動認可のSYSTEMを別々に記録する。

最小PolicyAuthorization案:

- id、organization_id、project_id、company_id、prepared_request_id。
- policy_id、policy_version、policy_hash、ruleset_version、decision_id。
- channel/delivery_method、payload_hash/version、matched_rules、execution_constraints_snapshot。
- authorization_time、expires_at、status（ISSUED/REVOKED/EXPIRED/CONSUMED）。CONSUMEDはdispatch実装後だけ。
- issued_by_principal=SYSTEM。初期は同一request/version/policy versionへの重複発行をunique/CASで防ぐ。

認可期限はPolicy expiry、payload expiry（既存A2は24時間）、Safety情報の鮮度上限の最小値。自動認可を無期限にしない。
Policyを変更してもpublished versionは書き換えない。未実行の旧Policy認可はactivate/revoke時に失効させ、最新有効Policyで再評価する。履歴として旧versionは残す。
発行時と実行時の間にsuppression/Policy/grant/Company/送信者/formが変われば再検査して拒否する。

### 不変payloadの再利用と状態の分離

初期の最小案は既存ApprovalRequestのimmutable envelopeを準備内容の保存先として再利用し、generic DTOでは`PreparedOutreach`として扱う。二つの編集可能な本文正本は作らない。
PolicyAuthorizationはそのrequest/hash/versionを参照するだけ。Policy経路でApprovalRequestをAPPROVEDにしない。Human証跡はnullのまま。
Policy経路のrequestがPENDINGでも、それはHuman承認済みを意味しない。UIの業務状態はPolicyDecision/Authorizationとの組合せで算出し、Human QueueにはMANUAL又はREQUIRE_HUMAN_APPROVALだけを表示する。
Agentによる改訂は既存どおり新PENDING版を作る。旧Human承認に加えて旧PolicyAuthorizationも失効する。
HumanとPolicyが同じpayloadを認可しても、共通のreservation/intent uniqueにより実送信を二重化しない。
将来payload保存先を分離する必要が判明した場合も、A2のrow/hash/台帳を残すadditive参照移行を行う。今回は新payload Modelの実装・改名をしない。

## 11. Core Safety Rules

Policy DecisionのALLOWもHumanのAPPROVEDも、外部callを直接許可しない。最後に共通Execution Guardを必ず通す。

| Rule | モード共通の強制と既存の根拠/不足 |
| --- | --- |
| suppression / opt-out / do_not_contact | `contact_permission.py`を判定の入口として再利用。Org + Project禁止の和集合。解除を送信API/Policy/Agentに付けない |
| sales prohibition | Form ProfileのPROHIBITEDはBLOCK。email permissionとのchannel差も明示し、公開禁止文の適用範囲はG1で確定 |
| dangerous URL | scraper/form_deliveryの検査を共通Guardへ。fetch/redirect/action/確認ページ各hopでSSRF/DNS/origin検証 |
| CAPTCHA | 自動化禁止。Human handlingへ。Codex/Policy/承認で突破権限を与えない |
| duplicate-send | tenant/Project/business intent/会社/宛先/channel/payloadを含む安定キーと原子的reservation。既存draft uniqueだけでは不十分 |
| sender validity | Orgに属する許可済みsender/transport identity。SMTP secretはAgentへ公開しない |
| destination validity | tenant/Project所属、recipient/domain/Form targetの一致と品質。Agentのarbitrary URL/宛先へそのまま配送しない |
| rate / daily limit | Org/Project/sender/provider/全体capacityをtransactionで予約。UNKNOWNも予約を安易に解放しない |
| form fingerprint | 保存済みmapping/hashに加えて実行時DOMを検証。変更・未対応profileでは停止/再解析・再認可 |
| immutable dispatch payload | A2のsnapshotを基準に最終SMTP本文、unsubscribe付加、送信者、fields、attachment digestも事前に確定。現在workerの送信時unsubscribe付加は未統合 |
| idempotency | 同じ認可/業務intentの同時claim・retry/recoveryを一つのattemptへ集約。外部protocolのexactly-once保証と混同しない |
| UNKNOWN protection | 通信断/worker中断等で結果不明なら共通UNKNOWN。自動retry、別Agent/別Policyによる同じintentの再作成を拒否しHuman Reviewへ |

重複防止キーは二層にする。認可ID/request/hashによる再実行idempotencyと、Org・会社・正規化宛先・channel・serverが定義するcampaign/thread等の業務intentによる重複防止を分ける。
A2のpayload_hashにはproposal_id/versionが含まれるため、同じ本文を別proposalで作るとhashが変わる。そのhashだけを重複判定に用いず、意味的な送信内容のdigestと業務intentも照合する。Agentに任意intent IDで新規送信を装う権限は与えない。UNKNOWNが残るintentを新版payloadや別Agentで回避できないようにする。

現在のemail workerにはcontact permission再検査、advisory lock、daily/interval制御がある。一方、全経路共通の認可・immutable最終payload・UNKNOWNは未完成。
外部call後のDB保存失敗を単純FAILEDとして再送可能にする構造は、新Governanceに接続する前に修正が必要。
通常のHuman承認も安全制御のoverrideではない。opt-out等の正当な状態訂正は別のHuman管理workflowと証跡を必要とし、dispatchの例外switchにしない。
実際のSMTPテスト送信やフォーム検証送信も外部送信として扱う。接続確認やpreviewをarbitrary-sendの抜け道にしない。

## 12. Agent API

名称はLeadHive Agent API。既存`/api/agent/projects/{id}/approval-requests`を互換維持する。

| Tool/操作候補 | Scope / 境界 | 現状 |
| --- | --- | --- |
| start_collection | collection:create、Org/Project budget、idempotent job開始 | Agent専用API未実装。既存collection Service/RESTをadapterで利用候補 |
| get_job_status | job:read、tenant/Project所有job | Agent専用未実装 |
| list_companies / get_company | company:read、pagination/filter、secret除外 | Agent専用未実装 |
| propose_analysis | analysis:propose、provenance付き提案 | scope登録のみ。確定scoreの直接編集は不可 |
| prepare_outreach / create_approval_request | outreach:prepare、不変提案 | A2のPENDING作成/改訂を再利用 |
| get_authorization_status | outreach:read、human/policy種別とreason参照 | A2の提案参照を拡張。Policy/実行状態未実装 |
| get_outreach_result | outreach:read、attempt/result/UNKNOWN等参照 | Agent専用未実装 |

禁止操作: approve_as_human、change_policy、remove_suppression、remove_optout、arbitrary_send、bypass_policy、credential読み書き。
Policy変更案APIを追加する場合も提案専用scopeとHuman publicationを分ける。既存allowlistを緩めてpolicy:update等をAgentへ発行しない。
Clientがmode/policy_id/authorization_typeを送ってもserverが有効Policy・principal・tenantから決定する。過剰なprepare/収集には予算・rate・取消/recovery境界を設ける。

## 13. Dots as One Client

Client metadataには製品名/instance識別を保存可能だが、Dots名でCoreの許可判定を分岐しない。
同じscope/Project grant/Org契約をDots、ChatGPT、custom Agent等へ適用する。
Agent credentialを共有せず、Client/Orgごとに発行・失効できるようにする。Client差はadapter/tool形式へ閉じ込める。
過去のDots設計書は歴史資料として保存し、本書を現在方針とする。既存APIやDB名をDotsから無意味にrenameしない。

## 14. Codex Assisted Path

| 経路 | Governance |
| --- | --- |
| NORMAL PATH | LeadHiveの対応executor。どのmodeでも認可＋Guardを要求 |
| CODEX ASSISTED | 特殊フォームの限定Execution Assistant。Org/Project/attempt/payloadへbindした短期task権限だけ |
| HUMAN REQUIRED | CAPTCHA、未知構造、確認画面の判断、UNKNOWN照合。自動retry/突破なし |
| BLOCKED | suppression/opt-out/営業禁止/危険URL/資格違反等。Human承認やCodex起動で解除不可 |

同じCodex製品でもprepareするAgent Client資格とdispatchを補助するexecutor資格を別用途として分離する。
executor用権限は一般Agent tokenに追加しない。認可・mapping・fingerprintが変わればtaskを失効させる。
既存Codex handoff/結果入力経路も共通attempt/認可のadapterへ段階移行する。自由文によるsubmitted申告だけを確実な送信証拠としない。

## 15. Audit Model

LeadHive DBが正本。Company/contact/source/解析確定版、payload、Policy publication、個別Human proof、Policy decision/authorization、attempt、結果/返信、suppression/opt-out、失効/UNKNOWN照合を保存する。
AgentのMemoryや会話はこれらの正本にしない。

台帳で分離する主体と根拠:

- proposal actor: HUMAN/AGENT。
- Human authorization: HUMAN、approved_by、proof、hash/version。
- Policy publication: HUMAN管理者、policy hash/version、step-up。
- Policy decision/authorization: SYSTEM、policy/ruleset版、観測値/条件、decision reasons。
- execution: SYSTEM/executor、authorization_type、authorization_id、attempt/reservation、結果。

OutreachAuditEventを追記専用として維持し、Policy発行/変更提案/activate/revoke、評価、review、BLOCK、duplicate prevented、UNKNOWN、照合等のeventを追加する。
既存eventの列やreasonをバックフィルで書換えない。secret/password/token/取得HTML/本文は台帳へ直接入れず、アクセス制御されたpayloadへの参照とdigestを使う。
dashboardはHuman approved、Policy authorized、Auto sent、Human review required、Blocked、UNKNOWN、Suppressed、Duplicate preventedを別集計する。同じ候補の複数eventを「送信数」として二重集計しない。

## 16. UI Changes

ProjectにAutomation Modeと有効Policy versionを表示。default MANUAL。Organization選択と管理権限を先に明示する。
RULE_BASED/AUTONOMOUSでは条件、上限、sender/template/channel/method、期限、review条件、現在のbudget使用量を確認できるようにする。
自動化拡大の変更は変更前後差分、警告、Human管理者step-up、activate確認を必要とする。Agentの変更案は別のproposal欄に表示する。
Human Queueは既存step-up UIを維持し、Policy authorizedをHuman approvedと表示しない。
BLOCK、review、temporarily deferred、UNKNOWNを区別し、UNKNOWNに通常retryボタンを付けない。Human照合用の専用画面を設ける。
Human-approvedでもCore Safetyにより実行不可となった理由を表示し、「承認したのに送られない」状態を説明する。

## 17. Migration Impact

**今回はMigrationを作成・実行しない。** 将来すべてadditive revisionで段階適用する。

1. Organization、OrganizationMembership、ProjectOrganization bindingを追加。既存Project/User/Memberは維持する。1 Project = 1 Orgをuniqueで保証。
2. Agent identity/credentialのOrg固定、旧Approval/Proof/ledgerのtenant contextを不変sidecar bindingで追加。Project→Orgと複合FK/制約で一致させる。
3. Org別sender/SMTP/IMAP/provider credentials、Org suppression/opt-out正本と旧Project禁止の読み合わせを追加。旧singletonはLegacy Org互換として当面維持する。
4. AutomationPolicy/immutable PolicyVersion/PolicyDecisionを追加。MANUAL既定、dry-run only。
5. PolicyAuthorizationと共通authorization参照を追加。PolicyにはHuman承認列を流用しない。
6. 別Dispatch Foundation工程でSendAttempt、reservation、budget reservation、UNKNOWN/reconciliationを追加し、既存delivery/Campaign/Batchへ参照を追加する。

### 不変A2データへのtenant追加

A2のpayload triggerはstatus/proof列以外のUPDATEを拒否し、台帳triggerはUPDATE/DELETE/TRUNCATEを拒否する。`organization_id`列を単純追加して過去rowをUPDATEするmigrationは衝突する。
推奨は不変sidecar binding: ApprovalTenantBinding/OutreachAuditContext等を追加し、過去rowのpayload/hash/ledgerを一切書換えずOrgを紐付ける。binding自体も変更不可とする。
新Policy/attempt ModelはOrgを明示保存し、既存resourceはbinding/Project join経由で必ずOrgを検証する。
Projectなしの認証失敗eventはplatform security contextに保持し、どのOrgにも未検証で割当てない。Orgの台帳一覧からは除外する。
新snapshot形式が必要な場合はcanonicalization_versionを更新し、新requestから利用する。既存json-v1 hashを再計算しない。

rollbackは新機能flagをOFFにし、MANUALと既存データを保持する。Policy/承認/台帳作成後にテーブルをdropするdowngradeを通常のrollbackにしない。

## 18. Backward Compatibility

A2のModel、path、step-up、Human-only APPROVED、default Agent OFF、既存UIを維持する。
Policyなし/feature OFFでは新しい自動化が起動しない。新mode導入を既存Projectへ自動適用しない。
既存Human配送の機能を今回削除しないが、現行confirmed経路を新MANUALの安全性保証済みと表示しない。
共通dispatchへの移行はpreview/dry-run→経路別adapter→tenant限定canary→全経路検証とし、移行対象経路では旧confirmedだけのバイパスを停止する。
通常メール、form direct、Campaign、Batch、worker recovery、Codex-assisted、SMTPテスト送信を一覧化し、未移行経路から自動化へ入れない。
Human Approvalの期限や証跡をPolicy publicationへ読み替えない。Policy停止は自動認可を失効させるが、Human承認履歴は消さない。

## 19. Security Risks

| 重要度 / blocker | 根拠と対策 |
| --- | --- |
| Critical: tenant/settings隔離なし | User.is_admin、singleton SMTP/IMAP/API設定、process共有credentials。Org別権限/設定/worker contextが成立するまで複数企業の実送信不可 |
| Critical: 共通dispatch認可未実装 | legacy confirmed/Campaign/Batch等はA2未接続。すべての外部callを認可/Guardへ移行するまで自動化不可 |
| Critical: UNKNOWN/idempotency不足 | 中断はfailed、共通attemptなし。結果不明を再試行しないintent隔離・照合を追加 |
| High: Projectを跨ぐopt-out回避 | 現行SuppressionがProject別。Org禁止の正本とProject追加禁止を和集合で強制 |
| High: Agentによる自己採点/Policy緩和 | score/rankの確定provenance、Human policy publication、禁止scope維持 |
| High: stale policy/authorization/tenant移管 | published版と認可を不変にし、activate/revoke/依存変更時に未使用認可を失効。実行時再検査 |
| High: payload/送信値の差 | SMTP unsubscribe付加、live sender/form mapping、添付内容を最終snapshotと合わせる |
| High: 並行Agentによる上限/重複回避 | Org等のbudget予約、共通intent unique、原子的consume、worker fencing |
| High: Web prompt injection / SSRF / executor逸脱 | WebはUntrusted Data。決定論rule、各hop URL検証、短期task権限、CAPTCHAはHuman |
| Medium: immutable ledgerの誤バックフィル | sidecar tenant contextを追加。過去承認/台帳/既存Migrationを変更しない |

パスワード＋sessionをHumanがAgentに共有した場合の限界は既存設計のまま。Policy管理のstep-upも将来Passkey等へ交換可能にする。
制度としてのpermission判定と、DB superuser/host侵害への耐性は別。通常APIにはoverrideを設けず、管理者による訂正も別workflowと監査に限定する。

## 20. Implementation Plan

推奨順序は **G1 → G2 → G3 → G4 → G5 → G6 → G7**。今回はどの実装も開始しない。
G6のAPI契約設計・read/prepare検証はG1〜G3と先行可能だが、Agentへ配送能力を出す条件はG4/G5のgateを省略しない。

| 工程 | 範囲・再利用 | 完了gate / rollback |
| --- | --- | --- |
| G1 既存Foundation監査・一般化 | 本書を入力に、MANUAL契約・generic DTO・client metadata・tenant/resource対応・全副作用経路一覧を確定。Human guard/禁止scopeを維持。G1後半で小さなtenant導入とOrg権限/設定分離を段階実装 | 2 Org/複数User/複数Agentのcross-tenant拒否、旧A2全回帰。自動送信OFF。新Org利用を止めLegacy Org運用へ |
| G2 AutomationPolicy + Decision Engine | 不変policy版、Human管理step-up、typed rules、deterministic decision/provenance。初期dry-runのみ | 全modeのtruth table、hard BLOCK優先、Policy緩和Agent拒否、競合版409、budget境界。flag OFFでMANUAL |
| G3 PolicyAuthorization | Humanとは別のSYSTEM認可、policy/payload/ruleset/version/expiry、reason/constraints台帳。dispatch未接続 | SYSTEM/PolicyがAPPROVEDを作れない、stale認可失効、同一payloadの認可競合、audit原子性。発行停止・未使用認可revoke |
| G4 RULE_BASED mode | 先に共通Dispatch Foundationを別小工程で完成し、全外部送信adapter・Core Safety・atomic reservation/consume・UNKNOWN・Org予算を接続。条件内だけSYSTEM実行、条件外Humanへ | legacy bypassなし、並行二重送信/worker停止/UNKNOWN・opt-out・CAPTCHA・URL・fingerprintの検証。default OFF、kill switch、未実行reservation停止 |
| G5 AUTONOMOUS mode | scope/地域/source/Company件数/AI費用/cycle/並行数を限定したworkflow orchestration。G4と同じdispatch Guard | 無限収集/自己権限拡大なし、各候補の根拠記録、pause/resume/recovery、Human reviewで停止。workflow OFF、未実行認可revoke |
| G6 LeadHive Agent API | 既存Agent prepare/readを一般化・拡張。collection/jobs/results/analysis proposal/authorization/result。製品別adapterはCore外 | 2種類以上Clientで同一契約、tenant/scopes/budgets・schema安定性、send/policy変更/解除Toolなし。credential/grant失効で停止 |
| G7 Dots PoC | Dotsを一Clientとして限定Org/Projectへ接続。初回は収集/分析/順位/Draft/認可判定まで、送信せずSTOP | 成果/費用/速度/回復/説明可能性をLeadHive/Hybridで比較。他Clientでも同じ境界。PoC grantを失効して停止 |

共通Dispatch FoundationはG4の必須前提であり、A2の完了を理由に省略しない。従来A3の要件をHuman/Policy両認可を扱う共通基盤として一般化し、G4を一つの大規模変更にまとめない。
tenant基盤はG1後半〜G3でadditiveに導入する。G2/G3をLegacy Orgのdry-runで先に作ることはできるが、複数OrgのG4/G5本運用はtenant/credentials/禁止正本のgate完了後に限定する。

**次に実装すべき1工程: G1。** 最初の小単位は既存A2を変更せずgeneric governance契約とtenant/Project binding境界・回帰テストを追加し、MANUAL/default OFFを保つこと。Policy実行や送信の有効化は含めない。

本設計の提出時点で停止する。既存Foundationの削除/巻戻し、Migration、AUTONOMOUS送信、Dots接続、production deployment、実メール/実フォーム送信は今回実施していない。
