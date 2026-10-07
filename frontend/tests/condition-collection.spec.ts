import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { test, expect } from '@playwright/test'

test('Confirmed criteria can be attached to a queued collection without running searches', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const env = { ...process.env, E2E_EMAIL: `e2e-condition-run-${randomBytes(8).toString('hex')}@example.com`, E2E_PASSWORD: randomBytes(24).toString('hex') }
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
    await page.getByRole('button', { name: '⌕ 企業収集', exact: true }).click()
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(fixture.project_id)
    const checkbox = page.getByRole('checkbox', { name: /確定条件を今回の収集に使う/ })
    await expect(checkbox).toBeDisabled()
    await page.getByText('対象条件を確認・分類する', { exact: true }).click()
    await page.getByRole('button', { name: '条件を確認して確定', exact: true }).click()
    await expect(checkbox).toBeEnabled()
    await checkbox.check()
    await page.getByLabel('検索キーワード（1行に1件）').fill('テスト対象')
    const responsePromise = page.waitForResponse(r => r.url().endsWith(`/projects/${fixture.project_id}/operations`) && r.request().method() === 'POST')
    await page.getByRole('button', { name: '収集を開始', exact: true }).click()
    const response = await responsePromise
    expect(response.status()).toBe(202)
    const data = await response.json() as { condition_request_id: string; condition_version: number }
    expect(data.condition_request_id).toBeTruthy(); expect(data.condition_version).toBe(1)
    await page.getByText('この収集の条件判定', { exact: true }).click()
    await expect(page.getByText('この収集の保存済み候補はありません。', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'キャンセル', exact: true }).click()
    await expect(page.getByText('キャンセル', { exact: true })).toBeVisible()
    expect(forbidden).toEqual([])
  } finally {
    execFileSync(python, ['../backend/tests/e2e_user.py', 'cleanup'], { env })
  }
})
