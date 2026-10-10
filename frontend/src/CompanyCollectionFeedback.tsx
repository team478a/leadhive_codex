import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import type { Company } from './types'

type Feedback = { subject: string; outcome: string; reason: string; reviewed_at: string; current: boolean }
const reasons = { wrong_company: '別会社・別店舗', wrong_industry: '対象業種ではない', article: '記事・お知らせ', recruitment: '採用専用', reservation: '予約専用', broken_link: 'リンク切れ', wrong_destination: '別の問い合わせ先', other: 'その他' }

export function CompanyCollectionFeedback({ company, readOnly, onSaved }: { company: Company; readOnly: boolean; onSaved: () => void }) {
  const [subject, setSubject] = useState<'company' | 'contact_url'>('contact_url')
  const [editing, setEditing] = useState(false)
  const [url, setUrl] = useState(company.contact_url || '')
  const [reason, setReason] = useState<keyof typeof reasons>('wrong_destination')
  const [history, setHistory] = useState<Feedback[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    api<{ items: Feedback[] }>(`/companies/${company.id}/collection-feedback`).then(r => { if (active) setHistory(r.items) }).catch(e => { if (active) setError(errorMessage(e)) })
    return () => { active = false }
  }, [company.id, company.updated_at])
  async function save(outcome: 'OK' | 'NG' | 'CORRECTED') {
    setBusy(true); setError('')
    try {
      await api(`/companies/${company.id}/collection-feedback`, 'POST', {
        subject, outcome, expected_updated_at: company.updated_at,
        reason: outcome === 'OK' ? 'confirmed' : reason,
        corrected_url: outcome === 'CORRECTED' ? url.trim() : '',
      })
      setEditing(false); onSaved()
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  const latest = history.find(item => item.subject === subject)
  return <div aria-label={`${company.company_name}の取得結果確認`} className="mt-3">
    <label className="field">確認する項目<select value={subject} onChange={e => { setSubject(e.target.value as typeof subject); setEditing(false) }}><option value="contact_url">問い合わせURL</option><option value="company">対象企業</option></select></label>
    {subject === 'contact_url' && <p className="text-sm break-all">{company.contact_url ? <a href={company.contact_url} target="_blank" rel="noreferrer">問い合わせ候補を開く</a> : '未検出（存在未確認）'}</p>}
    <p className="muted text-xs">{latest ? `${latest.outcome === 'OK' ? 'OKを記録' : latest.outcome === 'NG' ? 'NGを記録' : 'URL修正を記録'}${latest.current ? '' : '（登録情報が変わっています）'}` : '人の確認待ち'}</p>
    {!readOnly && <><div className="actions"><button className="secondary" disabled={busy || (subject === 'contact_url' && !company.contact_url)} onClick={() => void save('OK')}>OK</button><button className="secondary" disabled={busy} onClick={() => { setEditing(!editing); setUrl(company.contact_url || '') }}>NG・修正</button></div>
      {editing && <div><label className="field">理由<select aria-label="理由" value={reason} onChange={e => setReason(e.target.value as keyof typeof reasons)}>{Object.entries(reasons).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        {subject === 'contact_url' && <label className="field">正しい問い合わせURL<input type="url" value={url} onChange={e => setUrl(e.target.value)} placeholder="https://example.com/contact" /></label>}
        <div className="actions"><button className="secondary" disabled={busy} onClick={() => void save('NG')}>{subject === 'company' ? '対象外として記録' : 'NGを記録して候補から外す'}</button>{subject === 'contact_url' && <button disabled={busy || !url.trim()} onClick={() => void save('CORRECTED')}>修正URLを保存</button>}</div></div>}
      <p className="muted text-xs">{subject === 'contact_url' ? 'URLのOK・修正・NGは再解析から保護します。' : 'NGは対象外として記録します。OKだけで対象外を解除しません。'}送信は承認されません。</p></>}
    {error && <p role="alert" className="error">{error}</p>}
  </div>
}
