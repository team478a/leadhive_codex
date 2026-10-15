import { expect, test } from '@playwright/test'
import { createServer } from 'node:http'
import { htmlHash, runOfflineInput, type OfflineInput } from './offline-input'

const fields = '<label>会社名<input name="company-name" required></label><label>メール<input name="mail" type="email" required></label><label>本文<textarea name="message" required></textarea></label>'
const make = (body: string): OfflineInput => ({ html: body, expectedHtmlHash: htmlHash(body), sourceUrl: 'https://synthetic.example/contact', permission: 'UNKNOWN',
  values: { 'company-name': '合成テスト', mail: 'fixture@example.com', message: '送信しない入力テスト' }, choices: {}, consents: {} })
const form = (extra = '') => `<form action="https://synthetic.example/send" method="post">${fields}${extra}<button type="submit">送信</button></form>`

test('ordinary archive fills, reads back, never clicks submit and emits no content', async ({ browser }) => {
  const input = make(form('<script>document.querySelector("form").onsubmit=()=>{throw Error("must not submit")}</script>'))
  const result = await runOfflineInput(browser, input)
  expect(result.status).toBe('OFFLINE_INPUT_VERIFIED')
  expect(result.fieldsFilled).toBe(3)
  expect(result.sent).toBe(false)
  expect(result.approvalGranted).toBe(false)
  expect(result.executionAllowed).toBe(false)
  expect(result.confirmationReached).toBe(false)
  expect(result.liveFetchPerformed).toBe(false)
  expect(JSON.stringify(result)).not.toContain('fixture@example.com')
  expect(JSON.stringify(result)).not.toContain('送信しない入力テスト')
})

test('inline dynamic form and archived iframe are supported', async ({ browser }, info) => {
  for (const html of [ `<div id="root"></div><script>document.getElementById('root').innerHTML=${JSON.stringify(form())}</script>`,
    `<iframe srcdoc="${form().replaceAll('&', '&amp;').replaceAll('"', '&quot;')}"></iframe>` ]) {
    const result = await runOfflineInput(browser, make(html), info.project.name === 'mobile')
    expect(result, result.reason).toMatchObject({ status: 'OFFLINE_INPUT_VERIFIED' })
  }
})

test('explicit selection and consent only, mismatches stop', async ({ browser }) => {
  const input = make(form('<select name="topic" required><option value="">選択</option><option value="business">事業提携</option></select><label><input name="privacy" type="checkbox" required>規約内容を確認</label>'))
  expect((await runOfflineInput(browser, input)).reason).toBe('CHOICE_REVIEW_REQUIRED')
  input.choices.topic = 'business'
  expect((await runOfflineInput(browser, input)).reason).toBe('CONSENT_REVIEW_REQUIRED')
  input.consents.privacy = { checked: true, label: '別の同意' }
  expect((await runOfflineInput(browser, input)).reason).toBe('CONSENT_REVIEW_REQUIRED')
  input.consents.privacy.label = '規約内容を確認'
  expect((await runOfflineInput(browser, input)).status).toBe('OFFLINE_INPUT_VERIFIED')
})

test('missing required, CAPTCHA, sales prohibition, sensitive inputs and ambiguity stop', async ({ browser }) => {
  for (const [html, reason] of [
    [form('<input name="unknown" required>'), 'REQUIRED_FIELD_UNKNOWN'],
    [form('<div class="cf-turnstile" data-sitekey="synthetic"></div>'), 'CAPTCHA'],
    ['<p>営業目的のお問い合わせは禁止です</p>' + form(), 'SALES_PROHIBITED'],
    [form('<input name="password" type="password">'), 'SENSITIVE_FIELD'],
    [form('<input name="file" type="file">'), 'SENSITIVE_FIELD'],
    [form('<input name="mail">'), 'FIELD_AMBIGUOUS'],
    [form() + form(), 'FORM_AMBIGUOUS'],
  ]) expect((await runOfflineInput(browser, make(html))).reason).toBe(reason)
  const blocked = make(form()); blocked.permission = 'PROHIBITED'
  expect((await runOfflineInput(browser, blocked)).status).toBe('BLOCKED')
})

test('snapshot mismatch, unknown proposal and invalid URL stop', async ({ browser }) => {
  const input = make(form()); input.expectedHtmlHash = 'stale'
  expect((await runOfflineInput(browser, input)).reason).toBe('SNAPSHOT_INVALID')
  input.expectedHtmlHash = htmlHash(input.html); input.values.hidden = 'must not fill'
  expect((await runOfflineInput(browser, input)).reason).toBe('UNKNOWN_INPUT_FIELD')
  input.sourceUrl = 'https://user:secret@synthetic.example'
  expect((await runOfflineInput(browser, input)).reason).toBe('INVALID_SOURCE')
})

test('validation error, changed structure and rewritten input are detected', async ({ browser }) => {
  const invalid = make(form()); invalid.values.mail = 'not an email'
  expect((await runOfflineInput(browser, invalid)).reason).toBe('FORM_VALIDATION_ERROR')
  const changed = make(form('<script>document.querySelector("input").oninput=()=>document.querySelector("textarea").required=false</script>'))
  expect((await runOfflineInput(browser, changed)).reason).toBe('STRUCTURE_CHANGED')
  const rewritten = make(form('<script>document.querySelector("input").oninput=e=>e.target.value="rewritten"</script>'))
  expect((await runOfflineInput(browser, rewritten)).reason).toBe('READBACK_MISMATCH')
})

test('GET, POST autosave and WebSocket never reach a server', async ({ browser }) => {
  let received = 0
  const server = createServer((_request, response) => { received++; response.end('unexpected') })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  if (!address || typeof address === 'string') throw Error('Fixture unavailable')
  const target = `http://127.0.0.1:${address.port}`
  try {
    for (const html of [form(`<img src="${target}/tracking">`),
      form(`<script>document.querySelector('input').oninput=()=>fetch('${target}/autosave',{method:'POST',body:'private'}).catch(()=>{})</script>`),
      form(`<script>new WebSocket('${target.replace('http:', 'ws:')}/socket')</script>`),
    ]) {
      const result = await runOfflineInput(browser, make(html))
      expect(result.reason).toBe('NETWORK_REQUIRED')
      expect(result.blockedRequests).toBeGreaterThan(0)
      expect(received).toBe(0)
    }
  } finally { await new Promise<void>(resolve => server.close(() => resolve())); server.closeAllConnections() }
})
