export const benchmarkStages = ['DISCOVERED', 'MATCHED', 'IDENTITY_CONFIRMED', 'OFFICIAL_SITE_CONFIRMED', 'DESTINATION_FOUND', 'CONTACT_ALLOWED', 'SENDABILITY_READY', 'DM_PREPARED', 'DM_READY'] as const
export type BenchmarkEvidence = {
  raw_stages: Record<string, boolean | null>; passed_stages: Record<string, boolean | null>
  primary_reason: string | null; secondary_reasons: string[]; reason_codes: string[]
  extra_reasons: { code: string; message: string; next_action: string }[]
  sole_blockers: string[]; potential_unlock: string[]
  match: string; identity: string; official_site: string; permission: string; preparation: string
  execution_allowed: boolean
}
export type BenchmarkMeta = { definition: string; baseline: Record<string, unknown> | null; cost: Record<string, unknown> }
export type BenchmarkRow = { status: string; benchmark?: BenchmarkEvidence; destinations: { key: string; type: string; shared: boolean }[] }
export function validBenchmark(row: BenchmarkRow): boolean {
  const b = row.benchmark
  if (!b || b.execution_allowed !== false || !['MATCHED', 'NOT_MATCHED', 'UNKNOWN'].includes(b.match) || !['CONFIRMED', 'PROBABLE', 'REVIEW_REQUIRED', 'DIFFERENT', 'UNKNOWN'].includes(b.identity) || !['CONFIRMED', 'HIGH', 'MEDIUM', 'LOW', 'REVIEW_REQUIRED', 'NOT_FOUND', 'UNKNOWN'].includes(b.official_site) || !['ALLOWED', 'UNCERTAIN', 'PROHIBITED'].includes(b.permission) || !['NOT_STARTED', 'DRAFT_PREPARED', 'REVIEW_REQUIRED', 'INVALIDATED', 'EXPIRED'].includes(b.preparation)) return false
  if (![b.raw_stages, b.passed_stages].every(stages => !!stages && benchmarkStages.every(code => stages[code] === null || typeof stages[code] === 'boolean')) || ![b.secondary_reasons, b.reason_codes, b.sole_blockers, b.potential_unlock].every(codes => Array.isArray(codes) && codes.every(code => typeof code === 'string')) || !Array.isArray(b.extra_reasons) || !b.extra_reasons.every(reason => [reason.code, reason.message, reason.next_action].every(v => typeof v === 'string'))) return false
  let passed: boolean | null = true
  for (const code of benchmarkStages) {
    const raw = b.raw_stages[code]
    passed = passed === false || raw === false ? false : passed === null || raw === null ? null : true
    if (b.passed_stages[code] !== passed) return false
  }
  return b.raw_stages.DISCOVERED === true && b.potential_unlock.every(code => b.sole_blockers.includes(code))
}
