import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import type { Project } from './types'

type State = 'ACCEPTED' | 'REJECTED' | 'DEFERRED'
type Metrics = { collection_precision: number | null; official_site_accuracy: number | null; contact_discovery_rate: number | null; misclassification_rate: number | null }
type Decision = { version: number; state: State; reason: string; actor_id: string; created_at: string; restored_from: number | null }
type Proposal = {
  id: string; version: number; state: State | 'PROPOSED'; input_hash: string; history: Decision[];
  report: { schema_version?: string; comparison: { before?: Metrics; after?: Metrics; status: string; regressions: number; changed_samples: number; improved_samples: number; evaluation_eligible_samples: number; proposal: { pattern: string; failed_samples: number; observed_diagnostic_errors?: number } } }
}
const states = { ACCEPTED: '採用', REJECTED: '却下', DEFERRED: '保留', PROPOSED: '未判断' }
const patterns: Record<string, string> = {
  CONTACT_URL_MISIDENTIFIED: '問い合わせURLの誤認', OFFICIAL_SITE_MISIDENTIFIED: '公式サイトの誤認',
  WRONG_INDUSTRY: '対象業種の誤判定', TARGET_MISCLASSIFIED: '営業対象の誤判定',
  FORM_DIAGNOSTIC_ERROR_OBSERVED: 'フォーム診断エラーの観測',
}
const statuses: Record<string, string> = { EVALUATED: '保存候補を比較済み', NO_ELIGIBLE_EVALUATION: '比較可能な保存候補なし', RUNNER_NOT_IMPLEMENTED: '比較処理は未対応' }

export function FeedbackProposalsPage({ projects }: { projects: Project[] }) {
  const [project, setProject] = useState(projects[0]?.id || '')
  const [items, setItems] = useState<Proposal[]>([])
  const [reason, setReason] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [truncated, setTruncated] = useState(false)
  useEffect(() => {
    let active = true
    setItems([]); setError(''); setNotice(''); setReason({}); setTruncated(false)
    if (project) {
      setBusy(true)
      api<{ items: Proposal[]; truncated: boolean }>(`/projects/${project}/feedback-proposals`)
        .then(data => { if (active) { setItems(data.items); setTruncated(data.truncated) } })
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
  return <section aria-label="改善候補の確認">
    <p className="panel mb-5">保存済み評価から改善候補を確認します。採用しても本番ルール・送信許可は変わりません。未検証の候補は改善の仮説です。</p>
    <label className="field">改善対象プロジェクト<select disabled={busy} value={project} onChange={e => setProject(e.target.value)}>
      {projects.length === 0 && <option value="">所有プロジェクトなし</option>}
      {projects.map(p => <option key={p.id} value={p.id}>{p.project_name}</option>)}
    </select></label>
    <button disabled={!project || busy} onClick={() => void act(async () => {
      const result = await api<{ event_count: number; unresolved_samples: number }>(`/projects/${project}/feedback-proposals/analyze`, 'POST')
      const data = await api<{ items: Proposal[]; truncated: boolean }>(`/projects/${project}/feedback-proposals`)
      setItems(data.items); setTruncated(data.truncated)
      setNotice(`評価${result.event_count}件を集計しました。元判定などが不足する記録${result.unresolved_samples}件。外部APIは使っていません。`)
    })}>保存済み評価を集計</button>
    {busy && <p role="status">読み込み・保存中…</p>}
    {error && <p className="error" role="alert">{error} 画面を開き直すと最新状態を読み込めます。</p>}
    {notice && <p role="status">{notice}</p>}
    {!busy && !error && items.length === 0 && <p className="panel mt-5">改善候補はありません。運用で評価を記録してから集計してください。</p>}
    {truncated && <p>最新100件を表示しています。全件の表示には未対応です。</p>}
    {items.map(item => { const c = item.report.comparison; return <article className="panel mt-5" key={item.id}>
      <h2>{patterns[c.proposal.pattern] || c.proposal.pattern}</h2>
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
