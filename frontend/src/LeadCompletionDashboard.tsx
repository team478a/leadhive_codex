import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import type { Project } from './types'
import { CohortDestinationDiagnostics } from './CohortDestinationDiagnostics'

type Cohort = { id: string; name: string; discovered: number; created_at: string }
type Review = { id: string; company_id: string; started_at: string; finished_at: string | null; outcome: string | null }
type Report = {
  cohort_id: string; cohort_hash: string; name: string; discovered: number; remaining_leads: number; context_changed: boolean; can_review: boolean
  dm_ready_rate: number | null; measured_at: string; definition_version: string
  stages: { code: string; count: number | null; observed_count: number | null; conversion_rate: number | null; coverage: string }[]
  diagnostics: { states: Record<string, number>; reasons: Record<string, number>; website_registered: number; official_evidence: number; destination_candidate_leads: number; unique_candidate_destinations: number; shared_candidate_destinations: number }
  cost: { search_api_attempts: Record<string, number>; ai_operations: number; input_tokens: number | null; output_tokens: number | null; token_observations: number; review_sessions: number; completed_reviews: number; timed_reviews: number; review_seconds: number | null }
  project_query_inventory: { id: string; source: string; found: number; saved: number; enriched_leads: number; duplicate: number; excluded: number; api_attempts: number | null; saturation_candidate: boolean }[]
  review_candidates: { id: string; name: string }[]; active_review: Review | null
}
const stages: Record<string, string> = { DISCOVERED: '発見・固定対象', MATCHED: '営業条件に一致', IDENTITY_CONFIRMED: '企業・店舗の照合', OFFICIAL_SITE_CONFIRMED: '公式サイト確認', DESTINATION_FOUND: '窓口確認', CONTACT_ALLOWED: '連絡可能', DM_READY: 'DM READY', HUMAN_APPROVED: 'Human承認', SENT: '送信' }

const numberOrUnknown = (value: number | null) => value === null ? '不明' : value.toLocaleString('ja-JP')

