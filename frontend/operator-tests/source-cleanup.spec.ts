import { test, expect } from '@playwright/test'
import { navigateWorkspace } from '../tests/navigation'

for (const role of ['owner', 'viewer'] as const) {
  test(`Known media cleanup and restoration for ${role}`, async ({ page }) => {
    const email = 'cleanup@example.test'
    const project = { id: 'project-1', project_name: '収集リスト', region: '大阪府', status: 'active' }
    const company = { id: 'media-1', project_id: project.id, company_name: 'Retty', website_url: 'https://retty.me/', status: 'unreviewed', address: '', updated_at: '2026-10-12T00:00:00Z' }
    const calls: string[] = []
    let failCleanup = false
    await page.addInitScript(email => localStorage.setItem(`leadhive:onboarding:${email}`, 'dismissed'), email)
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname
      const method = route.request().method()
      if (method === 'POST') calls.push(path)
      let data: unknown = []
      if (path === '/api/auth/me') data = { id: 'operator', email, is_admin: false }
      else if (path === '/api/projects') data = [project]
      else if (path.endsWith('/members')) data = [{ email, role }]
      else if (path === '/api/dashboard') data = { total_companies: 1 }
      else if (path === '/api/outreach-execution-status') data = { outbound_enabled: false }
      else if (path.endsWith('/company-list')) {
        const excluded = new URL(route.request().url()).searchParams.get('status') === 'excluded'
        const visible = company.status === 'excluded' ? excluded : !excluded
        data = { items: visible ? [company] : [], total: visible ? 1 : 0 }
      } else if (path.endsWith('/companies')) data = [company]
      else if (path.endsWith('/source-exclusions/cleanup') && method === 'POST') {
        if (failCleanup) { await route.fulfill({ status: 503, json: { detail: '整理テストエラー' } }); return }
        expect(route.request().postDataJSON()).toEqual({ company_ids: ['media-1'] })
        company.status = 'excluded'; data = { excluded_ids: ['media-1'], protected_ids: [] }
      } else if (path.endsWith('/cleanup/media-1/restore') && method === 'POST') {
        expect(route.request().postDataJSON()).toEqual({ expected_updated_at: company.updated_at })
        company.status = 'unreviewed'; data = { restored: true }
      } else if (path.endsWith('/cleanup/media-1')) data = { restorable: true }
      else if (path.endsWith('/collection-feedback')) data = { items: [] }
      await route.fulfill({ json: data })
    })
    await page.goto('/')
    await navigateWorkspace(page, '④ 収集リストの確認')
    const results = page.getByRole('region', { name: '収集リストの確認' })
    await expect(results.getByRole('heading', { name: 'Retty', exact: true })).toBeVisible()
    const organize = results.getByRole('button', { name: '既知のまとめサイトを整理' })
    if (role === 'viewer') {
      await expect(organize).toBeDisabled(); expect(calls).toEqual([])
    } else {
      await organize.click()
      await expect(results.getByRole('status')).toContainText('1件を収集対象外へ移しました')
      await expect(results.getByRole('heading', { name: 'Retty', exact: true })).toHaveCount(0)
      await results.getByRole('button', { name: '収集対象外を見る' }).click()
      await expect(results.getByRole('heading', { name: 'Retty', exact: true })).toBeVisible()
      await results.getByRole('button', { name: '取得結果を確認する' }).click()
      await results.getByRole('button', { name: '自動除外を取り消して候補に戻す' }).click()
      await results.getByRole('button', { name: '候補に戻る', exact: true }).click()
      await expect(results.getByRole('heading', { name: 'Retty', exact: true })).toBeVisible()
      expect(calls).toEqual(['/api/projects/project-1/source-exclusions/cleanup', '/api/projects/project-1/source-exclusions/cleanup/media-1/restore'])
      failCleanup = true
      await organize.click()
      await expect(results.getByRole('alert')).toContainText('整理テストエラー')
      await expect(results.getByRole('status')).toContainText('整理済み0件')
      await expect(results.getByRole('heading', { name: 'Retty', exact: true })).toBeVisible()
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  })
}
