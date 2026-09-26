export interface User { id: string; email: string; is_admin: boolean; created_at: string }
export interface ApplicationSettings {
  public_app_url: string; openai_model: string; gbizinfo_api_base_url: string
  openai_api_key_source: 'database' | 'environment' | 'unset'
  serper_api_key_source: 'database' | 'environment' | 'unset'
  google_places_api_key_source: 'database' | 'environment' | 'unset'
  gbizinfo_api_token_source: 'database' | 'environment' | 'unset'
  settings_encryption_ready: boolean
  updated_at: string | null
}
export type ApplicationService = 'serper' | 'google_places' | 'openai' | 'gbizinfo'
export interface ServiceConnectionTest {
  service: ApplicationService; ok: boolean; message: string; checked_at: string
}
export interface SmtpSettings {
  host: string; port: number; username: string; from_email: string; from_name: string
  use_starttls: boolean; timeout_seconds: number; password_configured: boolean; updated_at: string
  max_emails_per_day: number; minimum_interval_seconds: number
}
export interface FormSenderSettings {
  company_name: string; department: string; position: string; contact_name: string
  last_name: string; first_name: string; furigana: string; email: string; phone: string
  postal_code: string; prefecture: string; city: string; address: string; building: string
  website: string; updated_at: string | null
}
export interface ProfileInput {
  profile_name: string
  description: string
  search_keywords: string[]
  positive_keywords: string[]
  negative_keywords: string[]
  exclusion_keywords: string[]
  scoring_rules: Record<string, unknown>
  ai_instruction: string
  default_regions: string[]
  active: boolean
}
export interface Profile extends ProfileInput {
  id: string; user_id: string | null; is_system: boolean; created_at: string; updated_at: string
}
export interface ProjectInput {
  project_name: string; target_profile_id: string; sales_objective: string
  region: string; status: 'draft' | 'active' | 'archived'
}
export interface Project extends ProjectInput {
  id: string; user_id: string; created_at: string; updated_at: string
}
export interface ProjectMember {
  id: string; project_id: string; user_id: string; email: string
  role: 'owner' | 'editor' | 'viewer'; created_at: string
}
export type CollectionSource = 'serper' | 'google_places' | 'gbizinfo' | 'url' | 'csv'
export interface CollectionJob {
  id: string; project_id: string; source: CollectionSource; keyword: string; region: string
  status: 'running' | 'completed' | 'failed'; found_count: number; saved_count: number
  duplicate_count: number; excluded_count: number; error_count: number; processing_ms: number
  error_message: string
  created_at: string; finished_at: string | null
}
export interface AiReviewAnalytics { source_keyword: string; reviewed_count: number; correct_count: number; accuracy_rate: number }
export interface CollectionPerformance {
  source: CollectionSource; keyword: string; run_count: number; found_count: number
  saved_count: number; duplicate_count: number; excluded_count: number; error_count: number
  save_rate: number; excluded_rate: number; average_processing_ms: number
}
export interface CsvPreview {
  headers: string[]; sample_rows: Record<string, string>[]; row_count: number
  suggested_mapping: Record<string, string>
}
export interface Company {
  id: string; project_id: string; company_name: string; website_url: string | null
  domain: string | null; address: string; phone: string; email: string
  source: CollectionSource; source_keyword: string; status: SalesStatus; notes: string
  next_followup_at: string | null; assignee: string
  protected_fields: string[]
  do_not_contact: boolean; exclusion_reason: string
  contact_quality_status: 'unknown' | 'observed' | 'verified' | 'invalid'
  contact_source_url: string; contact_checked_at: string | null
  prefecture: string; city: string; contact_url: string
  instagram_url: string; x_url: string; tiktok_url: string; facebook_url: string
  youtube_url: string; line_url: string; business_summary: string; website_text: string
  scraped_urls: string[]
  analysis_status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | 'duplicate' | 'excluded'
  analysis_error: string; is_aggregator: boolean; duplicate_of_id: string | null
  scraped_at: string | null
  score: number | null; rank: 'A' | 'B' | 'C' | '対象外' | null; is_target: boolean | null
  business_type: string; ai_summary: string; ai_reason: string
  ai_strengths: string[]; ai_concerns: string[]; ai_recommended_approach: string
  ai_status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  ai_error: string; ai_provider: string; ai_model: string; ai_analyzed_at: string | null
  created_at: string; updated_at: string
}
export type SalesStatus = 'unreviewed' | 'target' | 'approached' | 'replied' | 'meeting' | 'won' | 'lost' | 'excluded'
export interface Dashboard {
  total_companies: number
  ranks: Record<string, number>
  statuses: Record<string, number>
  recent_jobs: CollectionJob[]
  operation_statuses: Record<string, number>
  unread_operation_failures: number
  recent_operations: OperationJob[]
  overdue_followups: number
  due_today_followups: number
}
export interface CompanyPage { items: Company[]; total: number; offset: number; limit: number }
export interface DataQuality {
  total: number; missing_website: number; missing_address: number
  missing_phone: number; missing_email: number; missing_contact: number
  failed_analysis: number; stale_analysis: number; reanalyzable: number; stale_days: number
}
export interface DuplicateCandidate {
  left: Company; right: Company; reasons: Array<'email' | 'phone' | 'name_address'>
}
export interface AiReview { id: string; company_id: string; reviewer_id: string | null; verdict: 'correct' | 'incorrect'; note: string; created_at: string; updated_at: string }
export interface Deal { id: string; company_id: string; title: string; stage: 'lead' | 'proposal' | 'negotiation' | 'won' | 'lost'; expected_amount: number; expected_close_date: string | null; owner: string; next_step: string; lost_reason: string; created_at: string; updated_at: string }
export interface DealPipelineItem extends Deal { project_id: string; company_name: string }
export interface DealPipeline { total_amount: number; by_stage: Record<string, number>; items: DealPipelineItem[] }
export interface OutreachExperiment { id: string; project_id: string; name: string; template_a_id: string; template_b_id: string; active: boolean; created_at: string; updated_at: string }
export interface OutreachExperimentResult { variant: 'A' | 'B'; delivered: number; replied: number; meetings: number; won: number; reply_rate: number }
export interface Activity {
  id: string; company_id: string
  activity_type: 'note' | 'call' | 'email' | 'form' | 'sns' | 'meeting' | 'status_change'
  note: string; created_at: string
}
export interface ContactPerson {
  id: string; company_id: string; name: string; department: string; title: string
  email: string; phone: string; source_url: string
  verification_status: 'unknown' | 'verified' | 'invalid'
  verified_at: string | null; notes: string; created_at: string; updated_at: string
}
export interface OutreachDraft {
  id: string; company_id: string; created_by_user_id: string | null; contact_person_id: string | null
  channel: 'email' | 'form' | 'sns'; subject: string; body: string
  ai_provider: string; ai_model: string; created_at: string; updated_at: string
}
export interface OutreachTemplate { id: string; project_id: string; created_by_user_id: string | null; name: string; channel: 'email' | 'form' | 'sns'; subject: string; body: string; created_at: string; updated_at: string }
export interface OutreachDraftApproval { id: string; draft_id: string; approved_by_user_id: string | null; approval_type: 'email' | 'form_direct' | 'form_codex'; subject: string; body: string; approved_at: string; delivered_at: string | null }
export interface EmailDelivery {
  id: string; draft_id: string; company_id: string; created_by_user_id: string | null
  recipient_email: string; recipient_name: string; subject: string; body: string
  status: 'queued' | 'running' | 'sent' | 'failed' | 'cancelled'
  scheduled_for: string; confirmed_at: string; sent_at: string | null
  started_at: string | null; finished_at: string | null; attempt_count: number
  error_message: string; created_at: string; updated_at: string
}
export interface EmailDeliveryListItem extends EmailDelivery { company_name: string }
export interface EmailDeliveryList {
  items: EmailDeliveryListItem[]; queued_count: number; running_count: number
  sent_count: number; failed_count: number; cancelled_count: number
}
export interface EmailCampaign { id: string; project_id: string; template_id: string; name: string; status: 'queued' | 'paused' | 'completed'; followup_days: number; queued_count: number; sent_count: number; failed_count: number; skipped_count: number; replied_count: number; meeting_count: number; won_count: number; created_at: string; updated_at: string }
export interface FormDeliveryBatchItem { id: string; company_id: string; draft_id: string | null; form_delivery_id: string | null; status: 'queued' | 'submitted' | 'failed' | 'manual_required' | 'skipped'; reason: string; submitted_at: string | null; created_at: string; company_name: string; form_url: string }
export interface FormDeliveryBatch { id: string; project_id: string; template_id: string; status: 'ready' | 'running' | 'completed' | 'cancelled'; operation_job_id: string | null; created_at: string; updated_at: string; items: FormDeliveryBatchItem[] }
export interface FormCodexTask { item_id: string; batch_id: string; company_id: string; company_name: string; form_url: string; body: string; reason: string; instructions: string; codex_status: 'open' | 'running' | 'submitted' | 'failed'; codex_assignee: string }
export interface FormField { name: string; label: string; field_type: 'text' | 'email' | 'tel' | 'textarea' | 'select'; required: boolean; value: string; options: string[]; mapped_key: string; confidence: number; decision_source: string }
export interface FormPreview { form_url: string; action_url: string; fields: FormField[]; form_profile_id: string | null; form_status: FormStatus; fingerprint: string }
export interface FormDelivery { id: string; draft_id: string; company_id: string; form_profile_id: string | null; delivery_method: 'direct' | 'codex_assisted'; status: 'pending' | 'submitted' | 'failed'; action_url: string; response_status: number | null; final_url: string; confirmation_used: boolean; completion_evidence: string; submitted_at: string | null; error_message: string; result_note: string; profile_fingerprint: string; field_mapping_snapshot: Array<Record<string, unknown>>; created_at: string }

