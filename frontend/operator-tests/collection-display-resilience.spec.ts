import { test, expect } from '@playwright/test'

test('collection progress and recent jobs stay visible when an optional report endpoint fails', async ({ page }) => {
  const email = 'operator@example.test'
  const profile = { id: 'profile-1', profile_name: 'SNS運用', search_keywords: ['SNS運用代行'], active: true }
  const project = { id: 'project-1', project_name: '大阪リスト', target_profile_id: profile.id, region: '大阪府', status: 'active' }
  const requestedCompanyList: string[] = []
  let failedReportRequests = 0
  await page.addInitScript(email => localStorage.setItem(`leadhive:onboarding:${email}`, 'dismissed'), email)
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: unknown = []
    if (path === '/api/auth/me') data = { id: 'operator', email, is_admin: false }
    else if (path === '/api/target-profiles') data = [profile]
    else if (path === '/api/projects') data = [project]
    else if (path === '/api/dashboard') data = { total_companies: 3 }
    else if (path === '/api/outreach-execution-status') data = { outbound_enabled: false }
    else if (path.endsWith('/members')) data = [{ email, role: 'owner' }]
    else if (path.endsWith('/company-analysis-summary')) data = {
      saved: 3, webCompleted: 0, webPending: 3, webFailed: 0, aiCompleted: 0, aiPending: 0,
    }
    else if (path.endsWith('/operations')) data = [{
      id: 'operation-1', project_id: project.id, operation_type: 'collect_search', status: 'running',
      processed_count: 12, total_count: 100, success_count: 12, failed_count: 0, attempt_count: 1,
    }]
    else if (path.endsWith('/collection-jobs')) data = [{
      id: 'collection-1', source: 'serper', status: 'completed', keyword: 'SNS運用代行', region: '大阪府',
      found_count: 12, saved_count: 8, duplicate_count: 2, excluded_count: 1, error_count: 0, processing_ms: 1200,
    }]
    else if (path.endsWith('/external-presence-report')) data = { required_platforms: [], candidates: [] }
    else if (path.endsWith('/search-schedules')) {
      failedReportRequests++
      await route.fulfill({ status: 503, json: { detail: '定期収集レポートを取得できません。' } })
      return
    }
    else if (path.endsWith('/companies')) requestedCompanyList.push(path)
    await route.fulfill({ json: data })
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'このターゲットで収集へ' }).click()
  await expect(page.getByRole('heading', { name: 'バックグラウンド処理', exact: true })).toBeVisible()
  await expect(page.getByText('12 / 100 件（成功 12・失敗 0・試行 1）')).toBeVisible()
  await expect(page.locator('body')).toContainText('SNS運用代行 / 大阪府')
  await expect.poll(() => failedReportRequests).toBeGreaterThan(0)
  await expect(page.getByText('12 / 100 件（成功 12・失敗 0・試行 1）')).toBeVisible()
  expect(requestedCompanyList).toHaveLength(0)
})
