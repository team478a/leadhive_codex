import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { openDestinationReview } from './formReviewNavigation'
import type { FormMappedKey, FormProfileField } from './types'
import { CompanyFormChoiceGroups } from './CompanyFormChoiceGroups'
import { CompanyFormLiveCheck } from './CompanyFormLiveCheck'
import { CompanyFormSavedChoices } from './CompanyFormSavedChoices'
import type { SavedChoiceStructure } from './CompanyFormSavedChoices'
import { CompanyFormSavedChoiceReviews } from './CompanyFormSavedChoiceReviews'
import { CompanyFormAdapterPrerequisites } from './CompanyFormAdapterPrerequisites'
import type { AdapterPrerequisites } from './CompanyFormAdapterPrerequisites'
import { CompanyFormInputPreparation } from './CompanyFormInputPreparation'

type Material = {
  adapter_prerequisites?: AdapterPrerequisites
  saved_choice_structure?: SavedChoiceStructure
  technical_diagnostic?: { route: string; boundary: string; reasons: { code: string; message: string }[]; observation_freshness: string; missing_field_names: number; execution_allowed: false; next_action: string }
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
  companyId: string
  formUrl: string
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

export function CompanyFormReviewMaterial({ profileId, companyId, formUrl, fingerprint, fields, readOnly, saving, onCorrect, onRefresh }: Props) {
  const [material, setMaterial] = useState<Material | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const load = useCallback(async () => {
    setBusy(true); setError(''); setMaterial(null)
    try { setMaterial(await api<Material>(`/form-profiles/${profileId}/review-material`)) }
    catch (err) { setError(err instanceof Error ? err.message : '確認資料を取得できませんでした。') }
    finally { setBusy(false) }
  }, [profileId])
  const fieldVersion = fields.map(field => `${field.id}:${field.updated_at}`).join('|')
  useEffect(() => {
    let active = true
    setBusy(true); setError(''); setMaterial(null)
    api<Material>(`/form-profiles/${profileId}/review-material`)
      .then(value => { if (active) setMaterial(value) })
      .catch(err => { if (active) setError(err instanceof Error ? err.message : '確認資料を取得できませんでした。') })
      .finally(() => { if (active) setBusy(false) })
    return () => { active = false }
  }, [profileId, fingerprint, fieldVersion])
  const reviewStates = new Set(['HUMAN_CONSENT_REQUIRED', 'GROUP_SELECTION_REVIEW_REQUIRED', 'FIELD_IDENTITY_REVIEW_REQUIRED', 'CHOICE_REVIEW_REQUIRED', 'FIELD_REVIEW_REQUIRED', 'SENDER_VALUE_MISSING', 'DRAFT_VALUE_MISSING'])
  const [showCandidates, setShowCandidates] = useState(false)
  const [navigationMessage, setNavigationMessage] = useState('')
  const sourceLink = /^https?:\/\//i.test(formUrl) ? formUrl : null
  async function saveChoice(field: FormProfileField, value: string) {
    const saved = await onCorrect(field, field.mapped_key, value)
    if (saved) await load()
    return saved
  }
  return <section className="mt-4" aria-label="フォーム入力確認" data-review-form-url={formUrl} tabIndex={-1}>
    <CompanyFormLiveCheck profileId={profileId} fingerprint={fingerprint} readOnly={readOnly} onRefresh={onRefresh} />
    <button className="secondary" disabled={busy} onClick={load}>{busy ? '読み込み中…' : '入力候補を更新'}</button>
    {error && <p className="error mt-3" role="alert">{error}</p>}
    <CompanyFormSavedChoices profileId={profileId} structure={material?.saved_choice_structure ?? null} />
    {material?.saved_choice_structure ? <CompanyFormSavedChoiceReviews key={material.saved_choice_structure.source_hash} profileId={profileId} readOnly={readOnly} onSaved={load} /> : null}
    {material && <div className="mt-3">
      <h3>フォーム入力の確認資料</h3>
      <p className="notice mt-3">保存済み情報から作った候補です。この表示では承認・送信されません。現在のページの確認結果は上の欄で確認してください。</p>
      <section className="notice mt-3" aria-label="確認の進め方">
        <strong>人が確認すること</strong>
        <p className="mt-2">1. 元フォームで窓口の用途と営業可否を確認</p>
        <button className="secondary mt-2" onClick={() => setNavigationMessage(openDestinationReview(companyId, formUrl) ? '' : '一致する窓口候補を1つに特定できません。「リスト完成の根拠」で窓口候補を確認・整理してください。')}>このフォームの窓口用途を確認</button>
        {navigationMessage && <p className="notice mt-2" role="status">{navigationMessage}</p>}
        <p>2. 下の選択肢・同意・必須条件を確認して記録</p>
        <p>3. 送信者情報と本文候補を確認</p>
        {sourceLink && <a className="secondary inline-block mt-3" href={sourceLink} target="_blank" rel="noopener noreferrer">元フォームを開く ↗</a>}
        <p className="muted text-sm mt-3">ここでの記録は入力内容の確認です。窓口の営業許可や送信承認を代替しません。技術未対応・送信禁止は解除されません。</p>
      </section>
      <p className="muted mt-3">確認事項 {material.human_review_count}件 ／ 必須値の不足 {material.missing_required_values}件</p>
      <p className="muted">営業可否：{material.permission_status === 'PROHIBITED' ? '送信禁止' : material.permission_status === 'ALLOWED' ? '禁止判定なし（送信承認ではありません）' : '未確認'}</p>
      {material.profile_review_reason && <p className="notice mt-3">{material.profile_review_reason}</p>}
      {!material.draft_id && <p className="notice mt-3">フォーム用の下書きがありません。DM文面の候補は表示できません。</p>}
      {!material.sender_settings_visible && <p className="muted mt-3">送信者設定は管理者のみ確認できます。</p>}
      <p className="muted text-xs mt-3">元の観測日時：{material.source_observed_at ? new Date(material.source_observed_at).toLocaleString('ja-JP') : '未記録'}</p>
      {material.profile_fingerprint !== fingerprint && <p className="notice mt-3">保存されたフォーム構造が変わりました。「入力候補を更新」で読み直してください。</p>}
      {material.items.length === 0 && <p className="muted mt-3">保存済みの入力項目はありません。</p>}
      {material.technical_diagnostic && <section className="notice mt-4" aria-label="送信経路の技術診断">
        <h3>送信を止めている技術上の理由</h3>
        <p className="mt-2">経路：{({ CF7_CANDIDATE: 'Contact Form 7の候補・実サイト経路未対応', BROWSER_REVIEW: 'ブラウザ動作の確認が必要', NATIVE_CANDIDATE: '通常POST経路の候補', UNKNOWN: '保存情報だけでは経路不明' } as Record<string, string>)[material.technical_diagnostic.route] ?? '未確認'}</p>
        <p>扱い：{({ BLOCKED: '送信対象外', HUMAN_REQUIRED: '人の操作が必要', TECHNICAL_HOLD: '技術対応の確認待ち', HUMAN_REVIEW: '人の確認・承認待ち' } as Record<string, string>)[material.technical_diagnostic.boundary] ?? '未確認'}</p>
        <ul className="mt-2">{material.technical_diagnostic.reasons.map(reason => <li key={reason.code}>{reason.message}</li>)}</ul>
        <p className="mt-2">{material.technical_diagnostic.next_action}</p>
        <p className="muted text-sm mt-2">保存済みデータの診断です。現在のサイト取得・ブラウザ入力・送信は行いません。候補経路の表示は送信対応済みや承認済みを意味しません。</p>
      </section>}
      <h3 className="mt-4">選択・同意・入力先の確認</h3>
      {material.adapter_prerequisites && <CompanyFormAdapterPrerequisites report={material.adapter_prerequisites} />}
      <CompanyFormInputPreparation key={`${profileId}:${material.profile_fingerprint}:${material.draft_id}:${fieldVersion}:${JSON.stringify(material.items)}`} profileId={profileId} readOnly={readOnly} />
      <p className="muted text-sm mt-2">確認対象の一覧です。記録済みの項目も表示します。件数は未確認件数や送信可能件数ではありません。</p>
      {material.profile_fingerprint === fingerprint && !material.items.some(item => reviewStates.has(item.review_state)) && <p className="muted mt-3">個別の選択確認対象はありません。窓口・本文・送信経路の確認は引き続き必要です。</p>}
      {material.profile_fingerprint === fingerprint && material.items.some(item => item.review_state === 'GROUP_SELECTION_REVIEW_REQUIRED') && <CompanyFormChoiceGroups profileId={profileId} readOnly={readOnly} onSaved={async () => { await onRefresh(); await load() }} />}
      <button className="secondary mt-3" aria-expanded={showCandidates} onClick={() => setShowCandidates(!showCandidates)}>{showCandidates ? '送信者情報・本文候補を閉じる' : '送信者情報・本文候補を見る'}</button>
      {material.profile_fingerprint === fingerprint && material.items.filter(item => item.review_state !== 'DO_NOT_FILL' && (reviewStates.has(item.review_state) || showCandidates)).sort((a, b) => Number(reviewStates.has(b.review_state)) - Number(reviewStates.has(a.review_state))).map(item => {
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
        {item.review_state === 'GROUP_SELECTION_REVIEW_REQUIRED' && <p className="notice mt-3">この項目は上の「複数項目の必須条件」で対象範囲と条件を確認します。</p>}
      </article>})}
      <p className="muted text-xs mt-3">隠し欄・スパム対策欄・送信ボタン・ファイル欄には入力候補を作りません。</p>
    </div>}
  </section>
}
