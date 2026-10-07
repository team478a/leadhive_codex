import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { test, expect } from '@playwright/test'

test('Industry excerpts require human confirmation and never establish a match alone', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const env = { ...process.env, E2E_EMAIL: `e2e-industry-${randomBytes(8).toString('hex')}@example.com`, E2E_PASSWORD: randomBytes(24).toString('hex') }
  execFileSync(python, ['../backend/tests/e2e_user.py', 'create'], { env })
  const forbidden: string[] = []
  page.on('request', r => {
    if (!['localhost', '127.0.0.1'].includes(new URL(r.url()).hostname) || /\/(send|dispatch|execute|approve|test-send|operations)([/?]|$)/.test(r.url()) && r.method() === 'POST') forbidden.push(r.url())
  })
  try {
    const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'destination-selection-fixture'], { env, encoding: 'utf8' })) as { project_id: string }
    execFileSync(python, ['../backend/tests/e2e_industry_hint.py', fixture.project_id], { env })
    await page.goto('/')
    await page.getByLabel('メールアドレス').fill(env.E2E_EMAIL)
    await page.getByLabel('パスワード').fill(env.E2E_PASSWORD)
    await page.getByRole('button', { name: 'ログインする', exact: true }).click()
    await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
    await page.getByRole('button', { name: '⌕ 企業収集', exact: true }).click()
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(fixture.project_id)
    await page.getByText('対象条件を確認・分類する', { exact: true }).click()
    await page.getByLabel('条件1の種類').selectOption('INDUSTRY')
    await page.getByLabel('条件1の内容').fill('美容院')
    await page.getByRole('button', { name: '条件を確認して確定', exact: true }).click()
    const result = page.getByRole('region', { name: '条件判定結果' })
    const company = result.locator(':scope > details').first()
    await company.locator(':scope > summary').click()
    await expect(company.locator(':scope > summary')).toContainText('確認待ち')
    const review = company.locator('div > details').first()
    await review.locator('summary').click()
    await expect(review.getByRole('region', { name: '業種の確認を助ける文章' })).toContainText('当社は美容院')
    await review.getByRole('button', { name: 'この文章を確認欄に入れる' }).click()
    const save = review.getByRole('button', { name: '人の確認結果を保存' })
    await expect(save).toBeDisabled()
    await review.getByRole('checkbox', { name: '公開ページとこの企業・店舗の事業内容を確認しました' }).check()
    await save.click()
    await expect(company.locator(':scope > summary')).toContainText('：一致')
    await company.getByRole('combobox', { name: '確認結果', exact: true }).selectOption('UNKNOWN')
    await review.getByLabel('確認内容・理由').fill('この企業の業種について行った確認を取り消します')
    await review.getByRole('button', { name: '人の確認結果を保存' }).click()
    await expect(result).toContainText('確認を取り消しました')
    await expect(company.locator(':scope > summary')).toContainText('確認待ち')
    expect(forbidden).toEqual([])
  } finally {
    execFileSync(python, ['../backend/tests/e2e_user.py', 'cleanup'], { env })
  }
})


