import { navigateWorkspace } from './navigation'
import { test, expect } from '@playwright/test'

test('location CSV keeps shared sites and prevents repeat import', async ({ page }, testInfo) => {
  await page.goto('/')
  await page.getByLabel('メールアドレス').fill(process.env.E2E_EMAIL!)
  await page.getByLabel('パスワード', { exact: true }).fill(process.env.E2E_PASSWORD!)
  await page.getByRole('button', { name: 'ログインする', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'プロジェクト', exact: true, level: 1 })).toBeVisible()
  const later = page.getByRole('button', { name: 'あとで見る', exact: true })
  await expect(later).toBeVisible()
  await later.click()
  const profiles = await page.request.get('/api/target-profiles')
  const profileId = (await profiles.json())[0].id
  const result = await page.request.post('/api/projects', { data: {
    project_name: `店舗取り込み ${testInfo.project.name}`, target_profile_id: profileId,
    sales_objective: 'No external access or sending', region: '兵庫県姫路市', status: 'draft',
  } })
  expect(result.status()).toBe(201)
  const projectId = (await result.json()).id
  await page.reload()
  await navigateWorkspace(page, '⌕ 企業収集')
  await page.getByLabel('プロジェクト', { exact: true }).selectOption(projectId)
  await page.getByLabel('収集元', { exact: true }).selectOption('csv')
  await page.getByLabel('取り込み単位', { exact: true }).selectOption('location')
  const content = 'company_name,website_url,phone,email,address,reference_url\n' +
    '店舗北,https://chain.example/north,,,姫路市,\n' +
    '店舗南,https://chain.example/south,,,姫路市,\n' +
    '店舗東,https://beauty.hotpepper.jp/sln1/,,,姫路市,\n' +
    '店舗西,https://beauty.hotpepper.jp/sln2/,,,姫路市,\n'
  await page.getByLabel('CSVファイル（UTF-8・最大5MB・1000行）').setInputFiles({
    name: 'locations.csv', mimeType: 'text/csv', buffer: Buffer.from(content),
  })
  await expect(page.getByText('4行を検出しました。取込先ごとにCSV列を指定してください。')).toBeVisible()
  const submit = async () => {
    expect(await page.locator('form').filter({ has: page.getByRole('button', { name: '収集を開始', exact: true }) }).evaluate(form => Array.from(form.querySelectorAll('input,select,textarea'))
      .filter(element => !(element as HTMLInputElement).validity.valid)
      .map(element => ({ type: (element as HTMLInputElement).type, value: (element as HTMLInputElement).value })))).toEqual([])
    const response = page.waitForResponse(r => r.url().endsWith(`/projects/${projectId}/collection-jobs/csv`) && r.request().method() === 'POST')
    await page.getByRole('button', { name: '収集を開始', exact: true }).click()
    return (await response).json()
  }
  expect((await submit()).saved_count).toBe(4)
  await expect(page.getByRole('button', { name: '収集を開始', exact: true })).toBeEnabled()
  const again = await submit()
  expect(again.saved_count).toBe(0)
  expect(again.duplicate_count).toBe(4)
  await navigateWorkspace(page, '▤ 企業一覧')
  await page.getByRole('combobox', { name: 'プロジェクト', exact: true }).selectOption(projectId)
  const east = page.getByTestId('company-list-item').filter({ has: page.getByText('店舗東', { exact: true }) })
  await expect(east).toBeVisible()
  await east.getByRole('button', { name: '詳細', exact: true }).click()
  await expect(page.getByRole('link', { name: '参考ページを開く', exact: true })).toHaveAttribute('href', 'https://beauty.hotpepper.jp/sln1')
  await expect(page.getByText('店舗単位で登録', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('location-import.png'), fullPage: true })
})
