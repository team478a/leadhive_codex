/** Isolated input trial. Default: archived HTML. Optional bounded GET loader; never dispatch. */
import { createHash } from 'node:crypto'
import type { Browser, Locator } from '@playwright/test'

export type OfflineInput = {
  html: string
  expectedHtmlHash: string
  sourceUrl: string
  permission: 'UNKNOWN' | 'PROHIBITED' | 'ALLOWED'
  values: Record<string, string>
  choices: Record<string, string>
  consents: Record<string, { checked: boolean; label: string }>
}
type Control = { name: string; tag: string; type: string; required: boolean; disabled: boolean; label: string; options: string[] }
export type OfflineResult = {
  definition: 'offline-form-input-v1'
  status: 'OFFLINE_INPUT_VERIFIED' | 'HUMAN_REQUIRED' | 'BLOCKED' | 'TECHNICAL_UNKNOWN'
  reason: string
  htmlHash: string
  payloadHash: string
  structureHash: string | null
  fieldsFilled: number
  actions: number
  blockedRequests: number
  omittedDecorativeRequests: number
  durationMs: number
  executionAllowed: false
  approvalGranted: false
  confirmationReached: false
  liveFetchPerformed: false
  sent: false
}
export const htmlHash = (html: string) => createHash('sha256').update(html, 'utf8').digest('hex')
export type CachedResource = { url: string; kind: 'script' | 'style'; body: string; sha256: string }
export type LiveLoader = { fetch: (url: string, kind: 'script' | 'stylesheet') => Promise<{ body: string; contentType: string }>; beforeInput: () => Promise<void> }
const digest = (value: unknown) => htmlHash(JSON.stringify(value))
const pairs = (value: Record<string, unknown>) => Object.entries(value).sort(([a], [b]) => a.localeCompare(b))

// Omit the documented font-only endpoint locally; never fetch or trust its CSS.
// Arbitrary stylesheets, lookalike hosts, scripts, frames and data still stop.
export function decorativeFontStylesheet(value: string): boolean {
  if (value.length > 2048) return false
  try {
    const url = new URL(value)
    if (url.protocol !== 'https:' || url.hostname !== 'fonts.googleapis.com' || url.port
      || url.username || url.password || url.hash || !['/css', '/css2'].includes(url.pathname)) return false
    const families = url.searchParams.getAll('family')
    if (!families.length || families.some(f => !/^[a-z0-9 :;,@._+|\-[\]]{1,300}$/i.test(f))) return false
    if ([...url.searchParams.keys()].some(key => !['family', 'display'].includes(key))) return false
    const display = url.searchParams.getAll('display')
    return display.length <= 1 && display.every(v => ['auto', 'block', 'swap', 'fallback', 'optional'].includes(v))
  } catch { return false }
}

async function inspect(scope: Locator) {
  return scope.evaluate(form => ({
    tag: form.tagName, id: form.id,
    action: form.getAttribute('action'), method: form.getAttribute('method'),
    buttons: [...form.querySelectorAll('button, input[type=submit]')].map(node => ({
      text: node.textContent, type: node.getAttribute('type'), disabled: node.matches(':disabled'),
    })),
    controls: [...form.querySelectorAll('input, textarea, select')].map(node => {
      const field = node as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
      return { name: field.name, tag: field.tagName.toLowerCase(), type: field.type,
        required: field.required, disabled: field.disabled || field.matches(':disabled'),
        label: [...(field.labels || [])].map(label => label.textContent?.trim() || '').join(' '),
        options: field instanceof HTMLSelectElement ? [...field.options].filter(option => !option.disabled && !option.parentElement?.matches('optgroup:disabled')).map(option => option.value)
          : ['checkbox', 'radio'].includes(field.type) ? [field.value] : [] }
    }),
  }))
}

