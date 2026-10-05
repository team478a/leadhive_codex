import { execFileSync } from 'node:child_process'
import { test, expect, type Page } from '@playwright/test'

async function dismissGuide(page: Page) {
  const laterButton = page.getByRole('dialog', { name: '3ステップで始めましょう' })
    .getByRole('button', { name: 'あとで見る' })
  try {
    await laterButton.waitFor({ state: 'visible', timeout: 10_000 })
    await laterButton.click()
  } catch {
    // The guide is already dismissed for this account.
  }
}

async function login(page: Page, email: string, password: string) {
  await page.goto('/')
  await page.getByLabel('メールアドレス').fill(email)
  await page.getByLabel('パスワード').fill(password)
  await page.getByRole('button', { name: 'ログインする', exact: true }).click()
  await dismissGuide(page)
  await expect(page.getByRole('heading', { name: 'プロジェクト', exact: true })).toBeVisible()
}

test('Form Intelligence profiles, correction and viewer mode', async ({ page }, testInfo) => {
  test.setTimeout(120_000)
  await login(page, process.env.E2E_EMAIL!, process.env.E2E_PASSWORD!)

  const profilesResponse = await page.request.get('/api/target-profiles')
  expect(profilesResponse.ok()).toBeTruthy()
  const targetProfiles = await profilesResponse.json()
  const projectName = `フォーム画面確認 ${testInfo.project.name}`
  const projectResponse = await page.request.post('/api/projects', {
    data: {
      project_name: projectName,
      target_profile_id: targetProfiles[0].id,
      sales_objective: '事業提携のご提案',
      region: '東京都',
      status: 'active',
    },
  })
  expect(projectResponse.ok()).toBeTruthy()
  const project = await projectResponse.json()
  const domain = `form-e2e-${testInfo.project.name}.example`
  const collectionResponse = await page.request.post(
    `/api/projects/${project.id}/collection-jobs/urls`,
    { data: { urls: [`https://${domain}`] } },
  )
  expect(collectionResponse.ok()).toBeTruthy()
  const companiesResponse = await page.request.get(`/api/projects/${project.id}/companies`)
  expect(companiesResponse.ok()).toBeTruthy()
  const company = (await companiesResponse.json())[0]

  const python = process.env.PYTHON || (process.platform === 'win32'
    ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  execFileSync(python, ['../backend/tests/e2e_form_intelligence.py', 'seed', company.id], {
    env: process.env,
  })

  await page.reload()
  await dismissGuide(page)
  const projectCard = page.getByRole('article').filter({
    has: page.getByRole('heading', { name: projectName, exact: true }),
  })
  await projectCard.getByRole('button', { name: '企業一覧' }).click()
  const companyRow = page.getByRole('row').filter({ hasText: domain })
  await expect(companyRow.getByText('準備完了', { exact: true })).toBeVisible()
  await companyRow.getByRole('button', { name: '詳細' }).click()

  const formPanel = page.getByRole('heading', { name: 'フォーム事前解析' })
    .locator('xpath=ancestor::section[1]')
  const profileCards = formPanel.locator('.form-profile-card')
  await expect(profileCards).toHaveCount(2)
  await expect(profileCards.filter({ hasText: '優先フォーム' }).getByText('送信準備完了')).toBeVisible()
  const captchaCard = profileCards.filter({ hasText: 'hCaptcha' })
  await expect(captchaCard.getByText('要確認', { exact: true })).toBeVisible()
  await captchaCard.getByRole('button', { name: '優先フォームにする' }).click()
  await expect(page.getByText('優先フォームを変更しました。')).toBeVisible()

  const departmentMapping = formPanel.getByLabel('部署コードの標準マッピング')
  await departmentMapping.selectOption('department')
  await formPanel.getByLabel('部署コードの推奨値').fill('営業企画')
  await departmentMapping.locator('xpath=ancestor::tr')
    .getByRole('button', { name: '修正を保存' }).click()
  await expect(page.getByText('フォーム項目の判定を修正しました。')).toBeVisible()
  await expect(departmentMapping).toHaveValue('department')
  await expect(captchaCard.getByText('MANUAL', { exact: true })).toBeVisible()
  const contactMethod = formPanel.getByLabel('連絡方法の連絡方法')
  await expect(contactMethod).toHaveValue('')
  await contactMethod.selectOption('m')
  await contactMethod.locator('xpath=ancestor::tr').getByRole('button', { name: '修正を保存' }).click()
  await expect(contactMethod.locator('xpath=ancestor::tr').getByText('MANUAL', { exact: true })).toBeVisible()
  await expect(contactMethod).toHaveValue('m')
  await formPanel.getByText(/解析ログ/).click()
  await expect(formPanel.getByText('manual_corrected', { exact: true })).toHaveCount(2)

  const memberResponse = await page.request.post(`/api/projects/${project.id}/members`, {
    data: { email: process.env.E2E_MEMBER_EMAIL, role: 'viewer' },
  })
  expect(memberResponse.ok()).toBeTruthy()
  await page.getByRole('button', { name: 'ログアウト', exact: true }).click()
  await login(page, process.env.E2E_MEMBER_EMAIL!, process.env.E2E_MEMBER_PASSWORD!)
  const viewerProjectCard = page.getByRole('article').filter({
    has: page.getByRole('heading', { name: projectName, exact: true }),
  })
  await viewerProjectCard.getByRole('button', { name: '企業一覧' }).click()
  await page.getByRole('row').filter({ hasText: domain }).getByRole('button', { name: '詳細' }).click()
  const viewerPanel = page.getByRole('heading', { name: 'フォーム事前解析' })
    .locator('xpath=ancestor::section[1]')
  await expect(viewerPanel.getByText('閲覧者は解析結果を確認できます。', { exact: false })).toBeVisible()
  await expect(viewerPanel.getByRole('button', { name: '再解析' })).toBeDisabled()
  await expect(viewerPanel.getByRole('button', { name: '優先フォームにする' })).toBeDisabled()
  await expect(viewerPanel.getByLabel('部署コードの標準マッピング')).toBeDisabled()
  await expect(viewerPanel.getByLabel('部署コードの推奨値')).toBeDisabled()
  await expect(viewerPanel.getByLabel('連絡方法の連絡方法')).toBeDisabled()

  await page.getByRole('button', { name: 'ログアウト', exact: true }).click()
  await login(page, process.env.E2E_EMAIL!, process.env.E2E_PASSWORD!)
  const deleteResponse = await page.request.delete(`/api/projects/${project.id}`)
  expect(deleteResponse.ok()).toBeTruthy()
})
