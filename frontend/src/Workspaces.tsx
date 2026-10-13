import { useEffect, useState } from 'react'
import { allPages, api, errorMessage } from './api'
import { CompanyCollectionFeedback } from './CompanyCollectionFeedback'
import { SalesPreparationPanel } from './SalesPreparationPanel'
import { CleanListSendPanel } from './CleanListSendPanel'
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
  const [showExcluded, setShowExcluded] = useState(false)
  const [organizing, setOrganizing] = useState(false)
  const [notice, setNotice] = useState('')
  const [actionError, setActionError] = useState('')
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
  const visible = items.filter(c => showExcluded ? c.status === 'excluded' : c.status !== 'excluded')
  async function organize() {
    if (readOnly || busy || organizing) return
    setOrganizing(true); setActionError(''); setNotice(''); setSelected(''); setPage(0)
    let moved = 0; let protectedCount = 0
    try {
      for (let i = 0; i < items.length; i += 100) {
        const result = await api<{ excluded_ids: string[]; protected_ids: string[] }>(`/projects/${projectId}/source-exclusions/cleanup`, 'POST', { company_ids: items.slice(i, i + 100).map(c => c.id) })
        moved += result.excluded_ids.length; protectedCount += result.protected_ids.length
        setNotice(`まとめサイトを整理中：${Math.min(i + 100, items.length)} / ${items.length}件`)
      }
      setNotice(`${moved}件を収集対象外へ移しました。人の確認・営業状況などにより${protectedCount}件を保護しました。`)
    } catch (e) { setActionError(errorMessage(e)); setNotice(`整理済み${moved}件。途中までの結果を保存しています。`) }
    finally { setOrganizing(false); setRevision(v => v + 1) }
  }
  return <section aria-label="収集リストの確認">
    <div className="panel mb-5"><h2>集まった候補を確認する</h2><p>対象企業のOK・NG、問い合わせ候補の確認・URL修正を記録できます。文面準備から送信までは「送信の準備・実行」にまとまっています。</p>
      {project ? <label className="field mt-3">確認する収集リスト<select disabled={organizing} value={project.id} onChange={e => { setPage(0); setSelected(''); setNotice(''); setActionError(''); onProjectSelected(e.target.value) }}>{projects.map(p => <option value={p.id} key={p.id}>{p.project_name}</option>)}</select></label> : <p>まだ収集リストがありません。</p>}
      <p className="mt-3">候補 {items.filter(c => c.status !== 'excluded').length}件 / 収集対象外 {items.filter(c => c.status === 'excluded').length}件</p>
      <div className="actions flex-wrap"><button className="secondary" disabled={readOnly || busy || organizing || !items.length} onClick={() => void organize()}>{organizing ? '整理中…' : '既知のまとめサイトを整理'}</button><button className="secondary" disabled={organizing} onClick={() => { setShowExcluded(v => !v); setPage(0); setSelected('') }}>{showExcluded ? '候補に戻る' : '収集対象外を見る'}</button></div>
      <p className="muted text-sm">確認済みの掲載媒体だけを自動整理します。データや人の判定は削除しません。</p>
    </div>
    {notice && <p role="status" className="panel">{notice}</p>}
    {actionError && <p role="alert" className="error">{actionError}</p>}
    {busy && !notice && <p role="status">リストを読み込み中…</p>}
    {error && <p className="error" role="alert">{error}<button className="secondary" onClick={() => setRevision(v => v + 1)}>再読み込み</button></p>}
    {!busy && !error && project && items.length === 0 && <p className="panel">候補はまだありません。収集開始画面から収集してください。</p>}
    {!busy && !error && items.length > 0 && visible.length === 0 && <p className="panel">{showExcluded ? '収集対象外の候補はありません。' : '通常の候補はありません。「収集対象外を見る」で移動した候補を確認できます。'}</p>}
    {visible.slice(page * 20, (page + 1) * 20).map(c => <article className="panel mb-3" key={c.id}><h3>{c.company_name}</h3><p className="muted break-words">{c.address || '住所未取得'}</p>
      <p className="mt-2">{publicLink(c.website_url) ? <a href={publicLink(c.website_url)} target="_blank" rel="noreferrer">企業サイトを開く ↗</a> : '企業サイト未取得'} / {c.contact_url ? '問い合わせ候補あり（未確認を含む）' : '問い合わせ候補未検出'}</p>
      {(c.do_not_contact || c.status === 'excluded') && <p className="mt-2">{c.do_not_contact ? '連絡禁止' : '対象外'}</p>}
      <button className="secondary mt-3" onClick={() => setSelected(v => v === c.id ? '' : c.id)}>{selected === c.id ? '確認を閉じる' : '取得結果を確認する'}</button>
      {selected === c.id && c.status === 'excluded' && <SourceCleanupRestore company={c} readOnly={readOnly} onSaved={() => { setSelected(''); setPage(0); setRevision(v => v + 1) }} />}
      {company?.id === c.id && <CompanyCollectionFeedback company={company} initialSubject="company" readOnly={readOnly} onSaved={() => setRevision(v => v + 1)} />}
    </article>)}
    {visible.length > 20 && <div className="actions"><button className="secondary" disabled={page === 0} onClick={() => { setPage(v => v - 1); setSelected('') }}>前の20件</button><span>{page + 1} / {Math.ceil(visible.length / 20)}</span><button className="secondary" disabled={(page + 1) * 20 >= visible.length} onClick={() => { setPage(v => v + 1); setSelected('') }}>次の20件</button></div>}
  </section>
}

