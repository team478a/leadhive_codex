import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { test, expect } from '@playwright/test'

test('Human freezes the funnel denominator and records review effort without approval or sending', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const env = { ...process.env, E2E_EMAIL: `e2e-metrics-${randomBytes(8).toString('hex')}@example.com`, E2E_PASSWORD: randomBytes(24).toString('hex') }
  execFileSync(python, ['../backend/tests/e2e_user.py', 'create'], { env })
  const forbidden: string[] = []
  page.on('request', request => {
    if (!['localhost', '127.0.0.1'].includes(new URL(request.url()).hostname) || /\/send(?:[/?]|$)|\/dispatch|\/execute|\/test-send|\/approve/.test(request.url())) forbidden.push(request.url())
  })
  try {
    const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'completion-fixture'], { env, encoding: 'utf8' })) as { project_id: string }
    await page.goto('/')
    await page.getByLabel('メールアドレス').fill(env.E2E_EMAIL)
    await page.getByLabel('パスワード').fill(env.E2E_PASSWORD)
    await page.getByRole('button', { name: 'ログインする', exact: true }).click()
    await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
    await page.getByRole('button', { name: '⌂ ダッシュボード', exact: true }).click()
    const panel = page.getByRole('region', { name: 'Lead Completion計測' })
    await panel.getByLabel('完成率のプロジェクト').selectOption(fixture.project_id)
    await panel.getByRole('button', { name: '現在のリストを集計対象として固定', exact: true }).click()
    await expect(panel).toContainText('DM READY率')
    await expect(panel).toContainText('未判定')
    await expect(panel).toContainText('料金・Cost per DM READYは不明')
    const diagnostic = panel.getByRole('region', { name: '固定リストの窓口診断' })
    let release: () => void = () => {}
    const gate = new Promise<void>(resolve => { release = resolve })
    let hold = true
    let syntheticUnknown = false
    await page.route('**/destination-diagnostics?*', async route => {
      if (new URL(route.request().url()).searchParams.get('offset') === '25' && hold) { hold = false; await gate }
      if (syntheticUnknown && new URL(route.request().url()).searchParams.get('offset') === '0') {
        // Response-only safety fixture; no send or database history is fabricated.
        const response = await route.fetch()
        const batch = await response.json()
        batch.rows[0].delivery_funnel = { prepared_ever: true, human_approved: true, sent: true, attempt_count: 1, results: { ACCEPTED: 0, DELIVERED: 0, UNKNOWN: 1, FAILED: 0, IN_PROGRESS: 0 }, queued: 0, blocked: 0, cancelled: 0, preflight_failed: 0, unverified_records: 0 }
        batch.rows[1].company_name = null
        batch.rows[1].reasons = [{ code: 'LEAD_REMOVED_OR_MERGED', message: '削除・統合された候補', next_action: '現在の対象を確認する' }]
        await route.fulfill({ response, json: batch })
      } else await route.continue()
    })
    await diagnostic.getByRole('button', { name: '窓口診断を集計', exact: true }).click()
    await expect(diagnostic).toContainText('診断済み 25 / 26件')
    await expect(diagnostic).toContainText('部分集計・未診断分あり')
    const queue = diagnostic.getByRole('region', { name: 'Lead Completion作業キュー' })
    await expect(queue).toContainText('部分集計・未診断分を含みません')
    await expect(queue).toContainText('作業対象 25件 / 診断済み 25件')
    await diagnostic.getByRole('button', { name: '窓口集計を中断', exact: true }).click()
    release()
    await expect(diagnostic).toContainText('診断済み 25 / 26件')
    await diagnostic.getByRole('button', { name: '窓口診断を集計', exact: true }).click()
    await expect(diagnostic).toContainText('診断済み 26 / 26件 — 全件集計済み')
    await expect(diagnostic).toContainText('READY 0 / REVIEW 0 / HOLD 26 / BLOCKED 0')
    await expect(diagnostic).toContainText('公式サイト未登録：25件')
    await expect(diagnostic).toContainText('診断範囲のDM READY：0件 / DM READY率：0.0%')
    const history = diagnostic.getByRole('region', { name: 'Human承認と送信結果のFunnel' })
    await expect(history).toContainText('提案準備済み 0 Lead → Human承認記録 0 Lead → 送信実行 0 Lead')
    await expect(history).toContainText('送信試行 0件')
    await expect(history).toContainText('メール到達証跡あり：0件')
    await expect(history).toContainText('旧経路の履歴を推定して混ぜません')
    await expect(diagnostic.locator('article').filter({ hasText: '診断範囲の共通窓口' })).toContainText('1')
    await expect(diagnostic.locator('article').filter({ hasText: 'READYの独立窓口' })).toContainText('0')
    await expect(queue).toContainText('作業対象 26件 / 診断済み 26件')
    await expect(queue.getByRole('article')).toHaveCount(25)
    await queue.getByRole('button', { name: '次の25件', exact: true }).click()
    await expect(queue.getByRole('article')).toHaveCount(1)
    await queue.getByLabel('作業キューの停止理由').selectOption({ label: '公式サイト未登録（25件）' })
    await expect(queue).toContainText('作業対象 25件 / 診断済み 26件（1 / 1ページ')
    await queue.getByLabel('作業キューの状態').selectOption('DM_READY')
    await expect(queue).toContainText('該当する診断済み候補はありません')
    await queue.getByLabel('作業キューの状態').selectOption('DM_NOT_READY')
    await expect(queue.getByRole('article')).toHaveCount(25)
    await panel.getByLabel('レビュー時間を記録する企業').selectOption({ index: 1 })
    await panel.getByRole('button', { name: 'レビュー時間の記録を開始', exact: true }).click()
    await expect(panel.getByRole('status').filter({ hasText: 'レビュー計測中' })).toContainText('レビュー計測中')
    await page.reload()
    await page.getByRole('button', { name: '⌂ ダッシュボード', exact: true }).click()
    await panel.getByLabel('完成率のプロジェクト').selectOption(fixture.project_id)
    await panel.getByLabel('固定した集計対象').selectOption({ index: 1 })
    await expect(panel.getByRole('status').filter({ hasText: 'レビュー計測中' })).toContainText('レビュー計測中')
    await panel.getByRole('button', { name: 'レビュー記録を終了', exact: true }).click()
    await expect(panel).toContainText('レビュー 1 / 1件終了')
    await expect(panel).toContainText('営業許可・Human承認を変更しません')
    syntheticUnknown = true
    await diagnostic.getByRole('button', { name: '窓口診断を集計', exact: true }).click()
    await expect(queue).toContainText('作業対象 26件 / 診断済み 26件')
    await expect(queue.getByRole('article').nth(1).getByRole('button', { name: '詳細を開く', exact: true })).toBeDisabled()
    await queue.getByLabel('作業キューの状態').selectOption('DELIVERY_REVIEW')
    await expect(queue).toContainText('作業対象 1件 / 診断済み 26件')
    await expect(queue).toContainText('Human確認が必要です。自動再送しません')
    const candidate = queue.getByRole('article').first()
    const companyName = await candidate.locator('strong').innerText()
    await candidate.getByRole('button', { name: '詳細を開く', exact: true }).click()
    await expect(page.getByRole('heading', { name: companyName, exact: true })).toBeVisible()
    expect(forbidden).toEqual([])
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  } finally {
    execFileSync(python, ['../backend/tests/e2e_user.py', 'cleanup'], { env })
  }
})
