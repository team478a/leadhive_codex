import { useCallback, useEffect, useRef, useState } from 'react'
import { api, download, errorMessage } from './api'
import { formMappedKeyLabels } from './formMappingLabels'
import type { FormMappedKey, OperationJob } from './types'

type Field = { id: string; label: string; name: string; field_type: string; required: boolean; mapped_key: string; recommended_value: string; display_value: string; options: { value: string; label: string }[]; suggested_mapped_key?: string; same_organization_suggestion?: boolean; other_organization_suggestion?: boolean }
type ChoiceGroup = { group_id: string; source_hash: string; label: string; supported: boolean; members: { field_id: string; label: string; required: boolean; options: { value: string; label: string }[] }[] }
type SavedGroup = { group_id: string; source_hash: string; label: string; required_observed: boolean; reviewable: boolean; options: { option_id: string; label: string; value: string }[] }
type Item = { company_id: string; company_name: string; profile_id: string; form_url: string; fingerprint: string; fields_hash: string; reason_codes: string[]; ready_confirmation_only: boolean; fields: Field[]; groups: ChoiceGroup[]; saved_groups: SavedGroup[] }
type Queue = { total: number; offset: number; limit: number; items: Item[] }
type QueueSummary = { total: number; by_readiness_reason: Record<string, number>; by_review_message: { message: string; count: number }[]; unresolved_required_labels: { normalized_label: string; field_type: string; form_count: number; example_labels: string[] }[]; consent_fields: { privacy_only_single_checkbox: number; mixed_privacy_newsletter: number; other: number } }
type PolicyStatus = { policy: string; conditions: string[]; enabled: boolean; enabled_at: string | null; can_manage: boolean; active_job: OperationJob | null }
const keys: FormMappedKey[] = ['company_name', 'department', 'position', 'contact_name', 'last_name', 'first_name', 'furigana', 'last_name_furigana', 'first_name_furigana', 'email', 'phone', 'phone_area_code', 'phone_exchange_code', 'phone_line_number', 'postal_code', 'postal_code_first', 'postal_code_last', 'prefecture', 'city', 'address', 'building', 'website', 'contact_category', 'contact_method', 'subject', 'message', 'privacy_consent', 'newsletter_consent', 'other', 'unknown']