export function SalesWorkspace({ projects, roles, initialProjectId, onNavigate, onProjectSelected }: {
  projects: Project[]; roles: Roles; initialProjectId: string; onProjectSelected: (id: string) => void
  onNavigate: (destination: 'companies' | 'approvals' | 'deliveries', id: string) => void
}) {
  const [selected, setSelected] = useState(initialProjectId || projects[0]?.id || '')
  const [sending, setSending] = useState(false)
  const project = projects.find(p => p.id === selected) || projects[0]
  return <section aria-label="営業作業">
    <div className="panel mb-5"><h2>送信までの流れ</h2><p className="mt-2">この画面で準備と送信を進めます。宛先・文面の確認と承認は人が行います。</p>
      {project ? <><label className="field mt-4">対象プロジェクト<select disabled={sending} value={project.id} onChange={e => { setSelected(e.target.value); onProjectSelected(e.target.value) }}>{projects.map(p => <option value={p.id} key={p.id}>{p.project_name}</option>)}</select></label>
        <ol className="flow-steps mt-4">
          <li><strong>1. 文面を準備</strong><span>企業一覧から対象企業を選び、DMを作成します。</span><button className="secondary" disabled={sending} onClick={() => onNavigate('companies', project.id)}>企業一覧・DM準備へ</button></li>
          <li><strong>2. 内容を確認・承認</strong><span>宛先と文面を確認し、承認キューで承認します。</span><button className="secondary" disabled={sending} onClick={() => onNavigate('approvals', project.id)}>承認キューを開く</button></li>
          <li><strong>3. 送信を開始</strong><span>承認済みの内容だけを一括送信します。</span><button className="secondary" disabled={sending} onClick={() => document.getElementById('clean-list-send-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}>一括送信へ</button></li>
          <li><strong>4. 結果を確認</strong><span>予約状況・送信結果を確認します。</span><button className="secondary" disabled={sending} onClick={() => onNavigate('deliveries', project.id)}>配信結果を見る</button></li>
        </ol>
      </> : <p className="mt-3">収集ターゲットを設定し、リストを収集してから営業作業を始めてください。</p>}
    </div>
    {project && roles[project.id] !== 'viewer' && roles[project.id] && <><SalesPreparationPanel key={project.id} projectId={project.id} /><CleanListSendPanel key={`send-${project.id}`} projectId={project.id} canWrite onBusyChange={setSending} onNavigate={destination => onNavigate(destination, project.id)} /></>}
    {project && roles[project.id] === 'viewer' && <p className="panel">閲覧のみです。営業準備の実行は所有者・編集者へ依頼してください。</p>}
  </section>
}

function SourceCleanupRestore({ company, readOnly, onSaved }: { company: Company; readOnly: boolean; onSaved: () => void }) {
  const [restorable, setRestorable] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const path = `/projects/${company.project_id}/source-exclusions/cleanup/${company.id}`
  useEffect(() => {
    let active = true
    api<{ restorable: boolean }>(path).then(r => { if (active) setRestorable(r.restorable) }).catch(e => { if (active) setError(errorMessage(e)) })
    return () => { active = false }
  }, [path])
  async function restore() {
    setBusy(true); setError('')
    try { await api(`${path}/restore`, 'POST', { expected_updated_at: company.updated_at }); onSaved() }
    catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  return <div className="mt-3">{error && <p role="alert">{error}</p>}{restorable && <><p>掲載媒体のシステム判定で対象外へ移しました。戻したURLは次の自動整理でも保護します。</p><button className="secondary" disabled={busy || readOnly} onClick={() => void restore()}>自動除外を取り消して候補に戻す</button></>}</div>
}
