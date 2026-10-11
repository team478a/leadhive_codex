import { useState } from 'react'
import type { Activity, Company, FormProfile } from './types'
import { OfflineInputHandoff } from './OfflineInputHandoff'

const prefix = 'フォーム入力確認 v1: '
const outcomes = { INPUT_OK: '入力できた（未送信）', INPUT_FAILED: '入力できなかった', CAPTCHA: 'CAPTCHAで停止', NOT_CHECKED: 'まだ試していない' }
const reasons = { REQUIRED_FIELD: '必須項目が分からない', CHOICE: '選択肢・同意を確認できない', DYNAMIC: '画面が動的で入力できない', FRAME: '別画面・iframeで入力できない', PAGE_ERROR: 'ページが開かない・エラー', OTHER: 'その他' }
type Outcome = keyof typeof outcomes
type Reason = keyof typeof reasons
type RecordValue = { version: 1; outcome: Outcome; reason: string; note: string; form_url: string; profile_id: string | null; fingerprint: string | null; source: 'HUMAN_REPORTED'; sent: false }

function validUrl(value: string) {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password && value.length <= 5000 } catch { return false }
}
function readRecord(activity: Activity): RecordValue | null {
  if (!activity.note.startsWith(prefix)) return null
  try {
    const value = JSON.parse(activity.note.slice(prefix.length))
    if (value.version !== 1 || value.source !== 'HUMAN_REPORTED' || value.sent !== false || !Object.hasOwn(outcomes, value.outcome)
      || typeof value.form_url !== 'string' || !validUrl(value.form_url) || typeof value.note !== 'string' || typeof value.reason !== 'string') return null
    return value
  } catch { return null }
}

export function CompanyFormInputTrial({ company, profiles, activities, readOnly, busy, onSave }: {
  company: Company; profiles: FormProfile[]; activities: Activity[]; readOnly: boolean; busy: boolean
  onSave: (note: string) => Promise<boolean>
}) {
  const [url, setUrl] = useState(company.contact_url || '')
  const [outcome, setOutcome] = useState<Outcome>('NOT_CHECKED')
  const [reason, setReason] = useState<Reason>('REQUIRED_FIELD')
  const [note, setNote] = useState('')
  const [message, setMessage] = useState('')
  const companyProfiles = profiles.filter(profile => profile.company_id === company.id)
  const known = [...new Set([company.contact_url, ...companyProfiles.map(profile => profile.form_url)].filter(value => value && validUrl(value)))]
  const stopped = outcome === 'INPUT_FAILED' || outcome === 'CAPTCHA'
  const blocked = company.do_not_contact || companyProfiles.some(profile => profile.form_url === url.trim() && profile.sales_contact_status === 'PROHIBITED')
  async function save() {
    const formUrl = url.trim()
    if (!validUrl(formUrl) || outcome === 'NOT_CHECKED' || stopped && !note.trim() || busy || readOnly) return
    const matches = companyProfiles.filter(profile => profile.form_url === formUrl)
    const profile = matches.length === 1 ? matches[0] : null
    const value: RecordValue = { version: 1, source: 'HUMAN_REPORTED', sent: false, outcome,
      reason: outcome === 'CAPTCHA' ? 'CAPTCHA' : outcome === 'INPUT_FAILED' ? reason : '',
      note: note.trim(), form_url: formUrl, profile_id: profile?.id ?? null, fingerprint: profile?.fingerprint ?? null }
    setMessage('')
    if (await onSave(prefix + JSON.stringify(value))) { setMessage('入力確認を記録しました。送信承認や営業可否は変更していません。'); setOutcome('NOT_CHECKED'); setNote('') }
  }
  return <><OfflineInputHandoff company={company} activities={activities} readOnly={readOnly} busy={busy} prohibited={company.do_not_contact || companyProfiles.some(p => p.sales_contact_status === 'PROHIBITED')} onSave={onSave} /><section className="panel mt-4" aria-label="フォーム入力の実運用記録">
    <h3>入力を試した結果を残す</h3>
    <p>元フォームで人が確認した結果を記録します。自動入力・送信は行いません。営業NGを見つけた場合は「営業NGリストへ移す」を使ってください。</p>
    {blocked && <p className="notice">この企業・フォームは送信禁止です。入力成功を記録しても禁止は解除されません。</p>}
    {readOnly ? <p>結果の記録は所有者または編集者が行います。</p> : <>
      <label className="field mt-3">確認したフォームURL<input type="url" maxLength={5000} value={url} disabled={busy} onChange={event => { setUrl(event.target.value); setOutcome('NOT_CHECKED'); setMessage('') }} /></label>
      {known.length > 0 && <label className="field">保存済みフォームから選ぶ<select value={known.includes(url) ? url : ''} disabled={busy} onChange={event => { setUrl(event.target.value); setOutcome('NOT_CHECKED'); setMessage('') }}><option value="">選択してください</option>{known.map(value => <option key={value} value={value}>{value}</option>)}</select></label>}
      <label className="field">入力確認の結果<select value={outcome} disabled={busy} onChange={event => setOutcome(event.target.value as Outcome)}>{Object.entries(outcomes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      {outcome === 'INPUT_FAILED' && <label className="field">入力できない理由<select value={reason} disabled={busy} onChange={event => setReason(event.target.value as Reason)}>{Object.entries(reasons).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>}
      <label className="field">確認メモ{stopped ? '（必須）' : '（任意）'}<textarea maxLength={1000} value={note} disabled={busy} onChange={event => setNote(event.target.value)} placeholder="止まった項目や画面を記録。パスワード・入力した個人情報は記載しないでください。" /></label>
      <button disabled={busy || !validUrl(url.trim()) || outcome === 'NOT_CHECKED' || stopped && !note.trim()} onClick={() => void save()}>未送信の入力結果を記録</button>
    </>}
    {message && <p role="status">{message}</p>}
    <p className="muted text-sm">人による申告です。自動検証済み・送信可能・Human承認済みとは扱いません。CAPTCHAは人の操作が必要です。</p>
    {activities.filter(activity => activity.company_id === company.id).map(activity => ({ activity, record: readRecord(activity) })).filter(item => item.record).slice(0, 5).map(({ activity, record }) => record && <article className="mt-3" key={activity.id}>
      <strong>{outcomes[record.outcome]}</strong><p className="break-all">{record.form_url}</p>
      <p>{record.reason === 'CAPTCHA' ? 'CAPTCHA' : reasons[record.reason as Reason] || ''} {record.note}</p>
      <p className="muted text-sm">{new Date(activity.created_at).toLocaleString('ja-JP')} / 人による記録・未送信</p>
    </article>)}
  </section></>
}
