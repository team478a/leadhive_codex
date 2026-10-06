import { useEffect, useRef, useState } from 'react'
import { api, ApiError, errorMessage } from './api'

type Reason = { code: string; message: string; next_action: string }
type Row = { dm_ready: boolean; dm_ready_reason: string | null; company_id: string; status: string; reasons: Reason[]; destinations: { key: string; type: string; status: string; shared: boolean }[] }
type Page = { cohort_id: string; cohort_hash: string; context_hash: string; definition_version: string; aggregation_definition: string; discovered: number; offset: number; inspected: number; next_offset: number | null; started_at: string; measured_at: string; rows: Row[] }
type Summary = { dmReady: number; dmReasons: Record<string, number>; processed: number; states: Record<string, number>; destinations: Record<string, { leads: number; ready: boolean; shared: boolean }>; reasons: Record<string, { reason: Reason; count: number; states: Set<string> }>; first: string; last: string; complete: boolean }
const empty = (): Summary => ({ dmReady: 0, dmReasons: {}, processed: 0, states: { READY: 0, REVIEW: 0, HOLD: 0, BLOCKED: 0 }, destinations: {}, reasons: {}, first: '', last: '', complete: false })

export function CohortDestinationDiagnostics({ cohortId, cohortHash, discovered }: { cohortId: string; cohortHash: string; discovered: number }) {
  const [data, setData] = useState<Summary>(empty)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const generation = useRef(0)
  useEffect(() => () => { generation.current++ }, [])
  function cancel() { generation.current++; setBusy(false) }
  async function collect() {
    const current = ++generation.current
    setBusy(true); setError(''); setData(empty())
    let result = empty()
    let offset = 0
    let context = ''
    let definition = ''
    const seen = new Set<string>()
    try {
      while (true) {
        const batch = await api<Page>(`/completion-cohorts/${cohortId}/destination-diagnostics?offset=${offset}&limit=25${context ? `&expected_context_hash=${context}` : ''}`)
        if (current !== generation.current) return
        if (batch.cohort_id !== cohortId || batch.cohort_hash !== cohortHash || batch.discovered !== discovered || batch.offset !== offset || batch.inspected !== batch.rows.length || !batch.inspected || (context && context !== batch.context_hash)) throw new ApiError(409, '集計対象または営業条件が変わりました。再集計してください。')
        if (definition && definition !== `${batch.definition_version}:${batch.aggregation_definition}`) throw new ApiError(409, '診断方式が変わりました。再集計してください。')
        definition = `${batch.definition_version}:${batch.aggregation_definition}`
        context = batch.context_hash
        const next = offset + batch.inspected
        if (next > discovered || batch.next_offset !== (next < discovered ? next : null)) throw new ApiError(409, '集計範囲を確認できません。再集計してください。')
        // Pages are observations over an interval; only confirmed received pages are counted.
        result = { ...result, states: { ...result.states }, destinations: { ...result.destinations }, reasons: { ...result.reasons }, dmReasons: { ...result.dmReasons } }
        if (batch.rows.some(row => seen.has(row.company_id) || !['READY', 'REVIEW', 'HOLD', 'BLOCKED'].includes(row.status) || typeof row.dm_ready !== 'boolean') || new Set(batch.rows.map(row => row.company_id)).size !== batch.rows.length) throw new ApiError(409, '診断対象の重複または状態を確認できません。再集計してください。')
        for (const row of batch.rows) {
          seen.add(row.company_id)
          if (row.dm_ready) result.dmReady++
          else if (row.dm_ready_reason) result.dmReasons[row.dm_ready_reason] = (result.dmReasons[row.dm_ready_reason] ?? 0) + 1
          result.states[row.status] = (result.states[row.status] ?? 0) + 1
          for (const item of row.destinations) {
            const previous = result.destinations[item.key]
            result.destinations[item.key] = { leads: (previous?.leads ?? 0) + 1, ready: (previous?.ready ?? false) || item.status === 'READY', shared: (previous?.shared ?? false) || item.shared }
          }
          if (row.status !== 'READY') for (const reason of row.reasons) {
            const previous = result.reasons[reason.code]
            result.reasons[reason.code] = { reason, count: (previous?.count ?? 0) + 1, states: new Set([...(previous?.states ?? []), row.status]) }
          }
        }
        result.processed = next
        result.first ||= batch.started_at
        result.last = batch.measured_at
        result.complete = batch.next_offset === null
        result = { ...result, states: { ...result.states }, destinations: { ...result.destinations }, reasons: { ...result.reasons }, dmReasons: { ...result.dmReasons } }
        setData(result)
        if (result.complete) break
        offset = next
      }
    } catch (e) { if (current === generation.current) setError(errorMessage(e)) }
    finally { if (current === generation.current) setBusy(false) }
  }
  const destinations = Object.values(data.destinations)
  const independentReady = destinations.filter(d => d.ready && d.leads === 1 && !d.shared).length
  return <section className="mt-5" aria-label="固定リストの窓口診断">
    <h3>固定リストの窓口診断</h3>
    <p className="muted">25件ずつ保存済み情報を診断します。全件終了までは部分集計です。ページごとの取得時点の診断です。集計中の変更を含むことがあるため、一時点の固定結果ではありません。窓口READYとDM READYを分けて確認します。送信許可は別操作です。</p>
    <button className="secondary" disabled={busy} onClick={() => void collect()}>窓口診断を集計</button>
    {busy && <button className="secondary" onClick={cancel}>窓口集計を中断</button>}
    <p role="status">診断済み {data.processed} / {discovered}件 — {data.complete ? '全件集計済み' : '部分集計・未診断分あり'}</p>
    {error && <p role="alert">{error} 完了扱いにはしません。最初から再集計してください。</p>}
    {data.processed > 0 && <>
      <p>窓口準備の分類：READY {data.states.READY} / REVIEW {data.states.REVIEW} / HOLD {data.states.HOLD} / BLOCKED {data.states.BLOCKED}</p>
      <div className="grid gap-3 sm:grid-cols-3"><article className="metric"><span>診断範囲の窓口候補（重複除外）</span><strong>{destinations.length}</strong></article><article className="metric"><span>診断範囲の共通窓口</span><strong>{destinations.filter(d => d.leads > 1 || d.shared).length}</strong></article><article className="metric"><span>READYの独立窓口</span><strong>{independentReady}</strong></article></div>
      <p className="muted">独立窓口は、診断範囲内で一つのLeadにだけ結び付き、共有判定のないREADY候補です。未診断・範囲外のLeadの窓口数を推定しません。DM READYは有効な根拠付き下書き・送信者・入力値を固定した承認待ち／承認済み提案があるLeadです。</p>
      <p>診断範囲のDM READY：{data.dmReady}件 / DM READY率：{data.complete ? `${(100 * data.dmReady / discovered).toFixed(1)}%` : '未判定（部分集計）'}</p>
      <ul>{Object.entries(data.dmReasons).sort((a, b) => b[1] - a[1]).map(([reason, count]) => <li key={reason}>{reason}：{count}件</li>)}</ul>
      <h4 className="mt-4">不足・停止理由と次の作業</h4>
      <p className="muted">READY以外のLeadを理由ごとに一度だけ数えます。一つのLeadに複数理由があるため合計は候補数と一致しません。別窓口の理由も含むので、企業詳細で窓口別に確認してください。</p>
      <ul>{Object.values(data.reasons).sort((a, b) => b.count - a.count || a.reason.code.localeCompare(b.reason.code)).map(item => <li key={item.reason.code}><strong>{item.reason.message}：{item.count}件</strong>（{[...item.states].join(' / ')}）— {item.reason.next_action} <small>({item.reason.code})</small></li>)}</ul>
      <p className="muted text-xs">診断期間：{new Date(data.first).toLocaleString('ja-JP')}〜{new Date(data.last).toLocaleString('ja-JP')}。条件変更時は再集計。承認・送信時の再確認を代替しません。</p>
    </>}
  </section>
}