export type FormStatus = 'UNANALYZED' | 'READY' | 'REVIEW_REQUIRED' | 'BLOCKED' | 'STALE' | 'ERROR'
export type FormMappedKey = 'company_name' | 'department' | 'position' | 'contact_name' | 'last_name' | 'first_name' | 'furigana' | 'email' | 'phone' | 'postal_code' | 'prefecture' | 'city' | 'address' | 'building' | 'website' | 'contact_category' | 'subject' | 'message' | 'privacy_consent' | 'newsletter_consent' | 'other' | 'unknown'
export interface FormProfileField { id: string; form_profile_id: string; position: number; selector: string; label: string; name: string; field_type: string; required: boolean; mapped_key: FormMappedKey; confidence: number; decision_source: 'DOM' | 'RULE' | 'JEV' | 'OPENAI' | 'MANUAL'; recommended_value: string; options: Array<{ value?: string; label?: string }>; placeholder: string; aria_label: string; surrounding_text: string; created_at: string; updated_at: string }
export interface FormProfile { id: string; company_id: string; form_url: string; form_index: number; form_status: FormStatus; sales_contact_status: 'ALLOWED' | 'PROHIBITED' | 'UNCERTAIN'; captcha_type: 'CAPTCHA_NONE' | 'CAPTCHA_RECAPTCHA' | 'CAPTCHA_HCAPTCHA' | 'CAPTCHA_TURNSTILE' | 'CAPTCHA_OTHER'; confirmation_page: boolean | null; is_primary: boolean; form_found: boolean; page_kind: string; fingerprint: string; analysis_version: string; analysis_provider: string; last_analyzed_at: string | null; analysis_duration_ms: number; error_message: string; created_at: string; updated_at: string; fields: FormProfileField[] }
export interface FormProfileSummary { company_id: string; profile_id: string; form_status: FormStatus; form_found: boolean; sales_contact_status: FormProfile['sales_contact_status']; captcha_type: FormProfile['captcha_type']; last_analyzed_at: string | null }
export interface FormAnalysisLog { id: string; company_id: string; form_profile_id: string | null; actor_user_id: string | null; event_type: string; provider: string; duration_ms: number; usage: Record<string, unknown>; estimated_cost: number | null; confidence: number | null; details: Record<string, unknown>; created_at: string }
export interface FormAssist { company_name: string; form_url: string; body: string; instructions: string }
export interface Notification {
  id: string; project_id: string; company_id: string | null; operation_job_id: string | null
  email_delivery_id: string | null; inbound_email_id: string | null
  notification_type: 'followup_overdue' | 'operation_failed' | 'email_delivery_failed' | 'inbound_reply_received' | 'followup_due_today'
  title: string; message: string; read_at: string | null; created_at: string
}
export interface FollowupTask { company: Company; due_state: 'overdue' | 'today' | 'upcoming' }
export interface ReplyQueueItem {
  company: Company; inbound_email_id: string; sender_email: string; subject: string
  preview: string; received_at: string
}
export type OutreachChannel = 'email' | 'form' | 'call' | 'sns'
export interface OutreachQueueItem {
  company: Company
  available_channels: OutreachChannel[]
  recommended_channel: OutreachChannel
  due_state: 'overdue' | 'today' | 'upcoming' | 'unset'
}
export interface OperationJob {
  id: string; project_id: string
  operation_type: 'collect_search' | 'web_analysis' | 'ai_analysis' | 'form_delivery' | 'form_intelligence'
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  total_count: number; processed_count: number; success_count: number; failed_count: number
  cancel_requested: boolean; attempt_count: number; acknowledged_at: string | null; error_message: string
  created_at: string; started_at: string | null; finished_at: string | null
}
export interface SearchSchedule {
  id: string; project_id: string; name: string
  source: 'serper' | 'google_places' | 'gbizinfo'; keywords: string[]; region: string
  max_results: number; interval_hours: number; company_limit: number; active: boolean
  next_run_at: string; last_enqueued_at: string | null; last_error: string
  created_at: string; updated_at: string
}
export interface AnalysisRefreshSchedule {
  id: string; project_id: string; interval_hours: number; stale_days: number
  batch_limit: number; active: boolean; next_run_at: string
  last_enqueued_at: string | null; last_error: string; created_at: string; updated_at: string
}
export interface SearchAnalytics {
  schedule_id: string; name: string; run_count: number
  found_count: number; saved_count: number; duplicate_count: number; excluded_count: number; error_count: number
  save_rate: number; duplicate_rate: number
}
export interface CompanyFilterValues {
  rank: string; minScore: string; region: string; status: string; source: string
  keyword: string; assignee: string; followup: string; sort: string
}
export interface SavedCompanyFilter {
  id: string; project_id: string; name: string; filters: CompanyFilterValues
  created_at: string; updated_at: string
}
export interface AssigneeAnalytics {
  assignee: string; total: number; approached: number; replied: number
  meetings: number; won: number; overdue: number
}
export interface SalesActivityAnalytics {
  days: number; activities: number; approached: number; replied: number
  meetings: number; won: number; reply_rate: number; meeting_rate: number; win_rate: number
  by_assignee: Array<{ assignee: string; approached: number; replied: number; meetings: number; won: number }>
}
export interface InboundMailSettings {
  host: string; port: number; username: string; mailbox: string; use_ssl: boolean
  timeout_seconds: number; poll_interval_seconds: number; active: boolean
  password_configured: boolean; last_polled_at: string | null; last_error: string; updated_at: string
}
export interface InboundEmail {
  id: string; sender_email: string; subject: string; preview: string; received_at: string
  company_id: string | null; company_name: string
  match_type: 'company_email' | 'contact_person' | 'manual' | 'unmatched'
  classification: 'reply' | 'bounce' | 'unsubscribe' | 'other'
  handled_by_user_id: string | null; handled_at: string | null
}
export interface InboundEmailCompanyCandidate {
  id: string; company_name: string; domain: string | null; email: string; project_name: string
}
export interface OutreachEffectivenessAnalytics {
  days: number
  items: Array<{ approval_type: 'email' | 'form_direct' | 'form_codex'; subject: string; approvals: number; replied: number; meetings: number; won: number; reply_rate: number }>
}
