import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errorMessage } from './api'
import { RawBenchmarkMetrics } from './RawBenchmarkMetrics'
import type { RawReport } from './rawBenchmarkTypes'
import { RawLeadReview, type RawRow } from './RawLeadReview'
import { RawPairReview } from './RawPairReview'
import { RawRunStability } from './RawRunStability'
import { RawQuickReview } from './RawQuickReview'
import { RawReviewProgress } from './RawReviewProgress'

type Benchmark = { id: string; region: string; industry: string }
type Source = { source: string; configured: boolean; pilot_allowed: boolean; reason?: string }

export function RawCollectionBenchmarkPage() {
  const [initialized, setInitialized] = useState(false)
  const [list, setList] = useState<Benchmark[]>([])
  const [sources, setSources] = useState<Source[]>([])
  const [selected, setSelected] = useState('')
  const [region, setRegion] = useState('')
  const [industry, setIndustry] = useState('')
  const [source, setSource] = useState('serper')
  const [keyword, setKeyword] = useState('')
  const [count, setCount] = useState(10)
  const [repeat, setRepeat] = useState(false)
  const [representatives, setRepresentatives] = useState(false)
  const [reviewMode, setReviewMode] = useState({ benchmarkId: '', all: false })
  const [rows, setRows] = useState<RawRow[]>([])
  const [report, setReport] = useState<RawReport | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const generation = useRef(0)
  const reload = useCallback(async (id: string) => {
    const current = ++generation.current
    setError(''); setReport(null); setRows([])
    if (!id) return
    try {
      const [r, s] = await Promise.all([api<RawReport>(`/raw-benchmarks/${id}/report`), api<RawRow[]>(`/raw-benchmarks/${id}/snapshots`)])
      if (current === generation.current) { setReport(r); setRows(s) }
    } catch (e) { if (current === generation.current) setError(errorMessage(e)) }
  }, [])
  useEffect(() => {
    let active = true
    Promise.all([api<Benchmark[]>('/raw-benchmarks'), api<Source[]>('/raw-benchmarks/sources')]).then(([v, s]) => { if (active) { setList(v); setSources(s); setInitialized(true); if (v[0]) { setSelected(v[0].id); void reload(v[0].id) } } }).catch(e => { if (active) { setInitialized(true); setError(errorMessage(e)) } })
    return () => { active = false }
  }, [reload])
  async function create() {
    setBusy(true); setError('')
    try {
      const v = await api<{ id: string }>('/raw-benchmarks', 'POST', { region, industry })
      setList(await api<Benchmark[]>('/raw-benchmarks')); setSelected(v.id); await reload(v.id)
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function collect() {
    setBusy(true); setError('')
    try { await api(`/raw-benchmarks/${selected}/queries`, 'POST', { source, keyword, requested_count: count, repeat }); await reload(selected) }
    catch (e) { await reload(selected); setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function cancel(id: string) {
    try { await api(`/raw-benchmarks/${selected}/queries/${id}/cancel`, 'POST', {}); await reload(selected) }
    catch (e) { setError(errorMessage(e)) }
  }
  if (!initialized) return <section aria-label="Raw Collection Benchmark"><p role="status">確認するリストを読み込み中…</p></section>
  return <section aria-label="Raw Collection Benchmark">
    {error && <div role="alert">{error}{selected && <button className="secondary mt-3" onClick={() => void reload(selected)}>もう一度読み込む</button>}</div>}
    {selected && !report && !error && <p role="status">候補を読み込み中…</p>}
    {report && <RawQuickReview rows={rows} region={list.find(v => v.id === selected)?.region ?? ""} industry={list.find(v => v.id === selected)?.industry ?? ""} canReview={report.can_review} allObservations={reviewMode.benchmarkId === selected && reviewMode.all} onModeChange={all => setReviewMode({ benchmarkId: selected, all })} onSaved={() => reload(selected)} />}
    {report && <RawReviewProgress report={report} loadedCount={rows.length} />}
    <details className="mt-5" open={list.length === 0}><summary>検索条件・詳しい集計を見る</summary>
    <section className="panel mt-5" aria-label="Raw Benchmark作成">
      <h3>少量Pilotを作成</h3>
      <label className="field">Benchmark地域<input value={region} maxLength={500} disabled={busy} onChange={e => setRegion(e.target.value)} /></label>
      <label className="field">Benchmark業種<input value={industry} maxLength={300} disabled={busy} onChange={e => setIndustry(e.target.value)} /></label>
      <button disabled={busy || !region.trim() || !industry.trim()} onClick={() => void create()}>空のRaw Benchmarkを作成</button>
    </section>
    <div className="field mt-5"><label htmlFor="raw-benchmark-select">Raw Benchmark</label><select id="raw-benchmark-select" value={selected} disabled={busy} onChange={e => { setSelected(e.target.value); void reload(e.target.value) }}><option value="">選択してください</option>{list.map(v => <option key={v.id} value={v.id}>{v.region} / {v.industry}</option>)}</select></div>
    {selected && <section className="panel" aria-label="Raw検索条件">
      <p>初回Queryの依頼枠は合計30候補。成功した同条件・同commitのRunだけ最大3回まで明示的に反復可能です。総Raw Hitは30を超える場合があります。自動再試行はしません。検索API費用が発生します。</p>
      <label className="field">Raw Source<select value={source} disabled={busy} onChange={e => setSource(e.target.value)}>{sources.map(s => <option key={s.source} value={s.source} disabled={!s.configured || !s.pilot_allowed}>{s.source} / {s.configured ? '設定あり' : '未設定'}{!s.pilot_allowed ? ' / 保存条件未確認' : ''}</option>)}</select></label>
      {sources.find(s => s.source === source)?.reason && <p>{sources.find(s => s.source === source)?.reason}</p>}
      <label className="field">Raw検索語<input value={keyword} maxLength={300} disabled={busy} onChange={e => setKeyword(e.target.value)} /></label>
      <label className="field">Raw依頼件数<input type="number" min={1} max={30} value={count} disabled={busy} onChange={e => setCount(Number(e.target.value))} /></label>
      <label className="checkbox-row"><input type="checkbox" checked={repeat} disabled={busy || !report?.can_review || report.repeat_limit < 3} onChange={e => setRepeat(e.target.checked)} />同じQueryを反復測定する（最大3回）</label>
      <button disabled={busy || !report?.can_review || !keyword.trim() || !Number.isInteger(count) || count < 1 || count > 30 || !sources.find(s => s.source === source)?.configured || !sources.find(s => s.source === source)?.pilot_allowed} onClick={() => void collect()}>{busy ? '収集中…' : 'このQueryだけ一次収集'}</button>
      <button className="secondary" onClick={() => void reload(selected)}>Raw結果を再読込</button>
      <p className="muted">画面を閉じても開始済み通信は取り消せません。再読込してジョブ状態を確認してください。中断は新しいQueryを追加しません。</p>
    </section>}
    {report && <><RawBenchmarkMetrics report={report} onCancel={id => void cancel(id)} /><RawRunStability report={report} /></>}
    {report && <RawPairReview rows={rows} canReview={report.can_review} onSaved={() => void reload(selected)} />}
    {selected && <section className="mt-5" aria-label="Raw結果とHuman Review"><h3>Raw結果 / Human Truth</h3>{report && rows.length === 0 && <p>Raw候補は0件です。精度は未測定です。</p>}<label className="checkbox-row"><input type="checkbox" checked={representatives} onChange={e => setRepresentatives(e.target.checked)} />未レビューRaw観測の代表候補だけを表示（店舗Identityの確定ではありません）</label>{rows.filter((row, i) => !representatives || (!row.review && rows.findIndex(r => !r.review && r.candidate_key === row.candidate_key) === i)).map(row => <RawLeadReview key={`${row.id}:${row.review?.version ?? 0}`} row={row} rows={rows} canReview={report?.can_review ?? false} onSaved={() => void reload(selected)} />)}</section>}
    </details>
  </section>
}
