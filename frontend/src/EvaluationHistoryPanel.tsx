import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'

type Metrics = { collection_precision: number | null; official_site_accuracy: number | null; contact_discovery_rate: number | null; misclassification_rate: number | null; paired_samples: number; api_cost: number | null; production_processing_seconds: number | null }
type Evaluation = {
  id: string; version: number; created_at: string; created_by: string; previous_id: string | null;
  report: { period: { start_inclusive: string; end_exclusive: string }; review_events: number; evaluation_samples: number; unresolved_samples: number; checkpoint_hash: string; input_hash: string; metric_definition: string; metrics: Metrics };
  comparison: null | { before: Metrics; observed_deltas: Record<string, number | null>; limitations: string[] };
  notes: { version: number; reason: string; note: string; actor_id: string; created_at: string }[];
}
const metricNames = [['collection_precision', '対象適合率'], ['official_site_accuracy', '公式サイト正答率'], ['contact_discovery_rate', '問い合わせURL正答率'], ['misclassification_rate', '誤判定率']] as const
const reasons: Record<string, string> = { INSUFFICIENT_EVALUATION: '評価データ不足', COHORT_CHANGED: '評価対象が変わった', NO_MEASURED_GAIN: '指標の改善なし', REGRESSION: '指標が悪化', NOT_APPLIED: '本番へ未反映', OTHER: 'その他' }
const limits: Record<string, string> = { ...reasons, EVALUATION_NOT_SEALED: '独立評価データの認証なし', VERSION_UNKNOWN: '元判定の版が不足', DATASET_KIND_CHANGED: 'データ種別が異なる' }
const percent = (v: number | null | undefined) => v == null ? '未測定' : `${(v * 100).toFixed(1)}%`
const localDate = (date: Date) => new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)

