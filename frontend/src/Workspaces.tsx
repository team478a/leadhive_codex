import { useEffect, useState } from 'react'
import { allPages, errorMessage } from './api'
import { CompanyCollectionFeedback } from './CompanyCollectionFeedback'
import { SalesPreparationPanel } from './SalesPreparationPanel'
import type { Company, Profile, Project, ProjectMember } from './types'

type Roles = Record<string, ProjectMember['role']>
export function CollectionTargets({ projects, profiles, roles, initialProjectId, onCreate, onAssist, onCollect, onEdit, onProjectSelected }: {
  projects: Project[]; profiles: Profile[]; roles: Roles; initialProjectId: string; onProjectSelected: (id: string) => void
  onCreate: () => void; onAssist: () => void; onCollect: (id: string) => void; onEdit: (project: Project) => void
}) {
  const [selected, setSelected] = useState(initialProjectId || projects[0]?.id || '')
  const project = projects.find(p => p.id === selected) || projects[0]
  const profile = profiles.find(p => p.id === project?.target_profile_id)
  return <section aria-label="収集ターゲット設定">
    <div className="panel mb-5"><h2>誰を集めるかを決めましょう</h2><p className="mt-2">業種・キーワード・地域を設定したら、件数を指定して収集を開始します。</p>
      <div className="actions"><button onClick={onCreate}>新しい収集ターゲットを設定</button><button className="secondary" onClick={onAssist}>サービスURLからターゲットを提案</button></div>
    </div>
    {project ? <section className="panel"><h2>保存したターゲットで収集する</h2>
      <label className="field mt-4">収集ターゲット<select value={project.id} onChange={e => { setSelected(e.target.value); onProjectSelected(e.target.value) }}>{projects.map(p => <option key={p.id} value={p.id}>{p.project_name}</option>)}</select></label>
      <dl className="grid gap-3 mt-4"><div><dt>対象</dt><dd>{profile?.profile_name || '設定未確認'}</dd></div><div><dt>地域</dt><dd>{project.region}</dd></div><div><dt>検索キーワード</dt><dd className="break-words">{profile?.search_keywords.join(' / ') || '収集画面で入力してください'}</dd></div></dl>
      <div className="actions"><button disabled={roles[project.id] === 'viewer' || !roles[project.id]} onClick={() => onCollect(project.id)}>このターゲットで収集へ</button>{roles[project.id] === 'owner' && <button className="secondary" onClick={() => onEdit(project)}>ターゲット設定を編集</button>}</div>
      {roles[project.id] === 'viewer' && <p className="muted">閲覧のみです。収集は所有者・編集者が開始できます。</p>}
    </section> : <p className="panel">保存したターゲットはありません。「新しい収集ターゲットを設定」から始めてください。</p>}
  </section>
}

function publicLink(value: string | null) {
  try { const u = new URL(value || ''); return /^https?:$/.test(u.protocol) && !u.username && !u.password ? u.href : undefined } catch { return undefined }
}

