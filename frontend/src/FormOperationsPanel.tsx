import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import { Field } from './forms'

interface Operation {
  id: string; company_name: string; form_url: string; status: string; category: string
  reason: string; expires_at: string; started_at: string | null; approval_status: string
  payload_hash: string; payload_version: number; can_reprepare: boolean
  review: { choice: string; actor_id: string; actor_label: string | null; timestamp: string } | null
}
interface Overview { counts: Record<string, number>; total: number; items: Operation[] }
interface Preview {
  preparation_hash: string; company_name: string
  proposal: { form_url: string; form_action_url?: string; subject: string; body: string; sender: Record<string, string> }
  fields: { name: string; label: string; required: boolean; value: string }[]
}
const labels: Record<string, string> = { expired: '承認期限切れ', interrupted: '事前確認が中断', blocked: '安全条件で停止', unknown: '結果不明・再送禁止', failed: '試行済み・送信前に失敗', cancelled: '取消済み', queued: '予約待ち', checking: '事前確認中', submitted: '送信完了を確認' }
const reviews: Record<string, string> = { investigating: '調査中', received: '担当者が受付を確認・再送禁止', unconfirmed: '受付を確認できず・再送禁止' }

export function FormOperationsPanel({ projectId, canWrite, refresh }: {
  projectId: string; canWrite: boolean; refresh: () => Promise<void>
}) {
  const [data, setData] = useState<Overview>({ counts: {}, total: 0, items: [] })
  const [category, setCategory] = useState('attention')
  const [offset, setOffset] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [selected, setSelected] = useState<Operation | null>(null)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [choices, setChoices] = useState<Record<string, string>>({})
  const url = `/projects/${projectId}/form-operations?category=${category}&limit=50&offset=${offset}`
  useEffect(() => {
    let live = true
    api<Overview>(url).then(next => { if (live) setData(next) }).catch(e => { if (live) setError(errorMessage(e)) })
    return () => { live = false }
  }, [url])
  async function act(fn: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try { await fn(); setData(await api<Overview>(url)); await refresh() }
    catch (e) { setError(errorMessage(e)); setPreview(null); setSelected(null) }
    finally { setBusy(false) }
  }
  return <section className="panel mt-4" aria-label="フォーム運用確認">
    <h2>フォーム運用確認</h2>
    <p>期限切れ・停止・結果不明を整理します。再準備は未送信の予約だけが対象で、新しいHuman承認が必要です。結果不明の確認記録を残しても再送はできません。</p>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    <p>{Object.entries(data.counts).map(([name, count]) => `${labels[name] ?? name}: ${count}件`).join(' / ') || '予約はありません。'}</p>
    <Field label="フォーム運用の表示対象"><select disabled={busy} value={category} onChange={e => { setCategory(e.target.value); setOffset(0); setSelected(null); setPreview(null) }}>
      <option value="attention">確認が必要な予約</option><option value="all">すべて</option>
      {Object.entries(labels).map(([name, label]) => <option key={name} value={name}>{label}</option>)}
    </select></Field>
    <button type="button" className="secondary" disabled={busy} onClick={() => act(async () => {})}>フォーム運用状況を更新</button>{' '}
    {canWrite && <button type="button" className="secondary" disabled={busy} onClick={() => act(async () => {
      const result = await api<{ processed: number; limit: number }>(`/projects/${projectId}/form-operations/reconcile`, 'POST')
      setNotice(`未送信の期限切れ・中断予約を${result.processed}件整理しました。1回最大${result.limit}件で、送信は行いません。`)
    })}>期限切れ・中断した未送信予約を整理</button>}
    <p>表示対象: {data.total}件</p>
    {data.items.map(row => <article key={row.id} className="border rounded p-3 my-3">
      <p>{row.company_name} / {labels[row.category] ?? row.category}</p><p className="break-all">{row.form_url}</p>
      <p>承認: {row.approval_status} / v{row.payload_version} / 期限: {new Date(row.expires_at).toLocaleString('ja-JP')}</p>
      {row.reason && <p>{row.reason}</p>}
      {row.can_reprepare && canWrite && <button type="button" disabled={busy} onClick={() => act(async () => {
        const next = await api<Preview>(`/approved-form-dispatches/${row.id}/reprepare-preview`)
        setSelected(row); setPreview(next)
      })}>{row.company_name}の現在の内容を再準備</button>}
      {row.status === 'unknown' && <div>
        <p role="note">送信結果自体はUNKNOWNを保持します。受付確認の記録は再送許可ではありません。</p>
        {row.review && <p>最新確認: {reviews[row.review.choice] ?? row.review.choice} / {new Date(row.review.timestamp).toLocaleString('ja-JP')} / 担当者: {row.review.actor_label ?? '削除済みユーザー'}</p>}
        {canWrite && <><Field label={`${row.company_name}の結果確認`}><select disabled={busy} value={choices[row.id] ?? 'investigating'} onChange={e => setChoices({ ...choices, [row.id]: e.target.value })}>
          {Object.entries(reviews).map(([name, label]) => <option key={name} value={name}>{label}</option>)}
        </select></Field><button type="button" disabled={busy} onClick={() => act(async () => {
          await api(`/approved-form-dispatches/${row.id}/review`, 'POST', { expected_hash: row.payload_hash, expected_version: row.payload_version, choice: choices[row.id] ?? 'investigating' })
          setNotice('担当者の確認記録を保存しました。送信結果はUNKNOWN、再送禁止のままです。')
        })}>{row.company_name}の確認記録を保存</button></>}
      </div>}
      {!row.can_reprepare && row.status !== 'unknown' && ['failed', 'blocked', 'interrupted'].includes(row.category) && <p>送信試行済み、または事前確認中です。履歴を確認してください。自動再送は行いません。</p>}
    </article>)}
    {preview && selected && <div className="panel">
      <h3>{preview.company_name}の再準備内容</h3>
      <p className="break-all">宛先: {preview.proposal.form_url} / POST先: {preview.proposal.form_action_url}</p>
      <p>送信者: {preview.proposal.sender.name} / {preview.proposal.sender.email}</p><p>{preview.proposal.subject}</p><p className="whitespace-pre-wrap break-words">{preview.proposal.body}</p>
      {preview.fields.map(field => <p className="break-words" key={field.name}>{field.label}{field.required ? '（必須）' : ''}: {field.value}</p>)}
      <button type="button" disabled={busy || !canWrite} onClick={() => act(async () => {
        const result = await api<{ id: string; status: string }>(`/approved-form-dispatches/${selected.id}/reprepare`, 'POST', {
          expected_hash: selected.payload_hash, expected_version: selected.payload_version, expected_preparation_hash: preview.preparation_hash,
        })
        setPreview(null); setSelected(null); setNotice(`承認候補 ${result.id} を確認しました（${result.status}）。承認キューで再認証・承認し、別操作で予約してください。`)
      })}>現在の内容を確認して承認候補へ追加</button>{' '}
      <button type="button" className="secondary" disabled={busy} onClick={() => { setSelected(null); setPreview(null) }}>再準備内容を閉じる</button>
    </div>}
    <button type="button" className="secondary" disabled={busy || offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>運用確認の前の50件</button>{' '}
    <button type="button" className="secondary" disabled={busy || offset + data.items.length >= data.total} onClick={() => setOffset(offset + 50)}>運用確認の次の50件</button>
  </section>
}
