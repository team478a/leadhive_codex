import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import type { OperationJob } from './types'

interface Hit {
  id: string; position: number; classification: string; disposition: string
  snapshot: { title: string; link: string; snippet: string; truncated: boolean }
}
interface ArticleEntry {
  id: string; entry_order: number; name: string; link_url: string; status: string
  reasons: string[]; disposition: string; company_id: string | null
}
interface ArticleExtraction {
  id: string; article_url: string; final_url: string; status: string; page_kind: string
  pattern: string; entry_count: number; linked_count: number; name_only_count: number
  rejected_count: number; warnings: string[]; entries: ArticleEntry[]
}
interface Discovery {
  summary: { available: boolean; received_count: number | null; captured_count: number | null
    omitted_count?: number; dispositions?: Record<string, number>; classifications?: Record<string, number> }
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
const entryStatuses: Record<string, string> = { LINKED: 'リンクあり', NAME_ONLY: 'サイト未特定', REJECTED: '除外' }

function safeLink(value: string) {
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password
      ? url.href : undefined
  } catch { return undefined }
}

export function CollectionDiscovery({ jobId, projectId, sourceOperationId, extractionJob, onStarted }: {
  jobId: string; projectId: string; sourceOperationId?: string
  extractionJob?: OperationJob; onStarted: () => void
}) {
  const [data, setData] = useState<Discovery | null>(null)
  const [extractions, setExtractions] = useState<ArticleExtraction[]>([])
  const [expanded, setExpanded] = useState(false)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(false)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')
  const extractionActive = Boolean(extractionJob && ['queued', 'running'].includes(extractionJob.status))
  async function load(next = 0) {
    setLoading(true); setError('')
    try {
      setData(await api<Discovery>(`/collection-jobs/${jobId}/discovery?offset=${next}&limit=20`))
      setOffset(next)
    } catch (e) { setError(errorMessage(e)) }
    finally { setLoading(false) }
  }
  const loadExtractions = useCallback(async () => {
    try {
      const result = await api<{ items: ArticleExtraction[] }>(`/collection-jobs/${jobId}/article-extractions?offset=0&limit=20`)
      setExtractions(result.items)
    } catch (e) { setError(errorMessage(e)) }
  }, [jobId])
  useEffect(() => {
    if (!expanded) return
    void loadExtractions()
    if (!extractionActive) return
    const timer = window.setInterval(() => void loadExtractions(), 5000)
    return () => window.clearInterval(timer)
  }, [expanded, extractionActive, loadExtractions])
  async function startExtraction() {
    if (!sourceOperationId) return
    setStarting(true); setError('')
    try {
      await api(`/projects/${projectId}/operations`, 'POST', {
        operation_type: 'extract_articles', source_operation_ids: [sourceOperationId],
        article_limit: 20, dry_run: false,
      })
      setExpanded(true)
      onStarted()
    } catch (e) { setError(errorMessage(e)) }
    finally { setStarting(false) }
  }
  const articleCount = data?.summary.classifications?.ARTICLE ?? 0
  const active = extractionActive
  return <div className="mt-3 text-sm">
    <button type="button" className="secondary" disabled={loading} onClick={() => void load()}>
      {loading ? '確認中…' : '取得候補と未取込の理由を確認'}</button>
    {error && <p role="alert" className="error">{error}</p>}
    {data && (!data.summary.available ? <p className="muted mt-2">この収集には候補記録がありません。導入前の履歴やSerper以外の収集は未計測です。</p> : <div>
      <p className="mt-2">検索応答 {data.summary.received_count} 件 / 記録 {data.summary.captured_count} 件 / 記録上限による省略 {data.summary.omitted_count ?? 0} 件</p>
      <p className="muted">検索結果の分類は正解判定や公式サイトの確認ではありません。</p>
      <div className="flex flex-wrap gap-2 my-2">{Object.entries(data.summary.dispositions ?? {}).map(([key, count]) => <span key={key} className="badge">{reasons[key] ?? key} {count}</span>)}</div>
      {articleCount > 0 && sourceOperationId && <section className="border rounded p-3 my-3" aria-label="記事から企業を抽出">
        <p>記事候補 {articleCount} 件。記事本文の取得・抽出を行います（検索API・AI・送信は利用しません）。</p>
        <button type="button" className={active ? 'secondary analysis-active' : 'secondary'} disabled={starting || !!active}
          aria-busy={starting || !!active} onClick={() => void startExtraction()}>
          {starting ? '登録中…' : active ? `記事抽出中 ${extractionJob?.processed_count ?? 0} / ${extractionJob?.total_count ?? 0}` : '記事から企業を抽出（最大20記事）'}
        </button>
        {extractionJob && <p className="muted mt-2">状態：{extractionJob.status === 'completed' ? '完了' : extractionJob.status === 'failed' ? '失敗' : extractionJob.status === 'cancelled' ? 'キャンセル' : '処理中'} / 新規保存 {extractionJob.article_saved_count ?? 0} 社 / 成功 {extractionJob.success_count}・失敗 {extractionJob.failed_count}</p>}
        {(extractionJob || active) && <button type="button" className="secondary mt-2" onClick={() => setExpanded(value => !value)}>{expanded ? '抽出結果を閉じる' : '記事ごとの抽出結果を表示'}</button>}
        {expanded && <div className="mt-3 space-y-3">{extractions.map(item => <article key={item.id} className="border-t pt-3 break-words">
          <strong>{item.article_url}</strong>
          <p>取得 {item.status} / パターン {item.pattern || '—'} / 抽出 {item.entry_count} 件（リンクあり {item.linked_count}・名称のみ {item.name_only_count}・除外 {item.rejected_count}）</p>
          {item.warnings.map(warning => <p className="muted" key={warning}>{warning}</p>)}
          <ul className="list-disc pl-5">{item.entries.map(entry => <li key={entry.id}>
            {entry.name} — {entryStatuses[entry.status] ?? entry.status} / {reasons[entry.disposition] ?? entry.disposition}
            {entry.status === 'NAME_ONLY' && <span className="muted">（サイト未特定。公式サイト検索は未実装）</span>}
            {safeLink(entry.link_url) && <> / <a href={safeLink(entry.link_url)} target="_blank" rel="noreferrer">リンク確認 ↗</a></>}
          </li>)}</ul>
        </article>)}</div>}
      </section>}
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
