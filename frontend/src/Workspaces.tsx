import { useCallback, useEffect, useRef, useState } from 'react'
import { allPages, api, errorMessage } from './api'
import { CompanyCollectionFeedback } from './CompanyCollectionFeedback'
import { FormReviewQueue } from './FormReviewQueue'
import { SendFlowTemplatePanel } from './SendFlowTemplatePanel'
import { SendFlowDraftPanel } from './SendFlowDraftPanel'
import { SendFlowApprovalPanel, SendFlowResultsPanel } from './SendFlowApprovalPanel'
import type { Company, CompanyPage, OperationJob, Profile, Project, ProjectMember } from './types'

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
  readiness_completed_at: string | null; latest_form_draft_updated_at: string | null; target_company_count: number
  draft_counts: Record<'email' | 'form', number>; form_reviewed_count: number
  approval_counts: { pending: Record<'email' | 'form', number>; approved_unsent: Record<'email' | 'form', number> }
  today: { sent: number; reserved: number }; results: { sent: number; failed: number; unknown: number }
}

type SendChannel = 'email' | 'form'
function storedSendChannel(projectId: string): SendChannel {
  try { return localStorage.getItem(`leadhive:send-channel:${projectId}`) === 'form' ? 'form' : 'email' }
  catch { return 'email' }
}
function persistSendChannel(projectId: string, channel: SendChannel) {
  try { localStorage.setItem(`leadhive:send-channel:${projectId}`, channel) } catch { return }
}

