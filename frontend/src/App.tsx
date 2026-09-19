import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { allPages, api, ApiError, errorMessage } from './api'
import { Field, ProfileForm, ProjectForm } from './forms'
import { CollectionPage } from './CollectionPage'
import { CompaniesPage } from './CompaniesPage'
import { DashboardPage } from './DashboardPage'
import type { Profile, Project, User } from './types'

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

type Editor = { type: 'project'; value?: Project } | { type: 'profile'; value?: Profile } | null
const statusNames = { draft: '下書き', active: '進行中', archived: 'アーカイブ' }

function Workspace({ user, onLogout }: { user: User; onLogout: () => void }) {
  const [tab, setTab] = useState<'dashboard' | 'projects' | 'collection' | 'companies' | 'profiles'>('projects')
  const [collectionProjectId, setCollectionProjectId] = useState('')
  const [projects, setProjects] = useState<Project[]>([])
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [editor, setEditor] = useState<Editor>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const reload = useCallback(async () => {
    const [nextProjects, nextProfiles] = await Promise.all([
      allPages<Project>('/projects'), allPages<Profile>('/target-profiles'),
    ])
    setProjects(nextProjects); setProfiles(nextProfiles); setLoaded(true)
  }, [])
  useEffect(() => {
    reload().catch(e => setError(errorMessage(e))).finally(() => setLoading(false))
  }, [reload])
  async function action(fn: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try { await fn() } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false) }
  }
  async function saved() {
    setEditor(null); setNotice('保存しました。')
    try { await reload() } catch (e) { setError(errorMessage(e)) }
  }
  return <div className="app-layout">
    <aside className="sidebar"><div className="brand">⬡ LeadHive</div>
      <p className="nav-label">ワークスペース</p>
      <nav aria-label="メインナビゲーション">
        <button className={tab === 'dashboard' ? 'nav-item selected' : 'nav-item'} onClick={() => {
          setTab('dashboard'); setEditor(null); setNotice('')
        }}>⌂ ダッシュボード</button>
        <button className={tab === 'projects' ? 'nav-item selected' : 'nav-item'} onClick={() => {
          setTab('projects'); setEditor(null); setNotice('')
        }}>▦ プロジェクト</button>
        <button className={tab === 'profiles' ? 'nav-item selected' : 'nav-item'} onClick={() => {
          setTab('profiles'); setEditor(null); setNotice('')
        }}>◎ ターゲットプロファイル</button>
        <button className={tab === 'collection' ? 'nav-item selected' : 'nav-item'} onClick={() => {
          setTab('collection'); setEditor(null); setNotice('')
        }}>⌕ 企業収集</button>
        <button className={tab === 'companies' ? 'nav-item selected' : 'nav-item'} onClick={() => {
          setTab('companies'); setEditor(null); setNotice('')
        }}>▤ 企業一覧</button>
      </nav>
      <div className="sidebar-footer"><p className="break-all">{user.email}</p>
        <button className="nav-item" disabled={busy} onClick={() => void action(async () => {
          await api('/auth/logout', 'POST'); onLogout()
        })}>ログアウト</button></div>
    </aside>
    <main className="workspace"><header><p className="eyebrow">YOUR WORKSPACE</p>
      <div className="page-heading"><div><h1>{tab === 'dashboard' ? 'ダッシュボード' : tab === 'projects' ? 'プロジェクト' : tab === 'collection' ? '企業収集' : tab === 'companies' ? '企業一覧' : 'ターゲットプロファイル'}</h1>
        <p className="muted">{tab === 'dashboard' ? '営業リスト全体の進捗を確認。' : tab === 'projects' ? '営業目的ごとに、ターゲットと地域を整理。' : tab === 'collection' ? '検索・URL・CSVから営業候補を登録。' : tab === 'companies' ? '優先順位と営業状況を確認・更新。' : '検索条件と評価基準を、業種に合わせて管理。'}</p></div>
        {!editor && (tab === 'projects' || tab === 'profiles') && <button disabled={!loaded || loading || busy} onClick={() => {
          setEditor({ type: tab === 'projects' ? 'project' : 'profile' }); setNotice('')
        }}>＋ {tab === 'projects' ? 'プロジェクトを作成' : 'プロファイルを作成'}</button>}
      </div></header>
      {error && <div className="error" role="alert">{error}<button className="secondary ml-4" disabled={busy}
        onClick={() => void action(reload)}>再読み込み</button></div>}
      {notice && <p className="notice" role="status">{notice}</p>}
      {loading ? <p role="status">読み込み中…</p> : editor?.type === 'project' ?
        <ProjectForm key={editor.value?.id ?? 'new'} profiles={profiles} initial={editor.value}
          onSaved={saved} onCancel={() => setEditor(null)} /> : editor?.type === 'profile' ?
        <ProfileForm key={editor.value?.id ?? 'new'} initial={editor.value} onSaved={saved}
          onCancel={() => setEditor(null)} /> : loaded && tab === 'projects' ? <>
          <div className="section-heading"><h2>すべてのプロジェクト</h2><span className="badge">{projects.length} 件</span></div>
          {projects.length === 0 ? <section className="panel empty"><div className="empty-icon">▦</div>
            <h2>最初のプロジェクトを作成しましょう</h2><p className="muted">営業目的とターゲットを決めるところから始められます。</p></section> :
            <div className="grid gap-5 xl:grid-cols-2">{projects.map(project => <article className="panel" key={project.id}>
              <div className="flex justify-between gap-3"><h2>{project.project_name}</h2><span className="badge">{statusNames[project.status]}</span></div>
              <p className="muted mt-3">{profiles.find(p => p.id === project.target_profile_id)?.profile_name ?? 'プロファイル'}</p>
              <p className="my-5 whitespace-pre-wrap">{project.sales_objective}</p>
              <div className="card-footer"><span className="muted">地域：{project.region}</span>
                <div className="flex flex-wrap gap-2"><button disabled={busy} onClick={() => {
                  setCollectionProjectId(project.id); setTab('collection'); setNotice('')
                }}>企業収集</button><button className="secondary" disabled={busy} onClick={() => {
                  setCollectionProjectId(project.id); setTab('companies'); setNotice('')
                }}>企業一覧</button><button className="secondary" disabled={busy} onClick={() => setEditor({ type: 'project', value: project })}>編集</button>
                  <button className="danger" disabled={busy} onClick={() => {
                    if (window.confirm(`「${project.project_name}」を削除しますか？`)) void action(async () => {
                      await api(`/projects/${project.id}`, 'DELETE'); await reload(); setNotice('削除しました。')
                    })
                  }}>削除</button></div></div>
            </article>)}</div>}
        </> : loaded && tab === 'collection' ? <CollectionPage projects={projects} profiles={profiles}
          initialProjectId={collectionProjectId} /> : loaded && tab === 'companies' ?
          <CompaniesPage projects={projects} initialProjectId={collectionProjectId} /> : loaded && tab === 'dashboard' ?
          <DashboardPage /> : loaded && <>
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
