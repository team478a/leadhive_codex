import { test } from '@playwright/test'
import { readFile, stat, writeFile } from 'node:fs/promises'
import { runOfflineInput, type OfflineInput, type CachedResource } from './offline-input'

test('private acquired snapshot input-only trial', async ({ browser }, info) => {
  const path = process.env.LEADHIVE_RENDERED_INPUT_FILE
  if (process.env.LEADHIVE_RENDERED_INPUT !== '1' || !path || (await stat(path)).size > 2_500_000) throw Error('Invalid private snapshot file')
  const file = JSON.parse(await readFile(path, 'utf8'))
  const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)
  if (!record(file) || file.definition !== 'rendered-input-acquisition-v1' || file.status !== 'SNAPSHOT_READY'
    || !record(file.bundle)) throw Error('Not an acquired snapshot')
  const input = file.bundle
  if (typeof input.html !== 'string' || typeof input.expectedHtmlHash !== 'string' || typeof input.sourceUrl !== 'string'
    || !['UNKNOWN', 'ALLOWED', 'PROHIBITED'].includes(String(input.permission))
    || !record(input.values) || !record(input.choices) || !record(input.consents)
    || [...Object.values(input.values), ...Object.values(input.choices)].some(v => typeof v !== 'string')
    || Object.values(input.consents).some(v => !record(v) || typeof v.checked !== 'boolean' || typeof v.label !== 'string')
    || !Array.isArray(input.resources) || input.resources.some(v => !record(v) || typeof v.url !== 'string'
      || typeof v.body !== 'string' || typeof v.sha256 !== 'string' || !['script', 'style'].includes(String(v.kind)))) throw Error('Invalid snapshot schema')
  // No report callback: acquired bundles are not existing cloud approval/handoff tasks.
  const result = await runOfflineInput(browser, input as OfflineInput, false, input.resources as CachedResource[])
  const output = info.outputPath('rendered-input-result.json')
  await writeFile(output, JSON.stringify(result, null, 2), 'utf8')
  await info.attach('rendered-input-result', { path: output, contentType: 'application/json' })
})