export function LeadCompletionDashboard() {
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState('')
  const [cohorts, setCohorts] = useState<Cohort[]>([])
  const [cohortId, setCohortId] = useState('')
  const [data, setData] = useState<Report | null>(null)
  const [reviewCompany, setReviewCompany] = useState('')
  const [outcome, setOutcome] = useState('CHECKED')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  useEffect(() => {
    let active = true
    api<Project[]>('/projects').then(rows => { if (active) setProjects(rows) }).catch(e => { if (active) setError(errorMessage(e)) })
    return () => { active = false }
  }, [])
  useEffect(() => {
    let active = true
    if (projectId) api<Cohort[]>(`/projects/${projectId}/completion-cohorts`).then(rows => { if (active) setCohorts(rows) }).catch(e => { if (active) setError(errorMessage(e)) })
    return () => { active = false }
  }, [projectId, reload])
  useEffect(() => {
    let active = true
    if (cohortId) api<Report>(`/completion-cohorts/${cohortId}`).then(row => { if (active) setData(row) }).catch(e => { if (active) { setData(null); setError(errorMessage(e)) } })
    return () => { active = false }
  }, [cohortId, reload])
  async function freeze() {
    setBusy(true); setError('')
    try {
      const row = await api<Cohort>(`/projects/${projectId}/completion-cohorts`, 'POST', { name: `完成率計測 ${new Date().toLocaleString('ja-JP')}` })
      setCohortId(row.id); setData(null); setReload(n => n + 1)
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function review() {
    setBusy(true); setError('')
    try {
      if (data?.active_review) await api(`/completion-reviews/${data.active_review.id}/finish`, 'POST', { outcome })
      else await api(`/completion-cohorts/${cohortId}/reviews`, 'POST', { company_id: reviewCompany })
      setReload(n => n + 1)
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  return <section className="panel mb-6" aria-label="Lead Completion計測">
    <h2>リスト完成率</h2>
    <p className="muted mt-2">集計対象を固定して不足情報を確認します。追加収集や削除後も分母は変わりません。ここから承認・送信は行いません。</p>
    <label className="field mt-4">完成率のプロジェクト<select value={projectId} disabled={busy} onChange={e => { setProjectId(e.target.value); setCohorts([]); setCohortId(''); setData(null); setError(''); setReviewCompany('') }}><option value="">選択してください</option>{projects.map(p => <option key={p.id} value={p.id}>{p.project_name}</option>)}</select></label>
    {projectId && <><button className="secondary" disabled={busy} onClick={() => void freeze()}>現在のリストを集計対象として固定</button><label className="field mt-4">固定した集計対象<select value={cohortId} disabled={busy} onChange={e => { setCohortId(e.target.value); setData(null); setReviewCompany('') }}><option value="">選択してください</option>{cohorts.map(c => <option key={c.id} value={c.id}>{c.name}（{c.discovered}件）</option>)}</select></label></>}
    {error && <p role="alert" className="error">{error}</p>}
    {data && <>
      <div className="grid gap-3 sm:grid-cols-3"><article className="metric"><span>固定候補数</span><strong>{data.discovered}</strong></article><article className="metric"><span>段階通過を含むDM READY率</span><strong>{data.dm_ready_rate === null ? '未判定' : `${data.dm_ready_rate}%`}</strong></article><article className="metric"><span>窓口候補（重複除外）</span><strong>{data.diagnostics.unique_candidate_destinations}</strong></article></div>
      <p className="muted mt-3">この表は全段階の通過を含む記録です。現在のDM READY率と根拠付きDMのHuman承認・送信結果は、下の窓口診断を全件集計して確認してください。URL登録だけをDM完成とは扱わず、未確認の段階を推定で埋めません。</p>
      {data.context_changed && <p role="status">固定後に営業条件が変更されています。旧条件との比較には注意してください。</p>}
      <div className="company-table-wrap mt-4"><table className="company-table"><thead><tr><th>段階</th><th>前段階通過を含む確認数</th><th>単独の根拠・候補数</th><th>変換率</th></tr></thead><tbody>{data.stages.map(s => <tr key={s.code}><td>{stages[s.code]}</td><td>{numberOrUnknown(s.count)}{s.coverage === 'PARTIAL' && '（部分計測）'}</td><td>{numberOrUnknown(s.observed_count)}</td><td>{s.conversion_rate === null ? '不明' : `${s.conversion_rate}%`}</td></tr>)}</tbody></table></div>
      <p className="mt-4">公式URL登録 {data.diagnostics.website_registered} / 有効な公式照合根拠 {data.diagnostics.official_evidence} / 窓口候補のあるLead {data.diagnostics.destination_candidate_leads} / 固定範囲内の共通窓口候補 {data.diagnostics.shared_candidate_destinations}</p>
      <CohortDestinationDiagnostics key={`${data.cohort_id}:${data.measured_at}`} cohortId={data.cohort_id} cohortHash={data.cohort_hash} discovered={data.discovered} />
      <h3 className="mt-5">処理コスト・レビュー</h3>
      <p>記録済み検索HTTP試行：{Object.entries(data.cost.search_api_attempts).map(([key, value]) => `${key} ${value}回`).join(' / ') || '記録なし'} / AI操作 {data.cost.ai_operations}回</p>
      <p>記録済みtoken：入力 {numberOrUnknown(data.cost.input_tokens)} / 出力 {numberOrUnknown(data.cost.output_tokens)}（{data.cost.token_observations}操作分）</p>
      <p>レビュー {data.cost.completed_reviews} / {data.cost.review_sessions}件終了、計測時間 {numberOrUnknown(data.cost.review_seconds)}秒（{data.cost.timed_reviews}件分）</p>
      <p className="muted">料金・Cost per DM READYは不明。固定後のProject単位の部分記録です。過去の利用、他のAI経路、SDK内部retry、記録前の中断を含む総費用ではありません。</p>
      {data.can_review && <div className="mt-4">
        <p>レビュー時間の記録は、企業情報の検証・営業許可・Human承認を変更しません。終了忘れが4時間を超えた記録は時間集計から除外します。</p>
        {data.active_review ? <><p role="status">レビュー計測中：{data.review_candidates.find(c => c.id === data.active_review?.company_id)?.name ?? '削除された候補'} / 開始 {new Date(data.active_review.started_at).toLocaleString('ja-JP')}</p><label className="field">レビュー記録結果<select value={outcome} onChange={e => setOutcome(e.target.value)}><option value="CHECKED">確認作業を終了</option><option value="REVIEW">要確認として終了</option><option value="HOLD">保留として終了</option><option value="BLOCKED">禁止理由を確認して終了</option><option value="ABANDONED">時間を計上せず中断</option></select></label></> : <label className="field">レビュー時間を記録する企業<select value={reviewCompany} onChange={e => setReviewCompany(e.target.value)}><option value="">選択してください</option>{data.review_candidates.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>}
        <button className="secondary" disabled={busy || (!data.active_review && !reviewCompany)} onClick={() => void review()}>{data.active_review ? 'レビュー記録を終了' : 'レビュー時間の記録を開始'}</button>
      </div>}
      <h3 className="mt-5">検索ごとの在庫結果</h3><p className="muted">Projectの直近50件。固定対象だけの成果ではありません。新規・補完がともに0なら検索停止の検討候補です。自動停止は行いません。</p>
      <div className="company-table-wrap"><table className="company-table"><thead><tr><th>情報源</th><th>発見</th><th>新規保存</th><th>補完Lead</th><th>重複</th><th>除外</th><th>検討</th></tr></thead><tbody>{data.project_query_inventory.map(q => <tr key={q.id}><td>{q.source}</td><td>{q.found}</td><td>{q.saved}</td><td>{q.enriched_leads}</td><td>{q.duplicate}</td><td>{q.excluded}</td><td>{q.saturation_candidate ? '検索停止を検討' : '—'}</td></tr>)}</tbody></table></div>
      <button className="secondary mt-4" disabled={busy} onClick={() => setReload(n => n + 1)}>計測を再読込</button>
      <p className="muted text-xs mt-3">{data.definition_version} / {new Date(data.measured_at).toLocaleString('ja-JP')} 現在。以前の100店舗Baselineは別定義の暫定分類です。</p>
    </>}
  </section>
}
