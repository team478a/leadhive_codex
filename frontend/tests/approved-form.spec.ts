import { execFileSync } from 'node:child_process'
import { test, expect } from '@playwright/test'

test('approved form reservations show disabled execution, cancellation and unknown protection', async ({ page }) => {
  const python = process.env.PYTHON || '../backend/.venv/Scripts/python.exe'
  const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'approval-fixture'], { env: process.env, encoding: 'utf8' })) as { project_id: string; company_id: string }
  const item = {
    id: 'form-approval', company_name: 'フォーム予約テスト会社', company_id: fixture.company_id,
    channel: 'form', recipient: null, form_url: 'https://example.com/contact', form_action_url: 'https://example.com/submit',
    subject: '営業提案', body: '承認した本文', sender: { name: '担当者', email: 'sender@example.com' },
    field_values: { message: '承認した本文' }, payload_hash: 'a'.repeat(64), payload_version: 1,
    status: 'APPROVED', created_by_principal_type: 'HUMAN', created_at: new Date().toISOString(), expires_at: new Date(Date.now() + 86400000).toISOString(),
  }
  const rows: Record<string, unknown>[] = []
  await page.route(`**/api/projects/${fixture.project_id}/approval-requests?**`, route => route.fulfill({ json: [item] }))
  await page.route(`**/api/projects/${fixture.project_id}/approved-form-dispatches?**`, route => route.fulfill({ json: rows }))
  let key = ''
  await page.route('**/api/approval-requests/form-approval/form-dispatch', route => {
    const body = route.request().postDataJSON()
    expect(body.expected_hash).toBe(item.payload_hash)
    expect(body.expected_version).toBe(1)
    expect(body.confirmed).toBeUndefined()
    key = body.idempotency_key
    rows.push({ id: 'reservation', approval_id: item.id, form_url: item.form_url, status: 'queued', reason: '', execution_enabled: false })
    return route.fulfill({ status: 201, json: rows[0] })
  })
  await page.route('**/api/approved-form-dispatches/reservation/cancel', route => {
    rows[0].status = 'cancelled'
    return route.fulfill({ json: rows[0] })
  })
  const forbidden: string[] = []
  page.on('request', request => { if (/\/form-delivery|\/execute|\/test-send/.test(request.url())) forbidden.push(request.url()) })
  await page.goto('/')
  await page.getByLabel('メールアドレス').fill(process.env.E2E_EMAIL!)
  await page.getByLabel('パスワード').fill(process.env.E2E_PASSWORD!)
  await page.getByRole('button', { name: 'ログインする', exact: true }).click()
  await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
  await page.getByRole('button', { name: '✓ 承認キュー', exact: true }).click()
  await page.getByLabel('承認プロジェクト').selectOption(fixture.project_id)
  const panel = page.getByRole('region', { name: '承認済みフォーム予約' })
  await panel.getByRole('button', { name: /フォーム予約テスト会社 の承認済みフォームを予約/ }).click()
  await expect(panel.getByRole('status')).toContainText('OFF')
  await expect(panel.getByText('実行OFF・送信されません')).toBeVisible()
  expect(key).toMatch(/^[a-f0-9-]{36}$/)
  await panel.getByRole('button', { name: 'フォーム予約を取り消す' }).click()
  await expect(panel.getByText(/取消済み/)).toBeVisible()
  rows.push({ id: 'unknown', approval_id: 'other-approval', form_url: item.form_url, status: 'unknown', reason: '結果不明・再送禁止', execution_enabled: false })
  await panel.getByRole('button', { name: 'フォーム予約の状態を更新' }).click()
  await expect(panel.getByRole('alert')).toContainText('再送禁止')
  await expect(panel.getByRole('button', { name: /再送|再試行/ })).toHaveCount(0)
  expect(forbidden).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width)
})

