import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, errorMessage } from './api'
import { Field } from './forms'
import type { ApprovalProposal } from './ApprovedEmailPanel'
import type { OperationJob } from './types'

type Channel = 'email' | 'form'
type QueueJob = OperationJob & { form_approval_results?: { status: string }[] }
type EmailDraft = { id: string; company_name: string; recipient: string; subject: string; body: string }
type FormQuota = { daily_limit: number; remaining_quota: number; pending_approvals: number; paused: boolean; within_send_window: boolean }
type SendPreview = { items: ApprovalProposal[]; email_enabled: boolean; form_enabled: boolean; browser_form_enabled?: boolean }
type ReservationPlan = { items: ApprovalProposal[]; key: string; daily: number; hourly: number }

const candidate = (item: ApprovalProposal, channel: Channel) => item.channel === channel
  && (channel === 'email' ? item.delivery_method === 'email' : ['form_direct', 'browser_form'].includes(item.delivery_method ?? ''))
const selection = (items: ApprovalProposal[]) => items.map(item => ({
  request_id: item.id, expected_hash: item.payload_hash, expected_version: item.payload_version,
}))

function sample(items: ApprovalProposal[]) {
  return [...items].sort(() => Math.random() - 0.5).slice(0, 5).map(item => item.id)
}

export function SendFlowApprovalPanel({ projectId, channel, canWrite, canManageSettings, readinessCompletedAt, readinessStale, onRefresh, onSettings }: {
  projectId: string; channel: Channel; canWrite: boolean; readinessCompletedAt: string | null
  readinessStale: boolean; canManageSettings: boolean
  onRefresh: () => Promise<void>; onSettings: () => void
}) {
  const [pending, setPending] = useState<ApprovalProposal[]>([])
  const [approvedReady, setApprovedReady] = useState<ApprovalProposal[]>([])
  const [selected, setSelected] = useState<Record<string, ApprovalProposal>>({})
  const [sampleIds, setSampleIds] = useState<string[]>([])
  const [offset, setOffset] = useState(0)
  const [emailDrafts, setEmailDrafts] = useState<EmailDraft[]>([])
  const [draftIds, setDraftIds] = useState<string[]>([])
  const [draftsOpen, setDraftsOpen] = useState(false)
  const [job, setJob] = useState<QueueJob | null>(null)
  const [quota, setQuota] = useState<FormQuota | null>(null)
  const [preview, setPreview] = useState<SendPreview | null>(null)
  const [password, setPassword] = useState('')
  const [dailyLimit, setDailyLimit] = useState(500)
  const [hourlyLimit, setHourlyLimit] = useState(60)
  const [retryPlan, setRetryPlan] = useState<ReservationPlan | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [sendingWindow, setSendingWindow] = useState('運用設定に従います')
  const jobId = job?.id
  const jobStatus = job?.status
  const selectionLimit = channel === 'form' ? 100 : 500

  const refreshQueue = useCallback(async () => {
    const [pendingRows, previewResult] = await Promise.all([
      api<ApprovalProposal[]>(`/projects/${projectId}/approval-requests?status=PENDING&limit=100&offset=${offset}`),
      api<SendPreview>(`/projects/${projectId}/bulk-send-preview`),
    ])
    setPending(pendingRows.filter(item => candidate(item, channel)))
    setApprovedReady((previewResult.items ?? []).filter(item => candidate(item, channel)))
    setPreview(previewResult)
  }, [channel, offset, projectId])

  useEffect(() => {
    let active = true
    setError('')
    Promise.all([
      api<ApprovalProposal[]>(`/projects/${projectId}/approval-requests?status=PENDING&limit=100&offset=${offset}`),
      api<SendPreview>(`/projects/${projectId}/bulk-send-preview`),
    ]).then(([pendingRows, previewResult]) => {
      if (!active) return
      setPending(pendingRows.filter(item => candidate(item, channel)))
      setApprovedReady((previewResult.items ?? []).filter(item => candidate(item, channel)))
      setPreview(previewResult)
    }).catch(reason => { if (active) setError(errorMessage(reason)) })
    if (channel === 'form') api<FormQuota>(`/projects/${projectId}/form-approval-daily-summary`).then(value => { if (active) setQuota(value) }).catch(reason => { if (active) setError(errorMessage(reason)) })
    api<{ enabled: boolean; start_minute: number; end_minute: number; timezone: string }>('/admin/sending-window').then(value => {
      if (!active) return
      const clock = (minute: number) => `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`
      setSendingWindow(value.enabled ? `毎日 ${clock(value.start_minute)}〜${clock(value.end_minute)}（${value.timezone}）` : '時間帯の制限なし')
    }).catch(() => {})
    return () => { active = false }
  }, [channel, offset, projectId])

  useEffect(() => {
    if (!jobId || !['queued', 'running'].includes(jobStatus ?? '')) return
    const timer = window.setInterval(() => {
      api<QueueJob[]>(`/projects/${projectId}/operations?limit=100`).then(rows => {
        const current = rows.find(row => row.id === jobId)
        if (!current) return
        setJob(current)
        if (['completed', 'failed', 'cancelled'].includes(current.status)) {
          setNotice(current.status === 'completed' ? '承認待ち提案を作成しました。内容を確認してください。' : '提案の一括作成が完了しませんでした。')
          void refreshQueue(); void onRefresh()
        }
      }).catch(reason => setError(errorMessage(reason)))
    }, 2000)
    return () => window.clearInterval(timer)
  }, [jobId, jobStatus, onRefresh, projectId, refreshQueue])

  useEffect(() => {
    if (channel !== 'form') return
    api<FormQuota>(`/projects/${projectId}/form-approval-daily-summary`).then(setQuota).catch(reason => setError(errorMessage(reason)))
  }, [channel, pending, projectId])

  const selectedItems = useMemo(() => Object.values(selected), [selected])
  const pendingSelected = selectedItems.filter(item => item.status === 'PENDING')
  const approvedSelected = selectedItems.filter(item => item.status === 'APPROVED')
  const waitingForFormJob = Boolean(job && ['queued', 'running'].includes(job.status))
  const dailyRemaining = channel === 'form' ? quota?.remaining_quota ?? 0 : dailyLimit
  const channelEnabled = channel === 'form' ? !!preview?.form_enabled : !!preview?.email_enabled
  const browserDeliveryDisabled = channel === 'form'
    && selectedItems.some(item => item.delivery_method === 'browser_form')
    && !preview?.browser_form_enabled
  const canReserve = channel !== 'form' || Boolean(quota && !quota.paused && quota.within_send_window && selectedItems.length <= quota.remaining_quota)

  function choose(items: ApprovalProposal[]) {
    setSelected(Object.fromEntries(items.map(item => [item.id, item])))
    setSampleIds(sample(items))
    setRetryPlan(null)
  }

  async function loadEmailDrafts() {
    setBusy(true); setError(''); setNotice('')
    try {
      setEmailDrafts(await api<EmailDraft[]>(`/projects/${projectId}/approval-email-drafts?limit=100&offset=0`))
      setDraftIds([]); setDraftsOpen(true)
    } catch (reason) { setError(errorMessage(reason)) } finally { setBusy(false) }
  }

  async function createEmailApprovals() {
    setBusy(true); setError(''); setNotice('')
    try {
      await api(`/projects/${projectId}/approval-requests/from-drafts`, 'POST', { draft_ids: draftIds })
      setEmailDrafts([]); setDraftIds([]); setDraftsOpen(false)
      setNotice('選択した文面を承認待ちに追加しました。')
      await refreshQueue(); await onRefresh()
    } catch (reason) { setError(errorMessage(reason)) } finally { setBusy(false) }
  }

  async function createFormApprovals() {
    setBusy(true); setError(''); setNotice('')
    try {
      const created = await api<QueueJob>(`/projects/${projectId}/form-approval-requests/bulk`, 'POST', { all_ready: true })
      setJob(created)
      setNotice('準備できたフォームから承認待ちを作成しています。送信・予約は行いません。')
      if (created.status === 'completed') { await refreshQueue(); await onRefresh() }
    } catch (reason) { setError(errorMessage(reason)) } finally { setBusy(false) }
  }

  async function reserve(plan: ReservationPlan) {
    if (channel === 'email') {
      await api(`/projects/${projectId}/approved-email-batches`, 'POST', {
        items: selection(plan.items), name: '会社別メール予約', daily_limit: plan.daily,
        hourly_limit: plan.hourly, idempotency_key: plan.key,
      })
      return
    }
    const result = await api<{ results: { request_id: string; reservation: unknown; error: string | null }[] }>(
      `/projects/${projectId}/approved-form-dispatches`, 'POST', { items: selection(plan.items), idempotency_key: plan.key })
    const failures = result.results.filter(item => item.error || !item.reservation)
    if (result.results.length !== plan.items.length || failures.length) {
      throw new Error(failures.map(item => item.error || '予約結果を確認できません。').join(' / ') || '一部の予約結果を確認できません。')
    }
  }

  async function approveAndReserve() {
    if (!selectedItems.length || !canWrite || !channelEnabled || browserDeliveryDisabled || !canReserve || busy) return
    const plan = { items: selectedItems, key: crypto.randomUUID(), daily: dailyLimit, hourly: hourlyLimit }
    setBusy(true); setError(''); setNotice('')
    let approved = pendingSelected.length === 0
    try {
      if (pendingSelected.length) {
        const proof = await api<{ challenge_token: string }>(`/projects/${projectId}/bulk-approval/challenge`, 'POST', { items: selection(pendingSelected) })
        await api(`/projects/${projectId}/bulk-approval/verify`, 'POST', { challenge_token: proof.challenge_token, password })
        await api(`/projects/${projectId}/bulk-approval/approve`, 'POST', { challenge_token: proof.challenge_token })
        approved = true
      }
      await reserve(plan)
      setRetryPlan(null); setSelected({}); setSampleIds([])
      setNotice(`${plan.items.length}件を承認・予約しました。送信時間帯・上限・停止設定に従って処理します。`)
      await refreshQueue(); await onRefresh()
    } catch (reason) {
      setError(errorMessage(reason))
      if (approved) {
        setRetryPlan(plan)
        setNotice('承認は完了しましたが予約を確認できません。予約だけやり直してください（同じ予約キーを使用します）。')
        await refreshQueue().catch(() => {})
      }
    } finally { setBusy(false); setPassword('') }
  }

  async function retryReservation() {
    if (!retryPlan || busy) return
    setBusy(true); setError(''); setNotice('')
    try {
      await reserve(retryPlan)
      setRetryPlan(null); setSelected({})
      setNotice(`${retryPlan.items.length}件を同じ予約キーで予約しました。`)
      await refreshQueue(); await onRefresh()
    } catch (reason) {
      setError(errorMessage(reason)); setNotice('予約は未確認です。再試行では同じ予約キーを使います。')
    } finally { setBusy(false) }
  }

  const quotaSelectable = [...pending, ...approvedReady]
    .sort((left, right) => left.created_at.localeCompare(right.created_at))
    .slice(0, Math.min(selectionLimit, dailyRemaining, channel === 'email' ? hourlyLimit : 100))
  const currentPageItems = [...pending, ...approvedReady]
  const sampled = selectedItems.filter(item => sampleIds.includes(item.id))

  return <section className="space-y-4" aria-label="承認して送る">
    <p className="muted">承認前に宛先・内容を確認し、ログインパスワードで再認証します。承認後、同じ選択内容を既存の予約APIへ登録します。送信の安全判定はサーバー側で再確認されます。</p>
    {channel === 'email' ? <>
      <div className="rounded border p-3"><strong>メール承認待ちの作成</strong><p className="muted mt-1">メール下書きを選び、承認待ちへ追加します。</p>
        <button type="button" className="secondary mt-2" disabled={busy || !canWrite} onClick={() => void loadEmailDrafts()}>準備済みメール文面を選ぶ</button>
        {draftsOpen && <div className="mt-3 space-y-2">{emailDrafts.map(draft => <details className="border-t py-2" key={draft.id}><summary>{draft.company_name} / {draft.recipient || '宛先なし'} / {draft.subject}</summary><p className="whitespace-pre-wrap">{draft.body}</p><label><input type="checkbox" disabled={!draft.recipient} checked={draftIds.includes(draft.id)} onChange={() => setDraftIds(ids => ids.includes(draft.id) ? ids.filter(id => id !== draft.id) : [...ids, draft.id])} /> 承認待ちに追加</label></details>)}
          {!emailDrafts.length && <p>追加できるメール文面はありません。</p>}
          <button type="button" disabled={busy || !draftIds.length} onClick={() => void createEmailApprovals()}>{draftIds.length}件を承認待ちに追加</button></div>}
      </div>
    </> : <div className="rounded border p-3"><strong>フォーム承認待ちの作成</strong><p className="muted mt-1">最新の送信可否で「準備可能」と判定されたフォーム文面から候補を作成します。解析が古い場合は文面段階で再集計してください。</p>
      <button type="button" disabled={busy || !canWrite || waitingForFormJob || !readinessCompletedAt || readinessStale} onClick={() => void createFormApprovals()}>{waitingForFormJob ? '承認待ちを作成中…' : '準備できたフォームの承認待ちを作成'}</button>
    </div>}
    {job && <p role="status">提案作成 {job.status} · {job.processed_count}/{job.total_count}社</p>}
    <div className="rounded border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2"><strong>送信上限・時間帯</strong>{canManageSettings
        ? <button type="button" className="secondary" onClick={onSettings}>運用設定で確認・変更</button>
        : <span className="muted text-sm">環境共通の設定変更は管理者に依頼してください。</span>}</div>
      {channel === 'form' && quota ? <p className="muted mt-2">本日の枠：残り{quota.remaining_quota}件 / 上限{quota.daily_limit}件 · {quota.paused ? '一時停止中' : quota.within_send_window ? '時間内' : '送信時間外'}</p>
        : <p className="muted mt-2">送信時間帯：{sendingWindow} · メール予約ごとの上限：24時間{dailyLimit}件 / 1時間{hourlyLimit}件</p>}
      {channel === 'email' && <div className="grid gap-3 sm:grid-cols-2"><Field label="この予約の24時間上限"><input type="number" min="1" max="10000" value={dailyLimit} onChange={event => setDailyLimit(Number(event.target.value))} /></Field><Field label="この予約の1時間上限"><input type="number" min="1" max="1000" value={hourlyLimit} onChange={event => setHourlyLimit(Number(event.target.value))} /></Field></div>}
      <p className="muted mt-2">送信時間帯・実行ON/OFF・連絡禁止・重複防止は既存のサーバー判定を維持します。</p>
      {channel === 'form' && selectedItems.some(item => item.delivery_method === 'browser_form') && !preview?.browser_form_enabled && <p className="muted mt-2">ブラウザーフォーム送信は既定でOFFです。運用承認後に有効化されるまで予約できません。</p>}
    </div>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    <div className="rounded border p-3">
      <div className="flex flex-wrap gap-2"><button type="button" className="secondary" disabled={!quotaSelectable.length || busy} onClick={() => choose(quotaSelectable)}>本日の枠の分だけ選択（最大{selectionLimit}社）</button>
        <button type="button" className="secondary" disabled={!currentPageItems.length || busy} onClick={() => choose(currentPageItems.slice(0, selectionLimit))}>表示中の対象を選択</button>
        <button type="button" className="secondary" disabled={!selectedItems.length || busy} onClick={() => choose([])}>選択解除</button></div>
      <h3 className="mt-4">承認待ち {pending.length}件 · 予約可能な承認済み {approvedReady.length}件</h3>
      {pending.map(item => <details className="border-t py-3" key={item.id}><summary>{item.company_name} / {channel === 'email' ? item.recipient : item.form_url}</summary>
        <p>送信者: {item.sender.name} / {item.sender.email}</p><p>件名: {item.subject}</p><p className="whitespace-pre-wrap break-words">{item.body}</p>
        {channel === 'form' && Object.entries(item.field_values).map(([name, value]) => <p className="break-words" key={name}>{name}: {value}</p>)}
        {item.delivery_method === 'browser_form' && item.browser_form_plan && <p className="muted text-sm">ブラウザー計画: {String(item.browser_form_plan.submission_kind)} · CAPTCHAなし · 同一サイト内 · {Array.isArray(item.browser_form_plan.fields) ? item.browser_form_plan.fields.length : 0}項目</p>}
        <p>承認期限: {new Date(item.expires_at).toLocaleString('ja-JP')}</p>
        <label><input type="checkbox" checked={Boolean(selected[item.id])} disabled={!canWrite || selectedItems.length >= selectionLimit && !selected[item.id]} onChange={() => choose(selected[item.id] ? selectedItems.filter(value => value.id !== item.id) : [...selectedItems, item])} /> 承認・予約対象にする</label>
      </details>)}
      {approvedReady.map(item => <details className="border-t py-3" key={item.id}><summary>{item.company_name} / {channel === 'email' ? item.recipient : item.form_url} / 承認済み</summary>
        <p>件名: {item.subject}</p><p className="whitespace-pre-wrap break-words">{item.body}</p>
        {channel === 'form' && Object.entries(item.field_values).map(([name, value]) => <p className="break-words" key={name}>{name}: {value}</p>)}
        {item.delivery_method === 'browser_form' && item.browser_form_plan && <p className="muted text-sm">ブラウザー計画: {String(item.browser_form_plan.submission_kind)} · CAPTCHAなし · 同一サイト内 · {Array.isArray(item.browser_form_plan.fields) ? item.browser_form_plan.fields.length : 0}項目</p>}
        <label><input type="checkbox" checked={Boolean(selected[item.id])} disabled={!canWrite || selectedItems.length >= selectionLimit && !selected[item.id]} onChange={() => choose(selected[item.id] ? selectedItems.filter(value => value.id !== item.id) : [...selectedItems, item])} /> 予約対象にする</label>
      </details>)}
      {!pending.length && !approvedReady.length && <p className="muted mt-3">このページに選択可能な{channel === 'email' ? 'メール' : '通常フォーム'}はありません。</p>}
      <div className="actions"><button type="button" className="secondary" disabled={offset === 0 || busy} onClick={() => setOffset(value => Math.max(0, value - 100))}>前の100件</button><span>{offset + 1}件目から</span><button type="button" className="secondary" disabled={pending.length < 100 || busy} onClick={() => setOffset(value => value + 100)}>次の100件</button></div>
    </div>
    {sampled.length > 0 && <section className="rounded border p-3" aria-label="承認前の抜き取り確認"><h3>承認前に無作為の最大5件を全文確認</h3>
      {sampled.map(item => <article className="border-t py-3" key={item.id}><strong>{item.company_name}</strong><p className="break-all">宛先: {channel === 'email' ? item.recipient : item.form_url}</p><p>件名: {item.subject}</p><pre className="whitespace-pre-wrap break-words">{item.body}</pre>{channel === 'form' && Object.entries(item.field_values).map(([name, value]) => <p className="break-words" key={name}>{name}: {value}</p>)}</article>)}
    </section>}
    {pendingSelected.length > 0 && <Field label="ログインパスワード（再認証）"><input type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} /></Field>}
    <button type="button" disabled={!canWrite || busy || !selectedItems.length || !channelEnabled || browserDeliveryDisabled || !canReserve || pendingSelected.length > 0 && !password} onClick={() => void approveAndReserve()}>
      {pendingSelected.length ? `選択した${selectedItems.length}件を承認して送信予約` : `承認済み${approvedSelected.length}件を送信予約`}
    </button>
    {retryPlan && <button type="button" className="secondary" disabled={busy} onClick={() => void retryReservation()}>予約だけやり直す（同じ予約キー）</button>}
    {channel === 'form' && quota && !quota.remaining_quota && <p className="muted">本日の予約可能枠がありません。承認・送信上限に達した場合は後で再度確認してください。</p>}
  </section>
}

