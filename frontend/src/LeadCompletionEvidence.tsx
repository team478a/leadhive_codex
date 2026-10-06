import { useEffect, useState } from 'react'
import { api } from './api'
import { DmPreparationPanel } from './DmPreparationPanel'
import { SendabilityPanel } from './SendabilityPanel'
import { SiteIdentityReview } from './SiteIdentityReview'
import type { IdentityReview } from './SiteIdentityReview'

type Inventory = {
  expected_identity_hash: string; identity_confirmation_source: string | null; human_identity_review: IdentityReview
  identity_status: string; official_site_confidence: string; can_refresh: boolean; candidate_destination_count: number
  observations: { id: string; source: string; identity_status: string; identity_reasons: string[]; applied_fields: string[]; allowed_usage: string }[]
  destinations: { id: string; type: string; destination: string; shared: boolean; linked_lead_count: number; current: boolean }[]
}
const labels: Record<string, string> = { CONFIRMED: '照合済み', PROBABLE: '候補一致', REVIEW_REQUIRED: '要確認', DIFFERENT: '別対象' }

export function LeadCompletionEvidence({ companyId, projectId, updatedAt }: { companyId: string; projectId: string; updatedAt: string }) {
  const [data, setData] = useState<Inventory | null>(null)
  const [reload, setReload] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    api<Inventory>(`/companies/${companyId}/lead-completion`).then(value => { if (active) setData(value) }).catch(() => { if (active) setData(null) })
    return () => { active = false }
  }, [companyId, updatedAt, reload])
  async function refresh() {
    setBusy(true); setError('')
    try { await api(`/projects/${projectId}/lead-destinations/refresh`, 'POST', {}); setReload(value => value + 1) }
    catch { setError('窓口を整理できません。権限・件数・接続状態を確認してください。') }
    finally { setBusy(false) }
  }
  if (!data) return null
  return <section className="panel mt-5" aria-label="リスト完成の根拠">
    <h3>リスト完成の根拠</h3>
    <p>企業・店舗の照合：{labels[data.identity_status] ?? '未確認'} / 公式サイト：{labels[data.official_site_confidence] ?? '未確認'}</p>
    <p className="muted">窓口候補 {data.candidate_destination_count}件。候補の保存・照合は、営業許可・DM READY・送信承認を意味しません。</p>
    {data.can_refresh && <button className="secondary" disabled={busy} onClick={() => void refresh()}>プロジェクトの窓口候補を整理</button>}
    {error && <p role="alert">{error}</p>}
    <ul>{data.destinations.map(item => <li key={item.id} className="break-all">{item.type}：{item.destination} — {item.current ? '現在の候補' : '登録内容変更・要更新'}{item.shared ? ` / 共通窓口（${item.linked_lead_count}件）` : ''} / 用途・送信可否は未確認</li>)}</ul>
    {data.destinations.length === 0 && <p>保存済みの窓口候補はありません。候補整理後に表示します。</p>}
    <ul>{data.observations.map(item => <li key={item.id}>{item.source}：{labels[item.identity_status] ?? '未確認'} / 補完 {item.applied_fields.length}項目{item.allowed_usage === 'REVIEW_REQUIRED' ? ' / 利用条件要確認' : ''}</li>)}</ul>
    <p className="muted">照合根拠の種別：{data.identity_confirmation_source === 'AUTOMATIC_RULE' ? '自動ルール照合' : data.identity_confirmation_source === 'HUMAN_OBSERVED' ? 'Humanの公開情報確認' : '未確認'}</p>
    <SiteIdentityReview key={`${companyId}:${data.expected_identity_hash}`} companyId={companyId} digest={data.expected_identity_hash} review={data.human_identity_review} canReview={data.can_refresh} onSaved={() => setReload(v => v + 1)} />
    <SendabilityPanel companyId={companyId} updatedAt={updatedAt} inventoryRevision={reload} onAssessmentChanged={() => setReload(v => v + 1)} />
    <DmPreparationPanel key={`${companyId}:${updatedAt}:${reload}`} companyId={companyId} projectId={projectId} />
  </section>
}
