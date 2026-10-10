import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { test, expect } from '@playwright/test'

test('Operational feedback corrects a URL, persists after reload and clears rejected candidates without sending', async ({ page }, testInfo) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const env = { ...process.env, E2E_EMAIL: `e2e-feedback-${randomBytes(8).toString('hex')}@example.com`, E2E_PASSWORD: randomBytes(24).toString('hex') }
  execFileSync(python, ['../backend/tests/e2e_user.py', 'create'], { env })
  const forbidden: string[] = []
  page.on('request', r => { if (!['localhost', '127.0.0.1'].includes(new URL(r.url()).hostname) || /\/(send|dispatch|execute|approve|test-send)([/?]|$)/.test(r.url())) forbidden.push(r.url()) })
  try {
    const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'destination-selection-fixture'], { env, encoding: 'utf8' })) as { project_id: string }
    await page.goto('/')
    await page.getByLabel('メールアドレス').fill(env.E2E_EMAIL)
    await page.getByLabel('パスワード').fill(env.E2E_PASSWORD)
    await page.getByRole('button', { name: 'ログインする', exact: true }).click()
    await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
    await page.getByRole('button', { name: '▤ 企業一覧', exact: true }).click()
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(fixture.project_id)
    let panel = page.locator('[aria-label$="の取得結果確認"]').first()
    if (testInfo.project.name === 'mobile') {
      await expect(page.getByRole('region', { name: '企業一覧のカード' })).toBeVisible()
      const box = await panel.boundingBox()
      expect(box?.width).toBeLessThanOrEqual(page.viewportSize()!.width)
    }
    await panel.getByRole('button', { name: 'NG・修正', exact: true }).click()
    await panel.getByLabel('理由', { exact: true }).selectOption('article')
    await panel.getByLabel('正しい問い合わせURL').fill('https://approval.example/contact-corrected')
    await panel.getByRole('button', { name: '修正URLを保存', exact: true }).click()
    await expect(panel).toContainText('URL修正を記録')
    await expect(panel.getByRole('link', { name: '問い合わせ候補を開く' })).toHaveAttribute('href', 'https://approval.example/contact-corrected')
    await panel.screenshot({ path: testInfo.outputPath('feedback-corrected.png') })
    await page.reload()
    await page.getByRole('button', { name: '▤ 企業一覧', exact: true }).click()
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(fixture.project_id)
    panel = page.locator('[aria-label$="の取得結果確認"]').first()
    await expect(panel).toContainText('URL修正を記録')
    await panel.getByRole('button', { name: 'OK', exact: true }).click()
    await expect(panel).toContainText('OKを記録')
    await panel.getByRole('button', { name: 'NG・修正', exact: true }).click()
    await panel.getByLabel('理由', { exact: true }).selectOption('recruitment')
    await panel.getByRole('button', { name: 'NGを記録して候補から外す', exact: true }).click()
    await expect(panel).toContainText('未検出（存在未確認）')
    await expect(panel.getByRole('button', { name: 'OK', exact: true })).toBeDisabled()
    expect(forbidden).toEqual([])
  } finally { execFileSync(python, ['../backend/tests/e2e_user.py', 'cleanup'], { env }) }
})
