import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { test, expect } from '@playwright/test'

test('diagnostic history remains separate from permission, job failure and old installations', async ({ page }) => {
  test.setTimeout(180_000)
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const env = { ...process.env, E2E_EMAIL: `e2e-observation-${randomBytes(8).toString('hex')}@example.com`, E2E_PASSWORD: randomBytes(24).toString('hex') }
  execFileSync(python, ['../backend/tests/e2e_user.py', 'create'], { env })
  const forbidden: string[] = []
  page.on('request', request => {
    if (!['localhost', '127.0.0.1'].includes(new URL(request.url()).hostname) || /\/send|\/dispatch|\/execute|\/test-send/.test(request.url())) forbidden.push(request.url())
  })
  try {
    const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'approval-fixture'], { env, encoding: 'utf8' })) as { project_id: string; company_id: string }
    let mode = 'history'
    await page.route(`**/api/companies/${fixture.company_id}/form-observations*`, route => {
      if (mode === 'old') return route.fulfill({ json: { available: false, items: [], has_more: false, latest_job: null } })
      if (mode === 'error') return route.fulfill({ status: 500, json: { detail: 'internal-secret' } })
      return route.fulfill({ json: {
        available: true, has_more: false,
        latest_job: { id: 'job', status: 'failed', processed_count: 1, success_count: 0, failed_count: 1 },
        items: [{ id: 'evidence', operation_job_id: 'old-job', observed_at: '2026-01-01T00:00:00Z', expires_at: '2026-01-02T00:00:00Z', snapshot_hash: '<img src=x onerror=alert(1)>', freshness: 'EXPIRED', reason: 'STATIC_ONLY_UNVERIFIED', diagnostic: { sales_permission: 'UNCERTAIN', captcha_state: 'UNVERIFIED' }, raw_body: 'internal-secret' }],
      } })
    })
    await page.goto('/')
    await page.getByLabel('メールアドレス').fill(env.E2E_EMAIL)
    await page.getByLabel('パスワード').fill(env.E2E_PASSWORD)
    await page.getByRole('button', { name: 'ログインする', exact: true }).click()
    await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
    await page.getByRole('button', { name: '▤ 企業一覧', exact: true }).click()
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(fixture.project_id)
    await page.getByRole('button', { name: '詳細', exact: true }).first().click()
    const panel = page.getByRole('region', { name: '静的フォーム観察履歴' })
    await expect(panel.getByText('期限切れ', { exact: true })).toBeVisible()
    await expect(panel).toContainText('最新の観察処理：失敗')
    await expect(panel).toContainText('送信許可・Human Approval・送信準備完了を意味しません')
    await expect(panel).toContainText('営業可否：不明・未検証 / CAPTCHA：不明・未検証')
    await expect(panel.locator('img, script')).toHaveCount(0)
    await expect(panel).not.toContainText('internal-secret')
    await expect(panel.getByRole('button')).toHaveCount(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
    for (const next of ['old', 'error']) {
      mode = next
      await page.getByRole('button', { name: '閉じる', exact: true }).first().click()
      await page.getByRole('button', { name: '詳細', exact: true }).first().click()
      await expect(panel).toContainText(next === 'old' ? '観察保存機能が未導入です' : '観察履歴を取得できません')
      await expect(panel).not.toContainText('internal-secret')
    }
    expect(forbidden).toEqual([])
  } finally {
    execFileSync(python, ['../backend/tests/e2e_user.py', 'cleanup'], { env })
  }
})

test('managed observation controls queue, stop and recover without any send action', async ({ page }) => {
  test.setTimeout(180_000)
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const env = { ...process.env, E2E_EMAIL: `e2e-observation-controls-${randomBytes(8).toString('hex')}@example.com`, E2E_PASSWORD: randomBytes(24).toString('hex') }
  execFileSync(python, ['../backend/tests/e2e_user.py', 'create'], { env })
  const forbidden: string[] = []
  page.on('request', request => {
    if (!['localhost', '127.0.0.1'].includes(new URL(request.url()).hostname) || /\/send|\/dispatch|\/execute|\/test-send/.test(request.url())) forbidden.push(request.url())
  })
  try {
    const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'approval-fixture'], { env, encoding: 'utf8' })) as { project_id: string; company_id: string }
    let state = ''
    const calls: string[] = []
    function job() {
      return { id: 'managed-job', status: state, cancel_requested: false, recoverable: state === 'running', reason_code: state === 'failed' ? 'WORKER_LOST' : null,
        events: [{ id: 'event', event_type: 'QUEUED', reason_code: 'QUEUED', principal_type: 'HUMAN', created_at: '2026-01-01T00:00:00Z' }], events_has_more: false }
    }
    await page.route(`**/api/companies/${fixture.company_id}/form-observation-jobs*`, async route => {
      if (route.request().method() === 'POST') {
        expect(route.request().postDataJSON()).toEqual({})
        calls.push('queue'); state = 'queued'
        return route.fulfill({ status: 202, json: job() })
      }
      return route.fulfill({ json: { available: true, can_start: true, can_manage: true, items: state ? [job()] : [], has_more: false } })
    })
    await page.route('**/api/form-observation-jobs/managed-job/*', async route => {
      expect(route.request().postDataJSON()).toEqual({})
      const action = route.request().url().split('/').pop()!
      calls.push(action); state = action === 'cancel' ? 'cancelled' : 'failed'
      return route.fulfill({ json: job() })
    })
    await page.goto('/')
    await page.getByLabel('メールアドレス').fill(env.E2E_EMAIL)
    await page.getByLabel('パスワード').fill(env.E2E_PASSWORD)
    await page.getByRole('button', { name: 'ログインする', exact: true }).click()
    await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
    await page.getByRole('button', { name: '▤ 企業一覧', exact: true }).click()
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(fixture.project_id)
    await page.getByRole('button', { name: '詳細', exact: true }).first().click()
    const panel = page.getByRole('region', { name: '静的フォーム観察履歴' })
    await panel.getByRole('button', { name: '管理下の観察を登録', exact: true }).click()
    await expect(panel).toContainText('ジョブ状態：待機中')
    await expect(panel.getByRole('button', { name: '管理下の観察を登録' })).toBeDisabled()
    await panel.getByRole('button', { name: '観察ジョブを停止', exact: true }).click()
    await expect(panel).toContainText('ジョブ状態：停止済み')
    state = 'running'
    await panel.getByRole('button', { name: '観察ジョブの状態を更新', exact: true }).click()
    await panel.getByRole('button', { name: '期限切れの観察ジョブを終了', exact: true }).click()
    await expect(panel).toContainText('担当処理の有効期限切れ')
    await expect(panel.getByRole('button', { name: /送信|承認/ })).toHaveCount(0)
    expect(calls).toEqual(['queue', 'cancel', 'recover'])
    expect(forbidden).toEqual([])
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  } finally {
    execFileSync(python, ['../backend/tests/e2e_user.py', 'cleanup'], { env })
  }
})
