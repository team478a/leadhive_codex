import { useEffect, useState } from 'react'
import { api } from './api'

type Group = {
  group_id: string; label: string; source_hash: string; review_supported: boolean
  review_status: 'NOT_REVIEWED' | 'RECORDED' | 'STALE' | 'EXPIRED'
  rule: 'AT_LEAST_ONE' | 'EXACTLY_ONE' | null
  saved_selections: Record<string, string>
  requirement_scope_status?: 'UNCONFIRMED' | 'HUMAN_RECORDED'
  member_count?: number; option_count?: number; individual_required_count?: number
  minimum_selected?: number | null; maximum_selected?: number | null
  members: { field_id: string; name: string; individually_required?: boolean; options: { value: string; label?: string }[] }[]
}
const statuses = { NOT_REVIEWED: '未確認', RECORDED: '条件・選択を記録済み', STALE: '項目変更・再確認が必要', EXPIRED: '期限切れ・再確認が必要' }

function GroupEditor({ group, readOnly, saving, onSave }: { group: Group; readOnly: boolean; saving: boolean; onSave: (rule: string, selections: { field_id: string; value: string }[]) => void }) {
  const [rule, setRule] = useState('')
  const [choices, setChoices] = useState<Record<string, string>>({})
  const [confirmed, setConfirmed] = useState(false)
  const selected = group.members.filter(member => choices[member.field_id]).map(member => ({ field_id: member.field_id, value: choices[member.field_id] }))
  return <article className="panel mt-3" aria-label="必須グループの確認">
    <strong>{group.label || '必須選択グループ'}</strong>
    <p className="muted mt-2">{statuses[group.review_status]}</p>
    <section className="notice mt-2" aria-label="必須範囲の確認状況">
      <p>{group.member_count ?? group.members.length}項目・{group.option_count ?? group.members.reduce((count, member) => count + member.options.length, 0)}選択肢</p>
      {group.requirement_scope_status === 'HUMAN_RECORDED' && group.review_status === 'RECORDED'
        ? <p>必須範囲：人が条件を記録済み（送信承認ではありません）</p>
        : <p>必須範囲：未確定（任意ではありません）。各欄すべてを必須として選ぶのではなく、対象範囲と必要な選択数を確認してください。</p>}
      <p>個別に必須と記録された項目：{group.individual_required_count ?? group.members.filter(member => member.individually_required).length}件</p>
    </section>
    <p className="notice mt-2">同じ見出しの項目をまとめた候補です。対象項目と条件を元フォームで確認してください。記録しても送信可能にはなりません。</p>
    <p className="muted mt-2">各欄に保存できる選択値は1つです。同じ欄で複数の値を選ぶケースは未対応です。</p>
    {!group.review_supported && <p className="notice mt-2">項目名・選択肢・同意条件を安全に確定できないため、このグループは記録できません。</p>}
    {group.review_supported && <>
      {group.rule && <p className="muted mt-2">前回の条件：{group.rule === 'EXACTLY_ONE' ? '1項目だけ選択' : '最低1項目を選択'}</p>}
      {Object.entries(group.saved_selections || {}).map(([id, value]) => <p className="muted mt-2" key={id}>前回の選択：{group.members.find(member => member.field_id === id)?.options.find(option => option.value === value)?.label || value}</p>)}
      {readOnly ? <p className="muted mt-2">条件の記録は所有者または編集者が行います。</p> : <>
        <label className="mt-3">確認した必須条件<select aria-label="確認した必須条件" value={rule} disabled={saving} onChange={event => { setRule(event.target.value); setConfirmed(false) }}>
          <option value="">元フォームで確認して選択</option><option value="AT_LEAST_ONE">最低1項目を選択</option><option value="EXACTLY_ONE">1項目だけ選択</option>
        </select></label>
        {group.members.map(member => <label className="mt-3 block break-all" key={member.field_id}>{member.options.slice(0, 2).map(option => option.label || option.value).join(' / ')}{member.options.length > 2 ? ` ほか${member.options.length - 2}件` : ''}：{member.options.length}選択肢{member.individually_required ? '（個別必須）' : '（グループ条件を確認）'}<select aria-label={`${member.name}のグループ選択`} disabled={saving} value={choices[member.field_id] || ''} onChange={event => { setChoices({ ...choices, [member.field_id]: event.target.value }); setConfirmed(false) }}>
          <option value="">選択しない</option>{member.options.map(option => <option key={option.value} value={option.value}>{option.label || option.value}</option>)}
        </select></label>)}
        <label className="mt-3 flex items-start gap-2"><input type="checkbox" checked={confirmed} disabled={saving} onChange={event => setConfirmed(event.target.checked)} />対象項目・必須条件・選択値を元フォームで確認しました</label>
        <button className="secondary mt-3" disabled={saving || !confirmed || !rule || selected.length === 0 || (rule === 'EXACTLY_ONE' && selected.length !== 1)} onClick={() => onSave(rule, selected)}>グループの確認を記録</button>
      </>}
    </>}
  </article>
}

export function CompanyFormChoiceGroups({ profileId, readOnly, onSaved }: { profileId: string; readOnly: boolean; onSaved: () => Promise<void> }) {
  const [groups, setGroups] = useState<Group[] | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const path = `/form-profiles/${profileId}/choice-groups`
  useEffect(() => {
    let active = true
    api<Group[]>(`/form-profiles/${profileId}/choice-groups`).then(result => { if (active) setGroups(result) }).catch(err => { if (active) setError(err instanceof Error ? err.message : '確認情報を取得できません。') })
    return () => { active = false }
  }, [profileId])
  async function refresh() {
    setBusy(true); setError('')
    try { setGroups(await api<Group[]>(path)) } catch (err) { setError(err instanceof Error ? err.message : '取得できません。') } finally { setBusy(false) }
  }
  async function save(group: Group, rule: string, selections: { field_id: string; value: string }[]) {
    setBusy(true); setError('')
    try {
      setGroups(await api<Group[]>(`${path}/${group.group_id}/review`, 'POST', { expected_source_hash: group.source_hash, rule, selections, membership_and_rule_confirmed: true }))
      await onSaved()
    } catch (err) { setError(err instanceof Error ? err.message : '記録できませんでした。') } finally { setBusy(false) }
  }
  return <section className="mt-4" aria-label="必須グループ確認">
    <h3>複数項目の必須条件</h3>
    <p className="muted mt-2">記録は24時間有効です。項目や選択値が変わった場合は再確認が必要です。送信承認とは別の記録です。</p>
    <button className="secondary mt-3" disabled={busy} onClick={refresh}>グループを読み直す</button>
    {error && <p className="error mt-3" role="alert">{error}</p>}
    {groups === null && !error && <p className="muted mt-3">読み込み中…</p>}
    {groups?.length === 0 && <p className="muted mt-3">保存済みの必須グループはありません。</p>}
    {groups?.map(group => <GroupEditor key={`${group.group_id}:${group.source_hash}:${group.review_status}`} group={group} readOnly={readOnly} saving={busy} onSave={(rule, selections) => void save(group, rule, selections)} />)}
  </section>
}
