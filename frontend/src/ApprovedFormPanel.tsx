import { useEffect, useRef, useState } from 'react'
import { api, errorMessage } from './api'
import type { ApprovalProposal } from './ApprovedEmailPanel'
import { FormDispatchGovernancePanel } from './FormDispatchGovernancePanel'
import { FormOperationsPanel } from './FormOperationsPanel'

interface Dispatch {
  id: string; approval_id: string; form_url: string; status: string; reason: string
  execution_enabled: boolean; created_at: string
  reservation_only?: boolean
  site_wait_until?: string | null
}
interface BrowserRun {
  id: string; mode: 'dry_run' | 'submit'; status: string; form_url: string; reason: string
  created_at: string; finished_at: string | null
  screenshot_before_url: string | null; screenshot_after_url: string | null
}
const labels: Record<string, string> = {
  queued: '予約待ち', checking: '事前確認中', submitted: '送信完了を確認',
  failed: '送信前に失敗・再承認が必要', unknown: '結果不明・再送禁止',
  blocked: '安全条件で停止', cancelled: '取消済み',
}

export function ApprovedFormPanel({ projectId, items, canWrite, refresh }: {
  projectId: string; items: ApprovalProposal[]; canWrite: boolean; refresh: () => Promise<void>
}) {
  const [rows, setRows] = useState<Dispatch[]>([])
  const [browserRuns, setBrowserRuns] = useState<BrowserRun[]>([])
  const [browserEnabled, setBrowserEnabled] = useState(false)
  const [offset, setOffset] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const keys = useRef<Record<string, string>>({})
  useEffect(() => {
    if (!projectId) return
    let live = true
    api<Dispatch[]>(`/projects/${projectId}/approved-form-dispatches?limit=50&offset=${offset}`)
      .then(next => { if (live) setRows(next) }).catch(e => { if (live) setError(errorMessage(e)) })
    return () => { live = false }
  }, [projectId, offset, items])
  useEffect(() => {
    if (!projectId) return
    let live = true
    Promise.all([
      api<BrowserRun[]>(`/projects/${projectId}/browser-form-runs?limit=20`),
      api<{ browser_form_execution_enabled: boolean }>('/form-dispatch-limits'),
    ]).then(([runs, limits]) => {
      if (live) { setBrowserRuns(runs); setBrowserEnabled(limits.browser_form_execution_enabled) }
    }).catch(e => { if (live) setError(errorMessage(e)) })
    return () => { live = false }
  }, [projectId, items, rows])
  useEffect(() => {
    if (!browserRuns.some(run => ['queued', 'checking'].includes(run.status))) return
    const timer = window.setInterval(() => {
      void api<BrowserRun[]>(`/projects/${projectId}/browser-form-runs?limit=20`)
        .then(setBrowserRuns).catch(e => setError(errorMessage(e)))
    }, 4000)
    return () => window.clearInterval(timer)
  }, [projectId, browserRuns])
  async function act(fn: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try {
      await fn()
      setRows(await api<Dispatch[]>(`/projects/${projectId}/approved-form-dispatches?limit=50&offset=${offset}`))
      setBrowserRuns(await api<BrowserRun[]>(`/projects/${projectId}/browser-form-runs?limit=20`))
      await refresh()
    } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false) }
  }
  async function reserve(item: ApprovalProposal) {
    await act(async () => {
      keys.current[item.id] ??= crypto.randomUUID()
      const result = await api<Dispatch>(`/approval-requests/${item.id}/form-dispatch`, 'POST', {
        expected_hash: item.payload_hash, expected_version: item.payload_version,
        idempotency_key: keys.current[item.id],
      })
      setNotice(result.reservation_only ? '予約のみを保存しました。この予約から送信は始まりません。' : result.execution_enabled ? '承認した内容で予約しました。ワーカーが送信前に再確認します。' : '予約を保存しました。フォーム実行はOFFのため送信されません。')
    })
  }
  return <><FormOperationsPanel key={`operations-${projectId}`} projectId={projectId} canWrite={canWrite} refresh={refresh} /><FormDispatchGovernancePanel key={projectId} projectId={projectId} items={items} canWrite={canWrite} refresh={refresh} /><section className="panel" aria-label="承認済みフォーム予約">
    <h2>承認済みフォームの送信予約</h2>
    <p className="muted">ブラウザー方式は同一サイト内・CAPTCHAなしの確認済み計画だけが対象です。機能は既定OFFです。</p>
    <p className="muted">宛先・POST先・文面・入力値が固定されたHuman承認だけを使います。実行設定は既定OFFです。上限は上の共通設定に従います。結果不明は自動再送しません。</p>
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    <fieldset disabled={busy}>
      {canWrite && items.filter(item => item.channel === 'form' && ['form_direct', 'form_adapter', 'cf7_real_reservation', 'browser_form'].includes(item.delivery_method ?? '') && item.status === 'APPROVED').map(item => <div key={item.id} className="my-3">
        <p>{item.company_name} / v{item.payload_version} / {item.subject}</p>
        {item.delivery_method === 'cf7_real_reservation' && <p>CF7予約のみ。Human再承認済みですが、送信には使用できません。</p>}
        {item.delivery_method === 'browser_form' && <p>{browserEnabled ? 'ブラウザー送信が有効です。送信直前にも承認payloadを再確認します。' : 'ブラウザー送信はOFFです。設定が有効になるまで予約できません。'}</p>}
        {item.adapter_plan && <p>管理下フォーム・予約のみ。実行器は未接続です。</p>}
        <details><summary>承認内容を確認</summary><p className="break-all">{item.form_url}</p><p className="break-all">POST先: {item.form_action_url || '未確定・再解析が必要'}</p><p className="whitespace-pre-wrap break-words">{item.body}</p>{Object.entries(item.field_values).map(([name, value]) => <p className="break-words" key={name}>{name}: {value}</p>)}</details>
        <button type="button" disabled={rows.some(row => row.approval_id === item.id) || !item.form_action_url || item.delivery_method === 'browser_form' && !browserEnabled} onClick={() => reserve(item)}>{item.company_name} の承認済みフォームを予約</button>
      </div>)}
      <button type="button" className="secondary" onClick={() => act(async () => {})}>フォーム予約の状態を更新</button>
      {!rows.length && <p>フォーム予約はありません。</p>}
      {rows.map(row => <article className="mt-3" key={row.id}>
        <p className="break-all">{row.form_url} / {labels[row.status] ?? row.status}</p>
        {row.reservation_only && <p>予約のみ・実行未接続</p>}
        {!row.execution_enabled && row.status === 'queued' && <p>実行OFF・送信されません</p>}
        {row.status === 'queued' && row.site_wait_until && <p>同じサイトへの間隔待ち: {new Date(row.site_wait_until).toLocaleString('ja-JP')}以降に再確認</p>}
        {row.reason && <p role={row.status === 'unknown' ? 'alert' : undefined}>{row.reason}</p>}
        {canWrite && ['queued', 'checking'].includes(row.status) && <button type="button" className="secondary" onClick={() => act(async () => { await api(`/approved-form-dispatches/${row.id}/cancel`, 'POST') })}>フォーム予約を取り消す</button>}
      </article>)}
      <button type="button" className="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>前の50予約</button>{' '}
      <button type="button" className="secondary" disabled={rows.length < 50} onClick={() => setOffset(offset + 50)}>次の50予約</button>
    </fieldset>
    <section className="panel mt-5" aria-label="ブラウザーフォーム送信結果">
      <h3>ブラウザーフォームの結果</h3>
      {!browserRuns.length && <p className="muted">実行記録はありません。</p>}
      {browserRuns.map(run => <article className="job-row mt-3" key={run.id}>
        <div>
          <strong>{run.mode === 'dry_run' ? 'dry-run（送信なし）' : '承認済み送信'} / {run.status === 'submitted' ? '送信済み' : run.status === 'unknown' ? '結果不明・再送禁止' : run.status === 'failed' ? '失敗' : run.status === 'dry_run_completed' ? 'dry-run完了' : run.status}</strong>
          <p className="muted text-xs break-all">{run.form_url}</p>
          {run.reason && <p className={run.status === 'unknown' ? 'error' : 'muted text-sm'}>{run.reason}</p>}
          {run.finished_at && <time className="muted text-xs">{new Date(run.finished_at).toLocaleString('ja-JP')}</time>}
          {(run.screenshot_before_url || run.screenshot_after_url) && <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
            {run.screenshot_before_url && <figure><figcaption className="muted text-xs">送信前</figcaption><img className="max-h-80 rounded border" src={`/api${run.screenshot_before_url}`} alt="送信前のフォーム" /></figure>}
            {run.screenshot_after_url && <figure><figcaption className="muted text-xs">送信後</figcaption><img className="max-h-80 rounded border" src={`/api${run.screenshot_after_url}`} alt="送信後のフォーム" /></figure>}
          </div>}
        </div>
      </article>)}
    </section>
  </section></>
}
