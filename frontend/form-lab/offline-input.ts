/** Isolated archived-HTML input trial. No live fetch, approval or dispatch. */
import { createHash } from 'node:crypto'
import type { Browser, Frame } from '@playwright/test'

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
  durationMs: number
  executionAllowed: false
  approvalGranted: false
  confirmationReached: false
  liveFetchPerformed: false
  sent: false
}
export const htmlHash = (html: string) => createHash('sha256').update(html, 'utf8').digest('hex')
const digest = (value: unknown) => htmlHash(JSON.stringify(value))
const pairs = (value: Record<string, unknown>) => Object.entries(value).sort(([a], [b]) => a.localeCompare(b))

async function inspect(frame: Frame) {
  return frame.locator('form').evaluate(form => ({
    action: form.getAttribute('action'), method: form.getAttribute('method'),
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

export async function runOfflineInput(browser: Browser, input: OfflineInput, mobile = false): Promise<OfflineResult> {
  input = structuredClone(input)
  const started = performance.now()
  const result: OfflineResult = { definition: 'offline-form-input-v1', status: 'TECHNICAL_UNKNOWN', reason: 'NOT_CHECKED',
    htmlHash: htmlHash(input.html), payloadHash: digest({ sourceUrl: input.sourceUrl, htmlHash: input.expectedHtmlHash,
      values: pairs(input.values), choices: pairs(input.choices), consents: pairs(input.consents) }),
    structureHash: null, fieldsFilled: 0, actions: 0, blockedRequests: 0, durationMs: 0,
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
  if (Object.keys(input.values).length + Object.keys(input.choices).length + Object.keys(input.consents).length > 100
    || Buffer.byteLength(JSON.stringify([input.values, input.choices, input.consents])) > 40_000) return stop('INPUT_BUDGET')
  const context = await browser.newContext({ serviceWorkers: 'block', acceptDownloads: false,
    viewport: mobile ? { width: 390, height: 844 } : { width: 1280, height: 800 } })
  const remaining = () => Math.max(1, 10_000 - (performance.now() - started))
  // Abort all requests including GET resources and autosave. Do not fetch even robots.txt.
  await context.route('**/*', async route => { result.blockedRequests++; await route.abort('blockedbyclient') })
  await context.routeWebSocket('**/*', socket => { result.blockedRequests++; socket.close() })
  context.on('page', page => {
    page.on('download', download => { result.blockedRequests++; void download.cancel() })
    page.on('popup', popup => { result.blockedRequests++; void popup.close() })
  })
  const timer = setTimeout(() => { void context.close().catch(() => {}) }, 10_000)
  const action = async (execute: () => Promise<unknown>) => {
    if (performance.now() - started >= 10_000 || result.actions >= 100) throw new Error('OPERATION_BUDGET')
    result.actions++; await execute()
  }
  try {
    const page = await context.newPage()
    await action(() => page.setContent(input.html, { waitUntil: 'load', timeout: remaining() }))
    if (page.url() !== 'about:blank') return stop('NAVIGATION_CHANGED')
    const frames = page.frames()
    if (frames.some(frame => !['about:blank', 'about:srcdoc'].includes(frame.url()))) return stop('EXTERNAL_FRAME')
    for (const frame of frames) {
      const text = await frame.locator('body').innerText({ timeout: remaining() })
      if (/営業.*(?:お断り|禁止)|勧誘.*(?:お断り|禁止)/.test(text)) return stop('SALES_PROHIBITED', 'BLOCKED')
      if (/CAPTCHA/i.test(text) || await frame.locator('.g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey]').count()) return stop('CAPTCHA', 'HUMAN_REQUIRED')
    }
    if (result.blockedRequests) return stop('NETWORK_REQUIRED')
    const candidates: Frame[] = []
    for (const frame of frames) if (await frame.locator('form').count()) candidates.push(frame)
    if (candidates.length !== 1 || await candidates[0].locator('form').count() !== 1) return stop('FORM_AMBIGUOUS')
    const frame = candidates[0]
    const structure = await inspect(frame)
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
      const locator = frame.locator('form input, form textarea, form select').nth(index)
      if (field.type === 'checkbox') await action(() => locator.setChecked(input.consents[field.name].checked, { timeout: remaining() }))
      else if (field.tag === 'select') await action(() => locator.selectOption(input.choices[field.name], { timeout: remaining() }))
      else if (field.type === 'radio') {
        if (field.options[0] !== input.choices[field.name]) continue
        await action(() => locator.check({ timeout: remaining() }))
      } else if (Object.hasOwn(input.values, field.name)) await action(() => locator.fill(input.values[field.name], { timeout: remaining() }))
      else continue
      result.fieldsFilled++
      if (page.url() !== 'about:blank') return stop('NAVIGATION_CHANGED')
      if (result.blockedRequests) return stop('NETWORK_REQUIRED')
      if (digest(await inspect(frame)) !== result.structureHash) return stop('STRUCTURE_CHANGED')
    }
    const readback = await frame.locator('form').evaluate(form => ({
      valid: (form as HTMLFormElement).checkValidity(),
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
      : performance.now() - started >= 10_000 ? 'TIMEOUT' : 'INPUT_OPERATION_FAILED')
  } finally { clearTimeout(timer); result.durationMs = Math.round(performance.now() - started); await context.close().catch(() => {}) }
}
