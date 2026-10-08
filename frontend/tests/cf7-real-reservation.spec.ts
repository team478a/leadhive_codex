import { execFileSync } from 'node:child_process'
import { test, expect } from '@playwright/test'

// Component workflow uses synthetic API responses. Backend tests exercise real step-up/DB guards.
test('CF7 separate reapproval saves reservation only', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'approval-fixture'], { env: process.env, encoding: 'utf8' })) as { project_id: string; company_id: string }
  const item = {
    id: 'b49cffdd-4909-4836-bc6f-432370515fe2', project_id: fixture.project_id,
    company_id: fixture.company_id, company_name: 'Real CF7 Review Fixture', channel: 'form',
    delivery_method: 'cf7_real_candidate_only', form_url: 'https://managed.example/contact',
    form_action_url: 'https://managed.example/wp-json/contact-form-7/v1/contact-forms/7/feedback',
    recipient: null, subject: 'Fixture subject', body: 'Fixture candidate body',
    sender: { name: 'Fixture sender', email: 'sender@example.com' }, field_values: { body: 'Fixture candidate body' },
    payload_hash: 'a'.repeat(64), payload_version: 1, status: 'PENDING',
    created_by_principal_type: 'HUMAN', created_at: '2026-10-08T01:00:00Z', expires_at: '2099-01-01T00:00:00Z',
    rejection_reason: null, invalidation_reason: null,
    cf7_real_handoff: { snapshot_hash: 'b'.repeat(64), snapshot: {
      expires_at: '2099-01-01T00:00:00Z', input_review: { actor_user_id: 'fixture-human', reviewed_at: '2026-10-08T01:00:00Z' },
      encoding: { wire_size: 1234, wire_sha256: 'c'.repeat(64) },
      contract: { contract_family: 'cf7-6.2', endpoint: 'https://managed.example/wp-json/contact-form-7/v1/contact-forms/7/feedback' },
    } },
  }
  item.status = 'APPROVED'
  const next = { ...item, id: 'bf31cc2f-aa05-41ea-ad83-16b2a3280e2f', delivery_method: 'cf7_real_reservation', status: 'PENDING', payload_hash: 'd'.repeat(64), cf7_reservation_plan: { source_approval_id: item.id, source_approval_hash: item.payload_hash, source_approval_version: 1, expires_at: item.expires_at, environment: 'RESERVATION_ONLY', execution_allowed: false } }
  const items = [item]
  const reservations: object[] = []
  let challenges = 0, approvals = 0
  const forbidden: string[] = []
  page.on('request', request => { if (request.method() === 'POST' && /\/(send|execute|test-send)(?:[/?]|$)/.test(request.url())) forbidden.push(request.url()) })
  await page.route(`**/api/projects/${fixture.project_id}/approval-requests*`, route => route.fulfill({ json: items }))
  await page.route(`**/api/projects/${fixture.project_id}/approval-audit*`, route => route.fulfill({ json: [] }))
  await page.route(`**/api/approval-requests/${item.id}/cf7-reservation-preview`, route => route.fulfill({ json: { plan: next.cf7_reservation_plan, preparation_hash: 'e'.repeat(64) } }))
  await page.route(`**/api/approval-requests/${item.id}/cf7-reservation-request`, route => {
    expect(route.request().postDataJSON()).toEqual({ expected_preparation_hash: 'e'.repeat(64) })
    items.push(next); return route.fulfill({ json: next })
  })
  await page.route(`**/api/projects/${fixture.project_id}/approved-form-dispatches*`, route => route.fulfill({ json: reservations }))
  const base = `**/api/approval-requests/${next.id}`
  await page.route(base + '/challenge', route => {
    expect(route.request().postDataJSON()).toEqual({ expected_hash: next.payload_hash, expected_version: 1 })
    challenges++; return route.fulfill({ json: { challenge_token: 't'.repeat(43) } })
  })
  await page.route(base + '/challenge/verify', route => {
    expect(route.request().postDataJSON().password === process.env.E2E_PASSWORD).toBe(true)
    return route.fulfill({ json: { verified: true } })
  })
  await page.route(base + '/approve', route => {
    expect(route.request().postDataJSON()).toEqual({ expected_hash: next.payload_hash, expected_version: 1, challenge_token: 't'.repeat(43) })
    approvals++; next.status = 'APPROVED'; return route.fulfill({ json: next })
  })
  await page.route(base + '/form-dispatch', route => {
    expect(route.request().postDataJSON().expected_hash).toBe(next.payload_hash)
    const row = { id: 'reservation-fixture', approval_id: next.id, form_url: next.form_url, status: 'queued', reason: '', execution_enabled: false, reservation_only: true, created_at: item.created_at }
    reservations.push(row); return route.fulfill({ json: row })
  })
  await page.goto('/')
  await page.getByLabel('メールアドレス').fill(process.env.E2E_EMAIL!)
  await page.getByLabel('パスワード').fill(process.env.E2E_PASSWORD!)
  await page.getByRole('button', { name: 'ログインする', exact: true }).click()
  await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
  await page.getByRole('button', { name: '✓ 承認キュー', exact: true }).click()
  await page.getByLabel('承認プロジェクト').selectOption(fixture.project_id)
  await page.getByRole('button', { name: /Real CF7 Review Fixture.*承認済み/ }).click()
  await page.getByRole('button', { name: '予約用の準備内容を確認', exact: true }).click()
  await page.getByRole('button', { name: '予約用の別承認候補を保存', exact: true }).click()
  await page.getByRole('button', { name: /Real CF7 Review Fixture.*承認待ち/ }).click()
  const article = page.getByRole('article')
  const approve = article.getByRole('button', { name: '予約内容を再承認（送信不可）', exact: true })
  await expect(approve).toBeDisabled()
  await article.getByLabel('宛先・入力内容・期限を確認しました（予約のみ・送信不可）').check()
  await article.getByLabel('承認用パスワード（再認証）').fill(process.env.E2E_PASSWORD!)
  await approve.click()
  await expect.poll(() => challenges).toBe(1); await expect.poll(() => approvals).toBe(1)
  const panel = page.getByRole('region', { name: '承認済みフォーム予約' })
  const reserve = panel.getByRole('button', { name: 'Real CF7 Review Fixture の承認済みフォームを予約', exact: true })
  await reserve.click()
  await expect(reserve).toBeDisabled()
  await expect(panel).toContainText('この予約から送信は始まりません')
  await expect(panel).toContainText('予約のみ・実行未接続')
  expect(forbidden).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
})
