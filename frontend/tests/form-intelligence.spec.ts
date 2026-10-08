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
  const inputReview = profileCards.first().getByRole('region', { name: 'フォーム入力確認' })
  // Fixture-only network response: no real website GET or send in this UI test.
  let liveChecks = 0
  const savedChecks = new Map<string, unknown>()
  await page.route('**/api/form-profiles/*/live-check', async route => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(savedChecks.get(route.request().url()) ?? null) })
      return
    }
    liveChecks += 1
    if (liveChecks === 1) {
      const result = {
      checked_at: '2026-10-08T00:00:00Z', structure_status: 'SAVED_BASELINE_INCOMPLETE',
      fingerprint_match: true, action_match: null, method_is_post: true,
      freshness: 'CURRENT', expires_at: '2026-10-09T00:00:00Z',
      sales_prohibition_detected: false, captcha_state: 'NOT_DETECTED_STATIC',
      execution_allowed: false, message: '静的HTML確認・送信承認ではありません。',
      }
      savedChecks.set(route.request().url(), result)
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(result) })
    }
    else await route.fulfill({ status: 429, contentType: 'application/json', body: JSON.stringify({ detail: '直前に確認済みです。1分待ってから再確認してください。' }) })
  })
  const liveReview = inputReview.getByRole('region', { name: '現在のフォーム確認' })
  let targetRefreshes = 0
  await page.route('**/api/form-profiles/*/refresh-target', async route => {
    targetRefreshes += 1
    const key = route.request().url().replace('/refresh-target', '/live-check')
    const old = savedChecks.get(key) as Record<string, unknown>
    savedChecks.set(key, { ...old, freshness: 'SOURCE_CHANGED' })
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ refresh_applied: true, execution_allowed: false, human_approved: false }) })
  })
  await liveReview.getByRole('button', { name: '現在のフォームを確認', exact: true }).click()
  await expect(liveReview.getByText('保存済みの比較情報が不足・再解析が必要', { exact: true })).toBeVisible()
  await expect(liveReview.getByText('入力項目：保存済みと一致', { exact: true })).toBeVisible()
  await expect(liveReview.getByText('送信先：比較元が未保存', { exact: true })).toBeVisible()
  await expect(liveReview.getByText('保存済みの確認結果（24時間以内の観測）', { exact: true })).toBeVisible()
  await expect(liveReview.getByText('静的HTMLでは未検出・画面確認が必要', { exact: false })).toBeVisible()
  await liveReview.getByText('保存済みの比較情報が不足・再解析が必要', { exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('live-check-viewport.png') })
  await liveReview.getByRole('button', { name: '現在のフォームを確認', exact: true }).click()
  await expect(liveReview.getByRole('alert')).toContainText('1分待って')
  await liveReview.getByRole('button', { name: 'このフォームだけ再解析', exact: true }).click()
  await expect(liveReview.getByText('保存されたフォーム情報が変わりました。この確認結果は以前の情報です。', { exact: true })).toBeVisible()
  expect(targetRefreshes).toBe(1)
  await expect(inputReview.getByRole('heading', { name: 'フォーム入力の確認資料' })).toBeVisible()
  await expect(inputReview.getByRole('link', { name: '元フォームを開く ↗' })).toHaveAttribute('href', `https://${domain}/contact`)
  await expect(inputReview.getByText('E2E review draft body', { exact: true })).toHaveCount(0)
  await inputReview.getByRole('button', { name: '送信者情報・本文候補を見る' }).click()
  await expect(inputReview.getByRole('heading', { name: 'フォーム入力の確認資料' })).toBeVisible()
  await expect(inputReview.getByText('E2E review draft body', { exact: true })).toBeVisible()
  await expect(inputReview.getByText(/この表示では承認・送信されません/)).toBeVisible()
  let materialFailures = 0
  await page.route('**/api/form-profiles/*/review-material', async route => {
    if (materialFailures++ === 0) await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '確認資料を取得できません。再度読み直してください。' }) })
    else await route.continue()
  })
  await inputReview.getByRole('button', { name: '入力候補を更新', exact: true }).click()
  await expect(inputReview.getByRole('alert')).toContainText('確認資料を取得できません')
  await expect(inputReview.getByRole('heading', { name: 'フォーム入力の確認資料' })).toHaveCount(0)
  await inputReview.getByRole('button', { name: '入力候補を更新', exact: true }).click()
  await expect(inputReview.getByRole('heading', { name: 'フォーム入力の確認資料' })).toBeVisible()
  await page.unroute('**/api/form-profiles/*/review-material')
  await inputReview.getByRole('region', { name: '確認の進め方' }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('human-review-handoff-viewport.png') })

  expect(await inputReview.getByRole('button', { name: '送信', exact: true }).count()).toBe(0)
  await expect(profileCards.getByText('静的構造: 通常経路の候補', { exact: true })).toHaveCount(2)
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
  const choiceMaterial = captchaCard.getByRole('region', { name: 'フォーム入力確認' })
  await expect(choiceMaterial.getByRole('heading', { name: '選択・同意・入力先の確認' })).toBeVisible()
  const methodSelection = choiceMaterial.getByLabel('連絡方法の確認選択', { exact: true })
  const methodArticle = methodSelection.locator('xpath=ancestor::article[1]')
  const methodSave = methodArticle.getByRole('button', { name: '確認した選択を保存' })
  await expect(methodSave).toBeDisabled()
  await methodSelection.selectOption('m')
  await expect(methodSave).toBeDisabled()
  await methodArticle.getByLabel('この項目の内容と選択値を確認しました').check()
  await methodSave.click()
  await expect(contactMethod.locator('xpath=ancestor::tr').getByText('MANUAL', { exact: true })).toBeVisible()
  await expect(contactMethod).toHaveValue('m')
  await expect(choiceMaterial.getByText('保存済みの選択：メール（送信承認ではありません）')).toBeVisible()
  const newsletter = formPanel.getByLabel('メルマガ登録の同意選択')
  await expect(newsletter).toHaveValue('')
  const newsletterSelection = choiceMaterial.getByLabel('メルマガ登録の確認選択', { exact: true })
  const newsletterArticle = newsletterSelection.locator('xpath=ancestor::article[1]')
  await expect(newsletterSelection).toHaveValue('')
  await newsletterArticle.getByLabel('この項目の内容と選択値を確認しました').check()
  await newsletterArticle.getByRole('button', { name: '確認した選択を保存' }).click()
  await expect(newsletter.locator('xpath=ancestor::tr').getByText('MANUAL', { exact: true })).toBeVisible()
  await expect(newsletter).toHaveValue('')
  await formPanel.getByText(/解析ログ/).click()
  await expect(formPanel.getByText('manual_corrected', { exact: true })).toHaveCount(3)
  const groupReview = choiceMaterial.getByRole('region', { name: '必須グループ確認' })
  await expect(groupReview.getByRole('button', { name: 'グループの確認を記録' })).toBeDisabled()
  await groupReview.getByLabel('確認した必須条件', { exact: true }).selectOption('EXACTLY_ONE')
  await groupReview.getByLabel('other[]のグループ選択', { exact: true }).selectOption('OTHER')
  await expect(groupReview.getByRole('button', { name: 'グループの確認を記録' })).toBeDisabled()
  await groupReview.getByLabel('対象項目・必須条件・選択値を元フォームで確認しました').check()
  await groupReview.getByRole('button', { name: 'グループの確認を記録' }).click()
  await expect(groupReview.getByText('条件・選択を記録済み', { exact: true })).toBeVisible()
  await expect(groupReview.getByText('前回の選択：その他', { exact: true })).toBeVisible()
  await expect(captchaCard.getByText('要確認', { exact: true })).toBeVisible()
  await expect(formPanel.getByText('manual_corrected', { exact: true })).toHaveCount(4)
  await groupReview.screenshot({ path: testInfo.outputPath('group-review.png') })

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
  await expect(viewerPanel.getByLabel('メルマガ登録の同意選択')).toBeDisabled()
  const viewerReview = viewerPanel.getByRole('region', { name: 'フォーム入力確認' }).first()
  await viewerReview.getByRole('button', { name: '入力候補を更新' }).click()
  await expect(viewerReview.getByText('送信者設定は管理者のみ確認できます。')).toBeVisible()
  await expect(viewerReview.getByRole('button', { name: '確認した選択を保存' })).toHaveCount(0)
  await expect(viewerReview.getByRole('button', { name: 'グループの確認を記録' })).toHaveCount(0)
  await expect(viewerReview.getByRole('button', { name: '現在のフォームを確認', exact: true })).toHaveCount(0)
  await expect(viewerPanel.getByText('保存されたフォーム情報が変わりました。この確認結果は以前の情報です。', { exact: true })).toBeVisible()
  await expect(viewerPanel.getByRole('button', { name: 'このフォームだけ再解析', exact: true })).toHaveCount(0)

  await page.getByRole('button', { name: 'ログアウト', exact: true }).click()
  await login(page, process.env.E2E_EMAIL!, process.env.E2E_PASSWORD!)
  const deleteResponse = await page.request.delete(`/api/projects/${project.id}`)
  expect(deleteResponse.ok()).toBeTruthy()
})
