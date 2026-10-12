import type { CompletionReturnContext } from './completionWorkQueueTypes'
import { useCallback, useEffect, useState, useRef, type FormEvent } from 'react'
import { allPages, api, ApiError, errorMessage } from './api'
import { Field, ProfileForm, ProjectForm } from './forms'
import { OutboundStatus } from './OutboundStatus'
import { CollectionPage } from './CollectionPage'
import { ApprovalQueuePage } from './ApprovalQueuePage'
import { CompaniesPage } from './CompaniesPage'
import { DashboardPage } from './DashboardPage'
import { RawCollectionBenchmarkPage } from './RawCollectionBenchmarkPage'
import { EmailDeliveriesPage } from './EmailDeliveriesPage'
import { OnboardingGuide } from './OnboardingGuide'
import { OperatorGuide, type OperatorDestination } from './OperatorGuide'
import { InstallationGuide } from './InstallationGuide'
import { FeedbackProposalsPage } from './FeedbackProposalsPage'
import { CollectionResults, CollectionTargets, SalesWorkspace } from './Workspaces'
import { SmtpSettingsPage } from './SmtpSettingsPage'
import type { Dashboard, Notification, Profile, Project, ProjectMember, User } from './types'

function Login({ onLogin, notice }: { onLogin: (user: User) => void; notice: string }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try { onLogin(await api<User>('/auth/login', 'POST', { email, password })) }
    catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false) }
  }
  return <main className="login-layout">
    <section className="login-intro"><div className="brand">⬡ LeadHive</div>
      <div><p className="eyebrow">営業の準備を、ひとつの場所で。</p>
        <h1>次の出会いを、<br />明確なターゲットから。</h1>
        <p>業種と営業目的に合わせて、<br />プロジェクトの土台をつくりましょう。</p></div>
      <p className="text-sm opacity-60">LeadHive V2 · 営業プロジェクト管理</p></section>
    <section className="login-form"><form onSubmit={submit} className="w-full max-w-sm">
      <p className="eyebrow">WELCOME BACK</p><h2>ログイン</h2>
      <p className="muted mb-8">アカウント情報を入力してください。</p>
      {(error || notice) && <p className="error" role="alert">{error || notice}</p>}
      <fieldset disabled={busy}>
        <Field label="メールアドレス"><input type="email" autoComplete="username" required
          value={email} onChange={e => setEmail(e.target.value)} /></Field>
        <Field label="パスワード"><input type="password" autoComplete="current-password" required
          value={password} onChange={e => setPassword(e.target.value)} /></Field>
        <button className="w-full mt-3" type="submit">{busy ? 'ログイン中…' : 'ログインする'}</button>
      </fieldset>
      <p className="muted text-sm mt-6">アカウントの発行は管理担当者へご依頼ください。</p>
    </form></section>
  </main>
}

type Editor = { type: 'project'; value?: Project; profileId?: string } | { type: 'profile'; value?: Profile } | null
const statusNames = { draft: '下書き', active: '進行中', archived: 'アーカイブ' }

