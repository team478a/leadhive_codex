import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import { DestinationChoice, type HumanDestinationChoice } from './DestinationChoice'

type Reason = { code: string; message: string; next_action: string }
type Review = { state: string; version: number; purpose: string; scope: string; source_url: string; evidence_excerpt: string; reviewed_by_user_id: string | null; created_at: string | null; expires_at: string | null }
type Destination = { id: string | null; type: string; destination: string; purpose: string; status: string; reasons: Reason[]; core_permission: string; expected_hash: string | null; review: Review }
type Assessment = {
  company_id: string; definition_version: string; evaluated_at: string; status: string; can_review: boolean
  reasons: Reason[]; live_destination_checked: boolean
  recommended_destination: { type: string; destination: string; purpose: string } | null; destination_selection_required: boolean
  human_choice: HumanDestinationChoice
  destinations: Destination[]
}
const states: Record<string, string> = { READY: '準備候補', REVIEW: '要確認', HOLD: '保留', BLOCKED: '利用不可' }

export function SendabilityPanel({ companyId, updatedAt, inventoryRevision }: { companyId: string; updatedAt: string; inventoryRevision: number }) {
  const [data, setData] = useState<Assessment | null>(null)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let active = true
    api<Assessment>(`/companies/${companyId}/sendability`).then(value => {
      if (active) { setData(value); setError('') }
    }).catch(e => { if (active) { setData(null); setError(errorMessage(e)) } })
    return () => { active = false }
  }, [companyId, updatedAt, inventoryRevision, revision])
  return <section className="mt-5" aria-label="窓口の利用可否と理由">
    <h3>窓口の利用可否と理由</h3>
    <p className="muted">保存済み情報からの準備診断です。現在のサイトへの接続、送信承認、送信は行いません。READYは窓口の準備候補です。用途確認は送信承認とは別で、7日で失効し、対象情報の変更でも再確認が必要になります。</p>
    {error && <p role="alert">判定を取得できません：{error}</p>}
    {data?.company_id === companyId && <>
      <p role="status">判定：{states[data.status] ?? '未判定'}（{data.status}）</p>
      <p className="muted">{data.definition_version} / {new Date(data.evaluated_at).toLocaleString('ja-JP')} 現在。DM READY・送信許可とは別の判定です。</p>
      <p className="muted">理由一覧には、利用できない別候補の理由も含まれます。各窓口の判定を確認してください。</p>
      {data.recommended_destination && <p className="break-all">推奨準備窓口：{data.recommended_destination.type} / {data.recommended_destination.destination} / 用途：{data.recommended_destination.purpose}。営業提案・提携相談・事業相談・一般の順に用途を評価します。送信先の確定・送信承認ではありません。</p>}
      {data.destination_selection_required && <p>同条件のREADY窓口が複数あります。Humanが対象範囲・用途を確認して選択する必要があります。自動選択しません。</p>}
      <ul>{data.reasons.map(reason => <li key={reason.code}><strong>{reason.message}</strong>：{reason.next_action} <small>({reason.code})</small></li>)}</ul>
      <DestinationChoice companyId={companyId} choice={data.human_choice} candidates={data.destinations} canReview={data.can_review} onSaved={() => setRevision(v => v + 1)} />
      {data.destinations.map(item => <details key={`${item.type}:${item.destination}`} className="mt-3 break-all">
        <summary>{item.type}：{item.destination} / {states[item.status] ?? '未判定'}（{item.status}）</summary>
        <p>既存連絡可否：{item.core_permission} / 用途登録：{item.purpose}。ALLOWEDだけでは準備完了になりません。</p>
        <ul>{item.reasons.map(reason => <li key={reason.code}>{reason.message}：{reason.next_action} <small>({reason.code})</small></li>)}</ul>
        <DestinationReview key={item.expected_hash ?? item.destination} companyId={companyId} item={item} canReview={data.can_review} onSaved={() => setRevision(v => v + 1)} />
      </details>)}
    </>}
  </section>
}

function DestinationReview({ companyId, item, canReview, onSaved }: { companyId: string; item: Destination; canReview: boolean; onSaved: () => void }) {
  const [purpose, setPurpose] = useState('unknown')
  const [scope, setScope] = useState('unknown')
  const [source, setSource] = useState('')
  const [excerpt, setExcerpt] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function save(revoke: boolean) {
    setBusy(true); setError('')
    try {
      await api(`/companies/${companyId}/destinations/${item.id}/reviews${revoke ? '/revoke' : ''}`, 'POST', revoke ? { expected_review_version: item.review.version } : { expected_hash: item.expected_hash, expected_review_version: item.review.version, purpose, scope, source_url: source, evidence_excerpt: excerpt })
      onSaved()
    } catch (e) { setError(errorMessage(e)); onSaved() } finally { setBusy(false) }
  }
  return <div className="mt-3" aria-label={`用途確認 ${item.destination}`}>
    <p>用途確認：{item.review.state} / 記録版 {item.review.version}</p>
    {item.review.created_at && <p>確認者ID：{item.review.reviewed_by_user_id} / {new Date(item.review.created_at).toLocaleString('ja-JP')} / 期限：{item.review.expires_at ? new Date(item.review.expires_at).toLocaleString('ja-JP') : '—'}</p>}
    {item.review.evidence_excerpt && <p>記録した根拠：{item.review.evidence_excerpt} / {item.review.source_url}</p>}
    {canReview && item.id && <>
      <p>公開ページに記載された用途を確認して記録してください。営業禁止・共通窓口・CAPTCHAなどは、この操作で解除されません。</p>
      <label className="field">窓口用途<select value={purpose} disabled={busy} onChange={e => setPurpose(e.target.value)}>{Object.entries({ unknown: '不明', general: '一般問い合わせ', business: '事業相談', partnership: '提携相談', sales: '営業提案', support: 'サポート専用', recruitment: '採用専用', reservation: '予約専用' }).map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select></label>
      <label className="field">窓口の対象範囲<select value={scope} disabled={busy} onChange={e => setScope(e.target.value)}><option value="unknown">不明</option><option value="company">企業</option><option value="location">店舗・拠点</option><option value="group">グループ・共通</option></select></label>
      <label className="field">用途の根拠URL<input value={source} disabled={busy} maxLength={2048} onChange={e => setSource(e.target.value)} placeholder="公式サイト内の公開ページ" /></label>
      <label className="field">公開ページの用途説明<textarea value={excerpt} disabled={busy} maxLength={1000} onChange={e => setExcerpt(e.target.value)} placeholder="確認した説明を10文字以上で記録。秘密情報は入力しないでください。" /></label>
      <button className="secondary" disabled={busy || !item.expected_hash || excerpt.trim().length < 10 || !source.trim()} onClick={() => void save(false)}>用途確認を記録</button>
      {item.review.version > 0 && item.review.state !== 'REVOKED' && <button className="secondary" disabled={busy} onClick={() => void save(true)}>用途確認を取り消す</button>}
    </>}
    {canReview && !item.id && <p>先に窓口候補を整理すると用途を記録できます。</p>}
    {error && <p role="alert">{error}</p>}
  </div>
}