// A custom contact container is an input candidate, never an executable form.
const customSelector = 'div, section, fieldset, [role="form"]'
async function customCandidates(scopes: Locator): Promise<number[]> {
  return scopes.evaluateAll(nodes => {
    const candidates = nodes.filter(node => {
      if (node.closest('form') || node.querySelector('form')) return false
      if (node.getAttribute('role') !== 'form'
        && !/contact|inquiry|inquiries|問い合わせ|問合せ/i.test(node.id + ' ' + (node.getAttribute('aria-label') || ''))) return false
      for (let ancestor: Element | null = node; ancestor; ancestor = ancestor.parentElement) {
        const style = getComputedStyle(ancestor)
        if (ancestor.hasAttribute('hidden') || ancestor.getAttribute('aria-hidden') === 'true'
          || style.display === 'none' || style.visibility === 'hidden') return false
      }
      const controls = [...node.querySelectorAll('input, textarea, select')] as HTMLInputElement[]
      if (!controls.length || controls.length > 100 || controls.some(field => field.hasAttribute('form')
        || ['password', 'search'].includes(field.type) || !field.name)) return false
      if (new Set(controls.map(field => field.name)).size !== controls.length) return false
      return controls.some(field => field.type === 'email' && !field.matches(':disabled'))
        && controls.some(field => field.tagName === 'TEXTAREA' && !field.matches(':disabled'))
        && [...node.querySelectorAll('button, input[type=submit]')].some(button => !button.matches(':disabled')
          && /送信|確認|send|submit|confirm/i.test(button.textContent || button.getAttribute('value') || ''))
    })
    if (candidates.length > 32) return []
    return candidates.filter(node => !candidates.some(child => child !== node && node.contains(child)))
      .map(node => nodes.indexOf(node))
  })
}

