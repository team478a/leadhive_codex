import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { test, expect } from '@playwright/test'

test('raw observations explain target truncation without claiming official confirmation', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const env = { ...process.env, E2E_EMAIL: `e2e-discovery-${randomBytes(8).toString('hex')}@example.com`, E2E_PASSWORD: randomBytes(24).toString('hex') }
  execFileSync(python, ['../backend/tests/e2e_user.py', 'create'], { env })
  const writes: string[] = []
  page.on('request', request => {
    if (request.method() !== 'GET' && /\/(operations|approve|dispatch|send|search|test-send)([/?]|$)/.test(request.url())) writes.push(request.url())
  })
  try {
    const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'destination-selection-fixture'], { env, encoding: 'utf8' })) as { project_id: string }
    const jobId = 'dfe24dde-5a02-4734-a3cc-c1ac889f7465'
    await page.route(`**/api/projects/${fixture.project_id}/operations`, route => route.fulfill({ json: [{
      id: 'scheduler-fixture', project_id: fixture.project_id, operation_type: 'collect_search', status: 'completed',
      total_count: 500, processed_count: 49, success_count: 49, failed_count: 0, attempt_count: 1,
      cancel_requested: false, acknowledged_at: null, error_message: '', created_at: '2026-10-09T00:00:00Z',
      collection_progress: { scheduler_version: 'fair-v1', target_count: 500, collected_count: 49, requests: 50, request_budget: 50,
        stop_reason: 'REQUEST_BUDGET_REACHED', coverage_status: 'PARTIAL', planned_queries: 20, unsearched_queries: 0,
        pending_queries: 20, failed_queries: 0, capped_queries: 0, unknown_attempts: 1 },
    }] }))
    await page.route(`**/api/projects/${fixture.project_id}/collection-jobs?*`, route => route.fulfill({ json: [{
      id: jobId, project_id: fixture.project_id, source: 'serper', keyword: 'SNS', region: '大阪', status: 'completed',
      found_count: 10, saved_count: 1, duplicate_count: 0, excluded_count: 0, error_count: 0,
      processing_ms: 2, error_message: '', created_at: '2026-10-09T00:00:00Z', finished_at: '2026-10-09T00:00:01Z',
    }] }))
    await page.route(`**/api/collection-jobs/${jobId}/discovery?*`, route => route.fulfill({ json: {
      summary: { available: true, received_count: 10, captured_count: 10, omitted_count: 0, dispositions: { SAVED: 1, TARGET_LIMIT: 9 } },
      hits: Array.from({ length: 10 }, (_, i) => ({ id: String(i), position: i + 1, classification: 'OFFICIAL_SITE_CANDIDATE', disposition: i === 0 ? 'SAVED' : 'TARGET_LIMIT', snapshot: { title: `合成候補 ${i}`, link: `https://candidate${i}.example.test`, snippet: '<script>untrusted()</script>', truncated: false } })),
    } }))
    await page.goto('/')
    await page.getByLabel('メールアドレス').fill(env.E2E_EMAIL)
    await page.getByLabel('パスワード').fill(env.E2E_PASSWORD)
    await page.getByRole('button', { name: 'ログインする', exact: true }).click()
    await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
    await page.getByRole('button', { name: '⌕ 企業収集', exact: true }).click()
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(fixture.project_id)
    await expect(page.getByText('新規候補 49 / 500 件・検索 50 / 50 回・検索上限に到達')).toBeVisible()
    await expect(page.getByText(/検索語 20 件・未検索 0 件・継続候補 20 件/)).toBeVisible()
    await expect(page.getByText(/一部の検索が残っています。/)).toBeVisible()
    await expect(page.getByText('結果不明の検索 1 回も検索予算に含めています。')).toBeVisible()
    await page.getByRole('button', { name: '取得候補と未取込の理由を確認' }).click()
    await expect(page.getByText('検索応答 10 件 / 記録 10 件 / 記録上限による省略 0 件')).toBeVisible()
    await expect(page.getByText('目標件数を超えたため未取込 9', { exact: true })).toBeVisible()
    await expect(page.getByText('10. 合成候補 9', { exact: true })).toBeVisible()
    await expect(page.getByText('<script>untrusted()</script>', { exact: true }).first()).toBeVisible()
    await expect(page.getByRole('link', { name: '取得したページを確認 ↗' }).last()).toHaveAttribute('href', 'https://candidate9.example.test/')
    await expect(page.getByText('公式サイト候補（未確認） · 企業候補として保存', { exact: true })).toBeVisible()
    expect(writes).toEqual([])
  } finally {
    execFileSync(python, ['../backend/tests/e2e_user.py', 'cleanup'], { env })
  }
})
