import { navigateWorkspace } from './navigation'
import { execFileSync } from 'node:child_process'
import { test, expect } from '@playwright/test'

test('bulk Human approval reserves and pauses email without sending', async ({ page }, testInfo) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'approved-email-fixture'], { env: process.env, encoding: 'utf8' })) as { project_id: string; company_id: string; recipient: string }
  await page.goto('/')
  await page.getByLabel('メールアドレス').fill(process.env.E2E_EMAIL!)
  await page.getByLabel('パスワード').fill(process.env.E2E_PASSWORD!)
  await page.getByRole('button', { name: 'ログインする', exact: true }).click()
  await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
  const smtpResponse = await page.request.get('/api/admin/smtp-settings')
  expect(smtpResponse.ok()).toBeTruthy()
  const smtp = await smtpResponse.json() as { from_name: string; from_email: string } | null
  const proposal = await page.request.post(`/api/projects/${fixture.project_id}/approval-requests`, { data: {
    company_id: fixture.company_id, channel: 'email', delivery_method: 'email', recipient: fixture.recipient,
    subject: 'Company specific message', body: 'A unique approved message, never sent by this test.', sender: { name: smtp?.from_name ?? 'A2 Human', email: smtp?.from_email ?? 'sender@example.com' },
  } })
  expect(proposal.status()).toBe(201)
  await navigateWorkspace(page, '✓ 承認キュー')
  await page.getByLabel('承認プロジェクト').selectOption(fixture.project_id)
  const panel = page.getByRole('region', { name: '承認済みメール予約' })
  await panel.locator('summary').filter({ hasText: fixture.recipient }).click()
  await panel.getByRole('checkbox', { name: 'A2 E2E Companyの宛先・文面を確認して選択' }).check()
  await panel.getByLabel('一括承認用ログインパスワード').fill(process.env.E2E_PASSWORD!)
  await panel.getByRole('button', { name: '選択した1件を一括Human承認', exact: true }).click()
  await expect(panel.getByRole('status')).toContainText('Human承認しました')
  await panel.getByRole('button', { name: '承認済み1件を送信予約', exact: true }).click()
  await expect(panel.getByText(/会社別メール予約.*実行無効/)).toBeVisible()
  await panel.getByRole('button', { name: '予約を一時停止' }).click()
  await expect(panel.getByText(/会社別メール予約.*一時停止/)).toBeVisible()
  await panel.getByRole('button', { name: '予約を再開' }).click()
  await panel.getByRole('button', { name: '未実行の予約を取り消す' }).click()
  await expect(panel.getByText(/会社別メール予約.*取消済み/)).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await page.screenshot({ path: testInfo.outputPath('approved-email.png'), fullPage: true })
  const deliveries = await page.request.get(`/api/projects/${fixture.project_id}/email-deliveries`)
  expect(deliveries.ok()).toBeTruthy()
  expect((await deliveries.json()).sent_count).toBe(0)
})
