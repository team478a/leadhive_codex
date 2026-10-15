import { test, expect } from '@playwright/test'
import { navigateWorkspace } from './navigation'

test('Admin records immutable evaluations, compares nulls, explains and reloads on desktop/mobile', async ({ page }, testInfo) => {
  const metrics = { collection_precision: null, official_site_accuracy: null, contact_discovery_rate: 0, misclassification_rate: 1, paired_samples: 1, api_cost: null, production_processing_seconds: null }
  const evaluations: Record<string, unknown>[] = []
  let failed = false
  const posts: string[] = []
  await page.addInitScript(() => localStorage.setItem('leadhive:onboarding:admin@example.test', 'dismissed'))
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    let data: unknown = []
    let status = 200
    if (method === 'POST') posts.push(path)
    if (path === '/api/auth/me') data = { id: 'admin', email: 'admin@example.test', is_admin: true }
    else if (path === '/api/projects') data = [{ id: 'project', project_name: '合成評価Project', status: 'active', region: '全国' }]
    else if (path.endsWith('/members')) data = [{ email: 'admin@example.test', role: 'owner' }]
    else if (path === '/api/dashboard') data = { total_companies: 0 }
    else if (path.endsWith('/feedback-proposals/status')) data = { enabled: true, runtime_applied: false }
    else if (path.endsWith('/feedback-proposals')) data = { items: [], truncated: false }
    else if (path.endsWith('/feedback-evaluations')) {
      if (method === 'GET') data = { items: evaluations, truncated: false }
      else {
        const body = route.request().postDataJSON()
        expect(new Date(body.start).getTime()).toBeLessThan(new Date(body.end).getTime())
        const item = {
          id: `evaluation-${evaluations.length + 1}`, version: 0, created_by: 'admin', created_at: '2026-10-12T08:00:00Z', previous_id: body.previous_id, notes: [],
          report: { period: { start_inclusive: body.start, end_exclusive: body.end }, review_events: 2, evaluation_samples: 1, unresolved_samples: 0, checkpoint_hash: 'b'.repeat(64), input_hash: 'a'.repeat(64), metric_definition: 'feedback-lab-v1', metrics },
          comparison: body.previous_id ? { before: metrics, observed_deltas: { collection_precision: null, official_site_accuracy: null, contact_discovery_rate: 0, misclassification_rate: 0 }, limitations: ['NOT_APPLIED', 'VERSION_UNKNOWN', 'COHORT_CHANGED'] } : null,
        }
        evaluations.unshift(item); data = item
      }
    } else if (path.endsWith('/notes')) {
      if (failed) { status = 409; data = { detail: '理由が更新されています。再読み込みしてください。' } }
      else {
        const body = route.request().postDataJSON()
        const item = evaluations.find(r => path.includes(`/${r.id}/`))!
        expect(body.expected_version).toBe(item.version)
        item.version = Number(item.version) + 1
        ;(item.notes as unknown[]).push({ version: item.version, ...body, actor_id: 'admin', created_at: '2026-10-12T08:01:00Z' })
        data = item
      }
    }
    await route.fulfill({ status, json: data })
  })
  await page.goto('/')
  await navigateWorkspace(page, '改善候補')
  const panel = page.getByRole('region', { name: '評価履歴', exact: true })
  await expect(panel).toContainText('評価履歴はありません')
  await panel.getByLabel('評価開始日時').fill('2026-10-12T00:00')
  await panel.getByLabel('評価終了日時').fill('2026-10-11T00:00')
  await expect(panel.getByRole('button', { name: 'この期間の評価を保存' })).toBeDisabled()
  await panel.getByLabel('評価終了日時').fill('2026-10-13T00:00')
  await panel.getByRole('button', { name: 'この期間の評価を保存' }).click()
  await expect(panel).toContainText('固定評価区分 1件')
  await expect(panel).toContainText('未測定')
  await panel.getByLabel('比較する評価').selectOption('evaluation-1')
  await panel.getByRole('button', { name: 'この期間の評価を保存' }).click()
  await expect(panel).toContainText('評価対象が変わった')
  await expect(panel).toContainText('差 未測定')
  const article = panel.locator('article').first()
  await article.getByLabel('改善を確認できない理由').selectOption('NOT_APPLIED')
  await article.getByLabel('理由の説明').fill('まだ本番の設定は反映していない')
  await article.getByRole('button', { name: '理由を記録' }).click()
  await article.getByText('評価の出所と理由の履歴', { exact: true }).click()
  await expect(article).toContainText('版1: 本番へ未反映')
  await expect(article).toContainText('まだ本番の設定は反映していない')
  await page.reload()
  await navigateWorkspace(page, '改善候補')
  const reloaded = panel.locator('article').first()
  await reloaded.getByText('評価の出所と理由の履歴', { exact: true }).click()
  await expect(reloaded).toContainText('版1: 本番へ未反映')
  failed = true
  await reloaded.getByLabel('理由の説明').fill('競合確認')
  await reloaded.getByRole('button', { name: '理由を記録' }).click()
  await expect(panel.getByRole('alert')).toContainText('再読み込み')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width)
  await panel.screenshot({ path: testInfo.outputPath('evaluation-history.png') })
  expect(posts.every(p => /\/feedback-evaluations(\/evaluation-\d+\/notes)?$/.test(p))).toBe(true)
})
