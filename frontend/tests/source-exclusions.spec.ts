import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { test, expect } from '@playwright/test'
import { navigateWorkspace } from './navigation'

test('Human source-domain memory persists and can be deactivated without collection or sending', async ({ page }, testInfo) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const env = { ...process.env, E2E_EMAIL: `e2e-source-memory-${randomBytes(8).toString('hex')}@example.com`, E2E_PASSWORD: randomBytes(24).toString('hex') }
  execFileSync(python, ['../backend/tests/e2e_user.py', 'create'], { env })
  const forbidden: string[] = []
  page.on('request', r => {
    if (!['localhost', '127.0.0.1'].includes(new URL(r.url()).hostname) || (r.method() === 'POST' && /\/(send|dispatch|execute|approve|analyze|operations|collection-jobs)([/?]|$)/.test(r.url()))) forbidden.push(r.url())
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
    let panel = page.locator('details').filter({ has: page.getByText('再収集しない掲載媒体', { exact: false }) }).first()
    await panel.locator('summary').click()
    await panel.getByLabel('除外する媒体の根拠URL').fill('https://www.listing.example/list')
    await expect(panel.getByRole('button', { name: '除外ドメインを記録' })).toBeDisabled()
    await panel.getByRole('checkbox').check()
    await panel.getByRole('button', { name: '除外ドメインを記録' }).click()
    await expect(panel).toContainText('listing.example / 除外中')
    await panel.screenshot({ path: testInfo.outputPath('source-memory.png') })
    if (testInfo.project.name === 'mobile') expect((await panel.boundingBox())?.width).toBeLessThanOrEqual(page.viewportSize()!.width)
    await page.reload()
    await navigateWorkspace(page, '⌕ 企業収集')
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(fixture.project_id)
    panel = page.locator('details').filter({ has: page.getByText('再収集しない掲載媒体', { exact: false }) }).first()
    await panel.locator('summary').click()
    await expect(panel).toContainText('listing.example / 除外中')
    await panel.getByRole('button', { name: '除外を解除' }).click()
    await expect(panel).toContainText('listing.example / 解除済み')
    expect(forbidden).toEqual([])
  } finally { execFileSync(python, ['../backend/tests/e2e_user.py', 'cleanup'], { env }) }
})
