import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import type { Project } from './types'
import { EvaluationHistoryPanel } from './EvaluationHistoryPanel'

type State = 'ACCEPTED' | 'REJECTED' | 'DEFERRED'
type Period = { start_inclusive: string; end_exclusive: string }
type Metrics = { collection_precision: number | null; official_site_accuracy: number | null; contact_discovery_rate: number | null; misclassification_rate: number | null }
type Decision = { version: number; state: State; reason: string; actor_id: string; created_at: string; restored_from: number | null }
type Proposal = {
  id: string; version: number; state: State | 'PROPOSED'; input_hash: string; history: Decision[];
  report: { schema_version?: string; period?: Period | null; comparison: { before?: Metrics; after?: Metrics; status: string; regressions: number; changed_samples: number; improved_samples: number; evaluation_eligible_samples: number; proposal: { pattern: string; failed_samples: number; observed_diagnostic_errors?: number } } }
}
const states = { ACCEPTED: '採用', REJECTED: '却下', DEFERRED: '保留', PROPOSED: '未判断' }
const patterns: Record<string, string> = {
  CONTACT_URL_MISIDENTIFIED: '問い合わせURLの誤認', OFFICIAL_SITE_MISIDENTIFIED: '公式サイトの誤認',
  WRONG_INDUSTRY: '対象業種の誤判定', TARGET_MISCLASSIFIED: '営業対象の誤判定',
  FORM_DIAGNOSTIC_ERROR_OBSERVED: 'フォーム診断エラーの観測',
}
const statuses: Record<string, string> = { EVALUATED: '保存候補を比較済み', NO_ELIGIBLE_EVALUATION: '比較可能な保存候補なし', RUNNER_NOT_IMPLEMENTED: '比較処理は未対応' }
const localDate = (date: Date) => new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)