export function SalesWorkspace({ projects, roles, initialProjectId, isAdmin, onNavigate, onProjectSelected }: {
  projects: Project[]; roles: Roles; initialProjectId: string; onProjectSelected: (id: string) => void
  isAdmin: boolean
  onNavigate: (destination: 'companies' | 'approvals' | 'deliveries' | 'settings', id: string) => void
}) {
  const [selected, setSelected] = useState(initialProjectId || projects[0]?.id || '')
  const [channel, setChannel] = useState<SendChannel>(() => storedSendChannel(initialProjectId || projects[0]?.id || ''))
  const [activeStep, setActiveStep] = useState(1)
  const [templateCount, setTemplateCount] = useState<number | null>(null)
  const [templateRevision, setTemplateRevision] = useState(0)
  const [templateEditorOpen, setTemplateEditorOpen] = useState(false)
  const [templateEditorTemplateId, setTemplateEditorTemplateId] = useState('')
  const [summary, setSummary] = useState<SendFlowSummary | null>(null)
  const [summaryError, setSummaryError] = useState('')
  const [readinessStale, setReadinessStale] = useState(false)
  const [readinessJob, setReadinessJob] = useState<OperationJob | null>(null)
  const [reviewRevision, setReviewRevision] = useState(0)
  const [formReviewPendingCount, setFormReviewPendingCount] = useState<number | null>(null)
  const [formReadyCount, setFormReadyCount] = useState<number | null>(null)
  const readinessJobId = readinessJob?.id
  const readinessJobStatus = readinessJob?.status
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
      setSummary(nextSummary); setTemplateCount(templates.filter(template => template.channel === channel).length)
      const contextKey = `${projectId}:${channel}`
      if (initializedProject.current !== contextKey) {
        initializedProject.current = contextKey
        const draftCount = nextSummary.draft_counts[channel]
        const hasApprovalWork = nextSummary.approval_counts.pending[channel] + nextSummary.approval_counts.approved_unsent[channel] > 0
        const formNeedsReview = channel === 'form' && draftCount > nextSummary.form_reviewed_count
        setActiveStep(draftCount === 0 ? 1 : formNeedsReview ? 2 : hasApprovalWork ? (channel === 'form' ? 3 : 2) : channel === 'form' ? 4 : 3)
      }
    }).catch(e => { if (live) setSummaryError(errorMessage(e)) })
    return () => { live = false }
  }, [channel, projectId])
  useEffect(() => {
    if (!readinessJobId || !['queued', 'running'].includes(readinessJobStatus ?? '') || !projectId) return
    const timer = window.setInterval(() => {
      api<OperationJob[]>(`/projects/${projectId}/operations?limit=100`).then(rows => {
        const current = rows.find(job => job.id === readinessJobId)
        if (!current) return
        setReadinessJob(current)
        if (current.status === 'completed') {
          setReadinessStale(false); setReviewRevision(value => value + 1); void refreshSummary()
        }
        if (current.status === 'failed' || current.status === 'cancelled') setSummaryError(current.error_message || 'フォーム送信可否の再集計に失敗しました。')
      }).catch(error => setSummaryError(errorMessage(error)))
    }, 2000)
    return () => window.clearInterval(timer)
  }, [projectId, readinessJobId, readinessJobStatus, refreshSummary])
  useEffect(() => {
    let live = true
    setFormReviewPendingCount(null); setFormReadyCount(null)
    if (!projectId || channel !== 'form') return () => { live = false }
    api<{ counts: Record<string, number>; review_queue_eligible: number; ready_confirmation_pending?: number }>(`/projects/${projectId}/form-dm-readiness`).then(readiness => {
      if (!live) return
      setFormReadyCount(Math.max(0, (readiness.counts.READY ?? 0) - (readiness.ready_confirmation_pending ?? 0)))
      setFormReviewPendingCount(readiness.review_queue_eligible ?? 0)
    }).catch(error => { if (live) setSummaryError(errorMessage(error)) })
    return () => { live = false }
  }, [channel, projectId, reviewRevision])
  const goToStep = useCallback((step: number) => {
    setActiveStep(step)
    requestAnimationFrame(() => document.getElementById(`send-flow-step-${step}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }, [])
  const afterDrafts = useCallback((createdChannel: 'email' | 'form') => {
    void refreshSummary()
    if (createdChannel === 'form') setReadinessStale(true)
  }, [refreshSummary])
  const pendingApprovals = summary?.approval_counts.pending[channel] ?? 0
  const approvedUnsent = summary?.approval_counts.approved_unsent[channel] ?? 0
  const draftCount = summary?.draft_counts[channel] ?? 0
  const readinessOlderThanDrafts = Boolean(
    summary?.latest_form_draft_updated_at
    && (!summary.readiness_completed_at
      || new Date(summary.latest_form_draft_updated_at).getTime() > new Date(summary.readiness_completed_at).getTime()),
  )
  const formReadinessStale = readinessStale || readinessOlderThanDrafts
  const approvalStep = channel === 'form' ? 3 : 2
  const resultStep = channel === 'form' ? 4 : 3
  const steps = [
    { id: 1, title: '文面をつくる', metric: `${draftCount}社に文面あり`, state: templateCount === null ? '確認中' : templateCount ? `${templateCount}テンプレート` : 'テンプレートを選択' },
    ...(channel === 'form' ? [{ id: 2, title: 'フォームを確認', metric: `確認待ち ${formReviewPendingCount ?? '…'}社 · 確認不要：${formReadyCount ?? '…'}社`, state: '人の確認が必要' }] : []),
    { id: approvalStep, title: '承認して送る', metric: `承認待ち ${pendingApprovals}件 · 承認済み未予約 ${approvedUnsent}件`, state: pendingApprovals ? '確認してください' : '予約状況を確認' },
    { id: resultStep, title: '結果', metric: '送信済み・失敗・不明を確認', state: '履歴を確認' },
  ]
  return <section aria-label="営業作業">
    <div className="panel mb-5"><h2>送信の準備・実行</h2><p className="mt-2">連絡方法を選ぶと、その経路の文面・確認・承認・結果だけを表示します。</p>
      {project ? <><label className="field mt-4">対象プロジェクト<select value={project.id} onChange={event => { setSelected(event.target.value); onProjectSelected(event.target.value); setSummary(null); setTemplateCount(null); initializedProject.current = ''; setChannel(storedSendChannel(event.target.value)); setActiveStep(1); setReadinessJob(null); setReadinessStale(false); setTemplateEditorOpen(false); setTemplateEditorTemplateId('') }}>{projects.map(item => <option value={item.id} key={item.id}>{item.project_name}</option>)}</select></label>
        <div className="actions justify-start border-0 p-0 mt-4" role="group" aria-label="連絡方法"><button type="button" aria-pressed={channel === 'form'} className={channel === 'form' ? '' : 'secondary'} onClick={() => { setChannel('form'); setActiveStep(1); persistSendChannel(project.id, 'form') }}>フォーム</button><button type="button" aria-pressed={channel === 'email'} className={channel === 'email' ? '' : 'secondary'} onClick={() => { setChannel('email'); setActiveStep(1); persistSendChannel(project.id, 'email') }}>メール</button></div>
        {summaryError && <p role="alert" className="error mt-3">{summaryError}<button type="button" className="secondary ml-2" onClick={() => void refreshSummary()}>再読み込み</button></p>}
        <p className="muted mt-3 text-sm">{channel === 'form' ? 'フォーム' : 'メール'}だけを表示中</p>
      </> : <p className="mt-3">収集ターゲットを設定し、リストを収集してから営業作業を始めてください。</p>}
    </div>
    {project && steps.map(step => <section id={`send-flow-step-${step.id}`} key={`${project.id}-${step.id}`} className="panel mb-4 scroll-mt-4" aria-label={`${step.id}. ${step.title}`}>
      <div className="flex items-center gap-2"><button type="button" className="flex min-w-0 flex-1 flex-nowrap items-center justify-between gap-2 bg-transparent p-0 text-left text-inherit hover:bg-transparent" aria-expanded={activeStep === step.id} onClick={() => setActiveStep(current => current === step.id ? 0 : step.id)}>
        <span className="flex min-w-0 items-center gap-2"><span className="badge shrink-0">{step.id}</span><strong className="truncate" role="heading" aria-level={2}>{step.id}. {step.title}</strong></span><span className="muted max-w-[55%] shrink text-right text-xs">{step.metric} · {step.state} {activeStep === step.id ? '−' : '+'}</span>
      </button>{channel === 'form' && step.id === 1 && <button type="button" className="secondary shrink-0 text-xs" disabled={!canWrite || Boolean(readinessJob && ['queued', 'running'].includes(readinessJob.status))} onClick={() => {
        if (!projectId) return
        setSummaryError(''); setReadinessStale(true)
        void api<OperationJob>(`/projects/${projectId}/form-dm-readiness/recalculate`, 'POST').then(job => {
          setReadinessJob(job)
          if (job.status === 'completed') { setReadinessStale(false); setReviewRevision(value => value + 1); void refreshSummary() }
        }).catch(error => setSummaryError(errorMessage(error)))
      }}>再集計</button>}</div>
      {activeStep === step.id && <div className="mt-5">
        {step.id === 1 && <>
          <SendFlowDraftPanel key={`drafts-${project.id}-${channel}-${templateRevision}`} projectId={project.id} channel={channel} canWrite={canWrite} readinessBusy={Boolean(readinessJob && ['queued', 'running'].includes(readinessJob.status))} onNeedTemplate={templateId => { setTemplateEditorTemplateId(templateId ?? ''); setTemplateEditorOpen(true) }} onCreated={afterDrafts} onNext={() => goToStep(channel === 'form' ? 2 : approvalStep)} />
          <details className="mt-4" open={templateEditorOpen} onToggle={event => setTemplateEditorOpen(event.currentTarget.open)}><summary>テンプレートを新しく作る・編集する</summary><div className="mt-4"><SendFlowTemplatePanel key={`templates-${project.id}-${channel}-${templateEditorTemplateId}`} projectId={project.id} channel={channel} canWrite={canWrite} initialTemplateId={templateEditorTemplateId} onTemplateCountChange={count => { setTemplateCount(count); setTemplateRevision(value => value + 1) }} /></div></details>
        </>}
        {channel === 'form' && step.id === 2 && <>
          {formReadinessStale && <p role="alert" className="error">集計が古いため再集計してください</p>}
          <FormReviewQueue key={`form-review-${project.id}-${reviewRevision}`} projectId={project.id} canWrite={canWrite} canManagePolicy={roles[project.id] === 'owner'} />
          <div className="actions"><button type="button" className="secondary" disabled={!canWrite || Boolean(readinessJob && ['queued', 'running'].includes(readinessJob.status))} onClick={() => {
            if (!projectId) return
            setSummaryError(''); setReadinessStale(true)
            void api<OperationJob>(`/projects/${projectId}/form-dm-readiness/recalculate`, 'POST').then(job => setReadinessJob(job)).catch(error => setSummaryError(errorMessage(error)))
          }}>{readinessJob && ['queued', 'running'].includes(readinessJob.status) ? '再集計中…' : 'フォーム送信可否を再集計'}</button><button type="button" onClick={() => goToStep(approvalStep)}>次へ：承認して送る</button></div>
          {readinessJob && <p className="muted" role="status">再集計 {readinessJob.status} · {readinessJob.processed_count}/{readinessJob.total_count}社</p>}
        </>}
        {step.id === approvalStep && <><SendFlowApprovalPanel key={`approve-${project.id}-${channel}`} projectId={project.id} channel={channel} canWrite={canWrite} canManageSettings={isAdmin} readinessCompletedAt={summary?.readiness_completed_at ?? null} readinessStale={readinessStale} onRefresh={refreshSummary} onSettings={() => onNavigate('settings', project.id)} /><div className="actions"><button type="button" className="secondary" onClick={() => onNavigate('approvals', project.id)}>高度な承認・検証を開く</button><button type="button" onClick={() => { goToStep(resultStep); void refreshSummary() }}>次へ：結果</button></div></>}
        {step.id === resultStep && <SendFlowResultsPanel key={`results-${project.id}-${channel}`} projectId={project.id} channel={channel} onDeliveries={() => onNavigate('deliveries', project.id)} />}
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
