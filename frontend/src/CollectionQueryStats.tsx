import { useState } from 'react'
import { api, download, errorMessage } from './api'

type QueryStat = {
  keyword: string
  region: string
  search_count: number
  candidate_count: number
  known_count: number
  new_count: number
  stop_reason: string
}

export function CollectionQueryStats({ jobId }: { jobId: string }) {
  const [rows, setRows] = useState<QueryStat[] | null>(null)
  const [error, setError] = useState('')
  const load = async () => {
    if (rows !== null) return
    try { setRows(await api<QueryStat[]>(`/operations/${jobId}/collection-query-stats`)) }
    catch (caught) { setError(errorMessage(caught)) }
  }
  return <details className="mt-3" onToggle={event => { if (event.currentTarget.open) void load() }}>
    <summary>検索語×地域ごとの結果</summary>
    <button type="button" className="secondary mt-3" onClick={() => void download(`/operations/${jobId}/collection-query-stats.csv`, `collection-query-stats-${jobId}.csv`).catch(caught => setError(errorMessage(caught)))}>CSVダウンロード</button>
    {error && <p className="error">{error}</p>}
    {rows === null ? <p className="muted mt-3">読み込み中…</p> : rows.length === 0 ? <p className="muted mt-3">検索結果はまだありません。</p> : <div className="overflow-x-auto mt-3"><table><thead><tr><th>検索語</th><th>地域</th><th>検索</th><th>候補</th><th>登録済み</th><th>新規</th><th>終了理由</th></tr></thead><tbody>{rows.map(row => <tr key={`${row.keyword}-${row.region}`}><td>{row.keyword}</td><td>{row.region}</td><td>{row.search_count}</td><td>{row.candidate_count}</td><td>{row.known_count}</td><td>{row.new_count}</td><td>{row.stop_reason}</td></tr>)}</tbody></table></div>}
  </details>
}
