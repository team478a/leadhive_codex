import { test, expect } from '@playwright/test'
import { decorativeFontStylesheet, htmlHash, runOfflineInput } from './offline-input'

const font = 'https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;700&display=swap'
const form = '<div id="contactForm"><label>Email<input name="email" type="email" required></label><label>Message<textarea name="message" required></textarea></label><button>Send</button></div>'
const input = (extra: string) => {
  const html = extra + form
  return { html, expectedHtmlHash: htmlHash(html), sourceUrl: 'https://synthetic.example/contact', permission: 'UNKNOWN' as const,
    values: { email: 'fixture@example.com', message: 'No sending' }, choices: {}, consents: {} }
}

test('font omission has an exact host, endpoint and bounded parameter contract', () => {
  expect(decorativeFontStylesheet(font)).toBe(true)
  expect(decorativeFontStylesheet('https://fonts.googleapis.com/css?family=Roboto|Open+Sans')).toBe(true)
  for (const value of [
    'https://fonts.googleapis.com.example.test/css2?family=Roboto',
    'https://fonts.googleapis.com./css2?family=Roboto',
    'https://fonts.googleapis.com:444/css2?family=Roboto',
    'https://user@fonts.googleapis.com/css2?family=Roboto',
    'http://fonts.googleapis.com/css2?family=Roboto',
    'https://fonts.googleapis.com/script?family=Roboto',
    'https://fonts.googleapis.com/css2',
    'https://fonts.googleapis.com/css2?family=',
    'https://fonts.googleapis.com/css2?family=Roboto%0A',
    'https://fonts.googleapis.com/css2?family=Roboto&unknown=1',
    'https://fonts.googleapis.com/css2?family=Roboto&display=invalid',
    'https://fonts.googleapis.com/css2?family=Roboto&display=swap&display=block',
    'https://fonts.googleapis.com/css2?family=Roboto#fragment',
    'https://fonts.googleapis.com/css2?family=' + 'A'.repeat(2200),
  ]) expect(decorativeFontStylesheet(value), value).toBe(false)
})

test('font-only stylesheet is locally omitted, never fetched or granted authority', async ({ browser }, info) => {
  let fetched = 0, authorized = 0
  const result = await runOfflineInput(browser, input(`<link rel="stylesheet" href="${font}">`), info.project.name === 'mobile', [], {
    fetch: async () => { fetched++; throw Error('NO_EXTERNAL_FETCH') }, beforeInput: async () => { authorized++ },
  })
  expect(fetched).toBe(0)
  expect(authorized).toBe(1)
  expect(result).toMatchObject({ status: 'OFFLINE_INPUT_VERIFIED', fieldsFilled: 2, omittedDecorativeRequests: 1,
    blockedRequests: 0, sent: false, confirmationReached: false, approvalGranted: false, executionAllowed: false })
})

test('arbitrary stylesheet, script, frame and data requests still stop before input', async ({ browser }) => {
  for (const [extra, reason] of [
    ['<link rel="stylesheet" href="https://unknown.example/style.css">', 'NETWORK_REQUIRED'],
    ['<link rel="stylesheet" href="https://fonts.googleapis.com.example.test/css2?family=Roboto">', 'NETWORK_REQUIRED'],
    [`<script src="${font}"></script>`, 'NETWORK_REQUIRED'],
    [`<iframe src="${font}"></iframe>`, 'EXTERNAL_FRAME'],
    [`<script>fetch(${JSON.stringify(font)}).catch(()=>{})</script>`, 'NETWORK_REQUIRED'],
  ]) expect(await runOfflineInput(browser, input(extra), false, [])).toMatchObject({
    reason, fieldsFilled: 0, omittedDecorativeRequests: 0, sent: false,
  })
})

test('font omission never applies after input starts or to the default archive path', async ({ browser }) => {
  const link = `<link rel="stylesheet" href="${font}">`
  expect((await runOfflineInput(browser, input(link))).reason).toBe('NETWORK_REQUIRED')
  const script = `<script>document.querySelector('input').oninput=()=>{const link=document.createElement('link');link.rel='stylesheet';link.href=${JSON.stringify(font)};document.head.append(link)}</script>`
  const late = input(''); late.html += script; late.expectedHtmlHash = htmlHash(late.html)
  expect(await runOfflineInput(browser, late, false, [])).toMatchObject({ reason: 'NETWORK_REQUIRED', omittedDecorativeRequests: 0, sent: false })
})

test('font omission preserves prohibition and CAPTCHA hard stops', async ({ browser }) => {
  for (const [extra, reason] of [['<p>営業目的の問い合わせは禁止です</p>', 'SALES_PROHIBITED'],
    ['<div class="g-recaptcha"></div>', 'CAPTCHA']] as const) {
    expect(await runOfflineInput(browser, input(`<link rel="stylesheet" href="${font}">${extra}`), false, [])).toMatchObject({
      reason, fieldsFilled: 0, sent: false, approvalGranted: false,
    })
  }
})
