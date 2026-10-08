import { useState } from 'react'
import { api, errorMessage } from './api'

export interface CF7ReservationPlan {
  source_approval_id: string; source_approval_hash: string; source_approval_version: number
  expires_at: string; environment: 'RESERVATION_ONLY'; execution_allowed: false
}

export function CF7ReservationPreparationPanel({ requestId, refresh }: { requestId: string; refresh: () => Promise<void> }) {
  const [preview, setPreview] = useState<{ preparation_hash: string; plan: CF7ReservationPlan } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  async function act(create: boolean) {
    setBusy(true); setError(''); setNotice('')
    try {
      if (create && preview) {
        await api(`/approval-requests/${requestId}/cf7-reservation-request`, 'POST', { expected_preparation_hash: preview.preparation_hash })
        setNotice('別の予約承認候補を保存しました。承認待ちの新しい提案を開き、再認証して承認してください。送信は行いません。')
        setPreview(null); await refresh()
      } else setPreview(await api(`/approval-requests/${requestId}/cf7-reservation-preview`))
    } catch (e) { setPreview(null); setError(errorMessage(e)) }
    finally { setBusy(false) }
  }
  return <section aria-label="CF7予約用の再承認準備" className="mt-4">
    <h3>予約用の再承認準備</h3>
    <p>候補承認を直接予約には使いません。別のHuman承認を作成し、予約だけ保存できます。この予約から送信は始まりません。</p>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    <button type="button" disabled={busy} onClick={() => act(false)}>予約用の準備内容を確認</button>
    {preview && <><p>予約のみ / 証拠期限：{new Date(preview.plan.expires_at).toLocaleString('ja-JP')}</p>
      <p className="break-all">元の承認：{preview.plan.source_approval_id} / v{preview.plan.source_approval_version}</p>
      <button type="button" disabled={busy} onClick={() => act(true)}>予約用の別承認候補を保存</button></>}
  </section>
}
