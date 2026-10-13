import { cloneElement, useEffect, useId, useRef, useState, type FormEvent, type ReactElement } from 'react'
import { api, errorMessage } from './api'
import { RegionSelector } from './RegionSelector'
import type { Profile, ProfileInput, Project, ProjectInput } from './types'
import { aliasText, industryAliasKey, parseAliases } from './industryAliases'
import { TargetProfileAssistant } from './TargetProfileAssistant'

export function Field({ label, children, required }: { label: string; children: ReactElement<{ id?: string; required?: boolean }>; required?: boolean }) {
  const id = useId()
  const isRequired = required ?? Boolean(children.props.required)
  return <div className="field"><label className={isRequired ? 'required-label' : undefined} htmlFor={id}>{label}</label>{cloneElement(children, { id })}</div>
}

export function ProjectForm({ profiles, initial, profileId, onSaved, onCancel, collectionSetup = false }: {
  profiles: Profile[]; initial?: Project; profileId?: string; onSaved: (project: Project) => Promise<void>; onCancel: () => void; collectionSetup?: boolean
}) {
  const [value, setValue] = useState<ProjectInput>(initial ? {
    project_name: initial.project_name, target_profile_id: initial.target_profile_id,
    sales_objective: initial.sales_objective, region: initial.region, status: initial.status,
  } : { project_name: '', target_profile_id: profileId ?? '', sales_objective: profiles.find(p => p.id === profileId)?.description ?? '', region: profiles.find(p => p.id === profileId)?.default_regions.join(' / ') || '全国', status: 'draft' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const project = await api<Project>(initial ? `/projects/${initial.id}` : '/projects', initial ? 'PUT' : 'POST', value)
      await onSaved(project)
    } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false) }
  }
  return <form onSubmit={submit} className="panel form-panel">
    <h2>{collectionSetup ? '収集ターゲットを設定' : initial ? 'プロジェクトを編集' : 'プロジェクトを作成'}</h2>
    <p className="muted">{collectionSetup ? '対象と地域を保存したら、収集開始画面へ進みます。' : 'ターゲットと営業目的を設定して、案件を整理しましょう。'}</p>
    {error && <p role="alert" className="error">{error}</p>}
    <fieldset disabled={busy}>
      <Field required label={collectionSetup ? '収集リスト名' : 'プロジェクト名'}><input required maxLength={200} value={value.project_name}
        onChange={e => setValue({ ...value, project_name: e.target.value })} /></Field>
      <Field required label={collectionSetup ? '収集する対象' : 'ターゲットプロファイル'}><select required value={value.target_profile_id}
        onChange={e => { const profile = profiles.find(p => p.id === e.target.value)
          setValue({ ...value, target_profile_id: e.target.value,
            ...(collectionSetup && !value.sales_objective ? { sales_objective: profile?.description || profile?.profile_name || '' } : {}),
            region: profile?.default_regions.join(' / ') || value.region }) }}>
        <option value="">選択してください</option>
        {profiles.filter(p => p.active || p.id === initial?.target_profile_id).map(p =>
          <option key={p.id} value={p.id}>{p.profile_name}{!p.active && '（無効）'}</option>)}
      </select></Field>
      <Field required label={collectionSetup ? '収集の目的' : '営業目的'}><textarea required maxLength={10000} rows={3} value={value.sales_objective}
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
        <button type="submit">{busy ? '保存中…' : collectionSetup ? '保存して収集へ' : '保存する'}</button></div>
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

