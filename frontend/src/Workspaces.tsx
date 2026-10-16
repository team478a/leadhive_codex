import { useCallback, useEffect, useRef, useState } from 'react'
import { allPages, api, errorMessage } from './api'
import { CompanyCollectionFeedback } from './CompanyCollectionFeedback'
import { CleanListSendPanel } from './CleanListSendPanel'
import { FormReviewQueue } from './FormReviewQueue'
import { ApprovalQueuePage } from './ApprovalQueuePage'
import { SendFlowTemplatePanel } from './SendFlowTemplatePanel'
import { SendFlowDraftPanel } from './SendFlowDraftPanel'
import type { Company, CompanyPage, Profile, Project, ProjectMember } from './types'

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
  const [candidateCount, setCandidateCount] = useState(0)
  const [excludedCount, setExcludedCount] = useState(0)
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
    const currentFilter = showExcluded ? 'status=excluded' : 'exclude_status=excluded'
    const otherFilter = showExcluded ? 'exclude_status=excluded' : 'status=excluded'
    Promise.all([
      api<CompanyPage>(`/projects/${projectId}/company-list?offset=${page * 20}&limit=20&sort=newest&${currentFilter}`),
      api<CompanyPage>(`/projects/${projectId}/company-list?offset=0&limit=1&${otherFilter}`),
    ]).then(([current, other]) => {
      if (!active) return
      setItems(current.items)
      setCandidateCount(showExcluded ? other.total : current.total)
      setExcludedCount(showExcluded ? current.total : other.total)
    })
      .catch(e => { if (active) setError(errorMessage(e)) }).finally(() => { if (active) setBusy(false) })
    return () => { active = false }
  }, [projectId, revision, page, showExcluded])
  const company = items.find(c => c.id === selected)
  const readOnly = !projectId || !['owner', 'editor'].includes(roles[projectId])
  const visible = items
  async function organize() {
    if (readOnly || busy || organizing) return
    setOrganizing(true); setActionError(''); setNotice(''); setSelected(''); setPage(0)
    let moved = 0; let protectedCount = 0
    try {
      const allCompanies = await allPages<Company>(`/projects/${projectId}/companies`)
      for (let i = 0; i < allCompanies.length; i += 100) {
        const result = await api<{ excluded_ids: string[]; protected_ids: string[] }>(`/projects/${projectId}/source-exclusions/cleanup`, 'POST', { company_ids: allCompanies.slice(i, i + 100).map(c => c.id) })
        moved += result.excluded_ids.length; protectedCount += result.protected_ids.length
        setNotice(`まとめサイトを整理中：${Math.min(i + 100, allCompanies.length)} / ${allCompanies.length}件`)
      }
      setNotice(`${moved}件を収集対象外へ移しました。人の確認・営業状況などにより${protectedCount}件を保護しました。`)
    } catch (e) { setActionError(errorMessage(e)); setNotice(`整理済み${moved}件。途中までの結果を保存しています。`) }
    finally { setOrganizing(false); setRevision(v => v + 1) }
  }
  return <section aria-label="収集リストの確認">
    <div className="panel mb-5"><h2>集まった候補を確認する</h2><p>対象企業のOK・NG、問い合わせ候補の確認・URL修正を記録できます。文面準備から送信までは「送信の準備・実行」にまとまっています。</p>
      {project ? <label className="field mt-3">確認する収集リスト<select disabled={organizing} value={project.id} onChange={e => { setPage(0); setSelected(''); setNotice(''); setActionError(''); onProjectSelected(e.target.value) }}>{projects.map(p => <option value={p.id} key={p.id}>{p.project_name}</option>)}</select></label> : <p>まだ収集リストがありません。</p>}
      <p className="mt-3">候補 {candidateCount}件 / 収集対象外 {excludedCount}件</p>
      <div className="actions flex-wrap"><button className="secondary" disabled={readOnly || busy || organizing || !items.length} onClick={() => void organize()}>{organizing ? '整理中…' : '既知のまとめサイトを整理'}</button><button className="secondary" disabled={organizing} onClick={() => { setShowExcluded(v => !v); setPage(0); setSelected('') }}>{showExcluded ? '候補に戻る' : '収集対象外を見る'}</button></div>
      <p className="muted text-sm">確認済みの掲載媒体だけを自動整理します。データや人の判定は削除しません。</p>
    </div>
    {notice && <p role="status" className="panel">{notice}</p>}
    {actionError && <p role="alert" className="error">{actionError}</p>}
    {busy && !notice && <p role="status">リストを読み込み中…</p>}
    {error && <p className="error" role="alert">{error}<button className="secondary" onClick={() => setRevision(v => v + 1)}>再読み込み</button></p>}
    {!busy && !error && project && (showExcluded ? excludedCount : candidateCount) === 0 && <p className="panel">{showExcluded ? '収集対象外の候補はありません。' : '候補はまだありません。収集開始画面から収集してください。'}</p>}
    {visible.map(c => <article className="panel mb-3" key={c.id}><h3>{c.company_name}</h3><p className="muted break-words">{c.address || '住所未取得'}</p>
      <p className="mt-2">{publicLink(c.website_url) ? <a href={publicLink(c.website_url)} target="_blank" rel="noreferrer">企業サイトを開く ↗</a> : '企業サイト未取得'} / {c.contact_url ? '問い合わせ候補あり（未確認を含む）' : '問い合わせ候補未検出'}</p>
      {(c.do_not_contact || c.status === 'excluded') && <p className="mt-2">{c.do_not_contact ? '連絡禁止' : '対象外'}</p>}
      <button className="secondary mt-3" onClick={() => setSelected(v => v === c.id ? '' : c.id)}>{selected === c.id ? '確認を閉じる' : '取得結果を確認する'}</button>
      {selected === c.id && c.status === 'excluded' && <SourceCleanupRestore company={c} readOnly={readOnly} onSaved={() => { setSelected(''); setPage(0); setRevision(v => v + 1) }} />}
      {company?.id === c.id && <CompanyCollectionFeedback company={company} initialSubject="company" readOnly={readOnly} onSaved={() => setRevision(v => v + 1)} />}
    </article>)}
    {(showExcluded ? excludedCount : candidateCount) > 20 && <div className="actions"><button className="secondary" disabled={page === 0 || busy} onClick={() => { setPage(v => v - 1); setSelected('') }}>前の20件</button><span>{page + 1} / {Math.ceil((showExcluded ? excludedCount : candidateCount) / 20)}</span><button className="secondary" disabled={(page + 1) * 20 >= (showExcluded ? excludedCount : candidateCount) || busy} onClick={() => { setPage(v => v + 1); setSelected('') }}>次の20件</button></div>}
  </section>
}

