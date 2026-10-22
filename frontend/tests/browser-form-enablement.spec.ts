import { execFileSync } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'
import { navigateWorkspace } from './navigation'

type BrowserFlags = {
  analysis: boolean
  dryRun: boolean
  delivery: boolean
}

async function openReadiness(page: Page, flags: BrowserFlags) {
  const python = process.env.PYTHON || (process.platform === 'win32'
    ? '../backend/.venv/Scripts/python.exe'
    : '../backend/.venv/bin/python')
  const fixture = JSON.parse(execFileSync(
    python,
    ['../backend/tests/e2e_user.py', 'approval-fixture'],
    { env: process.env, encoding: 'utf8' },
  )) as { project_id: string }
  await page.route(`**/api/projects/${fixture.project_id}/send-flow-summary`, route => route.fulfill({ json: {
    readiness_completed_at: null, target_company_count: 0,
    draft_counts: { email: 0, form: 0 }, form_reviewed_count: 0,
    approval_counts: { pending: { email: 0, form: 0 }, approved_unsent: { email: 0, form: 0 } },
    today: { sent: 0, reserved: 0 }, results: { sent: 0, failed: 0, unknown: 0 },
  } }))
  await page.route(`**/api/projects/${fixture.project_id}/outreach-templates`, route => route.fulfill({ json: [] }))
  await page.route(`**/api/projects/${fixture.project_id}/company-list?**`, route => route.fulfill({ json: { items: [], total: 0, offset: 0, limit: 20 } }))
  await page.route(`**/api/projects/${fixture.project_id}/form-dm-readiness**`, route => route.fulfill({ json: {
    counts: { BROWSER_READY: 3 }, total: 3, offset: 0, limit: 20, items: [],
    last_aggregated_at: new Date().toISOString(), last_aggregated_by_commit: 'abc1234',
    last_aggregated_by_host: 'worker-1', active_job: null, active_reanalysis_job: null,
    browser_analysis_enabled: flags.analysis,
    browser_dry_run_enabled: flags.dryRun,
    browser_delivery_enabled: flags.delivery,
    browser_analysis_job: null,
    browser_analysis_counts: {
      total: 7, contact_page_no_form: 0, embed_unverified: 0, contact_form_7: 3,
      multipart: 2, confirmation: 1, javascript_submission: 1,
      remaining_targets: 42, last_analyzed_at: null,
    },
    read_only: true, external_requests: 0,
  } }))

  await page.goto('/')
  await page.getByLabel('メールアドレス').fill(process.env.E2E_EMAIL!)
  await page.getByLabel('パスワード').fill(process.env.E2E_PASSWORD!)
  await page.getByRole('button', { name: 'ログインする', exact: true }).click()
  await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
  await navigateWorkspace(page, '▶ 送信の準備・実行')
  await page.evaluate(projectId => localStorage.setItem(`leadhive:send-channel:${projectId}`, 'form'), fixture.project_id)
  await page.getByLabel('対象プロジェクト').selectOption(fixture.project_id)
  await page.getByRole('region', { name: '送信先と文面の準備' }).getByText('フォームの送信可否集計・詳細').click()
  return page.getByRole('region', { name: 'フォームDM送信可否' })
}

test('shows browser analysis disabled state and remaining targets', async ({ page }) => {
  const panel = await openReadiness(page, { analysis: false, dryRun: false, delivery: false })
  await expect(panel.getByText('ブラウザー解析の残り：42社（1回に最大100社）')).toBeVisible()
  await expect(panel.getByText('ブラウザー解析は管理者の設定でOFFです。実際の動作にはWorker側の設定も必要です。')).toBeVisible()
})

test('shows delivery and dry-run disabled states', async ({ page }) => {
  const panel = await openReadiness(page, { analysis: true, dryRun: false, delivery: false })
  await expect(panel.getByText('ブラウザー送信は管理者の設定でOFFです。対象の確認とdry-runまでは行えます。dry-runも管理者の設定でOFFです。実際の動作にはWorker側の設定も必要です。')).toBeVisible()
})

test('hides browser feature warning when all flags are enabled', async ({ page }) => {
  const panel = await openReadiness(page, { analysis: true, dryRun: true, delivery: true })
  await expect(panel.getByText(/管理者の設定でOFF/)).toHaveCount(0)
  await expect(panel.getByText(/実際の動作にはWorker側の設定も必要です/)).toHaveCount(0)
})
