import { navigateWorkspace } from './navigation'
import { execFileSync } from 'node:child_process'
import { test, expect } from '@playwright/test'

test('form review queue supports safe review, keyboard navigation, skip ordering and do-not-send', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'approval-fixture'], { env: process.env, encoding: 'utf8' })) as { project_id: string }
  const items = ['先頭のスキップ候補', '次の確認候補', '連絡対象外候補'].map((company_name, index) => ({
    company_id: `company-${index}`, company_name, profile_id: `profile-${index}`,
    form_url: `https://example.com/contact-${index}`, fingerprint: 'a'.repeat(64), fields_hash: 'b'.repeat(64),
    reason_codes: ['REVIEW_REQUIRED'], ready_confirmation_only: false, fields: [], groups: [], saved_groups: [],
  }))
  items.push({
    company_id: 'company-ready', company_name: '準備可能・未確認候補', profile_id: 'profile-ready',
    form_url: 'https://example.com/contact-ready', fingerprint: 'c'.repeat(64), fields_hash: 'd'.repeat(64),
    reason_codes: ['READY'], ready_confirmation_only: true, fields: [], groups: [], saved_groups: [],
  })
  const submitted: { profile_id: string; action: string; confirmed_no_sales_prohibition: boolean }[] = []
  await page.route(`**/api/projects/${fixture.project_id}/send-flow-summary`, route =>
    route.fulfill({ json: {
      readiness_completed_at: null, target_company_count: 3,
      latest_form_draft_updated_at: null,
      draft_counts: { email: 0, form: 3 }, form_reviewed_count: 0,
      approval_counts: { pending: { email: 0, form: 0 }, approved_unsent: { email: 0, form: 0 } },
      today: { sent: 0, reserved: 0 }, results: { sent: 0, failed: 0, unknown: 0 },
    } }))
  await page.route(`**/api/projects/${fixture.project_id}/form-review-queue`, route =>
    route.fulfill({ json: { total: items.length, offset: 0, limit: 50, items } }))
  await page.route(`**/api/projects/${fixture.project_id}/form-dm-readiness`, route =>
    route.fulfill({ json: { counts: { READY: 1 }, review_queue_eligible: 3, ready_confirmation_pending: 1, total: 4, items: [] } }))
  await page.route('**/api/form-profiles/*/review-decision', async route => {
    const profileId = route.request().url().split('/').at(-2)!
    const body = route.request().postDataJSON()
    submitted.push({ profile_id: profileId, action: body.action, confirmed_no_sales_prohibition: body.confirmed_no_sales_prohibition })
    if (body.action === 'DO_NOT_SEND') items.splice(items.findIndex(item => item.profile_id === profileId), 1)
    else items.splice(items.findIndex(item => item.profile_id === profileId), 1)
    await route.fulfill({ json: { status: body.action } })
  })

  await page.goto('/')
  await page.getByLabel('メールアドレス').fill(process.env.E2E_EMAIL!)
  await page.getByLabel('パスワード').fill(process.env.E2E_PASSWORD!)
  await page.getByRole('button', { name: 'ログインする', exact: true }).click()
  await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
  await navigateWorkspace(page, '▶ 送信の準備・実行')
  await page.evaluate(projectId => localStorage.setItem(`leadhive:send-channel:${projectId}`, 'form'), fixture.project_id)
  await page.getByLabel('対象プロジェクト').selectOption(fixture.project_id)
  const queueStage = page.getByRole('region', { name: '2. フォームを確認', exact: true })
  const queueStageHeader = queueStage.getByRole('button').first()
  await expect(queueStageHeader).toHaveAttribute('aria-expanded', 'true')
  await expect(queueStageHeader).toContainText('確認待ち 3社 · 確認不要：0社')

  const panel = page.getByRole('region', { name: 'フォーム確認キュー' })
  await expect(panel.getByRole('heading', { name: 'フォーム確認キュー' })).toBeVisible()
  await expect(panel.getByRole('heading', { name: '先頭のスキップ候補' })).toBeVisible()
  const noProhibition = panel.getByLabel('フォームを開いて確認し、営業お断り・営業禁止の記載がないことを確認しました')
  await expect(panel.getByRole('button', { name: '確認して次へ' })).toBeDisabled()
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await page.keyboard.press('Enter')
  expect(submitted).toHaveLength(0)
  await noProhibition.focus()
  await page.keyboard.press('Enter')
  expect(submitted).toHaveLength(0)
  await noProhibition.uncheck()
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await page.keyboard.press('s')
  await expect(panel.getByRole('heading', { name: '次の確認候補' })).toBeVisible()
  await panel.getByRole('button', { name: '更新' }).focus()
  await page.keyboard.press('Enter')
  await expect(panel.getByRole('heading', { name: '次の確認候補' })).toBeVisible()

  await noProhibition.check()
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await page.keyboard.press('Enter')
  await expect(panel.getByRole('heading', { name: '連絡対象外候補' })).toBeVisible()
  expect(submitted[0]).toMatchObject({ profile_id: 'profile-1', action: 'CONFIRM', confirmed_no_sales_prohibition: true })
  await panel.getByRole('button', { name: '送信しない・連絡対象外' }).focus()
  await page.keyboard.press('Enter')
  await expect(panel.getByRole('heading', { name: '準備可能・未確認候補' })).toBeVisible()
  await expect(panel.getByText('この企業を連絡対象外にしました。')).toBeVisible()
  expect(submitted[1]).toMatchObject({ profile_id: 'profile-2', action: 'DO_NOT_SEND', confirmed_no_sales_prohibition: false })
  expect(items.some(item => item.profile_id === 'profile-2')).toBe(false)
  await expect(panel.getByRole('heading', { name: '準備可能・未確認候補' })).toBeVisible()
  await expect(panel.getByText('解析された入力項目・値')).toHaveCount(0)
  const readyConfirmation = panel.getByLabel('フォームを開いて営業お断りの表記がないことを確認')
  await expect(panel.getByRole('button', { name: '確認して次へ' })).toBeDisabled()
  await readyConfirmation.check()
  await panel.getByRole('button', { name: '確認して次へ' }).click()
  expect(submitted[2]).toMatchObject({ profile_id: 'profile-ready', action: 'CONFIRM', confirmed_no_sales_prohibition: true })
  await expect(panel.getByRole('heading', { name: '先頭のスキップ候補' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width)
})
