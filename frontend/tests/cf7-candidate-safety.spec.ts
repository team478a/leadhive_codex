import { navigateWorkspace } from './navigation'
import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { test, expect } from '@playwright/test'

// UI isolation test: the candidate list response is mocked, never a DB approval.
// Actual preparation/proof/approval bindings are covered by PostgreSQL API tests.
test('non-executable CF7 candidates show a warning and never offer reservations', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const env = { ...process.env, E2E_EMAIL: `e2e-cf7-safety-${randomBytes(8).toString('hex')}@example.com`, E2E_PASSWORD: randomBytes(24).toString('hex') }
  execFileSync(python, ['../backend/tests/e2e_user.py', 'create'], { env })
  const forbidden: string[] = []
  page.on('request', request => {
    if (!['localhost', '127.0.0.1'].includes(new URL(request.url()).hostname) || /\/form-dispatch$|\/send(?:[/?]|$)|\/execute|\/test-send/.test(request.url())) forbidden.push(request.url())
  })
  try {
    const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'approval-fixture'], { env, encoding: 'utf8' })) as { project_id: string; company_id: string }
    await page.route(`**/api/projects/${fixture.project_id}/approval-requests*`, route => route.fulfill({ json: [{
      id: '00000000-0000-0000-0000-000000000001', project_id: fixture.project_id,
      company_id: fixture.company_id, company_name: 'CF7 Safety', channel: 'form',
      delivery_method: 'cf7_candidate_only', status: 'APPROVED', payload_hash: 'a'.repeat(64), payload_version: 1,
      recipient: null, form_url: 'https://managed.example/contact/', form_action_url: 'https://managed.example/wp-json/',
      sender: { name: 'Operator', email: 'operator@example.com' }, subject: '', body: 'Controlled candidate',
      field_values: { message: 'Controlled candidate' }, created_by_principal_type: 'HUMAN',
      created_at: new Date().toISOString(), expires_at: new Date(Date.now() + 3600000).toISOString(),
    }] }))
    await page.goto('/')
    await page.getByLabel('メールアドレス').fill(env.E2E_EMAIL)
    await page.getByLabel('パスワード').fill(env.E2E_PASSWORD)
    await page.getByRole('button', { name: 'ログインする', exact: true }).click()
    await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
    await navigateWorkspace(page, '✓ 承認キュー')
    await page.getByLabel('承認プロジェクト').selectOption(fixture.project_id)
    await page.getByRole('button', { name: /CF7 Safety.*承認済み/ }).click()
    await expect(page.getByRole('status')).toContainText('送信予約・実送信には使用できません')
    await expect(page.getByRole('button', { name: 'CF7 Safety の承認済みフォームを予約', exact: true })).toHaveCount(0)
    expect(forbidden).toEqual([])
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  } finally {
    execFileSync(python, ['../backend/tests/e2e_user.py', 'cleanup'], { env })
  }
})
