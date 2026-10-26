import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { api, download, errorMessage, upload } from './api'
import { PresenceSearchControls } from './ExternalPresence'
import { defaultPresencePlan } from './externalPresenceShared'
import { PresenceEvidenceQueue } from './PresenceEvidenceQueue'
import { PresenceRequirements } from './PresenceRequirements'
import { CollectionConditions, type ConditionRevision } from './CollectionConditions'
import { ConditionCollectionReport } from './ConditionCollectionReport'
import { CollectionProgress } from './CollectionProgress'
import { CollectionQueryStats } from './CollectionQueryStats'
import { CollectionDiscovery } from './CollectionDiscovery'
import { Field } from './forms'
import { prefectures } from './prefectures'
import { RegionSelector } from './RegionSelector'
import { SourceExclusions } from './SourceExclusions'
import type { AiReviewAnalytics, CollectionJob, CollectionPerformance, CollectionSource, Company, CompanyPage, CsvPreview, OperationJob, Profile, Project, SearchAnalytics, SearchSchedule } from './types'

const sourceNames: Record<CollectionSource, string> = {
  serper: 'Google検索（Serper）', google_places: 'Google Maps / Places', gbizinfo: 'gBizINFO（法人情報）',
  url: 'URL直接入力', csv: 'CSVインポート',
}
const availableSources = Object.entries(sourceNames).filter(([value]) => value !== 'google_places')
const statusNames = { running: '実行中', completed: '完了', failed: '失敗' }
const operationStatusNames: Record<OperationJob['status'], string> = {
  queued: '待機中', running: '実行中', completed: '完了', failed: '失敗', cancelled: 'キャンセル',
}
const analysisNames = {
  pending: '未解析', running: '解析中', completed: '解析済み', failed: '解析失敗',
  skipped: 'URLなし', duplicate: '重複', excluded: '対象外',
}
const aiNames = {
  pending: 'AI未判定', running: 'AI判定中', completed: 'AI判定済み',
  failed: 'AI判定失敗', skipped: 'AI判定保留',
}
type CompanyAnalysisSummary = { saved: number; webCompleted: number; webPending: number; webFailed: number; aiCompleted: number; aiPending: number }
type FormAnalysisSummary = { counts: Record<string, number>; company_total: number; analyzed_count: number }
type AiTargetSummary = { eligible_count: number; all_count: number }
const emptyAnalysisSummary: CompanyAnalysisSummary = { saved: 0, webCompleted: 0, webPending: 0, webFailed: 0, aiCompleted: 0, aiPending: 0 }
const emptyAiTargetSummary: AiTargetSummary = { eligible_count: 0, all_count: 0 }

