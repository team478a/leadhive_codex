import { useState } from 'react'
import { api } from './api'
import type { FormMappedKey, FormProfileField } from './types'
import { CompanyFormChoiceGroups } from './CompanyFormChoiceGroups'
import { CompanyFormLiveCheck } from './CompanyFormLiveCheck'

type Material = {
  draft_id: string | null
  source_observed_at: string | null
  sender_settings_visible: boolean
  permission_status: string
  profile_review_reason: string
  human_review_count: number
  missing_required_values: number
  profile_fingerprint: string
  items: { position: number; name: string; label: string; required: boolean; review_state: string; proposed_value: string | null; options: { label?: string; value?: string }[] }[]
}
const states: Record<string, string> = {
  DO_NOT_FILL: '入力しない', HUMAN_CONSENT_REQUIRED: '同意内容を人が確認',
  GROUP_SELECTION_REVIEW_REQUIRED: '必須の選択範囲を確認', FIELD_IDENTITY_REVIEW_REQUIRED: '入力先を確認',
  CHOICE_REVIEW_REQUIRED: '選択肢を確認', SENDER_VALUE_PROPOSED: '送信者情報の候補',
  SENDER_VALUE_MISSING: '送信者情報が未設定', UNAPPROVED_DRAFT_VALUE: '未承認の下書き',
  DRAFT_VALUE_MISSING: '下書きが未設定', FIELD_REVIEW_REQUIRED: '入力内容を確認',
  OPTIONAL_LEAVE_BLANK: '任意・空欄の候補',
}

type Props = {
  profileId: string
  fingerprint: string
  fields: FormProfileField[]
  readOnly: boolean
  saving: boolean
  onCorrect: (field: FormProfileField, key: FormMappedKey, value: string) => Promise<boolean>
  onRefresh: () => Promise<void>
}

function ChoiceReview({ field, readOnly, saving, onSave }: { field: FormProfileField; readOnly: boolean; saving: boolean; onSave: (value: string) => Promise<boolean> }) {
  const [value, setValue] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [error, setError] = useState('')
  const valid = field.options.some(option => option.value === value && value !== '') || (!field.required && value === '')
  async function save() {
    setError('')
    if (await onSave(value)) { setConfirmed(false); setValue('') }
    else { setError('保存できませんでした。表示されたエラーを確認して再度お試しください。') }
  }
  return <div className="mt-3">
    {field.decision_source === 'MANUAL' && <p className="muted text-sm">保存済みの選択：{field.options.find(option => option.value === field.recommended_value)?.label || field.recommended_value || '選択しない'}（送信承認ではありません）</p>}
    {readOnly ? <p className="muted text-sm">選択の保存は所有者または編集者が行います。</p> : <>
      <label>{field.label}の確認選択<select aria-label={`${field.label}の確認選択`} value={value} disabled={saving} onChange={event => { setValue(event.target.value); setConfirmed(false) }}>
        <option value="">{field.required ? '内容を確認して選んでください' : '選択しない（任意）'}</option>
        {field.options.filter(option => option.value).map((option, index) => <option key={index} value={option.value}>{option.label || option.value}</option>)}
      </select></label>
      <label className="mt-3 flex items-start gap-2"><input type="checkbox" checked={confirmed} disabled={saving} onChange={event => setConfirmed(event.target.checked)} />この項目の内容と選択値を確認しました</label>
      <button className="secondary mt-3" disabled={saving || !confirmed || !valid} onClick={save}>確認した選択を保存</button>
      {error && <p className="error mt-3" role="alert">{error}</p>}
    </>}
  </div>
}

