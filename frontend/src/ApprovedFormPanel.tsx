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
const labels: Record<string, string> = {
  queued: '予約待ち', checking: '事前確認中', submitted: '送信完了を確認',
  failed: '送信前に失敗・再承認が必要', unknown: '結果不明・再送禁止',
  blocked: '安全条件で停止', cancelled: '取消済み',
}

export function ApprovedFormPanel({ projectId, items, canWrite, refresh }: {
  projectId: string; items: ApprovalProposal[]; canWrite: boolean; refresh: () => Promise<void>
}) {
  const [rows, setRows] = useState<Dispatch[]>([])
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
  async function act(fn: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try {
      await fn()
      setRows(await api<Dispatch[]>(`/projects/${projectId}/approved-form-dispatches?limit=50&offset=${offset}`))
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
    <p className="muted">初期対応は確認画面を挟まないフォームのみです。確認画面・CAPTCHA・特殊フォームは人間による確認が必要です。</p>
    <p className="muted">宛先・POST先・文面・入力値が固定されたHuman承認だけを使います。実行設定は既定OFFです。上限は上の共通設定に従います。結果不明は自動再送しません。</p>
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    <fieldset disabled={busy}>
      {canWrite && items.filter(item => item.channel === 'form' && ['form_direct', 'form_adapter', 'cf7_real_reservation'].includes(item.delivery_method ?? '') && item.status === 'APPROVED').map(item => <div key={item.id} className="my-3">
        <p>{item.company_name} / v{item.payload_version} / {item.subject}</p>
        {item.delivery_method === 'cf7_real_reservation' && <p>CF7予約のみ。Human再承認済みですが、送信には使用できません。</p>}
        {item.adapter_plan && <p>管理下フォーム・予約のみ。実行器は未接続です。</p>}
        <details><summary>承認内容を確認</summary><p className="break-all">{item.form_url}</p><p className="break-all">POST先: {item.form_action_url || '未確定・再解析が必要'}</p><p className="whitespace-pre-wrap break-words">{item.body}</p>{Object.entries(item.field_values).map(([name, value]) => <p className="break-words" key={name}>{name}: {value}</p>)}</details>
        <button type="button" disabled={rows.some(row => row.approval_id === item.id) || !item.form_action_url} onClick={() => reserve(item)}>{item.company_name} の承認済みフォームを予約</button>
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
  </section></>
}
