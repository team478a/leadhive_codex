import { useEffect, useState } from 'react'
import { api } from './api'

type Group = {
  group_id: string; label: string; source_hash: string; review_supported: boolean
  review_status: string; expires_at: string | null; recorded_rule: string | null
  review_current: boolean; present_in_saved_fields: boolean; check_reasons: string[]; evaluated_at: string
  recorded_options: { option_id: string; label: string; checked: boolean }[]
  options: { option_id: string; label: string; value: string }[]
}
const statuses: Record<string, string> = { NOT_REVIEWED: '未記録', RECORDED: '確認記録あり（送信承認ではありません）', STALE: '変更あり・再確認が必要', EXPIRED: '期限切れ・再確認が必要', REMOVED: '項目の削除・名称変更を検出' }
const reasons: Record<string, string> = { REVIEW_MISSING: '人による確認記録がありません。', SOURCE_CHANGED: '項目・選択肢・フォーム構造が記録時から変わっています。', PROFILE_UNVERIFIED: 'フォームの保存情報が古いか、解析エラーがあります。', REVIEW_EXPIRED: '確認記録の24時間の期限が切れています。', REVIEW_UNSUPPORTED: '同意項目・不明な選択値などがあるため記録できません。', GROUP_REMOVED: '記録時の項目は現在の保存情報にありません。削除または名称変更の可能性があります。' }

function Editor({ group, readOnly, busy, onSave }: { group: Group; readOnly: boolean; busy: boolean; onSave: (rule: string, selected: Set<string>) => void }) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [rule, setRule] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  return <article className="panel mt-3">
    <strong>{group.label}</strong><p className="muted mt-2">{statuses[group.review_status] ?? '未確認'}</p>
    <ul className="muted mt-2">{group.check_reasons.map(reason => <li key={reason}>{reasons[reason] ?? '再確認が必要です。'}</li>)}</ul>
    {group.expires_at && <p className="muted">記録の期限：{new Date(group.expires_at).toLocaleString('ja-JP')}</p>}
    {group.recorded_options.length > 0 && <details className="mt-2"><summary>前回の確認内容（履歴）</summary>{group.recorded_options.map(o => <p key={o.option_id}>{o.label}：{o.checked ? '選択' : '未選択'}</p>)}</details>}
    {!group.present_in_saved_fields ? <p className="notice mt-2">過去の履歴としてのみ表示します。現在の項目で改めて確認してください。</p> : !group.review_supported ? <p className="notice mt-2">同意項目や不明な選択値があるため記録できません。</p> : readOnly ? <p className="muted mt-2">確認記録は所有者または編集者が行います。</p> : <>
      <label className="mt-3">確認した選択条件<select aria-label={`${group.label}の選択条件`} disabled={busy} value={rule} onChange={e => { setRule(e.target.value); setConfirmed(false) }}>
        <option value="">元フォームで確認して選択</option><option value="OPTIONAL">任意（未選択も可）</option><option value="AT_LEAST_ONE">最低1つ選択</option><option value="EXACTLY_ONE">1つだけ選択</option>
      </select></label>
      {group.options.map(o => <label className="mt-3 flex items-start gap-2" key={o.option_id}><input type="checkbox" disabled={busy} checked={selected.has(o.option_id)} onChange={e => { const next = new Set(selected); if (e.target.checked) next.add(o.option_id); else next.delete(o.option_id); setSelected(next); setConfirmed(false) }} />{o.label || o.value}</label>)}
      <label className="mt-3 flex items-start gap-2"><input type="checkbox" disabled={busy} checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />元フォームで、同じグループであること・選択条件・全選択肢の選択と未選択・同意ではない用途を確認しました</label>
      <button className="secondary mt-3" disabled={busy || !confirmed || !rule || (rule === 'EXACTLY_ONE' && selected.size !== 1) || (rule === 'AT_LEAST_ONE' && selected.size === 0)} onClick={() => onSave(rule, selected)}>複数選択の確認を記録</button>
    </>}
  </article>
}

