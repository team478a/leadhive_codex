import { test } from '@playwright/test'
import { readFile, stat, writeFile } from 'node:fs/promises'
import { runOfflineInput, type OfflineInput } from './offline-input'

test('private saved HTML input trial', async ({ browser }, info) => {
  const file = process.env.LEADHIVE_OFFLINE_INPUT_FILE
  if (process.env.LEADHIVE_OFFLINE_FORM_INPUT !== '1' || !file) throw Error('Offline runner disabled')
  if ((await stat(file)).size > 1_000_000) throw Error('Input file exceeds budget')
  let input: unknown
  try { input = JSON.parse(await readFile(file, 'utf8')) } catch { throw Error('Invalid input JSON') }
  const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)
  if (!record(input) || typeof input.html !== 'string' || typeof input.expectedHtmlHash !== 'string'
    || typeof input.sourceUrl !== 'string' || !['UNKNOWN', 'ALLOWED', 'PROHIBITED'].includes(String(input.permission))
    || !record(input.values) || !record(input.choices) || !record(input.consents)
    || [...Object.values(input.values), ...Object.values(input.choices)].some(value => typeof value !== 'string')
    || Object.values(input.consents).some(value => !record(value) || typeof value.checked !== 'boolean' || typeof value.label !== 'string')) throw Error('Invalid input file schema')
  const result = await runOfflineInput(browser, input as OfflineInput)
  // Only digests, counts and reason codes. Never attach HTML, values or screenshots.
  const output = info.outputPath('offline-input-result.json')
  await writeFile(output, JSON.stringify(result, null, 2), 'utf8')
  await info.attach('offline-input-result', { path: output, contentType: 'application/json' })
  // A completed diagnostic can be BLOCKED/HUMAN_REQUIRED; it is not a success label.
})
