import { test, expect } from '@playwright/test'
import { htmlHash, runOfflineInput } from './offline-input'
import { documentSnapshot } from './document-snapshot'

const fields = '<label>会社<input name="company" required></label><label>メール<input type="email" name="email" required></label><label>本文<textarea name="message" required></textarea></label>'
const custom = (extra = '', id = 'contactForm') => `<div id="${id}">${fields}${extra}<button id="send">送信する</button></div>`
const input = (html: string) => ({ html, expectedHtmlHash: htmlHash(html), sourceUrl: 'https://synthetic.example/contact', permission: 'UNKNOWN' as const,
  values: { company: '合成テスト', email: 'fixture@example.com', message: '送信しない' }, choices: {}, consents: {} })

test('custom contact scope fills and reads back without clicking or granting permission', async ({ browser }) => {
  const result = await runOfflineInput(browser, input(custom('<script>document.querySelector("button").onclick=()=>{throw Error("must not click")}</script>')), false, [])
  expect(result).toMatchObject({ status: 'OFFLINE_INPUT_VERIFIED', fieldsFilled: 3, blockedRequests: 0,
    sent: false, confirmationReached: false, approvalGranted: false, executionAllowed: false })
})

test('nested contact scope is selected once; ordinary form retains priority', async ({ browser }) => {
  for (const html of [`<section id="contact">${custom()}</section>`, `${custom()}<form>${fields}</form>`]) {
    expect(await runOfflineInput(browser, input(html))).toMatchObject({ status: 'OFFLINE_INPUT_VERIFIED', fieldsFilled: 3 })
  }
  const linked = `<form id="normal">${fields}</form><input name="outside" form="normal" required>`
  expect((await runOfflineInput(browser, input(linked))).reason).toBe('FORM_VALIDATION_ERROR')
})

test('five-field custom contact structure includes an optional telephone without mixing unrelated inputs', async ({ browser }) => {
  const html = `<input name="search"><section aria-label="Contact"><label>会社<input name="company"></label>
    <label>氏名<input name="name"></label><label>メール<input type="email" name="email"></label>
    <label>電話<input type="tel" name="tel"></label><label>本文<textarea name="message"></textarea></label><button>送信</button></section>`
  const proposal = input(html)
  Object.assign(proposal.values, { name: '合成担当者', tel: '' })
  expect(await runOfflineInput(browser, proposal, false, [])).toMatchObject({ status: 'OFFLINE_INPUT_VERIFIED', fieldsFilled: 5 })
})

test('ambiguous, hidden, unnamed, external-form and unrelated containers stop without input', async ({ browser }) => {
  for (const html of [custom() + custom('', 'inquiry'), `<div hidden>${custom()}</div>`,
    custom('<input>'), custom('<input name="other" form="elsewhere">'), custom('', 'login'),
    custom('<input name="email">'), custom('<input type="password" name="password">')]) {
    expect(await runOfflineInput(browser, input(html))).toMatchObject({ reason: 'FORM_AMBIGUOUS', fieldsFilled: 0 })
  }
})

test('custom scope preserves prohibition, CAPTCHA, required fields and validation', async ({ browser }) => {
  for (const [html, reason] of [[custom('<p>営業目的のお問い合わせは禁止です</p>'), 'SALES_PROHIBITED'],
    [custom('<div class="g-recaptcha"></div>'), 'CAPTCHA'], [custom('<input name="unknown" required>'), 'REQUIRED_FIELD_UNKNOWN']] as const) {
    expect(await runOfflineInput(browser, input(html))).toMatchObject({ reason, fieldsFilled: 0 })
  }
  const invalid = input(custom()); invalid.values.email = 'invalid'
  expect((await runOfflineInput(browser, invalid)).reason).toBe('FORM_VALIDATION_ERROR')
})

test('custom scope stops autosave, changed structure and rewritten values', async ({ browser }) => {
  for (const [script, reason] of [
    ['document.querySelector("input").oninput=()=>fetch("/autosave",{method:"POST"}).catch(()=>{})', 'NETWORK_REQUIRED'],
    ['document.querySelector("input").oninput=()=>document.querySelector("textarea").required=false', 'STRUCTURE_CHANGED'],
    ['document.querySelector("input").oninput=e=>e.target.value="rewritten"', 'READBACK_MISMATCH'],
  ]) expect((await runOfflineInput(browser, input(custom(`<script>${script}</script>`)), false, [])).reason).toBe(reason)
})

test('large raster snapshot can render custom fields while retaining safety text', async ({ browser }) => {
  const html = `<img src="data:image/png;base64,${'A'.repeat(2_100_000)}">${custom()}`
  const compacted = documentSnapshot(html)
  expect(compacted).toBe(`<img src="data:,">${custom()}`)
  expect(await runOfflineInput(browser, input(compacted), false, [])).toMatchObject({ status: 'OFFLINE_INPUT_VERIFIED', fieldsFilled: 3 })
})
