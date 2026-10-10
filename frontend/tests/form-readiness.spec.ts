import { navigateWorkspace } from './navigation'
import { execFileSync } from 'node:child_process'
import { test, expect } from '@playwright/test'

test('stored form overview filters, paginates and does not authorize sending', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'approval-fixture'], { env: process.env, encoding: 'utf8' })) as { project_id: string; company_id: string }
  const row = { company_id: fixture.company_id, company_name: '集計テスト会社', category: 'candidate', form_url: 'https://example.com/contact', form_status: 'READY', analysis_version: '1.2', last_analyzed_at: null, review_reason: '', permission: { status: 'PROHIBITED', reason_code: 'suppression_domain', message: 'Suppression Listに登録された宛先には送信できません。' } }
  await page.route(`**/api/projects/${fixture.project_id}/form-readiness?**`, route => {
    const params = new URL(route.request().url()).searchParams
    const category = params.get('category')
    const offset = Number(params.get('offset'))
    const items = offset ? [] : category === 'all' ? [row] : [{ ...row, category: category === 'legacy' ? 'UNRECOGNIZED' : category, review_reason: category === 'captcha' ? '人による操作・確認が必要です。' : '', permission: { status: category === 'review' ? 'UNCERTAIN' : 'ALLOWED', reason_code: '', message: '保存情報からは未確定です。' } }]
    return route.fulfill({ json: { counts: { candidate: 26, captcha: 1 }, company_total: 27, total: category === 'captcha' ? 1 : 27, analysis_version: '1.2', items } })
  })
  const writes: string[] = []
  page.on('request', request => { if (request.url().includes('/api/') && request.method() !== 'GET' && !request.url().includes('/auth/') && !request.url().includes('/onboarding')) writes.push(request.url()) })
  await page.goto('/')
  await page.getByLabel('メールアドレス').fill(process.env.E2E_EMAIL!)
  await page.getByLabel('パスワード').fill(process.env.E2E_PASSWORD!)
  await page.getByRole('button', { name: 'ログインする', exact: true }).click()
  await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
  await navigateWorkspace(page, '▤ 企業一覧')
  await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(fixture.project_id)
  const panel = page.getByRole('region', { name: 'フォーム候補の集計' })
  await expect(panel.getByText('プロジェクト全体: 27社 / 現行解析: 1.2', { exact: true })).toBeVisible()
  await expect(panel.getByText(/連絡制御: Suppression/)).toBeVisible()
  await expect(panel.getByText(/次にすること：連絡制御によって停止しています/)).toBeVisible()
  await expect(panel.getByText(/送信許可の件数ではありません/)).toBeVisible()
  await panel.getByRole('button', { name: 'フォーム集計の次の25社' }).click()
  await expect(panel.getByRole('button', { name: '集計テスト会社の企業詳細を確認' })).toHaveCount(0)
  await expect(panel.getByText(/この表示範囲に該当する企業はありません/)).toBeVisible()
  await panel.getByRole('button', { name: 'フォーム集計の前の25社' }).click()
  await panel.getByRole('combobox', { name: 'フォーム集計の表示対象', exact: true }).selectOption('captcha')
  await expect(panel.getByText('表示対象: 1社', { exact: true })).toBeVisible()
  await expect(panel.getByText('人による操作・確認が必要です。', { exact: true })).toBeVisible()
  await expect(panel.getByText(/次にすること：CAPTCHAは人の操作・確認が必要/)).toBeVisible()
  for (const [category, text] of [
    ['review', '次にすること：連絡できるか未確定です。'],
    ['confirmation', '確認画面の発見は送信経路の検証完了ではありません。'],
    ['missing_form', '静的HTMLでの未検出をフォームなしと判断しないでください。'],
    ['prohibited', '項目修正や文面作成で禁止状態は解除できません。'],
    ['legacy', '分類不明のまま送信準備完了とは扱いません。'],
  ]) {
    await panel.getByRole('combobox', { name: 'フォーム集計の表示対象', exact: true }).selectOption(category)
    await expect(panel.getByText(text, { exact: false })).toBeVisible()
  }
  expect(writes).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width)
})
