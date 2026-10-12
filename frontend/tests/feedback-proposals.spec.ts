import { test, expect } from '@playwright/test'
import { navigateWorkspace } from './navigation'

test('Admin reviews research proposals, restores decisions and sees unavailable evaluation on desktop/mobile', async ({ page }, testInfo) => {
  let version = 0
  let state = 'PROPOSED'
  let failed = false
  let empty = true
  const history: { version: number; state: string; reason: string; actor_id: string; created_at: string; restored_from: number | null }[] = []
  const comparison = { status: 'NO_ELIGIBLE_EVALUATION', regressions: 0, changed_samples: 0, improved_samples: 0, evaluation_eligible_samples: 0, proposal: { pattern: 'CONTACT_URL_MISIDENTIFIED', failed_samples: 2 } }
  const item = () => ({ id: 'proposal-1', version, state, input_hash: 'a'.repeat(64), history, report: { comparison } })
  const calls: string[] = []
  await page.addInitScript(() => localStorage.setItem('leadhive:onboarding:admin@example.test', 'dismissed'))
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    calls.push(`${method} ${path}`)
    let data: unknown = []
    let status = 200
    if (path === '/api/auth/me') data = { id: 'admin-1', email: 'admin@example.test', is_admin: true }
    else if (path === '/api/projects') data = [{ id: 'project-1', project_name: '評価用Project', status: 'active', region: '全国' }]
    else if (path.endsWith('/members')) data = [{ email: 'admin@example.test', role: 'owner' }]
    else if (path === '/api/dashboard') data = { total_companies: 0 }
    else if (path.endsWith('/feedback-evaluations')) data = { items: [], truncated: false }
    else if (path.endsWith('/feedback-proposals')) data = { items: empty ? [] : [item()], truncated: false }
    else if (path.endsWith('/analyze')) { empty = false; data = { event_count: 3, unresolved_samples: 1 } }
    else if (path.endsWith('/decisions') || path.endsWith('/restore')) {
      const body = route.request().postDataJSON()
      if (failed) { status = 409; data = { detail: '他の操作で判断が更新されました。再読み込みしてください。' } }
      else {
        expect(body.expected_version).toBe(version)
        state = body.restore_version ? history.find(h => h.version === body.restore_version)!.state : body.state
        version += 1
        history.push({ version, state, reason: body.reason, actor_id: 'admin-1', created_at: '2026-10-12T00:00:00Z', restored_from: body.restore_version || null })
        data = item()
      }
    }
    await route.fulfill({ status, json: data })
  })
  await page.goto('/')
  await navigateWorkspace(page, '改善候補')
  const panel = page.getByRole('region', { name: '改善候補の確認' })
  await expect(panel).toContainText('改善候補はありません')
  await panel.getByRole('button', { name: '保存済み評価を集計' }).click()
  await expect(panel).toContainText('比較可能な保存候補なし')
  await expect(panel.getByRole('button', { name: '採用', exact: true })).toBeDisabled()
  await panel.getByLabel('判断理由').fill('候補を研究対象として採用')
  await panel.getByRole('button', { name: '採用', exact: true }).click()
  await expect(panel).toContainText('判断版 1')
  await panel.getByLabel('判断理由').fill('今回は保留')
  await panel.getByRole('button', { name: '保留', exact: true }).click()
  await panel.getByText('判断履歴と出所', { exact: true }).click()
  await panel.getByLabel('判断理由').fill('判断版1へ復元')
  await panel.getByRole('button', { name: '版1の判断に戻す' }).click()
  await expect(panel).toContainText('判断版 3')
  await expect(panel).toContainText('版1から復元')
  await page.reload()
  await navigateWorkspace(page, '改善候補')
  await expect(panel).toContainText('判断版 3')
  failed = true
  await panel.getByLabel('判断理由').fill('競合確認')
  await panel.getByRole('button', { name: '却下', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('再読み込み')
  await expect(panel).toContainText('判断版 3')
  const width = await page.evaluate(() => document.documentElement.scrollWidth)
  expect(width).toBeLessThanOrEqual(page.viewportSize()!.width)
  await panel.screenshot({ path: testInfo.outputPath('feedback-proposals.png') })
  expect(calls.filter(c => c.startsWith('POST') && !/\/(analyze|decisions|restore)$/.test(c))).toEqual([])
})
