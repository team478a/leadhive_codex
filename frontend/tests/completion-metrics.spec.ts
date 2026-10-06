import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { test, expect } from '@playwright/test'

test('Human freezes the funnel denominator and records review effort without approval or sending', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const env = { ...process.env, E2E_EMAIL: `e2e-metrics-${randomBytes(8).toString('hex')}@example.com`, E2E_PASSWORD: randomBytes(24).toString('hex') }
  execFileSync(python, ['../backend/tests/e2e_user.py', 'create'], { env })
  const forbidden: string[] = []
  page.on('request', request => {
    if (!['localhost', '127.0.0.1'].includes(new URL(request.url()).hostname) || /\/send(?:[/?]|$)|\/dispatch|\/execute|\/test-send|\/approve/.test(request.url())) forbidden.push(request.url())
  })
  try {
    const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'approval-fixture'], { env, encoding: 'utf8' })) as { project_id: string }
    await page.goto('/')
    await page.getByLabel('メールアドレス').fill(env.E2E_EMAIL)
    await page.getByLabel('パスワード').fill(env.E2E_PASSWORD)
    await page.getByRole('button', { name: 'ログインする', exact: true }).click()
    await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
    await page.getByRole('button', { name: '⌂ ダッシュボード', exact: true }).click()
    const panel = page.getByRole('region', { name: 'Lead Completion計測' })
    await panel.getByLabel('完成率のプロジェクト').selectOption(fixture.project_id)
    await panel.getByRole('button', { name: '現在のリストを集計対象として固定', exact: true }).click()
    await expect(panel).toContainText('DM READY率')
    await expect(panel).toContainText('未判定')
    await expect(panel).toContainText('料金・Cost per DM READYは不明')
    await panel.getByLabel('レビュー時間を記録する企業').selectOption({ index: 1 })
    await panel.getByRole('button', { name: 'レビュー時間の記録を開始', exact: true }).click()
    await expect(panel.getByRole('status')).toContainText('レビュー計測中')
    await page.reload()
    await page.getByRole('button', { name: '⌂ ダッシュボード', exact: true }).click()
    await panel.getByLabel('完成率のプロジェクト').selectOption(fixture.project_id)
    await panel.getByLabel('固定した集計対象').selectOption({ index: 1 })
    await expect(panel.getByRole('status')).toContainText('レビュー計測中')
    await panel.getByRole('button', { name: 'レビュー記録を終了', exact: true }).click()
    await expect(panel).toContainText('レビュー 1 / 1件終了')
    await expect(panel).toContainText('営業許可・Human承認を変更しません')
    expect(forbidden).toEqual([])
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  } finally {
    execFileSync(python, ['../backend/tests/e2e_user.py', 'cleanup'], { env })
  }
})
