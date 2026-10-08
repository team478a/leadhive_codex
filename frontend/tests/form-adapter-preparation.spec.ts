import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { test, expect } from '@playwright/test'

test('controlled plan is prepared, human approved and reserved without execution', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const env = { ...process.env, E2E_EMAIL: `e2e-adapter-${randomBytes(8).toString('hex')}@example.com`, E2E_PASSWORD: randomBytes(24).toString('hex') }
  execFileSync(python, ['../backend/tests/e2e_user.py', 'create'], { env })
  const forbidden: string[] = []
  page.on('request', request => {
    if (!new URL(request.url()).hostname.match(/^(localhost|127\.0\.0\.1)$/) || /\/send(?:[/?]|$)|\/execute|\/test-send/.test(request.url())) forbidden.push(request.url())
  })
  try {
    const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'adapter-fixture'], { env, encoding: 'utf8' })) as { project_id: string; company_id: string }
    await page.goto('/')
    await page.getByLabel('メールアドレス').fill(env.E2E_EMAIL)
    await page.getByLabel('パスワード').fill(env.E2E_PASSWORD)
    await page.getByRole('button', { name: 'ログインする', exact: true }).click()
    await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
    await page.getByRole('button', { name: '✓ 承認キュー', exact: true }).click()
    await page.getByLabel('承認プロジェクト').selectOption(fixture.project_id)
    await page.getByLabel('フォーム準備方式').selectOption('adapter')
    await page.getByRole('button', { name: 'フォーム候補を選ぶ', exact: true }).click()
    await page.getByLabel('フォーム提案先の会社').selectOption(fixture.company_id)
    await page.getByLabel('フォーム用Draft', { exact: true }).selectOption({ label: 'Synthetic adapter draft' })
    await page.getByRole('button', { name: '保存済みの入力内容を確認', exact: true }).click()
    await expect(page.getByRole('region', { name: '管理下フォームの操作計画' })).toContainText('controlled_lab_single_post')
    await page.getByRole('button', { name: 'フォーム提案を承認待ちに追加', exact: true }).click()
    await page.getByRole('button', { name: /A2 E2E Company.*承認待ち/ }).click()
    await expect(page.getByRole('region', { name: '管理下フォームの操作計画' })).toContainText('実行器は未接続')
    await page.getByLabel('承認用パスワード（再認証）').fill(env.E2E_PASSWORD)
    await page.getByRole('button', { name: '内容を確認して承認', exact: true }).click()
    await expect(page.getByRole('button', { name: 'A2 E2E Company · form · v1 · 承認済み（未送信）', exact: true })).toBeVisible()
    const reservations = page.getByRole('region', { name: '承認済みフォーム予約' })
    await reservations.getByRole('button', { name: 'A2 E2E Company の承認済みフォームを予約', exact: true }).click()
    await expect(reservations.getByText('予約のみ・実行未接続', { exact: true })).toBeVisible()
    await reservations.getByRole('button', { name: 'フォーム予約を取り消す', exact: true }).click()
    await expect(reservations.getByText(/取消済み/)).toBeVisible()
    expect(forbidden).toEqual([])
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  } finally {
    execFileSync(python, ['../backend/tests/e2e_user.py', 'cleanup'], { env })
  }
})
