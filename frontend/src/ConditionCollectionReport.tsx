import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import { CollectionFactReview, type FactCondition } from './CollectionFactReview'
import { ConditionReviewNavigation } from './ConditionReviewNavigation'
import { matchesReviewFilter } from './conditionReviewFilter'
import { conditionOutcomes as labels, conditionPriorities, conditionReasons, conditionValue } from './collectionConditionLabels'

type Report = { status: string; condition_version: number; total_candidates: number; page_counts: Record<string, number>; candidates: { company_id: string; company_name: string; state: string; conditions: (FactCondition & { id: string; priority: string; outcome: string; reason: string; evidence_url: string })[] }[] }
export function ConditionCollectionReport({ jobId, status }: { jobId: string; status: string }) {
  const [report, setReport] = useState<Report | null>(null)
  const [offset, setOffset] = useState(0)
  const [selection, setSelection] = useState({ scope: '', filter: 'ALL' })
  const scope = `${jobId}:${offset}`
  const filter = selection.scope === scope ? selection.filter : 'ALL'
  useEffect(() => { setSelection({ scope, filter: 'ALL' }) }, [scope])
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  useEffect(() => { setOffset(0) }, [jobId])
  useEffect(() => {
    let active = true
    setError(''); setReport(null)
    api<Report>(`/operations/${jobId}/collection-conditions?offset=${offset}&limit=20`).then(value => { if (active) setReport(value) }).catch(e => { if (active) setError(errorMessage(e)) })
    return () => { active = false }
  }, [jobId, status, offset, refresh])
  return <details data-condition-results><summary>この収集の条件判定</summary>
    {error && <p className="error">{error}</p>}
    {!report && !error && <p>判定結果を読み込んでいます。</p>}
    {report && <><p>確定第{report.condition_version}版・候補 {report.total_candidates}件。</p>
      <p>表示ページ内：一致 {report.page_counts.MATCH}、不一致 {report.page_counts.NO_MATCH}、確認待ち {report.page_counts.REVIEW_REQUIRED}。</p>
      <p>現在の保存済み根拠で判定します。収集中・中断したジョブは部分結果です。DM READYや送信承認とは別です。</p>
      <ConditionReviewNavigation candidates={report.candidates} filter={filter} onFilter={value => setSelection({ scope, filter: value })} />
      {report.candidates.filter(c => matchesReviewFilter(c, filter)).map(c => <details key={c.company_id} data-condition-candidate data-review-required={c.state === 'REVIEW_REQUIRED'}><summary tabIndex={0}>{c.company_name}：{labels[c.state]}</summary>{c.conditions.map(r => <div key={r.id}><p>{conditionPriorities[r.priority]}・{conditionValue(r.value)}：{labels[r.outcome] ?? '未確認'}。{conditionReasons[r.reason] ?? '根拠の追加確認が必要'}{r.evidence_url && <a href={r.evidence_url} target="_blank" rel="noopener noreferrer">根拠 ↗</a>}</p><CollectionFactReview companyId={c.company_id} condition={r} onSaved={() => setRefresh(n => n + 1)} /></div>)}</details>)}
      {!report.candidates.length && <p>この収集の保存済み候補はありません。</p>}
      <div className="flex flex-wrap gap-2"><button type="button" disabled={offset === 0} onClick={() => setOffset(n => Math.max(0, n - 20))}>前の候補</button><button type="button" disabled={offset + 20 >= report.total_candidates} onClick={() => setOffset(n => n + 20)}>次の候補</button></div>
    </>}
    <button type="button" onClick={() => setRefresh(n => n + 1)}>条件判定を更新</button>
  </details>
}
