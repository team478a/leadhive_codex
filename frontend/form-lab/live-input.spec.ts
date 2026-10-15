import { test, expect } from '@playwright/test'
import { createHash } from 'node:crypto'
import { runLiveInput } from './live-input'
import { canonicalLive, type LiveTask } from '../src/liveInputContract'
import { publicIPv4, publicTarget, robotsPermits } from './public-get'

const make = () => {
  const base = { definition: 'live-input-task-v1' as const, companyId: '11111111-1111-1111-1111-111111111111', projectId: '22222222-2222-2222-2222-222222222222',
    input: { formUrl: 'https://synthetic.example/contact', termsConfirmed: true as const, values: { name: '合成入力', email: 'fixture@example.com', message: '未送信テスト' }, choices: {}, consents: {} } }
  return { ...base, trialId: '33333333-3333-3333-3333-333333333333', requestHash: createHash('sha256').update(canonicalLive(base)).digest('hex'), token: 'lh_input_' + 'a'.repeat(64), expiresAt: new Date(Date.now() + 600_000).toISOString(), serverOrigin: 'https://owned.example' }
}
const form = '<form><label>名前<input name="name" required></label><label>メール<input type="email" name="email" required></label><label>本文<textarea name="message" required></textarea></label><button>送信</button></form>'

test('automatic report returns only unsent metadata and never retries', async () => {
  const { transferLiveResult } = await import('./live-input')
  const task = { ...make(), autoReport: true }
  const report = { definition: 'live-form-input-only-v1', trialId: task.trialId, companyId: task.companyId,
    projectId: task.projectId, requestHash: task.requestHash, status: 'LIVE_INPUT_VERIFIED',
    reason: 'STOP_BEFORE_CONFIRMATION_OR_SEND', fieldsFilled: 3, blockedRequests: 0,
    sent: false, approvalGranted: false, executionAllowed: false, confirmationReached: false,
    secret: task.token, values: task.input.values }
  let calls = 0
  const post = async (_task: LiveTask, action: string, body: Record<string, unknown>, origin: string) => {
    calls++; expect(action).toBe('result'); expect(origin).toBe(task.serverOrigin)
    expect(JSON.stringify(body)).not.toContain(task.token); expect(body).not.toHaveProperty('values')
  }
  expect(await transferLiveResult(task, report, task.serverOrigin, post)).toBe('RECORDED')
  expect(calls).toBe(1)
  expect(await transferLiveResult({ ...task, autoReport: false }, report, task.serverOrigin, post)).toBe('NOT_REQUESTED')
  for (const changed of [{ sent: true }, { companyId: make().projectId }, { fieldsFilled: 0 }, { blockedRequests: 1 }, { reason: 'private free text' }])
    expect(await transferLiveResult(task, { ...report, ...changed }, task.serverOrigin, post)).toBe('FAILED')
  expect(calls).toBe(1)
  expect(await transferLiveResult(task, report, task.serverOrigin, async () => { calls++; throw Error('offline') })).toBe('FAILED')
  expect(calls).toBe(2)
  expect(await transferLiveResult(task, report, 'https://foreign.example')).toBe('FAILED')
})

test('live pathway loads dynamic fields then freezes all traffic and stops before send', async ({ browser }) => {
  const phases: string[] = [], requests: string[] = []
  const transport = { count: 0, async fetch(url: string) {
    this.count++; requests.push(url)
    if (url.endsWith('/contact')) return { contentType: 'text/html', body: '<div id="root"></div><script src="/render.js"></script>' }
    return { contentType: 'application/javascript', body: `document.querySelector('#root').innerHTML=${JSON.stringify(form)}` }
  } }
  const result = await runLiveInput(browser, make(), 'https://owned.example', transport, async (_task, phase) => { phases.push(phase) })
  expect(result.status).toBe('LIVE_INPUT_VERIFIED'); expect(result.fieldsFilled).toBe(3)
  expect(phases).toEqual(['LOAD', 'INPUT']); expect(requests).toHaveLength(2)
  expect(result.sent).toBe(false); expect(result.confirmationReached).toBe(false); expect(result.approvalGranted).toBe(false)
  expect(JSON.stringify(result)).not.toContain('fixture@example.com')
})
for (const operation of ["fetch('/send',{method:'POST',body:this.value})", "fetch('/save?value='+this.value)", "this.form.submit()"])
  test(`live input never transmits data: ${operation}`, async ({ browser }) => {
    const transport = { count: 0, async fetch() { this.count++; return { contentType: 'text/html', body: form + `<script>document.querySelector('input').oninput=function(){${operation}}</script>` } } }
    const result = await runLiveInput(browser, make(), 'https://owned.example', transport, async () => {})
    expect(result.status).not.toBe('LIVE_INPUT_VERIFIED'); expect(result.reason).toBe('NETWORK_REQUIRED')
    expect(transport.count).toBe(1); expect(result.sent).toBe(false)
  })
test('revocation at input gate and sales prohibition prevent any fill', async ({ browser }) => {
  for (const blocked of [false, true]) {
    const transport = { count: 0, async fetch() { this.count++; return { contentType: 'text/html', body: form + (blocked ? '<p>営業目的のお問い合わせは禁止です。</p>' : '') } } }
    const result = await runLiveInput(browser, make(), 'https://owned.example', transport, async (_task, phase) => { if (phase === 'INPUT') throw Error('CORE_CHECK_DENIED') })
    expect(result.fieldsFilled).toBe(0); expect(result.status).not.toBe('LIVE_INPUT_VERIFIED'); expect(result.sent).toBe(false)
  }
})
test('edited and expired tasks never load the company site', async ({ browser }) => {
  for (const task of [{ ...make(), expiresAt: new Date(0).toISOString() }, { ...make(), input: { ...make().input, formUrl: 'https://foreign.example/contact' } }]) {
    let calls = 0
    await expect(runLiveInput(browser, task, 'https://owned.example', { count: 0, async fetch() { calls++; throw Error() } }, async () => {})).rejects.toThrow()
    expect(calls).toBe(0)
  }
})
test('public target, IP ranges and robots guard reject unsafe transport', () => {
  for (const value of ['http://example.com', 'https://127.0.0.1/', 'https://[::1]/', 'https://user:pass@example.com/', 'https://example.com:8443/', 'https://example.com/#x']) expect(() => publicTarget(value)).toThrow()
  for (const ip of ['127.0.0.1', '10.0.0.1', '192.168.1.1', '100.64.0.1', '169.254.169.254', '198.18.0.1', '224.0.0.1', '::1']) expect(publicIPv4(ip)).toBe(false)
  expect(publicIPv4('8.8.8.8')).toBe(true)
  expect(robotsPermits('User-agent: *\nDisallow: /contact', '/contact')).toBe(false)
  expect(robotsPermits('User-agent: *\nDisallow: /*?secret=', '/contact?secret=x')).toBe(false)
  expect(robotsPermits('User-agent: *\nDisallow: /\nAllow: /contact', '/contact')).toBe(true)
})
test('foreign script resources remain blocked', async ({ browser }) => {
  const transport = { count: 0, async fetch() { this.count++; return { contentType: 'text/html', body: form + '<script src="https://foreign.example/code.js"></script>' } } }
  const result = await runLiveInput(browser, make(), 'https://owned.example', transport, async () => {})
  expect(result.fieldsFilled).toBe(0); expect(result.reason).toBe('NETWORK_REQUIRED'); expect(transport.count).toBe(1)
})
