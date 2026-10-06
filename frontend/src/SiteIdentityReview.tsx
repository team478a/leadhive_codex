import { useState } from 'react'
import { api, errorMessage } from './api'

export type IdentityReview = { state: string; version: number; source_url: string; observed_name: string; observed_address: string; observed_phone: string; evidence_excerpt: string; actor_user_id: string | null; created_at: string | null; expires_at: string | null; reasons: string[] }

export function SiteIdentityReview({ companyId, digest, review, canReview, onSaved }: { companyId: string; digest: string; review: IdentityReview; canReview: boolean; onSaved: () => void }) {
  const [name, setName] = useState('')
  const [address, setAddress] = useState('')
  const [phone, setPhone] = useState('')
  const [source, setSource] = useState('')
  const [excerpt, setExcerpt] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function save(revoke: boolean) {
    setBusy(true); setError('')
    try {
      await api(`/companies/${companyId}/site-identity-reviews${revoke ? '/revoke' : ''}`, 'POST', revoke ? { expected_review_version: review.version } : { expected_hash: digest, expected_review_version: review.version, source_url: source, observed_name: name, observed_address: address, observed_phone: phone, evidence_excerpt: excerpt })
      onSaved()
    } catch (e) { setError(errorMessage(e)); onSaved() } finally { setBusy(false) }
  }
  return <details className="mt-3" aria-label="企業・店舗と公式サイトのHuman確認">
    <summary>企業・店舗と公式サイトを確認する</summary>
    <p>Human確認：{review.state} / 記録版 {review.version}</p>
    <p className="muted">公式ページで確認した名称と、番地を含む住所または電話を記録します。アプリが実サイトを検証したという意味ではありません。7日で失効し、対象情報の変更でも再確認が必要です。送信承認・営業許可とは別です。</p>
    {review.created_at && <p>確認者ID：{review.actor_user_id} / 期限：{review.expires_at ? new Date(review.expires_at).toLocaleString('ja-JP') : '—'}</p>}
    {review.evidence_excerpt && <p className="break-all">{review.observed_name} / {review.observed_address} / {review.observed_phone}<br />記録した根拠：{review.evidence_excerpt} / {review.source_url} / {review.reasons.join(', ')}</p>}
    {canReview && <>
      <label className="field">公式ページの企業・店舗名<input disabled={busy} value={name} maxLength={300} onChange={e => setName(e.target.value)} /></label>
      <label className="field">公式ページの住所<input disabled={busy} value={address} maxLength={1000} onChange={e => setAddress(e.target.value)} /></label>
      <label className="field">公式ページの電話<input disabled={busy} value={phone} maxLength={100} onChange={e => setPhone(e.target.value)} /></label>
      <label className="field">照合の根拠URL<input disabled={busy} value={source} maxLength={2048} onChange={e => setSource(e.target.value)} placeholder="公式サイト内の公開ページ" /></label>
      <label className="field">照合の公開情報<textarea disabled={busy} value={excerpt} maxLength={1000} onChange={e => setExcerpt(e.target.value)} placeholder="確認した公開情報を10文字以上。秘密情報は記録しないでください。" /></label>
      <button className="secondary" disabled={busy || name.trim().length < 2 || (!address.trim() && !phone.trim()) || !source.trim() || excerpt.trim().length < 10} onClick={() => void save(false)}>照合確認を記録</button>
      {review.version > 0 && review.state !== 'REVOKED' && <button className="secondary" disabled={busy} onClick={() => void save(true)}>照合確認を取り消す</button>}
    </>}
    {error && <p role="alert">{error}</p>}
  </details>
}
