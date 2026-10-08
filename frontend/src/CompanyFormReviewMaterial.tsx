import { useState } from 'react'
import { api } from './api'

type Material = {
  draft_id: string | null
  source_observed_at: string | null
  sender_settings_visible: boolean
  permission_status: string
  profile_review_reason: string
  human_review_count: number
  missing_required_values: number
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

export function CompanyFormReviewMaterial({ profileId }: { profileId: string }) {
  const [material, setMaterial] = useState<Material | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function load() {
    setBusy(true); setError(''); setMaterial(null)
    try { setMaterial(await api<Material>(`/form-profiles/${profileId}/review-material`)) }
    catch (err) { setError(err instanceof Error ? err.message : '確認資料を取得できませんでした。') }
    finally { setBusy(false) }
  }
  return <section className="mt-4" aria-label="フォーム入力確認">
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
      {material.items.length === 0 && <p className="muted mt-3">保存済みの入力項目はありません。</p>}
      {material.items.filter(item => item.review_state !== 'DO_NOT_FILL').map(item => <article className="panel mt-3" key={`${item.position}:${item.name}`}>
        <strong className="break-all">{item.label || item.name || '名称不明'}{item.required ? '（必須）' : ''}</strong>
        <p className="muted text-sm mt-2">{states[item.review_state] ?? '要確認'}</p>
        {item.proposed_value !== null && <p className="mt-2 break-all whitespace-pre-wrap">{item.proposed_value}</p>}
        {item.options.length > 0 && <p className="muted text-sm mt-2 break-all">選択肢：{item.options.map(option => option.label || option.value || '名称不明').join(' ／ ')}</p>}
      </article>)}
      <p className="muted text-xs mt-3">隠し欄・スパム対策欄・送信ボタン・ファイル欄には入力候補を作りません。</p>
    </div>}
  </section>
}
