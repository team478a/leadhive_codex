export interface User { id: string; email: string; created_at: string }
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
export type CollectionSource = 'serper' | 'google_places' | 'url' | 'csv'
export interface CollectionJob {
  id: string; project_id: string; source: CollectionSource; keyword: string; region: string
  status: 'running' | 'completed' | 'failed'; found_count: number; saved_count: number
  duplicate_count: number; error_count: number; error_message: string
  created_at: string; finished_at: string | null
}
export interface Company {
  id: string; project_id: string; company_name: string; website_url: string | null
  domain: string | null; address: string; phone: string; email: string
  source: CollectionSource; source_keyword: string; status: string
  created_at: string; updated_at: string
}
