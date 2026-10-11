import { navigateWorkspace } from './navigation'
import { test, expect } from '@playwright/test'

test('Human sales NG registers exclusion, preserves quality and reasons without sending', async ({ page }, testInfo) => {
  test.setTimeout(120_000)
  await page.goto('/')
  await page.getByLabel('メールアドレス').fill(process.env.E2E_EMAIL!)
  await page.getByLabel('パスワード').fill(process.env.E2E_PASSWORD!)
  await page.getByRole('button', { name: 'ログインする', exact: true }).click()
  const guide = page.getByRole('dialog', { name: '3ステップで始めましょう' })
  try {
    await guide.getByRole('button', { name: 'あとで見る' }).waitFor({ state: 'visible', timeout: 5000 })
    await guide.getByRole('button', { name: 'あとで見る' }).click()
  } catch { /* This account may have already dismissed onboarding. */ }
  const profilesResponse = await page.request.get('/api/target-profiles')
  expect(profilesResponse.ok()).toBeTruthy()
  const profiles = await profilesResponse.json()
  const projectResponse = await page.request.post('/api/projects', { data: {
    project_name: `手動営業NG ${testInfo.project.name}`, target_profile_id: profiles[0].id,
    sales_objective: 'Synthetic no-send test', region: '東京都', status: 'active',
  } })
  expect(projectResponse.ok()).toBeTruthy()
  const project = await projectResponse.json()
  try {
    const imported = await page.request.post(`/api/projects/${project.id}/collection-jobs/urls`, { data: {
      urls: [`https://manual-sales-ng-${testInfo.project.name}.example`],
    } })
    expect(imported.ok()).toBeTruthy()
    const company = (await (await page.request.get(`/api/projects/${project.id}/companies`)).json())[0]
    // Existing restriction must not be removed; adding an NG reason cannot promote quality.
    const existing = await page.request.patch(`/api/companies/${company.id}/contact-control`, { data: {
      do_not_contact: true, exclusion_reason: '既存の連絡拒否', contact_quality_status: 'observed',
    } })
    expect(existing.ok()).toBeTruthy()
    await page.reload()
    await expect(page.getByRole('heading', { name: `手動営業NG ${testInfo.project.name}`, exact: true })).toBeVisible()
    await navigateWorkspace(page, '▤ 企業一覧')
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(project.id)
    await page.getByTestId('company-list-item').getByRole('button', { name: '詳細', exact: true }).click()
    const ng = page.getByRole('region', { name: '営業NG登録' })
    await expect(ng.getByRole('button', { name: '営業NGリストへ移す' })).toBeDisabled()
    await ng.getByLabel('営業NGの理由').fill('問い合わせページに営業禁止と明記')
    const request = page.waitForRequest(request => request.url().includes(`/companies/${company.id}/contact-control`) && request.method() === 'PATCH')
    await ng.getByRole('button', { name: '営業NGリストへ移す' }).click()
    const payload = (await request).postDataJSON()
    expect(payload.do_not_contact).toBe(true)
    expect(payload.contact_quality_status).toBe('observed')
    expect(payload.exclusion_reason).toContain('既存の連絡拒否')
    await expect(ng.getByText('営業NGリストに登録済み', { exact: true })).toBeVisible()
    await expect(ng.getByRole('button', { name: '営業NGリストへ移す' })).toHaveCount(0)
    const stored = await (await page.request.get(`/api/companies/${company.id}`)).json()
    expect(stored.do_not_contact).toBe(true)
    expect(stored.status).toBe('excluded')
    expect(stored.contact_quality_status).toBe('observed')
    const report = await (await page.request.get(`/api/projects/${project.id}/form-readiness?category=prohibited&offset=0&limit=25`)).json()
    expect(report.items.map((item: { company_id: string }) => item.company_id)).toContain(company.id)
    expect(report.items[0].permission.status).toBe('PROHIBITED')
    await page.reload()
    await navigateWorkspace(page, '▤ 企業一覧')
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(project.id)
    await page.getByTestId('company-list-item').getByRole('button', { name: '詳細', exact: true }).click()
    await expect(page.getByRole('region', { name: '営業NG登録' })).toContainText('問い合わせページに営業禁止と明記')
  } finally {
    expect((await page.request.delete(`/api/projects/${project.id}`)).ok()).toBeTruthy()
  }
})
