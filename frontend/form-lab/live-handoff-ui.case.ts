import { test, expect, type Page } from '@playwright/test'
import { readFile } from 'node:fs/promises'

const companyId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const projectId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
const trialId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
async function mount(page: Page, readOnly = false, prohibited = false, restore = false) {
  await page.route('**/harness', r => r.fulfill({ contentType: 'text/html', body: '<script type="module">import R from "/@react-refresh"; R.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type; window.__vite_plugin_react_preamble_installed__=true;</script><div id="root"></div>' }))
  await page.goto('/harness')
  await page.evaluate(async ({ companyId, projectId, trialId, readOnly, prohibited, restore }) => {
    const rp = '/node_modules/.vite/deps/react.js', dp = '/node_modules/.vite/deps/react-dom_client.js', cp = '/src/LiveInputHandoff.tsx'
    const React = (await import(rp)).default; const { createRoot } = (await import(dp)).default; const { LiveInputHandoff } = await import(cp)
    const state = window as unknown as { saved: string[] }; state.saved = []
    const field = { required: true, label: '会社名', recommended_value: 'private fixture', options: [] }
    createRoot(document.getElementById('root')).render(React.createElement(LiveInputHandoff, {
      company: { id: companyId, project_id: projectId }, readOnly, prohibited,
      activities: restore ? [{ id: trialId, company_id: companyId, created_at: new Date().toISOString(), note: '実ページ入力専用依頼 v1: ' + JSON.stringify({ project_id: projectId, request_hash: 'b'.repeat(64), state: 'INPUT_STARTED' }) }] : [],
      profiles: [{ id: 'profile', company_id: companyId, is_primary: true, form_url: 'https://synthetic.example/contact', fields: [
        { ...field, id: 'name', name: 'name', field_type: 'text' },
        { ...field, id: 'purpose', name: 'purpose', label: '用途', field_type: 'select', options: [{ value: 'business', label: '事業相談' }] },
        { ...field, id: 'consent', name: 'consent', label: '同意文言', field_type: 'checkbox' },
      ] }], onSave: async (note: string) => { state.saved.push(note); return true },
    }))
  }, { companyId, projectId, trialId, readOnly, prohibited, restore })
}

test('live handoff requires explicit review, downloads private task and records metadata only', async ({ page }) => {
  await mount(page)
  await expect(page.getByRole('button', { name: 'PC入力専用の依頼を保存' })).toBeDisabled()
  await expect(page.getByLabel('用途（必須）')).toHaveValue('')
  await expect(page.getByRole('checkbox', { name: /同意内容/ })).not.toBeChecked()
  let issued = false
  await page.route(`**/api/companies/${companyId}/live-input-trials`, async route => {
    issued = true
    const input = route.request().postDataJSON()
    expect(input.choices.purpose).toBe('business')
    expect(input.consents.consent.checked).toBe(true)
    expect(input).not.toHaveProperty('confirmed')
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ definition: 'live-input-task-v1', trialId, companyId, projectId,
      input, token: 'lh_input_' + 'a'.repeat(64), requestHash: 'b'.repeat(64), expiresAt: new Date(Date.now() + 900000).toISOString() }) })
  })
  await page.getByLabel('用途（必須）').selectOption('business')
  await page.getByRole('checkbox', { name: /同意内容/ }).check()
  await page.getByRole('checkbox', { name: /宛先・入力内容/ }).check()
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'PC入力専用の依頼を保存' }).click()
  const task = JSON.parse(await readFile((await (await download).path())!, 'utf8'))
  expect(issued).toBe(true); expect(task.input.values.name).toBe('private fixture')
  const report = { definition: 'live-form-input-only-v1', trialId, companyId, projectId, requestHash: task.requestHash,
    status: 'LIVE_INPUT_VERIFIED', reason: 'STOP_BEFORE_CONFIRMATION_OR_SEND', fieldsFilled: 3, blockedRequests: 0,
    sent: false, executionAllowed: false, approvalGranted: false, confirmationReached: false }
  const file = page.getByLabel('PCの未送信結果JSON')
  await file.setInputFiles({ name: 'wrong.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify({ ...report, sent: true })) })
  await expect(page.getByRole('status')).toContainText('対応する未送信')
  await file.setInputFiles({ name: 'result.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(report)) })
  await expect(page.getByRole('status')).toContainText('未送信のPC報告を記録')
  const saved = await page.evaluate(() => (window as unknown as { saved: string[] }).saved)
  expect(saved).toHaveLength(1); expect(saved[0]).toContain('PC_REPORTED_UNVERIFIED')
  expect(saved[0]).not.toContain('private fixture'); expect(saved[0]).not.toContain(task.token)
})

test('viewer and sales NG cannot issue live input tasks', async ({ page }) => {
  await mount(page, true)
  await expect(page.getByRole('button', { name: 'PC入力専用の依頼を保存' })).toHaveCount(0)
  await mount(page, false, true)
  await expect(page.getByText('営業NG・連絡禁止のため入力依頼を作成できません。')).toBeVisible()
  await expect(page.getByRole('button', { name: 'PC入力専用の依頼を保存' })).toBeDisabled()
})

test('reopened company accepts its existing input report without retaining ticket secrets', async ({ page }) => {
  await mount(page, false, false, true)
  const report = { definition: 'live-form-input-only-v1', trialId, companyId, projectId, requestHash: 'b'.repeat(64), status: 'TECHNICAL_UNKNOWN',
    reason: 'NETWORK_REQUIRED', fieldsFilled: 0, sent: false, executionAllowed: false, approvalGranted: false, confirmationReached: false }
  await page.getByLabel('PCの未送信結果JSON').setInputFiles({ name: 'report.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(report)) })
  await expect(page.getByRole('status')).toContainText('未送信のPC報告を記録')
  await expect(page.getByLabel('PCの未送信結果JSON')).toHaveCount(0)
})