export async function runOfflineInput(browser: Browser, input: OfflineInput, mobile = false,
  resources?: CachedResource[], live?: LiveLoader): Promise<OfflineResult> {
  input = structuredClone(input)
  resources = resources === undefined ? undefined : structuredClone(resources)
  const started = performance.now()
  const maxMs = live ? 60_000 : 10_000
  const result: OfflineResult = { definition: 'offline-form-input-v1', status: 'TECHNICAL_UNKNOWN', reason: 'NOT_CHECKED',
    htmlHash: htmlHash(input.html), payloadHash: digest({ sourceUrl: input.sourceUrl, htmlHash: input.expectedHtmlHash,
      values: pairs(input.values), choices: pairs(input.choices), consents: pairs(input.consents),
      ...(resources ? { rendering: 'cached-resources-v2-font-omission', resources: resources.map(r => [r.url, r.kind, r.sha256]).sort() } : {}) }),
    structureHash: null, fieldsFilled: 0, actions: 0, blockedRequests: 0, omittedDecorativeRequests: 0, durationMs: 0,
    executionAllowed: false, approvalGranted: false, confirmationReached: false, liveFetchPerformed: false, sent: false }
  const stop = (reason: string, status: OfflineResult['status'] = 'TECHNICAL_UNKNOWN') => {
    result.reason = reason; result.status = status; result.durationMs = Math.round(performance.now() - started); return result
  }
  let source: URL
  try { source = new URL(input.sourceUrl) } catch { return stop('INVALID_SOURCE') }
  if (!['http:', 'https:'].includes(source.protocol) || source.username || source.password) return stop('INVALID_SOURCE')
  if (!['UNKNOWN', 'PROHIBITED', 'ALLOWED'].includes(input.permission)) return stop('INVALID_PERMISSION')
  if (input.permission === 'PROHIBITED') return stop('SALES_PROHIBITED', 'BLOCKED')
  if (Buffer.byteLength(input.html) > 500_000 || result.htmlHash !== input.expectedHtmlHash) return stop('SNAPSHOT_INVALID')
  const cache = new Map<string, CachedResource>()
  if (resources) {
    if (source.protocol !== 'https:' || resources.length > 8) return stop('RESOURCE_SNAPSHOT_INVALID')
    let size = Buffer.byteLength(input.html)
    for (const resource of resources) {
      let url: URL
      try { url = new URL(resource.url) } catch { return stop('RESOURCE_SNAPSHOT_INVALID') }
      if (url.origin !== source.origin || url.username || url.password || url.hash || resource.url === source.href
        || cache.has(resource.url) || !['script', 'style'].includes(resource.kind)
        || Buffer.byteLength(resource.body) > 500_000 || htmlHash(resource.body) !== resource.sha256) return stop('RESOURCE_SNAPSHOT_INVALID')
      size += Buffer.byteLength(resource.body)
      if (size > 2_000_000) return stop('RESOURCE_SNAPSHOT_INVALID')
      cache.set(resource.url, resource)
    }
  }
  if (Object.keys(input.values).length + Object.keys(input.choices).length + Object.keys(input.consents).length > 100
    || Buffer.byteLength(JSON.stringify([input.values, input.choices, input.consents])) > 40_000) return stop('INPUT_BUDGET')
  const context = await browser.newContext({ serviceWorkers: 'block', acceptDownloads: false,
    viewport: mobile ? { width: 390, height: 844 } : { width: 1280, height: 800 } })
  if (resources) {
    await context.exposeBinding('__leadhiveBlockedOperation', () => { result.blockedRequests++ })
    await context.addInitScript(() => {
      const blocked = () => { void (window as unknown as Record<string, () => Promise<void>>).__leadhiveBlockedOperation() }
      // Prevent implicit navigation as well as blocking its eventual HTTP request.
      for (const name of ['submit', 'requestSubmit']) Object.defineProperty(HTMLFormElement.prototype, name,
        { configurable: false, writable: false, value: blocked })
      document.addEventListener('submit', event => { event.preventDefault(); blocked() }, true)
      // These transports/workers are outside the intended HTML form operation.
      for (const name of ['RTCPeerConnection', 'webkitRTCPeerConnection', 'WebTransport', 'Worker', 'SharedWorker']) {
        Object.defineProperty(window, name, { configurable: false, writable: false,
          value: function () { blocked(); throw Error('Unsupported browser transport') } })
      }
    })
  }
  const remaining = () => Math.max(1, maxMs - (performance.now() - started))
  let frozen = false
  let served = 0
  // Default rendering uses hash-checked snapshots; the explicit live loader alone may perform bounded GET. Never route.fetch.
  await context.route('**/*', async route => {
    const request = route.request()
    if (resources && !frozen && request.method() === 'GET' && ++served <= (live ? 100 : 20)) {
      if (request.url() === source.href && request.resourceType() === 'document') {
        await route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: input.html }); return
      }
      if (request.resourceType() === 'stylesheet' && decorativeFontStylesheet(request.url())) {
        result.omittedDecorativeRequests++
        await route.fulfill({ status: 200, contentType: 'text/css', body: '' }); return
      }
      const asset = cache.get(request.url())
      if (asset && request.resourceType() === (asset.kind === 'script' ? 'script' : 'stylesheet')) {
        await route.fulfill({ status: 200, contentType: asset.kind === 'script' ? 'application/javascript; charset=utf-8' : 'text/css; charset=utf-8', body: asset.body }); return
      }
      if (live && ['script', 'stylesheet'].includes(request.resourceType()) && new URL(request.url()).origin === source.origin) {
        try {
          const response = await live.fetch(request.url(), request.resourceType() as 'script' | 'stylesheet')
          if (frozen) { result.blockedRequests++; await route.abort('blockedbyclient'); return }
          await route.fulfill({ status: 200, contentType: response.contentType, body: response.body }); return
        } catch { result.blockedRequests++; await route.abort('failed'); return }
      }
      // Decorative content is omitted, not fetched; unknown scripts/data/frames stop.
      if (['image', 'font', 'media'].includes(request.resourceType())) { result.omittedDecorativeRequests++; await route.abort('blockedbyclient'); return }
    }
    result.blockedRequests++; await route.abort('blockedbyclient')
  })
  await context.routeWebSocket('**/*', socket => { result.blockedRequests++; socket.close() })
  context.on('page', page => {
    page.on('download', download => { result.blockedRequests++; void download.cancel() })
    page.on('popup', popup => { result.blockedRequests++; void popup.close() })
  })
  const timer = setTimeout(() => { void context.close().catch(() => {}) }, maxMs)
  const action = async (execute: () => Promise<unknown>) => {
    if (performance.now() - started >= maxMs || result.actions >= 100) throw new Error('OPERATION_BUDGET')
    result.actions++; await execute()
  }
  try {
    const page = await context.newPage()
    await action(() => resources
      ? page.goto(source.href, { waitUntil: 'load', timeout: remaining() })
      : page.setContent(input.html, { waitUntil: 'load', timeout: remaining() }))
    frozen = true
    const expectedUrl = resources ? source.href : 'about:blank'
    if (page.url() !== expectedUrl) return stop('NAVIGATION_CHANGED')
    const frames = page.frames()
    if (frames.some(frame => !['about:blank', 'about:srcdoc', expectedUrl].includes(frame.url()))) return stop('EXTERNAL_FRAME')
    for (const frame of frames) {
      const text = await frame.locator('body').innerText({ timeout: remaining() })
      if (/(?:営業|勧誘)[^。\n]{0,80}(?:お断り|禁止|ご遠慮)/.test(text.normalize('NFKC'))) return stop('SALES_PROHIBITED', 'BLOCKED')
      if (/CAPTCHA/i.test(text) || await frame.locator('.g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey]').count()) return stop('CAPTCHA', 'HUMAN_REQUIRED')
    }
    if (result.blockedRequests) return stop('NETWORK_REQUIRED')
    if (live) await live.beforeInput()
    const candidates: Locator[] = []
    for (const frame of frames) {
      const forms = frame.locator('form')
      for (let index = 0; index < await forms.count(); index++) candidates.push(forms.nth(index))
    }
    if (!candidates.length) for (const frame of frames) {
      const scopes = frame.locator(customSelector)
      for (const index of await customCandidates(scopes)) candidates.push(scopes.nth(index))
    }
    if (candidates.length !== 1) return stop('FORM_AMBIGUOUS')
    const scope = candidates[0]
    const structure = await inspect(scope)
    const controls: Control[] = structure.controls
    if (!controls.length || controls.length > 100) return stop('FIELD_BUDGET')
    result.structureHash = digest(structure)
    const groups = new Map<string, Control[]>()
    for (const control of controls) {
      if (['hidden', 'submit', 'button', 'reset', 'image'].includes(control.type)) continue
      if (['file', 'password'].includes(control.type)) return stop('SENSITIVE_FIELD', 'HUMAN_REQUIRED')
      if (!control.name) return stop('FIELD_AMBIGUOUS')
      groups.set(control.name, [...(groups.get(control.name) || []), control])
    }
    for (const key of [...Object.keys(input.values), ...Object.keys(input.choices), ...Object.keys(input.consents)]) {
      if (!groups.has(key)) return stop('UNKNOWN_INPUT_FIELD')
    }
    for (const [name, group] of groups) {
      const field = group[0]
      if (group.length > 1 && !group.every(control => control.type === 'radio')) return stop('FIELD_AMBIGUOUS')
      if (field.disabled) {
        if (Object.hasOwn(input.values, name) || Object.hasOwn(input.choices, name) || Object.hasOwn(input.consents, name)) return stop('DISABLED_FIELD')
        continue
      }
      const sources = [Object.hasOwn(input.values, name), Object.hasOwn(input.choices, name), Object.hasOwn(input.consents, name)].filter(Boolean).length
      if (sources > 1) return stop('FIELD_AMBIGUOUS')
      if (field.type === 'checkbox') {
        const consent = input.consents[name]
        if (!consent || consent.label !== field.label || field.required && !consent.checked) return stop('CONSENT_REVIEW_REQUIRED', 'HUMAN_REQUIRED')
      } else if (field.tag === 'select' || field.type === 'radio') {
        if (!Object.hasOwn(input.choices, name) || !group.some(control => !control.disabled && control.options.includes(input.choices[name]))
          || group.some(control => control.required) && !input.choices[name]) return stop('CHOICE_REVIEW_REQUIRED', 'HUMAN_REQUIRED')
      } else if (!['text', 'email', 'tel', 'url', 'textarea', 'search', 'number'].includes(field.type)) return stop('UNSUPPORTED_FIELD', 'HUMAN_REQUIRED')
      else if (field.required && !input.values[name]?.trim()) return stop('REQUIRED_FIELD_UNKNOWN', 'HUMAN_REQUIRED')
    }
    for (const [index, field] of controls.entries()) {
      if (['hidden', 'submit', 'button', 'reset', 'image'].includes(field.type) || field.disabled) continue
      const locator = scope.locator('input, textarea, select').nth(index)
      if (field.type === 'checkbox') await action(() => locator.setChecked(input.consents[field.name].checked, { timeout: remaining() }))
      else if (field.tag === 'select') await action(() => locator.selectOption(input.choices[field.name], { timeout: remaining() }))
      else if (field.type === 'radio') {
        if (field.options[0] !== input.choices[field.name]) continue
        await action(() => locator.check({ timeout: remaining() }))
      } else if (Object.hasOwn(input.values, field.name)) await action(() => locator.fill(input.values[field.name], { timeout: remaining() }))
      else continue
      result.fieldsFilled++
      if (page.url() !== expectedUrl) return stop('NAVIGATION_CHANGED')
      if (result.blockedRequests) return stop('NETWORK_REQUIRED')
      for (const current of page.frames()) {
        if (!['about:blank', 'about:srcdoc', expectedUrl].includes(current.url())) return stop('EXTERNAL_FRAME')
        const text = await current.locator('body').innerText({ timeout: remaining() })
        if (/(?:営業|勧誘)[^。\n]{0,80}(?:お断り|禁止|ご遠慮)/.test(text.normalize('NFKC'))) return stop('SALES_PROHIBITED', 'BLOCKED')
        if (/CAPTCHA/i.test(text) || await current.locator('.g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey]').count()) return stop('CAPTCHA', 'HUMAN_REQUIRED')
      }
      if (digest(await inspect(scope)) !== result.structureHash) return stop('STRUCTURE_CHANGED')
    }
    const readback = await scope.evaluate(form => ({
      valid: form instanceof HTMLFormElement ? form.checkValidity() : [...form.querySelectorAll('input, textarea, select')].every(node =>
        (node as HTMLInputElement).checkValidity()),
      values: [...form.querySelectorAll('input, textarea, select')].map(node => {
        const field = node as HTMLInputElement
        return { name: field.name, type: field.type, value: field.value, checked: field.checked, disabled: field.matches(':disabled') }
      }),
    }))
    if (!readback.valid) return stop('FORM_VALIDATION_ERROR')
    for (const field of readback.values.filter(field => !field.disabled)) {
      if (Object.hasOwn(input.values, field.name) && field.value !== input.values[field.name]
        || Object.hasOwn(input.choices, field.name) && (field.type !== 'radio' ? field.value !== input.choices[field.name] : field.checked !== (field.value === input.choices[field.name]))
        || Object.hasOwn(input.consents, field.name) && field.checked !== input.consents[field.name].checked) return stop('READBACK_MISMATCH')
    }
    if (result.blockedRequests) return stop('NETWORK_REQUIRED')
    if (!result.fieldsFilled) return stop('NO_INPUT_PERFORMED')
    return stop('STOP_BEFORE_CONFIRMATION_OR_SEND', 'OFFLINE_INPUT_VERIFIED')
  } catch (error) {
    return stop(error instanceof Error && error.message === 'OPERATION_BUDGET' ? 'OPERATION_BUDGET'
      : performance.now() - started >= maxMs ? 'TIMEOUT' : 'INPUT_OPERATION_FAILED')
  } finally { clearTimeout(timer); result.durationMs = Math.round(performance.now() - started); await context.close().catch(() => {}) }
}
