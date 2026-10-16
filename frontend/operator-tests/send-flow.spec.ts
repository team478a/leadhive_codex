import { expect, test } from '@playwright/test'
import { navigateWorkspace } from '../tests/navigation'

test('send flow creates a template draft and opens the next stage', async ({ page }) => {
  const projectId = 'send-flow-project'
  const companyId = 'send-flow-company'
  const email = 'send-flow@example.test'
  const calls: { path: string; method: string; body: Record<string, unknown> | null }[] = []
  let createdTemplate: Record<string, unknown> | null = null
  let bulkBody: Record<string, unknown> | null = null
  let summaryRefreshAfterDraft = 0
  const summary = () => ({
    readiness_completed_at: null, target_company_count: 1,
    draft_counts: { email: bulkBody ? 1 : 0, form: 0 }, form_reviewed_count: 0,
    approval_counts: { pending: { email: 0, form: 0 }, approved_unsent: { email: 0, form: 0 } },
    today: { sent: 0, reserved: 0 }, results: { sent: 0, failed: 0, unknown: 0 },
  })
  const company = { id: companyId, project_id: projectId, company_name: '見本会社', domain: 'sample.example', email: 'contact@sample.example', do_not_contact: false }
  const pageErrors: string[] = []
  page.on('pageerror', error => pageErrors.push(error.message))
  const completedOperation = {
    id: 'send-flow-job', project_id: projectId, operation_type: 'bulk_template_drafts', status: 'completed',
    total_count: 1, processed_count: 1, success_count: 1, failed_count: 0, cancel_requested: false,
    attempt_count: 1, acknowledged_at: null, error_message: '', created_at: '2026-10-17T00:00:00Z',
    started_at: '2026-10-17T00:00:00Z', finished_at: '2026-10-17T00:00:01Z',
    bulk_template_results: { created: [companyId], skipped_existing: [], excluded: [] },
  }
  await page.addInitScript(userEmail => localStorage.setItem(`leadhive:onboarding:${userEmail}`, 'dismissed'), email)
  await page.route('**/api/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()
    const body = method === 'POST' || method === 'PUT' ? request.postDataJSON() as Record<string, unknown> : null
    calls.push({ path, method, body })
    let data: unknown = []
    if (path === '/api/auth/me') data = { id: 'send-flow-user', email, is_admin: false }
    else if (path === '/api/dashboard') data = { total_companies: 1, ranks: {}, statuses: {}, recent_jobs: [], operation_statuses: {}, unread_operation_failures: 0, recent_operations: [], overdue_followups: 0, due_today_followups: 0 }
    else if (path === '/api/outreach-execution-status') data = { outbound_enabled: false }
    else if (path === '/api/target-profiles') data = [{ id: 'send-flow-profile', profile_name: '見本', search_keywords: [], default_regions: [], active: true }]
    else if (path === '/api/projects') data = [{ id: projectId, project_name: '送信フロー確認', target_profile_id: 'send-flow-profile', region: '全国', sales_objective: '確認', status: 'active' }]
    else if (path === `/api/projects/${projectId}/members`) data = [{ id: 'membership', email, role: 'owner' }]
    else if (path === `/api/projects/${projectId}/send-flow-summary`) {
      if (bulkBody) summaryRefreshAfterDraft += 1
      data = summary()
    }
    else if (path === `/api/projects/${projectId}/outreach-templates` && method === 'GET') data = createdTemplate ? [createdTemplate] : []
    else if (path === `/api/projects/${projectId}/outreach-templates` && method === 'POST') {
      createdTemplate = { ...body, id: 'send-flow-template', project_id: projectId, created_by_user_id: 'send-flow-user', created_at: '2026-10-17T00:00:00Z', updated_at: '2026-10-17T00:00:00Z' }
      data = createdTemplate
    } else if (path.endsWith('/company-list')) data = { items: [company], total: 1, offset: 0, limit: 20 }
    else if (path === `/api/projects/${projectId}/form-dm-readiness`) data = { counts: { NO_FORM_DRAFT: 0 }, total: 0, offset: 0, limit: 20, items: [], last_aggregated_at: null, active_job: null, read_only: true, external_requests: 0 }
    else if (path === `/api/projects/${projectId}/outreach-drafts/bulk-from-template` && method === 'POST') {
      bulkBody = body
      data = { ...completedOperation, status: 'queued', processed_count: 0, success_count: 0, bulk_template_results: { created: [], skipped_existing: [], excluded: [] } }
    } else if (path === `/api/projects/${projectId}/operations`) data = [completedOperation]
    else if (path.endsWith('/form-operations')) data = { counts: {}, total: 0, items: [] }
    else if (path.endsWith('/bulk-send-preview')) data = { items: [], skipped: {}, email_enabled: false, form_enabled: false }
    else if (path === '/api/form-dispatch-limits') data = { daily_limit: 100, hourly_limit: 10, minimum_interval_seconds: 60, site_interval_seconds: 300, paused: false, version: 1, can_manage: true, execution_enabled: false }
    else if (path.endsWith('/form-approval-daily-summary')) data = { daily_limit: 100, started_last_24h: 0, approved_unsent: 0, pending_approvals: 0, remaining_quota: 100, paused: false, within_send_window: true }
    await route.fulfill({ json: data })
  })

  await page.goto('/')
  await navigateWorkspace(page, '▶ 送信の準備・実行')
  const sales = page.getByRole('region', { name: '営業作業', exact: true })
  await expect(sales.getByRole('heading', { name: '1. 文面テンプレート' })).toBeVisible()
  await expect(sales.getByRole('region', { name: '送信先と文面の準備' })).toHaveCount(0)
  await sales.getByLabel('テンプレート名').fill('初回案内')
  await sales.getByLabel('件名').fill('ご案内')
  await sales.getByLabel('本文').fill('{{会社名}}様\nご案内が不要の場合はご返信ください。')
  await expect(sales.getByText('見本会社', { exact: true }).last()).toBeVisible()
  await sales.getByRole('button', { name: 'テンプレートを保存' }).click()
  await expect(sales.getByRole('status')).toContainText('テンプレートを保存しました')
  await sales.getByRole('button', { name: '次へ：送信先と文面を用意' }).click()
  const draftStage = sales.getByRole('region', { name: '2. 送信先と文面を用意' })
  await expect(draftStage.getByText('見本会社')).toBeVisible()
  await draftStage.getByRole('checkbox').check()
  await draftStage.getByRole('button', { name: '選択した1社に下書きを作成' }).click()
  await expect(sales.getByRole('button', { name: /4\. 承認/ })).toHaveAttribute('aria-expanded', 'true', { timeout: 10_000 })
  expect(bulkBody).toMatchObject({ template_id: 'send-flow-template', channel: 'email', company_ids: [companyId] })
  await expect.poll(() => summaryRefreshAfterDraft).toBeGreaterThan(0)
  await expect(sales.getByRole('button', { name: /2\. 送信先と文面を用意 1社/ })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width)
  expect(calls.some(call => call.method === 'POST' && call.path.endsWith('/outreach-drafts/bulk-from-template'))).toBe(true)
  expect(pageErrors).toEqual([])
})
