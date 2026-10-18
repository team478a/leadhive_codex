import { navigateWorkspace } from './navigation'
import { execFileSync } from 'node:child_process'
import { test, expect } from '@playwright/test'

test('reanalyzes only the selected readiness reason and shows bounded job progress', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'approval-fixture'], { env: process.env, encoding: 'utf8' })) as { project_id: string }
  const baseJob = {
    id: 'reanalysis-job', project_id: fixture.project_id, operation_type: 'form_intelligence',
    status: 'queued', total_count: 500, processed_count: 0, success_count: 0, failed_count: 0,
    cancel_requested: false, attempt_count: 0, acknowledged_at: null, error_message: '',
    created_at: new Date().toISOString(), started_at: null, finished_at: null,
    readiness_reanalysis_reason: 'MULTIPART_ONLY', readiness_reanalysis_matched_count: 520,
  }
  const readiness = {
    counts: { MULTIPART_ONLY: 520, CONFIRMATION_PAGE: 2, NO_FORM_DRAFT: 0 },
    total: 520, offset: 0, limit: 20, items: [],
    last_aggregated_at: new Date().toISOString(), last_aggregated_by_commit: 'abc1234',
    last_aggregated_by_host: 'worker-1', active_job: null, active_reanalysis_job: null,
    read_only: true, external_requests: 0,
  }
  let posted = false
  let statusReads = 0
  await page.route(`**/api/projects/${fixture.project_id}/send-flow-summary`, route => route.fulfill({ json: {
    readiness_completed_at: null, target_company_count: 0,
    draft_counts: { email: 0, form: 0 }, form_reviewed_count: 0,
    approval_counts: { pending: { email: 0, form: 0 }, approved_unsent: { email: 0, form: 0 } },
    today: { sent: 0, reserved: 0 }, results: { sent: 0, failed: 0, unknown: 0 },
  } }))
  await page.route(`**/api/projects/${fixture.project_id}/outreach-templates`, route => route.fulfill({ json: [] }))
  await page.route(`**/api/projects/${fixture.project_id}/company-list?**`, route => route.fulfill({ json: { items: [], total: 0, offset: 0, limit: 20 } }))
  await page.route(`**/api/projects/${fixture.project_id}/form-dm-readiness**`, async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.method() === 'POST' && url.pathname.endsWith('/reanalyze')) {
      posted = true
      expect(url.searchParams.get('reason')).toBe('MULTIPART_ONLY')
      await route.fulfill({ status: 202, json: baseJob })
      return
    }
    if (url.pathname.includes('/reanalysis-jobs/')) {
      statusReads += 1
      const progress = statusReads === 1
        ? { ...baseJob, status: 'running', processed_count: 2, started_at: new Date().toISOString() }
        : { ...baseJob, status: 'completed', processed_count: 500, success_count: 498, failed_count: 2, finished_at: new Date().toISOString() }
      await route.fulfill({ json: progress })
      return
    }
    await route.fulfill({ json: readiness })
  })

  await page.goto('/')
  await page.getByLabel('メールアドレス').fill(process.env.E2E_EMAIL!)
  await page.getByLabel('パスワード').fill(process.env.E2E_PASSWORD!)
  await page.getByRole('button', { name: 'ログインする', exact: true }).click()
  await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
  await navigateWorkspace(page, '▶ 送信の準備・実行')
  await page.evaluate(projectId => localStorage.setItem(`leadhive:send-channel:${projectId}`, 'form'), fixture.project_id)
  await page.getByLabel('対象プロジェクト').selectOption(fixture.project_id)
  const preparation = page.getByRole('region', { name: '送信先と文面の準備' })
  await preparation.getByText('フォームの送信可否集計・詳細').click()
  const readinessPanel = page.getByRole('region', { name: 'フォームDM送信可否' })
  const reanalyzeButton = readinessPanel.getByRole('button', { name: 'この500社を再解析（全520社）' })
  await expect(reanalyzeButton).toBeVisible()
  await reanalyzeButton.click()
  await expect(readinessPanel.getByText(/フォーム再解析中（multipart形式のみ（添付欄なし））：2\/500社/)).toBeVisible({ timeout: 8_000 })
  await expect(readinessPanel.getByText(/フォーム再解析が完了しました：498社成功、2社失敗/)).toBeVisible({ timeout: 8_000 })
  expect(posted).toBe(true)
  expect(statusReads).toBeGreaterThanOrEqual(2)
})