export function FormReviewQueue({ projectId, canWrite, canManagePolicy }: { projectId: string; canWrite: boolean; canManagePolicy: boolean }) {
  const [items, setItems] = useState<Item[]>([]); const [total, setTotal] = useState(0); const [index, setIndex] = useState(0)
  const [summary, setSummary] = useState<QueueSummary | null>(null)
  const [policy, setPolicy] = useState<PolicyStatus | null>(null)
  const [policyAccepted, setPolicyAccepted] = useState(false); const [resetAccepted, setResetAccepted] = useState(false)
  const [policyBusy, setPolicyBusy] = useState(false)
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [notice, setNotice] = useState('')
  const [mapping, setMapping] = useState<Record<string, string>>({}); const [values, setValues] = useState<Record<string, string>>({})
  const [checked, setChecked] = useState<Record<string, boolean>>({}); const [rule, setRule] = useState<Record<string, string>>({})
  const [noProhibition, setNoProhibition] = useState(false)
  const [showTechnicalFields, setShowTechnicalFields] = useState(false)
  const [doNotSendReason, setDoNotSendReason] = useState('WRONG_PURPOSE')
  const item = items[index]
  const skippedProfileIds = useRef(new Set<string>())
  const skip = useCallback(() => { if (item) skippedProfileIds.current.add(item.profile_id); setIndex(v => Math.min(v + 1, items.length - 1)); setNotice('') }, [item, items.length])
  const load = useCallback(async () => {
    if (!projectId) return
    setBusy(true); setError('')
    try {
      const [result, summaryResult, policyResult] = await Promise.all([
        api<Queue>(`/projects/${projectId}/form-review-queue`),
        api<QueueSummary>(`/projects/${projectId}/form-review-queue/summary`),
        api<PolicyStatus>(`/projects/${projectId}/consent-policy`),
      ])
      const queueItems = Array.isArray(result?.items) ? result.items : []
      const sortedItems = [...queueItems].sort((a, b) => Number(skippedProfileIds.current.has(a.profile_id)) - Number(skippedProfileIds.current.has(b.profile_id)))
      setItems(sortedItems); setTotal(Number.isFinite(result?.total) ? result.total : sortedItems.length)
      setSummary(summaryResult)
      setPolicy(policyResult)
      setIndex(Math.max(0, sortedItems.findIndex(queueItem => !skippedProfileIds.current.has(queueItem.profile_id))))
    }
    catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }, [projectId])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (!policy?.active_job || !['queued', 'running'].includes(policy.active_job.status)) return
    const timer = window.setInterval(() => {
      api<PolicyStatus>(`/projects/${projectId}/consent-policy`).then(result => {
        const wasActive = Boolean(policy.active_job)
        setPolicy(result)
        if (wasActive && !result.active_job) void load()
      }).catch(cause => setError(errorMessage(cause)))
    }, 2000)
    return () => window.clearInterval(timer)
  }, [load, policy?.active_job, projectId])
  const changePolicy = useCallback(async (action: 'enable' | 'disable' | 'reset') => {
    if (!policy || policyBusy || !canManagePolicy) return
    setPolicyBusy(true); setError(''); setNotice('')
    try {
      if (action === 'disable') {
        setPolicy(await api<PolicyStatus>(`/projects/${projectId}/consent-policy/disable`, 'POST'))
        setNotice('自動判断を無効にしました。すでに決めた欄は保持しています。')
      } else {
        const result = await api<{ setting: PolicyStatus }>(`/projects/${projectId}/consent-policy/${action}`, 'POST', { policy: policy.policy, accepted: action === 'enable' ? policyAccepted : resetAccepted })
        setPolicy(result.setting)
        setNotice(action === 'enable' ? '同意欄の自動判断を開始しました。送信・承認は行いません。' : 'このルールで決めた欄の取り消しを開始しました。')
        if (action === 'enable') setPolicyAccepted(false); else setResetAccepted(false)
      }
    } catch (cause) { setError(errorMessage(cause)) } finally { setPolicyBusy(false) }
  }, [canManagePolicy, policy, policyAccepted, policyBusy, projectId, resetAccepted])
  const canConfirm = Boolean(item && item.groups.every(g => g.supported) && item.saved_groups.every(g => g.reviewable))
  useEffect(() => {
    if (!item) return
    setMapping(Object.fromEntries(item.fields.map(f => [f.id, f.suggested_mapped_key || f.mapped_key])))
    setValues(Object.fromEntries(item.fields.map(f => [f.id, f.recommended_value || ''])))
    setChecked({}); setRule(Object.fromEntries([...item.groups.map(g => [g.group_id, 'AT_LEAST_ONE']), ...item.saved_groups.map(g => [g.group_id, g.required_observed ? 'AT_LEAST_ONE' : 'OPTIONAL'])]))
    setNoProhibition(false); setDoNotSendReason('WRONG_PURPOSE'); setShowTechnicalFields(false)
  }, [item])
  const submit = useCallback(async (action: 'CONFIRM' | 'DO_NOT_SEND') => {
    if (!item || busy || !canWrite) return
    setBusy(true); setError(''); setNotice('')
    try {
      await api(`/form-profiles/${item.profile_id}/review-decision`, 'POST', {
        action, expected_fingerprint: item.fingerprint, expected_fields_hash: item.fields_hash,
        confirmed_no_sales_prohibition: noProhibition,
        do_not_send_reason: action === 'DO_NOT_SEND' ? doNotSendReason : undefined,
        field_decisions: item.fields.map(f => ({ field_id: f.id, mapped_key: mapping[f.id] || f.mapped_key, recommended_value: mapping[f.id] === 'privacy_consent' ? '' : values[f.id] || '', consent_checked: mapping[f.id] === 'privacy_consent' && checked[f.id] === true })),
        group_decisions: item.groups.map(g => ({ group_id: g.group_id, expected_source_hash: g.source_hash, rule: rule[g.group_id] === 'EXACTLY_ONE' ? 'EXACTLY_ONE' : 'AT_LEAST_ONE', selections: g.members.flatMap(m => values[m.field_id] ? [{ field_id: m.field_id, value: values[m.field_id] }] : []) })),
        saved_group_decisions: item.saved_groups.map(g => ({ group_id: g.group_id, expected_source_hash: g.source_hash, rule: rule[g.group_id] || (g.required_observed ? 'AT_LEAST_ONE' : 'OPTIONAL'), options: g.options.map(o => ({ option_id: o.option_id, checked: checked[o.option_id] === true })) })),
      })
      setNotice(action === 'CONFIRM' ? '確認を記録しました。送信・承認は行っていません。' : 'この企業を連絡対象外にしました。')
      const remaining = items.filter(candidate => candidate.profile_id !== item.profile_id)
      setItems(remaining)
      setTotal(value => Math.max(0, value - 1))
      setIndex(value => Math.min(value, Math.max(0, remaining.length - 1)))
      if (remaining.length === 0 && total > 1) await load()
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }, [busy, canWrite, checked, doNotSendReason, item, items, load, mapping, noProhibition, rule, total, values])
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (!item || event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.target instanceof HTMLElement && ['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON'].includes(event.target.tagName)) return
      if (event.key.toLowerCase() === 's' && canWrite) { event.preventDefault(); skip() }
      if (event.key === 'Enter' && canWrite && noProhibition) { event.preventDefault(); void submit('CONFIRM') }
    }
    window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey)
  }, [canWrite, item, noProhibition, skip, submit])
  const visibleFields = item?.fields.filter(field => field.field_type !== 'hidden') ?? []
  const technicalFields = item?.fields.filter(field => field.field_type === 'hidden') ?? []
  const renderField = (field: Field) => <div className="border-t py-3" key={field.id}><strong>{field.label || field.name || '名称不明'}{field.required ? '（必須）' : ''}</strong>
    <label className="field mt-2">対応項目<select disabled={!canWrite || busy} value={mapping[field.id] || field.mapped_key} onChange={event => setMapping(value => ({ ...value, [field.id]: event.target.value }))}>{keys.map(key => <option value={key} key={key}>{formMappedKeyLabels[key]}</option>)}</select></label>
    {field.same_organization_suggestion && <p className="muted text-xs">同一組織の別フォームで確認された候補：{formMappedKeyLabels[field.suggested_mapped_key as FormMappedKey] ?? field.suggested_mapped_key}。今回のフォームでも確認してください。</p>}
    {field.other_organization_suggestion && <p className="muted text-xs">他の利用企業で確認された候補（提案）：{formMappedKeyLabels[field.suggested_mapped_key as FormMappedKey] ?? field.suggested_mapped_key}。この利用企業では未確認です。</p>}
    {mapping[field.id] === 'privacy_consent' ? <label className="mt-2 block"><input type="checkbox" checked={checked[field.id] === true} onChange={event => setChecked(value => ({ ...value, [field.id]: event.target.checked }))} /> 必須の同意内容を読み、同意チェックを明示的に選択</label>
      : mapping[field.id] === 'newsletter_consent' ? <p className="muted">メルマガ同意は常に未選択です。</p>
        : field.options?.length ? <label className="field mt-2">選択値<select value={values[field.id] || ''} onChange={event => setValues(value => ({ ...value, [field.id]: event.target.value }))}><option value="">未選択</option>{field.options.map((option, optionIndex) => <option key={`${option.value}-${optionIndex}`} value={option.value}>{option.label || option.value}</option>)}</select></label>
          : <p className="muted mt-1">値プレビュー：{field.display_value || '（空）'}</p>}
  </div>
  return <section className="panel mb-5" aria-label="フォーム確認キュー">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h2>フォーム確認キュー</h2><p className="muted mt-2 text-sm">保存済み解析の人手確認です。外部アクセス、AI、承認、送信は行いません。</p></div><button className="secondary" disabled={busy} onClick={() => void load()}>更新</button></div>
    {error && <p role="alert" className="error mt-3">{error}</p>}{notice && <p role="status" className="mt-3">{notice}</p>}
    {summary && <section className="mt-4 border-t pt-4" aria-label="フォーム確認の集計">
      <div className="flex flex-wrap items-center justify-between gap-2"><h3>確認が必要な理由の集計（{summary.total}件）</h3><button type="button" className="secondary" onClick={() => void download(`/projects/${projectId}/form-review-queue/summary?format=csv`, 'form-review-queue-summary.csv').catch(cause => setError(errorMessage(cause)))}>集計CSVをダウンロード</button></div>
      <div className="mt-3 grid gap-3 md:grid-cols-3">
        <div><strong>理由別</strong><ul className="mt-1">{Object.entries(summary.by_readiness_reason).map(([reason, count]) => <li key={reason}>{reason}: {count}件</li>)}</ul></div>
        <div><strong>未解決の項目名（上位10件）</strong><ul className="mt-1">{summary.unresolved_required_labels.slice(0, 10).map(row => <li key={`${row.normalized_label}-${row.field_type}`}>{row.normalized_label || '名称不明'}（{row.field_type}）: {row.form_count}フォーム</li>)}</ul></div>
        <div><strong>同意欄の内訳</strong><ul className="mt-1"><li>個人情報のみ・単一チェック: {summary.consent_fields.privacy_only_single_checkbox}件</li><li>個人情報とメルマガが混在: {summary.consent_fields.mixed_privacy_newsletter}件</li><li>その他: {summary.consent_fields.other}件</li></ul></div>
      </div>
    </section>}
    {policy && <section className="mt-4 border-t pt-4" aria-label="同意欄の自動判断設定">
      <div className="flex flex-wrap items-center justify-between gap-2"><h3>同意欄の自動判断</h3><span className="badge">{policy.enabled ? '有効' : '無効'}</span></div>
      <p className="muted mt-2 text-sm">{policy.policy}。送信・承認は行わず、送信可否の確認は通常どおり残ります。</p>
      <ol className="mt-3 list-decimal pl-5 text-sm">{policy.conditions.map(condition => <li key={condition}>{condition}</li>)}</ol>
      {policy.active_job && <p className="mt-3" role="status">処理中 {policy.active_job.processed_count}/{policy.active_job.total_count}フォーム（成功 {policy.active_job.success_count}・失敗 {policy.active_job.failed_count}）</p>}
      {canManagePolicy && !policy.enabled && <><label className="mt-3 block"><input type="checkbox" checked={policyAccepted} onChange={event => setPolicyAccepted(event.target.checked)} /> 上記の条件に当てはまる同意欄を、プロジェクトの方針として自動でチェックすることを承認します</label><button className="mt-3" type="button" disabled={!policyAccepted || policyBusy || Boolean(policy.active_job)} onClick={() => void changePolicy('enable')}>承認して有効にする</button></>}
      {canManagePolicy && policy.enabled && <button className="secondary mt-3" type="button" disabled={policyBusy || Boolean(policy.active_job)} onClick={() => void changePolicy('disable')}>自動判断を無効にする</button>}
      {canManagePolicy && <details className="mt-4"><summary>このルールで決めた欄を未決定に戻す</summary><p className="muted mt-2 text-sm">手動で決めた欄には触れません。自動判断が有効なままなら、次回の解析時に条件へ一致する欄へ再適用されます。</p><label className="mt-2 block"><input type="checkbox" checked={resetAccepted} onChange={event => setResetAccepted(event.target.checked)} /> POLICYで決めた欄だけを未決定に戻すことを確認しました</label><button className="secondary mt-3" type="button" disabled={!resetAccepted || policyBusy || Boolean(policy.active_job)} onClick={() => void changePolicy('reset')}>未決定に戻す</button></details>}
      {!canManagePolicy && <p className="muted mt-3 text-sm">この設定はプロジェクト所有者だけが変更できます。</p>}
    </section>}
    {busy && <p className="mt-3">読み込み中…</p>}{!busy && !item && <p className="mt-3">確認対象はありません（{total}件）。</p>}
    {item && <div className="mt-4">
      <p className="muted">{index + 1}件目 / {total}件 · {item.reason_codes.join('、')}</p><h3 className="mt-2">{item.company_name}</h3>
      <a className="break-all text-sm" href={item.form_url} target="_blank" rel="noreferrer">フォームを開いて目視確認 ↗</a>
      {!item.ready_confirmation_only && <><p className="mt-3">解析された入力項目・値</p>
      {visibleFields.map(renderField)}
      {technicalFields.length > 0 && <div className="border-t py-3"><button type="button" className="secondary" onClick={() => setShowTechnicalFields(value => !value)}>{showTechnicalFields ? '仕組み用の項目を隠す' : `仕組み用の項目を表示（${technicalFields.length}件）`}</button>{showTechnicalFields && <div className="mt-3">{technicalFields.map(renderField)}</div>}</div>}
      {item.groups.map(g => <div className="border-t py-3" key={g.group_id}><strong>{g.label}（同名選択項目）</strong>{!g.supported ? <p>安全に扱えない構造のため、この項目は確定できません。</p> : <><label className="field mt-2">選択条件<select value={rule[g.group_id] || 'AT_LEAST_ONE'} onChange={e => setRule(v => ({ ...v, [g.group_id]: e.target.value }))}><option value="AT_LEAST_ONE">1つ以上</option><option value="EXACTLY_ONE">ちょうど1つ</option></select></label>{g.members.map(m => <label className="field mt-2" key={m.field_id}>{m.label}{m.required ? '（必須）' : ''}<select value={values[m.field_id] || ''} onChange={e => setValues(v => ({ ...v, [m.field_id]: e.target.value }))}><option value="">未選択</option>{m.options.map((o, i) => <option key={`${o.value}-${i}`} value={o.value}>{o.label || o.value}</option>)}</select></label>)}</>}</div>)}
      {item.saved_groups.map(g => <div className="border-t py-3" key={g.group_id}><strong>{g.label}（保存済みチェック選択肢）</strong>{!g.reviewable ? <p>保存データの不足・曖昧さがあるため、この項目は安全に確認できません。</p> : <><label className="field mt-2">確認した条件<select value={rule[g.group_id] || (g.required_observed ? 'AT_LEAST_ONE' : 'OPTIONAL')} onChange={e => setRule(v => ({ ...v, [g.group_id]: e.target.value }))}><option value="OPTIONAL">任意</option><option value="AT_LEAST_ONE">1つ以上</option><option value="EXACTLY_ONE">ちょうど1つ</option></select></label>{g.options.map(o => <label className="mt-2 block" key={o.option_id}><input type="checkbox" checked={checked[o.option_id] === true} onChange={e => setChecked(v => ({ ...v, [o.option_id]: e.target.checked }))} /> {o.label || o.value}</label>)}</>}</div>)}</>}
      <label className="mt-4 block"><input type="checkbox" checked={noProhibition} onChange={e => setNoProhibition(e.target.checked)} /> {item.ready_confirmation_only ? 'フォームを開いて営業お断りの表記がないことを確認' : 'フォームを開いて確認し、営業お断り・営業禁止の記載がないことを確認しました'}</label>
      <label className="field mt-4">送信しない理由<select disabled={!canWrite || busy} value={doNotSendReason} onChange={e => setDoNotSendReason(e.target.value)}><option value="SALES_PROHIBITED">営業お断り・営業禁止</option><option value="WRONG_PURPOSE">用途違い</option><option value="OTHER">その他</option></select></label>
      <div className="actions mt-4 flex-wrap"><button disabled={!canWrite || busy || !noProhibition || !canConfirm} onClick={() => void submit('CONFIRM')}>確認して次へ</button><button className="secondary" disabled={busy} onClick={skip}>スキップ（S）</button><button className="secondary" disabled={!canWrite || busy} onClick={() => void submit('DO_NOT_SEND')}>送信しない・連絡対象外</button></div>
      {!canWrite && <p className="muted mt-2">閲覧のみです。確認記録は編集者以上が行えます。</p>}
    </div>}
  </section>
}
