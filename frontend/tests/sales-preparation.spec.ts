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
  const imported = await page.request.post(`/api/projects/${projectId}/collection-jobs/urls`, {
    data: { urls: ['https://preparation.example'] },
  })
  expect(imported.ok()).toBeTruthy()
  await page.reload()
  await navigateWorkspace(page, '⌕ 企業収集')
  await page.getByLabel('プロジェクト', { exact: true }).selectOption(projectId)
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
  await panel.getByText('企業ごとの準備状況', { exact: true }).click()
  await expect(panel.getByText('preparation.example', { exact: true })).toBeVisible()
  expect(await panel.getByRole('button', { name: /送信/ }).count()).toBe(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await panel.getByRole('button', { name: '営業準備を停止', exact: true }).click()
})