export function ProfileForm({ initial, onSaved, onCancel, onCreateProject }: {
  initial?: Profile; onSaved: () => Promise<void>; onCancel: () => void; onCreateProject?: (profileId: string) => void
}) {
  const [value, setValue] = useState<ProfileInput>(initial ?? blankProfile)
  const [keywords, setKeywords] = useState(() => Object.fromEntries(
    keywordFields.map(([key]) => [key, (initial ?? blankProfile)[key].join('\n')]),
  ))
  const [aliases, setAliases] = useState(aliasText(initial?.scoring_rules[industryAliasKey]))
  const [rules, setRules] = useState(JSON.stringify(Object.fromEntries(Object.entries(initial?.scoring_rules ?? {}).filter(([key]) => key !== industryAliasKey)), null, 2))
  const [busy, setBusy] = useState(false)
  const [startProject, setStartProject] = useState(false)
  const [error, setError] = useState('')
  const errorRef = useRef<HTMLParagraphElement>(null)
  useEffect(() => {
    if (!error) return
    errorRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    errorRef.current?.focus({ preventScroll: true })
  }, [error])
  async function submit(event: FormEvent) {
    event.preventDefault(); setError('')
    let scoring_rules: Record<string, unknown>
    try {
      scoring_rules = JSON.parse(rules)
      if (!scoring_rules || Array.isArray(scoring_rules) || typeof scoring_rules !== 'object') throw Error()
    } catch { setError('スコアルールには有効なJSONオブジェクトを入力してください。'); return }
    try {
      if (industryAliasKey in scoring_rules) throw Error('業種の別名は専用の入力欄で設定してください。')
      const mapping = parseAliases(aliases)
      if (Object.keys(mapping).length) scoring_rules[industryAliasKey] = mapping
    } catch (e) { setError(e instanceof Error ? e.message : '業種の別名を確認してください。'); return }
    const body: ProfileInput = { ...blankProfile }
    for (const key of Object.keys(blankProfile) as (keyof ProfileInput)[]) {
      Object.assign(body, { [key]: value[key] })
    }
    for (const [key] of keywordFields) body[key] = keywords[key].split('\n').map(s => s.trim()).filter(Boolean)
    body.scoring_rules = scoring_rules
    setBusy(true)
    try {
      const result = await api<Profile>(initial ? `/target-profiles/${initial.id}` : '/target-profiles', initial ? 'PUT' : 'POST', body)
      await onSaved()
      if (startProject) onCreateProject?.(result.id)
    } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false) }
  }
  return <form className="panel form-panel" onSubmit={submit}>
    <h2>{initial ? 'プロファイルを編集' : 'プロファイルを作成'}</h2>
    <p className="muted">＊は必須項目です。キーワードは1行に1件、最大100件・1件300文字以内です。</p>
    {error && <p ref={errorRef} tabIndex={-1} role="alert" className="error">{error}</p>}
    <fieldset disabled={busy}>
      <TargetProfileAssistant onApply={(target, summary, source) => {
        setValue({ ...value, profile_name: target.name, description: `${summary}\n確認元: ${source}\n提案理由: ${target.reason}` })
        setKeywords({ ...keywords, search_keywords: target.search_keywords.join('\n'), positive_keywords: target.positive_keywords.join('\n'), negative_keywords: target.negative_keywords.join('\n'), exclusion_keywords: target.exclusion_keywords.join('\n') })
      }} />
      <Field required label="プロファイル名"><input required maxLength={200} value={value.profile_name}
        onChange={e => setValue({ ...value, profile_name: e.target.value })} /></Field>
      <Field label="説明"><textarea maxLength={10000} value={value.description}
        onChange={e => setValue({ ...value, description: e.target.value })} /></Field>
      <div className="grid gap-x-6 sm:grid-cols-2">{keywordFields.filter(([key]) => key === 'search_keywords' || key === 'default_regions').map(([key, label]) =>
        <div key={key}><Field label={label}><textarea rows={4} value={keywords[key]}
          onChange={e => setKeywords({ ...keywords, [key]: e.target.value })} /></Field>
          <p className="muted mt-1 text-sm">{key === 'default_regions' ? '1行に1地域、最大100件。' : '1行に1件、最大100件・1件300文字以内。'} 現在{keywords[key].split('\n').filter(line => line.trim()).length}件</p></div>)}</div>
      <details><summary>詳細設定（加点・減点・除外・AI指示）</summary>
      <div className="grid gap-x-6 sm:grid-cols-2">{keywordFields.filter(([key]) => key !== 'search_keywords' && key !== 'default_regions').map(([key, label]) =>
        <div key={key}><Field label={label}><textarea rows={4} value={keywords[key]} onChange={e => setKeywords({ ...keywords, [key]: e.target.value })} /></Field>
          <p className="muted mt-1 text-sm">1行に1件、最大100件・1件300文字以内。現在{keywords[key].split('\n').filter(line => line.trim()).length}件</p></div>)}</div>
      <Field label="業種確認に使う別名（1行に1業種）"><textarea rows={3} maxLength={24000} placeholder="美容院: 美容室, ヘアサロン" value={aliases} onChange={e => setAliases(e.target.value)} /></Field>
      <p className="muted">例：美容院: 美容室, ヘアサロン。最大20業種、各10別名。保存済み公式サイトの確認候補にだけ使います。検索語の追加・AIスコア変更・自動一致判定は行いません。</p>
      <Field label="スコアルール（JSON）"><textarea className="font-mono" rows={8} value={rules}
        onChange={e => setRules(e.target.value)} spellCheck={false} /></Field>
      <Field label="AIへの指示"><textarea rows={4} maxLength={20000} value={value.ai_instruction}
        onChange={e => setValue({ ...value, ai_instruction: e.target.value })} /></Field>
      <label className="flex items-center gap-3"><input type="checkbox" checked={value.active}
        onChange={e => setValue({ ...value, active: e.target.checked })} />有効にする</label>
      </details>
      <div className="actions"><button type="button" className="secondary" onClick={onCancel}>キャンセル</button>
        <button type="submit" onClick={() => setStartProject(false)}>{busy ? '保存中…' : '保存する'}</button>
        {onCreateProject && <button type="submit" onClick={() => setStartProject(true)}>保存してプロジェクト作成へ</button>}</div>
    </fieldset>
  </form>
}