export function CollectionPage({ projects, profiles, initialProjectId, onConfigureTarget, onProjectSelected, mode = 'collection' }: {
  mode?: 'collection' | 'analysis'; projects: Project[]; profiles: Profile[]; initialProjectId: string; onConfigureTarget?: () => void; onProjectSelected?: (id: string) => void
}) {
  const [projectId, setProjectId] = useState(initialProjectId || projects[0]?.id || '')
  const [source, setSource] = useState<CollectionSource>('serper')
  const [collectionMethod, setCollectionMethod] = useState<'company_first' | 'form_first'>(
    'company_first',
  )
  const [formFirstQueryTypes, setFormFirstQueryTypes] = useState([
    'intitle_contact', 'inurl_contact', 'inurl_inquiry', 'form_words',
  ])
  const [formFirstIndustry, setFormFirstIndustry] = useState<'general' | 'restaurant'>('general')
  const [requireCorporateNumber, setRequireCorporateNumber] = useState(false)
  const [presencePlan, setPresencePlan] = useState(defaultPresencePlan)
  const [confirmedConditions, setConfirmedConditions] = useState<ConditionRevision | null>(null)
  const [useConditions, setUseConditions] = useState(false)
  const [conditionsDirty, setConditionsDirty] = useState(false)
  const [keywords, setKeywords] = useState('')
  const [region, setRegion] = useState('全国')
  const [maxResults, setMaxResults] = useState(20)
  const [targetCount, setTargetCount] = useState(100)
  const [searchRequestLimit, setSearchRequestLimit] = useState(5000)
  const [autoContinue, setAutoContinue] = useState(true)
  const [file, setFile] = useState<File | null>(null)
  const [csvPreview, setCsvPreview] = useState<CsvPreview | null>(null)
  const [csvMapping, setCsvMapping] = useState<Record<string, string>>({})
  const [recordType, setRecordType] = useState('company')
  const [jobs, setJobs] = useState<CollectionJob[]>([])
  const [companies, setCompanies] = useState<Company[]>([])
  const [analysisSummary, setAnalysisSummary] = useState(emptyAnalysisSummary)
  const [formAnalysisSummary, setFormAnalysisSummary] = useState<FormAnalysisSummary | null>(null)
  const [aiTargetSummary, setAiTargetSummary] = useState(emptyAiTargetSummary)
  const [aiTargetScope, setAiTargetScope] = useState<'eligible' | 'all'>('eligible')
  const [analysisTotal, setAnalysisTotal] = useState(0)
  const [dataLoading, setDataLoading] = useState(true)
  const [analysisPage, setAnalysisPage] = useState(0)
  const [operations, setOperations] = useState<OperationJob[]>([])
  const [schedules, setSchedules] = useState<SearchSchedule[]>([])
  const [analytics, setAnalytics] = useState<SearchAnalytics[]>([])
  const [performance, setPerformance] = useState<CollectionPerformance[]>([])
  const [reviewAnalytics, setReviewAnalytics] = useState<AiReviewAnalytics[]>([])
  const [scheduleName, setScheduleName] = useState('定期検索')
  const [intervalHours, setIntervalHours] = useState(168)
  const [companyLimit, setCompanyLimit] = useState(10000)
  const [loading, setLoading] = useState(false)
  const [continuingJobId, setContinuingJobId] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [aiAnalyzing, setAiAnalyzing] = useState(false)
  const [formAnalyzing, setFormAnalyzing] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const progressPanel = useRef<HTMLDivElement>(null)
  const hadActiveOperations = useRef(false)
  const busyMessage = loading ? '収集を受け付けています…' : analyzing ? 'サイト解析を受け付けています…' : aiAnalyzing ? 'AI判定を受け付けています…' : ''
  const visibleOperations = operations.filter(job => mode === 'analysis' ? ['web_analysis', 'site_analysis', 'ai_analysis', 'form_intelligence'].includes(job.operation_type) : ['collect_search', 'extract_articles'].includes(job.operation_type))
  const collectionRunning = operations.some(job => job.operation_type === 'collect_search' && ['queued', 'running'].includes(job.status))
  const resumableJob = !collectionRunning ? visibleOperations.find(job => job.operation_type === 'collect_search'
    && job.status === 'completed' && job.collection_progress?.stop_reason === 'REQUEST_BUDGET_REACHED'
    && !!job.collection_progress.pending_queries) : undefined
  const webJob = operations.find(job => job.project_id === projectId && ['web_analysis', 'site_analysis'].includes(job.operation_type) && ['queued', 'running'].includes(job.status))
  const aiJob = operations.find(job => job.project_id === projectId && job.operation_type === 'ai_analysis' && ['queued', 'running'].includes(job.status))
  const formJob = operations.find(job => job.project_id === projectId && ['site_analysis', 'form_intelligence'].includes(job.operation_type) && ['queued', 'running'].includes(job.status))
  const webBusy = analyzing || !!webJob
  const aiBusy = aiAnalyzing || !!aiJob
  const formBusy = formAnalyzing || !!formJob
  const project = projects.find(item => item.id === projectId)
  const formFirstMode = source === 'serper' && collectionMethod === 'form_first'
  const profile = profiles.find(item => item.id === project?.target_profile_id)
  const projectRegion = project?.region
  const analysisCounts = analysisSummary
  const selectedAiTargetCount = aiTargetScope === 'all' ? aiTargetSummary.all_count : aiTargetSummary.eligible_count
  const suggestedKeywords = useMemo(() => profile?.search_keywords ?? [], [profile])
  const suggestedKeywordText = suggestedKeywords.join('\n')

  const reload = useCallback(async (progressOnly = false) => {
    if (!projectId) { setJobs([]); setCompanies([]); setAnalysisSummary(emptyAnalysisSummary); setAiTargetSummary(emptyAiTargetSummary); setAnalysisTotal(0); setOperations([]); setSchedules([]); setAnalytics([]); setPerformance([]); setReviewAnalytics([]); setDataLoading(false); return }
    if (!progressOnly && mode === 'analysis') setDataLoading(true)
    const coreLoads: Promise<unknown>[] = [
      api<OperationJob[]>(`/projects/${projectId}/operations?limit=20`).then(next => {
        setOperations(next.filter(job => job.operation_type !== 'prepare_outreach'))
      }),
    ]
    if (mode === 'analysis' || mode === 'collection') {
      coreLoads.push(api<CompanyAnalysisSummary>(`/projects/${projectId}/company-analysis-summary`).then(setAnalysisSummary))
    }
    if (mode === 'analysis' && !progressOnly) {
      coreLoads.push(api<CompanyPage>(`/projects/${projectId}/company-list?offset=${analysisPage * 20}&limit=20`).then(nextPage => {
        setCompanies(nextPage.items); setAnalysisTotal(nextPage.total)
      }))
      coreLoads.push(api<FormAnalysisSummary>(`/projects/${projectId}/form-readiness?category=all&limit=1&offset=0`).then(setFormAnalysisSummary))
      coreLoads.push(api<AiTargetSummary>(`/projects/${projectId}/ai-analysis/targets`).then(setAiTargetSummary))
    }
    if (mode === 'collection' && !progressOnly) {
      // The screen shows recent jobs only. Loading every historical job/company
      // before rendering progress can turn one refresh into hundreds of requests.
      coreLoads.push(api<CollectionJob[]>(`/projects/${projectId}/collection-jobs?offset=0&limit=50`).then(setJobs))
    }
    const coreResults = await Promise.allSettled(coreLoads)
    const coreFailure = coreResults.find((result): result is PromiseRejectedResult => result.status === 'rejected')
    if (mode === 'analysis') {
      if (coreFailure) throw coreFailure.reason
      setDataLoading(false)
      return
    }
    if (progressOnly) {
      if (coreFailure) throw coreFailure.reason
      return
    }

    const serviceLoads = [
      api<SearchSchedule[]>(`/projects/${projectId}/search-schedules`).then(setSchedules),
      api<SearchAnalytics[]>(`/projects/${projectId}/search-analytics`).then(setAnalytics),
      api<CollectionPerformance[]>(`/projects/${projectId}/collection-performance`).then(setPerformance),
      api<AiReviewAnalytics[]>(`/projects/${projectId}/ai-review-analytics`).then(setReviewAnalytics),
    ]
    const serviceResults = await Promise.allSettled(serviceLoads)
    const serviceFailure = serviceResults.find((result): result is PromiseRejectedResult => result.status === 'rejected')
    if (coreFailure) throw coreFailure.reason
    if (serviceFailure) throw serviceFailure.reason
  }, [projectId, mode, analysisPage])

  useEffect(() => { setAnalysisPage(0); setAiTargetScope('eligible') }, [projectId])
  useEffect(() => { reload().catch(e => { setDataLoading(false); setError(errorMessage(e)) }) }, [reload])
  useEffect(() => {
    if (!operations.some(job => ['queued', 'running'].includes(job.status))) return
    const timer = window.setInterval(() => void reload(true).catch(e => setError(errorMessage(e))), 5000)
    return () => window.clearInterval(timer)
  }, [operations, reload])
  useEffect(() => {
    const active = operations.some(job => ['queued', 'running'].includes(job.status))
    if (hadActiveOperations.current && !active) void reload().catch(e => setError(errorMessage(e)))
    hadActiveOperations.current = active
  }, [operations, reload])
  useEffect(() => {
    if (projectRegion) setRegion(projectRegion)
    if (suggestedKeywordText) setKeywords(suggestedKeywordText)
  }, [projectId, projectRegion, suggestedKeywordText])

  async function refresh() {
    if (refreshing) return
    setRefreshing(true); setError(''); setNotice('')
    try { await reload(); setNotice('最新の収集・解析状況に更新しました。') }
    catch (e) { setError(errorMessage(e)) }
    finally { setRefreshing(false) }
  }

  async function continueCollection(jobId: string) {
    setContinuingJobId(jobId); setError(''); setNotice('')
    try {
      await api(`/operations/${jobId}/continue`, 'POST')
      await reload()
      setNotice('続きの収集を登録しました。バックグラウンド処理で進捗を確認できます。')
      window.setTimeout(() => {
        progressPanel.current?.scrollIntoView({ block: 'start', behavior: 'smooth' })
        progressPanel.current?.focus({ preventScroll: true })
      }, 0)
    } catch (e) { setError(errorMessage(e)) }
    finally { setContinuingJobId('') }
  }

  async function submit(event: FormEvent) {
    event.preventDefault(); setError(''); setNotice('')
    const formFirst = formFirstMode
    if (formFirst && formFirstQueryTypes.length === 0) {
      setError('検索型を1つ以上選択してください。')
      return
    }
    if (conditionsDirty && source !== 'csv' && source !== 'url' && !formFirst) {
      setError('対象条件の変更を確定するか、未確定の変更を取り消してください。')
      return
    }
    setLoading(true)
    try {
      if (!projectId) throw new Error('プロジェクトを選択してください。')
      let result: CollectionJob[]
      if (source === 'csv') {
        if (!file) { setError('CSVファイルを選択してください。'); return }
        const form = new FormData(); form.append('file', file)
        form.append('record_type', recordType)
        if (csvPreview) form.append('column_mapping', JSON.stringify(Object.fromEntries(Object.entries(csvMapping).filter(([, value]) => value))))
        result = [await upload<CollectionJob>(`/projects/${projectId}/collection-jobs/csv`, form)]
      } else if (source === 'url') {
        const urls = keywords.split('\n').map(value => value.trim()).filter(Boolean)
        result = [await api<CollectionJob>(`/projects/${projectId}/collection-jobs/urls`, 'POST', { urls })]
      } else {
        const values = keywords.split('\n').map(value => value.trim()).filter(Boolean)
        if (useConditions && confirmedConditions?.project_id !== projectId) throw new Error('対象条件を先に確定してください。')
        await api<OperationJob>(`/projects/${projectId}/operations`, 'POST', {
          operation_type: 'collect_search', source, keywords: values, region, max_results: maxResults,
          ...(source === 'serper' ? { region_mode: 'prefecture_order' } : {}),
          ...(!formFirst ? { presence_search: presencePlan } : {}),
          ...(source === 'serper' ? {
            target_count: targetCount,
            collection_method: collectionMethod,
            ...(formFirst
              ? { form_first_query_types: formFirstQueryTypes, form_first_industry: formFirstIndustry, require_corporate_number: requireCorporateNumber, auto_continue: false }
              : { search_request_limit: searchRequestLimit, auto_continue: autoContinue }),
          } : {}),
          ...(useConditions && confirmedConditions && !formFirst ? { condition_request_id: confirmedConditions.id, condition_version: confirmedConditions.version, condition_hash: confirmedConditions.payload_hash } : {}),
        })
        await reload()
        setNotice('検索収集をバックグラウンド処理へ登録しました。')
        return
      }
      await reload()
      setNotice(result.some(job => job.status === 'failed')
        ? '収集処理を終了しました。失敗したジョブの内容を確認してください。'
        : '収集処理が完了しました。結果を確認してください。')
    } catch (e) { setError(errorMessage(e)) }
    finally { setLoading(false) }
  }

  async function selectCsv(nextFile: File | null) {
    setFile(nextFile); setCsvPreview(null); setCsvMapping({}); setError('')
    if (!nextFile || !projectId) return
    try {
      const form = new FormData(); form.append('file', nextFile)
      const preview = await upload<CsvPreview>(`/projects/${projectId}/collection-jobs/csv/preview`, form)
      setCsvPreview(preview); setCsvMapping(preview.suggested_mapping)
    } catch (e) { setError(errorMessage(e)) }
  }

  async function analyze(companyIds: string[] = []) {
    if (webBusy) return
    setAnalyzing(true); setError(''); setNotice('')
    try {
      if (!companyIds.length) {
        await api<OperationJob>(`/projects/${projectId}/operations`, 'POST', {
          operation_type: 'site_analysis', company_ids: [], force: false,
        })
        await reload(); setNotice('Web解析をバックグラウンド処理へ登録しました。'); return
      }
      const job = await api<OperationJob>(`/projects/${projectId}/web-analysis`, 'POST', {
        company_ids: companyIds, limit: companyIds.length, force: false,
      })
      await reload()
      setNotice(`${companyIds.length}社のサイト解析を登録しました（ジョブ ${job.id.slice(0, 8)}）。`)
    } catch (e) { setError(errorMessage(e)) }
    finally { setAnalyzing(false) }
  }

  async function analyzeAi(companyIds: string[] = []) {
    if (aiBusy) return
    setAiAnalyzing(true); setError(''); setNotice('')
    try {
      if (!companyIds.length) {
        await api<OperationJob>(`/projects/${projectId}/operations`, 'POST', {
          operation_type: 'ai_analysis', company_ids: [], force: false, ai_target_scope: aiTargetScope,
        })
        await reload(); setNotice(`${selectedAiTargetCount}社のAI判定をバックグラウンド処理へ登録しました。`); return
      }
      const results = await api<Company[]>(`/projects/${projectId}/ai-analysis`, 'POST', {
        company_ids: companyIds, limit: companyIds.length, force: false,
      })
      await reload()
      setNotice(results.length
        ? `${results.length}社のAI判定を完了しました。`
        : 'AI判定対象の企業はありません。')
    } catch (e) { setError(errorMessage(e)) }
    finally { setAiAnalyzing(false) }
  }

  async function analyzeForms() {
    setFormAnalyzing(true); setError(''); setNotice('')
    try {
      await api<OperationJob>(`/projects/${projectId}/operations`, 'POST', {
        operation_type: 'site_analysis', company_ids: [], force: false,
      })
      await reload()
      setNotice('未解析の企業を、サイト解析ジョブに登録しました。')
    } catch (e) { setError(errorMessage(e)) }
    finally { setFormAnalyzing(false) }
  }

  async function createSchedule() {
    setError(''); setNotice('')
    try {
      if (!['serper', 'google_places', 'gbizinfo'].includes(source)) throw new Error('検索収集の条件を選択してください。')
      await api(`/projects/${projectId}/search-schedules`, 'POST', {
        name: scheduleName, source,
        keywords: keywords.split('\n').map(value => value.trim()).filter(Boolean),
        region, max_results: maxResults, interval_hours: intervalHours,
        company_limit: companyLimit, active: true,
      })
      await reload(); setNotice('定期収集を保存しました。')
    } catch (e) { setError(errorMessage(e)) }
  }

  if (projects.length === 0) return <section className="panel empty">
    <h2>先にプロジェクトを作成してください</h2>
    <p className="muted">企業は営業プロジェクトごとに収集・保存されます。</p>{onConfigureTarget && <button className="mt-4" onClick={onConfigureTarget}>収集ターゲットを設定</button>}
  </section>

  const progress = <div className="panel scroll-mt-24" ref={progressPanel} tabIndex={-1}><div className="flex items-center justify-between gap-4"><h2>バックグラウンド処理</h2>
        <button type="button" className="secondary" disabled={refreshing} aria-busy={refreshing} onClick={() => void refresh()}>{refreshing ? '更新中…' : '更新'}</button></div>
        {visibleOperations.length === 0 ? <p className="muted mt-4">処理履歴はまだありません。</p> : visibleOperations.map(job =>
            <article className="job-row block" key={job.id}><div className="flex justify-between gap-3"><strong>{job.operation_type === 'prepare_outreach' ? '営業準備' : ['web_analysis', 'site_analysis'].includes(job.operation_type) ? 'サイト解析' : job.operation_type === 'ai_analysis' ? 'AI判定' : job.operation_type === 'form_intelligence' ? 'フォーム解析' : job.operation_type === 'extract_articles' ? '記事から企業を抽出' : '検索収集'}</strong><span className="badge">{operationStatusNames[job.status]}</span></div>
            {job.operation_type === 'extract_articles' ? <p className="muted my-2 text-sm">記事 {job.processed_count} / {job.total_count} 件（新規保存 {job.article_saved_count ?? 0} 社・失敗 {job.failed_count} 件）</p> : job.collection_progress ? <CollectionProgress progress={job.collection_progress} /> : <p className="muted my-2 text-sm">{job.processed_count} / {job.total_count} 件（成功 {job.success_count}・失敗 {job.failed_count}・試行 {job.attempt_count}）</p>}
            {job.operation_type === 'collect_search' && job.collection_progress && <CollectionQueryStats jobId={job.id} />}
            {job.error_message && <p className="error mb-0">{job.error_message}</p>}
            {job.condition_request_id && <ConditionCollectionReport jobId={job.id} status={job.status} />}
            {['queued', 'running'].includes(job.status) && <button type="button" className="danger" onClick={() => void api(`/operations/${job.id}/cancel`, 'POST').then(() => reload()).catch(e => setError(errorMessage(e)))}>キャンセル</button>}
            {job.operation_type === 'collect_search' && job.status === 'completed' && job.collection_progress?.stop_reason === 'REQUEST_BUDGET_REACHED' && !!job.collection_progress.pending_queries && <button type="button" className="secondary" disabled={!!continuingJobId} onClick={() => void continueCollection(job.id)}>{continuingJobId === job.id ? '登録中…' : '続きから収集'}</button>}
            {job.operation_type !== 'prepare_outreach' && ['failed', 'cancelled'].includes(job.status) && <button type="button" className="secondary" onClick={() => void api(`/operations/${job.id}/retry`, 'POST').then(() => reload()).catch(e => setError(errorMessage(e)))}>再実行</button>}
          </article>)}
      </div>

  return <div className={mode === 'analysis' ? 'min-w-0 space-y-6' : 'grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(360px,.95fr)]'}>
    {(error || busyMessage || notice) && <aside aria-label="操作結果" className="xl:col-span-2 fixed inset-x-4 bottom-[max(1rem,env(safe-area-inset-bottom))] z-50 max-h-[40dvh] overflow-y-auto rounded-xl border border-slate-300 bg-white p-4 shadow-xl sm:static sm:mb-4 sm:max-h-none sm:shadow-none">
        <p className={error ? 'error m-0' : 'm-0'} role={error ? 'alert' : 'status'}>{error || busyMessage || notice}</p>
        {!busyMessage && <div className="mt-3 flex flex-wrap gap-2">
          {!error && notice.includes('バックグラウンド') && <button type="button" onClick={() => {
            setNotice('')
            progressPanel.current?.scrollIntoView({ block: 'start' })
            progressPanel.current?.focus({ preventScroll: true })
          }}>進捗を見る</button>}
          <button type="button" className="secondary" onClick={() => { setError(''); setNotice('') }}>通知を閉じる</button>
        </div>}
      </aside>}
    {mode === 'analysis' && <section className="panel" role="region" aria-label="解析開始"><h2>収集済みリストを後から解析</h2><p className="muted mt-2">新しく収集せず、保存済み企業のWeb情報取得・AI判定・フォーム解析を行います。解析だけでは送信されません。</p><Field label="解析する収集リスト"><select value={projectId} onChange={e => { setProjectId(e.target.value); onProjectSelected?.(e.target.value) }}>{projects.map(item => <option key={item.id} value={item.id}>{item.project_name} / {item.region}</option>)}</select></Field>
      {dataLoading ? <p className="muted mt-4" role="status">保存済み企業と解析状況を読み込んでいます…</p> : <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-8" aria-label="解析状況">
        {([['保存済み', analysisCounts.saved], ['Web解析済み', analysisCounts.webCompleted], ['Web未解析', analysisCounts.webPending], ['Web解析失敗', analysisCounts.webFailed], ['AI判定済み', analysisCounts.aiCompleted], ['AI未判定', analysisCounts.aiPending], ['フォーム解析済み', formAnalysisSummary?.analyzed_count ?? 0], ['フォーム未解析', formAnalysisSummary?.counts.unanalyzed ?? 0]] as const).map(([label, count]) => <div className="metric" key={label}><span>{label}</span><strong>{count}社</strong></div>)}
      </div>}
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <button type="button" className={webBusy ? 'analysis-active' : undefined} aria-busy={webBusy} disabled={dataLoading || webBusy || analysisCounts.webPending + analysisCounts.webFailed === 0}
            onClick={() => void analyze()}>{webBusy ? (webJob?.status === 'queued' ? 'サイト解析 待機中…' : 'サイト解析中…') : 'サイト解析を開始'}</button>
          <button type="button" className={aiBusy ? 'analysis-active' : undefined} aria-busy={aiBusy} disabled={dataLoading || aiBusy || selectedAiTargetCount === 0}
            onClick={() => void analyzeAi()}>{aiBusy ? (aiJob?.status === 'queued' ? 'AI判定 待機中…' : 'AI判定中…') : 'AI判定を開始'}</button>
          <button type="button" className={formBusy ? 'analysis-active' : undefined} aria-busy={formBusy}
            disabled={dataLoading || formBusy || analysisCounts.webCompleted === 0 || (formAnalysisSummary?.counts.unanalyzed ?? 0) === 0}
            onClick={() => void analyzeForms()}>{formBusy ? (formJob?.status === 'queued' ? 'サイト解析 待機中…' : 'サイト解析中…') : 'フォームを含むサイト解析'}</button>
      </div>
      <div className="mt-4 rounded border p-3" aria-label="AI判定対象">
        <p className="m-0"><strong>AI判定対象：{selectedAiTargetCount}社</strong>（API利用見込み：最大{selectedAiTargetCount}回）</p>
        <p className="muted mb-0 mt-2 text-sm">既定では送信可能・フォーム確認待ち、またはメールアドレスがあり連絡禁止でない企業だけを判定します。</p>
        <details className="mt-2">
          <summary>詳細設定</summary>
          <label className="mt-2 flex items-center gap-2">
            <input type="checkbox" checked={aiTargetScope === 'all'} onChange={event => setAiTargetScope(event.target.checked ? 'all' : 'eligible')} />
            Web解析済みの未判定企業をすべて対象にする（{aiTargetSummary.all_count}社）
          </label>
        </details>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-3" aria-label="各解析の目的">
        <article className="rounded border p-3"><strong>1. Web解析</strong><p className="muted mb-0 mt-2 text-sm">公式サイトから事業内容・連絡先を取得します。AI判定とフォーム解析の基礎情報になります。</p></article>
        <article className="rounded border p-3"><strong>2. AI判定</strong><p className="muted mb-0 mt-2 text-sm">取得した情報を営業目的と照らし、対象としての優先度と判定理由を整理します。先にWeb解析を行ってください。</p></article>
        <article className="rounded border p-3"><strong>3. フォーム解析</strong><p className="muted mb-0 mt-2 text-sm">Web解析済み企業の問い合わせ先・入力項目・営業禁止表示・CAPTCHAを確認し、送信準備に使います。送信操作は行いません。</p></article>
      </div>
      <p className="muted mt-3">各処理は100社ずつバックグラウンドで続き、画面を閉じても継続します。失敗した企業は完了後に再実行できます。AI判定にはAPI費用が発生します。</p></section>}
    {mode === 'collection' && <section className="min-w-0 space-y-6">
    {resumableJob && <div className="panel border-2 border-amber-300 bg-amber-50" role="region" aria-label="収集の続き"><h2>収集の続きがあります</h2>
      <p className="mt-2">目標 {resumableJob.collection_progress?.collected_count ?? 0} / {resumableJob.collection_progress?.target_count ?? 0} 件。検索上限で一時停止しました。
        {resumableJob.collection_progress?.current_region && ` 次は${resumableJob.collection_progress.current_region}から巡回します。`}</p>
      <button type="button" disabled={!!continuingJobId} onClick={() => void continueCollection(resumableJob.id)}>{continuingJobId === resumableJob.id ? '続きの収集を登録中…' : '続きから収集を再開'}</button>
      <p className="muted mb-0 mt-2 text-sm">自動継続が有効なら、ここでの手動操作は不要です。</p></div>}
    <form className="panel form-panel min-w-0 max-w-none" onSubmit={submit}>
      <h2>収集条件</h2><p className="muted">ターゲットのキーワード・地域を引き継いでいます。件数を確認して収集を開始してください。</p>
      {conditionsDirty && source !== 'csv' && source !== 'url' && <p role="status">対象条件に未確定の変更があります。確定するか、変更を取り消してから収集してください。</p>}
      <fieldset disabled={loading}>
        <Field label="プロジェクト"><select required value={projectId}
          onChange={e => { setProjectId(e.target.value); onProjectSelected?.(e.target.value); setUseConditions(false); setConfirmedConditions(null); setConditionsDirty(false) }}>{projects.map(item =>
          <option key={item.id} value={item.id}>{item.project_name}</option>)}</select></Field>
        <Field label="収集元"><select value={source} onChange={e => {
          const next = e.target.value as CollectionSource; setSource(next); setFile(null)
          setKeywords(next === 'url' ? '' : suggestedKeywordText)
        }}>{availableSources.map(([value, label]) =>
          <option key={value} value={value}>{label}</option>)}</select></Field>
        {source === 'serper' && <Field label="収集方法"><select value={collectionMethod} onChange={event => {
          const method = event.target.value as 'company_first' | 'form_first'
          setCollectionMethod(method)
          if (method === 'form_first') setUseConditions(false)
        }}><option value="company_first">会社起点（従来）</option><option value="form_first">フォーム起点（問い合わせページから探す）</option></select></Field>}
        {source === 'csv' ? <Field label="CSVファイル（UTF-8・最大5MB・1000行）">
          <input type="file" accept=".csv,text/csv" required onChange={e => void selectCsv(e.target.files?.[0] ?? null)} />
        </Field> : <Field label={source === 'url' ? 'URL（1行に1件）' : '検索キーワード（1行に1件）'}>
          <textarea required rows={8} value={keywords} onChange={e => setKeywords(e.target.value)}
            placeholder={source === 'url' ? 'https://example.com' : '検索キーワード'} />
        </Field>}
        {(['serper', 'google_places', 'gbizinfo'].includes(source)) && <div className="grid gap-5 sm:grid-cols-2">
          {source === 'serper' ? <RegionSelector value={region} onChange={setRegion} includeMunicipalities={false} /> : <Field label="都道府県"><select required value={region} onChange={e => setRegion(e.target.value)}>
            <option value="全国">全国</option>
            {prefectures.map(prefecture => <option key={prefecture} value={prefecture}>{prefecture}</option>)}
            {region !== '全国' && !prefectures.some(prefecture => prefecture === region) && <option value={region}>{region}（プロジェクトの地域）</option>}
          </select></Field>}
          {source === 'serper' ? <Field label="収集する新規候補数（目標）"><input type="number" min={1} max={10000} required value={targetCount}
            onChange={e => setTargetCount(Number(e.target.value))} /></Field> : <Field label="キーワードごとの最大件数"><input type="number" min={1}
            max={source === 'google_places' ? 60 : 100} value={maxResults}
            onChange={e => setMaxResults(Number(e.target.value))} /></Field>}
        </div>}
        {source === 'serper' && <>
          {collectionMethod === 'form_first' && <section className="rounded border p-3" aria-label="フォーム起点の検索条件">
            <h3>問い合わせページの検索型</h3>
            <Field label="業種別の除外語"><select value={formFirstIndustry} onChange={event => setFormFirstIndustry(event.target.value as 'general' | 'restaurant')}>
              <option value="general">共通の除外語のみ</option>
              <option value="restaurant">飲食店（グルメサイト・予約語を除外）</option>
            </select></Field>
            <button type="button" className="secondary mt-2" onClick={() => {
              setRegion('名古屋市')
              setKeywords(['居酒屋', 'レストラン', 'カフェ', '焼肉', 'ラーメン', '寿司', '和食', 'イタリアン'].join('\n'))
              setFormFirstIndustry('restaurant')
            }}>名古屋市・飲食店の初回試験条件を入力</button>
            <div className="grid gap-2 sm:grid-cols-2">
              {[
                ['intitle_contact', 'ページタイトルに「お問い合わせ」'],
                ['inurl_contact', 'URLに contact'],
                ['inurl_inquiry', 'URLに inquiry'],
                ['form_words', '「お問い合わせフォーム」'],
              ].map(([value, label]) => <label key={value} className="checkbox-row">
                <input type="checkbox" checked={formFirstQueryTypes.includes(value)} onChange={event => {
                  setFormFirstQueryTypes(current => event.target.checked
                    ? [...current, value] : current.filter(item => item !== value))
                }} />{label}
              </label>)}
            </div>
            {formFirstQueryTypes.length === 0 && <p role="alert" className="error">検索型を1つ以上選択してください。</p>}
            <label className="checkbox-row mt-3"><input type="checkbox" checked={requireCorporateNumber}
              onChange={event => setRequireCorporateNumber(event.target.checked)} />法人番号を確認できた会社だけ登録</label>
            <p className="muted mb-0 text-sm">初回試験は検索20回までです。飲食店は8語から分けて検索し、グルメサイトや予約語を除外します。ページ確認は同一サイト内のGETのみで、フォーム入力・送信はしません。</p>
          </section>}
          <section aria-label="検索の組み合わせ" className="muted text-sm">
          <p>{region === '全国' ? '全国は各キーワードに都道府県名を足して検索します。北海道から沖縄県へ、県内の検索語を巡回して次の県へ進みます。' : `${region}と各キーワードを組み合わせて検索します。`}</p>
            <p>目標件数に届く前に検索候補を調べ終えた場合や、総検索上限に達した場合は停止します。</p>
            <details><summary>検索キーワードと地域の組み合わせを確認</summary><ul>
              {(region === '全国' ? prefectures : region.split(/\s*\/\s*/).every(area => prefectures.some(prefecture => prefecture === area)) ? region.split(/\s*\/\s*/) : [region]).map(area => <li key={area}>{keywords.split('\n').map(value => value.trim()).filter(Boolean).map(keyword => `${keyword} ${area}`).join(' / ') || `キーワード未入力 ${area}`}</li>)}
            </ul></details>
          </section>
          {collectionMethod === 'company_first' && <><label className="checkbox-row"><input type="checkbox" checked={autoContinue} disabled={loading} onChange={event => {
            const enabled = event.target.checked
            setAutoContinue(enabled)
            setSearchRequestLimit(enabled ? 5000 : Math.min(searchRequestLimit, 50))
          }} />目標件数まで50回ごとに自動で続きを実行する（おすすめ）</label>
          <Field label={autoContinue ? '検索の総上限（安全上限）' : '今回の検索回数上限'}><input type="number" min={autoContinue ? 50 : 1} max={autoContinue ? 5000 : 50} required value={searchRequestLimit}
            onChange={event => setSearchRequestLimit(Number(event.target.value))} disabled={loading} /></Field>
          <p className="muted text-sm">目標件数は最大10,000社です。検索1ジョブは最大50回で区切りますが、自動継続をONにすると総上限{searchRequestLimit}回まで次のジョブへ引き継ぎます。重複・対象外は目標件数に含めません。総上限に達した後に「続きから収集を再開」を押すと、追加1,000回を新しい安全上限として自動継続します。検索API費用が発生します。追加調査は別の上限です。</p></>}
        </>}
        {source === 'csv' && <div><Field label="取り込み単位"><select value={recordType} onChange={e => setRecordType(e.target.value)}><option value="company">企業単位（同じドメインは1社）</option><option value="location">店舗単位（同じサイトの別店舗を保持）</option></select></Field><p className="muted text-sm">店舗単位では店名と住所（住所がなければURL）で重複を判定します。予約・ポータルサイトは参考URLとして保存し、公式サイト解析やフォーム送信には使用しません。</p></div>}
        {source === 'csv' && csvPreview && <div className="mt-4"><p className="muted text-sm">{csvPreview.row_count}行を検出しました。取込先ごとにCSV列を指定してください。</p><div className="grid gap-3 mt-3 sm:grid-cols-2">{Object.entries({ company_name: '会社名', website_url: 'WebサイトURL', phone: '電話', email: 'メール', address: '住所', reference_url: '参考URL（任意）' }).map(([field, label]) => <Field key={field} label={label}><select required={field !== 'reference_url'} value={csvMapping[field] ?? ''} onChange={e => setCsvMapping({ ...csvMapping, [field]: e.target.value })}><option value="">列を選択</option>{csvPreview.headers.map(header => <option key={header} value={header}>{header}</option>)}</select></Field>)}</div><div className="overflow-x-auto"><table><thead><tr>{csvPreview.headers.map(header => <th key={header}>{header}</th>)}</tr></thead><tbody>{csvPreview.sample_rows.map((row, index) => <tr key={index}>{csvPreview.headers.map(header => <td key={header}>{row[header]}</td>)}</tr>)}</tbody></table></div></div>}
        {source !== 'csv' && source !== 'url' && !formFirstMode && <PresenceSearchControls value={presencePlan} onChange={setPresencePlan} />}
        {source !== 'csv' && source !== 'url' && !formFirstMode && <label><input type="checkbox" checked={useConditions} disabled={confirmedConditions?.project_id !== projectId} onChange={e => setUseConditions(e.target.checked)} />確定条件を今回の収集に使う{confirmedConditions?.project_id === projectId ? `（第${confirmedConditions.version}版）` : '（先に条件を確定してください）'}<span className="muted block">必須・除外の媒体は追加調査OFFでも、上限内で確認します。未対応・上限不足は確認待ちです。</span></label>}
        <div className="actions"><button type="submit">{loading ? (['serper', 'google_places', 'gbizinfo'].includes(source) ? '登録中…' : '収集中…') : '収集を開始'}</button></div>
      </fieldset>
    </form>
    <SourceExclusions key={`sources-${projectId}`} projectId={projectId} />
    <CollectionConditions key={`conditions-${projectId}`} projectId={projectId} onConfirmed={setConfirmedConditions} onDraftChanged={setConditionsDirty} onApplied={row => {
      setConfirmedConditions(row)
      if (source === 'csv' || source === 'url') return
      setUseConditions(true)
      if (source === 'serper' && row.snapshot.requested_count_explicit && row.snapshot.requested_count) setTargetCount(row.snapshot.requested_count)
      const areas = row.snapshot.conditions.filter(c => c.type === 'AREA' && c.priority === 'MUST')
      const industries = row.snapshot.conditions.filter(c => c.type === 'INDUSTRY' && c.priority === 'MUST')
      if (areas.length === 1) setRegion(areas[0].value)
      if (industries.length === 1) setKeywords(industries[0].value)
    }} />
    <PresenceEvidenceQueue key={`presence-${projectId}`} projectId={projectId} />

    <div className="panel"><h2>定期収集テンプレート</h2><p className="muted mt-2 text-sm">現在の検索条件を保存し、ワーカーで定期実行します。</p>
      <Field label="テンプレート名"><input maxLength={200} value={scheduleName} onChange={e => setScheduleName(e.target.value)} /></Field>
      <div className="grid gap-4 sm:grid-cols-2"><Field label="実行間隔（時間）"><input type="number" min={1} max={720} value={intervalHours} onChange={e => setIntervalHours(Number(e.target.value))} /></Field>
        <Field label="プロジェクト企業上限"><input type="number" min={1} max={100000} value={companyLimit} onChange={e => setCompanyLimit(Number(e.target.value))} /></Field></div>
      <button type="button" disabled={!['serper', 'google_places', 'gbizinfo'].includes(source)} onClick={() => void createSchedule()}>現在の検索条件を保存</button>
      {schedules.map(schedule => <article className="job-row block" key={schedule.id}><div className="flex justify-between gap-3"><strong>{schedule.name}</strong><span className="badge">{schedule.active ? '有効' : '停止中'}</span></div>
        <p className="muted my-2 text-sm">{schedule.keywords.join(' / ')}・{schedule.interval_hours}時間ごと・上限{schedule.company_limit}社</p>
        <p className="muted text-sm">次回 {new Date(schedule.next_run_at).toLocaleString('ja-JP')}</p>{schedule.last_error && <p className="error mt-2 mb-0">{schedule.last_error}</p>}
        {schedule.source === 'google_places' ? <p className="muted mt-2 text-sm">Google Maps / Placesの新規収集停止に伴い、このテンプレートは再実行できません。過去の実績は保持されます。</p> : <div className="mt-3 flex flex-wrap gap-2"><button type="button" className="secondary" onClick={() => void api(`/search-schedules/${schedule.id}/run`, 'POST').then(() => reload()).catch(e => setError(errorMessage(e)))}>今すぐ実行</button>
          <button type="button" className="secondary" onClick={() => void api(`/search-schedules/${schedule.id}`, 'PUT', {
            name: schedule.name, source: schedule.source, keywords: schedule.keywords,
            region: schedule.region, max_results: schedule.max_results,
            interval_hours: schedule.interval_hours, company_limit: schedule.company_limit,
            active: !schedule.active,
          }).then(() => reload()).catch(e => setError(errorMessage(e)))}>{schedule.active ? '停止' : '再開'}</button></div>}
          <button type="button" className="danger mt-3" onClick={() => void api(`/search-schedules/${schedule.id}`, 'DELETE').then(() => reload()).catch(e => setError(errorMessage(e)))}>削除</button>
      </article>)}
      {analytics.length > 0 && <div className="mt-6 overflow-x-auto"><h3 className="mb-3">テンプレート別成果</h3><table><thead><tr><th>テンプレート</th><th>検索数</th><th>発見</th><th>保存</th><th>保存率</th><th>重複率</th><th>公式外</th><th>エラー</th></tr></thead>
        <tbody>{analytics.map(item => <tr key={item.schedule_id}><td>{item.name}</td><td>{item.run_count}</td><td>{item.found_count}</td><td>{item.saved_count}</td><td>{item.save_rate}%</td><td>{item.duplicate_rate}%</td><td>{item.excluded_count}</td><td>{item.error_count}</td></tr>)}</tbody></table></div>}
      {reviewAnalytics.length > 0 && <div className="mt-6 overflow-x-auto"><h3 className="mb-2">AI判定レビュー精度</h3><p className="muted mb-3 text-sm">人手レビューを検索語ごとに集計しています。精度が低い検索語はターゲット条件の見直し候補です。</p><table><thead><tr><th>検索語</th><th>レビュー数</th><th>正しい</th><th>精度</th></tr></thead><tbody>{reviewAnalytics.map(item => <tr key={item.source_keyword}><td>{item.source_keyword}</td><td>{item.reviewed_count}</td><td>{item.correct_count}</td><td>{item.accuracy_rate}%</td></tr>)}</tbody></table></div>}
      {performance.length > 0 && <div className="mt-6 overflow-x-auto"><h3 className="mb-2">収集精度・速度の実績</h3><p className="muted mb-3 text-sm">保存率が低い検索語、公式外が多い検索語、時間がかかる収集元を比較して、検索条件を見直せます。</p><table><thead><tr><th>収集元</th><th>検索語</th><th>実行</th><th>発見</th><th>保存</th><th>保存率</th><th>公式外率</th><th>重複</th><th>エラー</th><th>平均時間</th></tr></thead>
        <tbody>{performance.map(item => <tr key={`${item.source}:${item.keyword}`}><td>{sourceNames[item.source]}</td><td>{item.keyword || '検索語なし'}</td><td>{item.run_count}</td><td>{item.found_count}</td><td>{item.saved_count}</td><td>{item.save_rate}%</td><td>{item.excluded_rate}%</td><td>{item.duplicate_count}</td><td>{item.error_count}</td><td>{(item.average_processing_ms / 1000).toFixed(1)}秒</td></tr>)}</tbody></table></div>}
    </div></section>}
    <section className="space-y-6">
      {mode === 'analysis' && progress}
      {mode === 'analysis' && <div className="panel"><div className="flex flex-wrap items-center justify-between gap-4"><div><h2>保存済み企業</h2>
        <p className="muted mt-2 text-sm">Webサイトから企業情報・SNS・問い合わせ先を抽出します。</p></div>
        </div>
        {companies.map(company => <article key={company.id} className="job-row">
          <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><strong>{company.company_name}</strong>
            <span className="badge">{analysisNames[company.analysis_status]}</span>
            <span className="badge">{aiNames[company.ai_status]}</span>
            {company.rank && <span className="badge">{company.rank} / {company.score}点</span>}</div>
            <p className="muted text-sm break-all">{company.domain || company.address || 'URL未登録'}</p>
            {company.business_summary && <p className="mt-2 text-sm">{company.business_summary}</p>}
            {company.analysis_error && <p className="error mt-2 mb-0">{company.analysis_error}</p>}
            {company.ai_summary && <p className="mt-2 text-sm"><strong>{company.business_type}</strong> — {company.ai_summary}</p>}
            {company.ai_reason && <p className="muted mt-1 text-sm">判定理由：{company.ai_reason}</p>}
            {company.ai_recommended_approach && <p className="mt-1 text-sm">推奨：{company.ai_recommended_approach}</p>}
            {company.ai_error && <p className="error mt-2 mb-0">{company.ai_error}</p>}
            <div className="mt-2 flex flex-wrap gap-3 text-sm">{company.contact_url && <a href={company.contact_url} target="_blank" rel="noreferrer">問い合わせ</a>}
              {company.instagram_url && <a href={company.instagram_url} target="_blank" rel="noreferrer">Instagram</a>}
              {company.x_url && <a href={company.x_url} target="_blank" rel="noreferrer">X</a>}
              {company.line_url && <a href={company.line_url} target="_blank" rel="noreferrer">LINE</a>}</div>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-2"><span className="badge">{sourceNames[company.source]}</span>
            {company.website_url && !['duplicate', 'excluded'].includes(company.analysis_status) &&
              <button type="button" className={webBusy ? 'secondary analysis-active' : 'secondary'} aria-busy={webBusy} disabled={webBusy}
                onClick={() => void analyze([company.id])}>{webBusy ? 'サイト解析 処理中…' : 'サイト解析'}</button>}
            {company.analysis_status === 'completed' && <button type="button" className={aiBusy ? 'secondary analysis-active' : 'secondary'} aria-busy={aiBusy}
              disabled={aiBusy} onClick={() => void analyzeAi([company.id])}>{aiBusy ? 'AI判定 処理中…' : 'AI判定'}</button>}</div>
        </article>)}
        {analysisTotal > 20 && <div className="actions"><button className="secondary" disabled={analysisPage === 0} onClick={() => setAnalysisPage(p => p - 1)}>前の20社</button><span>{analysisPage + 1} / {Math.ceil(analysisTotal / 20)}</span><button className="secondary" disabled={(analysisPage + 1) * 20 >= analysisTotal} onClick={() => setAnalysisPage(p => p + 1)}>次の20社</button></div>}
      </div>}
      {mode === 'collection' && <div className="panel"><div className="flex items-center justify-between gap-4"><h2>最近の収集ジョブ</h2>
        <button type="button" className="secondary" disabled={refreshing} aria-busy={refreshing} onClick={() => void refresh()}>{refreshing ? '更新中…' : '更新'}</button></div>
        {jobs.length === 0 ? <p className="muted mt-4">収集履歴はまだありません。</p> : jobs.slice(0, 10).map(job =>
          <article className="job-row block" key={job.id}>
            <div className="flex justify-between gap-3"><strong>{sourceNames[job.source]}</strong>
              <span className="badge">{statusNames[job.status]}</span></div>
            {(job.keyword || job.region) && <p className="muted my-2 text-sm">{[job.keyword, job.region].filter(Boolean).join(' / ')}</p>}
            <PresenceRequirements key={`${job.id}-${job.status}-${operations.map(o => o.status).join()}-${companies.length}`} jobId={job.id} /><div className="job-stats"><span>発見 {job.found_count}</span><span>保存 {job.saved_count}</span>
              <span>重複 {job.duplicate_count}</span><span>公式外 {job.excluded_count}</span><span>エラー {job.error_count}</span><span>{job.processing_ms}ms</span></div>
            {job.source === 'serper' && <CollectionDiscovery key={`${job.id}-${job.status}`} jobId={job.id} projectId={projectId}
              sourceOperationId={job.operation_job_id ?? undefined}
              extractionJob={operations.find(operation => operation.operation_type === 'extract_articles' && operation.source_operation_ids?.includes(job.operation_job_id ?? ''))}
              onStarted={() => { void reload(true).catch(e => setError(errorMessage(e))) }} />}
            {job.error_message && <p className="error mt-3 mb-0">{job.error_message}</p>}
            {job.source === 'csv' && job.error_count > 0 && <button type="button" className="secondary mt-3" onClick={() => void download(`/collection-jobs/${job.id}/errors.csv`, 'csv-import-errors.csv').catch(e => setError(errorMessage(e)))}>行別エラーをダウンロード</button>}
          </article>)}
      </div>}
      {mode === 'collection' && progress}
    </section>
  </div>
}
