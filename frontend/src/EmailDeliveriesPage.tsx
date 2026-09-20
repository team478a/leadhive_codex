import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import type { EmailDeliveryList, Project } from './types'

const statusName = {
  queued: '送信待ち', running: '送信中', sent: '送信済み', failed: '失敗', cancelled: 'キャンセル済み',
}

export function EmailDeliveriesPage({ projects }: { projects: Project[] }) {
  const [projectId, setProjectId] = useState(projects[0]?.id ?? '')
  const [data, setData] = useState<EmailDeliveryList | null>(null)
  const [error, setError] = useState('')
  const load = useCallback(async () => {
    if (!projectId) { setData(null); return }
    setError('')
    try { setData(await api<EmailDeliveryList>(`/projects/${projectId}/email-deliveries`)) }
    catch (e) { setError(errorMessage(e)) }
  }, [projectId])
  useEffect(() => { void load() }, [load])
  if (projects.length === 0) return <section className="panel empty"><h2>プロジェクトがありません</h2><p className="muted">メール配信状況はプロジェクトごとに確認します。</p></section>
  return <section className="panel" aria-label="メール配信状況"><div className="flex flex-wrap items-end justify-between gap-3"><div><h2>メール配信状況</h2><p className="muted mt-2 text-sm">最近の送信予約と送信結果を確認します。上限・間隔に達したメールは送信待ちのまま保持されます。</p></div><label className="field min-w-56">プロジェクト<select value={projectId} onChange={e => setProjectId(e.target.value)}>{projects.map(project => <option value={project.id} key={project.id}>{project.project_name}</option>)}</select></label></div>
    {error && <p className="error mt-4" role="alert">{error}</p>}
    {!data ? <p className="muted mt-5" role="status">読み込み中…</p> : <><div className="grid gap-3 mt-5 sm:grid-cols-2 xl:grid-cols-5">{[['送信待ち', data.queued_count], ['送信中', data.running_count], ['送信済み', data.sent_count], ['失敗', data.failed_count], ['キャンセル', data.cancelled_count]].map(([label, count]) => <div className="metric-card" key={String(label)}><p className="muted text-sm">{label}</p><strong>{count}</strong></div>)}</div>
      <div className="mt-6 space-y-3">{data.items.length === 0 ? <p className="muted">このプロジェクトのメール送信履歴はありません。</p> : data.items.map(item => <article className="job-row" key={item.id}><div><strong>{item.company_name}</strong><p className="muted text-sm">{item.recipient_email} / {item.subject}</p><p className="muted text-xs">予約：{new Date(item.scheduled_for).toLocaleString('ja-JP')}{item.sent_at ? ` / 送信：${new Date(item.sent_at).toLocaleString('ja-JP')}` : ''}</p>{item.error_message && <p className="error text-sm">{item.error_message}</p>}</div><span className="badge">{statusName[item.status]}</span></article>)}</div></>}
  </section>
}