test('form bulk approval, idempotent reservation and saved administrator limits', async ({ page }) => {
  const python = process.env.PYTHON || '../backend/.venv/Scripts/python.exe'
  const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'approval-fixture'], { env: process.env, encoding: 'utf8' })) as { project_id: string; company_id: string }
  const item = {
    id: 'bulk-form', company_name: '一括フォーム会社', company_id: fixture.company_id,
    channel: 'form', recipient: null, form_url: 'https://example.com/contact', form_action_url: 'https://example.com/submit',
    subject: '提案', body: '会社別文面', sender: { name: '担当者', email: 'sender@example.com' }, field_values: { message: '会社別文面' },
    payload_hash: 'b'.repeat(64), payload_version: 1, status: 'PENDING', created_by_principal_type: 'HUMAN',
    created_at: new Date().toISOString(), expires_at: new Date(Date.now() + 86400000).toISOString(),
  }
  let limits = { daily_limit: 30, hourly_limit: 5, minimum_interval_seconds: 60, paused: false, version: 1, can_manage: true, execution_enabled: false }
  await page.route(`**/api/projects/${fixture.project_id}/approval-requests?**`, route => route.fulfill({ json: [item] }))
  await page.route('**/api/form-dispatch-limits', route => {
    if (route.request().method() === 'PUT') {
      const body = route.request().postDataJSON()
      expect(body.expected_version).toBe(limits.version)
      expect(body.password).toBe('mock-human-password')
      expect(body.execution_enabled).toBeUndefined()
      limits = { ...limits, daily_limit: body.daily_limit, paused: body.paused, version: limits.version + 1 }
    }
    return route.fulfill({ json: limits })
  })
  await page.route(`**/api/projects/${fixture.project_id}/bulk-approval/*`, route => {
    const action = route.request().url().split('/').at(-1)
    if (action === 'challenge') {
      expect(route.request().postDataJSON().items).toEqual([{ request_id: item.id, expected_hash: item.payload_hash, expected_version: 1 }])
      return route.fulfill({ json: { challenge_token: 'mock-bound-token' } })
    }
    if (action === 'verify') expect(route.request().postDataJSON().password).toBe('mock-human-password')
    if (action === 'approve') item.status = 'APPROVED'
    return route.fulfill({ json: { approved_count: 1 } })
  })
  const keys: string[] = []
  await page.route(`**/api/projects/${fixture.project_id}/approved-form-dispatches`, route => {
    const body = route.request().postDataJSON()
    keys.push(body.idempotency_key)
    expect(body.items).toEqual([{ request_id: item.id, expected_hash: item.payload_hash, expected_version: 1 }])
    return route.fulfill({ status: 201, json: { results: [{ request_id: item.id, reservation: { id: 'same-reservation' }, error: null }] } })
  })
  await page.goto('/')
  await page.getByLabel('メールアドレス').fill(process.env.E2E_EMAIL!)
  await page.getByLabel('パスワード').fill(process.env.E2E_PASSWORD!)
  await page.getByRole('button', { name: 'ログインする', exact: true }).click()
  await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
  await page.getByRole('button', { name: '✓ 承認キュー', exact: true }).click()
  await page.getByLabel('承認プロジェクト').selectOption(fixture.project_id)
  const panel = page.getByRole('region', { name: 'フォーム一括承認と上限管理' })
  await panel.getByRole('button', { name: 'このページのフォームをまとめて選択' }).click()
  await panel.getByLabel('フォーム一括承認用ログインパスワード').fill('mock-human-password')
  await panel.getByRole('button', { name: 'フォーム1件を一括Human承認', exact: true }).click()
  await expect(panel.getByRole('status')).toContainText('まだ予約していません')
  await panel.getByRole('button', { name: '承認済みフォーム1件を一括予約', exact: true }).click()
  await expect(panel.getByRole('status')).toContainText('実送信はOFF')
  await panel.getByRole('button', { name: '承認済みフォーム1件を一括予約', exact: true }).click()
  expect(keys).toHaveLength(2)
  expect(keys[0]).toBe(keys[1])
  await panel.getByLabel('フォーム24時間上限').fill('500')
  await expect(panel.getByText(/保存済み: 直近24時間30件/)).toBeVisible()
  await panel.getByLabel('フォーム実行を一時停止').check()
  await panel.getByLabel('上限変更用管理者パスワード').fill('mock-human-password')
  await panel.getByRole('button', { name: '管理者再認証してフォーム上限を保存' }).click()
  await expect(panel.getByText(/保存済み: 直近24時間500件.*一時停止中.*OFF/)).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width)
})
