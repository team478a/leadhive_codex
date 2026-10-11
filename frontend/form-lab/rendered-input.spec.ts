import { test, expect } from '@playwright/test'
import { htmlHash, runOfflineInput, type OfflineInput, type CachedResource } from './offline-input'

const fields = '<label>会社名<input name="company-name" required></label><label>メール<input name="mail" type="email" required></label><label>本文<textarea name="message" required></textarea></label>'
const make = (script: string) => {
  const html = '<div id="root"></div><script src="https://synthetic.example/render.js"></script>'
  const input: OfflineInput = { html, expectedHtmlHash: htmlHash(html), sourceUrl: 'https://synthetic.example/contact', permission: 'UNKNOWN',
    values: { 'company-name': '合成テスト', mail: 'fixture@example.com', message: '送信しないテスト' }, choices: {}, consents: {} }
  const resources: CachedResource[] = [{ url: 'https://synthetic.example/render.js', kind: 'script', body: script, sha256: htmlHash(script) }]
  return { input, resources }
}
const render = `document.querySelector('#root').innerHTML=${JSON.stringify(`<form action="/send" method="post">${fields}<button>送信</button></form>`)};`

test('downloaded script renders a real URL snapshot without live network', async ({ browser }, info) => {
  const { input, resources } = make(render)
  // This .example host cannot be contacted; every response is fulfilled from snapshots.
  const result = await runOfflineInput(browser, input, info.project.name === 'mobile', resources)
  expect(result.status).toBe('OFFLINE_INPUT_VERIFIED')
  expect(result.fieldsFilled).toBe(3)
  expect(result.blockedRequests).toBe(0)
  expect(result.liveFetchPerformed).toBe(false)
  expect(result.sent).toBe(false)
  expect(result.confirmationReached).toBe(false)
  expect(result.executionAllowed).toBe(false)
  expect(JSON.stringify(result)).not.toContain('fixture@example.com')
})

test('default archive still refuses external scripts', async ({ browser }) => {
  const { input } = make(render)
  expect((await runOfflineInput(browser, input)).reason).toBe('NETWORK_REQUIRED')
})

test('snapshot tamper and foreign resources are rejected before browser use', async ({ browser }) => {
  const { input, resources } = make(render)
  for (const change of [
    { ...resources[0], body: 'tampered' },
    { ...resources[0], url: 'https://foreign.example/render.js' },
  ]) expect((await runOfflineInput(browser, input, false, [change])).reason).toBe('RESOURCE_SNAPSHOT_INVALID')
})

test('required missing scripts stop rather than inventing a form', async ({ browser }) => {
  const { input } = make(render)
  expect((await runOfflineInput(browser, input, false, [])).reason).toBe('NETWORK_REQUIRED')
})

for (const operation of [
  "fetch('/send',{method:'POST',body:'synthetic'}).catch(()=>{})",
  "fetch('/render.js').catch(()=>{})",
  "document.querySelector('form').submit()",
]) {
  test(`input freezes all transport: ${operation}`, async ({ browser }) => {
    const { input, resources } = make(render + `document.querySelector('input').addEventListener('input',()=>{${operation}});`)
    const result = await runOfflineInput(browser, input, false, resources)
    expect(result.reason).toBe('NETWORK_REQUIRED')
    expect(result.status).not.toBe('OFFLINE_INPUT_VERIFIED')
    expect(result.blockedRequests).toBeGreaterThan(0)
    expect(result.sent).toBe(false)
  })
}

test('rendered and late sales prohibition prevent completion', async ({ browser }) => {
  for (const script of [
    render + "document.body.insertAdjacentHTML('beforeend','<p>営業メールはご遠慮ください。</p>')",
    render + "document.querySelector('input').addEventListener('input',()=>{document.body.insertAdjacentHTML('beforeend','<p>営業目的の連絡は禁止です。</p>')})",
  ]) {
    const { input, resources } = make(script)
    const result = await runOfflineInput(browser, input, false, resources)
    expect(result.status).toBe('BLOCKED')
    expect(result.reason).toBe('SALES_PROHIBITED')
    expect(result.sent).toBe(false)
  }
})

test('different script snapshots change the payload hash', async ({ browser }) => {
  const first = make(render)
  const second = make(render + '\n/* new snapshot */')
  const a = await runOfflineInput(browser, first.input, false, first.resources)
  const b = await runOfflineInput(browser, second.input, false, second.resources)
  expect(a.status).toBe('OFFLINE_INPUT_VERIFIED')
  expect(b.status).toBe('OFFLINE_INPUT_VERIFIED')
  expect(a.payloadHash).not.toBe(b.payloadHash)
})

test('CAPTCHA and worker transports cannot be enabled by cached scripts', async ({ browser }) => {
  for (const [script, reason] of [
    [render + "document.body.insertAdjacentHTML('beforeend','<div class=cf-turnstile data-sitekey=fixture></div>')", 'CAPTCHA'],
    [render + "try{new Worker('/worker.js')}catch{}", 'NETWORK_REQUIRED'],
    [render + "try{new RTCPeerConnection()}catch{}", 'NETWORK_REQUIRED'],
  ]) {
    const { input, resources } = make(script)
    const result = await runOfflineInput(browser, input, false, resources)
    expect(result.reason).toBe(reason)
    expect(result.status).not.toBe('OFFLINE_INPUT_VERIFIED')
    expect(result.fieldsFilled).toBe(0)
    expect(result.sent).toBe(false)
  }
})