export function FeedbackProposalsPage({ projects }: { projects: Project[] }) {
  const [project, setProject] = useState(projects[0]?.id || '')
  const [items, setItems] = useState<Proposal[]>([])
  const [reason, setReason] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [truncated, setTruncated] = useState(false)
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [provenance, setProvenance] = useState(false)
  const [start, setStart] = useState(() => localDate(new Date(Date.now() - 7 * 86400000)))
  const [end, setEnd] = useState(() => localDate(new Date()))
  useEffect(() => {
    let active = true
    setItems([]); setError(''); setNotice(''); setReason({}); setTruncated(false); setEnabled(null); setProvenance(false)
    if (project) {
      setBusy(true)
      api<{ enabled: boolean; provenance_enabled: boolean }>(`/projects/${project}/feedback-proposals/status`)
        .then(async status => {
          if (!active) return
          setEnabled(status.enabled)
          setProvenance(status.provenance_enabled)
          if (status.enabled) {
            const data = await api<{ items: Proposal[]; truncated: boolean }>(`/projects/${project}/feedback-proposals`)
            if (active) { setItems(data.items); setTruncated(data.truncated) }
          }
        })
        .catch(e => { if (active) setError(errorMessage(e)) })
        .finally(() => { if (active) setBusy(false) })
    }
    return () => { active = false }
  }, [project])
  async function act(task: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try { await task() } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function decide(item: Proposal, state?: State, restore?: number) {
    await act(async () => {
      const updated = await api<Proposal>(`/projects/${project}/feedback-proposals/${item.id}/${restore ? 'restore' : 'decisions'}`, 'POST',
        { expected_version: item.version, reason: reason[item.id] || '', ...(restore ? { restore_version: restore } : { state }) })
      setItems(current => current.map(r => r.id === item.id ? updated : r))
      setNotice('判断を記録しました。本番ルールは変更していません。')
      setReason(current => ({ ...current, [item.id]: '' }))
    })
  }
  const validPeriod = !!start && !!end && new Date(start).getTime() < new Date(end).getTime()
  return <section aria-label="改善候補の確認">
    <p className="panel mb-5">保存済み評価から改善候補を確認します。採用しても本番ルール・送信許可は変わりません。未検証の候補は改善の仮説です。</p>
    <label className="field">改善対象プロジェクト<select disabled={busy} value={project} onChange={e => setProject(e.target.value)}>
      {projects.length === 0 && <option value="">所有プロジェクトなし</option>}
      {projects.map(p => <option key={p.id} value={p.id}>{p.project_name}</option>)}
    </select></label>
    {enabled === false && <div className="panel mt-5" role="status"><h2>改善候補の集計は未有効化です</h2><p>担当者は収集結果のOK・NGとURL修正を記録できます。集計を使うには、配置担当者がAPI側のFEEDBACK_WORKBENCH_ENABLEDをtrueに設定して再配置してください。</p><p>この設定だけで送信や本番ルールの変更は行われません。</p></div>}
    {enabled === true && <>
    {!provenance && <p className="panel mt-5">元判定の記録がOFFです。人の評価は集計できますが、元判定がない項目の正答率は未測定になります。配置担当者がFEEDBACK_PROVENANCE_ENABLEDをtrueにすると、今後の解析で元判定を記録できます。過去の記録は補いません。</p>}
    <div className="form-grid mt-5">
      <label className="field">集計開始日時<input type="datetime-local" value={start} disabled={busy} onChange={e => setStart(e.target.value)} /></label>
      <label className="field">集計終了日時<input type="datetime-local" value={end} disabled={busy} onChange={e => setEnd(e.target.value)} /></label>
    </div>
    <p>端末の時刻で指定します。終了日時は含みません。1000件を超えた場合は期間を短くしてください。</p>
    {!validPeriod && <p>終了日時は開始日時より後にしてください。</p>}
    <button disabled={!project || busy || !validPeriod} onClick={() => void act(async () => {
      const result = await api<{ event_count: number; unresolved_samples: number }>(`/projects/${project}/feedback-proposals/analyze`, 'POST', { start: new Date(start).toISOString(), end: new Date(end).toISOString() })
      const data = await api<{ items: Proposal[]; truncated: boolean }>(`/projects/${project}/feedback-proposals`)
      setItems(data.items); setTruncated(data.truncated)
      setNotice(`評価${result.event_count}件を集計しました。元判定などが不足する記録${result.unresolved_samples}件。外部APIは使っていません。`)
    })}>この期間の改善候補を集計</button>
    </>}
    {busy && <p role="status">読み込み・保存中…</p>}
    {error && <p className="error" role="alert">{error} 画面を開き直すと最新状態を読み込めます。</p>}
    {notice && <p role="status">{notice}</p>}
    {!busy && !error && enabled && items.length === 0 && <p className="panel mt-5">改善候補はありません。運用で評価を記録してから集計してください。</p>}
    {truncated && <p>最新100件を表示しています。全件の表示には未対応です。</p>}
    {enabled && <EvaluationHistoryPanel key={project} project={project} />}
    {items.map(item => { const c = item.report.comparison; return <article className="panel mt-5" key={item.id}>
      <h2>{patterns[c.proposal.pattern] || c.proposal.pattern}</h2>
      <p>集計期間：{item.report.period ? `${new Date(item.report.period.start_inclusive).toLocaleString('ja-JP')} 〜 ${new Date(item.report.period.end_exclusive).toLocaleString('ja-JP')}（終了日時を除く）` : '期間指定なし'}</p>
      <p>{states[item.state]} · 判断版 {item.version} · {statuses[c.status] || c.status}</p>
      <p className="muted">Human確認の失敗 {c.proposal.failed_samples}件{c.proposal.observed_diagnostic_errors !== undefined && ` / SYSTEM診断エラー ${c.proposal.observed_diagnostic_errors}件`}</p>
      <p>比較対象 {c.evaluation_eligible_samples}件 / 変更 {c.changed_samples}件 / 改善 {c.improved_samples}件 / 回帰 {c.regressions}件</p>
      <dl>{([['collection_precision', '対象適合率'], ['official_site_accuracy', '公式サイト正答率'], ['contact_discovery_rate', '問い合わせURL正答率'], ['misclassification_rate', '誤判定率']] as const).map(([key, label]) => {
        const percent = (value: number | null | undefined) => value == null ? '未測定' : `${(value * 100).toFixed(1)}%`
        return <div key={key}><dt>{label}</dt><dd>変更前 {percent(c.before?.[key])} → 比較後 {percent(c.after?.[key])}</dd></div>
      })}</dl>
      <p className="muted">独立評価データの認証なし。費用・Coverageは未測定。本番反映なし。</p>
      <label className="field mt-3">判断理由<textarea maxLength={2000} value={reason[item.id] || ''} onChange={e => setReason(current => ({ ...current, [item.id]: e.target.value }))} /></label>
      <div className="actions">{(['ACCEPTED', 'REJECTED', 'DEFERRED'] as const).map(state => <button key={state} disabled={busy || !reason[item.id]?.trim() || (state === 'ACCEPTED' && c.regressions > 0)} onClick={() => void decide(item, state)}>{states[state]}</button>)}</div>
      <details className="mt-3"><summary>判断履歴と出所</summary><p>解析版: {item.report.schema_version || '未記録'}</p><p className="break-all">入力hash: {item.input_hash}</p>
        {item.history.length === 0 && <p>判断履歴なし</p>}
        {item.history.map(h => <div className="mt-3" key={h.version}><p>版{h.version}: {states[h.state]} / {new Date(h.created_at).toLocaleString('ja-JP')}{h.restored_from && ` / 版${h.restored_from}から復元`}</p><p className="whitespace-pre-wrap">{h.reason}</p><p className="muted break-all">判断者: {h.actor_id}</p><button className="secondary" disabled={busy || !reason[item.id]?.trim() || h.version === item.version} onClick={() => void decide(item, undefined, h.version)}>版{h.version}の判断に戻す</button></div>)}
      </details>
    </article> })}
  </section>
}
