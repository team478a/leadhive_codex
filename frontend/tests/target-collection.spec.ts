import { navigateWorkspace } from './navigation'
import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { test, expect } from '@playwright/test'

test('collection uses a count goal and displays why searching ended', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const env = { ...process.env, E2E_EMAIL: `e2e-target-${randomBytes(8).toString('hex')}@example.com`, E2E_PASSWORD: randomBytes(24).toString('hex') }
  execFileSync(python, ['../backend/tests/e2e_user.py', 'create'], { env })
  try {
    const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'destination-selection-fixture'], { env, encoding: 'utf8' })) as { project_id: string }
    await page.goto('/')
    await page.getByLabel('メールアドレス').fill(env.E2E_EMAIL)
    await page.getByLabel('パスワード').fill(env.E2E_PASSWORD)
    await page.getByRole('button', { name: 'ログインする', exact: true }).click()
    await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
    await navigateWorkspace(page, '⌕ 企業収集')
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(fixture.project_id)
    await expect(page.getByLabel('収集する新規候補数（目標）')).toHaveAttribute('max', '10000')
    await page.getByLabel('収集する新規候補数（目標）').fill('150')
    await expect(page.getByLabel('検索の総上限（安全上限）')).toHaveValue('5000')
    await expect(page.getByLabel('検索の総上限（安全上限）')).toHaveAttribute('max', '5000')
    await expect(page.getByLabel('目標件数まで50回ごとに自動で続きを実行する（おすすめ）')).toBeChecked()
    await page.getByLabel('目標件数まで50回ごとに自動で続きを実行する（おすすめ）').uncheck()
    await page.getByLabel('今回の検索回数上限').fill('2')
    await page.getByLabel('検索キーワード（1行に1件）').fill('SNS運用代行会社')
    await page.getByRole('combobox', { name: '都道府県', exact: true }).selectOption('兵庫県')
    await expect(page.getByRole('region', { name: '検索の組み合わせ' })).toContainText('兵庫県と各キーワード')
    await page.getByRole('combobox', { name: '都道府県', exact: true }).selectOption('全国')
    await page.getByText('検索キーワードと地域の組み合わせを確認', { exact: true }).click()
    await expect(page.getByRole('region', { name: '検索の組み合わせ' })).toContainText('SNS運用代行会社 北海道')
    await expect(page.getByRole('region', { name: '検索の組み合わせ' })).toContainText('SNS運用代行会社 沖縄県')
    const responsePromise = page.waitForResponse(r => r.url().includes(`/projects/${fixture.project_id}/operations`) && r.request().method() === 'POST')
    await page.getByRole('button', { name: '収集を開始', exact: true }).click()
    const response = await responsePromise
    expect(response.request().postDataJSON().target_count).toBe(150)
    expect(response.request().postDataJSON().search_request_limit).toBe(2)
    expect(response.request().postDataJSON().auto_continue).toBe(false)
    expect(response.request().postDataJSON().region).toBe('全国')
    expect(response.request().postDataJSON().region_mode).toBe('prefecture_order')
    expect(response.status()).toBe(202)
    const operation = await response.json()
    await page.route(`**/projects/${fixture.project_id}/operations**`, async route => {
      if (route.request().method() !== 'GET') return route.continue()
      await route.fulfill({ json: [{ ...operation, status: 'completed', collection_progress: { target_count: 150, collected_count: 8, requests: 4, request_budget: 50, stop_reason: 'QUERIES_EXHAUSTED' } }] })
    })
    await page.reload()
    await navigateWorkspace(page, '⌕ 企業収集')
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(fixture.project_id)
    await expect(page.getByText('新規候補 8 / 150 件・今回の検索 4 / 50 回・新規対象が増えず検索を終了')).toBeVisible()
    await page.route(`**/projects/${fixture.project_id}/operations**`, async route => {
      if (route.request().method() !== 'GET') return route.continue()
      await route.fulfill({ json: [{ ...operation, status: 'completed', collection_progress: { target_count: 150, collected_count: 0, discovered_count: 8, review_required_count: 6, no_match_count: 2, conditions_applied: true, requests: 2, request_budget: 2, pending_queries: 3, stop_reason: 'REQUEST_BUDGET_REACHED' } }] })
    })
    await page.getByRole('button', { name: '更新', exact: true }).last().click()
    await expect(page.getByText('条件一致 0 / 150 件・今回の検索 2 / 2 回・今回の検索上限に到達')).toBeVisible()
    await expect(page.getByRole('region', { name: '収集の続き' })).toContainText('目標 0 / 150 件')
    await expect(page.getByRole('button', { name: '続きから収集を再開' })).toBeVisible()
    await page.route(`**/api/operations/${operation.id}/continue`, route => route.fulfill({ status: 202, json: operation }))
    const continuePromise = page.waitForRequest(r => r.url().endsWith(`/api/operations/${operation.id}/continue`) && r.method() === 'POST')
    await page.getByRole('region', { name: '収集の続き' }).getByRole('button', { name: '続きから収集を再開' }).click()
    await continuePromise
    await expect(page.getByRole('button', { name: '続きから収集', exact: true })).toBeVisible()
    await expect(page.getByText(/発見候補 8 件・確認待ち 6 件・条件不一致 2 件/)).toBeVisible()
  } finally {
    execFileSync(python, ['../backend/tests/e2e_user.py', 'cleanup'], { env })
  }
})
