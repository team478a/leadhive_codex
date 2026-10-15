import { navigateWorkspace } from './navigation'
import { execFileSync } from 'node:child_process'
import { test, expect } from '@playwright/test'

test('confirmed complaint stops email and requires owner reauthentication', async ({ page }, testInfo) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'email-feedback-fixture'], { env: process.env, encoding: 'utf8' })) as { project_id: string; recipient: string }
  await page.goto('/')
  await page.getByLabel('メールアドレス').fill(process.env.E2E_EMAIL!)
  await page.getByLabel('パスワード').fill(process.env.E2E_PASSWORD!)
  await page.getByRole('button', { name: 'ログインする', exact: true }).click()
  await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
  await navigateWorkspace(page, '✉ メール配信状況')
  await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(fixture.project_id)
  const panel = page.getByRole('region', { name: '配信結果と安全停止' })
  await panel.getByRole('button', { name: '確認済みの配信結果を登録', exact: true }).click()
  await panel.getByLabel('結果を記録するメール', { exact: true }).selectOption({ label: `A2 E2E Company / ${fixture.recipient}` })
  await panel.getByLabel('確認した配信結果').selectOption('complaint')
  const record = panel.getByRole('button', { name: '確認結果を記録', exact: true })
  await record.scrollIntoViewIfNeeded()
  if (testInfo.project.name === 'mobile') await record.tap()
  else await record.click()
  await expect(panel.getByText(/安全停止中:/)).toBeVisible()
  await panel.getByLabel('安全停止解除用ログインパスワード').fill(process.env.E2E_PASSWORD!)
  await panel.getByRole('button', { name: '原因確認済みとして安全停止を解除' }).click()
  await expect(panel.getByText('安全停止なし（送信の有効化とは別です）')).toBeVisible()
  await expect(panel.getByText(/人の確認/)).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width)
  await page.screenshot({ path: testInfo.outputPath('email-feedback.png'), fullPage: true })
})
