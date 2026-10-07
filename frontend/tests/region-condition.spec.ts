import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { test, expect } from '@playwright/test'

test('Verified region proof classifies a candidate and human withdrawal remains unknown', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const env = { ...process.env, E2E_EMAIL: `e2e-region-${randomBytes(8).toString('hex')}@example.com`, E2E_PASSWORD: randomBytes(24).toString('hex') }
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
    await page.getByRole('button', { name: '⌕ 企業収集', exact: true }).click()
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(fixture.project_id)
    await page.getByText('対象条件を確認・分類する', { exact: true }).click()
    await page.getByLabel('条件1の種類').selectOption('AREA')
    await page.getByLabel('条件1の内容').fill('兵庫県姫路市')
    await page.getByRole('button', { name: '条件を確認して確定', exact: true }).click()
    const result = page.getByRole('region', { name: '条件判定結果' })
    const company = result.locator(':scope > details').first()
    await company.locator(':scope > summary').click()
    await expect(result).toContainText('確認済み住所から地域一致')
    await expect(company.getByRole('link', { name: '根拠 ↗' })).toHaveAttribute('href', /^https:\/\//)
    const review = company.locator('div > details').first()
    await review.locator('summary').click()
    await company.getByRole('combobox', { name: '確認結果', exact: true }).selectOption('UNKNOWN')
    await review.getByLabel('確認内容・理由').fill('登録された住所根拠の確認を取り消します')
    await review.getByRole('button', { name: '人の確認結果を保存' }).click()
    await expect(result).toContainText('確認を取り消しました')
    await expect(company.locator(':scope > summary')).toContainText('確認待ち')
    expect(forbidden).toEqual([])
  } finally {
    execFileSync(python, ['../backend/tests/e2e_user.py', 'cleanup'], { env })
  }
})

