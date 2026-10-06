import { useState } from 'react'
import { api, errorMessage } from './api'

export type HumanDestinationChoice = {
  state: string; version: number; actor_user_id: string | null
  created_at: string | null; expires_at: string | null
  recorded_destination: { id: string; type: string; destination: string } | null
  active_destination: { id: string; type: string; destination: string } | null
}
type Candidate = { id: string | null; type: string; destination: string; status: string; expected_hash: string | null; review: { version: number } }
const labels: Record<string, string> = { UNSELECTED: '未選択', CURRENT: '有効', REVOKED: '取り消し済み', EXPIRED: '期限切れ', STALE: '情報変更により無効', INELIGIBLE: '安全条件により無効' }

export function DestinationChoice({ companyId, choice, candidates, canReview, onSaved }: {
  companyId: string; choice: HumanDestinationChoice; candidates: Candidate[]; canReview: boolean; onSaved: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function save(item?: Candidate) {
    setBusy(true); setError('')
    try {
      await api(item ? `/companies/${companyId}/destinations/${item.id}/choice` : `/companies/${companyId}/destination-choice/revoke`, 'POST', item ? {
        expected_hash: item.expected_hash, expected_purpose_version: item.review.version, expected_choice_version: choice.version,
      } : { expected_choice_version: choice.version })
      onSaved()
    } catch (e) { setError(errorMessage(e)); onSaved() } finally { setBusy(false) }
  }
  return <section className="mt-3 break-all" aria-label="営業準備に使う窓口の選択">
    <h4>営業準備に使う窓口</h4>
    <p>準備対象の選択：{labels[choice.state] ?? choice.state}（{choice.state}） / 記録版 {choice.version}</p>
    <p className="muted">用途確認・送信承認とは別の記録です。READYの窓口だけを選択できます。情報・用途の版・安全条件が変わると利用できません。最長7日で失効し、他の窓口に自動で切り替えません。</p>
    {choice.recorded_destination && <p>記録した窓口：{choice.recorded_destination.type} / {choice.recorded_destination.destination}</p>}
    {choice.active_destination && <p>現在の準備対象：{choice.active_destination.type} / {choice.active_destination.destination}</p>}
    {choice.created_at && <p>選択者ID：{choice.actor_user_id} / {new Date(choice.created_at).toLocaleString('ja-JP')} / 期限：{choice.expires_at ? new Date(choice.expires_at).toLocaleString('ja-JP') : '—'}</p>}
    {canReview && <div className="row wrap">
      {candidates.filter(item => item.id && item.expected_hash && item.status === 'READY' && item.id !== choice.active_destination?.id).map(item => <button key={item.id} className="secondary" disabled={busy} onClick={() => void save(item)}>この窓口を準備対象に選択：{item.type} / {item.destination}</button>)}
      {choice.version > 0 && choice.state !== 'REVOKED' && <button className="secondary" disabled={busy} onClick={() => void save()}>窓口の選択を取り消す</button>}
    </div>}
    {error && <p role="alert">{error}</p>}
  </section>
}
