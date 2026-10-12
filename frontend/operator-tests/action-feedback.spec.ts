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
