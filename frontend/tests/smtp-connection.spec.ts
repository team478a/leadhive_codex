import { test, expect } from '@playwright/test'

test('SMTP diagnostics shows connection evidence without sending on desktop and mobile', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('メールアドレス').fill(process.env.E2E_EMAIL!)
  await page.getByLabel('パスワード').fill(process.env.E2E_PASSWORD!)
  await page.getByRole('button', { name: 'ログインする', exact: true }).click()
  const guide = page.getByRole('dialog', { name: '3ステップで始めましょう' })
  await expect(guide).toBeVisible()
  await guide.getByRole('button', { name: 'あとで見る' }).click()
  await page.getByRole('button', { name: '⚙ 運用設定' }).click()
  const panel = page.getByRole('region', { name: 'SMTP接続確認' })
  await panel.getByRole('button', { name: 'メールを送らず接続確認', exact: true }).click()
  await expect(panel.getByRole('alert')).toContainText('SMTP設定を保存してから')
  let tests = 0
  let sends = 0
  page.on('request', request => {
    if (request.url().endsWith('/smtp-settings/test')) sends++
  })
  await page.route('**/api/admin/smtp-settings/connection-test', route => {
    tests++
    return route.fulfill({ json: { ok: true, stage: 'completed', tls_verified: true,
      authenticated: true, checked_at: '2026-10-05T00:00:00Z',
      message: '接続・認証を確認しました。メールは送信していません。' } })
  })
  await panel.getByRole('button', { name: 'メールを送らず接続確認', exact: true }).click()
  await expect(panel.getByRole('status')).toContainText('メールは送信していません')
  await expect(panel.getByRole('status')).toContainText('認証：確認済み')
  expect(tests).toBe(1)
  expect(sends).toBe(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width)
})
