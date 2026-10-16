import { test, expect } from '@playwright/test'
import { navigateWorkspace } from '../tests/navigation'

for (const role of ['owner', 'viewer'] as const) {
  test(`Collection and sales work stay separate for ${role}`, async ({ page }, info) => {
    const email = 'operator@example.test'
    const profile = { id: 'profile-1', profile_name: 'SNS運用代行', description: 'SNS運用代行会社を集める', search_keywords: ['SNS運用代行', 'Instagram運用代行'], default_regions: ['大阪府'], active: true }
    const projects = [{ id: 'project-1', project_name: '大阪リスト', target_profile_id: profile.id, region: '大阪府', sales_objective: '候補収集', status: 'active' }]
    const calls: { method: string; path: string; body: Record<string, unknown> | null }[] = []
    const errors: string[] = []
    page.on('pageerror', e => errors.push(e.message))
    await page.addInitScript(email => localStorage.setItem(`leadhive:onboarding:${email}`, 'dismissed'), email)
    await page.route('https://geolonia.github.io/japanese-addresses/api/ja.json', route => route.fulfill({ json: { 大阪府: ['大阪市'], 兵庫県: ['神戸市'] } }))
    await page.route('**/api/**', async route => {
      if (new URL(route.request().url()).hostname === 'geolonia.github.io') { await route.fallback(); return }
      const path = new URL(route.request().url()).pathname
      const method = route.request().method()
      const body = method === 'POST' ? route.request().postDataJSON() : null
      calls.push({ method, path, body })
      let data: unknown = []
      if (path === '/api/auth/me') data = { id: 'operator', email, is_admin: false }
      else if (path === '/api/dashboard') data = { total_companies: 1 }
      else if (path === '/api/outreach-execution-status') data = { outbound_enabled: false }
      else if (path.endsWith('/bulk-send-preview')) data = { items: [], skipped: {}, email_enabled: false, form_enabled: false }
      else if (path.endsWith('/send-flow-summary')) data = { readiness_completed_at: null, target_company_count: 1, draft_counts: { email: 0, form: 0 }, form_reviewed_count: 0, approval_counts: { pending: { email: 0, form: 0 }, approved_unsent: { email: 0, form: 0 } }, today: { sent: 0, reserved: 0 }, results: { sent: 0, failed: 0, unknown: 0 } }
      else if (path.endsWith('/outreach-templates')) data = []
      else if (path === '/api/target-profiles') data = [profile]
      else if (path === '/api/projects' && method === 'POST') {
        const created = { ...body, id: 'project-2' } as typeof projects[number]
        projects.push(created); data = created
      } else if (path === '/api/projects') data = projects
      else if (path.endsWith('/members')) data = [{ email, role }]
      else if (path === '/api/form-adapter-preparation-status' || path === '/api/cf7-candidate-preparation-status') data = { enabled: false }
      else if (path.endsWith('/company-list')) data = {
        items: [{ id: 'company-1', project_id: 'project-2', company_name: '確認候補', address: '大阪府', website_url: 'https://candidate.example/', contact_url: 'https://candidate.example/contact', updated_at: '2026-10-12T00:00:00Z', analysis_status: 'pending', ai_status: 'pending' }],
        total: 1,
      }
      else if (path.endsWith('/form-operations')) data = { counts: {}, total: 0, items: [] }
      else if (path === '/api/form-dispatch-limits') data = null
      else if (path.endsWith('/companies')) data = [{ id: 'company-1', company_name: '確認候補', address: '大阪府', website_url: 'https://candidate.example/', contact_url: 'https://candidate.example/contact', updated_at: '2026-10-12T00:00:00Z', analysis_status: 'pending', ai_status: 'pending' }]
      else if (path.endsWith('/collection-feedback')) data = { items: [] }
      else if (path.endsWith('/operations') && method === 'POST') data = { id: 'operation-1', status: 'queued' }
      else if (path.endsWith('/email-deliveries')) data = { items: [], total: 0 }
      await route.fulfill({ json: data })
    })
    await page.goto('/')
    await expect(page.getByRole('heading', { name: '収集ターゲット設定', level: 1 })).toBeVisible()
    const targets = page.getByRole('region', { name: '収集ターゲット設定' })
    await expect(targets).toContainText('SNS運用代行 / Instagram運用代行')
    expect(calls.filter(c => c.method === 'POST')).toEqual([])
    if (role === 'viewer') {
      await expect(targets.getByRole('button', { name: 'このターゲットで収集へ' })).toBeDisabled()
      await expect(page.getByRole('button', { name: '2. 収集開始', exact: true })).toBeDisabled()
    } else {
      await targets.getByRole('button', { name: '新しい収集ターゲットを設定' }).click()
      await page.getByLabel('収集リスト名').fill('兵庫リスト')
      await page.getByLabel('収集する対象').selectOption(profile.id)
      await expect(page.getByLabel('収集の目的')).toHaveValue(profile.description)
      await page.getByRole('combobox', { name: '都道府県', exact: true }).selectOption('兵庫県')
      await page.getByRole('combobox', { name: '市区町村', exact: true }).selectOption('神戸市')
      await expect(page.getByText('兵庫県 / 神戸市', { exact: true })).toBeVisible()
      await page.getByRole('button', { name: '都道府県を複数選択', exact: true }).click()
      await page.getByRole('checkbox', { name: '大阪府', exact: true }).check()
      await page.getByRole('checkbox', { name: '全国', exact: true }).check()
      await expect(page.getByRole('checkbox', { name: '大阪府', exact: true })).not.toBeChecked()
      await page.getByRole('checkbox', { name: '兵庫県', exact: true }).check()
      await page.getByRole('checkbox', { name: '大阪府', exact: true }).check()
      await expect(page.getByRole('checkbox', { name: '全国', exact: true })).not.toBeChecked()
      await page.locator('.region-selector').screenshot({ path: info.outputPath('multiple-prefectures.png') })
      await page.getByRole('button', { name: '保存して収集へ' }).click()
      await expect(page.getByRole('heading', { name: '企業収集', level: 1 })).toBeVisible()
      await expect(page.getByLabel('プロジェクト', { exact: true })).toHaveValue('project-2')
      await expect(page.getByLabel('検索キーワード（1行に1件）')).toHaveValue(profile.search_keywords.join('\n'))
      await expect(page.getByRole('checkbox', { name: '大阪府', exact: true })).toBeChecked()
      await expect(page.getByRole('checkbox', { name: '兵庫県', exact: true })).toBeChecked()
      expect(calls.find(c => c.path === '/api/projects' && c.method === 'POST')?.body?.region).toBe('大阪府 / 兵庫県')
      await page.getByText('検索キーワードと地域の組み合わせを確認', { exact: true }).click()
      await expect(page.getByRole('region', { name: '検索の組み合わせ' })).toContainText('SNS運用代行 大阪府')
      await expect(page.getByRole('region', { name: '検索の組み合わせ' })).toContainText('SNS運用代行 兵庫県')
      await expect(page.getByRole('region', { name: '営業準備', exact: true })).toHaveCount(0)
      expect(calls.filter(c => c.method === 'POST').map(c => c.path)).toEqual(['/api/projects'])
      await page.getByLabel('収集する新規候補数').fill('30')
      await page.getByRole('button', { name: '収集を開始', exact: true }).click()
      await expect(page.getByText('検索収集をバックグラウンド処理へ登録しました。', { exact: true })).toBeVisible()
      expect(calls.find(c => c.path.endsWith('/operations') && c.method === 'POST')?.body).toMatchObject({ operation_type: 'collect_search', target_count: 30, region: '大阪府 / 兵庫県', region_mode: 'prefecture_order', keywords: profile.search_keywords })
    }
    await page.getByRole('button', { name: '4. 結果確認', exact: true }).click()
    const result = page.getByRole('region', { name: '収集リストの確認' })
    await expect(result).toContainText('確認候補')
    if (role === 'owner') await expect(result.getByRole('combobox', { name: '確認する収集リスト', exact: true })).toHaveValue('project-2')
    await result.getByRole('button', { name: '取得結果を確認する' }).click()
    await expect(result.getByRole('combobox', { name: '確認する項目' })).toHaveValue('company')
    await result.getByRole('combobox', { name: '確認する項目' }).selectOption('contact_url')
    await expect(result).toContainText('問い合わせ候補を開く')
    await expect(result.getByRole('button', { name: /Human承認|DM準備/ })).toHaveCount(0)
      await expect(result.getByRole('region', { name: 'クリーニング済みリストの一括送信' })).toHaveCount(0)
    if (role === 'viewer') await expect(result.getByRole('button', { name: 'OKを記録' })).toHaveCount(0)
    await result.screenshot({ path: info.outputPath('collection-results.png') })
    await navigateWorkspace(page, '▶ 送信の準備・実行')
    const sales = page.getByRole('region', { name: '営業作業', exact: true })
    await expect(sales.getByRole('heading', { name: '送信までの流れ' })).toBeVisible()
    if (role === 'owner') {
      await expect(sales.getByRole('combobox', { name: '対象プロジェクト', exact: true })).toHaveValue('project-2')
      await expect(sales.getByRole('heading', { name: '1. 文面テンプレート' })).toBeVisible()
      await expect(sales.getByRole('heading', { name: '2. 送信先と文面を用意' })).toHaveCount(1)
      await expect(sales.getByRole('region', { name: '承認済み内容の一括送信' })).toHaveCount(0)
      await sales.getByRole('heading', { name: '5. 送信' }).click()
      await expect(sales.getByRole('region', { name: '承認済み内容の一括送信' })).toBeVisible()
      await expect(sales.getByRole('button', { name: '0件の送信を開始' })).toBeDisabled()
      await sales.getByRole('heading', { name: '4. 承認' }).click()
      await sales.getByRole('button', { name: '承認キューを別画面で開く' }).click()
      await expect(page.getByLabel('承認プロジェクト')).toHaveValue('project-2').catch(e => { throw new Error(errors.join('; ') || String(e)) })
    } else await expect(sales.getByText('閲覧のみです。営業準備の実行は所有者・編集者へ依頼してください。')).toBeVisible()
    expect(calls.filter(c => c.method === 'POST' && !['/api/projects', '/api/projects/project-2/operations'].includes(c.path))).toEqual([])
    expect(errors).toEqual([])
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width)
  })
}
