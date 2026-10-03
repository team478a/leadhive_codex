# LeadHive × Dots — External Orchestration Readiness Audit

Phase 0 / 監査日: 2026-10-03 / READ-ONLY AUDIT。文書作成のみ。

## 1. Executive Summary

LeadHiveを作り直す必要はない。収集・解析・結果参照・営業記録のREST APIとサービス境界は既に広く存在する。一方、**外部AIには準備のみ許可し、人だけが承認・送信できる境界は現在ない**。owner/editor sessionをDotsへ渡すと、Dots自身が`confirmed=true`を送ってメール予約・フォーム送信・送信再試行を承認できる。

この所見をSTOP CONDITIONのblockerとする。実装への移行は保留し、本書は現状の証拠、選択肢の比較、送信を行わない評価案までに限定する。監査結果提出時の追加指示に基づく設計候補の推奨はOption B（Thin Agent API）とするが、blocker解消を保証するものではない。既存コード、権限、DB、外部設定を変更していない。

総合判定は、**想定する安全な外部オーケストレーション全体についてNEEDS CORE CHANGES**。単なるREST/MCP変換だけでは、人間承認の独立性とフォーム承認snapshotを保証できない。ただし、**人が既存LeadHiveを操作して結果をexportし、外部判断とDRAFTをオフライン比較する非送信PoCはREADY FOR POC**である。これはDotsの自動API操作・M2M認証が準備済みという意味ではない。

| 最優先項目 | 判定 | 要点 |
| --- | --- | --- |
| Collection | PARTIAL READY | async開始とdedupは実装済み。machine scopes、client idempotency、総量budget不足 |
| Job status | PARTIAL READY | Project別一覧pollingは可。OperationJob ID単独GET・webhook・result linkage不足 |
| Result read | PARTIAL READY | Company/フォーム/履歴読取は広い。抑止の最終判定API、完全返信/履歴pagination不足 |
| Outreach preparation | PARTIAL READY | Draft編集・template・form batch準備可。任意外部Draft新規保存とメールcampaign準備専用はない |
| Human approval | BLOCKER | 人とagentを区別しない。フォーム承認内容の不変性が不足 |
| M2M auth | NOT IMPLEMENTED | Cookie sessionのみ。service account/API token/scopesなし |

Dotsの製品/公式仕様/API・MCP対応・local connectorは未提示。接続性・性能・料金を推測で確定しない。

## 2. Audit Baseline

| 項目 | 調査点 |
| --- | --- |
| 主対象 | `team478a/leadhive_codex` |
| audit branch | `codex/integration` |
| LeadHive baseline / audit対象commit | `d5f86a52922750f190d20091ad750169120eb4d8`（local HEADとorigin/integration一致） |
| main比較点 | `b66ed40c533476d2adb7ad74940e6b9f86faa34b`（初期仕様） |
| audit文書commit | 監査・結果提出時は未作成。その後のユーザー指示により、文書のみcommit/pushする。調査対象のbaselineは変更しない |
| 旧版 | 今回再調査不要。V2のAPI境界の根拠に旧版を用いない |
| 開始時の未commitファイル | 前回監査の`docs/DOTS_NATIVE_ARCHITECTURE_AUDIT.md`。保持し、変更しない |

証拠は固定SHAのソース、README、仕様/実装記録（特に10、18〜22、31、38〜41、46〜50、52〜57、65〜68、74〜81）、前回監査、integration status。API146 handlerをASTで再抽出した。テストはコード・既存CI証跡を参照し、今回はAPI呼出し、DB接続・Migration、worker起動、検索、実企業サイト取得、AI API、SMTP/IMAP、Codex taskを実行していない。