function Workspace({ user, onLogout }: { user: User; onLogout: () => void }) {
  const [tab, setTab] = useState<'dashboard' | 'projects' | 'collection' | 'companies' | 'profiles' | 'deliveries' | 'settings' | 'approvals' | 'raw' | 'operation' | 'installation' | 'improvements' | 'targets' | 'sales' | 'results' | 'analysis'>(window.location.hash === '#raw' ? 'raw' : 'targets')
  const [menuOpen, setMenuOpen] = useState(false)
  const menuButton = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!menuOpen) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setMenuOpen(false); menuButton.current?.focus() }
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [menuOpen])
  const [collectionProjectId, setCollectionProjectId] = useState('')
  const [replyInboundEmailId, setReplyInboundEmailId] = useState<string | null>(null)
  const [completionReturnContext, setCompletionReturnContext] = useState<CompletionReturnContext | null>(null)
  const [completionCompanyId, setCompletionCompanyId] = useState<string | null>(null)
  const [followupCompanyId, setFollowupCompanyId] = useState<string | null>(null)
  const [projects, setProjects] = useState<Project[]>([])
  const [showArchivedProjects, setShowArchivedProjects] = useState(false)
  const currentProjects = projects.filter(project => project.status !== 'archived')
  const archivedCount = projects.length - currentProjects.length
  const visibleProjects = showArchivedProjects ? projects : currentProjects
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [editor, setEditor] = useState<Editor>(null)
  const [collectionSetup, setCollectionSetup] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [unreadNotifications, setUnreadNotifications] = useState(0)
  const [totalCompanies, setTotalCompanies] = useState(0)
  const guideStorageKey = `leadhive:onboarding:${user.email}`
  const [guideOpen, setGuideOpen] = useState(() => localStorage.getItem(guideStorageKey) !== 'dismissed')
  const [projectRoles, setProjectRoles] = useState<Record<string, ProjectMember['role']>>({})
  const selectedCollectionProject = currentProjects.find(p => p.id === collectionProjectId) || currentProjects[0]
  const canCollect = !!selectedCollectionProject && ['owner', 'editor'].includes(projectRoles[selectedCollectionProject.id])
  const [memberProject, setMemberProject] = useState<Project | null>(null)
  const [members, setMembers] = useState<ProjectMember[]>([])
  const [memberEmail, setMemberEmail] = useState('')
  const [memberRole, setMemberRole] = useState<'editor' | 'viewer'>('editor')
  const reload = useCallback(async () => {
    const [nextProjects, nextProfiles, notifications, dashboard] = await Promise.all([
      allPages<Project>('/projects'), allPages<Profile>('/target-profiles'),
      api<Notification[]>('/notifications?unread_only=true&limit=100'),
      api<Dashboard>('/dashboard'),
    ])
    const memberLists = await Promise.all(nextProjects.map(project => api<ProjectMember[]>(`/projects/${project.id}/members`)))
    setProjects(nextProjects); setProfiles(nextProfiles)
    setProjectRoles(Object.fromEntries(nextProjects.map((project, index) => [project.id, memberLists[index].find(member => member.email === user.email)?.role ?? 'viewer'])))
    setUnreadNotifications(notifications.length); setTotalCompanies(dashboard.total_companies); setLoaded(true)
  }, [user.email])
  useEffect(() => {
    reload().catch(e => setError(errorMessage(e))).finally(() => setLoading(false))
  }, [reload])
  async function action(fn: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try { await fn() } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false) }
  }
  async function saved() {
    try {
      await reload()
      setEditor(null); setNotice('保存しました。')
    } catch (e) { setError(errorMessage(e)) }
  }
  async function savedTarget(project: Project) {
    await reload()
    setCollectionProjectId(project.id); setEditor(null); setCollectionSetup(false); setTab('collection')
    setNotice('ターゲットを保存しました。件数を確認して「収集を開始」を押してください。')
  }
  function configureTarget(value?: Project) {
    closeGuide(); setTab('targets'); setCollectionSetup(true); setEditor({ type: 'project', value }); setNotice('')
  }
  async function openMembers(project: Project) {
    setMemberProject(project); setMemberEmail(''); setMemberRole('editor')
    setMembers(await api<ProjectMember[]>(`/projects/${project.id}/members`))
  }
  async function saveMember() {
    if (!memberProject || !memberEmail.trim()) return
    await action(async () => {
      await api(`/projects/${memberProject.id}/members`, 'POST', { email: memberEmail, role: memberRole })
      setMembers(await api<ProjectMember[]>(`/projects/${memberProject.id}/members`)); setMemberEmail('')
      setNotice('プロジェクトメンバーを保存しました。')
    })
  }
  async function removeMember(member: ProjectMember) {
    if (!memberProject) return
    await action(async () => {
      await api(`/projects/${memberProject.id}/members/${member.id}`, 'DELETE')
      setMembers(await api<ProjectMember[]>(`/projects/${memberProject.id}/members`))
      setNotice('プロジェクトメンバーを削除しました。')
    })
  }
  function navigateForOperator(destination: OperatorDestination, projectId: string) {
    setCollectionProjectId(projectId); setCompletionCompanyId(null); setCompletionReturnContext(null)
    setReplyInboundEmailId(null); setFollowupCompanyId(null); setEditor(null); setNotice(''); setTab(destination)
  }
  function closeGuide() {
    localStorage.setItem(guideStorageKey, 'dismissed')
    setGuideOpen(false)
  }
  function openProjectCreator() {
    configureTarget()
  }
  function navigateFromGuide(destination: 'collection' | 'results' | 'settings') {
    closeGuide(); setEditor(null); setNotice(''); setTab(destination)
    if (currentProjects[0]) setCollectionProjectId(currentProjects[0].id)
  }
  return <div className="app-layout">
    <aside className="sidebar"><div className="sidebar-header"><div className="brand">⬡ LeadHive</div><button ref={menuButton} className="mobile-menu-toggle" aria-expanded={menuOpen} aria-controls="workspace-navigation-panel" onClick={() => setMenuOpen(v => !v)}>メニュー <span aria-hidden="true">{menuOpen ? '×' : '☰'}</span></button></div>
      <div id="workspace-navigation-panel" className={`sidebar-menu ${menuOpen ? 'flex' : 'hidden lg:flex'}`}>
      <nav id="workspace-navigation" aria-label="メインナビゲーション" onClick={() => { setMenuOpen(false); if (menuOpen) menuButton.current?.focus() }}>
        <p className="nav-label">リスト収集</p>
        <button className={tab === 'targets' ? 'nav-item selected' : 'nav-item'} onClick={() => { setTab('targets'); setEditor(null); setNotice('') }}>① 収集ターゲット設定</button>
        <button className={tab === 'collection' ? 'nav-item selected' : 'nav-item'} onClick={() => {
          setTab('collection'); setEditor(null); setNotice('')
        }}>⌕ 企業収集</button>
        <button className={tab === 'analysis' ? 'nav-item selected' : 'nav-item'} onClick={() => { setTab('analysis'); setEditor(null); setNotice('') }}>③ リスト解析</button>
        <button className={tab === 'results' ? 'nav-item selected' : 'nav-item'} onClick={() => { setTab('results'); setEditor(null); setNotice('') }}>④ 収集リストの確認</button>
        <p className="nav-label">営業作業</p>
        <button className={tab === 'sales' ? 'nav-item selected' : 'nav-item'} onClick={() => { setTab('sales'); setEditor(null); setNotice('') }}>▶ 営業準備</button>
        <button className={tab === 'companies' ? 'nav-item selected' : 'nav-item'} onClick={() => {
          setCompletionCompanyId(null); setTab('companies'); setEditor(null); setNotice('')
        }}>▤ 企業一覧</button>
        <button className={tab === 'deliveries' ? 'nav-item selected' : 'nav-item'} onClick={() => {
          setTab('deliveries'); setEditor(null); setNotice('')
        }}>✉ メール配信状況</button>
        <button className={tab === 'approvals' ? 'nav-item selected' : 'nav-item'} onClick={() => {
          setTab('approvals'); setEditor(null); setNotice('')
        }}>✓ 承認キュー</button>
        <p className="nav-label">管理・ガイド</p>
        <button className={tab === 'raw' ? 'nav-item selected' : 'nav-item'} onClick={() => { setTab('raw'); setMenuOpen(false); setEditor(null); setNotice('') }}>◎ 収集結果の確認（検証用）</button>
        <button className={tab === 'dashboard' ? 'nav-item selected' : 'nav-item'} onClick={() => {
          setTab('dashboard'); setEditor(null); setNotice('')
        }}>⌂ ダッシュボード{unreadNotifications > 0 && ` (${unreadNotifications})`}</button>
        <button className={tab === 'projects' ? 'nav-item selected' : 'nav-item'} onClick={() => {
          setTab('projects'); setCollectionSetup(false); setEditor(null); setNotice('')
        }}>▦ プロジェクト</button>
        <button className={tab === 'profiles' ? 'nav-item selected' : 'nav-item'} onClick={() => {
          setTab('profiles'); setCollectionSetup(false); setEditor(null); setNotice('')
        }}>◎ ターゲットプロファイル</button>
        <button className={tab === 'operation' ? 'nav-item selected' : 'nav-item'} onClick={() => { setTab('operation'); setEditor(null); setNotice('') }}>▶ 担当者の作業ガイド</button>
        {user.is_admin && <button className={tab === 'improvements' ? 'nav-item selected' : 'nav-item'} onClick={() => { setTab('improvements'); setEditor(null); setNotice('') }}>改善候補</button>}
        {user.is_admin && <button className={tab === 'settings' ? 'nav-item selected' : 'nav-item'} onClick={() => {
          setTab('settings'); setEditor(null); setNotice('')
        }}>⚙ 運用設定</button>}
        <button className={tab === 'installation' ? 'nav-item selected' : 'nav-item'} onClick={() => { setTab('installation'); setEditor(null); setNotice('') }}>↓ 導入・ダウンロード</button>
        <button className="nav-item" onClick={() => setGuideOpen(true)}>？ 使い方ガイド</button>
      </nav>
      <div className="sidebar-footer"><p className="break-all">{user.email}</p>
        <button className="nav-item" disabled={busy} onClick={() => void action(async () => {
          await api('/auth/logout', 'POST'); onLogout()
        })}>ログアウト</button></div>
      </div>
    </aside>
    <main className="workspace"><OutboundStatus /><header><p className="eyebrow">YOUR WORKSPACE</p>
      <div className="page-heading"><div><h1>{tab === 'targets' ? '収集ターゲット設定' : tab === 'analysis' ? 'リスト解析' : tab === 'results' ? '収集リストの確認' : tab === 'sales' ? '営業準備' : tab === 'improvements' ? '改善候補' : tab === 'installation' ? '導入・ダウンロード' : tab === 'operation' ? '担当者の作業ガイド' : tab === 'raw' ? '収集結果の確認' : tab === 'approvals' ? '承認キュー' : tab === 'dashboard' ? 'ダッシュボード' : tab === 'projects' ? 'プロジェクト' : tab === 'collection' ? '企業収集' : tab === 'companies' ? '企業一覧' : tab === 'deliveries' ? 'メール配信状況' : tab === 'settings' ? '運用設定' : 'ターゲットプロファイル'}</h1>
        <p className="muted">{tab === 'targets' ? 'ターゲット設定 → 収集 → 解析 → 結果確認。解析は後からでもできます。' : tab === 'analysis' ? '保存済みリストを選び、後からWeb解析・AI判定。' : tab === 'results' ? '収集した候補を確認してOK・NG・URL修正を記録。' : tab === 'sales' ? '収集したリストからDMを準備し、人の確認後に送信する。' : tab === 'improvements' ? '改善候補を確認し、理由付きで判断を記録。採用しても本番ルールは変わりません。' : tab === 'installation' ? 'クラウド版・ローカル版の使い始め方と配布リンク。' : tab === 'operation' ? '収集・入力・結果記録を、実際に使いながら進める。' : tab === 'raw' ? '候補を順番に確認して、営業対象かどうかを記録。' : tab === 'approvals' ? '提案内容を確認し、Human承認を記録。' : tab === 'dashboard' ? '営業リスト全体の進捗を確認。' : tab === 'projects' ? '営業目的ごとに、ターゲットと地域を整理。' : tab === 'collection' ? '検索・URL・CSVから営業候補を登録。' : tab === 'companies' ? '優先順位と営業状況を確認・更新。' : tab === 'deliveries' ? '送信予約と配信結果をプロジェクトごとに確認。' : tab === 'settings' ? '収集・AI・メール送受信に使う運用設定を管理。' : '検索条件と評価基準を、業種に合わせて管理。'}</p></div>
        {!editor && (tab === 'projects' || tab === 'profiles') && <button disabled={!loaded || loading || busy} onClick={() => {
          setEditor({ type: tab === 'projects' ? 'project' : 'profile' }); setNotice('')
        }}>＋ {tab === 'projects' ? 'プロジェクトを作成' : 'プロファイルを作成'}</button>}
      </div></header>
      {error && <div className="error" role="alert">{error}<button className="secondary ml-4" disabled={busy}
        onClick={() => void action(reload)}>再読み込み</button></div>}
      {notice && <p className="notice" role="status">{notice}</p>}
      {!editor && ['targets', 'collection', 'analysis', 'results'].includes(tab) && <nav className="panel mb-5 actions" aria-label="収集の作業順">
        <button className={tab === 'targets' ? '' : 'secondary'} aria-current={tab === 'targets' ? 'step' : undefined} onClick={() => setTab('targets')}>1. ターゲット設定</button>
        <button className={tab === 'collection' ? '' : 'secondary'} aria-current={tab === 'collection' ? 'step' : undefined} disabled={!canCollect} onClick={() => setTab('collection')}>2. 収集開始</button>
        <button className={tab === 'analysis' ? '' : 'secondary'} aria-current={tab === 'analysis' ? 'step' : undefined} disabled={!canCollect} onClick={() => setTab('analysis')}>3. リスト解析</button>
        <button className={tab === 'results' ? '' : 'secondary'} aria-current={tab === 'results' ? 'step' : undefined} onClick={() => setTab('results')}>4. 結果確認</button>
      </nav>}
      {loading ? <p role="status">読み込み中…</p> : editor?.type === 'project' ?
        <ProjectForm key={editor.value?.id ?? 'new'} profiles={profiles} initial={editor.value} profileId={editor.profileId}
          collectionSetup={collectionSetup} onSaved={collectionSetup ? savedTarget : saved} onCancel={() => { setEditor(null); setCollectionSetup(false) }} /> : editor?.type === 'profile' ?
        <ProfileForm key={editor.value?.id ?? 'new'} initial={editor.value} onSaved={saved} onCreateProject={profileId => { setTab(collectionSetup ? 'targets' : 'projects'); setEditor({ type: 'project', profileId }) }}
          onCancel={() => setEditor(null)} /> : loaded && tab === 'targets' ? <CollectionTargets onProjectSelected={setCollectionProjectId} initialProjectId={collectionProjectId} projects={currentProjects} profiles={profiles} roles={projectRoles}
          onCreate={() => configureTarget()} onEdit={configureTarget}
          onAssist={() => { closeGuide(); setCollectionSetup(true); setTab('profiles'); setEditor({ type: 'profile' }) }}
          onCollect={id => { setCollectionProjectId(id); setTab('collection'); setNotice('') }} /> : loaded && tab === 'results' ? <CollectionResults key={collectionProjectId} initialProjectId={collectionProjectId} projects={currentProjects} roles={projectRoles} onProjectSelected={setCollectionProjectId} /> : loaded && tab === 'sales' ?
          <SalesWorkspace onProjectSelected={setCollectionProjectId} projects={currentProjects} roles={projectRoles} initialProjectId={collectionProjectId}
            onNavigate={(destination, id) => { setCollectionProjectId(id); setCompletionCompanyId(null); setCompletionReturnContext(null); setReplyInboundEmailId(null); setFollowupCompanyId(null); setTab(destination); setNotice('') }} /> : loaded && tab === 'improvements' && user.is_admin ? <FeedbackProposalsPage projects={projects.filter(p => projectRoles[p.id] === 'owner')} /> : loaded && tab === 'installation' ? <InstallationGuide onGuide={() => setTab('operation')} /> : loaded && tab === 'operation' ? <OperatorGuide projects={currentProjects} projectRoles={projectRoles} onNavigate={navigateForOperator} onCreateProject={openProjectCreator} /> : loaded && tab === 'projects' ? <>
          <section className="panel mb-5"><h2>サービスURLから営業を準備する</h2><p className="muted mt-2">URLを入力し、AIのターゲット・検索語案を確認して収集条件を作れます。</p><div className="mt-3 flex flex-wrap gap-3"><button disabled={busy} onClick={() => { setTab('profiles'); setEditor({ type: 'profile' }); setNotice('') }}>URLから営業条件を作る</button><button className="secondary" onClick={() => setTab('operation')}>担当者の作業ガイドを開く</button></div></section>
          <div className="section-heading"><h2>{showArchivedProjects ? 'すべてのプロジェクト' : '運用中のプロジェクト'}</h2><span className="badge">{visibleProjects.length} 件</span></div>
          <label className="mb-4 flex items-center gap-2"><input type="checkbox" checked={showArchivedProjects} onChange={event => setShowArchivedProjects(event.target.checked)} />アーカイブを表示（{archivedCount}件）</label>
          <p className="muted mb-4">検証や終了した案件は「編集」からアーカイブできます。企業データ・履歴は残り、ステータスを戻すと通常一覧へ戻せます。</p>
          {visibleProjects.length === 0 ? <section className="panel empty"><div className="empty-icon">▦</div>
            <h2>{archivedCount ? '運用中のプロジェクトはありません' : '最初のプロジェクトを作成しましょう'}</h2><p className="muted">標準プロファイルを選び、案件名・提案内容・地域を入力するだけで始められます。{archivedCount > 0 && '過去の案件は「アーカイブを表示」で確認できます。'}</p>
            <div className="mt-6 flex flex-wrap justify-center gap-3"><button onClick={() => setEditor({ type: 'project' })}>プロジェクトを作る</button><button className="secondary" onClick={() => setGuideOpen(true)}>使い方を見る</button></div></section> :
            <div className="grid gap-5 xl:grid-cols-2">{visibleProjects.map(project => <article className="panel" key={project.id}>
              <div className="flex justify-between gap-3"><h2>{project.project_name}</h2><span className="badge">{statusNames[project.status]}</span></div>
              <p className="muted mt-3">{profiles.find(p => p.id === project.target_profile_id)?.profile_name ?? 'プロファイル'}</p>
              <p className="my-5 whitespace-pre-wrap">{project.sales_objective}</p>
              <div className="card-footer"><span className="muted">地域：{project.region}</span>
                <div className="flex flex-wrap gap-2">{projectRoles[project.id] !== 'viewer' && <button disabled={busy} onClick={() => {
                  setCollectionProjectId(project.id); setTab('collection'); setNotice('')
                }}>企業収集</button>}<button className="secondary" disabled={busy} onClick={() => {
                  setCompletionCompanyId(null); setCollectionProjectId(project.id); setTab('companies'); setNotice('')
                }}>企業一覧</button>{projectRoles[project.id] === 'owner' && <><button className="secondary" disabled={busy} onClick={() => void openMembers(project).catch(e => setError(errorMessage(e)))}>メンバー</button><button className="secondary" disabled={busy} onClick={() => setEditor({ type: 'project', value: project })}>編集</button>
                  <button className="danger" disabled={busy} onClick={() => {
                    if (window.confirm(`「${project.project_name}」を削除しますか？`)) void action(async () => {
                      await api(`/projects/${project.id}`, 'DELETE'); await reload(); setNotice('削除しました。')
                    })
                  }}>削除</button></>}</div></div>
            </article>)}</div>}
          {memberProject && <section className="panel mt-6" aria-label="プロジェクトメンバー"><div className="flex justify-between gap-3"><div><h2>{memberProject.project_name}のメンバー</h2><p className="muted mt-2 text-sm">編集者は操作可能、閲覧者は参照のみです。</p></div><button className="secondary" onClick={() => setMemberProject(null)}>閉じる</button></div><div className="detail-grid mt-4"><label className="field">メンバーのメール<input type="email" value={memberEmail} onChange={e => setMemberEmail(e.target.value)} /></label><label className="field">権限<select value={memberRole} onChange={e => setMemberRole(e.target.value as 'editor' | 'viewer')}><option value="editor">編集者</option><option value="viewer">閲覧者</option></select></label></div><div className="actions"><button disabled={busy || !memberEmail.trim()} onClick={() => void saveMember()}>メンバーを保存</button></div>{members.map(member => <article className="job-row" key={member.id}><div><strong>{member.email}</strong><p className="muted text-sm">{member.role === 'owner' ? '所有者' : member.role === 'editor' ? '編集者' : '閲覧者'}</p></div>{member.role !== 'owner' && <button className="danger" disabled={busy} onClick={() => void removeMember(member)}>削除</button>}</article>)}</section>}
        </> : loaded && (tab === 'collection' || tab === 'analysis') ? <CollectionPage key={`${tab}-${collectionProjectId}`} mode={tab === 'analysis' ? 'analysis' : 'collection'} onProjectSelected={setCollectionProjectId} onConfigureTarget={() => configureTarget()} projects={projects.filter(project => projectRoles[project.id] !== 'viewer')} profiles={profiles}
          initialProjectId={collectionProjectId} /> : loaded && tab === 'companies' ?
          <>{completionCompanyId && completionReturnContext && <section className="panel mb-4" aria-label="作業キューへの戻り先">
            <p>企業詳細の変更は必要に応じて保存してください。戻る操作で自動保存・承認・送信は行いません。</p>
            <button className="secondary mt-3" onClick={() => { setCompletionCompanyId(null); setTab('dashboard'); setNotice('') }}>作業キューへ戻る</button>
          </section>}<CompaniesPage projects={projects} projectRoles={projectRoles} initialProjectId={collectionProjectId} initialReplyInboundEmailId={replyInboundEmailId} initialFollowupCompanyId={followupCompanyId} initialCompanyId={completionCompanyId} /></> : loaded && tab === 'dashboard' ?
          <DashboardPage completionReturnContext={completionReturnContext} onOpenCompany={(context, companyId) => {
            setCompletionReturnContext(context); setCollectionProjectId(context.projectId); setReplyInboundEmailId(null); setFollowupCompanyId(null); setCompletionCompanyId(companyId); setTab('companies'); setNotice('')
          }} onUnreadChange={setUnreadNotifications} onOpenInboundReply={(projectId, inboundEmailId) => {
            setCompletionCompanyId(null); setCollectionProjectId(projectId); setFollowupCompanyId(null); setReplyInboundEmailId(inboundEmailId); setTab('companies'); setNotice('')
          }} onOpenFollowup={(projectId, companyId) => {
            setCompletionCompanyId(null); setCollectionProjectId(projectId); setReplyInboundEmailId(null); setFollowupCompanyId(companyId); setTab('companies'); setNotice('')
          }} /> : loaded && tab === 'settings' ?
          <SmtpSettingsPage defaultRecipient={user.email} /> : loaded && tab === 'raw' ? <RawCollectionBenchmarkPage /> : loaded && tab === 'deliveries' ?
          <EmailDeliveriesPage key={collectionProjectId} initialProjectId={collectionProjectId} projects={projects} projectRoles={projectRoles} /> : loaded && tab === 'approvals' ?
          <ApprovalQueuePage key={collectionProjectId} initialProjectId={collectionProjectId} projects={projects} projectRoles={projectRoles} /> : loaded && <>
          <div className="section-heading"><h2>プロファイル一覧</h2><span className="badge">{profiles.length} 件</span></div>
          <p className="muted mb-5">標準プロファイルは複製して編集できます。案件専用の条件も、複製して設定してください。</p>
          {profiles.length === 0 && <p className="panel empty">プロファイルがありません。新規作成してください。</p>}
          <div className="grid gap-5 xl:grid-cols-2">{profiles.map(profile => <article className="panel" key={profile.id}>
            <div className="flex justify-between gap-3"><h2>{profile.profile_name}</h2>
              <span className="badge">{profile.is_system ? '標準' : 'カスタム'}{!profile.active && ' / 無効'}</span></div>
            <p className="muted my-4 whitespace-pre-wrap">{profile.description || '説明は未設定です。'}</p>
            <div className="flex flex-wrap gap-2 mb-6">{profile.search_keywords.map((keyword, i) => <span key={i} className="keyword">{keyword}</span>)}</div>
            <div className="card-footer"><span className="muted text-sm">地域：{profile.default_regions.join(' / ') || '未設定'}</span>
              <div className="flex flex-wrap gap-2"><button className="secondary" disabled={busy} onClick={() => void action(async () => {
                const clone = await api<Profile>(`/target-profiles/${profile.id}/clone`, 'POST')
                await reload(); setEditor({ type: 'profile', value: clone })
              })}>複製</button>
                {!profile.is_system && <><button className="secondary" disabled={busy} onClick={() => setEditor({ type: 'profile', value: profile })}>編集</button>
                  <button className="danger" disabled={busy} onClick={() => {
                    if (window.confirm(`「${profile.profile_name}」を削除しますか？`)) void action(async () => {
                      await api(`/target-profiles/${profile.id}`, 'DELETE'); await reload(); setNotice('削除しました。')
                    })
                  }}>削除</button></>}
              </div></div>
          </article>)}</div>
        </>}
    </main>
    <OnboardingGuide open={loaded && guideOpen} projectCount={currentProjects.length} totalCompanies={totalCompanies}
      isAdmin={user.is_admin} onClose={closeGuide} onCreateProject={openProjectCreator} onNavigate={navigateFromGuide} />
  </div>
}

export function App() {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState('')
  useEffect(() => {
    api<User>('/auth/me').then(setUser).catch(e => {
      if (!(e instanceof ApiError && e.status === 401)) setNotice(errorMessage(e))
    }).finally(() => setLoading(false))
  }, [])
  useEffect(() => {
    function expire() { setUser(null); if (user) setNotice('セッションが切れました。再度ログインしてください。') }
    window.addEventListener('session-expired', expire)
    return () => window.removeEventListener('session-expired', expire)
  }, [user])
  if (loading) return <main className="p-12" role="status">読み込み中…</main>
  return user ? <Workspace user={user} onLogout={() => { setUser(null); setNotice('') }} /> :
    <Login notice={notice} onLogin={value => { setUser(value); setNotice('') }} />
}
