import { test, expect } from '@playwright/test'

test('Human input trial records failures without approving, sending or changing prohibition', async ({ page }, testInfo) => {
  test.setTimeout(120_000)
  await page.goto('/')
  await page.getByLabel('メールアドレス').fill(process.env.E2E_EMAIL!)
  await page.getByLabel('パスワード').fill(process.env.E2E_PASSWORD!)
  await page.getByRole('button', { name: 'ログインする', exact: true }).click()
  const guide = page.getByRole('dialog', { name: '3ステップで始めましょう' })
  try { await guide.getByRole('button', { name: 'あとで見る' }).waitFor({ state: 'visible', timeout: 5000 }); await guide.getByRole('button', { name: 'あとで見る' }).click() } catch { /* Already dismissed. */ }
  const profilesResponse = await page.request.get('/api/target-profiles')
  expect(profilesResponse.ok()).toBeTruthy()
  const profiles = await profilesResponse.json()
  const response = await page.request.post('/api/projects', { data: {
    project_name: `入力試行 ${testInfo.project.name}`, target_profile_id: profiles[0].id,
    sales_objective: 'Synthetic no-send', region: '東京都', status: 'active',
  } })
  expect(response.ok()).toBeTruthy()
  const project = await response.json()
  try {
    expect((await page.request.post(`/api/projects/${project.id}/collection-jobs/urls`, { data: { urls: [`https://input-trial-${testInfo.project.name}.example`] } })).ok()).toBeTruthy()
    const company = (await (await page.request.get(`/api/projects/${project.id}/companies`)).json())[0]
    expect((await page.request.patch(`/api/companies/${company.id}/contact-control`, { data: {
      do_not_contact: true, exclusion_reason: '営業NG：合成テスト', contact_quality_status: 'observed',
    } })).ok()).toBeTruthy()
    await page.reload()
    await expect(page.getByRole('heading', { name: `入力試行 ${testInfo.project.name}`, exact: true })).toBeVisible()
    await page.getByRole('button', { name: '▤ 企業一覧', exact: true }).click()
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(project.id)
    await page.getByTestId('company-list-item').getByRole('button', { name: '詳細', exact: true }).click()
    const panel = page.getByRole('region', { name: 'フォーム入力の実運用記録' })
    await expect(panel).toContainText('送信禁止')
    const writes: string[] = []
    page.on('request', request => { if (['POST', 'PATCH', 'DELETE', 'PUT'].includes(request.method())) writes.push(new URL(request.url()).pathname) })
    const save = panel.getByRole('button', { name: '未送信の入力結果を記録' })
    await expect(save).toBeDisabled()
    await panel.getByLabel('確認したフォームURL').fill('javascript:alert(1)')
    await panel.getByLabel('入力確認の結果').selectOption('INPUT_OK')
    await expect(save).toBeDisabled()
    const formUrl = 'https://input-trial.example/contact'
    await panel.getByLabel('確認したフォームURL').fill(formUrl)
    await expect(panel.getByLabel('入力確認の結果')).toHaveValue('NOT_CHECKED')
    await panel.getByLabel('入力確認の結果').selectOption('INPUT_FAILED')
    await panel.getByLabel('入力できない理由').selectOption('DYNAMIC')
    await expect(save).toBeDisabled()
    await panel.getByLabel('確認メモ（必須）').fill('項目が表示されない')
    await save.click()
    await expect(panel.getByRole('status')).toContainText('記録しました')
    const records = await (await page.request.get(`/api/companies/${company.id}/activities`)).json()
    const value = JSON.parse(records[0].note.replace('フォーム入力確認 v1: ', ''))
    expect(value).toMatchObject({ version: 1, source: 'HUMAN_REPORTED', sent: false, outcome: 'INPUT_FAILED', reason: 'DYNAMIC', form_url: formUrl })
    await panel.getByLabel('入力確認の結果').selectOption('INPUT_OK')
    await save.click()
    await expect(panel.getByText('入力できた（未送信）', { exact: true }).last()).toBeVisible()
    await panel.getByLabel('入力確認の結果').selectOption('CAPTCHA')
    await expect(save).toBeDisabled()
    await panel.getByLabel('確認メモ（必須）').fill('画像認証のため停止')
    await save.click()
    await expect(panel.getByText('CAPTCHAで停止', { exact: true }).last()).toBeVisible()
    expect(writes).toEqual(Array(3).fill(`/api/companies/${company.id}/activities`))
    const stored = await (await page.request.get(`/api/companies/${company.id}`)).json()
    expect(stored.do_not_contact).toBe(true)
    expect(stored.exclusion_reason).toBe('営業NG：合成テスト')
    expect(stored.status).toBe('excluded')
    await page.reload()
    await page.getByRole('button', { name: '▤ 企業一覧', exact: true }).click()
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(project.id)
    await page.getByTestId('company-list-item').getByRole('button', { name: '詳細', exact: true }).click()
    await expect(panel.getByText('項目が表示されない', { exact: false })).toBeVisible()
    await expect(panel.getByRole('button', { name: /送信|承認/ }).filter({ hasText: /^フォームを送信$|^承認する$/ })).toHaveCount(0)
  } finally { expect((await page.request.delete(`/api/projects/${project.id}`)).ok()).toBeTruthy() }
})