状態表記: IMPLEMENTED=コード確認、PARTIAL=一部確認、SPEC ONLY=文書のみ、NOT IMPLEMENTED=当該実装なし。実行実証済み・性能保証とは区別する。[baselineの既存CI](https://github.com/team478a/leadhive_codex/actions/runs/36315906644)は成功済みだが、この監査で新たに再実行したものではない。新所見の競合は静的根拠であり、実際の二重送信を再現していない。

## 3. Current LeadHive Architecture

```text
Browser → Cookie session → FastAPI（schema + project_access）
                               ├ 同期services → Company/CollectionJob
                               └ OperationJob → PostgreSQL queue → worker
                                            → Serper/Places/gBiz/Web/OpenAI
Company/Profile/Project → AI解析 → list/score/rank/理由
Company + Draft/Template → 確認bool → EmailDelivery / form POST / form batch job
                       → 状態・Activity・返信・Deal
特殊フォーム → UIで承認したタスクをコピー → 外部Codex Skill → 人が結果記録
```

`Project.sales_objective`と`target_profile_id`はDBから読む。region/keywords/sourceはjob入力へ明示する。Profileを指定するだけでkeywordを自律展開し、目標300社まで実行するAPIはない。収集→Web→AI→Form解析は個別job。Phase 6 CLIは連続実行の検証経路で、営業戦略agentではない。

役割分離の候補はDots=判断、LeadHive=実行/正本、Codex=例外支援で成立し得るが、**現在その3者を別principalとして認可する実装はない**。業務サービスは再利用可能。ただしサービスを直接呼ぶ場合はAPIの認可・入力検証を迂回できるため、サービス存在を安全な外部契約と同一視しない。

## 4. Existing API Inventory

全APIは`/api`配下。adminは`/api/admin`。API versionはFastAPI metadataの`0.1.0`であり、versioned agent contract/変更保証はない。公開handlerはhealth/login/logout/token unsubscribeの4つ。それ以外はcurrent_user/current_adminを要求する。権限は各handler/helperで別途確認する。

| router module（backend/app/） | handler数 | 領域 |
| --- | ---: | --- |
| routes.py | 18 | auth/Profile/Project/member |
| admin_routes.py | 15 | settings/接続test/SMTP/IMAP/受信 |
| collection_routes.py | 8 | Company基本一覧/CollectionJob/検索/URL/CSV |
| analysis_routes.py + ai_routes.py | 4 | 同期Web/AI |
| company_routes.py | 11 | 詳細/filters/contacts/contact control/CSV/dashboard |
| company_quality_routes.py | 4 | 品質/重複/merge |
| company_reporting_routes.py | 7 | activity/effectiveness/filter/担当分析 |
| company_workflow_routes.py | 10 | queue/返信/追客/営業状態/Activity |
| operation_routes.py | 16 | job/schedule/monitoring |
| form_intelligence_routes.py | 8 | profile/field/log/解析 |
| outreach_draft_routes.py | 19 | template/draft/approval/email/form |
| campaign_routes.py | 4 | email campaign/pause/resume/unsubscribe |
| form_batch_routes.py | 7 | form batch/Codex queue |
| improvement_routes.py | 12 | AiReview/Deal/experiment |
| notification_routes.py | 3 | 通知 |
| 合計 | 146 | 固定SHAの業務router decorator数 |

FastAPI自動生成の`/docs`/`/openapi.json`等は146に含めない。全path/method/response model/認証依存/lineの静的索引を本節末尾に掲載する。request schemaの重要経路は次節以降に詳述する。

**GETだけ許可すれば副作用がない、とは限らない**。`GET /outreach-drafts/{id}/form-preview`は外部サイトを取得し、変更があればFormProfileをSTALEへDB更新する。`GET /notifications`は通知を同期作成する。非送信PoC/read-only connectorはmethodだけでなくhandlerの意味でallowlistを決める必要がある。今回はいずれも呼び出していない。

### 全146 API静的索引

認証欄はdependencyのみ（project/roleチェックはhandler/helper）。HTTP値は成功時宣言で、409/422等の失敗を省略。requestがpath/query/なしの行は本文schemaを持たない。CSVや204等のresponse_model未指定は機能未実装という意味ではない。sourceは全て`backend/app/`配下、lineはbaseline固定。

| Method / endpoint | Request body schema | Response / HTTP | Auth | Source |
| --- | --- | --- | --- | --- |
| GET `/api/admin/application-settings` | path/query/なし | ApplicationSettingsOut / 200 | admin | `admin_routes.py:91` |
| PUT `/api/admin/application-settings` | body: ApplicationSettingsInput | ApplicationSettingsOut / 200 | admin | `admin_routes.py:96` |
| POST `/api/admin/application-settings/test/{service}` | path/query/なし | ServiceConnectionTestOut / 200 | admin | `admin_routes.py:135` |
| GET `/api/admin/smtp-settings` | path/query/なし | SmtpSettingsOut &#124; None / 200 | admin | `admin_routes.py:214` |
| GET `/api/admin/form-sender-settings` | path/query/なし | FormSenderSettingsOut / 200 | admin | `admin_routes.py:220` |
| PUT `/api/admin/form-sender-settings` | body: FormSenderSettingsInput | FormSenderSettingsOut / 200 | admin | `admin_routes.py:225` |
| PUT `/api/admin/smtp-settings` | body: SmtpSettingsInput | SmtpSettingsOut / 200 | admin | `admin_routes.py:244` |
| POST `/api/admin/smtp-settings/test` | body: SmtpTestInput | 未指定 / 204 | admin | `admin_routes.py:293` |
| GET `/api/admin/inbound-mail-settings` | path/query/なし | InboundMailSettingsOut &#124; None / 200 | admin | `admin_routes.py:307` |
| PUT `/api/admin/inbound-mail-settings` | body: InboundMailSettingsInput | InboundMailSettingsOut / 200 | admin | `admin_routes.py:313` |
| POST `/api/admin/inbound-mail-settings/test` | path/query/なし | 未指定 / 204 | admin | `admin_routes.py:360` |
| POST `/api/admin/inbound-mail-settings/sync` | path/query/なし | InboundMailSyncOut / 200 | admin | `admin_routes.py:374` |
| GET `/api/admin/inbound-emails` | path/query/なし | list[InboundEmailOut] / 200 | admin | `admin_routes.py:386` |
| GET `/api/admin/inbound-email-companies` | path/query/なし | list[InboundEmailCompanyCandidateOut] / 200 | admin | `admin_routes.py:401` |
| POST `/api/admin/inbound-emails/{inbound_email_id}/match` | body: InboundEmailMatchInput | InboundEmailOut / 200 | admin | `admin_routes.py:437` |
| POST `/api/companies/{company_id}/ai-analysis` | body: CompanyAiAnalysisInput | CompanyOut / 200 | session | `ai_routes.py:26` |
| POST `/api/projects/{project_id}/ai-analysis` | body: AiAnalysisInput | list[CompanyOut] / 200 | session | `ai_routes.py:38` |
| POST `/api/companies/{company_id}/analyze` | body: CompanyAnalysisInput | CompanyOut / 200 | session | `analysis_routes.py:18` |
| POST `/api/projects/{project_id}/web-analysis` | body: WebAnalysisInput | list[CompanyOut] / 200 | session | `analysis_routes.py:29` |
| GET `/api/projects/{project_id}/email-campaigns` | path/query/なし | list[EmailCampaignOut] / 200 | session | `campaign_routes.py:71` |
| POST `/api/projects/{project_id}/email-campaigns` | body: EmailCampaignCreateInput | EmailCampaignOut / 201 | session | `campaign_routes.py:87` |
| POST `/api/email-campaigns/{campaign_id}/{action}` | path/query/なし | EmailCampaignOut / 200 | session | `campaign_routes.py:168` |
| POST `/api/public/unsubscribe/{token}` | path/query/なし | 未指定 / 200 | public | `campaign_routes.py:191` |
| GET `/api/projects/{project_id}/companies` | path/query/なし | list[CompanyOut] / 200 | session | `collection_routes.py:50` |
| GET `/api/projects/{project_id}/collection-jobs` | path/query/なし | list[CollectionJobOut] / 200 | session | `collection_routes.py:68` |
| GET `/api/collection-jobs/{job_id}` | path/query/なし | CollectionJobOut / 200 | session | `collection_routes.py:86` |
| POST `/api/projects/{project_id}/collection-jobs/search` | body: SearchCollectionInput | list[CollectionJobOut] / 201 | session | `collection_routes.py:95` |
| POST `/api/projects/{project_id}/collection-jobs/urls` | body: UrlCollectionInput | CollectionJobOut / 201 | session | `collection_routes.py:123` |
| POST `/api/projects/{project_id}/collection-jobs/csv` | file: UploadFile, column_mapping: str &#124; None | CollectionJobOut / 201 | session | `collection_routes.py:140` |
| POST `/api/projects/{project_id}/collection-jobs/csv/preview` | file: UploadFile | CsvPreviewOut / 200 | session | `collection_routes.py:165` |
| GET `/api/collection-jobs/{job_id}/errors.csv` | path/query/なし | 未指定 / 200 | session | `collection_routes.py:194` |
| GET `/api/projects/{project_id}/duplicate-candidates` | path/query/なし | list[DuplicateCandidateOut] / 200 | session | `company_quality_routes.py:51` |
| POST `/api/projects/{project_id}/companies/merge` | body: CompanyMergeInput | CompanyOut / 200 | session | `company_quality_routes.py:89` |
| GET `/api/projects/{project_id}/data-quality` | path/query/なし | DataQualityOut / 200 | session | `company_quality_routes.py:174` |
| POST `/api/projects/{project_id}/data-quality/reanalyze` | body: DataQualityReanalyzeInput | OperationJobOut / 202 | session | `company_quality_routes.py:220` |
| GET `/api/sales-activity-analytics` | path/query/なし | SalesActivityAnalyticsOut / 200 | session | `company_reporting_routes.py:47` |
| GET `/api/outreach-effectiveness-analytics` | path/query/なし | OutreachEffectivenessAnalyticsOut / 200 | session | `company_reporting_routes.py:108` |
| GET `/api/projects/{project_id}/saved-company-filters` | path/query/なし | list[SavedCompanyFilterOut] / 200 | session | `company_reporting_routes.py:166` |
| POST `/api/projects/{project_id}/saved-company-filters` | body: SavedCompanyFilterInput | SavedCompanyFilterOut / 201 | session | `company_reporting_routes.py:182` |
| PUT `/api/saved-company-filters/{filter_id}` | body: SavedCompanyFilterInput | SavedCompanyFilterOut / 200 | session | `company_reporting_routes.py:199` |
| DELETE `/api/saved-company-filters/{filter_id}` | path/query/なし | 未指定 / 204 | session | `company_reporting_routes.py:220` |
| GET `/api/projects/{project_id}/assignee-analytics` | path/query/なし | list[AssigneeAnalyticsOut] / 200 | session | `company_reporting_routes.py:235` |
| GET `/api/projects/{project_id}/company-list` | path/query/なし | CompanyPageOut / 200 | session | `company_routes.py:109` |
| GET `/api/companies/{company_id}` | path/query/なし | CompanyOut / 200 | session | `company_routes.py:138` |
| PUT `/api/companies/{company_id}` | body: CompanyEditInput | CompanyOut / 200 | session | `company_routes.py:145` |
| PATCH `/api/companies/{company_id}/contact-control` | body: CompanyContactControlInput | CompanyOut / 200 | session | `company_routes.py:163` |
| PATCH `/api/projects/{project_id}/companies/bulk-assignee` | body: CompanyBulkAssigneeInput | list[CompanyOut] / 200 | session | `company_routes.py:218` |
| GET `/api/companies/{company_id}/contacts` | path/query/なし | list[ContactPersonOut] / 200 | session | `company_routes.py:248` |
| POST `/api/companies/{company_id}/contacts` | body: ContactPersonInput | ContactPersonOut / 201 | session | `company_routes.py:262` |
| PUT `/api/contacts/{contact_id}` | body: ContactPersonInput | ContactPersonOut / 200 | session | `company_routes.py:291` |
| DELETE `/api/contacts/{contact_id}` | path/query/なし | 未指定 / 204 | session | `company_routes.py:318` |
| GET `/api/projects/{project_id}/companies.csv` | path/query/なし | 未指定 / 200 | session | `company_routes.py:341` |
| GET `/api/dashboard` | path/query/なし | DashboardOut / 200 | session | `company_routes.py:406` |
| GET `/api/projects/{project_id}/outreach-queue` | path/query/なし | list[OutreachQueueItemOut] / 200 | session | `company_workflow_routes.py:67` |
| GET `/api/projects/{project_id}/followup-tasks` | path/query/なし | list[FollowupTaskOut] / 200 | session | `company_workflow_routes.py:132` |
| GET `/api/projects/{project_id}/reply-queue` | path/query/なし | list[ReplyQueueItemOut] / 200 | session | `company_workflow_routes.py:176` |
| POST `/api/companies/{company_id}/followup-task` | body: FollowupTaskResolveInput | CompanyOut / 200 | session | `company_workflow_routes.py:218` |
| POST `/api/companies/{company_id}/reply-response` | body: ReplyResponseInput | CompanyOut / 200 | session | `company_workflow_routes.py:251` |
| POST `/api/companies/{company_id}/outreach` | body: OutreachRecordInput | CompanyOut / 200 | session | `company_workflow_routes.py:297` |
| PATCH `/api/companies/{company_id}/sales` | body: CompanySalesInput | CompanyOut / 200 | session | `company_workflow_routes.py:327` |
| PATCH `/api/projects/{project_id}/companies/bulk-sales` | body: CompanyBulkSalesInput | list[CompanyOut] / 200 | session | `company_workflow_routes.py:353` |
| GET `/api/companies/{company_id}/activities` | path/query/なし | list[ActivityOut] / 200 | session | `company_workflow_routes.py:384` |
| POST `/api/companies/{company_id}/activities` | body: ActivityInput | ActivityOut / 201 | session | `company_workflow_routes.py:399` |
| GET `/api/projects/{project_id}/form-delivery-batches` | path/query/なし | list[FormDeliveryBatchOut] / 200 | session | `form_batch_routes.py:88` |
| POST `/api/projects/{project_id}/form-delivery-batches` | body: FormDeliveryBatchCreateInput | FormDeliveryBatchOut / 201 | session | `form_batch_routes.py:106` |
| GET `/api/projects/{project_id}/form-codex-queue` | path/query/なし | list[FormCodexTaskOut] / 200 | session | `form_batch_routes.py:173` |
| POST `/api/form-codex-queue/{item_id}` | body: FormCodexTaskUpdateInput | FormCodexTaskOut / 200 | session | `form_batch_routes.py:217` |
| POST `/api/form-delivery-batch-items/{item_id}/retry` | body: FormDeliveryBatchItemRetryInput | FormDeliveryBatchOut / 200 | session | `form_batch_routes.py:357` |
| POST `/api/form-delivery-batches/{batch_id}/execute` | body: FormDeliveryBatchExecuteInput | FormDeliveryBatchOut / 200 | session | `form_batch_routes.py:394` |
| POST `/api/form-delivery-batches/{batch_id}/cancel` | path/query/なし | FormDeliveryBatchOut / 200 | session | `form_batch_routes.py:449` |
| GET `/api/projects/{project_id}/form-profiles/summary` | path/query/なし | list[FormProfileSummaryOut] / 200 | session | `form_intelligence_routes.py:60` |
| GET `/api/companies/{company_id}/form-profiles` | path/query/なし | list[FormProfileOut] / 200 | session | `form_intelligence_routes.py:90` |
| GET `/api/form-profiles/{profile_id}` | path/query/なし | FormProfileOut / 200 | session | `form_intelligence_routes.py:103` |
| POST `/api/companies/{company_id}/form-intelligence/analyze` | path/query/なし | list[FormProfileOut] / 200 | session | `form_intelligence_routes.py:113` |
| POST `/api/projects/{project_id}/form-intelligence/jobs` | body: FormIntelligenceJobInput | OperationJobOut / 202 | session | `form_intelligence_routes.py:125` |
| PATCH `/api/form-profile-fields/{field_id}` | body: FormFieldCorrectionInput | FormProfileFieldOut / 200 | session | `form_intelligence_routes.py:162` |
| POST `/api/form-profiles/{profile_id}/select-primary` | path/query/なし | FormProfileOut / 200 | session | `form_intelligence_routes.py:232` |
| GET `/api/form-profiles/{profile_id}/logs` | path/query/なし | list[FormAnalysisLogOut] / 200 | session | `form_intelligence_routes.py:246` |
| GET `/api/companies/{company_id}/ai-review` | path/query/なし | AiReviewOut &#124; None / 200 | session | `improvement_routes.py:49` |
| PUT `/api/companies/{company_id}/ai-review` | body: AiReviewInput | AiReviewOut / 200 | session | `improvement_routes.py:57` |
| GET `/api/projects/{project_id}/ai-review-analytics` | path/query/なし | list[AiReviewAnalyticsOut] / 200 | session | `improvement_routes.py:78` |
| GET `/api/projects/{project_id}/deal-pipeline` | path/query/なし | DealPipelineOut / 200 | session | `improvement_routes.py:103` |
| GET `/api/companies/{company_id}/deals` | path/query/なし | list[DealOut] / 200 | session | `improvement_routes.py:146` |
| POST `/api/companies/{company_id}/deals` | body: DealInput | DealOut / 201 | session | `improvement_routes.py:154` |
| PUT `/api/deals/{deal_id}` | body: DealInput | DealOut / 200 | session | `improvement_routes.py:169` |
| DELETE `/api/deals/{deal_id}` | path/query/なし | 未指定 / 204 | session | `improvement_routes.py:187` |
| GET `/api/projects/{project_id}/outreach-experiments` | path/query/なし | list[OutreachExperimentOut] / 200 | session | `improvement_routes.py:199` |
| POST `/api/projects/{project_id}/outreach-experiments` | body: OutreachExperimentInput | OutreachExperimentOut / 201 | session | `improvement_routes.py:215` |
| POST `/api/outreach-experiments/{experiment_id}/apply/{draft_id}` | path/query/なし | OutreachExperimentAssignmentOut / 200 | session | `improvement_routes.py:242` |
| GET `/api/outreach-experiments/{experiment_id}/results` | path/query/なし | list[OutreachExperimentResultOut] / 200 | session | `improvement_routes.py:277` |
| GET `/api/notifications` | path/query/なし | list[NotificationOut] / 200 | session | `notification_routes.py:114` |
| POST `/api/notifications/{notification_id}/read` | path/query/なし | NotificationOut / 200 | session | `notification_routes.py:131` |
| POST `/api/notifications/read-all` | path/query/なし | 未指定 / 204 | session | `notification_routes.py:151` |
| GET `/api/projects/{project_id}/analysis-refresh-schedule` | path/query/なし | AnalysisRefreshScheduleOut &#124; None / 200 | session | `operation_routes.py:53` |
| PUT `/api/projects/{project_id}/analysis-refresh-schedule` | body: AnalysisRefreshScheduleInput | AnalysisRefreshScheduleOut / 200 | session | `operation_routes.py:66` |
| DELETE `/api/projects/{project_id}/analysis-refresh-schedule` | path/query/なし | 未指定 / 204 | session | `operation_routes.py:90` |
| POST `/api/projects/{project_id}/analysis-refresh-schedule/run` | path/query/なし | OperationJobOut / 202 | session | `operation_routes.py:108` |
| GET `/api/projects/{project_id}/search-schedules` | path/query/なし | list[SearchScheduleOut] / 200 | session | `operation_routes.py:145` |
| GET `/api/projects/{project_id}/search-analytics` | path/query/なし | list[SearchAnalyticsOut] / 200 | session | `operation_routes.py:157` |
| GET `/api/projects/{project_id}/collection-performance` | path/query/なし | list[CollectionPerformanceOut] / 200 | session | `operation_routes.py:197` |
| POST `/api/projects/{project_id}/search-schedules` | body: SearchScheduleInput | SearchScheduleOut / 201 | session | `operation_routes.py:253` |
| PUT `/api/search-schedules/{schedule_id}` | body: SearchScheduleInput | SearchScheduleOut / 200 | session | `operation_routes.py:272` |
| DELETE `/api/search-schedules/{schedule_id}` | path/query/なし | 未指定 / 204 | session | `operation_routes.py:289` |
| POST `/api/search-schedules/{schedule_id}/run` | path/query/なし | OperationJobOut / 202 | session | `operation_routes.py:297` |
| POST `/api/projects/{project_id}/operations` | body: OperationJobInput | OperationJobOut / 202 | session | `operation_routes.py:332` |
| GET `/api/projects/{project_id}/operations` | path/query/なし | list[OperationJobOut] / 200 | session | `operation_routes.py:358` |
| POST `/api/operations/{job_id}/cancel` | path/query/なし | OperationJobOut / 200 | session | `operation_routes.py:374` |
| POST `/api/operations/{job_id}/retry` | path/query/なし | OperationJobOut / 202 | session | `operation_routes.py:389` |
| POST `/api/operations/{job_id}/acknowledge` | path/query/なし | OperationJobOut / 200 | session | `operation_routes.py:418` |
| GET `/api/projects/{project_id}/outreach-templates` | path/query/なし | list[OutreachTemplateOut] / 200 | session | `outreach_draft_routes.py:106` |
| POST `/api/projects/{project_id}/outreach-templates` | body: OutreachTemplateInput | OutreachTemplateOut / 201 | session | `outreach_draft_routes.py:124` |
| DELETE `/api/outreach-templates/{template_id}` | path/query/なし | 未指定 / 204 | session | `outreach_draft_routes.py:141` |
| GET `/api/projects/{project_id}/email-deliveries` | path/query/なし | EmailDeliveryListOut / 200 | session | `outreach_draft_routes.py:155` |
| GET `/api/companies/{company_id}/outreach-drafts` | path/query/なし | list[OutreachDraftOut] / 200 | session | `outreach_draft_routes.py:260` |
| GET `/api/outreach-drafts/{draft_id}/approvals` | path/query/なし | list[OutreachDraftApprovalOut] / 200 | session | `outreach_draft_routes.py:275` |
| POST `/api/outreach-drafts/{draft_id}/apply-template` | body: OutreachTemplateApplyInput | OutreachDraftOut / 200 | session | `outreach_draft_routes.py:290` |
| GET `/api/outreach-drafts/{draft_id}/email-delivery` | path/query/なし | EmailDeliveryOut &#124; None / 200 | session | `outreach_draft_routes.py:311` |
| GET `/api/outreach-drafts/{draft_id}/form-preview` | path/query/なし | FormPreviewOut / 200 | session | `outreach_draft_routes.py:321` |
| GET `/api/outreach-drafts/{draft_id}/form-assist` | path/query/なし | FormAssistOut / 200 | session | `outreach_draft_routes.py:349` |
| GET `/api/outreach-drafts/{draft_id}/form-delivery` | path/query/なし | FormDeliveryOut &#124; None / 200 | session | `outreach_draft_routes.py:383` |
| POST `/api/outreach-drafts/{draft_id}/form-assist-delivery` | body: FormAssistDeliveryInput | FormDeliveryOut / 201 | session | `outreach_draft_routes.py:397` |
| POST `/api/outreach-drafts/{draft_id}/form-delivery` | body: FormDeliveryCreateInput | FormDeliveryOut / 201 | session | `outreach_draft_routes.py:493` |
| POST `/api/outreach-drafts/{draft_id}/email-delivery` | body: EmailDeliveryCreateInput | EmailDeliveryOut / 202 | session | `outreach_draft_routes.py:574` |
| POST `/api/email-deliveries/{delivery_id}/cancel` | path/query/なし | EmailDeliveryOut / 200 | session | `outreach_draft_routes.py:615` |
| POST `/api/email-deliveries/{delivery_id}/retry` | body: EmailDeliveryRetryInput | EmailDeliveryOut / 200 | session | `outreach_draft_routes.py:631` |
| POST `/api/companies/{company_id}/outreach-drafts/generate` | body: OutreachDraftGenerateInput | OutreachDraftOut / 201 | session | `outreach_draft_routes.py:665` |
| PUT `/api/outreach-drafts/{draft_id}` | body: OutreachDraftUpdateInput | OutreachDraftOut / 200 | session | `outreach_draft_routes.py:734` |
| DELETE `/api/outreach-drafts/{draft_id}` | path/query/なし | 未指定 / 204 | session | `outreach_draft_routes.py:749` |
| GET `/api/health` | path/query/なし | 未指定 / 200 | public | `routes.py:32` |
| POST `/api/auth/login` | body: Login | UserOut / 200 | public | `routes.py:42` |
| POST `/api/auth/logout` | path/query/なし | 未指定 / 204 | public | `routes.py:74` |
| GET `/api/auth/me` | path/query/なし | UserOut / 200 | session | `routes.py:83` |
| GET `/api/target-profiles` | path/query/なし | list[ProfileOut] / 200 | session | `routes.py:118` |
| POST `/api/target-profiles` | body: ProfileInput | ProfileOut / 201 | session | `routes.py:139` |
| GET `/api/target-profiles/{profile_id}` | path/query/なし | ProfileOut / 200 | session | `routes.py:152` |
| PUT `/api/target-profiles/{profile_id}` | body: ProfileInput | ProfileOut / 200 | session | `routes.py:159` |
| POST `/api/target-profiles/{profile_id}/clone` | path/query/なし | ProfileOut / 201 | session | `routes.py:174` |
| DELETE `/api/target-profiles/{profile_id}` | path/query/なし | 未指定 / 204 | session | `routes.py:188` |
| GET `/api/projects` | path/query/なし | list[ProjectOut] / 200 | session | `routes.py:207` |
| POST `/api/projects` | body: ProjectInput | ProjectOut / 201 | session | `routes.py:226` |
| GET `/api/projects/{project_id}` | path/query/なし | ProjectOut / 200 | session | `routes.py:240` |
| PUT `/api/projects/{project_id}` | body: ProjectInput | ProjectOut / 200 | session | `routes.py:247` |
| DELETE `/api/projects/{project_id}` | path/query/なし | 未指定 / 204 | session | `routes.py:264` |
| GET `/api/projects/{project_id}/members` | path/query/なし | list[ProjectMemberOut] / 200 | session | `routes.py:274` |
| POST `/api/projects/{project_id}/members` | body: ProjectMemberInput | ProjectMemberOut / 201 | session | `routes.py:310` |
| DELETE `/api/projects/{project_id}/members/{member_id}` | path/query/なし | 未指定 / 204 | session | `routes.py:345` |

## 5. Collection API Readiness

### 現行契約

| 用途 | method / endpoint | request | response・実行方式 |
| --- | --- | --- | --- |
| Profile準備 | POST `/api/target-profiles` | ProfileInput: name、検索/positive/negative/exclusion語、scoring_rules、ai_instruction、default_regions等 | 201 ProfileOut |
| Project準備 | POST `/api/projects` | ProjectInput: project_name,target_profile_id,sales_objective,region,status | 201 ProjectOut |
| async検索 | POST `/api/projects/{project_id}/operations` | OperationJobInput: `operation_type=collect_search`,source,keywords,region,max_results | 202 OperationJobOut、`id`がjob ID |
| 同期検索 | POST `/api/projects/{project_id}/collection-jobs/search` | SearchCollectionInput: source,keywords,region,max_results | 201 list[CollectionJobOut]。HTTP内で検索完了、keyword別ID |
| URL | POST `/api/projects/{project_id}/collection-jobs/urls` | UrlCollectionInput: urls（1〜100） | 201 CollectionJobOut、同期保存 |
| CSV/preview | POST `/api/projects/{project_id}/collection-jobs/csv`、`/csv/preview` | multipart file、csvのcolumn_mappingはJSON文字列、5MB/1000行 | CollectionJobOut / CsvPreviewOut |
| Web/AI解析 | POST `/api/projects/{project_id}/operations` | operation_type=web_analysis/ai_analysis、company_ids<=100、force | 202 OperationJobOut。別job |

sourceはserper/google_places/gbizinfo。検索keywordsは1〜20、max_resultsは1〜100（Places<=60）。async検索はsource/keywords/region必須。operation requestにはTargetProfile/SalesObjectiveそのものを含めず、Project関連を使う。検索keyword/regionがProject/Profileと一致することを強制するvalidatorはない。

認証はCookie＋owner/editor write。Profileはsystem又は本人所有、Projectはowner/member境界。`services/collection.py`→`collection_jobs.py`→workerの境界を再利用できる。

### reliability

| 項目 | 現状 |
| --- | --- |
| async | DB OperationJob、別worker process、PostgreSQL SKIP LOCKED claim |
| retry | failed/cancelled OperationJobから新IDを作る。lease失効は上限内再queue。通常Provider失敗の自動backoff/quota再試行は未確認 |
| cancel | queuedはcancelled、runningはcancel_requested。外部callの途中を即停止せずcheckpoint |
| rate limit | request件数制限、検索最大4並列、timeoutあり。machine別budget/Provider quota governor/API rate limitなし |
| idempotency | Idempotency-Key/request ID/同一request結果再取得はNOT IMPLEMENTED |
| job重複 | project+operation_typeのqueued/running partial unique、race-safe add_operation_job。完了後の同一request再実行は許す |
| 企業重複 | project内domain/URL/名称住所unique、savepoint/IntegrityError、再解析重複。全Project共通同一性なし |
| 300社達成 | 検索raw件数と保存数は別。query拡張/目標適性社数の自律達成なし |

同期検索はOperationJobのactive uniqueやcancelを通らない。単純に全検索経路をAgentへ公開するとbudget・同時制御が不統一になる。collection jobのsuppression除外もduplicate_countへ含まれる。

判定: **機能境界はIMPLEMENTED、外部Agent向け安全契約はPARTIAL READY**。

## 6. Job Status Readiness

| API | 読める内容 | 制限 |
| --- | --- | --- |
| GET `/api/projects/{id}/operations?limit=100` | OperationJobOut: id,type,status,total/processed/success/failed,cancel_requested,attempt_count,error,created/started/finished,acknowledged | 最新最大100、offset/status/id filterなし |
| GET `/api/collection-jobs/{id}` | CollectionJobOut: found/saved/duplicate/excluded/error、processing_ms、keyword/region/source | 子収集job単独は可能 |
| GET `/api/projects/{id}/collection-jobs?offset=0&limit=100` | 子job履歴、count/失敗 | operation_job_idのfilterとresponse露出なし |
| POST `/api/operations/{id}/cancel` | updated OperationJobOut | owner/editor、runningは停止要求 |
| POST `/api/operations/{id}/retry` | 202 new OperationJobOut | failed/cancelledのみ、全payload再実行 |

OperationJob状態はqueued/running/completed/failed/cancelled。CollectionJobはrunning/completed/failedだけで、cancelledはない。Operation total/successは収集時keyword単位、解析時company単位であり、保存企業数ではない。

**GET `/api/operations/{id}`は存在しない**。一覧でidを探すpollingが必要で、履歴が100件を超えると古いjobをこの一覧から追えない。webhook/event/SSE/subscriptionはNOT IMPLEMENTED。通知はUI通知であり、外部callbackではない。

DBのCollectionJob.operation_job_idは存在するがCollectionJobOutにない。CompanyもCollectionJob IDを持たず、source/source_keywordのみ。したがって「このjobの保存企業だけ」を安定取得する標準APIはない。専用PoC Project＋ID差分で近似可能だが、同時収集・scheduleがあるProjectでは完全なjob-result帰属としない。

判定: **pollingの基本は可能、ID・結果追跡・安定履歴はPARTIAL READY**。

## 7. Result Read Readiness

| 要求情報 | 一覧 | 個別 | 内容／注意 |
| --- | --- | --- | --- |
| Company/website/domain/address/region/phone/email | GET `/projects/{id}/companies`又は`/company-list` | GET `/companies/{id}` | CompanyOutにprefecture/city、contact_url、SNS、body、出典、AI列も含む |
| contact | CompanyOut基本連絡先、contactsは会社別一覧 | GET `/companies/{id}/contacts`（一覧）、単独contact GETなし | ContactPersonOut、品質/source_url/verified date |
| source/collection keyword | CompanyOut.source/source_keyword、CollectionJob一覧 | CollectionJob単独 | 複数出典の全履歴・raw SERP snippet・place_idなし |
| AI summary/score/rank/reason/approach | CompanyOutに含む | 同上 | 最新ai_provider/model/date/status。入力版/全履歴なし |
| Form Intelligence | GET `/projects/{id}/form-profiles/summary` | GET `/companies/{id}/form-profiles`、`/form-profiles/{id}` | summary=会社別primaryのみ、URL/fieldsはdetail。status/prohibition/CAPTCHA/fingerprint等 |
| form logs | profile別 | GET `/form-profiles/{id}/logs` | FormAnalysisLog、manual correction/decision evidence |
| contact suppression | CompanyOut.do_not_contact、quality、reason | 同上 | SuppressionEntry一覧・全宛先の最終permission APIなし。flagだけで完全判定できない |
| outreach history | 会社別draft最大50、activities、queue | draft別approvals/email-delivery/form-delivery | Draft単独GETなし。IDは会社別一覧やbatchから取得 |
| send history | GET `/projects/{id}/email-deliveries`、email-campaigns、form-delivery-batches | GET `/outreach-drafts/{id}/email-delivery`／`form-delivery` | email一覧limit<=200、offsetなし。form全社共通history一覧なし |
| reply | GET `/projects/{id}/reply-queue` | admin inbound-emails一覧。個別reply GETなし | queueは未処理replyかつCompany=repliedで会社別代表。全返信のpageable project APIではない |
| pipeline state | CompanyOut.status、GET `/projects/{id}/deal-pipeline` | GET `/companies/{id}/deals` | Deal/営業状態。Company.statusと送信許可は別 |
| campaign結果 | email-campaigns、effectiveness、experiment/results | campaign単独GETなし | counts/返信/meeting/won等。inbox到達/開封率ではない |

主Company一覧はoffset>=0、limit1〜100。`company-list`はitems,total,offset,limit。filters=rank,min_score,region,status,source,keyword,assignee,followup。sort=score_desc/newest/company_name。regionはprefecture/addressの部分一致であり、複数地域のOR条件や厳密な所在地判定ではない。score_descはscore/created_atで順序を付け、ID tie-breakはないため、更新中のoffset paginationは安定snapshotではない。

基本Company一覧はcreated_at desc/id順、responseはlistでtotalなし。Form summaryはpaginationなし、history系は多くが固定limitのみ。大量AIへ渡す際にCompanyOut丸ごとを送ると連絡先と最大Web本文も含むため、必要なfieldsだけ抽出する境界が必要。

認証: project readはowner/editor/viewer。admin inbound一覧はglobal admin専用で、project-only agentへadmin権限を渡す理由にはならない。

判定: **主結果は読めるが、抑止・全履歴・job帰属・agent最小権限はPARTIAL READY**。

## 8. Outreach Preparation Readiness

| 準備対象 | 実装 | 境界 |
| --- | --- | --- |
| 31社選定 | bulk-sales(status=target,<=100)、filters/queue、form batch IDs | 独立の提案snapshot/外部ranking runはない。target化は正式営業状態の更新 |
| AI message generation | POST `/companies/{id}/outreach-drafts/generate`: channel,contact_person_id,instruction | current internal AIを呼ぶ。ai_status=completed、連絡先/抑止checkが条件 |
| 外部文面保存 | PUT `/outreach-drafts/{id}`でsubject/body更新、template作成 | 任意文面の新規Draft POSTなし。既存Draft生成には内部AIが必要 |
| template | GET/POST `/projects/{id}/outreach-templates`、POST `/outreach-drafts/{id}/apply-template` | 同Project/channel検証。生成済みDraftへ適用 |
| email/form Draft | 生成/一覧/更新/削除あり | 更新は承認後も許可。email送信snapshotは別、form batchはlatest参照 |
| sender情報 | admin form-sender-settings/SMTP settings | agentにはglobal admin read不要。最小sender参照APIなし |
| suppression可否 | 生成やbatchや送信でservice検査 | `evaluate_contact_permission`はserviceのみ。独立preflight APIなし |
| duplicate-send確認 | draft delivery read、campaign/form batch内部除外 | 全channel共通履歴・idempotency予約ではない |
| Form check | saved profile APIs | form-preview GETはlive fetch/STALE更新を伴う。今回は呼ばない |
| approval履歴 | GET `/outreach-drafts/{id}/approvals` | pending approval request/state APIではない |
| form campaign preparation | POST `/projects/{id}/form-delivery-batches`: template_id,company_ids | 201 ready batch。execute別API、実送信しないがDB Draft/items作成 |
| email campaign preparation | NOT IMPLEMENTED（専用） | create EmailCampaignはconfirmed要求→queued EmailDeliveriesまで作る。prepare-onlyとして使えない |

emailではDraft準備と送信予約は分離するが、campaignでは準備と承認/予約が一体。form batchは準備とexecuteが分離するが承認版の不変性が不足。外部分析のscore/rank/reasonをCompany AI列へ取り込む正式APIもない（CompanyEditInputは基本情報のみ、AiReviewはverdict/note）。既存Activity/notesへ評価を文字列記録する方法は完全な外部判断SoRを代替しない。

判定: **準備機能は部分再利用可能。Dotsの評価/文面/提案を完全に保存する契約はPARTIAL**。

## 9. Human Approval / Send Boundary

### STOP CONDITIONで検出したblocker

| ID | 重要度 | 確認事実・コード根拠 | 影響 |
| --- | --- | --- | --- |
| B1 | 最重要 | `security.py::current_user`＋`project_access.py`＋send schemas/routes: owner/editorとconfirmed boolだけ | Agentにwrite sessionを渡すと自身で承認・送信可能。独立human gateなし |
| B2 | 高 | `form_batch_routes.py::execute_form_batch`はjob payloadにbatch_id/limit/userだけ。`bulk_form_delivery.py::process_form_batch_item`は実行時Draftを読む。Approval rowはPOST成功後に作る | 承認後PUT/apply-templateで本文変更可能。承認本文/宛先/sender/versionが固定されない |
| B3 | 高 | `outreach_draft_routes.py::create_form_delivery`は既存Delivery検索→外部submit→Delivery insert/commit。unique(draft_id)は外部POSTの後 | 同時requestで両方POSTし得る。DB conflictは先に起きた二重外部送信を戻せない。静的競合リスク、未再現 |
| B4 | 高 | direct formのrequestは任意`field_values`、実送信は許可field値の各2,000文字。ApprovalはDraft.subject/body、mapping_snapshotはfield mapping | 承認台帳の本文と実送信値を一致確認するhash/完全payload snapshotなし |

email campaignにもCompany既送信検索→別Draft insertのcheck-then-insertがある。uniqueはdraft単位でcompany/キャンペーン依頼単位ではなく、同時campaign作成の重複送信を保証していない。これも静的リスクとして扱い、試験送信は行わない。

### 承認の現状

| 要件 | 現在 | 判定 |
| --- | --- | --- |
| approval model | OutreachDraftApproval: draft_id,approved_by_user_id,type,subject,body,approved_at,delivered_at等 | IMPLEMENTED |
| pending/approved/rejected/expired state | Approval rowは承認イベント。独立request/状態/期限なし | NOT IMPLEMENTED |
| approved_by/at | User IDと時刻。ただし呼出principalが人かagentかを識別しない | PARTIAL |
| payload hash/version | form fingerprintは構造hash。本文/宛先/sender/全入力/条件のapproval hashではない | NOT IMPLEMENTED |
| email承認後本文/宛先固定 | EmailDeliveryへrecipient/subject/bodyをcopy。Draft変更でもこのdeliveryは変わらない | IMPLEMENTED |
| email campaign snapshot | 作成時templateからDraft/Delivery/Approvalをcopy | IMPLEMENTED（作成が既に予約） |
| form承認後不変性 | batchはlatest Draft/sender/profileを利用。directはrequest values、事後Approval | PARTIAL / BLOCKER |
| suppression再確認 | 共通permission service、email worker/form実行直前 | IMPLEMENTED。外部I/O前後のraceを完全排除するものではない |
| duplicate-send | 同Draft unique、campaign会社既送信除外、batch会社既送信除外 | PARTIAL。全channel/global/idempotent外部POST保証なし |
| rate | email advisory claim lock、rolling24h、minimum interval、runningも計上 | IMPLEMENTED（SMTPテスト除外）。form共通送信rate/budgetなし |
| audit | Approval/Delivery/Activity/FormAnalysisLog | PARTIAL。全actor/各attemptの不変台帳なし |

email retryはfailed deliveryを同内容で再queueしconfirmed_at更新するが、Approval履歴へretryの独立承認イベントは追加しない。Email stale runningはfailedにし自動再送しない。成功直後にDB保存できない場合は実送信済みか不明になる。フォーム完了未確認も受付済みの可能性があるため、agentの自動retryを許可できる状態とは言えない。

Draft DELETEはDelivery/Approval cascadeの起点になる。editorにprepare更新権限を与えただけで、既送信の記録保持に影響し得る。認証scopeの分離だけでなく、既存mutationの監査保持も要確認。

**人間承認のみを保証する接続は未完成**。UI確認ダイアログやconfirmed bool、Skillのsubmission_authorized boolをmachine-proofの承認トークンと扱わない。本節のblocker解消を確認するまでlive送信PoC・方式選定・実装手順への移行を保留する。

## 10. Authentication / Authorization

| 項目 | 現行 |
| --- | --- |
| Browser auth | IMPLEMENTED: email/password、Argon2系password hash、opaque Cookie `leadhive_session` |
| session | IMPLEMENTED: AuthSession token SHA-256保存、expires_at、HttpOnly/SameSite=Lax、Secure設定、再login/logout失効 |
| JWT | NOT IMPLEMENTED |
| inbound API key / API token | NOT IMPLEMENTED。Serper/OpenAI等のoutbound keyとは別 |
| service account / machine principal | NOT IMPLEMENTED。専用Userを作っても通常session userでありM2Mではない |
| scopes / prepare-only role | NOT IMPLEMENTED。collection-only/draft-only/approve-onlyのscopeなし |
| roles | Project owner/editor/viewer、global is_admin |
| Project boundary | IMPLEMENTED: project_access/company_access/helper。viewerはreadのみ、writeはowner/editor |
| tenant boundary | PARTIAL: ProjectとUser所有。Organization/Tenant modelの独立境界なし。settingsはglobal singleton |
| human vs agent | NOT IMPLEMENTED。同一User/sessionの操作を識別しない |
| browser protection | Origin/Sec-Fetch-Site確認、CORS allowed origins/credentials/methods |
| machine endpoint保護 | NOT IMPLEMENTED: scope付きtoken・machine rate/budget・独立auditなし |

非browser clientはOriginなしでもSec-Fetch-Site=cross-siteでなければmiddlewareで一律拒否されない。Cookieを持てば呼出し得るが、これはM2M許可の設計ではない。CORSはserver-to-serverの送信認可を代替しない。login rate limitもapp内にない（公開運用はproxy前提）。

viewer credentialは結果readには使えるがcollection/Draft作成には使えない。editorに昇格すると承認・抑止解除・記録更新にも広がる。現行roleだけで「実行準備は可、送信承認は不可」を表現できない。

## 11. System of Record

Dots Memoryは推論文脈と補助cache。確定記録はLeadHiveへ残す。単なるDB保存と、不変履歴・保持保証は区別する。

| 正本候補 | 既存Model | 不足・注意 |
| --- | --- | --- |
| Company/domain/contact/source | Company/ContactPerson/CollectionJob | project scope、法人単位aliasと複数source provenanceなし |
| collection result/job state | CollectionJob/OperationJob | APIでjob→company一覧への確実な帰属なし |
| suppression/opt-out | Company flag/SuppressionEntry | project scope、final permissionはservice、解除もeditor可 |
| Form Intelligence | FormProfile/Field/Log | version/fingerprintあり。live送信payloadの承認hashとは違う |
| external analysis/ranking | Company AI列/AiReview | 外部評価ingest/run履歴/schema未実装 |
| outreach message | Draft/Template/Delivery copy | 任意外部Draft createなし。form latest参照 |
| approval | OutreachDraftApproval | 独立human principal、pending/expired/revoke/payload bindingなし |
| send attempt/result | EmailDelivery/FormDelivery/Activity | attempt_count/最新状態。独立append-only attempt/unknown resultなし |
| reply/error/activity/pipeline | InboundEmail/Job errors/Activity/Deal | 返信原本/thread、全actor、完全履歴page不足 |

Company/Project/Draftのcascadeで記録が削除され得る。抑止はCompany削除後もProjectに残るがProject削除では失われる。確定記録をMemoryだけに残したり、agentが会話上「解除」と言っただけでopt-out解除する運用は成立しない。

## 12. Dots Responsibility Candidates

以下は移管・再利用の評価候補。Dotsの実能力確認ではない。

| 判断対象 | 分類 | 評価 |
| --- | --- | --- |
| search strategy generation | MOVE TO DOTS CANDIDATE | 現行は人。目的からquery/地域分割を提案する価値 |
| keyword expansion | MOVE TO DOTS CANDIDATE | 収集成果を見て拡張候補。予算/停止/結果保存はCore |
| target interpretation | HYBRID | Dotsが解釈、人がProfile/SalesObjective条件を確定 |
| company semantic analysis | NEEDS POC | 同一本文で現行構造化AIと精度/費用比較 |
| sales-fit reasoning | MOVE TO DOTS CANDIDATE | 根拠と不明点を説明。結果を正式保存するAPIは不足 |
| prioritization | HYBRID | Dots提案、Coreのrank・期日・状態・禁止条件を参照 |
| recommended approach | MOVE TO DOTS CANDIDATE | 会社別の企業事実とOEM目的の接続を比較 |
| message generation | NEEDS POC | 事実一致・署名・個人情報・Draft保存・承認版が条件 |
| next-action reasoning | HYBRID | Dots提案、抑止/返信/人の承認/日程はCore |
| campaign analysis | HYBRID | LeadHiveの確定metricsからDotsが解釈、集計はCore |
| final send permission/recording | KEEP IN LEADHIVE | AIの意味判断では上書きさせない制約 |

## 13. LeadHive Responsibility

既存の収集Provider、canonicalize/dedup、SafeFetcher、構造抽出、typed schemas、権限境界、Company/contacts、FormProfile、permission service、queue/recovery、SMTP/IMAP、記録/追客/Deal、監視/backupを維持する候補。UIは人のreview/承認/失敗確認に引き続き必要。

サービスを直接外部公開せず認可・schema境界を保つ必要があるが、今回は公開方法を選択しない。Agent判断とCoreのhard rules（禁止/宛先/承認/上限）を分離する価値がある。現行営業状態target化、opt-out解除、承認・送信・削除を「準備」の一語にまとめない。

## 14. Codex Assisted Path

| 分類 | 現在の境界 | 外部Dots側の注意 |
| --- | --- | --- |
| NORMAL PATH | email登録済み宛先＋承認→SMTP。formはALLOWED/READY/CAPTCHA_NONE/対応構造/required値・live fingerprint一致 | current roleでは自身でconfirmed可能。安全なtool権限分離はまだない |
| CODEX ASSISTED | static対応外、JS/iframe、必須mapping不足、確認が必要なform。GET form-assist/form-codex-queueで提案payload | Dotsはexception候補を説明できるが送信taskへ昇格してよい根拠なし |
| HUMAN REQUIRED | CAPTCHA、可否不明、同意/本人操作、結果不明 | CAPTCHAは人が正規画面で完了。曖昧な結果を自動retryしない |
| BLOCKED | suppression/Company do_not_contact、form営業禁止、危険URL、Skillが禁止する支払・添付・login等 | 迂回channel/別Project/強制trueで回避しない |

`.agents/skills/leadhive-form-submit/SKILL.md`を実行せず監査資料として読んだ。1件の`LEADHIVE_FORM_TASK_V1`、submission_authorized=true、form URL/本文/task referenceが必要。サイトとpayloadをuntrustedとし、禁止検出で停止、最終submit最大1回、曖昧時pending、CAPTCHAは人へ依頼する。

Backend payloadのsubmission_authorized初期値はfalse。`frontend/src/formCodexTask.ts::approvedCodexFormTask`がUI確認後にtrueへ変換する。署名された承認証明ではなく、人のコピー・貼付とSkillの手順に依存する。承認task生成を確定する独立server gate/callback/無人起動はない。結果は人がLeadHiveへPOST記録する。支援taskが作れそうという理由でDotsの権限を越えさせない。

## 15. Batch Processing Analysis

実測latency/価格は取得・実行していない。以下はコード上限と処理構造による比較。Dotsがn社を逐次扱うと、外部判断n回＋tool往復を伴う可能性があるが、Dots内部batch/費用契約は不明。

| 観点 | Dots 1社ずつ | LeadHive batch |
| --- | --- | --- |
| latency | 会話/lookup/推論のround trip、直列ならnに比例。実際の並列機能不明 | Web/AIは1job<=100で逐次。検索のみ最大4並列。batch化だけではAI callsは減らない |
| API/AI cost | tool/会話context再送や再試行、Dots料金未確認 | 検索query数、HTML fetch、AI入力token/callsに依存。通常AI全usage台帳不足 |
| reliability/retry | Memoryだけの進捗は再開/結果照合不可。外部副作用retry危険 | DB進捗/lease/cancel/retryあり、送信unknownを解決する保証ではない |
| concurrency | clientが複数送信するとAPI競合を増やす | active project/type unique、worker claim。別type/同期APIは同時動作し得る |
| duplicate | agentが履歴を失うと再操作。dedupはCore依存 | project企業uniqueあり。job idempotency/送信company uniqueは別 |
| resumability | stable IDsと版・request記録必要、現行Dots接続なし | saved/skippedを再選択可能。retryは旧payload全体、新job ID |
| auditability | 会話ログだけでは不足 | Job/Delivery/Activityあり、全attempt/actor/分析版不足 |

| 規模 | LeadHive解析job目安 | Dots逐次の比較と制限 |
| --- | --- | --- |
| Test 1: 50社 | Web1＋AI1job、最大250HTML pages＋robots、通常50AI calls | 50社別判断＋tool往復の対照。専用Project・停止した収集条件で小規模評価可能 |
| Test 2: 300社 | Web3＋AI3job、最大1,500HTML pages、通常300AI calls | 300件の保存/再開/費用/timeoutが必要。最新100job一覧だけでは長期追跡に限界 |
| Test 3: 3,000社 | Web30＋AI30job、最大15,000HTML pages、通常3,000AI calls | 3,000逐次tool会話は未実証。paging/snapshot/quota/進捗帰属を含む負荷試験が必要 |

job目安は対象企業が既に取得済み・全件解析可能の場合。skip/失敗/内部retryでcallsは変わる。Serper query<=100、Places<=60、keywords<=20なので1収集Operationは名目2,000/1,200raw候補まで。3,000unique適性企業を取得する保証なし。Serperのpage/cursorなし、同query反復は重複し得る。

N社の必要query目安は`ceil(N/(R*u))`、u=公式/unique/目的に合う保存比率で未測定。安い/速いを断定できない。停止確認はcheckpointで、長い並列検索中のlease・公平性も追加検証対象。Phase 6の100＋100と人のreviewは未完了。

## 16. Security Risks

| リスク | 既存対策 | 外部Agent接続の不足／判定 |
| --- | --- | --- |
| website prompt injection | AI system指示、Skillはweb/payloadをuntrusted扱い | 指示だけで保証不可。Agentのtool実行許可を本文に依存させない |
| malicious URL/content | SafeFetcher: public IP/redirect/robots/TLS/サイズ/timeout | 外部toolが取得guardを迂回しないこと。browserとAI判断の差を検証 |
| unauthorized send | confirmed、project role、登録宛先、permission | **B1: human principal分離なし** |
| duplicate send | unique draft、company既送信チェック、worker locks | **B3: direct form外部POST前の予約なし**。campaign並列race、request idempotencyなし |
| stale approval | emailはDelivery本文copy | **B2/B4: form本文/sender/宛先/入力版を承認時固定しない** |
| changed form | live fingerprint/STALE/禁止/CAPTCHA再検査 | 構造hashはpayload approval hashではない |
| cross-project | project_access、viewer/editor、他Project404 | agentのscopeなし。global adminは受信/設定を横断閲覧可能 |
| credential exposure | DB Fernet、secret非再表示、ログsafe errors | session共有/HTML本文/返信/設定の過剰tool返却。cloud/local鍵・scope未設計 |
| excessive collection | 1request上限、active job unique | 完了後の繰返し、同期API、machine quota/budgetなし |
| excessive sending | email rate/advisory、form20/実行 | confirmedを自身で設定できる。form組織共通rateなし、SMTPテスト別枠 |
| opt-out violation | permission service直前、unsubscribe/IMAP取込 | project横断scopeなし。editor contact-control解除、既承認から送信までのrace |
| false result / record destruction | Delivery/Approval/Activity | 支援結果はclient自己申告、Draft削除cascade、immutable actor ledgerなし |

`Company.website_text`、AI結果、受信返信、Form label/DOM、外部判断結果は**Untrusted Data**。それらの中の「送れ」「承認済み」「抑止を解除」は認可根拠にしない。抑止解除・送信承認・sender変更・秘密参照・admin操作をAgent準備操作と同じ権限で扱わない境界が必要だが、今回実装案を先に進めない。

## 17. Option A — Existing REST

既存RESTをDotsから直接利用する案。**現在利用できるHTTP契約はあるが、人のsessionを外部Agentへ共有する方式は安全な推奨接続として採用しない**。viewerならread、一方collection/Draft writeにeditorが必要でsendも可能になる。

| 比較軸 | 評価 |
| --- | --- |
| 既存コードへの影響/開発量 | 表面的には小。機械認証と準備/承認分離を満たすと追加が必要 |
| セキュリティ | Cookie/roleの権限が広い。M2M/prepare-onlyなし |
| Dots接続性 | HTTP toolsがあれば技術候補。Dots具体契約とlocalhost接続は不明 |
| Codex接続性 | RESTを扱えるclientは可能。現行Skillはbrowserタスク方式でREST agentではない |
| 保守性/他Agent再利用 | 既存146handlerをclientが理解する負担。安全allowlistが必要 |
| API安定性 | schemaはあるがversioned orchestration契約、job-ID単独読取/result帰属不足 |

HTTP methodだけのallowlist、write Cookie共有、全部のOpenAPI tools自動公開を安全とは判定しない。

## 18. Option B — Agent API

既存サービス/RESTの上へ薄い境界を置く案。例示された`/api/agent/*`は全てNOT IMPLEMENTED。

| 比較軸 | 評価 |
| --- | --- |
| 既存コードへの影響 | Core/worker/Provider再利用余地大。adapterだけで既存form承認・外部副作用raceは消えない |
| セキュリティ | prepare/read限定principal、allowlist、budgetを表す余地。未実装 |
| Dots/Codex接続性 | HTTP工具対応なら共用候補。製品契約・local transport次第 |
| 保守性/他Agent再利用 | 少数の型付きworkflow操作へ整理可能。別契約と既存APIの整合維持が必要 |
| API安定性 | job/result/draftとの対応を契約化できる可能性。現状からは不足 |
| 開発量 | 小〜中の可能性だが、human gate/フォームsnapshotを含めると「薄いだけ」と断定不可 |

Bは評価対象として有力だが、B1〜B4未解消の段階では選択・実装計画へ進めない。

## 19. Option C — MCP / Tool Server

LeadHive専用MCP server/toolsはNOT IMPLEMENTED。既存Codex SkillとMCPは別。`search_companies`/`start_collection`/`get_collection_status`/`prepare_outreach`等は将来候補名であり現在のAPI名ではない。

| 比較軸 | 評価 |
| --- | --- |
| 既存コードへの影響 | API/serviceをwrap可能。別transport/auth/tool schemaが必要 |
| セキュリティ | tool allowlistを絞れるがMCP化だけでHuman approvalを保証しない |
| Dots接続性 | Dots MCP support/local接続/承認UI未確認 |
| Codex接続性 | 対応clientとの親和性は候補。既存Skill起動・送信許可は自動で統合されない |
| 保守性/他Agent再利用 | MCP対応clientへ共用可能性、運用surface/互換性の追加負担 |
| API安定性 | tool契約の版管理が必要。基底RESTのcapability不足は残る |
| 開発量 | Bよりtransport面が増える可能性。製品契約未確認で見積確定不可 |

比較結論: **設計候補としてOption B（Thin Agent API）を推奨する**。既存REST・サービス・workerを維持し、外部へ公開する操作を限定でき、Dots固有transportへの依存も抑えられるためである。薄いAPIだけで承認・フォーム送信の問題は解消しない。実装移行は保留する。REST基底は再利用対象として維持し、MCPを理由に作り直さない。

## 20. PoC Proposal

**非送信・人介在・export型のPoC設計だけ**。今回は実行しない。B1〜B4のためAgentへwrite sessionを渡さず、既存送信API/Skill/task起動を利用しない。

対象: 大阪・兵庫のSNS運用会社50社、目的はハッシーOEM候補探索。ハッシーの実際の製品/価格/対象/実績/提携条件は未提示なので、勝手に営業目的や効果を補完しない。承認済みSalesObjectiveを評価開始前に人が定義する。

```text
人が既存Project/Profile/検索条件を確認 → 人がLeadHiveで収集
 → 人がWeb/既存AI解析（baseline） → 保存結果をexport
 → 同一50社・同一取得本文・目的を固定
 → 外部判断を3方式で比較 → 順位・根拠・DRAFT成果物
 → STOP（承認request/予約/送信/Skillなし）
```

結果exportでは会社ID/本文/出典/取得時刻/条件を固定したPoC成果物が必要。現行CSVはCompany全入力snapshotではないため、不足項目は人の許可されたread/exportで補う別工程。今回はexportしていない。既存AI未完了をDotsの返却値だけでcompletedへ書換えない。

| 比較arm | 定義 | 比較を公平にする条件 |
| --- | --- | --- |
| Existing LeadHive | 保存本文＋Profile/目的→現行AI score/reason/approach/draft | 同じ候補・時点、失敗も除外せず記録 |
| Dots-centric判断 | 同じ取得データ→Dots又は明示的な代理判断→順位/理由/DRAFT | Dots未接続なら「Dots相当」でありDots実証完了としない |
| Hybrid | Dots strategy/判断＋LeadHiveの確定属性/制約/集計を併用 | 禁止flagを判断で上書きせず、予定channelは可否未確定を表す |

上記は判断品質の比較。検索strategyの比較は、固定50社を共有する評価と別枠で、同じquery数/地域/時間予算を与え、公式unique企業数と適性企業数を測る。外部判断armをagent自身のbrowser取得にすると取得差と判断差が混ざるため別指標にする。

| 評価 | 測定方法 |
| --- | --- |
| 収集精度 | 人が公式/地域/SNS運用業務をreview、unique適性数。raw/saved/除外を分離 |
| 分析品質 | 人のgoldと適性一致、捏造、欠損を不明扱いできる割合、理由の出典 |
| 速度 | query/取得/推論/人作業/待ち時間を分けたwall time、中央値・tail |
| API/AI cost | provider requests/失敗・retry/token/Dots利用を分離。現行一般usage不足も記録 |
| 重複/再開 | Company重複、評価重複、同じcheckpointから再開したときの余計な処理 |
| 説明可能性 | 順位理由が承認済みOEM条件と出典に結び付くか |
| 操作量 | 人のclick/転記/review時間、tool回数 |
| エラー復旧 | 保存したfixture結果によるtimeout/欠損/型不正への対応比較。実サイト送信なし |

合格条件は事前合意が必要。必須停止条件案は未承認送信ゼロ、禁止解除ゼロ、Skill起動ゼロ、出典のない事実を確定扱いしない、失敗/費用/取得条件を隠さない。50社達成と分析精度・実API接続成功はそれぞれ別に判定する。

## 21. Missing Capabilities

| 不足 | 現在の状態 | 対象範囲 |
| --- | --- | --- |
| prepare専用machine principal/scopes | NOT IMPLEMENTED | 安全な自動API接続 |
| human-only approval request/state/hash/expiry | NOT IMPLEMENTED、B1 | live送信boundary |
| form approval snapshotとpayload一致 | PARTIAL、B2/B4 | form live execution |
| 外部POST前のidempotent claim/unknown照合 | PARTIAL、B3 | form/campaign送信 |
| job ID単独GET・結果帰属・stable paging | NOT IMPLEMENTED（基本listはある） | 継続orchestration |
| client Idempotency-Key/request ledger | NOT IMPLEMENTED | retry/resume |
| external analysis/Draft ingest | NOT IMPLEMENTED（Draft更新等はある） | Dots結果をSoRへ保存 |
| email campaign prepare-only | NOT IMPLEMENTED | 31社準備→人の承認 |
| permission/suppression read-only preflight | NOT IMPLEMENTED（serviceはある） | 事前候補選定 |
| machine budget/Provider quota/form rate | PARTIAL | 大量処理/副作用 |
| project横断opt-out、immutable attempt/actor/history | PARTIAL | 全社監査・再接触防止 |
| Dots transport/MCP/local bridge契約 | 未確認 | 実製品との接続 |

「不足」を本監査中の変更TODOとして実行しない。重大blockerがあるため修正手順・Migration案・adapter実装を開始しない。

## 22. Open Questions

1. Dotsの具体的製品/版とHTTP/MCP/auth/local connectorの契約は何か。
2. Agentはread/提案のみか、collection/Draft作成も許可するか。誰が独立に承認し、どの確定内容へ同意するか。
3. ハッシーOEMの承認済み目的、禁止業種、地域基準、提携候補のgoldは何か。
4. formのsender/入力/宛先/内容変更、approval失効、結果不明の再送をどう扱うか。
5. 抑止はProject単位か自社全体か。記録削除/保持/個人情報削除の条件は何か。
6. ローカルのみのLeadHiveとcloud Dotsをどう通信させるか。現在は127.0.0.1公開で外部到達不可。
7. Dotsの判断結果の版/出典/費用を正本へ残す要件は何か。
8. 300/3,000社は候補数・公式社数・適性・連絡可能数のどれを目標とするか。

## 23. Recommended Next Decision

**STOP CONDITION成立: live接続の実装移行を保留する。** 設計候補はOption Bとするが、人間承認の独立性（B1）、フォーム承認後の内容固定（B2/B4）、外部送信の二重実行防止（B3）について事実確認と方針決定が先である。既存LeadHiveの置換・削減を前提にしない。

| 判定候補 | 今回の結論 |
| --- | --- |
| READY FOR POC | **人介在・export・送信なしの比較に限定して可**。既存コードほぼ変更なし。今回未実施 |
| READY WITH THIN ADAPTER | **安全な送信まで含む全体判定としては不可**。adapterだけではB1〜B4の保証にならない |
| NEEDS CORE CHANGES | **想定する本接続全体の総合判定**。承認・form実行の業務境界に変更が必要。今回変更なし |
| NOT READY | 収集/解析/記録機能そのものの不足ではない。Dots具体契約と直接接続は未準備 |

外部Agentが収集・準備を安全に自動操作するPoCの判定も**NEEDS CORE CHANGES**とする。送信しない場合でも限定権限と外部判断・Draft保存契約が不足する。人介在・export型の比較はREADY FOR POCだが、自動接続の検証とは区別する。

**次に行うべき作業は、人間承認とAgent準備権限の境界についての設計レビュー1件とする。** Dots製品契約・OEM目的も未確定事項として扱う。認証追加、API/DB変更、PoC実行の手順は本監査の範囲外として保留した。

最大blocker5件: **①human-only権限なし、②form承認payloadの固定不足、③外部送信前idempotency不足、④M2M＋job/result/Draft契約不足、⑤Dots製品・localhost接続契約未確認**。

新規成果物は本監査文書のみ。コード/前回文書/DB/設定を変更せず、検索・実企業アクセス・メール/フォーム送信・Codex task・PR・merge・deployを行っていない。
