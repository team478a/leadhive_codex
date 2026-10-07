import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { test, expect } from '@playwright/test'

test('Presence states, links and bounded search controls work without external requests', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const env = { ...process.env, E2E_EMAIL: `e2e-presence-${randomBytes(8).toString('hex')}@example.com`, E2E_PASSWORD: randomBytes(24).toString('hex') }
  execFileSync(python, ['../backend/tests/e2e_user.py', 'create'], { env })
  const forbidden: string[] = []
  page.on('request', r => {
    if (!['localhost', '127.0.0.1'].includes(new URL(r.url()).hostname) || /\/(send|dispatch|execute|approve|test-send)([/?]|$)/.test(r.url())) forbidden.push(r.url())
  })
  try {
    const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'destination-selection-fixture'], { env, encoding: 'utf8' })) as { project_id: string }
    execFileSync(python, ['../backend/tests/e2e_presence.py', fixture.project_id], { env })
    await page.goto('/')
    await page.getByLabel('メールアドレス').fill(env.E2E_EMAIL)
    await page.getByLabel('パスワード').fill(env.E2E_PASSWORD)
    await page.getByRole('button', { name: 'ログインする', exact: true }).click()
    await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
    await page.getByRole('button', { name: '▤ 企業一覧', exact: true }).click()
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(fixture.project_id)
    await page.getByText('掲載媒体・SNS・求人', { exact: true }).first().click()
    const cell = page.locator('details').filter({ has: page.getByText('掲載媒体・SNS・求人', { exact: true }) }).first()
    await expect(cell).toContainText('X：未調査')
    await expect(cell).toContainText('YouTube：調査で見つからず')
    await expect(cell).toContainText('検索上限に到達')
    await expect(cell.getByRole('link', { name: 'あり ↗' }).first()).toHaveAttribute('href', 'https://instagram.com/fixture')
    await page.getByRole('button', { name: '⌕ 企業収集', exact: true }).click()
    await page.getByText(/追加で調べる情報（0項目/).click()
    await expect(page.getByLabel('Instagram追加調査')).toHaveValue('AUTO')
    await page.getByLabel('Instagram追加調査').selectOption('SEARCH')
    await page.getByLabel('HotPepper Beauty追加調査').selectOption('REQUIRED')
    await page.getByLabel('追加検索の上限', { exact: true }).fill('1')
    await expect(page.getByText(/追加で調べる情報（2項目・上限1検索/)).toBeVisible()
    await expect(page.getByLabel('X追加調査', { exact: true })).toHaveValue('AUTO')
    await page.getByLabel('SNS一括設定', { exact: true }).selectOption('AUTO')
    await expect(page.getByLabel('Instagram追加調査')).toHaveValue('AUTO')
    await expect(page.getByLabel('HotPepper Beauty追加調査')).toHaveValue('REQUIRED')
    await expect(page.getByText('検索中に見つかった情報は、設定に関係なく保存します。', { exact: false })).toBeVisible()
    expect(forbidden).toEqual([])
  } finally {
    execFileSync(python, ['../backend/tests/e2e_user.py', 'cleanup'], { env })
  }
})
