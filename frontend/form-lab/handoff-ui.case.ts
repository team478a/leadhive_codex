import { test, expect, type Page } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { sha } from '../src/offlineHandoffContract'
async function mount(page: Page, readOnly = false, prohibited = false) {
  await page.route('**/harness', route => route.fulfill({ contentType: 'text/html', body: '<script type="module">import RefreshRuntime from "/@react-refresh"; RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type; window.__vite_plugin_react_preamble_installed__=true;</script><div id="trial-root"></div>' }))
  await page.goto('/harness')
  await page.evaluate(async ({ readOnly, prohibited }) => {
    const reactPath = '/node_modules/.vite/deps/react.js'; const domPath = '/node_modules/.vite/deps/react-dom_client.js'; const componentPath = '/src/OfflineInputHandoff.tsx'
    const React = (await import(reactPath)).default; const { createRoot } = (await import(domPath)).default; const { OfflineInputHandoff } = await import(componentPath)
    const state = window as unknown as { saved: string[] }; state.saved = []
    createRoot(document.getElementById('trial-root')).render(React.createElement(OfflineInputHandoff, { company: { id: 'company-a', project_id: 'project-a' }, activities: [], readOnly, busy: false, prohibited,
      onSave: async (note: string) => { state.saved.push(note); return true } }))
  }, { readOnly, prohibited })
}
test('company handoff downloads private inputs, validates report and records only metadata', async ({ page }) => {
  await mount(page)
  const html = '<form><input name="name"></form>'
  const input = { html, expectedHtmlHash: await sha(html), sourceUrl: 'https://synthetic.example', permission: 'UNKNOWN', values: { name: 'private fixture' }, choices: {}, consents: {} }
  const download = page.waitForEvent('download')
  await page.getByLabel('保存HTMLの入力JSON').setInputFiles({ name: 'input.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(input)) })
  const task = JSON.parse(await readFile((await (await download).path())!, 'utf8'))
  const result = { definition: 'offline-form-input-v1', htmlHash: input.expectedHtmlHash, status: 'HUMAN_REQUIRED', reason: 'CAPTCHA', fieldsFilled: 0, actions: 1, blockedRequests: 0, durationMs: 10, executionAllowed: false, approvalGranted: false, confirmationReached: false, liveFetchPerformed: false, sent: false }
  const report = { definition: 'offline-input-report-v1', binding: task.binding, result }
  await page.getByLabel('PC入力試行の結果JSON').setInputFiles({ name: 'wrong.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify({ ...report, binding: { ...task.binding, companyId: 'other' } })) })
  await expect(page.getByRole('status')).toContainText('一致しません')
  await page.getByLabel('PC入力試行の結果JSON').setInputFiles({ name: 'result.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(report)) })
  await expect(page.getByRole('status')).toContainText('未認証')
  const saved = await page.evaluate(() => (window as unknown as { saved: string[] }).saved)
  expect(saved).toHaveLength(1); expect(saved[0]).toContain('PC_REPORTED_UNVERIFIED'); expect(saved[0]).not.toContain('private fixture'); expect(saved[0]).not.toContain('synthetic.example')
  await expect(page.getByLabel('PC入力試行の結果JSON')).toHaveCount(0)
})
test('viewer cannot prepare and sales NG is bound into the PC task', async ({ page }) => {
  await mount(page, true)
  await expect(page.getByText('所有者・編集者が依頼作成と記録を行います。')).toBeVisible()
  await expect(page.locator('input[type=file]')).toHaveCount(0)
  await mount(page, false, true)
  await expect(page.getByText('営業NGです。依頼もBLOCKEDとなり、入力は行いません。')).toBeVisible()
  const html = '<form><input name="name"></form>'
  const download = page.waitForEvent('download')
  await page.getByLabel('保存HTMLの入力JSON').setInputFiles({ name: 'input.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify({ html, expectedHtmlHash: await sha(html), sourceUrl: 'https://synthetic.example', permission: 'ALLOWED', values: {}, choices: {}, consents: {} })) })
  const task = JSON.parse(await readFile((await (await download).path())!, 'utf8'))
  expect(task.input.permission).toBe('PROHIBITED')
})
