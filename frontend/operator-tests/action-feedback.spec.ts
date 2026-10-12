import { test, expect } from '@playwright/test'

test('Collection feedback stays in the mobile viewport and links to progress', async ({ page }, info) => {
  const email = 'operator@example.test'
  let releaseRequest: () => void = () => {}
  const pending = new Promise<void>(resolve => { releaseRequest = resolve })
  let attempts = 0
  let queued = false
  const profile = { id: 'profile-1', profile_name: 'SNS運用', search_keywords: ['SNS運用代行'], active: true }
  const project = { id: 'project-1', project_name: '大阪リスト', target_profile_id: profile.id, region: '大阪府', status: 'active' }
  await page.addInitScript(email => localStorage.setItem(`leadhive:onboarding:${email}`, 'dismissed'), email)
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    let data: unknown = []
    if (path === '/api/auth/me') data = { id: 'operator', email, is_admin: false }
    else if (path === '/api/target-profiles') data = [profile]
    else if (path === '/api/projects') data = [project]
    else if (path === '/api/dashboard') data = { total_companies: 0 }
    else if (path === '/api/outreach-execution-status') data = { outbound_enabled: false }
    else if (path.endsWith('/members')) data = [{ email, role: 'owner' }]
    else if (path.endsWith('/operations') && method === 'POST') {
      attempts++
      if (attempts === 1) {
        await pending
        queued = true
        data = { id: 'operation-1', status: 'queued' }
      } else {
        await route.fulfill({ status: 503, json: { detail: '収集を登録できませんでした。時間をおいて再試行してください。' } })
        return
      }
    } else if (path.endsWith('/operations') && queued) data = [{ id: 'operation-1', operation_type: 'collect_search', status: 'queued', processed_count: 0, total_count: 100, success_count: 0, failed_count: 0, attempt_count: 0 }]
    await route.fulfill({ json: data })
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'このターゲットで収集へ' }).click()
  const start = page.getByRole('button', { name: '収集を開始', exact: true })
  await start.scrollIntoViewIfNeeded()
  await start.click()
  const feedback = page.getByRole('complementary', { name: '操作結果' })
  await expect(feedback.getByRole('status')).toHaveText('収集を受け付けています…')
  await expect(page.getByRole('button', { name: '登録中…' })).toBeDisabled()
  if (info.project.name === 'mobile') {
    await expect(feedback).toBeInViewport({ ratio: 1 })
    expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(200)
  }
  releaseRequest()
  await expect(feedback.getByRole('status')).toHaveText('検索収集をバックグラウンド処理へ登録しました。')
  if (info.project.name === 'mobile') await expect(feedback).toBeInViewport({ ratio: 1 })
  await feedback.screenshot({ path: info.outputPath('collection-feedback.png') })
  await feedback.getByRole('button', { name: '進捗を見る' }).click()
  await expect(feedback).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'バックグラウンド処理', exact: true })).toBeInViewport()
  expect(attempts).toBe(1)
  await start.click()
  await expect(feedback.getByRole('alert')).toContainText('収集を登録できませんでした。')
  if (info.project.name === 'mobile') await expect(feedback).toBeInViewport({ ratio: 1 })
  await expect(feedback.getByRole('button', { name: '進捗を見る' })).toHaveCount(0)
  await feedback.getByRole('button', { name: '通知を閉じる' }).click()
  await expect(feedback).toHaveCount(0)
  expect(attempts).toBe(2)
})


