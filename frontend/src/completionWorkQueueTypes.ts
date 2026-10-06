export type CompletionWorkRow = {
  company_id: string
  company_name: string | null
  status: string
  dm_ready: boolean
  dm_ready_reason: string | null
  reasons: { code: string; message: string; next_action: string }[]
  delivery_funnel: { sent: boolean; results: Record<string, number>; unverified_records: number }
}
