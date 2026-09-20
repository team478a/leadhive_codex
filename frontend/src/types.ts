export interface User { id: string; email: string; is_admin: boolean; created_at: string }
export interface SmtpSettings {
  host: string; port: number; username: string; from_email: string; from_name: string
  use_starttls: boolean; timeout_seconds: number; password_configured: boolean; updated_at: string
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
export type CollectionSource = 'serper' | 'google_places' | 'url' | 'csv'
export interface CollectionJob {
  id: string; project_id: string; source: CollectionSource; keyword: string; region: string
  status: 'running' | 'completed' | 'failed'; found_count: number; saved_count: number
  duplicate_count: number; excluded_count: number; error_count: number; processing_ms: number
  error_message: string
  created_at: string; finished_at: string | null
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
export interface EmailDelivery {
  id: string; draft_id: string; company_id: string; created_by_user_id: string | null
  recipient_email: string; recipient_name: string; subject: string; body: string
  status: 'queued' | 'running' | 'sent' | 'failed' | 'cancelled'
  scheduled_for: string; confirmed_at: string; sent_at: string | null
  started_at: string | null; finished_at: string | null; attempt_count: number
  error_message: string; created_at: string; updated_at: string
}
export interface Notification {
  id: string; project_id: string; company_id: string | null; operation_job_id: string | null
  email_delivery_id: string | null
  notification_type: 'followup_overdue' | 'operation_failed' | 'email_delivery_failed'
  title: string; message: string; read_at: string | null; created_at: string
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
  operation_type: 'collect_search' | 'web_analysis' | 'ai_analysis'
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  total_count: number; processed_count: number; success_count: number; failed_count: number
  cancel_requested: boolean; attempt_count: number; acknowledged_at: string | null; error_message: string
  created_at: string; started_at: string | null; finished_at: string | null
}
export interface SearchSchedule {
  id: string; project_id: string; name: string
  source: 'serper' | 'google_places'; keywords: string[]; region: string
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
