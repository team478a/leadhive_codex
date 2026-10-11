import { createHash } from 'node:crypto'
import { resolve4 } from 'node:dns/promises'
import { request } from 'node:https'
import { rootCertificates } from 'node:tls'
import type { Browser } from '@playwright/test'
import { canonicalLive, validateLiveTask, type LiveTask } from '../src/liveInputContract'
import { htmlHash, runOfflineInput } from './offline-input'
import { publicIPv4, publicTarget, PublicGetter } from './public-get'

export async function checkTicket(task: LiveTask, phase: 'LOAD' | 'INPUT', trustedOrigin: string) {
  await corePost(task, 'check', { requestHash: task.requestHash, phase }, trustedOrigin,
    v => v.inputOnly === true && v.sendAllowed === false)
}

async function corePost(task: LiveTask, action: 'check' | 'result', payload: Record<string, unknown>, trustedOrigin: string,
  accepted: (value: Record<string, unknown>) => boolean) {
  const server = publicTarget(trustedOrigin)
  if (server.origin !== trustedOrigin || trustedOrigin !== task.serverOrigin) throw Error('TRUSTED_SERVER_MISMATCH')
  const url = new URL(`/api/live-input-trials/${task.trialId}/${action}`, server)
  let timer: ReturnType<typeof setTimeout> | undefined
  const answers = await Promise.race([resolve4(url.hostname), new Promise<never>((_, reject) => { timer = setTimeout(() => reject(Error('CORE_DNS_TIMEOUT')), 5000) })]).finally(() => clearTimeout(timer))
  if (!answers.length || answers.some(a => !publicIPv4(a))) throw Error('UNSAFE_SERVER_DNS')
  const body = JSON.stringify(payload)
  if (Buffer.byteLength(body) > 4096) throw Error('CORE_BODY_LIMIT')
  await new Promise<void>((resolve, reject) => {
    const req = request(url, { method: 'POST', agent: false, ca: [...rootCertificates], rejectUnauthorized: true,
      lookup: (_h, opts, callback) => opts.all ? callback(null, [{ address: answers[0], family: 4 }]) : callback(null, answers[0], 4),
      headers: { Authorization: `Bearer ${task.token}`, 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) } }, res => {
      let bytes = 0; let text = ''
      res.on('data', (chunk: Buffer) => { bytes += chunk.length; if (bytes > 4096) res.destroy(); else text += chunk.toString('utf8') })
      res.on('error', () => reject(Error('CORE_CHECK_FAILED')))
      res.on('end', () => {
        try { const v = JSON.parse(text); if (res.statusCode !== 200 || !v || typeof v !== 'object' || !accepted(v)) throw Error(); resolve() }
        catch { reject(Error('CORE_CHECK_DENIED')) }
      })
    })
    const totalTimer = setTimeout(() => req.destroy(), 5000)
    req.on('close', () => clearTimeout(totalTimer))
    req.setTimeout(5000, () => req.destroy()); req.on('error', () => reject(Error('CORE_CHECK_FAILED'))); req.end(body)
  })
}

// Only bounded metadata is returned to the independently selected Core origin.
// Company pages never receive this credential; no redirects or automatic retries.
export async function transferLiveResult(value: unknown, result: unknown, trustedOrigin: string,
  post: typeof corePost = corePost): Promise<'NOT_REQUESTED' | 'RECORDED' | 'FAILED'> {
  try {
    validateLiveTask(value)
    if (value.autoReport !== true) return 'NOT_REQUESTED'
    const r = result as Record<string, unknown>
    if (!r || ['trialId', 'companyId', 'projectId', 'requestHash'].some(k => r[k] !== value[k as keyof LiveTask])
      || ['sent', 'approvalGranted', 'executionAllowed', 'confirmationReached'].some(k => r[k] !== false)
      || r.definition !== 'live-form-input-only-v1'
      || !['LIVE_INPUT_VERIFIED', 'TECHNICAL_UNKNOWN', 'HUMAN_REQUIRED', 'BLOCKED'].includes(String(r.status))
      || typeof r.reason !== 'string' || !/^[A-Z_]{3,100}$/.test(r.reason)
      || !Number.isInteger(r.fieldsFilled) || Number(r.fieldsFilled) < 0 || Number(r.fieldsFilled) > 100
      || !Number.isInteger(r.blockedRequests) || Number(r.blockedRequests) < 0 || Number(r.blockedRequests) > 100000
      || r.status === 'LIVE_INPUT_VERIFIED' && (r.reason !== 'STOP_BEFORE_CONFIRMATION_OR_SEND' || !r.fieldsFilled || r.blockedRequests !== 0)) return 'FAILED'
    const body = Object.fromEntries(['definition', 'trialId', 'companyId', 'projectId', 'requestHash', 'status', 'reason', 'fieldsFilled',
      'blockedRequests', 'sent', 'approvalGranted', 'executionAllowed', 'confirmationReached'].map(k => [k, r[k]]))
    await post(value, 'result', body, trustedOrigin, v => v.recorded === true && typeof v.alreadyRecorded === 'boolean')
    return 'RECORDED'
  } catch { return 'FAILED' }
}
export async function runLiveInput(browser: Browser, value: unknown, trustedOrigin: string,
  transport?: { fetch: (url: string, kind: 'document' | 'script' | 'stylesheet') => Promise<{ body: string; contentType: string }>; count: number },
  authorize: typeof checkTicket = checkTicket) {
  validateLiveTask(value)
  const task = value
  const original = { definition: task.definition, companyId: task.companyId, projectId: task.projectId, input: task.input }
  if (createHash('sha256').update(canonicalLive(original)).digest('hex') !== task.requestHash) throw Error('TASK_HASH_MISMATCH')
  publicTarget(task.input.formUrl)
  await authorize(task, 'LOAD', trustedOrigin)
  const getter = transport ?? new PublicGetter(task.input.formUrl)
  const page = await getter.fetch(task.input.formUrl, 'document')
  const result = await runOfflineInput(browser, { html: page.body, expectedHtmlHash: htmlHash(page.body), sourceUrl: task.input.formUrl,
    permission: 'UNKNOWN', values: task.input.values, choices: task.input.choices, consents: task.input.consents }, false, [],
  { fetch: (url, kind) => getter.fetch(url, kind), beforeInput: () => authorize(task, 'INPUT', trustedOrigin) })
  return { ...result, definition: 'live-form-input-only-v1',
    status: result.status === 'OFFLINE_INPUT_VERIFIED' ? 'LIVE_INPUT_VERIFIED' : result.status,
    liveFetchPerformed: true, getRequests: getter.count, trialId: task.trialId, companyId: task.companyId, projectId: task.projectId, requestHash: task.requestHash,
    source: 'PC_REPORTED_UNVERIFIED', executionAllowed: false, approvalGranted: false, confirmationReached: false, sent: false }
}
