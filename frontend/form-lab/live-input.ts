import { createHash } from 'node:crypto'
import { resolve4 } from 'node:dns/promises'
import { request } from 'node:https'
import { rootCertificates } from 'node:tls'
import type { Browser } from '@playwright/test'
import { canonicalLive, validateLiveTask, type LiveTask } from '../src/liveInputContract'
import { htmlHash, runOfflineInput } from './offline-input'
import { publicIPv4, publicTarget, PublicGetter } from './public-get'

export async function checkTicket(task: LiveTask, phase: 'LOAD' | 'INPUT', trustedOrigin: string) {
  const server = publicTarget(trustedOrigin)
  if (server.origin !== trustedOrigin || trustedOrigin !== task.serverOrigin) throw Error('TRUSTED_SERVER_MISMATCH')
  const url = new URL(`/api/live-input-trials/${task.trialId}/check`, server)
  let timer: ReturnType<typeof setTimeout> | undefined
  const answers = await Promise.race([resolve4(url.hostname), new Promise<never>((_, reject) => { timer = setTimeout(() => reject(Error('CORE_DNS_TIMEOUT')), 5000) })]).finally(() => clearTimeout(timer))
  if (!answers.length || answers.some(a => !publicIPv4(a))) throw Error('UNSAFE_SERVER_DNS')
  const body = JSON.stringify({ requestHash: task.requestHash, phase })
  await new Promise<void>((resolve, reject) => {
    const req = request(url, { method: 'POST', agent: false, ca: [...rootCertificates], rejectUnauthorized: true,
      lookup: (_h, opts, callback) => opts.all ? callback(null, [{ address: answers[0], family: 4 }]) : callback(null, answers[0], 4),
      headers: { Authorization: `Bearer ${task.token}`, 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) } }, res => {
      let bytes = 0; let text = ''
      res.on('data', (chunk: Buffer) => { bytes += chunk.length; if (bytes > 4096) res.destroy(); else text += chunk.toString('utf8') })
      res.on('error', () => reject(Error('CORE_CHECK_FAILED')))
      res.on('end', () => {
        try { const v = JSON.parse(text); if (res.statusCode !== 200 || v.inputOnly !== true || v.sendAllowed !== false) throw Error(); resolve() }
        catch { reject(Error('CORE_CHECK_DENIED')) }
      })
    })
    const totalTimer = setTimeout(() => req.destroy(), 5000)
    req.on('close', () => clearTimeout(totalTimer))
    req.setTimeout(5000, () => req.destroy()); req.on('error', () => reject(Error('CORE_CHECK_FAILED'))); req.end(body)
  })
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
