import { navigateWorkspace } from './navigation'
import { execFileSync } from 'node:child_process'
import { test, expect } from '@playwright/test'

test('stored form Draft preparation submits only the reviewed hash without dispatch', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'approval-fixture'], { env: process.env, encoding: 'utf8' })) as { project_id: string; company_id: string }
  const forbidden: string[] = []
  page.on('request', request => { if (/\/send(?:[/?]|$)|\/execute|\/test-send|\/dispatch|\/form-delivery|\/form-preview/.test(request.url())) forbidden.push(request.url()) })
  await page.route(`**/api/companies/${fixture.company_id}/outreach-drafts`, route => route.fulfill({ json: [{ id: 'form-draft', channel: 'form', subject: 'フォーム提案', body: '個別の営業文面' }] }))
  await page.route('**/api/outreach-drafts/form-draft/form-approval-preview', route => route.fulfill({ json: {
    preparation_hash: 'a'.repeat(64), company_name: 'A2 E2E Company',
    proposal: { form_url: 'https://example.com/contact', subject: 'フォーム提案', body: '個別の営業文面', sender: { name: '担当者', email: 'sender@example.com' } },
    fields: [{ name: 'message', label: 'お問い合わせ内容', required: true, value: '個別の営業文面' }],
  } }))
  let submitted = false
  await page.route('**/api/outreach-drafts/form-draft/form-approval-request', route => {
    expect(route.request().postDataJSON()).toEqual({ expected_preparation_hash: 'a'.repeat(64) })
    submitted = true
    return route.fulfill({ status: 201, json: { status: 'PENDING' } })
  })
  await page.goto('/')
  await page.getByLabel('メールアドレス').fill(process.env.E2E_EMAIL!)
  await page.getByLabel('パスワード').fill(process.env.E2E_PASSWORD!)
  await page.getByRole('button', { name: 'ログインする', exact: true }).click()
  await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
  await navigateWorkspace(page, '✓ 承認キュー')
  await page.getByLabel('承認プロジェクト').selectOption(fixture.project_id)
  await page.getByRole('button', { name: 'フォーム候補を選ぶ', exact: true }).click()
  await page.getByLabel('フォーム提案先の会社').selectOption(fixture.company_id)
  await page.getByLabel('フォーム用Draft', { exact: true }).selectOption('form-draft')
  await page.getByRole('button', { name: '保存済みの入力内容を確認', exact: true }).click()
  const panel = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'フォームDraftから承認候補を準備' }) })
  await expect(panel.getByText('お問い合わせ内容（必須）')).toBeVisible()
  await expect(panel.getByText('フォームURL: https://example.com/contact')).toBeVisible()
  await page.getByRole('button', { name: 'フォーム提案を承認待ちに追加', exact: true }).click()
  await expect(panel.getByRole('status')).toContainText('送信は行っていません')
  expect(submitted).toBeTruthy()
  expect(forbidden).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width)
})
