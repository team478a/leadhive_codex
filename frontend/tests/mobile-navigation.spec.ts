import { test, expect } from '@playwright/test'
import { navigateWorkspace } from './navigation'

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('leadhive:onboarding:mobile@example.invalid', 'dismissed'))
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    const body = path === '/api/auth/me' ? { id: 'fixture-user', email: 'mobile@example.invalid', is_admin: true }
      : path === '/api/dashboard' ? { total_companies: 0 }
        : path === '/api/outreach-execution-status' ? { outbound_enabled: false } : []
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
  })
})

test('content is visible on arrival and menu closes after navigation', async ({ page }, info) => {
  await page.goto('/')
  const menu = page.getByRole('button', { name: 'メニュー', exact: true })
  const nav = page.getByRole('navigation', { name: 'メインナビゲーション' })
  await expect(page.getByRole('heading', { name: 'プロジェクト', exact: true, level: 1 })).toBeVisible()
  if (info.project.name === 'mobile') {
    await expect(menu).toHaveAttribute('aria-expanded', 'false')
    await expect(nav).toBeHidden()
    const heading = await page.getByRole('heading', { name: 'プロジェクト', exact: true, level: 1 }).boundingBox()
    expect(heading!.y).toBeLessThan(page.viewportSize()!.height / 2)
  } else { await expect(nav).toBeVisible(); await expect(menu).toBeHidden() }
  await navigateWorkspace(page, '◎ ターゲットプロファイル')
  await expect(page.getByRole('heading', { name: 'ターゲットプロファイル', level: 1 })).toBeVisible()
  if (info.project.name === 'mobile') await expect(nav).toBeHidden()
  await navigateWorkspace(page, '▦ プロジェクト')
  await expect(page.getByRole('heading', { name: 'プロジェクト', level: 1 })).toBeVisible()
  await page.screenshot({ path: `test-results/navigation-${info.project.name}.png` })
})

test('short phone viewport keeps menu toggle reachable and footer scrollable', async ({ page }, info) => {
  test.skip(info.project.name !== 'mobile')
  await page.setViewportSize({ width: 390, height: 390 })
  await page.goto('/')
  const menu = page.getByRole('button', { name: 'メニュー', exact: true })
  await menu.click()
  await expect(menu).toHaveAttribute('aria-expanded', 'true')
  const panel = page.locator('#workspace-navigation-panel')
  const dimensions = await panel.evaluate(el => ({ height: el.clientHeight, content: el.scrollHeight, overflow: getComputedStyle(el).overflowY }))
  expect(dimensions.content).toBeGreaterThan(dimensions.height)
  expect(dimensions.overflow).toBe('auto')
  await page.getByRole('button', { name: 'ログアウト', exact: true }).scrollIntoViewIfNeeded()
  await expect(menu).toBeInViewport()
  await expect(page.getByRole('button', { name: 'ログアウト', exact: true })).toBeInViewport()
  await menu.click()
  await expect(panel).toBeHidden()
  await menu.click()
  await page.keyboard.press('Escape')
  await expect(panel).toBeHidden()
  await expect(menu).toBeFocused()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})

test('raw entry uses the same collapsed navigation', async ({ page }, info) => {
  await page.goto('/#raw')
  await expect(page.getByRole('heading', { name: '収集結果の確認', level: 1 })).toBeVisible()
  if (info.project.name === 'mobile') await expect(page.getByRole('navigation', { name: 'メインナビゲーション' })).toBeHidden()
  await navigateWorkspace(page, '▦ プロジェクト')
  await expect(page.getByRole('heading', { name: 'プロジェクト', level: 1 })).toBeVisible()
})

test('navigation waits for authenticated workspace instead of mistaking loading for a closed menu', async ({ page }) => {
  let releaseAuth!: () => void
  const authGate = new Promise<void>(resolve => { releaseAuth = resolve })
  await page.route('**/api/auth/me', async route => {
    await authGate
    await route.fulfill({ json: { id: 'fixture-user', email: 'mobile@example.invalid', is_admin: true } })
  })
  await page.goto('/')
  await expect(page.getByText('読み込み中…', { exact: true })).toBeVisible()
  const navigate = navigateWorkspace(page, '◎ ターゲットプロファイル')
  // No navigation control exists until auth completes, on either screen size.
  await expect(page.locator('.sidebar')).toHaveCount(0)
  releaseAuth()
  await navigate
  await expect(page.getByRole('heading', { name: 'ターゲットプロファイル', level: 1 })).toBeVisible()
})

test('a stale initial settings response cannot overwrite newly saved sending hours', async ({ page }) => {
  await page.route('**/api/admin/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/sending-window')) return route.fallback()
    const json = path.endsWith('/inbound-emails') ? []
      : path.endsWith('/application-settings') ? { public_app_url: '', openai_model: '', gbizinfo_api_base_url: '', settings_encryption_ready: false }
        : path.endsWith('/form-sender-settings') ? { company_name: '', contact_name: '', email: '', phone: '', updated_at: null } : null
    return route.fulfill({ json })
  })
  let releaseFirst!: () => void
  let firstFinished!: () => void
  const firstGate = new Promise<void>(resolve => { releaseFirst = resolve })
  const firstDone = new Promise<void>(resolve => { firstFinished = resolve })
  let reads = 0
  await page.route('**/api/admin/sending-window', async route => {
    if (route.request().method() === 'PUT') {
      return route.fulfill({ json: { ...route.request().postDataJSON(), timezone: 'Asia/Tokyo', allowed_now: false } })
    }
    const first = ++reads === 1
    if (first) await firstGate
    await route.fulfill({ json: { enabled: false, start_minute: 480, end_minute: 1200, timezone: 'Asia/Tokyo', allowed_now: true } })
    if (first) firstFinished()
  })
  await page.goto('/')
  await navigateWorkspace(page, '⚙ 運用設定')
  const panel = page.getByRole('region', { name: '送信可能時間', exact: true })
  const checkbox = panel.getByRole('checkbox')
  await expect(checkbox).toBeEnabled()
  await checkbox.check()
  await panel.getByRole('button', { name: '送信可能時間を保存', exact: true }).click()
  await expect(panel).toContainText('毎日 08:00〜20:00')
  releaseFirst()
  await firstDone
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  await expect(checkbox).toBeChecked()
  await expect(panel).toContainText('毎日 08:00〜20:00')
})
