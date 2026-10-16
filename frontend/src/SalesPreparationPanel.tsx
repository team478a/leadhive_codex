import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, errorMessage } from './api'
import { Field } from './forms'
import type { OperationJob } from './types'

type Item = {
  id: string; company_id: string; company_name: string; status: string; stage: string; reason: string
  channel: string; draft_id: string | null
  details: { website_candidates?: { url: string; title: string }[] }
}
type Preparation = {
  job: OperationJob; counts: Record<string, number>; item_count: number
  used_search_requests: number; used_ai_requests: number
  max_search_requests: number; max_ai_requests: number
}
type PreparationItems = { total: number; offset: number; limit: number; items: Item[] }
const names: Record<string, string> = {
  pending: '未処理', running: '処理中', ready: '文面準備済み', review: '要確認',
  blocked: '準備停止', error: 'エラー', queued: '待機中', completed: '完了',
  cancelled: '停止済み', failed: '一部失敗',
}

export function SalesPreparationPanel({ projectId }: { projectId: string }) {
  const [limit, setLimit] = useState(300)
  const [offset, setOffset] = useState(0)
  const [search, setSearch] = useState(30)
  const [ai, setAi] = useState(60)
  const [score, setScore] = useState(60)
  const [channel, setChannel] = useState('auto')
  const [drafts, setDrafts] = useState(true)
  const [jobs, setJobs] = useState<Preparation[]>([])
  const [itemPages, setItemPages] = useState<Record<string, { offset: number; total: number; items: Item[] }>>({})
  const [detailsOpen, setDetailsOpen] = useState<Record<string, boolean>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const refresh = useCallback(async () => {
    if (!projectId) { setJobs([]); return }
    setJobs(await api<Preparation[]>(`/projects/${projectId}/sales-preparation`))
  }, [projectId])
  useEffect(() => { void refresh().catch(e => setError(errorMessage(e))) }, [refresh])

  async function action(path: string, body?: unknown) {
    setBusy(true); setError('')
    try { await api(path, 'POST', body); await refresh() }
    catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false) }
  }
  function start(event: FormEvent) {
    event.preventDefault()
    void action(`/projects/${projectId}/sales-preparation`, {
      limit, offset, channel, minimum_score: score, max_search_requests: search,
      max_ai_requests: ai, generate_drafts: drafts,
    })
  }
  const active = jobs.some(({ job }) => ['queued', 'running'].includes(job.status))
  useEffect(() => {
    if (!active) return
    let mounted = true
    const timer = window.setInterval(() => {
      if (mounted) void refresh().catch(e => { if (mounted) setError(errorMessage(e)) })
    }, 5000)
    return () => { mounted = false; window.clearInterval(timer) }
  }, [active, refresh])
  async function loadItems(jobId: string, itemOffset: number) {
    try {
      const page = await api<PreparationItems>(`/sales-preparation/${jobId}/items?offset=${itemOffset}&limit=20`)
      setItemPages(current => ({ ...current, [jobId]: { offset: itemOffset, total: page.total, items: page.items } }))
    } catch (e) { setError(errorMessage(e)) }
  }
  async function retryReviewItems(result: Preparation) {
    setBusy(true); setError('')
    try {
      const companyIds: string[] = []
      for (let itemOffset = 0; itemOffset < result.item_count; itemOffset += 20) {
        const page = await api<PreparationItems>(`/sales-preparation/${result.job.id}/items?offset=${itemOffset}&limit=20`)
        companyIds.push(...page.items.filter(item => ['review', 'error'].includes(item.status)).map(item => item.company_id))
      }
      if (!companyIds.length) return
      await api(`/projects/${projectId}/sales-preparation`, 'POST', {
        company_ids: companyIds, limit: 300, channel, minimum_score: score,
        max_search_requests: search, max_ai_requests: ai, generate_drafts: drafts,
      })
      await refresh()
    } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false) }
  }
  return <section className="panel min-w-0" aria-label="営業準備">
    <h2>営業準備をまとめて実行</h2>
    <p className="muted text-sm">公式サイト照合 → Web解析 → 営業適性判定 → 連絡可否確認 → 会社別の文面作成。承認や送信は行いません。</p>
    {error && <p className="error" role="alert">{error}</p>}
    <form onSubmit={start}>
      <fieldset disabled={busy || active || !projectId}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="準備する最大件数"><input required type="number" min={1} max={300} value={limit} onChange={e => setLimit(Number(e.target.value))} /></Field>
          <Field label="先頭から除く件数"><input required type="number" min={0} max={100000} value={offset} onChange={e => setOffset(Number(e.target.value))} /></Field>
          <Field label="最低営業スコア"><input required type="number" min={0} max={100} value={score} onChange={e => setScore(Number(e.target.value))} /></Field>
          <Field label="検索回数の上限"><input required type="number" min={0} max={300} value={search} onChange={e => setSearch(Number(e.target.value))} /></Field>
          <Field label="AI回数の上限"><input required type="number" min={0} max={600} value={ai} onChange={e => setAi(Number(e.target.value))} /></Field>
        </div>
        <Field label="準備する連絡方法"><select value={channel} onChange={e => setChannel(e.target.value)}><option value="auto">メール優先、メール未登録ならフォーム</option><option value="email">メール</option><option value="form">フォーム</option></select></Field>
        <label className="flex items-center gap-2 my-3"><input type="checkbox" checked={drafts} onChange={e => setDrafts(e.target.checked)} />会社別の文面を作成する</label>
        <p className="muted text-sm">既定では登録順の先頭300件が対象です。次の300件は「先頭から除く件数」を300にします。AI判定と文面生成は別々に回数を消費します。300件すべてを判定・文面作成する場合は最大600回が必要です。上限を超える企業は要確認として残します。</p>
        <button type="submit">営業準備を開始</button>
      </fieldset>
    </form>
    <p className="muted text-sm mt-3">公式サイトの一致が曖昧な場合は候補URLを保存します。停止後の再開では完了済みの企業と消費済みの回数を引き継ぎます。文面は企業一覧の営業文面で確認できます。</p>
    {jobs.map(result => <article key={result.job.id} className="border-t mt-4 pt-4 min-w-0">
      <strong>{names[result.job.status]} · {result.job.processed_count}/{result.job.total_count}件</strong>
      <p className="muted text-sm">検索 {result.used_search_requests}/{result.max_search_requests}回 · AI {result.used_ai_requests}/{result.max_ai_requests}回</p>
      <p className="text-sm">{Object.entries(result.counts).map(([status, count]) => `${names[status]} ${count}件`).join(' / ')}</p>
      {['queued', 'running'].includes(result.job.status) && <button type="button" className="secondary" disabled={busy} onClick={() => void action(`/operations/${result.job.id}/cancel`)}>営業準備を停止</button>}
      {['cancelled', 'failed'].includes(result.job.status) && (result.counts.pending || result.counts.running) > 0 && <button type="button" disabled={busy} onClick={() => void action(`/sales-preparation/${result.job.id}/resume`)}>未処理から再開</button>}
      {result.job.id === jobs[0]?.job.id && !active && (result.counts.review || result.counts.error) > 0 && <button type="button" className="secondary" disabled={busy} onClick={() => void retryReviewItems(result)}>要確認・エラーだけ再準備（新しい回数上限）</button>}
      <details className="mt-3" onToggle={event => {
        const open = event.currentTarget.open
        setDetailsOpen(current => ({ ...current, [result.job.id]: open }))
        if (open && !itemPages[result.job.id]) void loadItems(result.job.id, 0)
      }}><summary>企業ごとの準備状況（{result.item_count}件）</summary>
        {detailsOpen[result.job.id] && <><ul className="space-y-3 mt-3">{(itemPages[result.job.id]?.items ?? []).map(item => <li key={item.id} className="break-words border-b pb-2">
          <strong>{item.company_name}</strong> · {names[item.status]}{item.channel && ` · ${item.channel === 'email' ? 'メール' : 'フォーム'}`}
          <p className="text-sm muted">{item.reason || '順番に処理します。'}</p>
          {item.details.website_candidates?.map(candidate => /^https?:\/\//.test(candidate.url) && <a className="block text-sm break-all" key={candidate.url} href={candidate.url} target="_blank" rel="noreferrer">候補: {candidate.title || candidate.url}</a>)}
        </li>)}</ul><div className="actions mt-3"><button type="button" className="secondary" disabled={busy || (itemPages[result.job.id]?.offset ?? 0) === 0} onClick={() => void loadItems(result.job.id, Math.max(0, (itemPages[result.job.id]?.offset ?? 0) - 20))}>前の20件</button><button type="button" className="secondary" disabled={busy || (itemPages[result.job.id]?.offset ?? 0) + 20 >= (itemPages[result.job.id]?.total ?? 0)} onClick={() => void loadItems(result.job.id, (itemPages[result.job.id]?.offset ?? 0) + 20)}>次の20件</button></div></>}
      </details>
    </article>)}
  </section>
}
