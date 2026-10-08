import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { test, expect } from '@playwright/test'

test('fixture plan is visible, human approved, and excluded from dispatch controls', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  // Each test gets its own principal; shared users exhaust the real step-up limit.
  const env = { ...process.env, E2E_EMAIL: `e2e-plan-${randomBytes(8).toString('hex')}@example.com`, E2E_PASSWORD: randomBytes(24).toString('hex') }
  execFileSync(python, ['../backend/tests/e2e_user.py', 'create'], { env })
  try {
    const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'approval-fixture'], { env, encoding: 'utf8' })) as { project_id: string; company_id: string }
    await page.goto('/')
    await page.getByLabel('メールアドレス').fill(env.E2E_EMAIL)
    await page.getByLabel('パスワード').fill(env.E2E_PASSWORD)
    await page.getByRole('button', { name: 'ログインする', exact: true }).click()
    const guide = page.getByRole('dialog', { name: '3ステップで始めましょう' })
    await expect(guide).toBeVisible()
    await guide.getByRole('button', { name: 'あとで見る' }).click()
    const sender = { name: 'Human', email: 'sender@example.com', company: '', phone: '' }
    const response = await page.request.post(`/api/projects/${fixture.project_id}/approval-requests`, { data: {
      company_id: fixture.company_id, channel: 'form', delivery_method: 'form_plan_fixture',
      form_url: 'https://fixture.example/contact', form_action_url: 'https://fixture.example/submit',
      subject: 'Fixture only', body: 'Anonymous plan', sender, field_values: { message: 'Anonymous plan' },
      execution_plan: {
        contract_version: 1, adapter_id: 'fixture_js_confirmation', adapter_version: '1',
        project_id: fixture.project_id, company_id: fixture.company_id, form_id: 'anonymous',
        form_url: 'https://fixture.example/contact', field_fingerprint: 'a'.repeat(64),
        route_fingerprint: 'b'.repeat(64), payload_version: 1, subject: 'Fixture only', body: 'Anonymous plan',
        sender: Object.entries(sender).map(([name, value]) => ({ name, value })),
        field_values: [{ name: 'message', value: 'Anonymous plan' }], steps: [
          { kind: 'confirm_local', url: 'https://fixture.example/contact', method: 'NONE' },
          { kind: 'submit', url: 'https://fixture.example/submit', method: 'POST' },
        ],
      },
    } })
    expect(response.status()).toBe(201)
    await page.getByRole('button', { name: '✓ 承認キュー', exact: true }).click()
    await page.getByLabel('承認プロジェクト').selectOption(fixture.project_id)
    await page.getByRole('button', { name: /A2 E2E Company.*承認待ち/ }).click()
    const proposal = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'A2 E2E Company の提案内容', exact: true }) })
    await expect(proposal).toContainText('検証用の操作計画（送信不可）')
    await expect(proposal).toContainText('fixture_js_confirmation')
    await expect(proposal).toContainText('confirm_local')
    await expect(proposal).toContainText('操作計画hash')
    await page.getByLabel('承認用パスワード（再認証）').fill(env.E2E_PASSWORD)
    await page.getByRole('button', { name: '内容を確認して承認', exact: true }).click()
    await expect(page.getByRole('status')).toContainText('送信は行っていません')
    await expect(page.getByRole('button', { name: /A2 E2E Company.*承認済み/ })).toBeVisible()
    await expect(page.getByRole('region', { name: '承認済みフォーム予約' }).getByText('A2 E2E Company')).toHaveCount(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  } finally {
    execFileSync(python, ['../backend/tests/e2e_user.py', 'cleanup'], { env })
  }
})
