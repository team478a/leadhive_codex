import { navigateWorkspace } from './navigation'
import { execFileSync } from 'node:child_process'
import { test, expect } from '@playwright/test'

// Component workflow uses synthetic API responses. Backend tests exercise real step-up/DB guards.
test('real CF7 candidate review uses Human queue and never exposes dispatch', async ({ page }) => {
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
  let challenges = 0, approvals = 0
  const forbidden: string[] = []
  page.on('request', request => { if (request.method() === 'POST' && /\/(send|execute|test-send|form-dispatch)(?:[/?]|$)/.test(request.url())) forbidden.push(request.url()) })
  await page.route(`**/api/projects/${fixture.project_id}/approval-requests*`, route => route.fulfill({ json: [item] }))
  await page.route(`**/api/projects/${fixture.project_id}/approval-audit*`, route => route.fulfill({ json: [] }))
  const base = `**/api/approval-requests/${item.id}`
  await page.route(base + '/challenge', route => {
    expect(route.request().postDataJSON()).toEqual({ expected_hash: item.payload_hash, expected_version: 1 })
    challenges++
    return route.fulfill({ json: { challenge_token: 't'.repeat(43) } })
  })
  await page.route(base + '/challenge/verify', route => {
    expect(route.request().postDataJSON().password === process.env.E2E_PASSWORD).toBe(true)
    return route.fulfill({ json: { verified: true } })
  })
  await page.route(base + '/approve', route => {
    expect(route.request().postDataJSON()).toEqual({ expected_hash: item.payload_hash, expected_version: 1, challenge_token: 't'.repeat(43) })
    approvals++
    item.status = 'APPROVED'
    return route.fulfill({ json: item })
  })
  await page.route(base + '/revoke', route => { item.status = 'REVOKED'; return route.fulfill({ json: item }) })
  await page.goto('/')
  await page.getByLabel('メールアドレス').fill(process.env.E2E_EMAIL!)
  await page.getByLabel('パスワード').fill(process.env.E2E_PASSWORD!)
  await page.getByRole('button', { name: 'ログインする', exact: true }).click()
  await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
  await navigateWorkspace(page, '✓ 承認キュー')
  await page.getByLabel('承認プロジェクト').selectOption(fixture.project_id)
  await page.getByRole('button', { name: /Real CF7 Review Fixture.*承認待ち/ }).click()
  const article = page.getByRole('article')
  await expect(article.getByRole('region', { name: '実サイトCF7候補の承認資料' })).toContainText('承認後も送信予約・実送信には使用できません')
  const approve = article.getByRole('button', { name: 'CF7候補内容を承認（送信不可）', exact: true })
  await expect(approve).toBeDisabled()
  await article.getByLabel('実サイトの宛先・入力内容・証拠期限を確認しました（送信不可）').check()
  await article.getByLabel('承認用パスワード（再認証）').fill(process.env.E2E_PASSWORD!)
  await approve.click()
  await expect(page.getByRole('button', { name: /Real CF7 Review Fixture.*承認済み/ })).toBeVisible()
  expect(challenges).toBe(1); expect(approvals).toBe(1)
  await expect(approve).toHaveCount(0)
  await expect(page.getByRole('region', { name: '承認済みフォーム予約' }).getByText('Real CF7 Review Fixture', { exact: true })).toHaveCount(0)
  await article.getByLabel('却下・取消の理由').fill('Fixture cancellation')
  await article.getByRole('button', { name: '取消', exact: true }).click()
  await expect(page.getByRole('button', { name: /Real CF7 Review Fixture.*取消済み/ })).toBeVisible()
  expect(forbidden).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
})