export function CompanyFormReviewMaterial({ profileId, fingerprint, fields, readOnly, saving, onCorrect, onRefresh }: Props) {
  const [material, setMaterial] = useState<Material | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function load() {
    setBusy(true); setError(''); setMaterial(null)
    try { setMaterial(await api<Material>(`/form-profiles/${profileId}/review-material`)) }
    catch (err) { setError(err instanceof Error ? err.message : '確認資料を取得できませんでした。') }
    finally { setBusy(false) }
  }
  async function saveChoice(field: FormProfileField, value: string) {
    const saved = await onCorrect(field, field.mapped_key, value)
    if (saved) await load()
    return saved
  }
  return <section className="mt-4" aria-label="フォーム入力確認">
    <CompanyFormLiveCheck profileId={profileId} readOnly={readOnly} onRefresh={onRefresh} />
    <button className="secondary" disabled={busy} onClick={load}>{busy ? '読み込み中…' : material ? '入力候補を更新' : '入力候補と確認事項を見る'}</button>
    {error && <p className="error mt-3" role="alert">{error}</p>}
    {material && <div className="mt-3">
      <h3>フォーム入力の確認資料</h3>
      <p className="notice mt-3">保存済み情報から作った候補です。この表示では承認・送信されません。現在のフォームは未再確認です。</p>
      <p className="muted mt-3">確認事項 {material.human_review_count}件 ／ 必須値の不足 {material.missing_required_values}件</p>
      <p className="muted">営業可否：{material.permission_status === 'PROHIBITED' ? '送信禁止' : material.permission_status === 'ALLOWED' ? '禁止判定なし（送信承認ではありません）' : '未確認'}</p>
      {material.profile_review_reason && <p className="notice mt-3">{material.profile_review_reason}</p>}
      {!material.draft_id && <p className="notice mt-3">フォーム用の下書きがありません。DM文面の候補は表示できません。</p>}
      {!material.sender_settings_visible && <p className="muted mt-3">送信者設定は管理者のみ確認できます。</p>}
      <p className="muted text-xs mt-3">元の観測日時：{material.source_observed_at ? new Date(material.source_observed_at).toLocaleString('ja-JP') : '未記録'}</p>
      {material.profile_fingerprint !== fingerprint && <p className="notice mt-3">保存されたフォーム構造が変わりました。「入力候補を更新」で読み直してください。</p>}
      {material.items.length === 0 && <p className="muted mt-3">保存済みの入力項目はありません。</p>}
      {material.profile_fingerprint === fingerprint && material.items.filter(item => item.review_state !== 'DO_NOT_FILL').map(item => {
        const field = fields.find(candidate => candidate.position === item.position && candidate.name === item.name)
        const editableChoice = field && ['CHOICE_REVIEW_REQUIRED', 'HUMAN_CONSENT_REQUIRED'].includes(item.review_state)
          && ['contact_category', 'contact_method', 'privacy_consent', 'newsletter_consent'].includes(field.mapped_key)
          && (['radio', 'select'].includes(field.field_type) || (field.field_type === 'checkbox' && field.options.length === 1))
          && field.options.length > 0
          && new Set(field.options.map(option => option.value)).size === field.options.length
          && field.options.every(option => typeof option.value === 'string' && option.value !== '')
        return <article className="panel mt-3" key={`${item.position}:${item.name}`}>
        <strong className="break-all">{item.label || item.name || '名称不明'}{item.required ? '（必須）' : ''}</strong>
        <p className="muted text-sm mt-2">{states[item.review_state] ?? '要確認'}</p>
        {item.proposed_value !== null && <p className="mt-2 break-all whitespace-pre-wrap">{item.proposed_value}</p>}
        {item.options.length > 0 && <p className="muted text-sm mt-2 break-all">選択肢：{item.options.map(option => option.label || option.value || '名称不明').join(' ／ ')}</p>}
        {editableChoice && <ChoiceReview key={`${field.id}:${field.updated_at}`} field={field} readOnly={readOnly} saving={saving || busy} onSave={value => saveChoice(field, value)} />}
        {item.review_state === 'GROUP_SELECTION_REVIEW_REQUIRED' && <p className="notice mt-3">この項目は下の「複数項目の必須条件」で対象範囲と条件を確認します。</p>}
      </article>})}
      <p className="muted text-xs mt-3">隠し欄・スパム対策欄・送信ボタン・ファイル欄には入力候補を作りません。</p>
      {material.profile_fingerprint === fingerprint && material.items.some(item => item.review_state === 'GROUP_SELECTION_REVIEW_REQUIRED') && <CompanyFormChoiceGroups profileId={profileId} readOnly={readOnly} onSaved={async () => { await onRefresh(); await load() }} />}
    </div>}
  </section>
}
