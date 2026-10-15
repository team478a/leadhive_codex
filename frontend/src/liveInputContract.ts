export type LivePlan = { formUrl: string; termsConfirmed: true; values: Record<string, string>; choices: Record<string, string>; consents: Record<string, { label: string; checked: boolean }> }
export type LiveTask = { definition: 'live-input-task-v1'; trialId: string; companyId: string; projectId: string; requestHash: string; token: string; expiresAt: string; input: LivePlan; serverOrigin: string; autoReport?: boolean }
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)
export const canonicalLive = (v: unknown): string => Array.isArray(v) ? `[${v.map(canonicalLive).join(',')}]` : record(v)
  ? `{${Object.keys(v).sort().map(k => `${JSON.stringify(k)}:${canonicalLive(v[k])}`).join(',')}}` : JSON.stringify(v)
export function validateLiveTask(v: unknown): asserts v is LiveTask {
  if (!record(v) || v.definition !== 'live-input-task-v1' || !record(v.input) || typeof v.serverOrigin !== 'string'
    || !/^[a-f0-9]{64}$/.test(String(v.requestHash)) || !/^lh_input_[a-f0-9]{64}$/.test(String(v.token))
    || ['trialId', 'companyId', 'projectId'].some(k => !/^[a-f0-9-]{36}$/.test(String(v[k])))
    || v.autoReport !== undefined && typeof v.autoReport !== 'boolean'
    || typeof v.expiresAt !== 'string' || !Number.isFinite(Date.parse(v.expiresAt)) || Date.parse(v.expiresAt) <= Date.now()) throw Error('TASK_INVALID_OR_EXPIRED')
  const p = v.input
  if (typeof p.formUrl !== 'string' || p.termsConfirmed !== true || !record(p.values) || !record(p.choices) || !record(p.consents)
    || [...Object.values(p.values), ...Object.values(p.choices)].some(x => typeof x !== 'string')
    || Object.values(p.consents).some(x => !record(x) || typeof x.label !== 'string' || !x.label.trim() || typeof x.checked !== 'boolean')
    || Object.keys(p.values).length + Object.keys(p.choices).length + Object.keys(p.consents).length > 100
    || new TextEncoder().encode(JSON.stringify(p)).length > 40_000
    || Object.keys(p).some(k => !['formUrl', 'termsConfirmed', 'values', 'choices', 'consents'].includes(k))
    || Object.keys(v).some(k => !['definition', 'trialId', 'companyId', 'projectId', 'requestHash', 'token', 'expiresAt', 'input', 'serverOrigin', 'autoReport'].includes(k))) throw Error('TASK_INVALID')
}