export function CollectionResults({ projects, roles, initialProjectId, onProjectSelected }: {
  projects: Project[]; roles: Roles; initialProjectId: string; onProjectSelected: (id: string) => void
}) {
  const project = projects.find(p => p.id === initialProjectId) || projects[0]
  const [items, setItems] = useState<Company[]>([])
  const [selected, setSelected] = useState('')
  const [page, setPage] = useState(0)
  const [revision, setRevision] = useState(0)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const projectId = project?.id
  useEffect(() => {
    let active = true
    setBusy(true); setError(''); setItems([])
    if (!projectId) { setBusy(false); return }
    allPages<Company>(`/projects/${projectId}/companies`).then(rows => { if (active) setItems(rows) })
      .catch(e => { if (active) setError(errorMessage(e)) }).finally(() => { if (active) setBusy(false) })
    return () => { active = false }
  }, [projectId, revision])
  const company = items.find(c => c.id === selected)
  const readOnly = !projectId || !['owner', 'editor'].includes(roles[projectId])
  return <section aria-label="収集リストの確認">
    <div className="panel mb-5"><h2>集まった候補を確認する</h2><p>対象企業のOK・NG、問い合わせ候補の確認・URL修正を記録できます。DM準備は「営業作業」から進めます。</p>
      {project ? <label className="field mt-3">確認する収集リスト<select value={project.id} onChange={e => onProjectSelected(e.target.value)}>{projects.map(p => <option value={p.id} key={p.id}>{p.project_name}</option>)}</select></label> : <p>まだ収集リストがありません。</p>}
      <p className="mt-3">保存済み候補 {items.length}件</p>
    </div>
    {busy && <p role="status">リストを読み込み中…</p>}
    {error && <p className="error" role="alert">{error}<button className="secondary" onClick={() => setRevision(v => v + 1)}>再読み込み</button></p>}
    {!busy && !error && project && items.length === 0 && <p className="panel">候補はまだありません。収集開始画面から収集してください。</p>}
    {items.slice(page * 20, (page + 1) * 20).map(c => <article className="panel mb-3" key={c.id}><h3>{c.company_name}</h3><p className="muted break-words">{c.address || '住所未取得'}</p>
      <p className="mt-2">{publicLink(c.website_url) ? <a href={publicLink(c.website_url)} target="_blank" rel="noreferrer">企業サイトを開く ↗</a> : '企業サイト未取得'} / {c.contact_url ? '問い合わせ候補あり（未確認を含む）' : '問い合わせ候補未検出'}</p>
      {(c.do_not_contact || c.status === 'excluded') && <p className="mt-2">{c.do_not_contact ? '連絡禁止' : '対象外'}</p>}
      <button className="secondary mt-3" onClick={() => setSelected(v => v === c.id ? '' : c.id)}>{selected === c.id ? '確認を閉じる' : '取得結果を確認する'}</button>
      {company?.id === c.id && <CompanyCollectionFeedback company={company} initialSubject="company" readOnly={readOnly} onSaved={() => setRevision(v => v + 1)} />}
    </article>)}
    {items.length > 20 && <div className="actions"><button className="secondary" disabled={page === 0} onClick={() => { setPage(v => v - 1); setSelected('') }}>前の20件</button><span>{page + 1} / {Math.ceil(items.length / 20)}</span><button className="secondary" disabled={(page + 1) * 20 >= items.length} onClick={() => { setPage(v => v + 1); setSelected('') }}>次の20件</button></div>}
  </section>
}

export function SalesWorkspace({ projects, roles, initialProjectId, onNavigate, onProjectSelected }: {
  projects: Project[]; roles: Roles; initialProjectId: string; onProjectSelected: (id: string) => void
  onNavigate: (destination: 'companies' | 'approvals' | 'deliveries', id: string) => void
}) {
  const [selected, setSelected] = useState(initialProjectId || projects[0]?.id || '')
  const project = projects.find(p => p.id === selected) || projects[0]
  return <section aria-label="営業作業">
    <div className="panel mb-5"><h2>集めたリストを使って営業する</h2><p className="mt-2">問い合わせ先の確認 → DM準備 → 人の承認 → 送信結果の確認を行います。</p>
      {project ? <><label className="field mt-4">営業するプロジェクト<select value={project.id} onChange={e => { setSelected(e.target.value); onProjectSelected(e.target.value) }}>{projects.map(p => <option value={p.id} key={p.id}>{p.project_name}</option>)}</select></label>
        <div className="actions"><button onClick={() => onNavigate('companies', project.id)}>企業一覧・DM準備へ</button><button className="secondary" onClick={() => onNavigate('approvals', project.id)}>承認キューへ</button><button className="secondary" onClick={() => onNavigate('deliveries', project.id)}>配信結果を見る</button></div>
      </> : <p className="mt-3">収集ターゲットを設定し、リストを収集してから営業作業を始めてください。</p>}
    </div>
    {project && roles[project.id] !== 'viewer' && roles[project.id] && <SalesPreparationPanel key={project.id} projectId={project.id} />}
    {project && roles[project.id] === 'viewer' && <p className="panel">閲覧のみです。営業準備の実行は所有者・編集者へ依頼してください。</p>}
  </section>
}
