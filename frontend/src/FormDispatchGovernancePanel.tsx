import { useEffect, useRef, useState } from 'react'
import { api, errorMessage } from './api'
import { Field } from './forms'
import type { ApprovalProposal } from './ApprovedEmailPanel'

interface Limits {
  daily_limit: number; hourly_limit: number; minimum_interval_seconds: number
  site_interval_seconds: number
  paused: boolean; version: number; can_manage: boolean; execution_enabled: boolean
}
interface DailySummary {
  daily_limit: number; started_last_24h: number; approved_unsent: number
  pending_approvals: number; remaining_quota: number; paused: boolean; within_send_window: boolean
}
interface ApprovalBatchJob {
  id: string; operation_type: string; status: string; total_count: number
  processed_count: number; success_count: number; failed_count: number
  form_approval_results: { company_id: string; status: string; reason_code?: string | null }[]
}
export function FormDispatchGovernancePanel({ projectId, items, canWrite, refresh }: {
  projectId: string; items: ApprovalProposal[]; canWrite: boolean; refresh: () => Promise<void>
}) {
  const [limits, setLimits] = useState<Limits | null>(null)
  const [savedLimits, setSavedLimits] = useState<Limits | null>(null)
  const [dailySummary, setDailySummary] = useState<DailySummary | null>(null)
  const [batchJob, setBatchJob] = useState<ApprovalBatchJob | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [password, setPassword] = useState('')
  const [adminPassword, setAdminPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const key = useRef<string | null>(null)
  const candidates = items.filter(i => i.channel === 'form' && i.delivery_method === 'form_direct' && ['PENDING', 'APPROVED'].includes(i.status))
  const chosen = candidates.filter(i => selected.includes(i.id))
  const pending = chosen.filter(i => i.status === 'PENDING')
  const approved = chosen.filter(i => i.status === 'APPROVED')
  const selections = (rows: ApprovalProposal[]) => rows.map(i => ({ request_id: i.id, expected_hash: i.payload_hash, expected_version: i.payload_version }))
  useEffect(() => {
    let live = true
    api<Limits>('/form-dispatch-limits').then(v => { if (live) { setLimits(v); setSavedLimits(v) } }).catch(e => { if (live) setError(errorMessage(e)) })
    return () => { live = false }
  }, [])
  useEffect(() => {
    let live = true
    api<DailySummary>(`/projects/${projectId}/form-approval-daily-summary`).then(value => {
      if (live) setDailySummary(value)
    }).catch(e => { if (live) setError(errorMessage(e)) })
    return () => { live = false }
  }, [projectId, items])
  useEffect(() => {
    if (!batchJob || !['queued', 'running'].includes(batchJob.status)) return
    const timer = window.setInterval(() => {
      api<ApprovalBatchJob[]>(`/projects/${projectId}/operations?limit=20`).then(rows => {
        const current = rows.find(row => row.id === batchJob.id)
        if (current) setBatchJob(current)
      }).catch(e => setError(errorMessage(e)))
    }, 2000)
    return () => window.clearInterval(timer)
  }, [batchJob?.id, batchJob?.status, projectId])
  function choose(ids: string[]) {
    setSelected(ids)
    key.current = null
    const sample = ids.map(id => ({ id, random: crypto.getRandomValues(new Uint32Array(1))[0] }))
      .sort((a, b) => a.random - b.random).slice(0, 5).map(entry => entry.id)
    setReviewSampleIds(sample)
  }
  const [reviewSampleIds, setReviewSampleIds] = useState<string[]>([])
  async function act(fn: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try { await fn(); await refresh() } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false); setPassword(''); setAdminPassword('') }
  }
  return <section className="panel mt-4" aria-label="フォーム一括承認と上限管理">
    <h2>フォームの一括Human承認・予約</h2>
    <p>このページの宛先・各社の入力値を確認して選択してください。一括承認と予約は別操作です。期限は最大24時間で、期限切れは実行できません。</p>
    {canWrite && <button type="button" className="secondary mt-3" disabled={busy || Boolean(batchJob && ['queued', 'running'].includes(batchJob.status))} onClick={() => act(async () => {
      const job = await api<ApprovalBatchJob>(`/projects/${projectId}/form-approval-requests/bulk`, 'POST', { all_ready: true })
      setBatchJob(job)
      setNotice('READY企業の承認提案作成をバックグラウンドに登録しました。送信・予約は行いません。')
    })}>READY全社からフォーム承認提案を一括作成</button>}
    {batchJob && <div role="status" className="mt-3 rounded border p-3">
      <strong>一括提案作成: {batchJob.status === 'completed' ? '完了' : batchJob.status === 'failed' ? '失敗' : '処理中'}</strong>
      <p>進捗 {batchJob.processed_count}/{batchJob.total_count} · 作成/既存 {batchJob.success_count} · 要確認 {batchJob.failed_count}</p>
      {batchJob.form_approval_results.slice(-10).map(result => <p key={result.company_id}>{result.company_id}: {result.status}{result.reason_code ? ` (${result.reason_code})` : ''}</p>)}
    </div>}
    {dailySummary && <p role="status" className="mt-2">本日の送信枠: 残り{dailySummary.remaining_quota}件 / 上限{dailySummary.daily_limit}件（直近24時間の実行{dailySummary.started_last_24h}件・承認済み未送信{dailySummary.approved_unsent}件） · このプロジェクトの承認待ち{dailySummary.pending_approvals}件{dailySummary.paused ? ' · 一時停止中' : !dailySummary.within_send_window ? ' · 送信時間外' : ''}</p>}
    {error && <p className="error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    <fieldset disabled={busy || !canWrite}>
      {candidates.map(i => <details key={i.id} className="my-3"><summary>{i.company_name} / {i.status} / v{i.payload_version}</summary>
        <p className="break-all">宛先: {i.form_url} / POST先: {i.form_action_url || '未確定'}</p>
        <p>送信者: {i.sender.name} / {i.sender.email}</p><p>{i.subject}</p><p className="whitespace-pre-wrap break-words">{i.body}</p>
        {Object.entries(i.field_values).map(([name, value]) => <p className="break-words" key={name}>{name}: {value}</p>)}
        <p>期限: {new Date(i.expires_at).toLocaleString('ja-JP')}</p>
        <label><input type="checkbox" checked={selected.includes(i.id)} disabled={!i.form_action_url} onChange={() => choose(selected.includes(i.id) ? selected.filter(x => x !== i.id) : [...selected, i.id])} /> {i.company_name}の入力内容を確認して選択</label>
      </details>)}
      <button type="button" className="secondary" disabled={!candidates.some(i => i.status === 'PENDING' && i.form_action_url) || !dailySummary?.remaining_quota} onClick={() => {
        const ids = candidates.filter(i => i.status === 'PENDING' && i.form_action_url).sort((a, b) => a.created_at.localeCompare(b.created_at)).slice(0, dailySummary?.remaining_quota ?? 0).map(i => i.id)
        choose(ids)
      }}>本日の枠の分だけ選択</button>{' '}
      <button type="button" className="secondary" disabled={!candidates.some(i => i.form_action_url)} onClick={() => choose(candidates.filter(i => i.form_action_url).map(i => i.id))}>このページのフォームをまとめて選択</button>{' '}
      <button type="button" className="secondary" onClick={() => choose([])}>フォーム選択を解除</button>
      {reviewSampleIds.length > 0 && <div className="mt-4 rounded border p-3" aria-label="承認前の抜き取り確認">
        <h3>承認前の抜き取り確認（無作為に最大5件）</h3>
        {chosen.filter(i => reviewSampleIds.includes(i.id)).map(i => <article key={i.id} className="border-t py-3">
          <strong>{i.company_name}</strong><p className="break-all">宛先URL: {i.form_url}</p>
          <p className="whitespace-pre-wrap break-words">本文: {i.body}</p>
          {Object.entries(i.field_values).map(([name, value]) => <p className="break-words" key={name}>{name}: {value}</p>)}
        </article>)}
      </div>}
      <Field label="フォーム一括承認用ログインパスワード"><input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></Field>
      <button type="button" disabled={!pending.length || !password || !dailySummary || pending.length > dailySummary.remaining_quota} onClick={() => act(async () => {
        const proof = await api<{ challenge_token: string }>(`/projects/${projectId}/bulk-approval/challenge`, 'POST', { items: selections(pending) })
        await api(`/projects/${projectId}/bulk-approval/verify`, 'POST', { challenge_token: proof.challenge_token, password })
        await api(`/projects/${projectId}/bulk-approval/approve`, 'POST', { challenge_token: proof.challenge_token })
        setNotice(`${pending.length}件をHuman承認しました。まだ予約していません。`)
      })}>フォーム{pending.length}件を一括Human承認</button>{' '}
      <button type="button" disabled={!approved.length} onClick={() => act(async () => {
        key.current ??= crypto.randomUUID()
        const result = await api<{ results: { request_id: string; reservation: unknown; error: string | null }[] }>(`/projects/${projectId}/approved-form-dispatches`, 'POST', { items: selections(approved), idempotency_key: key.current })
        const failures = result.results.filter(r => r.error)
        setNotice(`${result.results.length - failures.length}件を予約済みとして確認しました。${failures.length}件は未予約です。${limits?.execution_enabled ? '' : '実送信はOFFです。'}`)
        if (failures.length) setError(failures.map(r => `${r.request_id}: ${r.error}`).join(' / '))
      })}>承認済みフォーム{approved.length}件を一括予約</button>
    </fieldset>
    {limits && <div className="mt-4">
      <h3>環境全体のフォーム送信上限</h3>
      <p>保存済み: 直近24時間{savedLimits?.daily_limit}件・直近1時間{savedLimits?.hourly_limit}件・間隔{savedLimits?.minimum_interval_seconds}秒・同じサイト{savedLimits?.site_interval_seconds ?? 300}秒 / {savedLimits?.paused ? '一時停止中' : '上限に従って実行'} / 実行{savedLimits?.execution_enabled ? '有効' : 'OFF'}</p>
      <p>上限変更では実送信を有効化しません。結果不明・失敗した試行も上限に数えます。承認期限内に処理できる件数を予約してください。</p>
      {limits.can_manage && <fieldset disabled={busy}>
        <Field label="フォーム24時間上限"><input type="number" min="1" max="1000" value={limits.daily_limit} onChange={e => setLimits({ ...limits, daily_limit: Number(e.target.value) })} /></Field>
        <Field label="フォーム1時間上限"><input type="number" min="1" max="100" value={limits.hourly_limit} onChange={e => setLimits({ ...limits, hourly_limit: Number(e.target.value) })} /></Field>
        <Field label="フォーム試行間隔（秒）"><input type="number" min="60" max="86400" value={limits.minimum_interval_seconds} onChange={e => setLimits({ ...limits, minimum_interval_seconds: Number(e.target.value) })} /></Field>
        <Field label="同じサイトへの試行間隔（秒）"><input type="number" min="60" max="86400" value={limits.site_interval_seconds ?? 300} onChange={e => setLimits({ ...limits, site_interval_seconds: Number(e.target.value) })} /></Field>
        <label><input type="checkbox" checked={limits.paused} onChange={e => setLimits({ ...limits, paused: e.target.checked })} /> フォーム実行を一時停止</label>
        <Field label="上限変更用管理者パスワード"><input type="password" autoComplete="current-password" value={adminPassword} onChange={e => setAdminPassword(e.target.value)} /></Field>
        <p>上限の増加・停止解除は今後の予約実行に反映されます。内容を確認して保存してください。</p>
        <button type="button" disabled={!adminPassword} onClick={() => act(async () => {
          const updated = await api<Limits>('/form-dispatch-limits', 'PUT', { daily_limit: limits.daily_limit, hourly_limit: limits.hourly_limit, minimum_interval_seconds: limits.minimum_interval_seconds, site_interval_seconds: limits.site_interval_seconds ?? 300, paused: limits.paused, expected_version: limits.version, password: adminPassword })
          setLimits(updated); setSavedLimits(updated); setNotice('フォーム上限を保存しました。実送信設定は変更していません。')
        })}>管理者再認証してフォーム上限を保存</button>{' '}
        <button type="button" className="secondary" onClick={() => act(async () => { const next = await api<Limits>('/form-dispatch-limits'); setLimits(next); setSavedLimits(next) })}>保存済み上限を再取得</button>
      </fieldset>}
    </div>}
  </section>
}
