import { test, expect } from '@playwright/test'

test('runtime status distinguishes application and browser workers', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('leadhive:onboarding:runtime@example.invalid', 'dismissed'))
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    const body = path === '/api/auth/me' ? { id: 'runtime-user', email: 'runtime@example.invalid', is_admin: true }
      : path === '/api/runtime-info' ? { api_commit: 'abc1234', workers: [
        { instance_id: 'main-worker-1', worker_type: 'application', commit_id: 'abc1234', host_name: 'api-host', last_seen_at: '2026-10-17T00:00:00Z' },
        { instance_id: 'browser-worker-1', worker_type: 'browser', commit_id: 'def5678', host_name: 'browser-host', last_seen_at: '2026-10-17T00:00:00Z' },
      ] }
        : path === '/api/dashboard' ? { total_companies: 0 }
          : path === '/api/outreach-execution-status' ? { outbound_enabled: false } : []
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
  })

  await page.goto('/')

  const status = page.getByRole('region', { name: '稼働バージョン' })
  await expect(status).toContainText('本体ワーカー版: abc1234 · api-host')
  await expect(status).toContainText('ブラウザーワーカー版: def5678 · browser-host')
  await expect(status.getByRole('alert')).toHaveText('APIとワーカーの版が違います。ワーカーを更新してください')
})
