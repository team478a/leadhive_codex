import { navigateWorkspace } from './navigation'
import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { test, expect } from '@playwright/test'

test('Site withdrawal invalidates confirmed criteria despite automatic evidence', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const env = { ...process.env, E2E_EMAIL: `e2e-site-${randomBytes(8).toString('hex')}@example.com`, E2E_PASSWORD: randomBytes(24).toString('hex') }
  execFileSync(python, ['../backend/tests/e2e_user.py', 'create'], { env })
  const forbidden: string[] = []
  page.on('request', r => {
    if (!['localhost', '127.0.0.1'].includes(new URL(r.url()).hostname) || /\/(send|dispatch|execute|approve|test-send|operations)([/?]|$)/.test(r.url()) && r.method() === 'POST') forbidden.push(r.url())
  })
  try {
    const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'destination-selection-fixture'], { env, encoding: 'utf8' })) as { project_id: string }
    execFileSync(python, ['../backend/tests/e2e_region_condition.py', fixture.project_id], { env })
    await page.goto('/')
    await page.getByLabel('メールアドレス').fill(env.E2E_EMAIL)
    await page.getByLabel('パスワード').fill(env.E2E_PASSWORD)
    await page.getByRole('button', { name: 'ログインする', exact: true }).click()
    await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
    await navigateWorkspace(page, '⌕ 企業収集')
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(fixture.project_id)
    await page.getByText('対象条件を確認・分類する', { exact: true }).click()
    await page.getByLabel('条件1の種類').selectOption('OFFICIAL_SITE')
    await page.getByRole('button', { name: '条件を確認して確定', exact: true }).click()
    const result = page.getByRole('region', { name: '条件判定結果' })
    const company = result.locator(':scope > details').first()
    await company.locator(':scope > summary').click()
    await expect(result).toContainText('公式サイトの根拠を確認')
    await expect(company.getByRole('link', { name: '根拠 ↗' })).toHaveAttribute('href', /^https:\/\//)
    execFileSync(python, ['../backend/tests/e2e_site_withdrawal.py', fixture.project_id], { env })
    await page.getByRole('button', { name: '最新の根拠で再表示' }).click()
    await expect(result).toContainText('公式サイトの確認が取り消されています')
    await expect(company.locator(':scope > summary')).toContainText('確認待ち')
    expect(forbidden).toEqual([])
  } finally {
    execFileSync(python, ['../backend/tests/e2e_user.py', 'cleanup'], { env })
  }
})