export function EvaluationHistoryPanel({ project }: { project: string }) {
  const [items, setItems] = useState<Evaluation[]>([])
  const [start, setStart] = useState(() => localDate(new Date(Date.now() - 7 * 86400000)))
  const [end, setEnd] = useState(() => localDate(new Date()))
  const [previous, setPrevious] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [truncated, setTruncated] = useState(false)
  const [notes, setNotes] = useState<Record<string, { reason: string; note: string }>>({})
  useEffect(() => {
    let active = true
    setItems([]); setPrevious(''); setError(''); setNotice(''); setNotes({}); setTruncated(false)
    if (project) {
      setBusy(true)
      api<{ items: Evaluation[]; truncated: boolean }>(`/projects/${project}/feedback-evaluations`)
        .then(data => { if (active) { setItems(data.items); setTruncated(data.truncated) } })
        .catch(e => { if (active) setError(errorMessage(e)) })
        .finally(() => { if (active) setBusy(false) })
    }
    return () => { active = false }
  }, [project])
  async function act(fn: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try { await fn() } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  const valid = !!start && !!end && new Date(start).getTime() < new Date(end).getTime()
  return <section aria-label="評価履歴" className="panel mt-5">
    <h2>評価履歴</h2>
    <p>期間内の保存済みレビューを記録します。終了日時は含みません。数値の上昇だけで本番改善とは判断しません。</p>
    <div className="form-grid">
      <label className="field">評価開始日時<input type="datetime-local" value={start} disabled={busy} onChange={e => setStart(e.target.value)} /></label>
      <label className="field">評価終了日時<input type="datetime-local" value={end} disabled={busy} onChange={e => setEnd(e.target.value)} /></label>
    </div>
    <label className="field">比較する評価<select value={previous} disabled={busy} onChange={e => setPrevious(e.target.value)}>
      <option value="">比較せず保存</option>
      {items.map(item => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString('ja-JP')} / 評価{item.report.evaluation_samples}件</option>)}
    </select></label>
    <button disabled={busy || !project || !valid} onClick={() => void act(async () => {
      const item = await api<Evaluation>(`/projects/${project}/feedback-evaluations`, 'POST', { start: new Date(start).toISOString(), end: new Date(end).toISOString(), previous_id: previous || null })
      setItems(current => [item, ...current.filter(r => r.id !== item.id)].slice(0, 100))
      setNotice('評価を保存しました。外部API・本番ルール変更はありません。')
    })}>この期間の評価を保存</button>
    {!valid && <p>終了日時は開始日時より後にしてください。</p>}
    {busy && <p role="status">評価履歴を読み込み・保存中…</p>}
    {error && <p role="alert" className="error">{error} 画面を開き直して再読み込みしてください。</p>}
    {notice && <p role="status">{notice}</p>}
    {!busy && !error && items.length === 0 && <p>評価履歴はありません。データが0件の期間も記録できます。</p>}
    {truncated && <p>最新100件を表示しています。</p>}
    {items.map(item => <article key={item.id} className="panel mt-5">
      <h3>{new Date(item.report.period.start_inclusive).toLocaleString('ja-JP')} 〜 {new Date(item.report.period.end_exclusive).toLocaleString('ja-JP')}</h3>
      <p>期間内レビュー {item.report.review_events}件 / 固定評価区分 {item.report.evaluation_samples}件 / 判定不足 {item.report.unresolved_samples}件 / 正解・元判定の両方あり {item.report.metrics.paired_samples}件</p>
      <dl>{metricNames.map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{item.comparison ? `前回 ${percent(item.comparison.before[key])} → 今回 ` : ''}{percent(item.report.metrics[key])}{item.comparison && ` / 差 ${item.comparison.observed_deltas[key] == null ? '未測定' : `${(item.comparison.observed_deltas[key]! * 100).toFixed(1)}pt`}`}</dd></div>)}</dl>
      <p>API費用・処理時間・Coverage：未測定。本番改善の実証なし。</p>
      {item.comparison && <p>比較の制限：{item.comparison.limitations.map(r => limits[r] || r).join('、')}</p>}
      <label className="field">改善を確認できない理由<select disabled={busy} value={notes[item.id]?.reason || 'INSUFFICIENT_EVALUATION'} onChange={e => setNotes(current => ({ ...current, [item.id]: { reason: e.target.value, note: current[item.id]?.note || '' } }))}>
        {Object.entries(reasons).map(([key, value]) => <option key={key} value={key}>{value}</option>)}
      </select></label>
      <label className="field">理由の説明<textarea disabled={busy} maxLength={2000} value={notes[item.id]?.note || ''} onChange={e => setNotes(current => ({ ...current, [item.id]: { reason: current[item.id]?.reason || 'INSUFFICIENT_EVALUATION', note: e.target.value } }))} /></label>
      <button disabled={busy || !notes[item.id]?.note.trim()} onClick={() => void act(async () => {
        const updated = await api<Evaluation>(`/projects/${project}/feedback-evaluations/${item.id}/notes`, 'POST', { expected_version: item.version, ...notes[item.id] })
        setItems(current => current.map(r => r.id === updated.id ? updated : r))
        setNotes(current => ({ ...current, [item.id]: { reason: 'INSUFFICIENT_EVALUATION', note: '' } }))
        setNotice('原因の説明を追記しました。測定値やHuman正解は変更していません。')
      })}>理由を記録</button>
      <details className="mt-3"><summary>評価の出所と理由の履歴</summary>
        <p className="break-all">入力hash: {item.report.input_hash}</p><p className="break-all">評価hash: {item.report.checkpoint_hash}</p><p>指標定義: {item.report.metric_definition}</p>
        <p className="break-all">記録者: {item.created_by} / {new Date(item.created_at).toLocaleString('ja-JP')}</p>
        {item.notes.length === 0 && <p>理由の記録なし</p>}
        {item.notes.map(note => <div key={note.version}><p>版{note.version}: {reasons[note.reason] || note.reason}</p><p className="whitespace-pre-wrap">{note.note}</p><p className="break-all">{note.actor_id} / {new Date(note.created_at).toLocaleString('ja-JP')}</p></div>)}
        <p>原因の説明は運用者の判断です。Human正解ラベルとは別に保存します。</p>
      </details>
    </article>)}
  </section>
}
