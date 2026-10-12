import { test, expect, type Page } from '@playwright/test'
import { navigateWorkspace } from '../tests/navigation'

async function setup(page: Page, options: { viewer?: boolean; stopped?: boolean; partial?: boolean; large?: boolean; disconnected?: boolean } = {}) {
  const email = 'bulk@example.test'
  const proposals = Array.from({ length: options.large ? 201 : 2 }, (_, n) => ({
    id: `approval-${n}`, company_id: `company-${n}`, company_name: `企業${n}`,
    channel: n === 0 ? 'email' : 'form', delivery_method: n === 0 ? 'email' : 'form_direct',
    recipient: n === 0 ? 'receiver@example.test' : null, form_url: 'https://example.test/contact',
    subject: '承認済み件名', body: '人が確認した文面', payload_hash: `hash-${n}`, payload_version: 1,
  }))
  const requests: { path: string; body: { idempotency_key: string; items: { request_id: string; expected_hash: string }[] } }[] = []
  let reserved = false; let formAttempt = 0
  await page.addInitScript(email => localStorage.setItem(`leadhive:onboarding:${email}`, 'dismissed'), email)
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    let data: unknown = []
    if (path === '/api/auth/me') data = { id: 'operator', email, is_admin: false }
    else if (path === '/api/projects') data = [{ id: 'project-1', project_name: '整理済みリスト', status: 'active', region: '大阪府' }]
    else if (path.endsWith('/members')) data = [{ email, role: options.viewer ? 'viewer' : 'owner' }]
    else if (path === '/api/dashboard') data = { total_companies: 2 }
    else if (path === '/api/outreach-execution-status') data = { outbound_enabled: true }
    else if (path.endsWith('/companies')) data = [{ id: 'company-0', company_name: '候補', status: 'unreviewed' }]
    else if (path.endsWith('/bulk-send-preview')) data = {
      items: reserved ? [] : proposals, skipped: { '営業NG・収集対象外': 4 },
      email_enabled: !options.stopped, form_enabled: !options.stopped,
    }
    else if (route.request().method() === 'POST') {
      requests.push({ path, body: route.request().postDataJSON() })
      if (options.disconnected && requests.length === 1) { await route.abort(); return }
      if (path.endsWith('/approved-form-dispatches')) {
        formAttempt++
        const items = route.request().postDataJSON().items as { request_id: string }[]
        if (options.partial && formAttempt === 1) {
          data = { results: items.map(i => ({ request_id: i.request_id, reservation: null, error: '営業NGへ変更されました' })) }
        } else {
          reserved = true
          data = { results: items.map(i => ({ request_id: i.request_id, reservation: { id: 'reservation' }, error: null })) }
        }
      } else data = { id: 'batch', status: 'queued' }
    }
    await route.fulfill({ json: data })
  })
  await page.goto('/')
  await navigateWorkspace(page, '④ 収集リストの確認')
  return { panel: page.getByRole('region', { name: 'クリーニング済みリストの一括送信' }), requests }
}

test('One click reserves both approved channels without approving or sending from the browser', async ({ page }, info) => {
  const { panel, requests } = await setup(page)
  await expect(panel).toContainText('メール 1件 / フォーム 1件')
  await panel.screenshot({ path: info.outputPath('bulk-send-ready.png') })
  expect(requests).toEqual([])
  await panel.getByRole('button', { name: '承認済み2件を一括送信開始' }).click()
  await expect(panel.getByRole('status')).toContainText('2件の送信予約が完了')
  expect(requests.map(r => r.path)).toEqual(['/api/projects/project-1/approved-email-batches', '/api/projects/project-1/approved-form-dispatches'])
  expect(requests[0].body.items).toEqual([{ request_id: 'approval-0', expected_hash: 'hash-0', expected_version: 1 }])
  await expect(panel.getByRole('button', { name: '承認済み0件を一括送信開始' })).toBeDisabled()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('Partial failure retries only the unfinished channel with the same key', async ({ page }) => {
  const { panel, requests } = await setup(page, { partial: true })
  await panel.getByRole('button', { name: '承認済み2件を一括送信開始' }).click()
  await expect(panel.getByRole('alert')).toContainText('営業NGへ変更')
  await panel.getByRole('button', { name: '未完了の予約を再試行' }).click()
  await expect(panel.getByRole('status')).toContainText('2件の送信予約が完了')
  expect(requests).toHaveLength(3)
  expect(requests[1].body.idempotency_key).toBe(requests[2].body.idempotency_key)
  expect(requests.filter(r => r.path.endsWith('/approved-email-batches'))).toHaveLength(1)
})

test('Full list exceeds one page and splits forms at the existing 100 item limit', async ({ page }) => {
  const { panel, requests } = await setup(page, { large: true })
  await panel.getByRole('button', { name: '承認済み201件を一括送信開始' }).click()
  await expect(panel.getByRole('status')).toContainText('201件の送信予約が完了')
  expect(requests.map(r => r.body.items.length)).toEqual([1, 100, 100])
})

test('Lost response keeps the email reservation key instead of recreating the request', async ({ page }) => {
  const { panel, requests } = await setup(page, { disconnected: true })
  await panel.getByRole('button', { name: '承認済み2件を一括送信開始' }).click()
  await expect(panel.getByRole('alert')).toContainText('接続できません')
  await panel.getByRole('button', { name: '未完了の予約を再試行' }).click()
  await expect(panel.getByRole('status')).toContainText('2件の送信予約が完了')
  expect(requests[0].body).toEqual(requests[1].body)
  expect(requests).toHaveLength(3)
})

for (const option of [{ viewer: true }, { stopped: true }]) {
  test(`Does not reserve for ${JSON.stringify(option)}`, async ({ page }) => {
    const { panel, requests } = await setup(page, option)
    await expect(panel.getByRole('button', { name: '承認済み2件を一括送信開始' })).toBeDisabled()
    expect(requests).toEqual([])
  })
}
