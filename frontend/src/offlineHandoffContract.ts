// Unsigned diagnostic exchange; never an approval or a trusted machine attestation.
export type TrialBinding = { trialId: string; companyId: string; projectId: string; requestHash: string; htmlHash: string }
export const trialPrefix = '保存HTML入力報告 v1: '
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)
const canonical = (v: unknown): string => Array.isArray(v) ? `[${v.map(canonical).join(',')}]` : record(v)
  ? `{${Object.keys(v).sort().map(k => `${JSON.stringify(k)}:${canonical(v[k])}`).join(',')}}` : JSON.stringify(v)
export async function sha(value: string) {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)))].map(v => v.toString(16).padStart(2, '0')).join('')
}
export function validInput(v: unknown): v is Record<string, unknown> {
  if (!record(v) || typeof v.html !== 'string' || new TextEncoder().encode(v.html).length > 500_000
    || typeof v.expectedHtmlHash !== 'string' || typeof v.sourceUrl !== 'string' || !['UNKNOWN', 'ALLOWED', 'PROHIBITED'].includes(String(v.permission))) return false
  try { const url = new URL(v.sourceUrl); if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return false } catch { return false }
  for (const key of ['values', 'choices', 'consents']) if (!record(v[key])) return false
  if ([...Object.values(v.values as object), ...Object.values(v.choices as object)].some(x => typeof x !== 'string')) return false
  if (Object.values(v.consents as object).some(x => !record(x) || typeof x.checked !== 'boolean' || typeof x.label !== 'string')) return false
  return Object.keys(v).every(key => ['html', 'expectedHtmlHash', 'sourceUrl', 'permission', 'values', 'choices', 'consents'].includes(key))
}
export async function bindInput(input: unknown, companyId: string, projectId: string, prohibited: boolean) {
  if (!validInput(input) || await sha(input.html as string) !== input.expectedHtmlHash) throw Error('入力JSONまたはHTML hashが一致しません。')
  const effectiveInput = { ...input, permission: prohibited ? 'PROHIBITED' : 'UNKNOWN' }
  const trialId = crypto.randomUUID()
  const binding: TrialBinding = { trialId, companyId, projectId, htmlHash: input.expectedHtmlHash as string,
    requestHash: await sha(canonical({ trialId, companyId, projectId, input: effectiveInput })) }
  return { definition: 'offline-input-handoff-v1', binding, input: effectiveInput }
}
export async function validateTask(task: unknown) {
  if (!record(task) || task.definition !== 'offline-input-handoff-v1' || !record(task.binding) || !validInput(task.input)) throw Error('Invalid handoff schema')
  const b = task.binding
  if (['trialId', 'companyId', 'projectId', 'htmlHash', 'requestHash'].some(k => typeof b[k] !== 'string')) throw Error('Invalid binding')
  if (await sha(task.input.html as string) !== b.htmlHash || b.htmlHash !== task.input.expectedHtmlHash
    || await sha(canonical({ trialId: b.trialId, companyId: b.companyId, projectId: b.projectId, input: task.input })) !== b.requestHash) throw Error('Handoff binding mismatch')
  return { binding: b as TrialBinding, input: task.input }
}
const statuses = ['OFFLINE_INPUT_VERIFIED', 'HUMAN_REQUIRED', 'BLOCKED', 'TECHNICAL_UNKNOWN']
export function sanitizeReport(value: unknown, expected: TrialBinding) {
  if (!record(value) || value.definition !== 'offline-input-report-v1' || !record(value.binding) || !record(value.result)) throw Error('依頼に対応する結果JSONを選択してください。')
  if (Object.entries(expected).some(([k, v]) => value.binding && (value.binding as Record<string, unknown>)[k] !== v)) throw Error('企業・依頼・HTMLが一致しません。')
  const r = value.result
  if (r.definition !== 'offline-form-input-v1' || r.htmlHash !== expected.htmlHash || !statuses.includes(String(r.status))
    || typeof r.reason !== 'string' || !/^[A-Z_]{1,64}$/.test(r.reason)
    || ['executionAllowed', 'approvalGranted', 'confirmationReached', 'liveFetchPerformed', 'sent'].some(k => r[k] !== false)
    || ['fieldsFilled', 'actions', 'blockedRequests', 'durationMs'].some(k => typeof r[k] !== 'number' || !Number.isFinite(r[k]) || (r[k] as number) < 0)
    || r.status === 'OFFLINE_INPUT_VERIFIED' && (r.reason !== 'STOP_BEFORE_CONFIRMATION_OR_SEND' || !r.fieldsFilled || r.blockedRequests !== 0)) throw Error('未送信の診断結果として確認できません。')
  return { version: 1, source: 'PC_REPORTED_UNVERIFIED', ...expected, status: r.status as string, reason: r.reason,
    fieldsFilled: r.fieldsFilled as number, durationMs: r.durationMs as number, sent: false }
}
