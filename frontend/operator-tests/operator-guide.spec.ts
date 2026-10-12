import { test, expect, type Page } from '@playwright/test'

async function setup(page: Page, count = 2, role = 'editor') {
  const mutations: string[] = []
  const projects = Array.from({ length: count }, (_, index) => ({ id: `project-${index}`, project_name: `担当プロジェクト${index + 1}`, region: '大阪府', status: 'draft', sales_objective: '公開情報だけで提案', target_profile_id: 'profile' }))
  await page.addInitScript(() => localStorage.setItem('leadhive:onboarding:operator@example.test', 'dismissed'))
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() !== 'GET') mutations.push(path)
    let body: unknown = []
    if (path === '/api/auth/me') body = { id: 'operator', email: 'operator@example.test', is_admin: false }
    else if (path === '/api/projects') body = projects
    else if (path.endsWith('/members')) body = [{ email: 'operator@example.test', role }]
    else if (path === '/api/dashboard') body = { total_companies: 10 }
    else if (path === '/api/outreach-execution-status') body = { outbound_enabled: false }
    else if (path.endsWith('/company-list')) body = { items: [], total: 0 }
    else if (path.endsWith('/data-quality') || path.endsWith('/deal-pipeline') || path.endsWith('/analysis-refresh-schedule')) body = null
    else if (path.endsWith('/form-readiness')) body = { counts: {}, items: [], total: 0, company_total: 0 }
    await route.fulfill({ json: body })
  })
  await page.goto('/')
  await page.getByRole('button', { name: '担当者の作業ガイドを開く' }).click()
  await expect(page.getByRole('heading', { name: '今日の作業を始める' })).toBeVisible()
  return mutations
}

test('explicit project selection, safe guidance, navigation preserves project and never writes', async ({ page }) => {
  const mutations = await setup(page)
  await expect(page.getByRole('button', { name: '企業一覧へ', exact: true })).toBeDisabled()
  await page.getByLabel('作業するプロジェクト').selectOption('project-1')
  await expect(page.getByRole('button', { name: '企業収集へ' })).toBeEnabled()
  await expect(page.getByText('入力成功は送信成功や承認済みを意味しません。', { exact: false })).toBeVisible()
  await page.getByText('PCでの操作手順', { exact: true }).click()
  await expect(page.getByText(/Start-Live-Input.cmd/)).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('guide-selected.png'), fullPage: true })
  await page.getByRole('button', { name: '企業一覧へ', exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'プロジェクト', exact: true })).toHaveValue('project-1')
  await page.getByText('担当者向け：この画面での作業順', { exact: true }).click()
  await expect(page.getByText(/入力成功を送信済みとして記録しない/)).toBeVisible()
  const list = page.getByRole('heading', { name: '企業一覧', exact: true }).last()
  await expect(list).toBeVisible()
  expect(await list.evaluate(element => !!(element.compareDocumentPosition([...document.querySelectorAll('h2')].find(item => item.textContent === '配信・追客・管理')!) & Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true)
  expect(mutations).toEqual([])
})

test('viewer can navigate to results but not start collection', async ({ page }) => {
  const mutations = await setup(page, 1, 'viewer')
  await expect(page.getByRole('button', { name: '企業収集へ' })).toBeDisabled()
  await expect(page.getByRole('button', { name: '企業一覧へ', exact: true })).toBeEnabled()
  await expect(page.getByText(/閲覧のみです/)).toBeVisible()
  expect(mutations).toEqual([])
})

test('empty projects and mobile layout offer next action without overflow', async ({ page }) => {
  await setup(page, 0)
  await expect(page.getByRole('button', { name: 'プロジェクトを作る', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '企業一覧へ', exact: true })).toBeDisabled()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: test.info().outputPath('guide-empty.png'), fullPage: true })
})
