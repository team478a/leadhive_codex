import { test, expect, type Page } from '@playwright/test'

async function setup(page: Page, count = 2, role = 'editor', openGuide = true, archivedCount = 0) {
  const mutations: string[] = []
  const projects = Array.from({ length: count }, (_, index) => ({ id: `project-${index}`, project_name: `担当プロジェクト${index + 1}`, region: '大阪府', status: index < archivedCount ? 'archived' : 'draft', sales_objective: '公開情報だけで提案', target_profile_id: 'profile' }))
  await page.addInitScript(() => localStorage.setItem('leadhive:onboarding:operator@example.test', 'dismissed'))
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() !== 'GET') mutations.push(path)
    let body: unknown = []
    if (path.startsWith('/api/projects/') && route.request().method() === 'PUT') {
      const project = projects.find(item => path === `/api/projects/${item.id}`)!
      Object.assign(project, route.request().postDataJSON())
      body = project
    }
    if (path === '/api/auth/me') body = { id: 'operator', email: 'operator@example.test', is_admin: false }
    else if (path === '/api/projects') body = projects
    else if (path === '/api/target-profiles') body = [{ id: 'profile', profile_name: '確認用プロファイル', active: true, default_regions: ['大阪府'] }]
    else if (path.endsWith('/members')) body = [{ email: 'operator@example.test', role }]
    else if (path === '/api/dashboard') body = { total_companies: 10 }
    else if (path === '/api/outreach-execution-status') body = { outbound_enabled: false }
    else if (path.endsWith('/company-list')) body = { items: [], total: 0 }
    else if (path.endsWith('/data-quality') || path.endsWith('/deal-pipeline') || path.endsWith('/analysis-refresh-schedule')) body = null
    else if (path.endsWith('/form-readiness')) body = { counts: {}, items: [], total: 0, company_total: 0 }
    await route.fulfill({ json: body })
  })
  await page.goto('/')
  await expect(page.getByRole('button', { name: '担当者の作業ガイドを開く' })).toBeVisible()
  if (openGuide) {
    await page.getByRole('button', { name: '担当者の作業ガイドを開く' }).click()
    await expect(page.getByRole('heading', { name: '今日の作業を始める' })).toBeVisible()
  }
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

async function openInstallation(page: Page) {
  const menu = page.getByRole('button', { name: /メニュー/ })
  if (await menu.isVisible()) await menu.click()
  await page.getByRole('button', { name: '↓ 導入・ダウンロード' }).click()
  await expect(page.getByRole('heading', { name: '利用する場所を選ぶ' })).toBeVisible()
}

test('installation page has safe unavailable downloads, mobile navigation and no writes', async ({ page }) => {
  const mutations = await setup(page, 2, 'viewer', false)
  await openInstallation(page)
  await expect(page.getByText('配布リンクは準備中です。管理者に配布ファイルを確認してください。')).toHaveCount(2)
  await expect(page.getByRole('link', { name: 'クラウド版を開く ↗' })).toHaveCount(0)
  await expect(page.getByText(/http:\/\/localhost:8787/)).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: test.info().outputPath('installation.png'), fullPage: true })
  await page.getByRole('button', { name: '担当者の作業ガイドへ' }).click()
  await expect(page.getByRole('heading', { name: '今日の作業を始める' })).toBeVisible()
  expect(mutations).toEqual([])
})

test('configured downloads are distinct and unsafe links are not rendered', async ({ page }) => {
  await page.route('**/installation-links.json', route => route.fulfill({ json: {
    cloud: { url: 'https://cloud.example.test/' },
    local: { url: 'https://downloads.example.test/local.zip', version: 'test-1', sha256: 'a'.repeat(64) },
    pc_input: { url: 'javascript:alert(1)' },
  } }))
  const mutations = await setup(page, 2, 'editor', false)
  await openInstallation(page)
  await expect(page.getByRole('link', { name: 'ローカル版をダウンロード ↗' })).toHaveAttribute('href', 'https://downloads.example.test/local.zip')
  await expect(page.getByRole('link', { name: 'クラウド版を開く ↗' })).toHaveAttribute('href', 'https://cloud.example.test/')
  await expect(page.getByRole('link', { name: 'PC入力専用ツールをダウンロード ↗' })).toHaveCount(0)
  await page.getByText('ファイル確認用 SHA-256').click()
  await expect(page.locator('code')).toContainText('a'.repeat(64))
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  expect(mutations).toEqual([])
})

test('link load failure preserves instructions and can retry', async ({ page }) => {
  let failed = true
  await page.route('**/installation-links.json', route => failed
    ? route.fulfill({ status: 503, body: 'unavailable' })
    : route.fulfill({ json: { pc_input: { url: 'https://downloads.example.test/input.zip' } } }))
  await setup(page, 2, 'editor', false)
  await openInstallation(page)
  await expect(page.getByText(/配布リンクを読み込めませんでした/)).toBeVisible()
  failed = false
  await page.getByRole('button', { name: '再読み込み', exact: true }).click()
  await expect(page.getByRole('link', { name: 'PC入力専用ツールをダウンロード ↗' })).toHaveAttribute('href', 'https://downloads.example.test/input.zip')
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

test('archived projects are hidden by default, can be read and do not trigger writes', async ({ page }) => {
  const mutations = await setup(page, 2, 'viewer', false, 1)
  await expect(page.getByRole('heading', { name: '担当プロジェクト1', exact: true })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: '担当プロジェクト2', exact: true })).toBeVisible()
  await page.getByRole('checkbox', { name: 'アーカイブを表示（1件）' }).check()
  await expect(page.getByRole('heading', { name: '担当プロジェクト1', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: test.info().outputPath('archives-visible.png'), fullPage: true })
  await page.locator('article').filter({ has: page.getByRole('heading', { name: '担当プロジェクト1', exact: true }) }).getByRole('button', { name: '企業一覧', exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'プロジェクト', exact: true })).toHaveValue('project-0')
  await page.reload()
  await expect(page.getByRole('heading', { name: '担当プロジェクト1', exact: true })).toHaveCount(0)
  expect(mutations).toEqual([])
})

test('all archived shows an empty operational list and excludes archives from work guide', async ({ page }) => {
  const mutations = await setup(page, 2, 'editor', false, 2)
  await expect(page.getByRole('heading', { name: '運用中のプロジェクトはありません' })).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('archives-hidden.png'), fullPage: true })
  await page.getByRole('button', { name: '担当者の作業ガイドを開く' }).click()
  await expect(page.getByRole('button', { name: 'プロジェクトを作る', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '企業収集へ' })).toBeDisabled()
  expect(mutations).toEqual([])
})

test('owner restores an archived project using existing status editor', async ({ page }) => {
  const mutations = await setup(page, 1, 'owner', false, 1)
  await page.getByRole('checkbox', { name: 'アーカイブを表示（1件）' }).check()
  await page.getByRole('button', { name: '編集', exact: true }).click()
  await expect(page.getByLabel('営業目的', { exact: true })).toHaveValue('公開情報だけで提案')
  await page.getByLabel('ステータス', { exact: true }).selectOption('active')
  await page.getByRole('button', { name: '保存する', exact: true }).click()
  await expect(page.getByText('保存しました。', { exact: true })).toBeVisible()
  await page.getByRole('checkbox', { name: 'アーカイブを表示（0件）' }).uncheck()
  await expect(page.getByRole('heading', { name: '担当プロジェクト1', exact: true })).toBeVisible()
  await expect(page.getByText('進行中', { exact: true })).toBeVisible()
  expect(mutations).toEqual(['/api/projects/project-0'])
})
