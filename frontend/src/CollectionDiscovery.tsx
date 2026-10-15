import { useState } from 'react'
import { api, errorMessage } from './api'

interface Hit {
  id: string; position: number; classification: string; disposition: string
  snapshot: { title: string; link: string; snippet: string; truncated: boolean }
}
interface Discovery {
  summary: { available: boolean; received_count: number | null; captured_count: number | null
    omitted_count?: number; dispositions?: Record<string, number> }
  hits: Hit[]
}
const reasons: Record<string, string> = {
  CAPTURED: '未処理（中断・障害の可能性）', SAVED: '企業候補として保存', DUPLICATE: '既存企業と重複',
  SUPPRESSED: '連絡禁止リスト', AGGREGATOR_EXCLUDED: '公式サイト以外',
  TARGET_LIMIT: '目標件数を超えたため未取込', RESPONSE_LIMIT: '応答の取込上限を超過',
  INVALID_URL: 'URLが無効', NON_COMPANY_SOURCE: 'SNS・掲載媒体などの参考情報',
  INGESTION_CONFLICT: '保存時の競合（確認待ち）',
}
const kinds: Record<string, string> = {
  OFFICIAL_SITE_CANDIDATE: '公式サイト候補（未確認）', ARTICLE: '記事候補',
  PORTAL_DIRECTORY: '掲載媒体', SOCIAL: 'SNS', JOB_PR: '求人・PR', OTHER: 'その他',
}

function safeLink(value: string) {
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password
      ? url.href : undefined
  } catch { return undefined }
}

export function CollectionDiscovery({ jobId }: { jobId: string }) {
  const [data, setData] = useState<Discovery | null>(null)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  async function load(next = 0) {
    setLoading(true); setError('')
    try {
      setData(await api<Discovery>(`/collection-jobs/${jobId}/discovery?offset=${next}&limit=20`))
      setOffset(next)
    } catch (e) { setError(errorMessage(e)) }
    finally { setLoading(false) }
  }
  return <div className="mt-3 text-sm">
    <button type="button" className="secondary" disabled={loading} onClick={() => void load()}>
      {loading ? '確認中…' : '取得候補と未取込の理由を確認'}</button>
    {error && <p role="alert" className="error">{error}</p>}
    {data && (!data.summary.available ? <p className="muted mt-2">この収集には候補記録がありません。導入前の履歴やSerper以外の収集は未計測です。</p> : <div>
      <p className="mt-2">検索応答 {data.summary.received_count} 件 / 記録 {data.summary.captured_count} 件 / 記録上限による省略 {data.summary.omitted_count ?? 0} 件</p>
      <p className="muted">検索結果の分類は正解判定や公式サイトの確認ではありません。</p>
      <div className="flex flex-wrap gap-2 my-2">{Object.entries(data.summary.dispositions ?? {}).map(([key, count]) => <span key={key} className="badge">{reasons[key] ?? key} {count}</span>)}</div>
      {data.hits.map(hit => <article key={hit.id} className="border-t py-3 break-words">
        <strong>{hit.position}. {hit.snapshot.title || '名称なし'}</strong>
        <p>{kinds[hit.classification] ?? hit.classification} · {reasons[hit.disposition] ?? hit.disposition}</p>
        {safeLink(hit.snapshot.link) && <a href={safeLink(hit.snapshot.link)} target="_blank" rel="noreferrer">取得したページを確認 ↗</a>}
        {hit.snapshot.snippet && <p className="muted mt-1">{hit.snapshot.snippet}</p>}
        {hit.snapshot.truncated && <p className="muted">長い検索結果は一部を省略して記録しています。</p>}
      </article>)}
      <div className="flex gap-2 mt-2">
        <button type="button" className="secondary" disabled={loading || offset === 0} onClick={() => void load(Math.max(0, offset - 20))}>前へ</button>
        <button type="button" className="secondary" disabled={loading || offset + 20 >= (data.summary.captured_count ?? 0)} onClick={() => void load(offset + 20)}>次へ</button>
      </div>
    </div>)}
  </div>
}
