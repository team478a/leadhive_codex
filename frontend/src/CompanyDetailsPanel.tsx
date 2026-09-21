import type { Company, SalesStatus } from './types'
import { statusNames } from './companyPageShared'

type Props = {
  company: Company
  values: Record<string, string>
  protectedFields: string[]
  doNotContact: boolean
  exclusionReason: string
  contactQuality: Company['contact_quality_status']
  status: SalesStatus
  note: string
  followup: string
  busy: boolean
  onValuesChange: (value: Record<string, string>) => void
  onProtectedFieldsChange: (value: string[]) => void
  onDoNotContactChange: (value: boolean) => void
  onExclusionReasonChange: (value: string) => void
  onContactQualityChange: (value: Company['contact_quality_status']) => void
  onStatusChange: (value: SalesStatus) => void
  onNoteChange: (value: string) => void
  onFollowupChange: (value: string) => void
  onSaveCompany: () => void
  onSaveContactControl: () => void
  onSaveStatus: () => void
  onClose: () => void
}

export function CompanyDetailsPanel({ company, values, protectedFields, doNotContact, exclusionReason, contactQuality, status, note, followup, busy, onValuesChange, onProtectedFieldsChange, onDoNotContactChange, onExclusionReasonChange, onContactQualityChange, onStatusChange, onNoteChange, onFollowupChange, onSaveCompany, onSaveContactControl, onSaveStatus, onClose }: Props) {
  const changeProtected = (field: string, enabled: boolean) => onProtectedFieldsChange(enabled ? [...protectedFields, field] : protectedFields.filter(item => item !== field))
  return <section className="panel mt-7" aria-label="企業詳細"><div className="flex justify-between gap-4"><div><p className="eyebrow">COMPANY DETAIL</p><h2>{company.company_name}</h2></div><button className="secondary" onClick={onClose}>閉じる</button></div><div className="detail-grid"><div><h3>基本情報を編集</h3>{[['company_name', '会社名'], ['address', '住所'], ['prefecture', '都道府県'], ['city', '市区町村'], ['phone', '電話'], ['email', 'メール'], ['assignee', '担当者']].map(([key, label]) => <div key={key}><label className="field">{label}<input value={values[key] ?? ''} onChange={e => onValuesChange({ ...values, [key]: e.target.value })} /></label>{key !== 'assignee' && <label className="checkbox-row text-sm"><input type="checkbox" checked={protectedFields.includes(key)} onChange={e => changeProtected(key, e.target.checked)} />{label}をWeb再解析から保護</label>}</div>)}</div><div><h3>問い合わせ先を編集</h3>{[['contact_url', 'フォーム'], ['instagram_url', 'Instagram'], ['x_url', 'X'], ['tiktok_url', 'TikTok'], ['facebook_url', 'Facebook'], ['youtube_url', 'YouTube'], ['line_url', 'LINE']].map(([key, label]) => <div key={key}><label className="field">{label}<input value={values[key] ?? ''} onChange={e => onValuesChange({ ...values, [key]: e.target.value })} /></label><label className="checkbox-row text-sm"><input type="checkbox" checked={protectedFields.includes(key)} onChange={e => changeProtected(key, e.target.checked)} />{label}をWeb再解析から保護</label></div>)}</div></div><div className="actions"><button disabled={busy} onClick={onSaveCompany}>企業情報を保存</button></div><div className="detail-grid"><div><h3>連絡禁止・除外</h3><label className="checkbox-row"><input type="checkbox" checked={doNotContact} onChange={e => onDoNotContactChange(e.target.checked)} />この企業への連絡を禁止</label><label className="field">除外理由<input maxLength={500} required={doNotContact} value={exclusionReason} onChange={e => onExclusionReasonChange(e.target.value)} placeholder="例：連絡拒否、既存顧客、競合" /></label></div><div><h3>連絡先品質</h3><label className="field">確認状態<select value={contactQuality} onChange={e => onContactQualityChange(e.target.value as Company['contact_quality_status'])}><option value="unknown">未確認</option><option value="observed">Web取得済み</option><option value="verified">人手確認済み</option><option value="invalid">無効</option></select></label><p className="muted text-sm">取得元：{company.contact_source_url || '未記録'}</p><p className="muted text-sm">最終確認：{company.contact_checked_at ? new Date(company.contact_checked_at).toLocaleString('ja-JP') : '未確認'}</p></div></div><div className="actions"><button disabled={busy || (doNotContact && !exclusionReason.trim())} onClick={onSaveContactControl}>連絡制御を保存</button></div><div className="detail-grid"><div><h3>AI分析</h3><p><strong>{company.rank ?? '未判定'} / {company.score ?? '—'}点</strong> {company.business_type}</p><p>{company.ai_summary || 'AI要約はありません。'}</p><p className="muted">{company.ai_reason}</p></div><div><h3>強み・懸念</h3><p>{company.ai_strengths.join(' / ') || '—'}</p><p className="muted">{company.ai_concerns.join(' / ') || '—'}</p><p>推奨：{company.ai_recommended_approach || '—'}</p></div></div><div className="mt-5"><h3>Web解析ページ</h3>{company.scraped_urls.length === 0 ? <p className="muted text-sm">解析ページの記録はありません。</p> : <ul className="mt-2 list-disc pl-5 text-sm">{company.scraped_urls.map(url => <li className="break-all" key={url}><a href={url} target="_blank" rel="noreferrer">{url}</a></li>)}</ul>}</div><div className="detail-grid"><div><label className="field">営業状況<select value={status} onChange={e => onStatusChange(e.target.value as SalesStatus)}>{Object.entries(statusNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="field">次回対応日時<input type="datetime-local" value={followup} onChange={e => onFollowupChange(e.target.value)} /></label></div><label className="field">メモ<textarea rows={5} maxLength={20000} value={note} onChange={e => onNoteChange(e.target.value)} /></label></div><div className="actions"><button disabled={busy} onClick={onSaveStatus}>{busy ? '保存中…' : '営業状況を保存'}</button></div></section>
}
