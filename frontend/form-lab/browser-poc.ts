import { createHash } from 'node:crypto'
import { devices, type Browser, type BrowserContext, type Frame } from '@playwright/test'
import { consentText, type Fixture } from './fixtures'

export type Proposal = {
  values: Record<string, string>
  selections: Record<string, string>
  consents: Record<string, { checked: boolean; text: string }>
}
export const anonymousProposal: Proposal = {
  values: { name: '匿名テスト', email: 'fixture@example.com', message: 'これはlocalhostの検証です。送信しません。' },
  selections: { topic: 'business', reply: 'email' },
  consents: { privacy: { checked: true, text: consentText } },
}
export type Control = {
  tag: string; type: string; name: string; required: boolean; label: string
  options: { value: string; label: string }[]
}
export type PocResult = {
  operationStatus: 'BROWSER_VERIFIED' | 'HUMAN_REQUIRED' | 'TECHNICAL_UNKNOWN'
  salesAuthorization: 'UNKNOWN' | 'PROHIBITED'
  executionAllowed: false
  confirmationReached: boolean
  reason: string
  controls: Control[]
  fingerprint: string | null
  payloadHash: string
  actions: number
  durationMs: number
  blockedRequests: number
  log: string[]
  viewportWidth: number | null
}
const hash = (value: unknown) => createHash('sha256').update(JSON.stringify(value)).digest('hex')

export async function installGuard(
  context: BrowserContext, allowed: Set<string>, maxMs: number, started: number,
  state: { blockedRequests: number; log: string[] },
) {
  const origins = new Set([...allowed].map(value => {
    const url = new URL(value)
    if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || !url.port || url.username || url.password || url.search || url.hash) throw new Error('Only owned loopback fixtures are permitted')
    return url.origin
  }))
  if (origins.size !== 1) throw new Error('Foreign fixture URL')
  let requests = 0
  await context.route('**/*', async route => {
    const request = route.request()
    requests++
    if (requests > 20 || request.method() !== 'GET' || !allowed.has(request.url()) || performance.now() - started >= maxMs) {
      state.blockedRequests++; state.log.push('NETWORK_BLOCKED')
      await route.abort('blockedbyclient')
      return
    }
    // Browser redirect chains are not reliably routed at every hop. Inspect the
    // owned fixture response without following redirects, before browser delivery.
    try {
      const response = await route.fetch({ maxRedirects: 0, maxRetries: 0, timeout: Math.max(1, maxMs - (performance.now() - started)) })
      if (response.status() >= 300 && response.status() < 400) {
        state.blockedRequests++; state.log.push('REDIRECT_BLOCKED')
        await route.abort('blockedbyclient')
      } else await route.fulfill({ response })
    } catch {
      state.blockedRequests++; state.log.push('NETWORK_FAILED')
      await route.abort('failed')
    }
  })
  await context.routeWebSocket('**/*', socket => { state.log.push('WEBSOCKET_BLOCKED'); socket.close() })
}

async function controls(frame: Frame): Promise<Control[]> {
  return frame.locator('form input, form textarea, form select').evaluateAll(nodes => nodes.map(node => {
    const field = node as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
    return {
      tag: field.tagName.toLowerCase(), type: field.type, name: field.name,
      required: field.required,
      label: [...(field.labels || [])].map(label => label.textContent?.trim() || '').join(' '),
      options: field instanceof HTMLSelectElement
        ? [...field.options].map(option => ({ value: option.value, label: option.textContent || '' }))
        : field.type === 'radio' || field.type === 'checkbox' ? [{ value: field.value, label: '' }] : [],
    }
  }))
}

async function formStructure(frame: Frame) {
  return frame.locator('form').evaluate(form => ({
    action: (form as HTMLFormElement).action, method: (form as HTMLFormElement).method,
    buttons: [...form.querySelectorAll('button')].map(button => ({ type: button.type, text: button.textContent, disabled: button.disabled })),
  }))
}

