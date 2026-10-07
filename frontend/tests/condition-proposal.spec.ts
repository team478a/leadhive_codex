import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { test, expect } from '@playwright/test'

test('Text proposal needs human confirmation and applies the confirmed search fields', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const env = { ...process.env, E2E_EMAIL: `e2e-proposal-${randomBytes(8).toString('hex')}@example.com`, E2E_PASSWORD: randomBytes(24).toString('hex') }
  execFileSync(python, ['../backend/tests/e2e_user.py', 'create'], { env })
  const forbidden: string[] = []
  const starts: string[] = []
  page.on('request', r => {
    if (!['localhost', '127.0.0.1'].includes(new URL(r.url()).hostname) || /\/(send|dispatch|execute|approve|test-send)([/?]|$)/.test(r.url()) && r.method() === 'POST') forbidden.push(r.url())
    if (/\/operations$/.test(r.url()) && r.method() === 'POST') starts.push(r.url())
  })
  try {
    const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'destination-selection-fixture'], { env, encoding: 'utf8' })) as { project_id: string }
    await page.goto('/')
    await page.getByLabel('メールアドレス').fill(env.E2E_EMAIL)
    await page.getByLabel('パスワード').fill(env.E2E_PASSWORD)
    await page.getByRole('button', { name: 'ログインする', exact: true }).click()
    await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
    await page.getByRole('button', { name: '⌕ 企業収集', exact: true }).click()
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(fixture.project_id)
    await page.getByText('対象条件を確認・分類する', { exact: true }).click()
    await page.getByLabel('探したい対象').fill('姫路市の美容院でInstagramあり\n現在募集中')
    await expect(page.getByRole('button', { name: '条件を確認して確定', exact: true })).toBeDisabled()
    await page.getByRole('button', { name: '文章から条件案を作る' }).click()
    await expect(page.getByLabel('条件4の種類')).toHaveValue('UNRESOLVED')
    await expect(page.getByRole('button', { name: '条件を確認して確定', exact: true })).toBeDisabled()
    expect(starts).toEqual([])
    await page.getByLabel('探したい対象').fill('姫路市の美容院でInstagramあり\n希望:公式サイトあり')
    await page.getByRole('button', { name: '文章から条件案を作る' }).click()
    await expect(page.getByLabel('条件4の種類')).toHaveValue('OFFICIAL_SITE')
    await page.getByRole('button', { name: '条件を確認して確定', exact: true }).click()
    await expect(page.getByRole('checkbox', { name: /確定条件を今回の収集に使う/ })).toBeChecked()
    await expect(page.getByLabel('地域', { exact: true })).toHaveValue('姫路市')
    await expect(page.getByLabel('検索キーワード（1行に1件）')).toHaveValue('美容院')
    await expect(page.getByLabel('キーワードごとの最大件数')).toHaveValue('20')
    expect(starts).toEqual([])
    await page.getByLabel('条件1の内容').fill('神戸市')
    await page.getByRole('button', { name: '収集を開始', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('対象条件の変更を確定するか')
    expect(starts).toEqual([])
    await page.getByRole('button', { name: '未確定の変更を取り消す' }).click()
    const responsePromise = page.waitForResponse(r => r.url().endsWith(`/projects/${fixture.project_id}/operations`) && r.request().method() === 'POST')
    await page.getByRole('button', { name: '収集を開始', exact: true }).click()
    const response = await responsePromise
    expect(response.status()).toBe(202)
    const payload = response.request().postDataJSON() as { keywords: string[]; region: string; condition_version: number }
    expect(payload.keywords).toEqual(['美容院']); expect(payload.region).toBe('姫路市'); expect(payload.condition_version).toBe(1)
    await page.getByRole('button', { name: 'キャンセル', exact: true }).click()
    expect(forbidden).toEqual([])
  } finally {
    execFileSync(python, ['../backend/tests/e2e_user.py', 'cleanup'], { env })
  }
})


test('Purpose sentence preserves mandatory recruiting and target count without searches', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const env = { ...process.env, E2E_EMAIL: `e2e-proposal-${randomBytes(8).toString('hex')}@example.com`, E2E_PASSWORD: randomBytes(24).toString('hex') }
  execFileSync(python, ['../backend/tests/e2e_user.py', 'create'], { env })
  const forbidden: string[] = []
  const starts: string[] = []
  page.on('request', r => {
    if (!['localhost', '127.0.0.1'].includes(new URL(r.url()).hostname) || /\/(send|dispatch|execute|approve|test-send)([/?]|$)/.test(r.url()) && r.method() === 'POST') forbidden.push(r.url())
    if (/\/operations$/.test(r.url()) && r.method() === 'POST') starts.push(r.url())
  })
  try {
    const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'destination-selection-fixture'], { env, encoding: 'utf8' })) as { project_id: string }
    await page.goto('/')
    await page.getByLabel('メールアドレス').fill(env.E2E_EMAIL)
    await page.getByLabel('パスワード').fill(env.E2E_PASSWORD)
    await page.getByRole('button', { name: 'ログインする', exact: true }).click()
    await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
    await page.getByRole('button', { name: '⌕ 企業収集', exact: true }).click()
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(fixture.project_id)
    await page.getByText('対象条件を確認・分類する', { exact: true }).click()
    await page.getByLabel('探したい対象').fill('兵庫県姫路市の美容院で、HotPepper Beautyに掲載していて、現在求人募集中の店舗を100件探す。できればInstagramと公式サイトがある店舗。')
    await page.getByRole('button', { name: '文章から条件案を作る' }).click()
    await expect(page.getByLabel('条件3の媒体')).toHaveValue('HOTPEPPER_BEAUTY')
    await expect(page.getByLabel('条件4の種類')).toHaveValue('ACTIVE_JOB')
    await expect(page.getByLabel('条件5の優先度')).toHaveValue('WANT')
    await expect(page.getByLabel('条件6の優先度')).toHaveValue('WANT')
    const count = page.getByLabel('目標件数（条件一致の達成保証なし）')
    await expect(count).toHaveValue('100')
    await expect(page.getByText('現在求人募集中の検証は未対応です。求人URLの存在だけでは条件一致にしません。', { exact: true })).toBeVisible()
    expect(starts).toEqual([])
    await count.fill('0')
    await expect(page.getByRole('button', { name: '条件を確認して確定', exact: true })).toBeDisabled()
    await count.fill('20')
    const responsePromise = page.waitForResponse(r => r.url().endsWith(`/projects/${fixture.project_id}/collection-conditions`) && r.request().method() === 'POST')
    await page.getByRole('button', { name: '条件を確認して確定', exact: true }).click()
    const response = await responsePromise
    const confirmed = await response.json() as { snapshot: { requested_count: number; requested_count_explicit: boolean } }
    expect(confirmed.snapshot.requested_count).toBe(20)
    expect(confirmed.snapshot.requested_count_explicit).toBe(true)
    await expect(page.getByRole('region', { name: '条件判定結果' })).toContainText('目標 20件（達成保証なし）')
    await expect(page.getByLabel('キーワードごとの最大件数')).toHaveValue('20')
    await page.reload()
    await page.getByRole('button', { name: '⌕ 企業収集', exact: true }).click()
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(fixture.project_id)
    await page.getByText('対象条件を確認・分類する', { exact: true }).click()
    await expect(count).toHaveValue('20')
    expect(starts).toEqual([])
    expect(forbidden).toEqual([])
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  } finally {
    execFileSync(python, ['../backend/tests/e2e_user.py', 'cleanup'], { env })
  }
})
