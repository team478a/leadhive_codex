import { useState } from 'react'
import { api } from './api'
import type { Activity, Company, FormProfile } from './types'
import type { LivePlan, LiveTask } from './liveInputContract'

const statusLabels: Record<string, string> = { LIVE_INPUT_VERIFIED: '入力・読み戻し成功（未送信）', TECHNICAL_UNKNOWN: '入力を確認できず停止', HUMAN_REQUIRED: '人の確認が必要', BLOCKED: '入力禁止・停止' }
const reasonLabels: Record<string, string> = {
  STOP_BEFORE_CONFIRMATION_OR_SEND: '入力内容を読み戻して確認しました。確認・送信ボタンは操作していません。',
  NETWORK_REQUIRED: '入力に追加の通信が必要なため停止しました。', CAPTCHA: 'CAPTCHAがあります。人の操作が必要です。',
  SALES_PROHIBITED: '営業禁止を検出したため停止しました。', REQUIRED_FIELD_UNKNOWN: '必須項目の入力内容が不足しています。',
  CHOICE_REVIEW_REQUIRED: '選択肢を確認してください。', CONSENT_REVIEW_REQUIRED: '同意文言を確認してください。',
  STRUCTURE_CHANGED: 'フォーム構造が変わりました。再解析してください。', READBACK_MISMATCH: '入力した内容と読み戻した内容が一致しません。',
  FORM_VALIDATION_ERROR: 'フォームの入力チェックでエラーが出ました。', FORM_AMBIGUOUS: '入力先フォームを一つに特定できません。',
  TIMEOUT: '制限時間に達しました。', CORE_CHECK_DENIED: '入力依頼の期限・状態・連絡禁止を確認してください。',
}

