import { test, expect } from '@playwright/test'

test('review actions fit the screen and a failed save preserves the candidate', async ({ page }, info) => {
  const writes: string[] = []
  await page.addInitScript(() => localStorage.setItem('leadhive:onboarding:mobile@example.invalid', 'dismissed'))
  await page.route('**/api/**', route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (request.method() === 'POST') writes.push(path)
    if (path.endsWith('/reviews')) return route.fulfill({ status: 409, json: { detail: '確認結果が更新されています' } })
    const metric = { found: 1, reviewed: 0, unreviewed: 1, correct: 0, unique_correct: 0, strict_precision: null, resolved_precision: null, duplicate_rate: null, uncertain_rate: null }
    const body = path === '/api/auth/me' ? { id: 'fixture-user', email: 'mobile@example.invalid', is_admin: true }
      : path === '/api/outreach-execution-status' ? { outbound_enabled: false }
        : path === '/api/raw-benchmarks' ? [{ id: 'fixture', region: '兵庫県姫路市', industry: '美容院' }]
          : path.endsWith('/report') ? { ...metric, can_review: true, unique_candidates: 1, base_requested_count: 1, repeat_limit: 3, query_groups: [], pair_labels: {}, phase: 'PILOT', requested_count: 1, coverage: null, code_commit: 'fixture', human_review_seconds: null, error_breakdown: {}, field_completeness: {}, sources: [], queries: [] }
            : path.endsWith('/snapshots') ? [{ id: 'snapshot', candidate_key: 'candidate', snapshot_hash: 'fixture-hash', payload: { company_name: '確認用の美容院', reference_url: 'https://example.invalid/', source: 'fixture', source_keyword: '美容院' }, review: null }]
              : path.endsWith('/review-start') ? { session_id: 'fixture-session' } : []
    return route.fulfill({ json: body })
  })
  await page.goto('/#raw')
  const card = page.getByRole('article', { name: '確認する候補' })
  const confirm = card.getByRole('button', { name: '自社サイト・対象条件を確認して次へ', exact: true })
  await expect(confirm).toBeEnabled()
  await card.getByRole('button', { name: '対象外・違う', exact: true }).click()
  for (const button of await card.locator('.actions button').all()) {
    const bounds = await button.boundingBox()
    expect(bounds!.x).toBeGreaterThanOrEqual(0)
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(page.viewportSize()!.width)
    if (info.project.name === 'mobile') expect(bounds!.height).toBeGreaterThanOrEqual(44)
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  await card.getByRole('button', { name: '地域が違うと確認して次へ', exact: true }).click()
  await expect(card.getByRole('alert')).toContainText('確認結果が更新されています')
  await expect(card).toContainText('確認用の美容院')
  await expect(page.getByRole('button', { name: '送信', exact: true })).toHaveCount(0)
  expect(writes).toEqual(['/api/raw-benchmarks/snapshots/snapshot/review-start', '/api/raw-benchmarks/snapshots/snapshot/reviews'])
  await page.screenshot({ path: `test-results/review-layout-${info.project.name}.png`, fullPage: true })
})
