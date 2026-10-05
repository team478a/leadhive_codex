import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import { Field } from './forms'

export interface ApprovalProposal {
  id: string; company_name: string; company_id: string; channel: 'email' | 'form'
  recipient: string | null; form_url: string | null; subject: string; body: string
  form_action_url?: string | null
  delivery_method?: string
  execution_plan?: Record<string, unknown> | null
  execution_plan_hash?: string | null
  sender: Record<string, string>; field_values: Record<string, string>
  payload_hash: string; payload_version: number; status: string
  created_by_principal_type: 'HUMAN' | 'AGENT'; created_at: string; expires_at: string
  rejection_reason: string | null; invalidation_reason: string | null
}
interface Batch {
  id: string; name: string; status: string; daily_limit: number; hourly_limit: number
  counts: Record<string, number>; execution_enabled: boolean
}
interface Draft { id: string; company_name: string; recipient: string; subject: string; body: string }
const labels: Record<string, string> = { queued: '予約待ち', running: '実行中', sent: 'SMTP受付済み', failed: '拒否・失敗', unknown: '結果不明・要確認', blocked: '安全条件で停止', cancelled: '取消済み', paused: '一時停止', completed: '処理終了' }

export function ApprovedEmailPanel({ projectId, items, canWrite, refresh }: {
  projectId: string; items: ApprovalProposal[]; canWrite: boolean; refresh: () => Promise<void>
}) {
  const [selected, setSelected] = useState<string[]>([])
  const [password, setPassword] = useState('')
  const [batches, setBatches] = useState<Batch[]>([])
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [draftIds, setDraftIds] = useState<string[]>([])
  const [draftOffset, setDraftOffset] = useState(0)
  const [daily, setDaily] = useState(500)
  const [hourly, setHourly] = useState(60)
  const [name, setName] = useState('会社別メール予約')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [reservationKey, setReservationKey] = useState<string | null>(null)
  const [showAll, setShowAll] = useState(false)
  const chosen = items.filter(i => selected.includes(i.id) && i.channel === 'email')
  const pending = chosen.filter(i => i.status === 'PENDING')
  const approved = chosen.filter(i => i.status === 'APPROVED')
  useEffect(() => {
    if (!projectId) return
    let live = true
    api<Batch[]>(`/projects/${projectId}/approved-email-batches`).then(b => { if (live) setBatches(b) }).catch(e => { if (live) setError(errorMessage(e)) })
    return () => { live = false }
  }, [projectId, items])
  async function act(fn: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try {
      await fn(); await refresh()
      setBatches(await api<Batch[]>(`/projects/${projectId}/approved-email-batches`))
    } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false); setPassword('') }
  }
  const selections = (rows: ApprovalProposal[]) => rows.map(i => ({ request_id: i.id, expected_hash: i.payload_hash, expected_version: i.payload_version }))
  async function bulkApprove() {
    await act(async () => {
      const proof = await api<{ challenge_token: string }>(`/projects/${projectId}/bulk-approval/challenge`, 'POST', { items: selections(pending) })
      await api(`/projects/${projectId}/bulk-approval/verify`, 'POST', { challenge_token: proof.challenge_token, password })
      await api(`/projects/${projectId}/bulk-approval/approve`, 'POST', { challenge_token: proof.challenge_token })
      setNotice(`${pending.length}件の宛先・文面をHuman承認しました。まだ送信予約していません。`)
    })
  }
  async function reserve() {
    const key = reservationKey ?? crypto.randomUUID()
    setReservationKey(key)
    await act(async () => {
      await api(`/projects/${projectId}/approved-email-batches`, 'POST', { items: selections(approved), name, daily_limit: daily, hourly_limit: hourly, idempotency_key: key })
      setNotice(`${approved.length}件を予約しました。実行が無効なら送信しません。`)
      setSelected([]); setReservationKey(null)
    })
  }
  function toggle(id: string) {
    setSelected(v => v.includes(id) ? v.filter(x => x !== id) : [...v, id]); setReservationKey(null)
  }
  async function loadDrafts(offset = draftOffset) {
    setDrafts(await api<Draft[]>(`/projects/${projectId}/approval-email-drafts?limit=50&offset=${offset}`))
    setDraftOffset(offset); setDraftIds([])
  }
  return <section className="panel mt-4 space-y-4" aria-label="承認済みメール予約">
    <h2>会社別メールの一括承認・送信予約</h2>
    <p className="muted">宛先と各社の文面を確認して選択してください。承認期限は最大24時間。日次・毎時上限とSMTPの上限の両方を守り、期限切れは再承認待ちで停止します。「SMTP受付済み」は相手への到達確認ではありません。</p>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    <fieldset disabled={busy || !canWrite} className="space-y-4">
      <button type="button" className="secondary" onClick={() => act(() => loadDrafts(0))}>準備済みメール文面を取得</button>
      {drafts.length > 0 && <div>
        <h3>承認待ちに追加する文面</h3>
        {drafts.map(d => <details key={d.id} className="my-2"><summary>{d.company_name} / {d.recipient || '宛先なし'} / {d.subject}</summary>
          <p className="whitespace-pre-wrap break-words">{d.body}</p>
          <label><input type="checkbox" checked={draftIds.includes(d.id)} disabled={!d.recipient} onChange={() => setDraftIds(v => v.includes(d.id) ? v.filter(x => x !== d.id) : [...v, d.id])} /> この文面を承認待ちに追加</label>
        </details>)}
        <button type="button" disabled={!draftIds.length} onClick={() => act(async () => {
          await api(`/projects/${projectId}/approval-requests/from-drafts`, 'POST', { draft_ids: draftIds }); setDrafts([]); setDraftIds([]); setNotice('承認待ち提案を作成しました。SMTP設定の送信者を使用します。')
        })}>選択文面を承認待ちに追加</button>{' '}
        <button type="button" className="secondary" disabled={drafts.length < 50} onClick={() => act(() => loadDrafts(draftOffset + 50))}>次の文面50件</button>
      </div>}
      <div className="flex flex-wrap gap-3">
        <button type="button" className="secondary" onClick={() => setShowAll(v => !v)}>{showAll ? '文面を折りたたむ' : 'このページの文面をすべて表示'}</button>
        <button type="button" className="secondary" onClick={() => { setSelected(items.filter(i => i.channel === 'email' && ['PENDING', 'APPROVED'].includes(i.status)).map(i => i.id)); setReservationKey(null) }}>このページのメールをまとめて選択</button>
        <button type="button" className="secondary" onClick={() => { setSelected([]); setReservationKey(null) }}>選択を解除</button>
      </div>
      <div className="space-y-3">{items.filter(i => i.channel === 'email' && ['PENDING', 'APPROVED'].includes(i.status)).map(i => <details key={i.id} open={showAll}>
        <summary>{i.company_name} / {i.recipient} / {i.status === 'PENDING' ? '承認待ち' : '承認済み'} / v{i.payload_version}</summary>
        <p>送信者: {i.sender.name} &lt;{i.sender.email}&gt;</p><p>件名: {i.subject}</p>
        <textarea aria-label={`${i.company_name}の確認用メール本文`} readOnly value={i.body} /><p>期限: {new Date(i.expires_at).toLocaleString('ja-JP')}</p>
        <label><input type="checkbox" checked={selected.includes(i.id)} onChange={() => toggle(i.id)} /> {i.company_name}の宛先・文面を確認して選択</label>
      </details>)}</div>
      <Field label="一括承認用ログインパスワード"><input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></Field>
      <button type="button" disabled={!pending.length || !password} onClick={bulkApprove}>選択した{pending.length}件を一括Human承認</button>
      <Field label="メール予約名"><input value={name} onChange={e => { setName(e.target.value); setReservationKey(null) }} /></Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="24時間の送信上限"><input type="number" min="1" max="10000" value={daily} onChange={e => { setDaily(Number(e.target.value)); setReservationKey(null) }} /></Field>
        <Field label="1時間の送信上限"><input type="number" min="1" max="1000" value={hourly} onChange={e => { setHourly(Number(e.target.value)); setReservationKey(null) }} /></Field>
      </div>
      <button type="button" disabled={!approved.length || !name || daily < 1 || hourly < 1} onClick={reserve}>承認済み{approved.length}件を送信予約</button>
    </fieldset>
    <h3>メール予約の状況</h3>
    {batches.length === 0 && <p>メール予約はありません。</p>}
    {batches.map(b => <article key={b.id} className="border rounded p-3 space-y-2">
      <p>{b.name} / {labels[b.status]} / 実行{b.execution_enabled ? '有効' : '無効'}</p>
      <p>上限: 24時間{b.daily_limit}件、1時間{b.hourly_limit}件</p>
      <p>{Object.entries(b.counts).map(([s, n]) => `${labels[s] ?? s}: ${n}`).join(' / ')}</p>
      {['queued', 'paused'].includes(b.status) && <div className="flex flex-wrap gap-3">
        <button type="button" className="secondary" disabled={busy || !canWrite} onClick={() => act(async () => { await api(`/approved-email-batches/${b.id}/${b.status === 'paused' ? 'resume' : 'pause'}`, 'POST') })}>{b.status === 'paused' ? '予約を再開' : '予約を一時停止'}</button>
        <button type="button" className="secondary" disabled={busy || !canWrite} onClick={() => act(async () => { await api(`/approved-email-batches/${b.id}/cancel`, 'POST') })}>未実行の予約を取り消す</button>
      </div>}
      {!!b.counts.unknown && <p role="alert">結果不明のメールは再送できません。SMTP提供元の履歴を確認してください。</p>}
    </article>)}
  </section>
}
