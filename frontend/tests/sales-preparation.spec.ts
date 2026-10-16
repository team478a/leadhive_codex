import { navigateWorkspace } from './navigation'
import { test, expect } from '@playwright/test'

test('sales preparation can queue cancel and resume without sending', async ({ page }, testInfo) => {
  await page.goto('/')
  await page.getByLabel('メールアドレス').fill(process.env.E2E_EMAIL!)
  await page.getByLabel('パスワード', { exact: true }).fill(process.env.E2E_PASSWORD!)
  await page.getByRole('button', { name: 'ログインする', exact: true }).click()
  const later = page.getByRole('button', { name: 'あとで見る', exact: true })
  await expect(later).toBeVisible()
  await later.click()
  const profiles = await page.request.get('/api/target-profiles')
  const profileId = (await profiles.json())[0].id
  const result = await page.request.post('/api/projects', { data: {
    project_name: `営業準備 ${testInfo.project.name}`, target_profile_id: profileId,
    sales_objective: 'No external access or sending', region: '全国', status: 'draft',
  } })
  expect(result.status()).toBe(201)
  const projectId = (await result.json()).id
  const jobId = 'sales-preparation-e2e'
  let preparationCreated = false
  let preparationStatus: 'queued' | 'cancelled' = 'queued'
  const preparation = () => ({
    job: {
      id: jobId, project_id: projectId, operation_type: 'prepare_outreach', status: preparationStatus,
      total_count: 1, processed_count: 0, success_count: 0, failed_count: 0,
      cancel_requested: false, attempt_count: 0, acknowledged_at: null,
      error_message: '', created_at: '', started_at: null, finished_at: null,
    },
    counts: { pending: 1, running: 0, ready: 0, review: 0, blocked: 0, error: 0 },
    item_count: 1, used_search_requests: 0, used_ai_requests: 0,
    max_search_requests: 0, max_ai_requests: 0,
  })
  await page.route(`**/api/projects/${projectId}/sales-preparation`, async route => {
    if (route.request().method() === 'POST') {
      preparationCreated = true
      preparationStatus = 'queued'
      await route.fulfill({ status: 202, json: {} })
    } else {
      await route.fulfill({ json: preparationCreated ? [preparation()] : [] })
    }
  })
  await page.route(`**/api/operations/${jobId}/cancel`, async route => {
    preparationStatus = 'cancelled'
    await route.fulfill({ json: {} })
  })
  await page.route(`**/api/sales-preparation/${jobId}/resume`, async route => {
    preparationStatus = 'queued'
    await route.fulfill({ json: {} })
  })
  await page.route(`**/api/sales-preparation/${jobId}/items**`, route => route.fulfill({ json: {
    total: 1, offset: 0, limit: 20, items: [{
      id: 'preparation-item', company_id: 'preparation-company', company_name: 'preparation.example',
      status: 'pending', stage: 'pending', reason: '', channel: '', draft_id: null, details: {},
    }],
  } }))
  await page.reload()
  await navigateWorkspace(page, '▶ 送信の準備・実行')
  await page.getByRole('combobox', { name: '対象プロジェクト', exact: true }).selectOption(projectId)
  const draftStage = page.getByRole('region', { name: '2. 送信先と文面を用意', exact: true })
  await draftStage.getByRole('button', { name: /2\. 送信先と文面を用意/ }).click()
  const draftPanel = draftStage.getByRole('region', { name: '送信先と文面の準備' })
  await draftPanel.getByLabel('文面の作り方').selectOption('ai')
  const panel = page.getByRole('region', { name: '営業準備', exact: true })
  await panel.getByLabel('検索回数の上限').fill('0')
  await panel.getByLabel('AI回数の上限').fill('0')
  await panel.getByRole('checkbox', { name: '会社別の文面を作成する' }).uncheck()
  await panel.getByRole('button', { name: '営業準備を開始', exact: true }).click()
  await expect(panel.getByText('待機中 · 0/1件', { exact: true })).toBeVisible()
  await panel.getByRole('button', { name: '営業準備を停止', exact: true }).click()
  await expect(panel.getByText('停止済み · 0/1件', { exact: true })).toBeVisible()
  await panel.getByRole('button', { name: '未処理から再開', exact: true }).click()
  await expect(panel.getByText('待機中 · 0/1件', { exact: true })).toBeVisible()
  await panel.getByText(/企業ごとの準備状況/).click()
  await expect(panel.getByText('preparation.example', { exact: true })).toBeVisible()
  expect(await panel.getByRole('button', { name: /送信/ }).count()).toBe(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await panel.getByRole('button', { name: '営業準備を停止', exact: true }).click()
})
