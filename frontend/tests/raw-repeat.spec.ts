import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { test, expect } from '@playwright/test'

test('Repeat observations and Human pair labels remain separate from collection truth', async ({ page }) => {
  test.setTimeout(120_000)
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const env = { ...process.env, E2E_EMAIL: `e2e-repeat-${randomBytes(8).toString('hex')}@example.com`, E2E_PASSWORD: randomBytes(24).toString('hex') }
  execFileSync(python, ['../backend/tests/e2e_user.py', 'create'], { env })
  const forbidden: string[] = []
  page.on('request', r => { if (!['localhost', '127.0.0.1'].includes(new URL(r.url()).hostname) || /\/(send|dispatch|execute|approve|test-send|search|queries)([/?]|$)/.test(r.url())) forbidden.push(r.url()) })
  try {
    await page.goto('/')
    await page.getByLabel('メールアドレス').fill(env.E2E_EMAIL)
    await page.getByLabel('パスワード').fill(env.E2E_PASSWORD)
    await page.getByRole('button', { name: 'ログインする', exact: true }).click()
    await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
    await page.getByRole('button', { name: '◎ 一次収集Benchmark', exact: true }).click()
    const raw = page.getByRole('region', { name: 'Raw Collection Benchmark', exact: true })
    await raw.getByLabel('Benchmark地域', { exact: true }).fill('兵庫県姫路市')
    await raw.getByLabel('Benchmark業種', { exact: true }).fill('美容院')
    await raw.getByRole('button', { name: '空のRaw Benchmarkを作成', exact: true }).click()
    await expect(raw.getByRole('region', { name: 'Raw Collection集計', exact: true })).toContainText('Found 0 / Reviewed 0 / Correct 0')
    const benchmark = await raw.getByLabel('Raw Benchmark', { exact: true }).inputValue()
    const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_raw_benchmark.py', benchmark, 'repeat'], { env, encoding: 'utf8' })) as { snapshot_ids: string[] }
    await raw.getByRole('button', { name: 'Raw結果を再読込', exact: true }).click()
    const metrics = raw.getByRole('region', { name: 'Raw Collection集計', exact: true })
    const stability = raw.getByRole('region', { name: 'Raw Run Stability', exact: true })
    await expect(metrics).toContainText('Found 6 / Reviewed 0 / Correct 0')
    await expect(stability).toContainText('Raw観測のUnique Candidate 4')
    await expect(stability).toContainText('Union 4 / Intersection 1 / Intersection Rate 25.0% / Repeat Discovery Rate 25.0% / Single-run Rate 75.0%')
    await expect(stability).toContainText('Human Entityの安定性未測定 / null')
    await raw.getByLabel('未レビューRaw観測の代表候補だけを表示（店舗Identityの確定ではありません）', { exact: true }).check()
    await expect(raw.locator('details[aria-label^="Raw候補 "]')).toHaveCount(4)
    const pair = raw.getByRole('region', { name: 'Raw Entity Pair Review', exact: true })
    for (const [index, outcome] of ['SAME', 'DIFFERENT', 'UNSURE'].entries()) {
      await pair.getByLabel('Pair候補1', { exact: true }).selectOption(fixture.snapshot_ids[0])
      await pair.getByLabel('Pair候補2', { exact: true }).selectOption(fixture.snapshot_ids[2])
      await pair.getByRole('button', { name: 'Pair特徴を比較', exact: true }).click()
      await expect(pair).toContainText(`Pair版 ${index}`)
      await expect(pair).toContainText('"phone_equal": null')
      await pair.getByRole('button', { name: 'Human Pairレビューを開始', exact: true }).click()
      await pair.getByLabel('Pair判定', { exact: true }).selectOption(outcome)
      await pair.getByLabel('Pair判定理由', { exact: true }).fill('Synthetic browser label, never operational truth')
      await pair.getByLabel('Pair根拠URL', { exact: true }).fill('https://evidence.example/page')
      await expect(pair.getByRole('button', { name: 'Pair判定を記録', exact: true })).toBeDisabled()
      await pair.getByLabel('この2候補を自分で比較しました', { exact: true }).check()
      await pair.getByRole('button', { name: 'Pair判定を記録', exact: true }).click()
      await expect(stability).toContainText(`Human Pair Label: SAME ${outcome === 'SAME' ? 1 : 0} / DIFFERENT ${outcome === 'DIFFERENT' ? 1 : 0} / UNSURE ${outcome === 'UNSURE' ? 1 : 0}`)
      await expect(metrics).toContainText('Found 6 / Reviewed 0 / Correct 0')
      await expect(metrics).toContainText('Strict Precision 未測定 / null')
    }
    await page.reload()
    await page.getByRole('button', { name: '◎ 一次収集Benchmark', exact: true }).click()
    await raw.getByLabel('Raw Benchmark', { exact: true }).selectOption(benchmark)
    await expect(stability).toContainText('UNSURE 1')
    expect(forbidden).toEqual([])
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  } finally { execFileSync(python, ['../backend/tests/e2e_user.py', 'cleanup'], { env }) }
})
