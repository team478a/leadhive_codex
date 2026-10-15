import { test, expect } from '@playwright/test'

test('collection progress and recent jobs stay visible when an optional report endpoint fails', async ({ page }) => {
  const email = 'operator@example.test'
  const profile = { id: 'profile-1', profile_name: 'SNS運用', search_keywords: ['SNS運用代行'], active: true }
  const project = { id: 'project-1', project_name: '大阪リスト', target_profile_id: profile.id, region: '大阪府', status: 'active' }
  const requestedCompanyList: string[] = []
  let failedReportRequests = 0
  let extractionStarted = false
  let extractionStatus = 'running'
  const writes: string[] = []
  await page.addInitScript(email => localStorage.setItem(`leadhive:onboarding:${email}`, 'dismissed'), email)
  await page.route('**/api/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (request.method() !== 'GET') writes.push(`${request.method()} ${path}`)
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
    else if (request.method() === 'POST' && path === `/api/projects/${project.id}/operations`) {
      extractionStarted = true
      expect(request.postDataJSON()).toMatchObject({ operation_type: 'extract_articles', source_operation_ids: ['operation-1'], article_limit: 20, dry_run: false })
      data = { id: 'extract-operation', project_id: project.id, operation_type: 'extract_articles', status: 'queued', processed_count: 0, total_count: 0, success_count: 0, failed_count: 0, attempt_count: 0 }
    }
    else if (path.endsWith('/operations')) data = [
      { id: 'operation-1', project_id: project.id, operation_type: 'collect_search', status: 'running', processed_count: 12, total_count: 100, success_count: 12, failed_count: 0, attempt_count: 1 },
      ...(extractionStarted ? [{ id: 'extract-operation', project_id: project.id, operation_type: 'extract_articles', status: extractionStatus, source_operation_ids: ['operation-1'], article_saved_count: 1, processed_count: 1, total_count: 1, success_count: 1, failed_count: 0, attempt_count: 1 }] : []),
    ]
    else if (path.endsWith('/collection-jobs')) data = [{
      id: 'collection-1', project_id: project.id, operation_job_id: 'operation-1', source: 'serper', status: 'completed', keyword: 'SNS運用代行', region: '大阪府',
      found_count: 12, saved_count: 8, duplicate_count: 2, excluded_count: 1, error_count: 0, processing_ms: 1200,
    }]
    else if (path.endsWith('/collection-jobs/collection-1/discovery')) data = {
      summary: { available: true, received_count: 1, captured_count: 1, omitted_count: 0, dispositions: { CAPTURED: 1 }, classifications: { ARTICLE: 1 } },
      hits: [{ id: 'hit-1', position: 1, classification: 'ARTICLE', disposition: 'CAPTURED', snapshot: { title: '合成記事', link: 'https://publisher.example/article', snippet: '記事', truncated: false } }],
    }
    else if (path.endsWith('/collection-jobs/collection-1/article-extractions')) data = { offset: 0, limit: 20, items: extractionStarted ? [{
      id: 'extraction-1', article_url: 'https://publisher.example/article', final_url: 'https://publisher.example/article', status: 'EXTRACTED', page_kind: 'LIST_ARTICLE', pattern: 'TABLE', entry_count: 1, linked_count: 1, name_only_count: 0, rejected_count: 0, warnings: [],
      entries: [{ id: 'entry-1', entry_order: 1, name: '株式会社サンプル', link_url: 'https://company.example', status: 'LINKED', reasons: [], disposition: 'SAVED', company_id: 'company-1' }],
    }] : [] }
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
  await page.getByRole('button', { name: '取得候補と未取込の理由を確認' }).click()
  await page.getByRole('button', { name: '記事から企業を抽出（最大20記事）' }).click()
  await expect(page.getByText('記事抽出中 1 / 1')).toBeVisible()
  await expect(page.getByText('株式会社サンプル')).toBeVisible()
  expect(writes).toEqual(['POST /api/projects/project-1/operations'])
  expect(requestedCompanyList).toHaveLength(0)
  extractionStatus = 'completed'
  await page.reload()
  await page.getByRole('button', { name: 'このターゲットで収集へ' }).click()
  await page.getByRole('button', { name: '取得候補と未取込の理由を確認' }).click()
  await page.getByRole('button', { name: '記事ごとの抽出結果を表示' }).click()
  await expect(page.getByText('株式会社サンプル')).toBeVisible()
})

test('background refresh identifies the endpoint when its network request fails', async ({ page }) => {
  const email = 'operator@example.test'
  const profile = { id: 'profile-1', profile_name: 'SNS運用', search_keywords: ['SNS運用代行'], active: true }
  const project = { id: 'project-1', project_name: '大阪リスト', target_profile_id: profile.id, region: '大阪府', status: 'active' }
  let failOperations = false
  await page.addInitScript(email => localStorage.setItem(`leadhive:onboarding:${email}`, 'dismissed'), email)
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (failOperations && path.endsWith('/operations')) { await route.abort('failed'); return }
    let data: unknown = []
    if (path === '/api/auth/me') data = { id: 'operator', email, is_admin: false }
    else if (path === '/api/target-profiles') data = [profile]
    else if (path === '/api/projects') data = [project]
    else if (path === '/api/dashboard') data = { total_companies: 0 }
    else if (path === '/api/outreach-execution-status') data = { outbound_enabled: false }
    else if (path.endsWith('/members')) data = [{ email, role: 'owner' }]
    else if (path.endsWith('/company-analysis-summary')) data = {
      saved: 0, webCompleted: 0, webPending: 0, webFailed: 0, aiCompleted: 0, aiPending: 0,
    }
    else if (path.endsWith('/collection-jobs')) data = []
    else if (path.endsWith('/search-schedules') || path.endsWith('/search-analytics')
      || path.endsWith('/collection-performance') || path.endsWith('/ai-review-analytics')) data = []
    await route.fulfill({ json: data })
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'このターゲットで収集へ' }).click()
  const progress = page.locator('.panel').filter({ has: page.getByRole('heading', { name: 'バックグラウンド処理', exact: true }) })
  await expect(progress).toBeVisible()
  failOperations = true
  await progress.getByRole('button', { name: '更新', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('GET /projects/:project/operations')
})

test('collection results load one server page at a time and retain exact category totals', async ({ page }, info) => {
  const email = 'operator@example.test'
  const profile = { id: 'profile-1', profile_name: 'SNS運用', search_keywords: ['SNS運用代行'], active: true }
  const project = { id: 'project-1', project_name: '大阪リスト', target_profile_id: profile.id, region: '大阪府', status: 'active' }
  const companyListRequests: string[] = []
  await page.addInitScript(email => localStorage.setItem(`leadhive:onboarding:${email}`, 'dismissed'), email)
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    const path = url.pathname
    let data: unknown = []
    if (path === '/api/auth/me') data = { id: 'operator', email, is_admin: false }
    else if (path === '/api/target-profiles') data = [profile]
    else if (path === '/api/projects') data = [project]
    else if (path === '/api/dashboard') data = { total_companies: 37 }
    else if (path === '/api/outreach-execution-status') data = { outbound_enabled: false }
    else if (path.endsWith('/members')) data = [{ email, role: 'owner' }]
    else if (path.endsWith('/company-list')) {
      companyListRequests.push(`${url.searchParams.get('offset')}:${url.searchParams.get('limit')}`)
      const excluded = url.searchParams.get('status') === 'excluded'
      const countOnly = url.searchParams.get('limit') === '1'
      const offset = Number(url.searchParams.get('offset') || 0)
      const items = countOnly ? [] : [{
        id: excluded ? 'excluded-1' : `candidate-${offset}`, project_id: project.id,
        company_name: excluded ? '対象外企業' : `候補${offset + 1}`, status: excluded ? 'excluded' : 'unreviewed',
        source: 'serper', address: '大阪府大阪市', website_url: 'https://example.test',
      }]
      data = { items, total: excluded ? 2 : 35, offset, limit: Number(url.searchParams.get('limit') || 20) }
    }
    await route.fulfill({ json: data })
  })

  await page.goto('/')
  if (info.project.name === 'mobile') await page.getByRole('button', { name: /メニュー/ }).click()
  await page.getByRole('button', { name: '④ 収集リストの確認', exact: true }).click()
  await expect(page.getByText('候補 35件 / 収集対象外 2件')).toBeVisible()
  await expect(page.getByRole('heading', { name: '候補1' })).toBeVisible()
  await expect(page.getByText('1 / 2', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '次の20件' }).click()
  await expect(page.getByRole('heading', { name: '候補21' })).toBeVisible()
  expect(companyListRequests).toContain('0:20')
  expect(companyListRequests).toContain('20:20')
  expect(companyListRequests.every(request => request.endsWith(':20') || request.endsWith(':1'))).toBeTruthy()
})
