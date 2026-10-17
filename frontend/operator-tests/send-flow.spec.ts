import { expect, test, type Page } from '@playwright/test'
import { navigateWorkspace } from '../tests/navigation'

type Proposal = {
  id: string; project_id: string; company_id: string; company_name: string; channel: 'email' | 'form'
  delivery_method: string; recipient: string | null; form_url: string | null; subject: string; body: string
  sender: { name: string; email: string }; field_values: Record<string, string>
  payload_hash: string; payload_version: number; status: string; created_at: string; expires_at: string
  created_by_principal_type: 'HUMAN'; rejection_reason: string | null; invalidation_reason: string | null
}

const proposal = (status = 'PENDING'): Proposal => ({
  id: 'proposal-email-1', project_id: 'project-1', company_id: 'company-1', company_name: '確認候補株式会社',
  channel: 'email', delivery_method: 'email', recipient: 'contact@example.test', form_url: null,
  subject: 'ご案内', body: 'ご不要の場合はこのメールにご返信ください。',
  sender: { name: '送信者', email: 'sender@example.test' }, field_values: {},
  payload_hash: 'payload-hash-1', payload_version: 1, status,
  created_at: '2026-10-17T00:00:00Z', expires_at: '2026-10-18T00:00:00Z',
  created_by_principal_type: 'HUMAN', rejection_reason: null, invalidation_reason: null,
})

const formProposal: Proposal = {
  ...proposal('APPROVED'), id: 'proposal-form-1', company_name: 'フォーム確認候補株式会社', channel: 'form',
  delivery_method: 'form_direct', recipient: null, form_url: 'https://example.test/contact',
}

