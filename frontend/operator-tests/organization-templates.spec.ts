import { expect, test } from '@playwright/test'
import { navigateWorkspace } from '../tests/navigation'

test('shared template is configured once in organization settings', async ({ page }) => {
  let saved: Record<string, unknown> | null = null
  await page.addInitScript(() => localStorage.setItem('leadhive:onboarding:owner@example.test', 'dismissed'))
  await page.route('**/api/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()
    let data: unknown = []
    let status = 200
    if (path === '/api/auth/me') data = { id: 'owner-1', email: 'owner@example.test', is_admin: false }
    else if (path === '/api/outreach-execution-status') data = { outbound_enabled: false }
    else if (path === '/api/dashboard') data = { total_companies: 0, ranks: {}, statuses: {}, recent_jobs: [], operation_statuses: {}, unread_operation_failures: 0, recent_operations: [], overdue_followups: 0, due_today_followups: 0 }
    else if (path === '/api/target-profiles') data = []
    else if (path === '/api/projects') data = []
    else if (path === '/api/organizations') data = [{ id: 'organization-1', name: '共通設定テスト', role: 'owner', status: 'active' }]
    else if (path === '/api/organizations/organization-1/members') data = [{ id: 'member-1', user_id: 'owner-1', email: 'owner@example.test', role: 'owner' }]
    else if (path === '/api/organizations/organization-1/suppression-entries') data = { items: [] }
    else if (path === '/api/organizations/organization-1/outreach-templates' && method === 'GET') data = saved ? [saved] : []
    else if (path === '/api/organizations/organization-1/outreach-templates' && method === 'POST') {
      saved = {
        ...request.postDataJSON(), id: 'shared-template-1', project_id: null,
        organization_id: 'organization-1', scope: 'organization', created_by_user_id: 'owner-1',
        created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z',
      }
      data = saved
      status = 201
    }
    await route.fulfill({ status, json: data })
  })

  await page.goto('/')
  await navigateWorkspace(page, '利用企業設定')
  await expect(page.getByRole('heading', { name: '利用企業設定', exact: true })).toBeVisible()
  const panel = page.getByRole('region', { name: '共通文面テンプレート' })
  await panel.getByLabel('テンプレート名').fill('OEM共通フォーム')
  await panel.getByLabel('本文').fill('お問い合わせです。今後のご案内が不要な場合はご連絡ください。')
  await panel.getByRole('button', { name: '共通テンプレートを保存' }).click()
  await expect(panel.getByRole('status')).toContainText('全プロジェクトで選択できます')
  await expect(panel.getByLabel('既存の共通テンプレート')).toHaveValue('shared-template-1')
})
