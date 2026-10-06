import { execFileSync } from 'node:child_process'
import { test, expect } from '@playwright/test'

test('Human operations prepare a new candidate and record UNKNOWN without dispatch', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'approval-fixture'], { env: process.env, encoding: 'utf8' })) as { project_id: string }
  const common = { form_url: 'https://example.com/contact', reason: '', expires_at: new Date().toISOString(), started_at: null, approval_status: 'EXPIRED', payload_hash: 'a'.repeat(64), payload_version: 1, review: null }
  const rows = [
    { ...common, id: 'expired', company_name: '期限切れ会社', status: 'blocked', category: 'expired', can_reprepare: true },
    { ...common, id: 'unknown', company_name: '結果不明会社', status: 'unknown', category: 'unknown', can_reprepare: false },
  ]
  await page.route(`**/api/projects/${fixture.project_id}/approval-requests?**`, route => route.fulfill({ json: [] }))
  await page.route(`**/api/projects/${fixture.project_id}/form-operations?**`, route => {
    const category = new URL(route.request().url()).searchParams.get('category')
    const filtered = ['attention', 'all'].includes(category!) ? rows : rows.filter(row => row.category === category)
    return route.fulfill({ json: { counts: { expired: 1, unknown: 1 }, total: filtered.length, items: filtered } })
  })
  await page.route('**/api/approved-form-dispatches/expired/reprepare-preview', route => route.fulfill({ json: {
    preparation_hash: 'b'.repeat(64), company_name: '期限切れ会社', fields: [{ name: 'message', label: '本文', required: true, value: '最新の提案' }],
    proposal: { form_url: common.form_url, subject: '新しい提案', body: '最新の提案', sender: { name: '担当者', email: 'sender@example.com' } },
  } }))
  await page.route('**/api/approved-form-dispatches/expired/reprepare', route => {
    expect(route.request().postDataJSON()).toEqual({ expected_hash: common.payload_hash, expected_version: 1, expected_preparation_hash: 'b'.repeat(64) })
    return route.fulfill({ status: 201, json: { id: 'new-candidate', status: 'PENDING' } })
  })
  await page.route('**/api/approved-form-dispatches/unknown/review', route => {
    expect(route.request().postDataJSON().choice).toBe('received')
    return route.fulfill({ json: { recorded: true, status: 'unknown', retry_allowed: false } })
  })
  const forbidden: string[] = []
  page.on('request', request => { if (/\/form-delivery|\/execute|\/test-send|\/retry|\/form-dispatch$/.test(request.url())) forbidden.push(request.url()) })
  await page.goto('/')
  await page.getByLabel('メールアドレス').fill(process.env.E2E_EMAIL!)
  await page.getByLabel('パスワード').fill(process.env.E2E_PASSWORD!)
  await page.getByRole('button', { name: 'ログインする', exact: true }).click()
  await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
  await page.getByRole('button', { name: '✓ 承認キュー', exact: true }).click()
  await page.getByLabel('承認プロジェクト').selectOption(fixture.project_id)
  const panel = page.getByRole('region', { name: 'フォーム運用確認' })
  await panel.getByRole('button', { name: '期限切れ会社の現在の内容を再準備' }).click()
  await expect(panel.getByText('新しい提案', { exact: true })).toBeVisible()
  await panel.getByRole('button', { name: '現在の内容を確認して承認候補へ追加' }).click()
  await expect(panel.getByRole('status')).toContainText('PENDING')
  await panel.getByLabel('結果不明会社の結果確認').selectOption('received')
  await panel.getByRole('button', { name: '結果不明会社の確認記録を保存' }).click()
  await expect(panel.getByRole('status')).toContainText('UNKNOWN、再送禁止')
  await panel.getByLabel('フォーム運用の表示対象').selectOption('unknown')
  await expect(panel.getByText('表示対象: 1件', { exact: true })).toBeVisible()
  await expect(panel.getByRole('button', { name: /再送|再試行/ })).toHaveCount(0)
  expect(forbidden).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width)
})
