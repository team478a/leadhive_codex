import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errorMessage } from './api'

type Field = { id: string; label: string; name: string; field_type: string; required: boolean; mapped_key: string; recommended_value: string; display_value: string; options: { value: string; label: string }[] }
type ChoiceGroup = { group_id: string; source_hash: string; label: string; supported: boolean; members: { field_id: string; label: string; required: boolean; options: { value: string; label: string }[] }[] }
type SavedGroup = { group_id: string; source_hash: string; label: string; required_observed: boolean; reviewable: boolean; options: { option_id: string; label: string; value: string }[] }
type Item = { company_id: string; company_name: string; profile_id: string; form_url: string; fingerprint: string; fields_hash: string; reason_codes: string[]; fields: Field[]; groups: ChoiceGroup[]; saved_groups: SavedGroup[] }
type Queue = { total: number; offset: number; limit: number; items: Item[] }
const keys = ['company_name', 'department', 'position', 'contact_name', 'last_name', 'first_name', 'furigana', 'email', 'phone', 'postal_code', 'prefecture', 'city', 'address', 'building', 'website', 'contact_category', 'contact_method', 'subject', 'message', 'privacy_consent', 'newsletter_consent', 'other', 'unknown']

export function FormReviewQueue({ projectId, canWrite }: { projectId: string; canWrite: boolean }) {
  const [items, setItems] = useState<Item[]>([]); const [total, setTotal] = useState(0); const [index, setIndex] = useState(0)
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [notice, setNotice] = useState('')
  const [mapping, setMapping] = useState<Record<string, string>>({}); const [values, setValues] = useState<Record<string, string>>({})
  const [checked, setChecked] = useState<Record<string, boolean>>({}); const [rule, setRule] = useState<Record<string, string>>({})
  const [noProhibition, setNoProhibition] = useState(false)
  const [doNotSendReason, setDoNotSendReason] = useState('WRONG_PURPOSE')
  const item = items[index]
  const skippedProfileIds = useRef(new Set<string>())
  const skip = useCallback(() => { if (item) skippedProfileIds.current.add(item.profile_id); setIndex(v => Math.min(v + 1, items.length - 1)); setNotice('') }, [item, items.length])
  const load = useCallback(async () => {
    if (!projectId) return
    setBusy(true); setError('')
    try {
      const result = await api<Queue>(`/projects/${projectId}/form-review-queue`)
      const queueItems = Array.isArray(result?.items) ? result.items : []
      const sortedItems = [...queueItems].sort((a, b) => Number(skippedProfileIds.current.has(a.profile_id)) - Number(skippedProfileIds.current.has(b.profile_id)))
      setItems(sortedItems); setTotal(Number.isFinite(result?.total) ? result.total : sortedItems.length)
      setIndex(Math.max(0, sortedItems.findIndex(queueItem => !skippedProfileIds.current.has(queueItem.profile_id))))
    }
    catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }, [projectId])
  useEffect(() => { void load() }, [load])
  const canConfirm = Boolean(item && item.groups.every(g => g.supported) && item.saved_groups.every(g => g.reviewable))
  useEffect(() => {
    if (!item) return
    setMapping(Object.fromEntries(item.fields.map(f => [f.id, f.mapped_key])))
    setValues(Object.fromEntries(item.fields.map(f => [f.id, f.recommended_value || ''])))
    setChecked({}); setRule(Object.fromEntries([...item.groups.map(g => [g.group_id, 'AT_LEAST_ONE']), ...item.saved_groups.map(g => [g.group_id, g.required_observed ? 'AT_LEAST_ONE' : 'OPTIONAL'])]))
    setNoProhibition(false); setDoNotSendReason('WRONG_PURPOSE')
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
      await load()
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }, [busy, canWrite, checked, doNotSendReason, item, load, mapping, noProhibition, rule, values])
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (!item || event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.target instanceof HTMLElement && ['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON'].includes(event.target.tagName)) return
      if (event.key.toLowerCase() === 's' && canWrite) { event.preventDefault(); skip() }
      if (event.key === 'Enter' && canWrite && noProhibition) { event.preventDefault(); void submit('CONFIRM') }
    }
    window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey)
  }, [canWrite, item, noProhibition, skip, submit])
  return <section className="panel mb-5" aria-label="フォーム確認キュー">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h2>フォーム確認キュー</h2><p className="muted mt-2 text-sm">保存済み解析の人手確認です。外部アクセス、AI、承認、送信は行いません。</p></div><button className="secondary" disabled={busy} onClick={() => void load()}>更新</button></div>
    {error && <p role="alert" className="error mt-3">{error}</p>}{notice && <p role="status" className="mt-3">{notice}</p>}
    {busy && <p className="mt-3">読み込み中…</p>}{!busy && !item && <p className="mt-3">確認対象はありません（{total}件）。</p>}
    {item && <div className="mt-4">
      <p className="muted">{index + 1}件目 / {total}件 · {item.reason_codes.join('、')}</p><h3 className="mt-2">{item.company_name}</h3>
      <a className="break-all text-sm" href={item.form_url} target="_blank" rel="noreferrer">フォームを開いて目視確認 ↗</a>
      <p className="mt-3">解析された入力項目・値</p>
      {item.fields.map(f => <div className="border-t py-3" key={f.id}><strong>{f.label || f.name || '名称不明'}{f.required ? '（必須）' : ''}</strong>
        <label className="field mt-2">対応項目<select disabled={!canWrite || busy} value={mapping[f.id] || f.mapped_key} onChange={e => setMapping(v => ({ ...v, [f.id]: e.target.value }))}>{keys.map(k => <option value={k} key={k}>{k}</option>)}</select></label>
        {mapping[f.id] === 'privacy_consent' ? <label className="mt-2 block"><input type="checkbox" checked={checked[f.id] === true} onChange={e => setChecked(v => ({ ...v, [f.id]: e.target.checked }))} /> 必須の同意内容を読み、同意チェックを明示的に選択</label>
          : mapping[f.id] === 'newsletter_consent' ? <p className="muted">メルマガ同意は常に未選択です。</p>
            : f.options?.length ? <label className="field mt-2">選択値<select value={values[f.id] || ''} onChange={e => setValues(v => ({ ...v, [f.id]: e.target.value }))}><option value="">未選択</option>{f.options.map((o, i) => <option key={`${o.value}-${i}`} value={o.value}>{o.label || o.value}</option>)}</select></label>
              : <p className="muted mt-1">値プレビュー：{f.display_value || '（空）'}</p>}
      </div>)}
      {item.groups.map(g => <div className="border-t py-3" key={g.group_id}><strong>{g.label}（同名選択項目）</strong>{!g.supported ? <p>安全に扱えない構造のため、この項目は確定できません。</p> : <><label className="field mt-2">選択条件<select value={rule[g.group_id] || 'AT_LEAST_ONE'} onChange={e => setRule(v => ({ ...v, [g.group_id]: e.target.value }))}><option value="AT_LEAST_ONE">1つ以上</option><option value="EXACTLY_ONE">ちょうど1つ</option></select></label>{g.members.map(m => <label className="field mt-2" key={m.field_id}>{m.label}{m.required ? '（必須）' : ''}<select value={values[m.field_id] || ''} onChange={e => setValues(v => ({ ...v, [m.field_id]: e.target.value }))}><option value="">未選択</option>{m.options.map((o, i) => <option key={`${o.value}-${i}`} value={o.value}>{o.label || o.value}</option>)}</select></label>)}</>}</div>)}
      {item.saved_groups.map(g => <div className="border-t py-3" key={g.group_id}><strong>{g.label}（保存済みチェック選択肢）</strong>{!g.reviewable ? <p>保存データの不足・曖昧さがあるため、この項目は安全に確認できません。</p> : <><label className="field mt-2">確認した条件<select value={rule[g.group_id] || (g.required_observed ? 'AT_LEAST_ONE' : 'OPTIONAL')} onChange={e => setRule(v => ({ ...v, [g.group_id]: e.target.value }))}><option value="OPTIONAL">任意</option><option value="AT_LEAST_ONE">1つ以上</option><option value="EXACTLY_ONE">ちょうど1つ</option></select></label>{g.options.map(o => <label className="mt-2 block" key={o.option_id}><input type="checkbox" checked={checked[o.option_id] === true} onChange={e => setChecked(v => ({ ...v, [o.option_id]: e.target.checked }))} /> {o.label || o.value}</label>)}</>}</div>)}
      <label className="mt-4 block"><input type="checkbox" checked={noProhibition} onChange={e => setNoProhibition(e.target.checked)} /> フォームを開いて確認し、営業お断り・営業禁止の記載がないことを確認しました</label>
      <label className="field mt-4">送信しない理由<select disabled={!canWrite || busy} value={doNotSendReason} onChange={e => setDoNotSendReason(e.target.value)}><option value="SALES_PROHIBITED">営業お断り・営業禁止</option><option value="WRONG_PURPOSE">用途違い</option><option value="OTHER">その他</option></select></label>
      <div className="actions mt-4 flex-wrap"><button disabled={!canWrite || busy || !noProhibition || !canConfirm} onClick={() => void submit('CONFIRM')}>確認して次へ</button><button className="secondary" disabled={busy} onClick={skip}>スキップ（S）</button><button className="secondary" disabled={!canWrite || busy} onClick={() => void submit('DO_NOT_SEND')}>送信しない・連絡対象外</button></div>
      {!canWrite && <p className="muted mt-2">閲覧のみです。確認記録は編集者以上が行えます。</p>}
    </div>}
  </section>
}