export function SendFlowResultsPanel({ projectId, channel, onDeliveries }: { projectId: string; channel: Channel; onDeliveries: () => void }) {
  const [email, setEmail] = useState<{ items: { id: string; company_name: string; status: string; sent_at: string | null; created_at: string; recipient_email: string; subject: string }[]; queued_count: number; running_count: number; sent_count: number; failed_count: number; unknown_count: number } | null>(null)
  const [forms, setForms] = useState<{ items: { id: string; company_name: string; form_url: string; status: string; started_at: string | null }[]; counts: Record<string, number> } | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    const request = channel === 'email'
      ? api<typeof email>(`/projects/${projectId}/email-deliveries?limit=20`).then(value => { if (active) setEmail(value) })
      : api<typeof forms>(`/projects/${projectId}/form-operations?category=all&limit=20&offset=0`).then(value => { if (active) setForms(value) })
    request.catch(reason => { if (active) setError(errorMessage(reason)) })
    return () => { active = false }
  }, [channel, projectId])
  const rows = channel === 'email' ? email?.items ?? [] : forms?.items ?? []
  const totals = channel === 'email'
    ? [['送信待ち', email?.queued_count ?? 0], ['送信中', email?.running_count ?? 0], ['送信済み', email?.sent_count ?? 0], ['失敗', email?.failed_count ?? 0], ['結果不明', email?.unknown_count ?? 0]]
    : [['送信待ち', forms?.counts.queued ?? 0], ['送信中', forms?.counts.checking ?? 0], ['送信済み', forms?.counts.submitted ?? 0], ['失敗', forms?.counts.failed ?? 0], ['結果不明', forms?.counts.unknown ?? 0]]
  return <section aria-label="送信結果">
    <h3>結果（{channel === 'email' ? 'メール' : 'フォーム'}）</h3>
    <div className="mt-3 flex flex-wrap gap-2">{totals.map(([label, count]) => <span className="badge" key={label}>{label} {count}件</span>)}</div>
    {error && <p role="alert" className="error mt-3">{error}</p>}
    <div className="mt-3 space-y-2">{channel === 'email'
      ? (email?.items ?? []).slice(0, 20).map(item => <article className="border-t py-2" key={item.id}>
        <strong>{item.company_name}</strong><p className="muted text-sm">{item.recipient_email} / {item.subject}</p>
        <p className="muted text-xs">{item.sent_at || item.created_at} · {item.status}</p>
      </article>)
      : (forms?.items ?? []).slice(0, 20).map(item => <article className="border-t py-2" key={item.id}>
        <strong>{item.company_name}</strong><p className="muted text-sm">{item.form_url}</p>
        <p className="muted text-xs">{item.started_at || '開始日時未記録'} · {item.status}</p>
      </article>)}{!rows.length && !error && <p className="muted">この連絡方法の履歴はありません。</p>}</div>
    <div className="actions"><button type="button" className="secondary" onClick={onDeliveries}>配信結果ページを開く</button></div>
  </section>
}
