import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import type { Dashboard } from './types'

const labels: Record<string, string> = {
  target: '営業対象', approached: 'アプローチ済', replied: '返信あり',
  meeting: '商談', won: '成約', unreviewed: '未確認', lost: '失注', excluded: '対象外',
}

const operationLabels: Record<string, string> = {
  collect_search: '検索収集', web_analysis: 'Web解析', ai_analysis: 'AI判定',
}
const operationStatuses: Record<string, string> = {
  queued: '待機中', running: '実行中', completed: '完了', failed: '失敗', cancelled: 'キャンセル',
}

export function DashboardPage({ onUnreadChange }: { onUnreadChange: (count: number) => void }) {
  const [data, setData] = useState<Dashboard | null>(null)
  const [error, setError] = useState('')
  const load = useCallback(async () => {
    const next = await api<Dashboard>('/dashboard')
    setData(next); onUnreadChange(next.unread_operation_failures)
  }, [onUnreadChange])
  useEffect(() => { load().catch(e => setError(errorMessage(e))) }, [load])
  async function acknowledge(id: string) {
    try { await api(`/operations/${id}/acknowledge`, 'POST'); await load() }
    catch (e) { setError(errorMessage(e)) }
  }
  if (error) return <p className="error" role="alert">{error}</p>
  if (!data) return <p role="status">読み込み中…</p>
  const cards = [
    ['総企業数', data.total_companies], ['Aランク', data.ranks.A ?? 0],
    ['Bランク', data.ranks.B ?? 0], ['Cランク', data.ranks.C ?? 0],
    ['対象外', data.ranks['対象外'] ?? 0], ['営業対象', data.statuses.target ?? 0],
    ['アプローチ済', data.statuses.approached ?? 0], ['返信あり', data.statuses.replied ?? 0],
    ['商談', data.statuses.meeting ?? 0], ['成約', data.statuses.won ?? 0],
    ['フォロー期限超過', data.overdue_followups], ['本日フォロー', data.due_today_followups],
  ] as const
  return <>
    {data.unread_operation_failures > 0 && <p className="error" role="alert">
      未確認のバックグラウンド処理失敗が {data.unread_operation_failures} 件あります。
    </p>}
    <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">{cards.map(([label, value]) =>
      <article className="metric" key={label}><span>{label}</span><strong>{value}</strong></article>)}</section>
    <section className="panel mt-6"><h2>直近の収集結果</h2>
      {data.recent_jobs.length === 0 ? <p className="muted mt-4">収集履歴はまだありません。</p> :
        data.recent_jobs.map(job => <article className="job-row" key={job.id}>
          <div><strong>{job.keyword || job.source}</strong><p className="muted text-sm">{job.region || '地域指定なし'}</p></div>
          <div className="text-right text-sm"><span className="badge">{job.status === 'completed' ? '完了' : job.status === 'failed' ? '失敗' : '実行中'}</span>
            <p className="muted mt-2">保存 {job.saved_count} / 発見 {job.found_count}</p></div>
        </article>)}</section>
    <section className="panel mt-6"><div className="flex flex-wrap items-center justify-between gap-3">
      <h2>バックグラウンド処理監視</h2>
      <p className="muted text-sm">{Object.entries(data.operation_statuses).map(([key, value]) => `${operationStatuses[key] ?? key} ${value}`).join(' / ') || '処理なし'}</p>
    </div>
      {data.recent_operations.length === 0 ? <p className="muted mt-4">処理履歴はまだありません。</p> :
        data.recent_operations.map(job => <article className="job-row" key={job.id}>
          <div><strong>{operationLabels[job.operation_type]}</strong>
            <p className="muted text-sm">{job.processed_count} / {job.total_count} 件・試行 {job.attempt_count}</p>
            {job.error_message && <p className="error mt-2 mb-0">{job.error_message}</p>}</div>
          <div className="text-right"><span className="badge">{operationStatuses[job.status]}</span>
            {job.status === 'failed' && !job.acknowledged_at && <button type="button" className="secondary mt-2"
              onClick={() => void acknowledge(job.id)}>確認済みにする</button>}</div>
        </article>)}</section>
    {Object.keys(data.statuses).length > 0 && <p className="muted mt-4 text-sm">営業状況：{Object.entries(data.statuses).map(([key, value]) => `${labels[key] ?? key} ${value}`).join(' / ')}</p>}
  </>
}
