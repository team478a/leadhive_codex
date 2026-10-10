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
  const companyRow = page.getByTestId('company-list-item').filter({ hasText: domain })
  await expect(companyRow.getByText('準備完了', { exact: true })).toBeVisible()
  await companyRow.getByRole('button', { name: '詳細' }).click()

  const formPanel = page.getByRole('heading', { name: 'フォーム事前解析' })
    .locator('xpath=ancestor::section[1]')
  const externalCandidate = formPanel.getByRole('region', { name: '外部問い合わせ候補' })
  await expect(externalCandidate).toContainText('窓口用途・営業可否の確認とHuman送信承認は別途必要')
  await expect(externalCandidate).toContainText('入力・送信は行っていません')
  await expect(externalCandidate).toContainText('取得上限により今回の対象外')
  await expect(externalCandidate.getByRole('link')).toHaveAttribute('href', 'https://external-contact.example/entry?no=test-only')
  await expect(externalCandidate.getByRole('link')).toHaveAttribute('rel', 'noreferrer')
  await expect(externalCandidate.getByRole('button')).toHaveCount(0)
  await formPanel.getByText(/解析ログ（/).click()
  await expect(formPanel.getByText('取得したHTMLで問い合わせフォーム未検出', { exact: true })).toBeVisible()
  await expect(formPanel.getByText('外部埋め込みあり・表示後の確認が必要', { exact: true })).toBeVisible()
  await expect(formPanel.getByText('ページ取得失敗・フォームの有無は未確認', { exact: true })).toBeVisible()
  await expect(formPanel.getByText('検証用の取得失敗', { exact: true })).toBeVisible()
  const profileCards = formPanel.locator('.form-profile-card')
  await expect(profileCards).toHaveCount(2)
  const reviewGuidance = profileCards.last().getByRole('region', { name: 'フォームの確認手順' })
  await expect(reviewGuidance).toContainText('CAPTCHAは人による操作・確認が必要です。')
  await expect(reviewGuidance).toContainText('フォーム確認や優先フォームの選択はHuman送信承認ではありません。')
  await expect(reviewGuidance).toContainText('入力先のマッピング済み表示は、選択肢や同意内容の確認済み表示ではありません。')
  await expect(reviewGuidance.getByRole('link', { name: 'メルマガ登録の選択・同意を確認する' })).toHaveCount(0)
  await expect(profileCards.first().getByRole('region', { name: 'フォームの確認手順' })).toContainText('表示後や確認画面でのCAPTCHAがないことは未確認です。')
  await expect(formPanel.getByText('営業可否: 営業禁止表記は未検出', { exact: true })).toHaveCount(2)
  await expect(reviewGuidance.getByRole('link', { name: '元の問い合わせページを開く（別タブ）' })).toHaveAttribute('target', '_blank')
  let guidanceWrites = 0
  const trackGuidanceWrite = (request: import('@playwright/test').Request) => {
    if (request.url().includes('/api/') && !['GET', 'HEAD', 'OPTIONS'].includes(request.method())) guidanceWrites++
  }
  page.on('request', trackGuidanceWrite)
  await reviewGuidance.getByRole('link', { name: '連絡方法の選択・同意を確認する' }).click()
  await expect(formPanel.getByLabel('連絡方法の標準マッピング').locator('xpath=ancestor::tr')).toBeInViewport()
  const fieldJump = reviewGuidance.getByRole('link', { name: '部署コードを確認する' })
  await fieldJump.click()
  const targetRow = formPanel.getByLabel('部署コードの標準マッピング').locator('xpath=ancestor::tr')
  await expect(targetRow).toBeInViewport()
  expect(guidanceWrites).toBe(0)
  page.off('request', trackGuidanceWrite)
  const inputReview = profileCards.first().getByRole('region', { name: 'フォーム入力確認' })
  const savedChoices = inputReview.getByRole('region', { name: '同名チェック項目の確認資料' })
  await expect(savedChoices.getByText('SNS運用（選択値：SNS）', { exact: true })).toBeVisible()
  await expect(savedChoices.getByText(/用途と選択条件は未確認/)).toBeVisible()
  await expect(savedChoices.getByRole('checkbox')).toHaveCount(0)
  const prerequisites = inputReview.getByRole('region', { name: 'フォーム対応の前提条件' })
  await expect(prerequisites).toContainText('実サイト対応済み・営業許可・送信承認を意味しません。')
  await expect(prerequisites).toContainText('複数選択の確認履歴：確認が必要')
  const inputPreparation = inputReview.getByRole('region', { name: '入力内容の確認票' })
  let preparationRecords = 0
  let changedPreparation = false
  await page.route('**/api/form-profiles/*/input-preparation', route => route.fulfill({ json: {
    snapshot_hash: 'a'.repeat(64), can_record: true, review_status: 'NOT_RECORDED', reasons: [],
    snapshot: { form_url: `https://${domain}/contact`, plugin_version: '6.2', rows: [{ position: 0, name: 'body', label: '本文', required: true, values: ['確認票の本文候補'], state: 'UNAPPROVED_DRAFT_VALUE' }] },
  } }))
  await page.route('**/api/form-profiles/*/input-preparation/reviews', async route => {
    preparationRecords += 1
    expect(route.request().postDataJSON()).toEqual({ expected_snapshot_hash: 'a'.repeat(64), input_content_confirmed: true })
    if (changedPreparation) await route.fulfill({ status: 409, json: { detail: '入力内容が変更されました。確認票を読み直してください。' } })
    else await route.fulfill({ json: { snapshot_hash: 'a'.repeat(64), can_record: true, review_status: 'RECORDED', reasons: [], snapshot: { form_url: `https://${domain}/contact`, plugin_version: '6.2', rows: [] } } })
  })
  await inputPreparation.getByRole('button', { name: '入力内容をまとめて確認' }).click()
  await expect(inputPreparation.getByRole('button', { name: '入力内容の確認を記録' })).toBeDisabled()
  await inputPreparation.getByText('本文（必須）：値あり', { exact: true }).click()
  await expect(inputPreparation.getByText('確認票の本文候補', { exact: true })).toBeVisible()
  await inputPreparation.getByRole('checkbox').check()
  await inputPreparation.getByRole('button', { name: '入力内容の確認を記録' }).click()
  await expect(inputPreparation).toContainText('入力確認を記録済み（送信承認ではありません）')
  let contractChanged = false
  await page.route('**/api/form-profiles/*/contract-preview', route => route.fulfill({ json: contractChanged ? { status: 'HOLD', reasons: ['INPUT_CONFIRMATION_REQUIRED'], contract: null, contract_hash: null, encoding_preview: null } : { status: 'PREVIEW_ONLY', reasons: [], contract_hash: 'b'.repeat(64), encoding_preview: { wire_size: 1234, wire_sha256: 'c'.repeat(64) }, contract: { endpoint: `https://${domain}/wp-json/contact-form-7/v1/contact-forms/7/feedback`, contract_family: 'cf7-6.2', parts: [{ name: 'body' }] } } }))
  await inputPreparation.getByRole('button', { name: 'フォーム証拠と入力を照合' }).click()
  await expect(inputPreparation.getByText('照合済み・送信不可の契約プレビュー', { exact: true })).toBeVisible()
  await expect(inputPreparation.getByText(/確認したREST送信先/)).toBeVisible()
  await expect(inputPreparation.getByText(/送信データの変換確認：1,234 bytes/)).toBeVisible()
  let handoffChanged = false
  await page.route('**/api/form-profiles/*/approval-handoff-preview', route => route.fulfill({ json: handoffChanged ? { status: 'HOLD', reasons: ['CONFIRMATION_EXPIRED'], snapshot: null, snapshot_hash: null } : { status: 'PREPARATION_ONLY', reasons: [], snapshot_hash: 'd'.repeat(64), snapshot: { expires_at: '2099-01-01T00:00:00+00:00', input_review: { actor_user_id: 'human' }, contract: { endpoint: `https://${domain}/wp-json/contact-form-7/v1/contact-forms/7/feedback`, parts: [{ name: 'body', value: '引き継ぎ本文', kind: 'textarea' }] } } } }))
  await inputPreparation.getByRole('button', { name: '承認へ引き継ぐ内容を確認' }).click()
  const handoff = inputPreparation.locator('[aria-label="承認引き継ぎプレビュー"]')
  await expect(handoff).toContainText('送信承認は未作成です')
  await handoff.getByText('引き継ぐ入力内容', { exact: true }).click()
  await expect(handoff).toContainText('引き継ぎ本文')
  let candidateRequests = 0
  await page.route('**/api/form-profiles/*/approval-handoff-request', route => {
    expect(route.request().postDataJSON()).toEqual({ expected_handoff_hash: 'd'.repeat(64) })
    candidateRequests++
    return route.fulfill({ status: 201, json: { status: 'PENDING' } })
  })
  await handoff.getByRole('button', { name: '候補内容を承認キューへ追加（送信不可）' }).click()
  await expect(handoff.getByRole('status')).toContainText('承認キューへ追加しました')
  await expect(handoff.getByRole('button', { name: '候補内容を承認キューへ追加（送信不可）' })).toHaveCount(0)
  expect(candidateRequests).toBe(1)
  await page.unroute('**/api/form-profiles/*/approval-handoff-request')
  handoffChanged = true
  await inputPreparation.getByRole('button', { name: '承認へ引き継ぐ内容を確認' }).click()
  await expect(handoff).toContainText('引き継ぎを保留しています')
  await expect(handoff.getByText(/引き継ぎ本文/)).toHaveCount(0)
  await page.unroute('**/api/form-profiles/*/approval-handoff-preview')
  contractChanged = true
  await inputPreparation.getByRole('button', { name: 'フォーム証拠と入力を照合' }).click()
  await expect(inputPreparation.getByText('証拠照合は保留です。', { exact: true })).toBeVisible()
  await expect(inputPreparation.getByText(/確認したREST送信先/)).toHaveCount(0)
  await expect(inputPreparation.getByText(/送信データの変換確認/)).toHaveCount(0)
  await page.unroute('**/api/form-profiles/*/contract-preview')
  changedPreparation = true
  await inputPreparation.getByRole('button', { name: '入力内容をまとめて確認' }).click()
  await inputPreparation.getByRole('checkbox').check()
  await inputPreparation.getByRole('button', { name: '入力内容の確認を記録' }).click()
  await expect(inputPreparation.getByRole('alert')).toContainText('確認票を読み直してください')
  await expect(inputPreparation.getByRole('checkbox')).toHaveCount(0)
  expect(preparationRecords).toBe(2)
  await page.unroute('**/api/form-profiles/*/input-preparation')
  await page.unroute('**/api/form-profiles/*/input-preparation/reviews')
  await prerequisites.getByText('送信承認：別工程で確認', { exact: true }).click()
  await expect(prerequisites).toContainText('入力の確認履歴は送信承認ではありません。')
  const choiceRecord = inputReview.getByRole('region', { name: '複数選択の確認記録' })
  await choiceRecord.getByLabel('事業内容の選択条件').selectOption('AT_LEAST_ONE')
  await choiceRecord.getByLabel('SNS運用', { exact: true }).check()
  await choiceRecord.getByLabel('OEM', { exact: true }).check()
  await choiceRecord.getByLabel(/元フォームで、同じグループ/).check()
  await choiceRecord.getByRole('button', { name: '複数選択の確認を記録' }).click()
  await expect(choiceRecord).toContainText('確認記録あり（送信承認ではありません）')
  await expect(prerequisites).toContainText('複数選択の確認履歴：保存済み情報あり')
  await choiceRecord.getByText('前回の確認内容（履歴）').click()
  await expect(choiceRecord).toContainText('SNS運用：選択')
  await expect(choiceRecord).toContainText('OEM：選択')
  const checkSummary = choiceRecord.getByRole('region', { name: '確認履歴の点検結果' })
  await expect(checkSummary).toContainText('現在の項目 1件 ／ 一致する確認 1件 ／ 要確認 0件')
  await choiceRecord.getByLabel('再確認が必要な項目だけ表示').check()
  await expect(choiceRecord.getByRole('button', { name: '複数選択の確認を記録' })).toHaveCount(0)
  await expect(choiceRecord).toContainText('取得時点で再確認が必要な項目はありません。')
  await choiceRecord.getByLabel('再確認が必要な項目だけ表示').uncheck()
  const checkPath = '**/api/form-profiles/*/saved-choice-reviews'
  await page.route(checkPath, async route => {
    const response = await route.fetch()
    const groups = await response.json()
    groups[0] = { ...groups[0], label: '現在の保存情報にない項目', options: [], review_status: 'REMOVED', review_current: false, review_supported: false, present_in_saved_fields: false, check_reasons: ['GROUP_REMOVED'] }
    await route.fulfill({ response, json: groups })
  })
  await choiceRecord.getByRole('button', { name: '複数選択を読み直す' }).click()
  await expect(checkSummary).toContainText('現在の項目 0件 ／ 一致する確認 0件 ／ 要確認 1件')
  await expect(choiceRecord).toContainText('記録時の項目は現在の保存情報にありません。')
  await expect(choiceRecord.getByRole('button', { name: '複数選択の確認を記録' })).toHaveCount(0)
  await page.unroute(checkPath)
  await page.route(checkPath, route => route.fulfill({ status: 503, json: { detail: '確認履歴を取得できません。' } }))
  await choiceRecord.getByRole('button', { name: '複数選択を読み直す' }).click()
  await expect(choiceRecord.getByRole('alert')).toContainText('確認履歴を取得できません。')
  await expect(checkSummary).toHaveCount(0)
  await page.unroute(checkPath)
  await choiceRecord.getByRole('button', { name: '複数選択を読み直す' }).click()
  await expect(checkSummary).toContainText('一致する確認 1件')
  await expect(inputReview.getByRole('region', { name: '送信経路の技術診断' })).toContainText('通常POST経路の候補')
  await expect(inputReview.getByRole('region', { name: '送信経路の技術診断' })).toContainText('技術対応の確認待ち')
  await page.getByRole('button', { name: 'プロジェクトの窓口候補を整理', exact: true }).click()
  const assessment = page.getByRole('region', { name: '窓口の利用可否と理由' })
  await expect(assessment.locator('details[data-form-destination]')).toHaveCount(2)
  await expect(inputReview.getByRole('button', { name: 'このフォームの窓口用途を確認', exact: true })).toBeVisible()
  // UI navigation must never submit a review, choice, approval or execution request.
  const navigationWrites: string[] = []
  const trackNavigation = (request: import('@playwright/test').Request) => {
    if (request.method() !== 'GET') navigationWrites.push(request.url())
  }
  page.on('request', trackNavigation)
  await inputReview.getByRole('button', { name: 'このフォームの窓口用途を確認', exact: true }).click()
  const contactDetails = assessment.locator('details[data-form-destination]').filter({ has: page.locator('summary').filter({ hasText: `/contact` }) }).first()
  await expect(contactDetails).toHaveAttribute('open', '')
  await expect(contactDetails.getByRole('combobox', { name: '窓口用途', exact: true })).toHaveValue('unknown')
  await expect(contactDetails.getByLabel('用途の根拠URL', { exact: true })).toHaveValue('')
  await expect(contactDetails.getByRole('button', { name: '用途確認を記録', exact: true })).toBeDisabled()
  await contactDetails.getByRole('button', { name: 'このフォームの選択・同意を確認', exact: true }).click()
  await expect(inputReview).toBeFocused()
  await contactDetails.locator('summary').click()
  await contactDetails.evaluate(element => { element.dataset.formDestination += '?different=1' })
  await inputReview.getByRole('button', { name: 'このフォームの窓口用途を確認', exact: true }).click()
  await expect(inputReview.getByText(/一致する窓口候補を1つに特定できません/)).toBeVisible()
  await expect(contactDetails).not.toHaveAttribute('open', '')
  await contactDetails.evaluate(element => { element.dataset.formDestination = element.dataset.formDestination!.split('?')[0] + '/#contact' })
  await inputReview.getByRole('button', { name: 'このフォームの窓口用途を確認', exact: true }).click()
  await expect(contactDetails).toHaveAttribute('open', '')
  await expect(inputReview.getByText(/一致する窓口候補を1つに特定できません/)).toHaveCount(0)
  await contactDetails.evaluate(element => { element.dataset.formDestination = element.dataset.formDestination!.split('#')[0] })
  await contactDetails.getByRole('button', { name: 'このフォームの選択・同意を確認', exact: true }).click()
  await expect(inputReview).toBeFocused()
  await formPanel.evaluate(element => {
    const duplicate = document.createElement('section')
    duplicate.dataset.reviewFormUrl = element.querySelector<HTMLElement>('[data-review-form-url]')!.dataset.reviewFormUrl
    duplicate.dataset.navigationFixture = 'duplicate'
    element.appendChild(duplicate)
  })
  await contactDetails.getByRole('button', { name: 'このフォームの選択・同意を確認', exact: true }).click()
  await expect(contactDetails.getByText(/一致する解析済みフォームを1つに特定できません/)).toBeVisible()
  await formPanel.locator('[data-navigation-fixture]').evaluate(element => element.remove())
  await contactDetails.getByRole('button', { name: 'このフォームの選択・同意を確認', exact: true }).click()
  await expect(inputReview).toBeFocused()
  expect(navigationWrites).toEqual([])
  page.off('request', trackNavigation)
  await page.screenshot({ path: testInfo.outputPath('destination-form-handoff.png') })

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
      cf7_static: { contract_shape: { reviewed_lab_version: true, hidden_complete: true, hidden_shape_valid: false, extra_hidden: 1, invalid_names: 2, repeated_names: 1, radio_controls: 2, select_controls: 1, checkbox_controls: 1, checked_checkboxes: 1, disabled_controls: 1 }, status: 'CF7_CANDIDATE', version: '6.1.4', form_count: 1, markers_complete: true, form_id_valid: true, rest_link_same_origin: true, missing_names: 0, file_inputs: 0, unsupported_controls: 0, base_override: false, execution_allowed: false, eligible_for_approval: false },
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
  const cf7Static = liveReview.getByLabel('CF7の静的構造確認')
  await expect(cf7Static.getByText('保存マーカー：CF7候補 / バージョン：6.1.4', { exact: true })).toBeVisible()
  await expect(cf7Static.getByText(/接続・受付は未検証/)).toBeVisible()
  const contract = cf7Static.getByLabel('限定契約との差分')
  await expect(contract.getByText(/隔離環境で検証した版と一致/)).toBeVisible()
  await expect(contract.getByText(/不一致・確認が必要/)).toBeVisible()
  await expect(contract.getByText(/未対応のラジオ：2件/)).toBeVisible()
  await expect(contract.getByText(/同意内容と選択値は人による確認が必要/)).toBeVisible()
  await cf7Static.scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('cf7-static-inspection.png') })
  await liveReview.getByText('保存済みの比較情報が不足・再解析が必要', { exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('live-check-viewport.png') })
  await liveReview.getByRole('button', { name: '現在のフォームを確認', exact: true }).click()
  await expect(liveReview.getByRole('alert')).toContainText('1分待って')
  await liveReview.getByRole('button', { name: 'このフォームだけ再解析', exact: true }).click()
  await expect(liveReview.getByText('保存されたフォーム情報が変わりました。この確認結果は以前の情報です。', { exact: true })).toBeVisible()
  await expect(cf7Static.getByText('以前の観察結果です。現在の構造とは限りません。', { exact: true })).toBeVisible()
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
  // Presentation-only fixtures; no external GET, approval or send.
  for (const [status, version] of [['HOLD', '6.2'], ['HOLD', '6.1.6'], ['HUMAN_REQUIRED', '6.1.6'], ['BLOCKED', '6.1.6']]) {
    await page.route('**/api/form-profiles/*/review-material', async route => {
      const response = await route.fetch()
      const body = await response.json()
      body.adapter_prerequisites.cf7_readiness = {
        status, observed_version: version, lab_contract_status: 'VERIFIED_FIXTURE_ONLY', freshness: 'CURRENT',
        reasons: [{ code: 'fixture-reason', message: `${version}実サイト準備は未接続です。`, next_action: '送信せず入力内容を確認する。' }],
      }
      await route.fulfill({ response, json: body })
    })
    await inputReview.getByRole('button', { name: '入力候補を更新', exact: true }).click()
    const readiness = prerequisites.getByRole('region', { name: 'CF7対応状況' })
    await expect(readiness).toContainText(({ HOLD: '実サイト送信は保留', HUMAN_REQUIRED: '人の操作が必要', BLOCKED: '送信対象外' } as Record<string, string>)[status])
    await expect(readiness).toContainText('検証済み（実サイト対応ではありません）')
    if (version === '6.1.6') await expect(readiness).toContainText('6.1.4として代用できません。')
    await expect(readiness.getByText('送信せず入力内容を確認する。', { exact: true })).toBeVisible()
    await expect(readiness.getByRole('button')).toHaveCount(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
    await page.unroute('**/api/form-profiles/*/review-material')
  }
  await inputReview.getByRole('button', { name: '入力候補を更新', exact: true }).click()
  await page.route('**/api/form-profiles/*/review-material', async route => {
    const response = await route.fetch()
    const body = await response.json()
    if (body.saved_choice_structure?.groups.length) {
      body.saved_choice_structure.source_hash = 'c'.repeat(64)
      body.saved_choice_structure.groups[0].options[0].label = '変更された選択肢'
    }
    await route.fulfill({ response, json: body })
  })
  await inputReview.getByRole('button', { name: '入力候補を更新', exact: true }).click()
  await expect(savedChoices.getByText(/以前表示した項目・選択肢・フォーム構造から変更/)).toBeVisible()
  await expect(savedChoices.getByText(/変更された選択肢/)).toBeVisible()
  await page.unroute('**/api/form-profiles/*/review-material')
  await page.route('**/api/form-profiles/*/review-material', async route => {
    const response = await route.fetch()
    const body = await response.json()
    body.saved_choice_structure = { ...body.saved_choice_structure, source_hash: 'd'.repeat(64), groups: [] }
    await route.fulfill({ response, json: body })
  })
  await inputReview.getByRole('button', { name: '入力候補を更新', exact: true }).click()
  await expect(savedChoices.getByText(/以前表示した項目・選択肢・フォーム構造から変更/)).toBeVisible()
  await expect(savedChoices.getByText('現在の保存情報には、複数選択の候補がありません。', { exact: true })).toBeVisible()
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
  await expect(captchaCard.getByRole('link', { name: '部署コードを確認する' })).toHaveCount(0)
  await expect(captchaCard.getByText('MANUAL', { exact: true })).toBeVisible()
  const contactMethod = formPanel.getByLabel('連絡方法の連絡方法')
  await expect(contactMethod).toHaveValue('')
  const choiceMaterial = captchaCard.getByRole('region', { name: 'フォーム入力確認' })
  await expect(choiceMaterial.getByRole('heading', { name: '選択・同意・入力先の確認' })).toBeVisible()
  await expect(choiceMaterial.getByRole('region', { name: '送信経路の技術診断' })).toContainText('人の操作が必要')
  await choiceMaterial.getByRole('region', { name: '送信経路の技術診断' }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('technical-diagnostic.png') })
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
  await expect(groupReview.getByRole('region', { name: '必須範囲の確認状況' })).toContainText('2項目・2選択肢')
  await expect(groupReview).toContainText('必須範囲：未確定（任意ではありません）')
  await expect(groupReview.getByRole('button', { name: 'グループの確認を記録' })).toBeDisabled()
  await groupReview.getByLabel('確認した必須条件', { exact: true }).selectOption('EXACTLY_ONE')
  await groupReview.getByLabel('other[]のグループ選択', { exact: true }).selectOption('OTHER')
  await expect(groupReview.getByRole('button', { name: 'グループの確認を記録' })).toBeDisabled()
  await groupReview.getByLabel('対象項目・必須条件・選択値を元フォームで確認しました').check()
  await groupReview.getByRole('button', { name: 'グループの確認を記録' }).click()
  await expect(groupReview.getByText('条件・選択を記録済み', { exact: true })).toBeVisible()
  await expect(groupReview).toContainText('必須範囲：人が条件を記録済み（送信承認ではありません）')
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
  await page.getByTestId('company-list-item').filter({ hasText: domain }).getByRole('button', { name: '詳細' }).click()
  const viewerPanel = page.getByRole('heading', { name: 'フォーム事前解析' })
    .locator('xpath=ancestor::section[1]')
  await expect(viewerPanel.getByText('閲覧者は解析結果を確認できます。', { exact: false })).toBeVisible()
  await expect(viewerPanel.getByRole('button', { name: '再解析' })).toBeDisabled()
  await expect(page.getByRole('region', { name: '営業NG登録' }).getByRole('button', { name: '営業NGリストへ移す' })).toHaveCount(0)
  await expect(viewerPanel.getByRole('region', { name: 'フォームの確認手順' })).toHaveCount(2)
  await expect(viewerPanel.getByRole('region', { name: 'フォームの確認手順' }).first()).toContainText('営業許可を確認した意味ではありません。')
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
  await expect(viewerReview.getByRole('button', { name: '複数選択の確認を記録' })).toHaveCount(0)
  await expect(viewerReview.getByRole('button', { name: '現在のフォームを確認', exact: true })).toHaveCount(0)
  await expect(viewerPanel.getByText('保存されたフォーム情報が変わりました。この確認結果は以前の情報です。', { exact: true })).toBeVisible()
  await expect(viewerPanel.getByRole('button', { name: 'このフォームだけ再解析', exact: true })).toHaveCount(0)

  await page.getByRole('button', { name: 'ログアウト', exact: true }).click()
  await login(page, process.env.E2E_EMAIL!, process.env.E2E_PASSWORD!)
  const deleteResponse = await page.request.delete(`/api/projects/${project.id}`)
  expect(deleteResponse.ok()).toBeTruthy()
})
