import { navigateWorkspace } from './navigation'
import { execFileSync } from 'node:child_process'
import { test, expect } from '@playwright/test'

test('form review queue supports safe review, keyboard navigation, skip ordering and do-not-send', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'approval-fixture'], { env: process.env, encoding: 'utf8' })) as { project_id: string }
  const items = ['先頭のスキップ候補', '次の確認候補', '連絡対象外候補'].map((company_name, index) => ({
    company_id: `company-${index}`, company_name, profile_id: `profile-${index}`,
    form_url: `https://example.com/contact-${index}`, fingerprint: 'a'.repeat(64), fields_hash: 'b'.repeat(64),
    reason_codes: ['REVIEW_REQUIRED'], ready_confirmation_only: false,
    fields: [] as { id: string; label: string; name: string; field_type: string; required: boolean; mapped_key: string; recommended_value: string; display_value: string; options: { value: string; label: string }[] }[],
    groups: [], saved_groups: [],
  }))
  items[0].fields = [
    { id: 'visible-field', label: 'お問い合わせ内容', name: 'message', field_type: 'textarea', required: true, mapped_key: 'message', recommended_value: '', display_value: '本文', options: [] },
    { id: 'hidden-field', label: '', name: '_wpcf7', field_type: 'hidden', required: false, mapped_key: 'other', recommended_value: '123', display_value: '123', options: [] },
  ]
  items.push({
    company_id: 'company-ready', company_name: '準備可能・未確認候補', profile_id: 'profile-ready',
    form_url: 'https://example.com/contact-ready', fingerprint: 'c'.repeat(64), fields_hash: 'd'.repeat(64),
    reason_codes: ['READY'], ready_confirmation_only: true, fields: [], groups: [], saved_groups: [],
  })
  const submitted: { profile_id: string; action: string; confirmed_no_sales_prohibition: boolean }[] = []
  const policyActions: string[] = []
  const labelRuleActions: string[] = []
  const labelRules: { id: string; normalized_label: string; field_type: string; mapped_key: string; recommended_value: string; status: 'ACTIVE' | 'RETIRED'; created_at: string; retired_at: string | null }[] = []
  let policyEnabled = false
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
  await page.route(`**/api/projects/${fixture.project_id}/form-review-queue/summary`, route =>
    route.fulfill({ json: {
      total: items.length,
      by_readiness_reason: { NEEDS_MAPPING_REVIEW: 3, READY: 1 },
      by_review_message: [{ message: '入力項目の確認が必要です。', count: 3 }],
      unresolved_required_labels: [{ normalized_label: 'よみがな', field_type: 'text', form_count: 2, example_labels: ['よみがな（必須）'] }],
      consent_fields: { privacy_only_single_checkbox: 1, mixed_privacy_newsletter: 1, other: 0 },
    } }))
  await page.route(`**/api/projects/${fixture.project_id}/consent-policy**`, async route => {
    const action = new URL(route.request().url()).pathname.split('/').at(-1)
    if (route.request().method() === 'POST') {
      policyActions.push(action!)
      if (action === 'enable') policyEnabled = true
      if (action === 'disable') policyEnabled = false
    }
    const setting = {
      policy: 'CONSENT_POLICY_V1',
      conditions: ['個人情報同意に対応付けられたチェック欄であること', 'メルマガ配信を含まないこと'],
      enabled: policyEnabled, enabled_at: policyEnabled ? '2026-10-24T00:00:00Z' : null,
      can_manage: true, active_job: null,
    }
    await route.fulfill({ json: action === 'enable' || action === 'reset' ? { setting, job: null } : setting })
  })
  await page.route(`**/api/projects/${fixture.project_id}/form-label-rules**`, async route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/preview')) {
      await route.fulfill({ json: { form_count: 2, examples: [{ company_name: '確認例企業', form_url: 'https://example.com/contact' }] } })
      return
    }
    if (route.request().method() === 'POST' && url.pathname.endsWith('/form-label-rules')) {
      const body = route.request().postDataJSON()
      labelRuleActions.push(`create:${body.normalized_label}:${body.mapped_key}`)
      labelRules.push({ id: 'rule-1', normalized_label: body.normalized_label, field_type: body.field_type, mapped_key: body.mapped_key, recommended_value: body.recommended_value, status: 'ACTIVE', created_at: '2026-10-24T00:00:00Z', retired_at: null })
      await route.fulfill({ status: 202, json: { rule: labelRules[0], job: null } })
      return
    }
    if (route.request().method() === 'POST' && url.pathname.endsWith('/retire')) {
      labelRuleActions.push('retire:rule-1'); labelRules[0].status = 'RETIRED'; labelRules[0].retired_at = '2026-10-24T00:01:00Z'
      await route.fulfill({ json: labelRules[0] }); return
    }
    await route.fulfill({ json: { rules: labelRules, active_job: null, allowed_mapped_keys: ['furigana', 'email', 'message', 'other'] } })
  })
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
  await page.getByLabel('対象プロジェクト').selectOption(fixture.project_id)
  const formSummary = page.waitForResponse(response => response.url().includes(`/api/projects/${fixture.project_id}/send-flow-summary`))
  await page.getByRole('button', { name: 'フォーム', exact: true }).click()
  await formSummary
  const queueStage = page.getByRole('region', { name: '2. フォームを確認', exact: true })
  const queueStageHeader = queueStage.getByRole('button').first()
  await expect(queueStageHeader).toHaveAttribute('aria-expanded', 'true')
  await expect(queueStageHeader).toContainText('確認待ち 3社 · 確認不要：0社')

  const panel = page.getByRole('region', { name: 'フォーム確認キュー' })
  await expect(panel.getByRole('heading', { name: 'フォーム確認キュー' })).toBeVisible()
  await expect(panel.getByRole('heading', { name: '確認が必要な理由の集計（4件）' })).toBeVisible()
  const policyPanel = panel.getByRole('region', { name: '同意欄の自動判断設定' })
  await expect(policyPanel.getByText('CONSENT_POLICY_V1。送信・承認は行わず')).toBeVisible()
  await policyPanel.getByLabel('上記の条件に当てはまる同意欄を、プロジェクトの方針として自動でチェックすることを承認します').check()
  await policyPanel.getByRole('button', { name: '承認して有効にする' }).click()
  await expect(policyPanel.getByText('有効', { exact: true })).toBeVisible()
  expect(policyActions).toEqual(['enable'])
  await expect(panel.getByText('よみがな（text）: 2フォーム')).toBeVisible()
  await panel.getByRole('tab', { name: '項目名ごとに決める' }).click()
  await panel.getByLabel('よみがなの対応先').selectOption('furigana')
  page.once('dialog', dialog => dialog.accept())
  await panel.getByRole('button', { name: 'このルールを保存して2フォームに反映' }).click()
  await expect(panel.getByText('項目名ルールを保存し、バックグラウンド反映を開始しました。')).toBeVisible()
  expect(labelRuleActions).toEqual(['create:よみがな:furigana'])
  page.once('dialog', dialog => dialog.accept())
  await panel.getByRole('button', { name: '無効にする' }).click()
  await expect(panel.getByText('ルールを無効にしました。反映済みの項目は保持しています。')).toBeVisible()
  expect(labelRuleActions).toEqual(['create:よみがな:furigana', 'retire:rule-1'])
  await panel.getByRole('tab', { name: 'フォームごとに確認' }).click()
  await expect(panel.getByRole('heading', { name: '先頭のスキップ候補' })).toBeVisible()
  await expect(panel.getByText('_wpcf7')).toHaveCount(0)
  await panel.getByRole('button', { name: '仕組み用の項目を表示（1件）' }).click()
  await expect(panel.getByText('_wpcf7')).toBeVisible()
  await panel.getByRole('button', { name: '仕組み用の項目を隠す' }).click()
  await expect(panel.getByText('_wpcf7')).toHaveCount(0)
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
