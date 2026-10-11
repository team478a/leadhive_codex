import { navigateWorkspace } from './navigation'
import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { test, expect } from '@playwright/test'

test('Human region and industry evidence updates criteria without collection or sending', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const env = { ...process.env, E2E_EMAIL: `e2e-facts-${randomBytes(8).toString('hex')}@example.com`, E2E_PASSWORD: randomBytes(24).toString('hex') }
  execFileSync(python, ['../backend/tests/e2e_user.py', 'create'], { env })
  const forbidden: string[] = []
  page.on('request', r => {
    if (!['localhost', '127.0.0.1'].includes(new URL(r.url()).hostname) || /\/(send|dispatch|execute|approve|test-send|operations)([/?]|$)/.test(r.url()) && r.method() === 'POST') forbidden.push(r.url())
  })
  try {
    const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'destination-selection-fixture'], { env, encoding: 'utf8' })) as { project_id: string }
    await page.goto('/')
    await page.getByLabel('メールアドレス').fill(env.E2E_EMAIL)
    await page.getByLabel('パスワード').fill(env.E2E_PASSWORD)
    await page.getByRole('button', { name: 'ログインする', exact: true }).click()
    await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
    await navigateWorkspace(page, '⌕ 企業収集')
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(fixture.project_id)
    await page.getByText('対象条件を確認・分類する', { exact: true }).click()
    await page.getByLabel('条件1の種類').selectOption('AREA')
    await page.getByLabel('条件1の内容').fill('姫路市')
    await page.getByRole('button', { name: '条件を追加', exact: true }).click()
    await page.getByLabel('条件2の種類').selectOption('INDUSTRY')
    await page.getByLabel('条件2の内容').fill('美容院')
    await page.getByRole('button', { name: '条件を確認して確定', exact: true }).click()
    const result = page.getByRole('region', { name: '条件判定結果' })
    const candidate = result.locator(':scope > details').first()
    await expect(candidate.locator(':scope > summary')).toContainText('：確認待ち（')
    await candidate.locator(':scope > summary').click()
    for (const value of ['姫路市', '美容院']) {
      const review = candidate.locator('details').filter({ has: page.locator('summary', { hasText: `地域・業種の根拠を確認する：${value}` }) })
      await review.locator('summary').click()
      await review.getByLabel('確認した公開ページURL').fill('https://example.test/about')
      await review.getByLabel('確認内容・理由').fill('合成テスト用の所在地と業種を人が確認したという検証記録です。')
      await review.getByRole('button', { name: '人の確認結果を保存' }).click()
      await expect(candidate).toContainText('人が根拠を確認しました')
    }
    await expect(candidate.locator(':scope > summary')).toContainText('：一致（')
    const area = candidate.locator('details').filter({ has: page.locator('summary', { hasText: '地域・業種の根拠を確認する：姫路市' }) })
    await area.getByLabel('確認結果').selectOption('UNKNOWN')
    await area.getByLabel('確認内容・理由').fill('判断に十分な根拠がないことが分かったので確認を取り消します。')
    await area.getByRole('button', { name: '人の確認結果を保存' }).click()
    await expect(candidate.locator(':scope > summary')).toContainText('：確認待ち（')
    await expect(candidate).toContainText('確認を取り消しました・判断不能')
    await page.reload()
    await navigateWorkspace(page, '⌕ 企業収集')
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(fixture.project_id)
    await page.getByText('対象条件を確認・分類する', { exact: true }).click()
    await expect(page.getByRole('region', { name: '条件判定結果' })).toContainText('第1版')
    expect(forbidden).toEqual([])
  } finally {
    execFileSync(python, ['../backend/tests/e2e_user.py', 'cleanup'], { env })
  }
})