type SendFlowSummary = {
  readiness_completed_at: string | null; target_company_count: number
  draft_counts: Record<'email' | 'form', number>; form_reviewed_count: number
  approval_counts: { pending: Record<'email' | 'form', number>; approved_unsent: Record<'email' | 'form', number> }
  today: { sent: number; reserved: number }; results: { sent: number; failed: number; unknown: number }
}

export function SalesWorkspace({ projects, roles, initialProjectId, onNavigate, onProjectSelected }: {
  projects: Project[]; roles: Roles; initialProjectId: string; onProjectSelected: (id: string) => void
  onNavigate: (destination: 'companies' | 'approvals' | 'deliveries', id: string) => void
}) {
  const [selected, setSelected] = useState(initialProjectId || projects[0]?.id || '')
  const [sending, setSending] = useState(false)
  const [activeStep, setActiveStep] = useState(1)
  const [templateCount, setTemplateCount] = useState<number | null>(null)
  const [summary, setSummary] = useState<SendFlowSummary | null>(null)
  const [summaryError, setSummaryError] = useState('')
  const initializedProject = useRef('')
  const project = projects.find(p => p.id === selected) || projects[0]
  const projectId = project?.id
  const canWrite = Boolean(projectId && ['owner', 'editor'].includes(roles[projectId] ?? ''))
  useEffect(() => { setSelected(initialProjectId || projects[0]?.id || '') }, [initialProjectId, projects])
  const refreshSummary = useCallback(async () => {
    if (!projectId) { setSummary(null); return }
    setSummaryError('')
    try { setSummary(await api<SendFlowSummary>(`/projects/${projectId}/send-flow-summary`)) }
    catch (e) { setSummaryError(errorMessage(e)) }
  }, [projectId])
  useEffect(() => {
    let live = true
    if (!projectId) { setSummary(null); setTemplateCount(null); return }
    setSummaryError('')
    Promise.all([
      api<SendFlowSummary>(`/projects/${projectId}/send-flow-summary`),
      api<import('./types').OutreachTemplate[]>(`/projects/${projectId}/outreach-templates`),
    ]).then(([nextSummary, templates]) => {
      if (!live) return
      setSummary(nextSummary); setTemplateCount(templates.length)
      if (initializedProject.current !== projectId) {
        initializedProject.current = projectId
        const draftTotal = nextSummary.draft_counts.email + nextSummary.draft_counts.form
        const waitingApproval = Object.values(nextSummary.approval_counts.pending).some(count => count > 0)
          || Object.values(nextSummary.approval_counts.approved_unsent).some(count => count > 0)
        setActiveStep(templates.length === 0 ? 1 : draftTotal === 0 ? 2
          : nextSummary.draft_counts.form > nextSummary.form_reviewed_count ? 3
            : waitingApproval ? 4 : nextSummary.today.reserved > 0 ? 5 : 6)
      }
    }).catch(e => { if (live) setSummaryError(errorMessage(e)) })
    return () => { live = false }
  }, [projectId])
  const goToStep = useCallback((step: number) => {
    setActiveStep(step)
    requestAnimationFrame(() => document.getElementById(`send-flow-step-${step}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }, [])
  const afterDrafts = useCallback((channel: 'email' | 'form') => {
    void refreshSummary()
    goToStep(channel === 'form' ? 3 : 4)
  }, [goToStep, refreshSummary])
  const draftTotal = (summary?.draft_counts.email ?? 0) + (summary?.draft_counts.form ?? 0)
  const pendingApprovals = summary ? Object.values(summary.approval_counts.pending).reduce((sum, count) => sum + count, 0) : 0
  const approvedUnsent = summary ? Object.values(summary.approval_counts.approved_unsent).reduce((sum, count) => sum + count, 0) : 0
  const steps = [
    { id: 1, title: '文面テンプレート', metric: templateCount === null ? '確認中' : `${templateCount}件`, state: templateCount ? '準備済み' : '作成してください' },
    { id: 2, title: '送信先と文面を用意', metric: `${draftTotal}社`, state: draftTotal ? '下書きあり' : '対応が必要' },
    { id: 3, title: 'フォームを確認', metric: summary ? `${Math.min(summary.form_reviewed_count, summary.draft_counts.form)} / ${summary.draft_counts.form}社` : '確認中', state: summary?.draft_counts.form ? '人の確認が必要' : 'フォームなし・スキップ' },
    { id: 4, title: '承認', metric: `承認待ち ${pendingApprovals}件 · 未送信 ${approvedUnsent}件`, state: pendingApprovals ? '承認待ち' : '確認してください' },
    { id: 5, title: '送信', metric: `本日 送信 ${summary?.today.sent ?? 0}件 · 予約 ${summary?.today.reserved ?? 0}件`, state: '承認済みのみ' },
    { id: 6, title: '結果', metric: `送信済み ${summary?.results.sent ?? 0} · 失敗 ${summary?.results.failed ?? 0} · 不明 ${summary?.results.unknown ?? 0}`, state: '結果を確認' },
  ]
  return <section aria-label="営業作業">
    <div className="panel mb-5"><h2>送信までの流れ</h2><p className="mt-2">文面作成から結果確認まで、上から順に進めます。下書き作成後も送信には人の確認と承認が必要です。</p>
      {project ? <><label className="field mt-4">対象プロジェクト<select disabled={sending} value={project.id} onChange={event => { setSelected(event.target.value); onProjectSelected(event.target.value); setSummary(null); setTemplateCount(null); initializedProject.current = '' }}>{projects.map(item => <option value={item.id} key={item.id}>{item.project_name}</option>)}</select></label>
        {summaryError && <p role="alert" className="error mt-3">{summaryError}<button type="button" className="secondary ml-2" onClick={() => void refreshSummary()}>再読み込み</button></p>}
        <section className="mt-4 rounded-lg border p-4" aria-label="送信フローの進捗">
          <h3>進み具合</h3><p className="muted mt-1 text-sm">送信可否集計の対象 {summary?.target_company_count ?? '…'}社 · {summary?.readiness_completed_at ? `最終集計 ${new Date(summary.readiness_completed_at).toLocaleString('ja-JP')}` : '送信可否集計なし'}</p>
          <ol className="flow-steps mt-3">{steps.map(step => <li key={step.id} className={activeStep === step.id ? 'border-[#235c4c]' : ''}>
            <strong>{step.id}. {step.title}</strong><span>{step.metric}</span><span className="badge">{step.state}</span>
          </li>)}</ol>
          <button type="button" className="secondary mt-3" disabled={sending} onClick={() => void refreshSummary()}>進捗を更新</button>
        </section>
      </> : <p className="mt-3">収集ターゲットを設定し、リストを収集してから営業作業を始めてください。</p>}
    </div>
    {project && steps.map(step => <section id={`send-flow-step-${step.id}`} key={`${project.id}-${step.id}`} className="panel mb-4 scroll-mt-4" aria-label={`${step.id}. ${step.title}`}>
      <button type="button" className="flex w-full flex-wrap items-center justify-between gap-3 bg-transparent p-0 text-left text-inherit hover:bg-transparent" aria-expanded={activeStep === step.id} onClick={() => setActiveStep(current => current === step.id ? 0 : step.id)}>
        <span className="flex items-center gap-3"><span className="badge">{step.id}</span><strong role="heading" aria-level={2}>{step.id}. {step.title}</strong></span><span className="muted text-sm">{step.metric} · {step.state} {activeStep === step.id ? '−' : '+'}</span>
      </button>
      {activeStep === step.id && <div className="mt-5">
        {step.id === 1 && <SendFlowTemplatePanel key={`templates-${project.id}`} projectId={project.id} canWrite={canWrite} onContinue={() => goToStep(2)} onTemplateCountChange={setTemplateCount} />}
        {step.id === 2 && <SendFlowDraftPanel key={`drafts-${project.id}`} projectId={project.id} canWrite={canWrite} onContinue={channel => goToStep(channel === 'form' ? 3 : 4)} onNeedTemplate={() => goToStep(1)} onCreated={afterDrafts} />}
        {step.id === 3 && (summary?.draft_counts.form ? <><FormReviewQueue key={`form-review-${project.id}`} projectId={project.id} canWrite={canWrite} /><div className="actions"><button type="button" onClick={() => { goToStep(4); void refreshSummary() }}>次へ：承認</button></div></> : <><p className="muted">フォーム下書きがないため、この段階はありません。</p><div className="actions"><button type="button" onClick={() => goToStep(4)}>フォーム確認を飛ばして承認へ</button></div></>)}
        {step.id === 4 && <><p className="muted mb-4">既存の承認キューと日次承認を使用します。承認は送信を開始せず、宛先・文面を確認した人の操作と再認証が必要です。</p><ApprovalQueuePage key={`approval-${project.id}`} projects={[project]} projectRoles={{ [project.id]: roles[project.id] }} initialProjectId={project.id} /><div className="actions"><button type="button" className="secondary" onClick={() => onNavigate('approvals', project.id)}>承認キューを別画面で開く</button><button type="button" onClick={() => { goToStep(5); void refreshSummary() }}>次へ：送信</button></div></>}
        {step.id === 5 && <><p className="muted mb-4">承認済みの内容だけを予約します。フォームは承認後に既存の実行条件と上限に従って処理されます。停止中・実行OFFの場合は送信されません。</p>{canWrite ? <CleanListSendPanel key={`send-${project.id}`} projectId={project.id} canWrite onBusyChange={setSending} onNavigate={destination => onNavigate(destination, project.id)} /> : <p className="muted">送信予約は所有者または編集者が実行できます。</p>}<div className="actions"><button type="button" onClick={() => { goToStep(6); void refreshSummary() }}>次へ：結果</button></div></>}
        {step.id === 6 && <section aria-label="送信結果">
          <h3>送信結果の集計</h3><div className="mt-3 flex flex-wrap gap-3"><span className="badge">送信済み {summary?.results.sent ?? 0}件</span><span className="badge">失敗 {summary?.results.failed ?? 0}件</span><span className="badge">結果不明 {summary?.results.unknown ?? 0}件</span></div>
          <p className="muted mt-3">結果不明のものは再送せず、配信元の記録を確認してください。</p>
          <div className="actions"><button type="button" className="secondary" onClick={() => onNavigate('deliveries', project.id)}>配信結果ページを開く</button><button type="button" onClick={() => void refreshSummary()}>結果を更新</button></div>
        </section>}
      </div>}
    </section>)}
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
