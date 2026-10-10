import { test, expect } from '@playwright/test'
import { bindInput, sanitizeReport, sha, validateTask } from '../src/offlineHandoffContract'
import { runOfflineInput } from './offline-input'
import { writeFile } from 'node:fs/promises'
test('handoff binds company, snapshot and inputs, without granting permission', async ({ browser }, info) => {
  const html = '<form><input name="name" required><button>Send</button></form>'
  const task = await bindInput({ html, expectedHtmlHash: await sha(html), sourceUrl: 'https://synthetic.example', permission: 'ALLOWED', values: { name: 'synthetic' }, choices: {}, consents: {} }, 'company-a', 'project-a', false)
  const validated = await validateTask(task)
  await writeFile(info.outputPath('synthetic-handoff.json'), JSON.stringify(task), 'utf8')
  expect(task.input.permission).toBe('UNKNOWN')
  const result = await runOfflineInput(browser, validated.input as Parameters<typeof runOfflineInput>[1])
  const report = { definition: 'offline-input-report-v1', binding: task.binding, result }
  expect(sanitizeReport(report, task.binding)).toMatchObject({ source: 'PC_REPORTED_UNVERIFIED', sent: false, status: 'OFFLINE_INPUT_VERIFIED' })
  expect(() => sanitizeReport(report, { ...task.binding, companyId: 'other' })).toThrow()
  expect(() => sanitizeReport(report, { ...task.binding, requestHash: 'other' })).toThrow()
  expect(() => sanitizeReport({ ...report, result: { ...result, sent: true } }, task.binding)).toThrow()
  expect(() => sanitizeReport({ ...report, result: { ...result, reason: 'secret body' } }, task.binding)).toThrow()
  await expect(validateTask({ ...task, input: { ...task.input, values: { name: 'changed' } } })).rejects.toThrow()
  const blocked = await bindInput({ ...task.input }, 'company-a', 'project-a', true)
  expect(blocked.input.permission).toBe('PROHIBITED')
  expect(JSON.stringify(sanitizeReport(report, task.binding))).not.toContain('synthetic')
})
