import { useState } from 'react'
import { api, errorMessage } from './api'

export type IdentityReview = { state: string; version: number; source_url: string; observed_name: string; observed_address: string; observed_phone: string; evidence_excerpt: string; actor_user_id: string | null; created_at: string | null; expires_at: string | null; reasons: string[] }
export type IdentityTarget = { company_name: string; address: string; phone: string; website_url: string }
type Preview = { comparison: string; reasons: string[]; can_record: boolean }
const reasonLabels: Record<string, string> = {
  COMPANY_NAME_MATCH: '名称が一致', ADDRESS_MATCH: '番地を含む住所が一致', PHONE_MATCH: '電話が一致',
  DOMAIN_MATCH: '登録サイトと同じドメイン（これだけでは確認不可）', REGION_ONLY: '住所が地域名だけです',
  ADDRESS_CONFLICT: '住所が登録情報と異なります', PHONE_CONFLICT: '電話が登録情報と異なります',
  INSUFFICIENT_IDENTITY_EVIDENCE: '照合に必要な情報が不足しています', RECORD_TYPE_DIFFERENT: '対象種別が異なります',
}

export function SiteIdentityReview({ companyId, digest, target, review, canReview, onSaved }: { companyId: string; digest: string; target: IdentityTarget; review: IdentityReview; canReview: boolean; onSaved: () => void }) {
  const [name, setName] = useState('')
  const [address, setAddress] = useState('')
  const [phone, setPhone] = useState('')
  const [source, setSource] = useState('')
  const [excerpt, setExcerpt] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [preview, setPreview] = useState<Preview | null>(null)
  const [observed, setObserved] = useState(false)
  const body = { expected_hash: digest, expected_review_version: review.version, source_url: source, observed_name: name, observed_address: address, observed_phone: phone, evidence_excerpt: excerpt }
  const complete = name.trim().length >= 2 && Boolean(address.trim() || phone.trim()) && Boolean(source.trim()) && excerpt.trim().length >= 10
  function edit(setter: (value: string) => void, value: string) { setter(value); setPreview(null); setObserved(false); setError('') }
  async function check() {
    setBusy(true); setError(''); setPreview(null); setObserved(false)
    try { setPreview(await api<Preview>(`/companies/${companyId}/site-identity-reviews/preview`, 'POST', body)) }
    catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function save(revoke: boolean) {
    setBusy(true); setError('')
    try {
      if (!revoke && (!preview?.can_record || !observed)) return
      await api(`/companies/${companyId}/site-identity-reviews${revoke ? '/revoke' : ''}`, 'POST', revoke ? { expected_review_version: review.version } : body)
      onSaved()
    } catch (e) { setError(errorMessage(e)); onSaved() } finally { setBusy(false); setPreview(null); setObserved(false) }
  }
  return <details className="mt-3" aria-label="企業・店舗と公式サイトのHuman確認">
    <summary>企業・店舗と公式サイトを確認する</summary>
    <p>Human確認：{review.state} / 記録版 {review.version}</p>
    <p className="muted">公式ページで確認した名称と、番地を含む住所または電話を記録します。アプリが実サイトを検証したという意味ではありません。7日で失効し、対象情報の変更でも再確認が必要です。送信承認・営業許可とは別です。</p>
    <div className="break-all" aria-label="照合対象の登録情報">
      <h4>1. 登録情報と公式ページを比較</h4>
      <p>名称：{target.company_name || '未登録'}<br />住所：{target.address || '未登録'}<br />電話：{target.phone || '未登録'}<br />サイト候補：{target.website_url || '未登録'}</p>
      <p className="muted">登録情報は比較対象です。公式ページで見た情報の欄には自動コピーしません。別店舗の住所・電話が一致しない場合は記録せず、登録情報や対象を確認してください。</p>
    </div>
    {review.state === 'STALE' && <p>対象情報が変更されています。現在の登録情報で再確認が必要です。</p>}
    {review.state === 'EXPIRED' && <p>確認期限が切れています。公開ページを再確認してください。</p>}
    {review.created_at && <p>確認者ID：{review.actor_user_id} / 期限：{review.expires_at ? new Date(review.expires_at).toLocaleString('ja-JP') : '—'}</p>}
    {review.evidence_excerpt && <p className="break-all">{review.observed_name} / {review.observed_address} / {review.observed_phone}<br />記録した根拠：{review.evidence_excerpt} / {review.source_url} / {review.reasons.join(', ')}</p>}
    {canReview && <>
      <h4>2. 公式ページで確認した情報を入力</h4>
      <label className="field">公式ページの企業・店舗名<input disabled={busy} value={name} maxLength={300} onChange={e => edit(setName, e.target.value)} /></label>
      <label className="field">公式ページの住所<input disabled={busy} value={address} maxLength={1000} onChange={e => edit(setAddress, e.target.value)} /></label>
      <label className="field">公式ページの電話<input disabled={busy} value={phone} maxLength={100} onChange={e => edit(setPhone, e.target.value)} /></label>
      <label className="field">照合の根拠URL<input disabled={busy} value={source} maxLength={2048} onChange={e => edit(setSource, e.target.value)} placeholder="公式サイト内の公開ページ" /></label>
      <label className="field">照合の公開情報<textarea disabled={busy} value={excerpt} maxLength={1000} onChange={e => edit(setExcerpt, e.target.value)} placeholder="確認した公開情報を10文字以上。秘密情報は記録しないでください。" /></label>
      <button className="secondary" disabled={busy || !complete} onClick={() => void check()}>入力内容の照合をプレビュー</button>
      {preview && <div role="status">
        <p>{preview.can_record ? '記録可能な一致です。まだ確認記録は保存されていません。' : '確認記録に必要な一致がありません。名称と住所または電話を見直してください。'}</p>
        <ul>{preview.reasons.map(reason => <li key={reason}>{reasonLabels[reason] ?? reason}</li>)}</ul>
        <p>入力内容と登録情報の比較のみです。実サイトの検証・送信承認は行いません。</p>
      </div>}
      <h4>3. 根拠を確認して記録</h4>
      <label className="field"><input type="checkbox" disabled={busy || !preview?.can_record} checked={observed} onChange={e => setObserved(e.target.checked)} />公式ページで名称と住所または電話、および根拠を確認しました</label>
      <button className="secondary" disabled={busy || !preview?.can_record || !observed} onClick={() => void save(false)}>照合確認を記録</button>
      {review.version > 0 && review.state !== 'REVOKED' && <button className="secondary" disabled={busy} onClick={() => void save(true)}>照合確認を取り消す</button>}
    </>}
    {error && <p role="alert">{error}</p>}
  </details>
}
