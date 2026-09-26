import { useEffect, useState } from 'react'
import type { Company, FormAnalysisLog, FormMappedKey, FormProfile, FormProfileField } from './types'

const mappedKeys: FormMappedKey[] = [
  'company_name', 'department', 'position', 'contact_name', 'last_name', 'first_name',
  'furigana', 'email', 'phone', 'postal_code', 'prefecture', 'city', 'address', 'building',
  'website', 'contact_category', 'subject', 'message', 'privacy_consent',
  'newsletter_consent', 'other', 'unknown',
]
const statusNames: Record<FormProfile['form_status'], string> = {
  UNANALYZED: '未解析', READY: '送信準備完了', REVIEW_REQUIRED: '要確認',
  BLOCKED: '送信対象外', STALE: '変更あり', ERROR: '解析失敗',
}
const salesNames: Record<FormProfile['sales_contact_status'], string> = {
  ALLOWED: '営業禁止なし', PROHIBITED: '営業禁止', UNCERTAIN: '要確認',
}
const captchaNames: Record<FormProfile['captcha_type'], string> = {
  CAPTCHA_NONE: 'なし', CAPTCHA_RECAPTCHA: 'reCAPTCHA', CAPTCHA_HCAPTCHA: 'hCaptcha',
  CAPTCHA_TURNSTILE: 'Turnstile', CAPTCHA_OTHER: 'その他',
}

type Props = {
  company: Company
  profiles: FormProfile[]
  logs: FormAnalysisLog[]
  busy: boolean
  onAnalyze: () => void
  onSelectPrimary: (profile: FormProfile) => void
  onCorrect: (field: FormProfileField, mappedKey: FormMappedKey, recommendedValue: string) => void
}

export function CompanyFormIntelligencePanel({ company, profiles, logs, busy, onAnalyze, onSelectPrimary, onCorrect }: Props) {
  const [drafts, setDrafts] = useState<Record<string, { mappedKey: FormMappedKey; value: string }>>({})
  useEffect(() => {
    setDrafts(Object.fromEntries(profiles.flatMap(profile => profile.fields.map(field => [
      field.id, { mappedKey: field.mapped_key, value: field.recommended_value },
    ]))))
  }, [profiles])
  return <section className="panel mt-6">
    <div className="section-heading"><div><h2>フォーム事前解析</h2><p className="muted text-sm">問い合わせフォームの構造と営業可否を送信前に確認します。</p></div><button disabled={busy || !company.website_url} onClick={onAnalyze}>{busy ? '解析中…' : profiles.length ? '再解析' : 'フォーム解析'}</button></div>
    {!company.website_url && <p className="muted mt-4">公式サイトURLを登録すると解析できます。</p>}
    {company.website_url && profiles.length === 0 && <p className="muted mt-4">まだ解析されていません。</p>}
    {profiles.map(profile => <article className="form-profile-card" key={profile.id}>
      <div className="section-heading">
        <div><div className="flex flex-wrap items-center gap-2"><strong>{profile.page_kind === 'partnership' ? '提携・法人向け' : profile.page_kind === 'recruitment' ? '採用向け' : profile.page_kind === 'support' ? 'サポート向け' : '一般問い合わせ'}</strong>{profile.is_primary && <span className="badge">優先フォーム</span>}<span className={`form-status ${profile.form_status.toLowerCase()}`}>{statusNames[profile.form_status]}</span></div><a className="text-link text-xs break-all" href={profile.form_url} target="_blank" rel="noreferrer">{profile.form_url}</a></div>
        {!profile.is_primary && <button className="secondary" disabled={busy} onClick={() => onSelectPrimary(profile)}>優先フォームにする</button>}
      </div>
      <div className="form-profile-summary">
        <span>フォーム: {profile.form_found ? 'あり' : '未検出'}</span><span>営業可否: {salesNames[profile.sales_contact_status]}</span><span>CAPTCHA: {captchaNames[profile.captcha_type]}</span><span>確認画面: {profile.confirmation_page === true ? 'あり' : profile.confirmation_page === false ? 'なし' : '不明'}</span><span>解析: {profile.last_analyzed_at ? new Date(profile.last_analyzed_at).toLocaleString('ja-JP') : '—'}</span><span>{profile.analysis_duration_ms} ms</span>
      </div>
      {profile.error_message && <p className="error mt-3">{profile.error_message}</p>}
      {profile.fields.length > 0 && <div className="company-table-wrap mt-4"><table className="company-table form-field-table"><thead><tr><th>元の項目</th><th>種類</th><th>標準マッピング</th><th>確度・根拠</th><th>推奨値</th><th></th></tr></thead><tbody>
        {profile.fields.map(field => {
          const draft = drafts[field.id] ?? { mappedKey: field.mapped_key, value: field.recommended_value }
          return <tr key={field.id}><td><strong>{field.label || field.name || '名称なし'}</strong><p className="muted text-xs break-all">{field.name || field.selector}</p>{field.required && <span className="required-mark">必須</span>}</td><td>{field.field_type}{field.options.length > 0 && <p className="muted text-xs">{field.options.map(option => option.label || option.value).filter(Boolean).join(' / ')}</p>}</td><td><select aria-label={`${field.label}の標準マッピング`} value={draft.mappedKey} onChange={event => setDrafts({ ...drafts, [field.id]: { ...draft, mappedKey: event.target.value as FormMappedKey } })}>{mappedKeys.map(key => <option key={key} value={key}>{key}</option>)}</select></td><td>{Math.round(field.confidence * 100)}%<p className="muted text-xs">{field.decision_source}</p></td><td><input aria-label={`${field.label}の推奨値`} value={draft.value} onChange={event => setDrafts({ ...drafts, [field.id]: { ...draft, value: event.target.value } })} placeholder="選択肢の推奨値" /></td><td><button className="secondary" disabled={busy || (draft.mappedKey === field.mapped_key && draft.value === field.recommended_value)} onClick={() => onCorrect(field, draft.mappedKey, draft.value)}>修正を保存</button></td></tr>
        })}
      </tbody></table></div>}
    </article>)}
    {logs.length > 0 && <details className="mt-5"><summary>解析ログ（{logs.length}件）</summary><div className="form-analysis-log mt-3">{logs.slice(0, 50).map(log => <p key={log.id}><time>{new Date(log.created_at).toLocaleString('ja-JP')}</time><strong>{log.event_type}</strong>{log.provider && <span>{log.provider}</span>}{log.duration_ms > 0 && <span>{log.duration_ms} ms</span>}</p>)}</div></details>}
  </section>
}
