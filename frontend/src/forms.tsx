import { cloneElement, useId, useState, type FormEvent, type ReactElement } from 'react'
import { api, errorMessage } from './api'
import { RegionSelector } from './RegionSelector'
import type { Profile, ProfileInput, Project, ProjectInput } from './types'

export function Field({ label, children }: { label: string; children: ReactElement<{ id?: string }> }) {
  const id = useId()
  return <div className="field"><label htmlFor={id}>{label}</label>{cloneElement(children, { id })}</div>
}

export function ProjectForm({ profiles, initial, onSaved, onCancel }: {
  profiles: Profile[]; initial?: Project; onSaved: () => Promise<void>; onCancel: () => void
}) {
  const [value, setValue] = useState<ProjectInput>(initial ? {
    project_name: initial.project_name, target_profile_id: initial.target_profile_id,
    sales_objective: initial.sales_objective, region: initial.region, status: initial.status,
  } : { project_name: '', target_profile_id: '', sales_objective: '', region: '全国', status: 'draft' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      await api(initial ? `/projects/${initial.id}` : '/projects', initial ? 'PUT' : 'POST', value)
      await onSaved()
    } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false) }
  }
  return <form onSubmit={submit} className="panel form-panel">
    <h2>{initial ? 'プロジェクトを編集' : 'プロジェクトを作成'}</h2>
    <p className="muted">ターゲットと営業目的を設定して、案件を整理しましょう。</p>
    {error && <p role="alert" className="error">{error}</p>}
    <fieldset disabled={busy}>
      <Field label="プロジェクト名"><input required maxLength={200} value={value.project_name}
        onChange={e => setValue({ ...value, project_name: e.target.value })} /></Field>
      <Field label="ターゲットプロファイル"><select required value={value.target_profile_id}
        onChange={e => { const profile = profiles.find(p => p.id === e.target.value)
          setValue({ ...value, target_profile_id: e.target.value,
            region: profile?.default_regions.join(' / ') || value.region }) }}>
        <option value="">選択してください</option>
        {profiles.filter(p => p.active || p.id === initial?.target_profile_id).map(p =>
          <option key={p.id} value={p.id}>{p.profile_name}{!p.active && '（無効）'}</option>)}
      </select></Field>
      <Field label="営業目的"><textarea required maxLength={10000} rows={3} value={value.sales_objective}
        onChange={e => setValue({ ...value, sales_objective: e.target.value })} /></Field>
      <RegionSelector value={value.region} onChange={region => setValue({ ...value, region })} />
      <div className="grid gap-5 sm:grid-cols-2">
        <Field label="ステータス"><select value={value.status}
          onChange={e => setValue({ ...value, status: e.target.value as ProjectInput['status'] })}>
          <option value="draft">下書き</option><option value="active">進行中</option>
          <option value="archived">アーカイブ</option>
        </select></Field>
      </div>
      <div className="actions"><button type="button" className="secondary" onClick={onCancel}>キャンセル</button>
        <button type="submit">{busy ? '保存中…' : '保存する'}</button></div>
    </fieldset>
  </form>
}

const blankProfile: ProfileInput = {
  profile_name: '', description: '', search_keywords: [], positive_keywords: [], negative_keywords: [],
  exclusion_keywords: [], scoring_rules: {}, ai_instruction: '', default_regions: ['全国'], active: true,
}
const keywordFields = [
  ['search_keywords', '検索キーワード'], ['positive_keywords', '加点キーワード'],
  ['negative_keywords', '減点キーワード'], ['exclusion_keywords', '除外キーワード'],
  ['default_regions', '標準地域'],
] as const

export function ProfileForm({ initial, onSaved, onCancel }: {
  initial?: Profile; onSaved: () => Promise<void>; onCancel: () => void
}) {
  const [value, setValue] = useState<ProfileInput>(initial ?? blankProfile)
  const [keywords, setKeywords] = useState(() => Object.fromEntries(
    keywordFields.map(([key]) => [key, (initial ?? blankProfile)[key].join('\n')]),
  ))
  const [rules, setRules] = useState(JSON.stringify(initial?.scoring_rules ?? {}, null, 2))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault(); setError('')
    let scoring_rules: Record<string, unknown>
    try {
      scoring_rules = JSON.parse(rules)
      if (!scoring_rules || Array.isArray(scoring_rules) || typeof scoring_rules !== 'object') throw Error()
    } catch { setError('スコアルールには有効なJSONオブジェクトを入力してください。'); return }
    const body: ProfileInput = { ...blankProfile }
    for (const key of Object.keys(blankProfile) as (keyof ProfileInput)[]) {
      Object.assign(body, { [key]: value[key] })
    }
    for (const [key] of keywordFields) body[key] = keywords[key].split('\n').map(s => s.trim()).filter(Boolean)
    body.scoring_rules = scoring_rules
    setBusy(true)
    try {
      await api(initial ? `/target-profiles/${initial.id}` : '/target-profiles', initial ? 'PUT' : 'POST', body)
      await onSaved()
    } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false) }
  }
  return <form className="panel form-panel" onSubmit={submit}>
    <h2>{initial ? 'プロファイルを編集' : 'プロファイルを作成'}</h2>
    <p className="muted">業種ごとの検索条件と評価基準を設定します。キーワードは1行に1件入力してください。</p>
    {error && <p role="alert" className="error">{error}</p>}
    <fieldset disabled={busy}>
      <Field label="プロファイル名"><input required maxLength={200} value={value.profile_name}
        onChange={e => setValue({ ...value, profile_name: e.target.value })} /></Field>
      <Field label="説明"><textarea maxLength={10000} value={value.description}
        onChange={e => setValue({ ...value, description: e.target.value })} /></Field>
      <div className="grid gap-x-6 sm:grid-cols-2">{keywordFields.map(([key, label]) =>
        <Field key={key} label={label}><textarea rows={4} value={keywords[key]}
          onChange={e => setKeywords({ ...keywords, [key]: e.target.value })} /></Field>)}</div>
      <Field label="スコアルール（JSON）"><textarea className="font-mono" rows={8} value={rules}
        onChange={e => setRules(e.target.value)} spellCheck={false} /></Field>
      <Field label="AIへの指示"><textarea rows={4} maxLength={20000} value={value.ai_instruction}
        onChange={e => setValue({ ...value, ai_instruction: e.target.value })} /></Field>
      <label className="flex items-center gap-3"><input type="checkbox" checked={value.active}
        onChange={e => setValue({ ...value, active: e.target.checked })} />有効にする</label>
      <div className="actions"><button type="button" className="secondary" onClick={onCancel}>キャンセル</button>
        <button type="submit">{busy ? '保存中…' : '保存する'}</button></div>
    </fieldset>
  </form>
}
