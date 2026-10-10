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
