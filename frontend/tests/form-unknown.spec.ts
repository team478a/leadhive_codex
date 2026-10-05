import { test, expect } from '@playwright/test'

test('unknown form results are visible without retry or Codex send actions', async ({ page }, info) => {
  await page.goto('/')
  await page.getByLabel('メールアドレス').fill(process.env.E2E_EMAIL!)
  await page.getByLabel('パスワード').fill(process.env.E2E_PASSWORD!)
  await page.getByRole('button', { name: 'ログインする', exact: true }).click()
  await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
  const profiles = await (await page.request.get('/api/target-profiles')).json()
  const name = `結果不明 ${info.project.name}`
  const response = await page.request.post('/api/projects', { data: {
    project_name: name, target_profile_id: profiles[0].id, sales_objective: '送信なし画面検証', region: '全国', status: 'draft',
  } })
  expect(response.ok()).toBeTruthy()
  const project = await response.json()
  await page.route(`**/api/projects/${project.id}/form-delivery-batches`, route => route.fulfill({ json: [{
    id: 'fixture-batch', project_id: project.id, template_id: 'fixture-template', status: 'completed',
    operation_job_id: null, created_at: '2026-10-05T00:00:00Z', updated_at: '2026-10-05T00:00:00Z',
    items: [{ id: 'fixture-item', company_id: 'fixture-company', company_name: '結果確認が必要な会社',
      draft_id: null, form_delivery_id: null, status: 'unknown', reason: '結果不明', submitted_at: null,
      created_at: '2026-10-05T00:00:00Z', form_url: 'https://example.com/contact' }],
  }] }))
  await page.reload()
  await page.getByRole('article').filter({ has: page.getByRole('heading', { name, exact: true }) }).getByRole('button', { name: '企業一覧', exact: true }).click()
  const batch = page.getByRole('article').filter({ hasText: '一括フォームDM' })
  await expect(batch.getByRole('alert')).toContainText('結果不明・再送禁止')
  await expect(batch.getByRole('button', { name: '再試行待ちに戻す' })).toHaveCount(0)
  await expect(batch.getByText('Codex支援が必要です', { exact: false })).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width)
})