async function setup(page: Page, options: { channel?: 'email' | 'form'; pending?: boolean; approvedForm?: boolean; templates?: boolean; failFirstReservation?: boolean } = {}) {
  const email = 'send-flow@example.test'
  const projectIds = ['project-1', 'project-2']
  const calls: { path: string; method: string; body: Record<string, unknown> | null }[] = []
  const reservations: Record<string, unknown>[] = []
  let savedTemplate: Record<string, unknown> | null = null
  let bulkDraftBody: Record<string, unknown> | null = null
  let currentProposal = options.pending ? proposal() : null
  let approvedProposal: Proposal | null = null
  const approvedFormProposal = options.approvedForm ? formProposal : null
  let reservationAttempts = 0
  const templates = options.templates ? [
    { id: 'email-template', project_id: 'project-1', name: 'メール用', channel: 'email', subject: '件名', body: '本文' },
    { id: 'form-template', project_id: 'project-1', name: 'フォーム用', channel: 'form', subject: '', body: 'フォーム本文' },
  ] : []
  const pageErrors: string[] = []
  page.on('pageerror', error => pageErrors.push(error.message))
  await page.addInitScript(({ userEmail, channel }) => {
    localStorage.setItem(`leadhive:onboarding:${userEmail}`, 'dismissed')
    if (channel) localStorage.setItem('leadhive:send-channel:project-1', channel)
  }, { userEmail: email, channel: options.channel })
  await page.route('**/api/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()
    const body = method === 'POST' || method === 'PUT' ? request.postDataJSON() as Record<string, unknown> : null
    calls.push({ path, method, body })
    let data: unknown = []
    let status = 200
    const summary = (projectId: string) => ({
      readiness_completed_at: '2026-10-16T00:00:00Z', target_company_count: 1,
      draft_counts: { email: bulkDraftBody ? 1 : options.pending ? 1 : 0, form: options.approvedForm ? 1 : 0 }, form_reviewed_count: options.approvedForm ? 1 : 0,
      approval_counts: { pending: { email: currentProposal?.status === 'PENDING' ? 1 : 0, form: 0 }, approved_unsent: { email: approvedProposal ? 1 : 0, form: approvedFormProposal ? 1 : 0 } },
      today: { sent: 0, reserved: 0 }, results: { sent: 0, failed: 0, unknown: 0 }, project_id: projectId,
    })
    if (path === '/api/auth/me') data = { id: 'send-flow-user', email, is_admin: true }
    else if (path === '/api/dashboard') data = { total_companies: 1, ranks: {}, statuses: {}, recent_jobs: [], operation_statuses: {}, unread_operation_failures: 0, recent_operations: [], overdue_followups: 0, due_today_followups: 0 }
    else if (path === '/api/outreach-execution-status') data = { outbound_enabled: false }
    else if (path === '/api/target-profiles') data = [{ id: 'profile-1', profile_name: '見本', search_keywords: [], default_regions: [], active: true }]
    else if (path === '/api/projects') data = projectIds.map((id, index) => ({ id, project_name: `送信テスト${index + 1}`, target_profile_id: 'profile-1', region: '全国', sales_objective: '確認', status: 'active' }))
    else if (projectIds.some(id => path === `/api/projects/${id}/members`)) data = [{ id: 'membership', email, role: 'owner' }]
    else if (projectIds.some(id => path === `/api/projects/${id}/send-flow-summary`)) data = summary(path.split('/')[3])
    else if (projectIds.some(id => path === `/api/projects/${id}/outreach-templates`) && method === 'GET') data = savedTemplate ? [...templates, savedTemplate] : templates
    else if (projectIds.some(id => path === `/api/projects/${id}/outreach-templates`) && method === 'POST') {
      savedTemplate = { ...body, id: 'new-template', project_id: path.split('/')[3], created_by_user_id: 'send-flow-user', created_at: '2026-10-17T00:00:00Z', updated_at: '2026-10-17T00:00:00Z' }
      data = savedTemplate
    } else if (path.endsWith('/company-list')) data = { items: [{ id: 'company-1', project_id: path.split('/')[3], company_name: '確認候補株式会社', domain: 'example.test', email: 'contact@example.test', do_not_contact: false }], total: 1, offset: 0, limit: 20 }
    else if (path.endsWith('/form-dm-readiness')) data = { counts: { NO_FORM_DRAFT: 1, READY: 1 }, total: 1, offset: 0, limit: 20, items: [], last_aggregated_at: '2026-10-16T00:00:00Z', active_job: null, read_only: true, external_requests: 0 }
    else if (path.endsWith('/form-review-queue')) data = { total: 0, offset: 0, limit: 20, items: [], read_only: true, external_requests: 0 }
    else if (path.endsWith('/outreach-drafts/bulk-from-template') && method === 'POST') {
      bulkDraftBody = body
      data = { id: 'draft-job', project_id: 'project-1', operation_type: 'bulk_template_drafts', status: 'completed', total_count: 1, processed_count: 1, success_count: 1, failed_count: 0, cancel_requested: false, attempt_count: 1, acknowledged_at: null, error_message: '', created_at: '2026-10-17T00:00:00Z', started_at: '2026-10-17T00:00:00Z', finished_at: '2026-10-17T00:00:01Z', bulk_template_results: { created: ['company-1'], skipped_existing: [], excluded: [] } }
    } else if (path.endsWith('/approval-email-drafts')) data = []
    else if (path.endsWith('/approval-requests') && method === 'GET') data = currentProposal ? [currentProposal] : []
    else if (path.endsWith('/bulk-send-preview')) data = { items: [...(approvedProposal ? [approvedProposal] : []), ...(approvedFormProposal ? [approvedFormProposal] : [])], skipped: {}, email_enabled: true, form_enabled: true }
    else if (path.endsWith('/form-approval-daily-summary')) data = { daily_limit: 100, started_last_24h: 0, approved_unsent: 0, pending_approvals: 0, remaining_quota: 100, paused: false, within_send_window: true }
    else if (path === '/api/admin/sending-window') data = { enabled: true, start_minute: 0, end_minute: 1439, timezone: 'Asia/Tokyo' }
    else if (path.endsWith('/email-deliveries')) data = { items: [], queued_count: 0, running_count: 0, sent_count: 0, failed_count: 0, unknown_count: 0 }
    else if (path.endsWith('/form-operations')) data = { items: [], total: 0, counts: {} }
    else if (path.endsWith('/operations') && method === 'GET') data = []
    else if (path.endsWith('/bulk-approval/challenge')) data = { challenge_token: 'challenge-token' }
    else if (path.endsWith('/bulk-approval/verify')) data = { verified: true }
    else if (path.endsWith('/bulk-approval/approve')) { approvedProposal = currentProposal ? { ...currentProposal, status: 'APPROVED' } : null; currentProposal = null; data = { approved: 1 } }
    else if (path.endsWith('/approved-email-batches') && method === 'POST') {
      reservations.push(body ?? {}); reservationAttempts += 1
      if (options.failFirstReservation && reservationAttempts === 1) { status = 503; data = { detail: '予約APIが一時失敗' } }
      else data = { id: 'batch-1', status: 'queued' }
    } else if (path.endsWith('/approved-form-dispatches') && method === 'POST') {
      reservations.push(body ?? {})
      const items = (body?.items ?? []) as { request_id: string }[]
      data = { results: items.map(item => ({ request_id: item.request_id, reservation: { id: `reservation-${item.request_id}` }, error: null })) }
    } else if (path === '/api/approval-audit') data = []
    else if (path.endsWith('/form-adapter-preparation-status')) data = { enabled: false }
    else if (path.endsWith('/cf7-candidate-preparation-status')) data = { enabled: true }
    else if (path.endsWith('/form-approval-readiness')) data = { items: [], total: 0, counts: {} }
    else if (path.endsWith('/companies')) data = []
    else if (path === '/api/admin/application-settings') data = { public_app_url: '', openai_model: '', gbizinfo_api_base_url: '', settings_encryption_ready: true, openai_api_key_source: 'unset', serper_api_key_source: 'unset', google_places_api_key_source: 'unset', gbizinfo_api_token_source: 'unset' }
    else if (path === '/api/admin/smtp-settings') data = null
    else if (path === '/api/admin/form-sender-settings') data = { company_name: '', department: '', position: '', contact_name: '', last_name: '', first_name: '', furigana: '', email: '', phone: '', postal_code: '', prefecture: '', city: '', address: '', building: '', website: '', updated_at: null }
    else if (path === '/api/admin/inbound-mail-settings') data = null
    else if (path === '/api/admin/inbound-emails') data = []
    else if (path === '/api/form-dispatch-limits') data = { daily_limit: 100, hourly_limit: 10, minimum_interval_seconds: 60, site_interval_seconds: 300, paused: false, version: 1, can_manage: true, execution_enabled: false }
    else if (method === 'POST' || method === 'PUT') data = { id: 'mock', status: 'completed' }
    await route.fulfill({ status, json: data })
  })
  await page.goto('/')
  await navigateWorkspace(page, '▶ 送信の準備・実行')
  return { calls, reservations, pageErrors }
}