export async function runPoc(
  browser: Browser, fixture: Fixture, scenario: string,
  proposal: Proposal = anonymousProposal, maxActions = 12, maxMs = 5000,
  viewMode: 'desktop' | 'mobile' = 'desktop',
): Promise<PocResult> {
  proposal = structuredClone(proposal)
  const started = performance.now()
  const origin = new URL(fixture.origin)
  if (origin.protocol !== 'http:' || origin.hostname !== '127.0.0.1' || !origin.port || origin.username || origin.password) {
    throw new Error('Only owned loopback fixtures are permitted')
  }
  if (!fixture.urls[scenario] || !Number.isInteger(maxActions) || maxActions < 1 || maxActions > 20 || !Number.isInteger(maxMs) || maxMs < 1 || maxMs > 10_000) {
    throw new Error('Invalid fixture or operation budget')
  }
  const allowed = new Set([fixture.urls[scenario], fixture.urls.usage, `${fixture.origin}/robots.txt`])
  if (scenario === 'iframe') allowed.add(fixture.urls.inner)
  if ([...allowed].some(url => new URL(url).origin !== fixture.origin)) throw new Error('Foreign fixture URL')
  const device = devices[viewMode === 'mobile' ? 'iPhone 13' : 'Desktop Chrome']
  const context = await browser.newContext({ serviceWorkers: 'block', acceptDownloads: false,
    viewport: device.viewport, userAgent: device.userAgent, deviceScaleFactor: device.deviceScaleFactor,
    isMobile: device.isMobile, hasTouch: device.hasTouch })
  const result: PocResult = {
    operationStatus: 'TECHNICAL_UNKNOWN', salesAuthorization: 'UNKNOWN', executionAllowed: false,
    confirmationReached: false, reason: 'NOT_CHECKED', controls: [], fingerprint: null,
    payloadHash: hash({ proposal, method: 'browser-preview-poc-v1', target: fixture.urls[scenario] }),
    actions: 0, durationMs: 0, blockedRequests: 0, log: [], viewportWidth: null,
  }
  const remaining = () => Math.max(1, maxMs - (performance.now() - started))
  const check = () => {
    if (performance.now() - started >= maxMs || result.actions >= maxActions) throw new Error('OPERATION_BUDGET')
  }
  const action = async (name: string, execute: () => Promise<unknown>) => {
    check(); result.actions++; result.log.push(name); await execute()
  }
  await installGuard(context, allowed, maxMs, started, result)
  context.on('page', page => {
    page.on('download', download => { result.log.push('DOWNLOAD_BLOCKED'); void download.cancel() })
    page.on('popup', popup => { result.log.push('POPUP_BLOCKED'); void popup.close() })
  })
  try {
    const page = await context.newPage()
    result.viewportWidth = page.viewportSize()?.width || null
    page.setDefaultTimeout(maxMs)
    // Use a guarded browser page, never context.request (which bypasses routing).
    await action('ROBOTS_CHECK', () => page.goto(`${fixture.origin}/robots.txt`, { timeout: remaining() }))
    const robots = await page.locator('body').innerText({ timeout: remaining() })
    const targetPath = new URL(fixture.urls[scenario]).pathname
    if (robots.split('\n').some(line => line.startsWith('Disallow: ') && targetPath.startsWith(line.slice(10)))) {
      result.reason = 'ROBOTS_BLOCKED'; return result
    }
    await action('TERMS_CHECK', () => page.goto(fixture.urls.usage, { timeout: remaining() }))
    const terms = JSON.parse(await page.locator('body').innerText({ timeout: remaining() }))
    if (terms.owner !== 'synthetic-fixture' || terms.forbidden.includes(scenario) || !terms.allowed.includes(scenario)) {
      result.reason = 'TERMS_BLOCKED'; return result
    }
    await action('DISPLAY', () => page.goto(fixture.urls[scenario], { timeout: remaining() }))
    if (page.url() !== fixture.urls[scenario]) throw new Error('TARGET_CHANGED')
    const frames = page.frames()
    if (frames.some(frame => frame.url() !== 'about:blank' && !allowed.has(frame.url()))) throw new Error('FOREIGN_FRAME')
    for (const frame of frames) {
      const text = await frame.locator('body').innerText({ timeout: remaining() })
      if (/営業.*お断り|勧誘.*お断り/.test(text)) {
        result.salesAuthorization = 'PROHIBITED'; result.reason = 'SALES_PROHIBITED'; return result
      }
      if (/CAPTCHA/i.test(text) || await frame.locator('.g-recaptcha, .h-captcha, [data-sitekey]').count()) {
        result.operationStatus = 'HUMAN_REQUIRED'; result.reason = 'CAPTCHA'; return result
      }
    }
    const candidates: Frame[] = []
    for (const frame of frames) if (await frame.locator('form').count()) candidates.push(frame)
    if (candidates.length !== 1 || await candidates[0].locator('form').count() !== 1) throw new Error('FORM_AMBIGUOUS')
    const frame = candidates[0]
    result.controls = await controls(frame)
    const structure = await formStructure(frame)
    if (new URL(structure.action).origin !== fixture.origin) throw new Error('UNSAFE_ACTION')
    result.fingerprint = hash({ structure, controls: result.controls, frame: frame.url(), operation: 'browser-preview-poc-v1' })
    // Validate all fields/choices/consents before any fill. Never infer required values.
    const names = new Set<string>()
    for (const field of result.controls) {
      if (['password', 'file'].includes(field.type)) { result.operationStatus = 'HUMAN_REQUIRED'; throw new Error('HUMAN_INPUT_REQUIRED') }
      if (!field.name || (names.has(field.name) && field.type !== 'radio')) throw new Error('FIELD_AMBIGUOUS')
      names.add(field.name)
      if (field.type === 'hidden') continue
      if (field.type === 'checkbox') {
        const choice = proposal.consents[field.name]
        if (!choice || choice.text !== field.label || (field.required && !choice.checked)) {
          result.operationStatus = 'HUMAN_REQUIRED'; throw new Error('CONSENT_REVIEW_REQUIRED')
        }
      } else if (field.tag === 'select' || field.type === 'radio') {
        const value = proposal.selections[field.name]
        const group = result.controls.filter(control => control.name === field.name)
        if (!value || !group.some(control => control.options.some(option => option.value === value))) throw new Error('CHOICE_REVIEW_REQUIRED')
      } else if (field.required && !proposal.values[field.name]) throw new Error('REQUIRED_FIELD_UNKNOWN')
    }
    const filled = new Set<string>()
    for (const field of result.controls) {
      if (field.type === 'hidden' || filled.has(field.name)) continue
      filled.add(field.name)
      // Names come from our immutable fixture, with strict selector escaping.
      if (!/^[a-z]+$/.test(field.name)) throw new Error('FIELD_AMBIGUOUS')
      const locator = frame.locator(`[name="${field.name}"]`)
      if (field.type === 'checkbox') await action('CONSENT_EXPLICIT', () => locator.setChecked(proposal.consents[field.name].checked, { timeout: remaining() }))
      else if (field.tag === 'select') await action('SELECT_EXPLICIT', () => locator.selectOption(proposal.selections[field.name], { timeout: remaining() }))
      else if (field.type === 'radio') {
        const value = proposal.selections[field.name]
        if (!/^[a-z]+$/.test(value)) throw new Error('CHOICE_REVIEW_REQUIRED')
        await action('RADIO_EXPLICIT', () => frame.locator(`[name="${field.name}"][value="${value}"]`).check({ timeout: remaining() }))
      }
      else if (proposal.values[field.name]) await action('FILL', () => locator.fill(proposal.values[field.name], { timeout: remaining() }))
    }
    const currentFingerprint = hash({ structure: await formStructure(frame), controls: await controls(frame), frame: frame.url(), operation: 'browser-preview-poc-v1' })
    if (currentFingerprint !== result.fingerprint) throw new Error('STRUCTURE_CHANGED')
    await action('PREVIEW_ONLY', () => frame.getByRole('button', { name: '入力内容を確認', exact: true }).click({ timeout: remaining() }))
    const error = await frame.getByRole('alert').innerText({ timeout: remaining() })
    if (error || await frame.locator('form :invalid').count()) throw new Error('FORM_VALIDATION_ERROR')
    result.confirmationReached = await frame.getByRole('heading', { name: '確認画面', exact: true }).isVisible()
    const readback = await frame.locator('#readback').evaluate(dl => Object.fromEntries(
      [...dl.querySelectorAll('dt')].map(dt => [dt.textContent, dt.nextElementSibling?.textContent]),
    ))
    const expected = Object.fromEntries([...filled].filter(name => !proposal.consents[name] || proposal.consents[name].checked).map(name => [name,
      proposal.values[name] ?? proposal.selections[name] ?? (proposal.consents[name]?.checked ? 'agree' : ''),
    ]))
    if (!result.confirmationReached || hash(readback) !== hash(expected)) throw new Error('READBACK_MISMATCH')
    if (result.blockedRequests) throw new Error('NETWORK_BLOCKED')
    result.operationStatus = 'BROWSER_VERIFIED'; result.reason = 'FIXTURE_PREVIEW_VERIFIED'
    result.log.push('STOP_BEFORE_FINAL_SEND')
  } catch (error) {
    const known = ['OPERATION_BUDGET', 'TARGET_CHANGED', 'FOREIGN_FRAME', 'FORM_AMBIGUOUS', 'UNSAFE_ACTION',
      'HUMAN_INPUT_REQUIRED', 'FIELD_AMBIGUOUS', 'CONSENT_REVIEW_REQUIRED', 'CHOICE_REVIEW_REQUIRED',
      'REQUIRED_FIELD_UNKNOWN', 'FORM_VALIDATION_ERROR', 'READBACK_MISMATCH', 'NETWORK_BLOCKED', 'STRUCTURE_CHANGED']
    result.reason = error instanceof Error && known.includes(error.message) ? error.message : 'TECHNICAL_UNKNOWN'
    result.log.push(result.reason)
  } finally {
    result.durationMs = Math.round(performance.now() - started)
    await context.close()
  }
  return result
}
