import type { BenchmarkEvidence } from './completionBenchmarkTypes'
export type CompletionWorkRow = {
  benchmark?: BenchmarkEvidence
  company_id: string
  company_name: string | null
  status: string
  dm_ready: boolean
  dm_ready_reason: string | null
  reasons: { code: string; message: string; next_action: string }[]
  delivery_funnel: { sent: boolean; results: Record<string, number>; unverified_records: number }
}

export type CompletionQueueFilters = { state: string; reason: string; page: number }
export type CompletionReturnContext = {
  projectId: string
  cohortId: string
  cohortHash: string
  filters: CompletionQueueFilters
}