test('channel is isolated and remembered separately for each project', async ({ page }) => {
  await setup(page, { channel: 'form', templates: true })
  const sales = page.getByRole('region', { name: '営業作業', exact: true })
  await expect(sales.getByRole('heading', { name: '送信の準備・実行' })).toBeVisible()
  await expect(sales.getByRole('button', { name: 'フォーム', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(sales.locator('[aria-label="2. フォームを確認"]')).toHaveCount(1)
  await expect(sales.getByRole('region', { name: '承認して送る', exact: true })).toHaveCount(0)
  await expect(sales.getByText('メール承認待ちの作成')).toHaveCount(0)
  await expect(sales.getByText('フォームの送信可否集計・詳細')).toHaveCount(1)
  const templateSelect = sales.getByLabel('使用するテンプレート')
  await expect(templateSelect.locator('option')).toHaveText(['選択してください', 'フォーム用'])

  await sales.getByRole('button', { name: 'メール', exact: true }).click()
  await expect(sales.locator('[aria-label="2. フォームを確認"]')).toHaveCount(0)
  await expect(sales.locator('[aria-label="1. 文面をつくる"]')).toHaveCount(1)
  await expect(sales.locator('[aria-label="2. 承認して送る"]')).toHaveCount(1)
  await expect(sales.locator('[aria-label="3. 結果"]')).toHaveCount(1)

  await sales.getByLabel('対象プロジェクト').selectOption('project-2')
  await expect(sales.getByRole('button', { name: 'メール', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await sales.getByRole('button', { name: 'フォーム', exact: true }).click()
  await sales.getByLabel('対象プロジェクト').selectOption('project-1')
  await expect(sales.getByRole('button', { name: 'メール', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await sales.getByLabel('対象プロジェクト').selectOption('project-2')
  await expect(sales.getByRole('button', { name: 'フォーム', exact: true })).toHaveAttribute('aria-pressed', 'true')

  await sales.locator('[aria-label="1. 文面をつくる"] > div > button').first().click()
  await expect(sales.locator('[id^="send-flow-step-"]')).toHaveCount(4)
  const bounds = await sales.locator('[id^="send-flow-step-"]').evaluateAll(elements => elements.map(element => {
    const rect = element.getBoundingClientRect()
    return { top: rect.top, bottom: rect.bottom }
  }))
  expect(bounds[bounds.length - 1].bottom - bounds[0].top, JSON.stringify(bounds)).toBeLessThanOrEqual(page.viewportSize()!.height)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width)
})

test('email template and bulk draft creation use the server-selected eligible set', async ({ page }) => {
  const { calls } = await setup(page)
  const sales = page.getByRole('region', { name: '営業作業', exact: true })
  await sales.locator('summary', { hasText: 'テンプレートを新しく作る・編集する' }).click()
  const editor = sales.getByRole('region', { name: '文面テンプレート' })
  await editor.getByLabel('テンプレート名').fill('初回案内')
  await editor.getByLabel('件名').fill('ご案内')
  await editor.getByLabel('本文').fill('ご不要の場合はこのメールにご返信ください。')
  await editor.getByRole('button', { name: 'テンプレートを保存' }).click()
  await expect(editor.getByRole('status')).toContainText('テンプレートを保存しました')
  const draftPanel = sales.getByRole('region', { name: '送信先と文面の準備' })
  await draftPanel.getByRole('button', { name: '条件に合う会社をすべて選択（最大500社）' }).click()
  await draftPanel.getByRole('button', { name: '条件一致企業に下書きを作成（最大500社）' }).click()
  await expect(draftPanel.getByRole('status', { name: '一括作成の進捗' })).toContainText('作成 1社 · 既存のためスキップ 0社 · 対象外 0社')
  await draftPanel.getByRole('button', { name: '次へ：承認して送る' }).click()
  await expect(sales.locator('[aria-label="2. 承認して送る"] button').first()).toHaveAttribute('aria-expanded', 'true')
  const request = calls.find(call => call.path.endsWith('/outreach-drafts/bulk-from-template'))
  expect(request?.body).toMatchObject({ template_id: 'new-template', channel: 'email', readiness_reason: 'NO_EMAIL_DRAFT' })
  expect(request?.body).not.toHaveProperty('company_ids')
})

test('one action approves and reserves; reservation retry reuses its original idempotency key', async ({ page }) => {
  const { calls, reservations, pageErrors } = await setup(page, { pending: true, failFirstReservation: true })
  const sales = page.getByRole('region', { name: '営業作業', exact: true })
  const approval = sales.getByRole('region', { name: '承認して送る' })
  await expect(approval.getByRole('heading', { name: /承認待ち 1件/ })).toBeVisible()
  await approval.locator('details').filter({ hasText: '確認候補株式会社' }).first().locator('summary').click()
  await approval.getByLabel('承認・予約対象にする').check()
  await expect(approval.getByRole('region', { name: '承認前の抜き取り確認' })).toContainText('ご不要の場合はこのメールにご返信ください。')
  await approval.getByLabel('ログインパスワード（再認証）').fill('user-password')
  await approval.getByRole('button', { name: '選択した1件を承認して送信予約' }).click()
  await expect(approval.getByRole('alert')).toContainText('予約APIが一時失敗')
  await expect(approval.getByRole('button', { name: '予約だけやり直す（同じ予約キー）' })).toBeVisible()
  await approval.getByRole('button', { name: '予約だけやり直す（同じ予約キー）' }).click()
  await expect(approval.getByRole('status')).toContainText('1件を同じ予約キーで予約しました')
  expect(calls.filter(call => call.path.endsWith('/bulk-approval/challenge')).length).toBe(1)
  expect(calls.filter(call => call.path.endsWith('/bulk-approval/approve')).length).toBe(1)
  expect(reservations).toHaveLength(2)
  expect(reservations[0].idempotency_key).toBe(reservations[1].idempotency_key)
  expect(reservations[0].items).toEqual([{ request_id: 'proposal-email-1', expected_hash: 'payload-hash-1', expected_version: 1 }])
  expect(pageErrors).toEqual([])
})

test('form selection reserves only form proposals through the existing form API', async ({ page }) => {
  const { reservations, pageErrors } = await setup(page, { channel: 'form', approvedForm: true })
  const sales = page.getByRole('region', { name: '営業作業', exact: true })
  const approvalStep = sales.locator('[aria-label="3. 承認して送る"]')
  const header = approvalStep.getByRole('button').first()
  await expect(header).toContainText('承認済み未予約 1件')
  await expect(header).toHaveAttribute('aria-expanded', 'true')
  const approval = approvalStep.getByRole('region', { name: '承認して送る', exact: true })
  await expect(approval.getByText('フォーム承認待ちの作成')).toBeVisible()
  await expect(approval.getByText('メール承認待ちの作成')).toHaveCount(0)
  await approval.getByRole('button', { name: '表示中の対象を選択' }).click()
  await expect(approval.getByRole('region', { name: '承認前の抜き取り確認' })).toContainText('フォーム確認候補株式会社')
  await approval.getByRole('button', { name: '承認済み1件を送信予約' }).click()
  await expect(approval.getByRole('status')).toContainText('1件を承認・予約しました')
  expect(reservations).toHaveLength(1)
  expect(reservations[0].items).toEqual([{ request_id: 'proposal-form-1', expected_hash: 'payload-hash-1', expected_version: 1 }])
  expect(pageErrors).toEqual([])
})

test('advanced approval and verification panels remain on their dedicated pages', async ({ page }) => {
  await setup(page)
  const sales = page.getByRole('region', { name: '営業作業', exact: true })
  const approvalStep = sales.locator('[aria-label="2. 承認して送る"]')
  await approvalStep.getByRole('button').first().click()
  await approvalStep.getByRole('button', { name: '高度な承認・検証を開く' }).click()
  await expect(page.getByRole('heading', { name: '承認キュー', level: 1 })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Human Approval Queue' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'フォームDraftから承認候補を準備' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'CF7候補を準備（送信不可）' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'フォーム運用確認' })).toBeVisible()
})

test('environment-wide form dispatch limits are available in Settings', async ({ page }) => {
  await setup(page)
  const sales = page.getByRole('region', { name: '営業作業', exact: true })
  const approvalStep = sales.locator('[aria-label="2. 承認して送る"]')
  await approvalStep.getByRole('button').first().click()
  await approvalStep.getByRole('button', { name: '運用設定で確認・変更' }).click()
  await expect(page.getByRole('heading', { name: '運用設定', level: 1 })).toBeVisible()
  await expect(page.getByRole('region', { name: 'フォーム送信上限' })).toBeVisible()
})
