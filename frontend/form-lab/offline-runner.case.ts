import { test } from '@playwright/test'
import { readFile, stat, writeFile } from 'node:fs/promises'
import { runOfflineInput, type OfflineInput } from './offline-input'
import { validateTask } from '../src/offlineHandoffContract'
import { transferReport } from './report-transfer'

test('private saved HTML input trial', async ({ browser }, info) => {
  const file = process.env.LEADHIVE_OFFLINE_INPUT_FILE
  if (process.env.LEADHIVE_OFFLINE_FORM_INPUT !== '1' || !file) throw Error('Offline runner disabled')
  if ((await stat(file)).size > 1_000_000) throw Error('Input file exceeds budget')
  let input: unknown
  try { input = JSON.parse(await readFile(file, 'utf8')) } catch { throw Error('Invalid input JSON') }
  const transfer = typeof input === 'object' && input !== null && 'transfer' in input ? input.transfer : undefined
  const handoff = typeof input === 'object' && input !== null && 'definition' in input
    ? await validateTask(input) : null
  if (handoff) input = handoff.input
  const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)
  if (!record(input) || typeof input.html !== 'string' || typeof input.expectedHtmlHash !== 'string'
    || typeof input.sourceUrl !== 'string' || !['UNKNOWN', 'ALLOWED', 'PROHIBITED'].includes(String(input.permission))
    || !record(input.values) || !record(input.choices) || !record(input.consents)
    || [...Object.values(input.values), ...Object.values(input.choices)].some(value => typeof value !== 'string')
    || Object.values(input.consents).some(value => !record(value) || typeof value.checked !== 'boolean' || typeof value.label !== 'string')) throw Error('Invalid input file schema')
  const result = await runOfflineInput(browser, input as OfflineInput)
  // Only digests, counts and reason codes. Never attach HTML, values or screenshots.
  const output = info.outputPath('offline-input-result.json')
  await writeFile(output, JSON.stringify(handoff ? { definition: 'offline-input-report-v1', binding: handoff.binding, result } : result, null, 2), 'utf8')
  if (handoff) {
    const report = { definition: 'offline-input-report-v1', binding: handoff.binding, result }
    const transferStatus = await transferReport(transfer, report,
      process.env.LEADHIVE_OFFLINE_REPORT_ORIGIN, process.env.LEADHIVE_OFFLINE_REPORT_LOOPBACK === '1')
    await writeFile(info.outputPath('transfer-status.json'), JSON.stringify({ transferStatus }), 'utf8')
    console.log(`Diagnostic report transfer: ${transferStatus}`)
  }
  await info.attach('offline-input-result', { path: output, contentType: 'application/json' })
  // A completed diagnostic can be BLOCKED/HUMAN_REQUIRED; it is not a success label.
})
