import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { test, expect } from '@playwright/test'

test('stored CF7 choices, human proof, source invalidation and revision never dispatch', async ({ page }) => {
  test.setTimeout(120_000) // Full preparation + two real password step-ups + revision.
  test.skip(process.env.CF7_E2E_DISPOSABLE_DATABASE !== 'true', 'Requires disposable CF7 P3 database; immutable evidence must not be deleted')
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const env = { ...process.env, E2E_EMAIL: `e2e-cf7-${randomBytes(8).toString('hex')}@example.com`, E2E_PASSWORD: randomBytes(24).toString('hex') }
  execFileSync(python, ['../backend/tests/e2e_user.py', 'create'], { env })
  const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'approval-fixture'], { env, encoding: 'utf8' })) as { company_id: string; project_id: string }
  const seeded = JSON.parse(execFileSync(python, ['../backend/tests/e2e_cf7.py', 'seed', fixture.company_id], { env, encoding: 'utf8' })) as { draft_id: string }
  const forbidden: string[] = []
  page.on('request', req => {
    if (!['127.0.0.1', 'localhost'].includes(new URL(req.url()).hostname) || /\/form-dispatch$|\/send|\/execute|\/test-send/.test(req.url())) forbidden.push(req.url())
  })
  // Real API and PostgreSQL throughout; no response mocks and no outbound worker.
  await page.goto('/')
  await page.getByLabel('メールアドレス').fill(env.E2E_EMAIL)
  await page.getByLabel('パスワード').fill(env.E2E_PASSWORD)
  await page.getByRole('button', { name: 'ログインする', exact: true }).click()
  await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
  await page.getByRole('button', { name: '✓ 承認キュー', exact: true }).click()
  await page.getByLabel('承認プロジェクト').selectOption(fixture.project_id)
  const panel = page.getByRole('region', { name: 'CF7候補の準備', exact: true })
  await panel.getByRole('button', { name: 'CF7候補の会社を選ぶ', exact: true }).click()
  await panel.getByLabel('CF7候補の会社', { exact: true }).selectOption(fixture.company_id)
  await panel.getByLabel('CF7フォームDraft').selectOption(seeded.draft_id)
  async function choices(region: ReturnType<typeof page.getByRole>) {
    await region.getByRole('button', { name: 'CF7証拠・同意欄を取得', exact: true }).click()
    await expect(region.getByRole('button', { name: 'CF7選択済み内容を確認', exact: true })).toBeDisabled()
    await region.getByLabel('問い合わせ内容への同意（必須）').selectOption('true')
    await expect(region.getByRole('button', { name: 'CF7選択済み内容を確認', exact: true })).toBeDisabled()
    await region.getByLabel('ニュース配信を購読する（任意）').selectOption('false')
    await region.getByRole('button', { name: 'CF7選択済み内容を確認', exact: true }).click()
    await expect(region.getByRole('region', { name: 'CF7候補の確認内容' })).toContainText('選択しない / 値: subscribe')
    await region.getByLabel('入力値・同意・期限を確認しました（送信不可）').check()
  }
  await choices(panel)
  await panel.getByRole('button', { name: 'CF7候補を承認待ちに保存', exact: true }).click()
  await page.getByRole('button', { name: 'CF7 Browser Fixture · form · v1 · 承認待ち', exact: true }).click()
  const approve = page.getByRole('button', { name: 'CF7候補内容を承認（送信不可）', exact: true })
  await expect(approve).toBeDisabled()
  async function humanApprove() {
    await page.getByLabel('CF7の入力値・同意・証拠期限を確認しました', { exact: true }).check()
    await page.getByLabel('承認用パスワード（再認証）').fill(env.E2E_PASSWORD)
    await approve.click()
  }
  await humanApprove()
  await expect(page.getByRole('button', { name: 'CF7 Browser Fixture · form · v1 · 承認済み（未送信）', exact: true })).toBeVisible()
  execFileSync(python, ['../backend/tests/e2e_cf7.py', 'change-draft', fixture.company_id], { env })
  await page.getByRole('button', { name: '最新の状態を取得', exact: true }).click()
  await expect(page.getByText('この候補は承認に使えません。', { exact: false })).toBeVisible()
  const revision = page.getByRole('region', { name: 'CF7候補の改訂', exact: true })
  await choices(revision)
  await expect(revision).toContainText('変更後の日本語本文')
  await revision.getByRole('button', { name: 'CF7改訂候補を承認待ちに保存', exact: true }).click()
  await page.getByRole('button', { name: 'CF7 Browser Fixture · form · v2 · 承認待ち', exact: true }).click()
  await expect(approve).toBeDisabled()
  await humanApprove()
  await expect(page.getByRole('button', { name: 'CF7 Browser Fixture · form · v2 · 承認済み（未送信）', exact: true })).toBeVisible()
  await page.getByLabel('却下・取消の理由').fill('検証終了')
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await expect(page.getByRole('button', { name: 'CF7 Browser Fixture · form · v2 · 取消済み', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'CF7 Browser Fixture の承認済みフォームを予約', exact: true })).toHaveCount(0)
  expect(forbidden).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  // Evidence/proofs/ledger retained. Runner drops only this whole disposable DB after teardown.
})