for (const kind of ['web_analysis', 'ai_analysis'] as const) {
  test(`${kind} stays inverted while queued/running and refresh recovers from errors`, async ({ page }, info) => {
    const email = 'operator@example.test'
    const profile = { id: 'profile-1', profile_name: '購入者', search_keywords: ['カフェ'], active: true }
    const project = { id: 'project-1', project_name: '収集済みリスト', target_profile_id: profile.id, region: '大阪府', status: 'active' }
    let status = ''
    let posts = 0
    let failRefresh = false
    const operation = () => ({ id: 'analysis-1', project_id: project.id, operation_type: kind, status, processed_count: 0, total_count: 2, success_count: 0, failed_count: 0, attempt_count: 0 })
    await page.addInitScript(email => localStorage.setItem(`leadhive:onboarding:${email}`, 'dismissed'), email)
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname
      let data: unknown = []
      if (path === '/api/auth/me') data = { id: 'operator', email, is_admin: false }
      else if (path === '/api/target-profiles') data = [profile]
      else if (path === '/api/projects') data = [project]
      else if (path === '/api/dashboard') data = { total_companies: 2 }
      else if (path === '/api/outreach-execution-status') data = { outbound_enabled: false }
      else if (path.endsWith('/members')) data = [{ email, role: 'owner' }]
      else if (path.endsWith('/companies')) data = [{ id: 'company-1', company_name: 'カフェ', source: 'serper', website_url: 'https://example.test', analysis_status: kind === 'ai_analysis' ? 'completed' : 'pending', ai_status: 'pending' }]
      else if (path.endsWith('/operations') && route.request().method() === 'POST') {
        posts++; status = 'queued'; data = operation()
      } else if (path.endsWith('/operations')) {
        if (failRefresh) { await route.fulfill({ status: 503, json: { detail: '更新に失敗しました。' } }); return }
        data = status ? [operation()] : []
      }
      await route.fulfill({ json: data })
    })
    await page.goto('/')
    await page.getByRole('button', { name: 'このターゲットで収集へ' }).click()
    await expect(page.getByRole('button', { name: 'Web解析を開始', exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: '3. リスト解析', exact: true }).click()
    await expect(page.getByLabel('解析する収集リスト')).toHaveValue(project.id)
    await expect(page.getByRole('button', { name: '収集を開始', exact: true })).toHaveCount(0)
    expect(posts).toBe(0)
    const idle = kind === 'web_analysis' ? 'Web解析を開始' : 'AI判定を開始'
    const queued = kind === 'web_analysis' ? 'Web解析 待機中…' : 'AI判定 待機中…'
    const running = kind === 'web_analysis' ? 'Web解析中…' : 'AI判定中…'
    const startPanel = page.getByRole('region', { name: '解析開始', exact: true })
    await expect(startPanel.getByRole('button', { name: idle, exact: true })).toBeVisible()
    expect(await page.getByRole('button', { name: idle, exact: true }).evaluate(button => {
      const progress = [...document.querySelectorAll('h2')].find(h => h.textContent === 'バックグラウンド処理')
      return !!progress && !!(button.compareDocumentPosition(progress) & Node.DOCUMENT_POSITION_FOLLOWING)
    })).toBeTruthy()
    await page.getByRole('button', { name: idle, exact: true }).click()
    const active = page.getByRole('button', { name: queued, exact: true })
    await expect(active).toBeDisabled()
    await expect(active).toHaveClass(/analysis-active/)
    await expect(active).toHaveCSS('background-color', 'rgb(255, 255, 255)')
    await expect(active).toHaveAttribute('aria-busy', 'true')
    await page.getByRole('button', { name: '通知を閉じる', exact: true }).click()
    await active.screenshot({ path: info.outputPath(`${kind}-active.png`) })
    const progress = page.locator('div.panel').filter({ has: page.getByRole('heading', { name: 'バックグラウンド処理', exact: true }) })
    const refresh = progress.getByRole('button', { name: '更新', exact: true })
    await expect(refresh).toBeEnabled()
    failRefresh = true
    await refresh.click()
    await expect(page.getByRole('alert')).toContainText('更新に失敗')
    await expect(refresh).toBeEnabled()
    await page.getByRole('button', { name: '通知を閉じる', exact: true }).click()
    failRefresh = false; status = 'running'
    await refresh.click()
    await expect(page.getByRole('button', { name: running, exact: true })).toHaveClass(/analysis-active/)
    await expect(page.getByRole('status')).toContainText('最新の収集・解析状況に更新')
    await page.getByRole('button', { name: '通知を閉じる', exact: true }).click()
    status = 'completed'
    await refresh.click()
    await expect(page.getByRole('button', { name: idle, exact: true })).toBeEnabled()
    await expect(page.getByRole('button', { name: idle, exact: true })).not.toHaveClass(/analysis-active/)
    expect(posts).toBe(1)
    await page.getByRole('button', { name: '2. 収集開始', exact: true }).click()
    await expect(page.getByLabel('プロジェクト', { exact: true })).toHaveValue(project.id)
    await expect(page.getByRole('button', { name: idle, exact: true })).toHaveCount(0)
    expect(posts).toBe(1)
  })
}