export function LiveInputHandoff({ company, profiles, activities = [], prohibited, readOnly, onSave }: {
  company: Company; profiles: FormProfile[]; activities?: Activity[]; prohibited: boolean; readOnly: boolean; onSave: (note: string) => Promise<boolean>
}) {
  const available = profiles.filter(p => p.company_id === company.id)
  const [profileId, setProfileId] = useState(available.find(p => p.is_primary)?.id ?? available[0]?.id ?? '')
  // Profiles load after the company panel. Resolve the default at render time.
  const profile = available.find(p => p.id === profileId) ?? available.find(p => p.is_primary) ?? available[0]
  const [values, setValues] = useState<Record<string, string>>({})
  const [choices, setChoices] = useState<Record<string, string>>({})
  const [consents, setConsents] = useState<Record<string, { label: string; checked: boolean }>>({})
  const [reviewed, setReviewed] = useState(false)
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState('')
  const [issuedTask, setTask] = useState<Pick<LiveTask, 'trialId' | 'requestHash'> | null>(null)
  const [finished, setFinished] = useState<string[]>([])
  const [recorded, setRecorded] = useState<{ status: string; reason: string; fieldsFilled: number; created: string } | null>(null)
  const history = activities.filter(a => a.company_id === company.id).flatMap(a => {
    try {
      const prefix = a.note.startsWith('実ページ入力専用依頼 v1: ') ? '実ページ入力専用依頼 v1: ' : a.note.startsWith('実ページ入力報告 v1: ') ? '実ページ入力報告 v1: ' : ''
      return prefix ? [{ id: a.id, created: a.created_at, prefix, value: JSON.parse(a.note.slice(prefix.length)) }] : []
    } catch { return [] }
  })
  const reported = new Set(history.filter(h => h.prefix === '実ページ入力報告 v1: ').map(h => h.value?.trialId))
  const previous = history.filter(h => h.prefix === '実ページ入力専用依頼 v1: ' && h.value?.project_id === company.project_id && ['PENDING', 'LOADED', 'INPUT_STARTED'].includes(h.value?.state)
    && /^[a-f0-9]{64}$/.test(h.value?.request_hash) && !reported.has(h.id) && !finished.includes(h.id)).sort((a, b) => b.created.localeCompare(a.created))[0]
  const task = issuedTask ?? (previous ? { trialId: previous.id, requestHash: previous.value.request_hash as string } : null)
  const reports = history.filter(h => h.prefix === '実ページ入力報告 v1: ' && h.value?.source === 'PC_REPORTED_UNVERIFIED'
    && h.value?.sent === false && Object.hasOwn(statusLabels, h.value?.status) && typeof h.value?.reason === 'string'
    && Number.isInteger(h.value?.fieldsFilled) && h.value.fieldsFilled >= 0 && h.value.fieldsFilled <= 100)
    .sort((a, b) => b.created.localeCompare(a.created))
  const latest = recorded ?? (reports[0] ? { ...reports[0].value, created: reports[0].created } : null)
  const fields = profile?.fields.filter(f => f.name && !['hidden', 'submit', 'button', 'reset', 'image'].includes(f.field_type)) ?? []
  const disabled = readOnly || prohibited || pending
  async function prepare() {
    if (!profile || !reviewed || disabled || task) return
    setPending(true); setMessage('')
    const plan: LivePlan = { formUrl: profile.form_url, termsConfirmed: true, values: {}, choices: {}, consents: {} }
    for (const field of fields) {
      if (['select', 'select-one', 'radio'].includes(field.field_type)) plan.choices[field.name] = choices[field.name] ?? ''
      else if (field.field_type === 'checkbox') plan.consents[field.name] = consents[field.name] ?? { label: field.label, checked: false }
      else plan.values[field.name] = values[field.name] ?? field.recommended_value ?? ''
    }
    try {
      const issued = await api<Omit<LiveTask, 'serverOrigin'>>(`/companies/${company.id}/live-input-trials`, 'POST', plan)
      const url = URL.createObjectURL(new Blob([JSON.stringify({ ...issued, serverOrigin: window.location.origin })], { type: 'application/json' }))
      const link = document.createElement('a'); link.href = url; link.download = `live-input-${issued.trialId}.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
      setTask({ trialId: issued.trialId, requestHash: issued.requestHash }); setReviewed(false)
      setMessage('PC用依頼を保存しました。有効期間は15分です。PCで「実ページ入力専用」を起動してください。確認・送信は行いません。')
    } catch (e) { setMessage(e instanceof Error ? e.message : '入力専用依頼を作成できませんでした。') }
    finally { setPending(false) }
  }
  async function revoke() {
    if (!task) return
    setPending(true)
    try { await api(`/companies/${company.id}/live-input-trials/${task.trialId}/revoke`, 'POST'); setFinished([...finished, task.trialId]); setTask(null); setMessage('入力依頼を取り消しました。開始済みのローカル入力内容はPCを閉じて破棄してください。') }
    catch { setMessage('取り消しを確認できませんでした。PCで開始しないでください。') } finally { setPending(false) }
  }
  async function record(file: File) {
    if (!task || file.size > 20_000) { setMessage('この依頼の小さい結果JSONを選択してください。'); return }
    try {
      const v = JSON.parse(await file.text())
      if (v.definition !== 'live-form-input-only-v1' || v.companyId !== company.id || v.projectId !== company.project_id || v.trialId !== task.trialId
        || v.requestHash !== task.requestHash || v.sent !== false || v.approvalGranted !== false || v.executionAllowed !== false || v.confirmationReached !== false
        || !['LIVE_INPUT_VERIFIED', 'TECHNICAL_UNKNOWN', 'HUMAN_REQUIRED', 'BLOCKED'].includes(v.status) || typeof v.reason !== 'string' || v.reason.length > 100
        || !Number.isInteger(v.fieldsFilled) || v.fieldsFilled < 0 || v.fieldsFilled > 100
        || v.status === 'LIVE_INPUT_VERIFIED' && (v.fieldsFilled === 0 || v.blockedRequests !== 0 || v.reason !== 'STOP_BEFORE_CONFIRMATION_OR_SEND')) throw Error()
      const safe = { version: 1, trialId: v.trialId, requestHash: v.requestHash, status: v.status, reason: v.reason, fieldsFilled: v.fieldsFilled, sent: false, source: 'PC_REPORTED_UNVERIFIED' }
      if (await onSave('実ページ入力報告 v1: ' + JSON.stringify(safe))) { setRecorded({ ...safe, created: new Date().toISOString() }); setFinished([...finished, task.trialId]); setTask(null); setMessage('未送信のPC報告を記録しました。営業許可・送信承認は変更していません。') }
    } catch { setMessage('この企業・依頼に対応する未送信の結果JSONを選択してください。') }
  }
  return <section className="panel mt-4" aria-label="実フォームのPC入力専用">
    <h3>実フォームへ入力する（送信しない）</h3>
    <p>PCで実ページを表示し、入力前に通信を止めて入力・読み戻しを確認します。確認・送信ボタンは操作しません。</p>
    <p>内容確認 → PCで入力 → 結果確認</p>
    <details><summary>PCでの操作手順</summary><ol className="list-decimal ml-5"><li>入力内容を確認してPC用ファイルを保存</li><li>PCの「実ページ入力専用」を起動してファイルを選択</li><li>結果JSONを選択して、この画面で結果を確認</li></ol>
      <p>スマートフォンでは準備と結果確認ができます。フォームへの入力はPCで行います。</p></details>
    {latest && <article aria-label="最新の入力結果" className="notice"><strong>{statusLabels[latest.status]}</strong>
      <p>{reasonLabels[latest.reason] ?? '未分類の理由です。担当者へ理由コードを伝えてください。'}</p>
      <p>入力確認項目: {latest.fieldsFilled}件</p><details><summary>理由コード・確認日時</summary><p>理由コード: <code className="break-all">{latest.reason}</code></p><p>{new Date(latest.created).toLocaleString('ja-JP')}</p></details>
      <p>PCの自動検証報告です。人の確認・営業許可・送信承認を表すものではありません。</p></article>}
    {prohibited && <p className="notice">営業NG・連絡禁止のため入力依頼を作成できません。</p>}
    {available.length > 0 ? <label className="field">入力先フォーム<select value={profile?.id ?? ''} disabled={disabled || !!task} onChange={e => { setProfileId(e.target.value); setValues({}); setChoices({}); setConsents({}); setReviewed(false) }}>{available.map(p => <option key={p.id} value={p.id}>{p.form_url}</option>)}</select></label> : <p>先にフォーム解析で入力項目を取得してください。</p>}
    {fields.map(field => <label className="field" key={field.id}>{field.label || field.name}{field.required ? '（必須）' : ''}
      {['select', 'select-one', 'radio'].includes(field.field_type) ? <select value={choices[field.name] ?? ''} disabled={disabled || !!task} onChange={e => { setChoices({ ...choices, [field.name]: e.target.value }); setReviewed(false) }}><option value="">人が選択してください</option>{field.options.map((o, i) => <option key={i} value={o.value ?? ''}>{o.label || o.value}</option>)}</select>
        : field.field_type === 'checkbox' ? <><input type="text" aria-label={`${field.name}の同意文言`} placeholder="実ページの同意文言を確認してください" value={consents[field.name]?.label ?? field.label} disabled={disabled || !!task} onChange={e => { setConsents({ ...consents, [field.name]: { checked: consents[field.name]?.checked ?? false, label: e.target.value } }); setReviewed(false) }} /><span><input type="checkbox" aria-label={`${field.name}の同意内容を確認`} checked={consents[field.name]?.checked ?? false} disabled={disabled || !!task} onChange={e => { setConsents({ ...consents, [field.name]: { label: consents[field.name]?.label ?? field.label, checked: e.target.checked } }); setReviewed(false) }} />この同意内容を確認してチェックする</span></>
          : <textarea rows={field.field_type === 'textarea' ? 5 : 2} maxLength={10000} disabled={disabled || !!task} value={values[field.name] ?? field.recommended_value ?? ''} onChange={e => { setValues({ ...values, [field.name]: e.target.value }); setReviewed(false) }} />}
    </label>)}
    {!readOnly && !task && <><label className="field"><span><input type="checkbox" checked={reviewed} disabled={disabled} onChange={e => setReviewed(e.target.checked)} />宛先・入力内容・利用条件を確認しました。入力のみで、送信は許可しません。</span></label><button disabled={disabled || !reviewed || !fields.length} onClick={() => void prepare()}>PC入力専用の依頼を保存</button></>}
    {task && <p className="notice">PC用ファイルは保存済みです（有効期間15分）。PCで実行して結果JSONを選択してください。作り直す場合は、先に入力依頼を取り消してください。</p>}
    {task && <><button disabled={disabled} onClick={() => void revoke()}>入力依頼を取り消す</button><label className="field">PCの未送信結果JSON<input type="file" accept=".json,application/json" disabled={disabled} onChange={e => { const f = e.target.files?.[0]; e.target.value = ''; if (f) void record(f) }} /></label></>}
    {message && <p role="status">{message}</p>}
    <p className="muted">この操作では送信しません。機能が無効と表示された場合は管理者へお問い合わせください。入力内容を含むPC用ファイルは安全に保管してください。</p>
  </section>
}
