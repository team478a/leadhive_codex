import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { test, expect } from '@playwright/test'

test('Human preparation choice persists, can be revoked and invalidates on destination change', async ({ page }) => {
  const python = process.env.PYTHON || (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  const env = { ...process.env, E2E_EMAIL: `e2e-completion-${randomBytes(8).toString('hex')}@example.com`, E2E_PASSWORD: randomBytes(24).toString('hex') }
  execFileSync(python, ['../backend/tests/e2e_user.py', 'create'], { env })
  const forbidden: string[] = []
  page.on('request', request => {
    if (!['localhost', '127.0.0.1'].includes(new URL(request.url()).hostname) || /\/(?:send|dispatch|execute|test-send|approve)(?:[/?]|$)/.test(request.url())) forbidden.push(request.url())
  })
  try {
    const fixture = JSON.parse(execFileSync(python, ['../backend/tests/e2e_user.py', 'destination-selection-fixture'], { env, encoding: 'utf8' })) as { project_id: string }
    await page.goto('/')
    await page.getByLabel('メールアドレス').fill(env.E2E_EMAIL)
    await page.getByLabel('パスワード').fill(env.E2E_PASSWORD)
    await page.getByRole('button', { name: 'ログインする', exact: true }).click()
    await page.getByRole('dialog', { name: '3ステップで始めましょう' }).getByRole('button', { name: 'あとで見る' }).click()
    await page.getByRole('button', { name: '▤ 企業一覧', exact: true }).click()
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(fixture.project_id)
    await page.getByRole('button', { name: '詳細', exact: true }).first().click()
    const panel = page.getByRole('region', { name: 'リスト完成の根拠' })
    await panel.getByRole('button', { name: 'プロジェクトの窓口候補を整理', exact: true }).click()
    const assessment = panel.getByRole('region', { name: '窓口の利用可否と理由' })
    await expect(assessment).toContainText('DESTINATION_PURPOSE_UNCERTAIN')
    await assessment.locator('summary').click()
    await assessment.getByRole('combobox', { name: '窓口用途', exact: true }).selectOption('business')
    await assessment.getByRole('combobox', { name: '窓口の対象範囲', exact: true }).selectOption('company')
    await assessment.getByLabel('用途の根拠URL', { exact: true }).fill('https://approval.example/contact')
    await assessment.getByLabel('公開ページの用途説明', { exact: true }).fill('事業提携などのご相談はこちらで受け付けます。')
    await assessment.getByRole('button', { name: '用途確認を記録', exact: true }).click()
    await expect(assessment).toContainText('判定：準備候補（READY）')
    const choice = assessment.getByRole('region', { name: '営業準備に使う窓口の選択' })
    await choice.getByRole('button', { name: /この窓口を準備対象に選択/ }).click()
    await expect(choice).toContainText('有効（CURRENT） / 記録版 1')
    await choice.getByRole('button', { name: '窓口の選択を取り消す', exact: true }).click()
    await expect(choice).toContainText('取り消し済み（REVOKED） / 記録版 2')
    await choice.getByRole('button', { name: /この窓口を準備対象に選択/ }).click()
    await expect(choice).toContainText('有効（CURRENT） / 記録版 3')
    await page.reload()
    await page.getByRole('button', { name: '▤ 企業一覧', exact: true }).click()
    await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(fixture.project_id)
    await page.getByRole('button', { name: '詳細', exact: true }).first().click()
    await expect(choice).toContainText('有効（CURRENT） / 記録版 3')
    await page.getByLabel('メール', { exact: true }).fill('changed-destination@example.com')
    await page.getByRole('button', { name: '企業情報を保存', exact: true }).click()
    await expect(choice).toContainText('情報変更により無効（STALE） / 記録版 3')
    await expect(choice).not.toContainText('現在の準備対象：')
    await expect(choice.getByRole('button', { name: /この窓口を準備対象に選択/ })).toHaveCount(0)
    await expect(panel.getByRole('button', { name: /送信|承認/ })).toHaveCount(0)
    expect(forbidden).toEqual([])
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  } finally {
    execFileSync(python, ['../backend/tests/e2e_user.py', 'cleanup'], { env })
  }
})