export function CompanyFormSavedChoiceReviews({ profileId, readOnly, onSaved }: { profileId: string; readOnly: boolean; onSaved?: () => Promise<void> }) {
  const [groups, setGroups] = useState<Group[] | null>(null)
  const [needsOnly, setNeedsOnly] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const path = `/form-profiles/${profileId}/saved-choice-reviews`
  useEffect(() => {
    let active = true
    setGroups(null); setError('')
    api<Group[]>(path).then(v => { if (active) setGroups(v) }).catch(e => { if (active) setError(e instanceof Error ? e.message : '取得できません。') })
    return () => { active = false }
  }, [path])
  async function load() {
    setBusy(true); setError('')
    try { setGroups(await api<Group[]>(path)) } catch (e) { setGroups(null); setError(e instanceof Error ? e.message : '取得できません。') } finally { setBusy(false) }
  }
  async function save(group: Group, rule: string, selected: Set<string>) {
    setBusy(true); setError('')
    try { setGroups(await api<Group[]>(`${path}/${group.group_id}`, 'POST', { expected_source_hash: group.source_hash, rule, options: group.options.map(o => ({ option_id: o.option_id, checked: selected.has(o.option_id) })), membership_and_rule_confirmed: true, non_consent_purpose_confirmed: true })); await onSaved?.() }
    catch (e) { setGroups(null); setError(e instanceof Error ? e.message : '記録できません。読み直してください。') } finally { setBusy(false) }
  }
  return <section className="mt-4" aria-label="複数選択の確認記録">
    <h3>複数選択の確認記録</h3><p className="notice mt-2">24時間有効の確認履歴です。項目変更後は再確認が必要です。入力値・営業許可・送信承認には反映しません。</p>
    <button className="secondary mt-3" disabled={busy} onClick={load}>複数選択を読み直す</button>
    {error && <p className="error mt-3" role="alert">{error}</p>}
    {groups === null && !error && <p className="muted mt-3">確認履歴を読み込み中…</p>}
    {groups && <>
      <section className="notice mt-3" aria-label="確認履歴の点検結果">
        <strong>現在の項目 {groups.filter(g => g.present_in_saved_fields).length}件 ／ 一致する確認 {groups.filter(g => g.review_current).length}件 ／ 要確認 {groups.filter(g => !g.review_current).length}件</strong>
        <p className="mt-2">項目変更 {groups.filter(g => g.review_status === 'STALE').length}件 ／ 期限切れ {groups.filter(g => g.check_reasons.includes('REVIEW_EXPIRED')).length}件 ／ 消失した項目 {groups.filter(g => !g.present_in_saved_fields).length}件</p>
        <p className="muted text-sm mt-2">取得時点の保存情報との比較です。現在のサイトとの一致・営業許可・送信対応を保証しません。</p>
        {groups[0]?.evaluated_at && <p className="muted text-sm">点検日時：{new Date(groups[0].evaluated_at).toLocaleString('ja-JP')}</p>}
      </section>
      <label className="mt-3 flex items-start gap-2"><input type="checkbox" checked={needsOnly} onChange={e => setNeedsOnly(e.target.checked)} />再確認が必要な項目だけ表示</label>
      {groups.length === 0 && <p className="muted mt-3">保存済みの候補項目・確認履歴はありません。</p>}
      {needsOnly && groups.length > 0 && groups.every(g => g.review_current) && <p className="muted mt-3">取得時点で再確認が必要な項目はありません。</p>}
      {groups.filter(g => !needsOnly || !g.review_current).map(group => <Editor key={`${profileId}:${group.group_id}:${group.source_hash}:${group.expires_at}:${group.review_status}`} group={group} readOnly={readOnly} busy={busy} onSave={(rule, selected) => void save(group, rule, selected)} />)}
    </>}
  </section>
}
