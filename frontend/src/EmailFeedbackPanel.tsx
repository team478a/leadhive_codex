import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import { Field } from './forms'

interface Health { paused: boolean; reason: string; stopped_at: string | null; counts: Record<string, number> }
interface Event { id: string; kind: string; source: string; recipient: string; occurred_at: string }
const names: Record<string, string> = { attempted: '送信試行', unknown: '結果不明', delivered: '到達通知', hard_bounce: '恒久不達', soft_bounce: '一時不達', complaint: '苦情', unsubscribe: '配信停止' }

export function EmailFeedbackPanel({ projectId, canWrite, isOwner, deliveries }: { projectId: string; canWrite: boolean; isOwner: boolean; deliveries: { id: string; company_name: string; recipient_email: string; status: string }[] }) {
  const [health, setHealth] = useState<Health | null>(null)
  const [events, setEvents] = useState<Event[]>([])
  const [deliveryId, setDeliveryId] = useState('')
  const [recipient, setRecipient] = useState('')
  const [kind, setKind] = useState('hard_bounce')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [eventKey, setEventKey] = useState<string | null>(null)
  const [occurredAt, setOccurredAt] = useState<string | null>(null)
  const [showEntry, setShowEntry] = useState(false)
  const load = useCallback(async () => {
    const [h, e] = await Promise.all([api<Health>(`/projects/${projectId}/email-health`), api<Event[]>(`/projects/${projectId}/email-feedback`)])
    setHealth(h); setEvents(e)
  }, [projectId])
  useEffect(() => { load().catch(e => setError(errorMessage(e))) }, [load])
  async function act(action: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try { await action(); await load() } catch (e) { setError(errorMessage(e)) } finally { setBusy(false); setPassword('') }
  }
  function changed() { setEventKey(null); setOccurredAt(null) }
  return <section className="panel mt-5 space-y-4" aria-label="配信結果と安全停止">
    <h2>配信結果と安全停止</h2>
    <p className="muted">SMTP受付と相手サーバーへの到達を分けて記録します。到達通知は開封や読了を意味しません。直近24時間（停止解除後は解除以降）の苦情1件、結果不明3件、または試行10件以上で恒久不達3件以上かつ5%以上を検出すると停止します。</p>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {health && <><p role="status">{health.paused ? `安全停止中: ${health.reason}` : '安全停止なし（送信の有効化とは別です）'}</p>
      <div className="flex flex-wrap gap-3">{Object.entries(health.counts).map(([k, v]) => <span key={k}>{names[k]}: {v}</span>)}</div></>}
    <button className="secondary" disabled={busy} onClick={() => act(load)}>配信結果を更新</button>
    {canWrite && <div><button type="button" className="secondary" aria-expanded={showEntry} onClick={() => setShowEntry(v => !v)}>確認済みの配信結果を登録</button>{showEntry && <fieldset disabled={busy} className="space-y-3 mt-3">
      <p>配信サービスの履歴を確認して登録してください。誤登録でも記録は削除できません。不達・苦情・配信停止は、そのメールアドレスへの連絡を禁止します。</p>
      <Field label="結果を記録するメール"><select value={deliveryId} onChange={e => { setDeliveryId(e.target.value); setRecipient(deliveries.find(d => d.id === e.target.value)?.recipient_email ?? ''); changed() }}><option value="">送信履歴から選択</option>{deliveries.filter(d => ['sent', 'unknown', 'running', 'failed'].includes(d.status)).map(d => <option key={d.id} value={d.id}>{d.company_name} / {d.recipient_email}</option>)}</select></Field>
      <Field label="確認した宛先メール"><input type="email" value={recipient} onChange={e => { setRecipient(e.target.value); changed() }} /></Field>
      <Field label="確認した配信結果"><select value={kind} onChange={e => { setKind(e.target.value); changed() }}>{Object.entries(names).filter(([k]) => !['attempted', 'unknown'].includes(k)).map(([k, n]) => <option key={k} value={k}>{n}</option>)}</select></Field>
      <button disabled={!deliveryId || !recipient} onClick={() => {
        const key = eventKey ?? crypto.randomUUID(), date = occurredAt ?? new Date().toISOString(); setEventKey(key); setOccurredAt(date)
        void act(async () => { await api(`/projects/${projectId}/email-feedback`, 'POST', { event_key: key, delivery_id: deliveryId, recipient, kind, occurred_at: date }); setNotice('結果を記録しました。送信・再送は行っていません。'); setEventKey(null); setOccurredAt(null) })
      }}>確認結果を記録</button>
    </fieldset>}</div>}
    {health?.paused && isOwner && <fieldset disabled={busy} className="space-y-3">
      <p>停止理由・SMTP履歴・対象を確認した所有者だけが停止を解除できます。連絡禁止、結果不明、失効済み承認は解除しません。各メール予約は別途再開してください。</p>
      <Field label="安全停止解除用ログインパスワード"><input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></Field>
      <button disabled={!password} onClick={() => act(async () => { await api(`/projects/${projectId}/email-health/review`, 'POST', { password, expected_stopped_at: health.stopped_at }); setNotice('安全停止を解除しました。メール予約は一時停止のままです。') })}>原因確認済みとして安全停止を解除</button>
    </fieldset>}
    <h3>最新50件の配信結果</h3>
    {events.length === 0 && <p>配信結果の通知はありません。</p>}
    {events.map(e => <article className="border rounded p-3 break-words" key={e.id}>{names[e.kind]} / {e.recipient} / {e.source === 'HUMAN' ? '人の確認' : '署名付き通知'} / {new Date(e.occurred_at).toLocaleString('ja-JP')}</article>)}
  </section>
}
