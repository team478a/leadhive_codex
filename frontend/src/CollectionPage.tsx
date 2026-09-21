import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { allPages, api, download, errorMessage, upload } from './api'
import { Field } from './forms'
import type { AiReviewAnalytics, CollectionJob, CollectionPerformance, CollectionSource, Company, CsvPreview, OperationJob, Profile, Project, SearchAnalytics, SearchSchedule } from './types'

const sourceNames: Record<CollectionSource, string> = {
  serper: 'Google検索（Serper）', google_places: 'Google Maps / Places', gbizinfo: 'gBizINFO（法人情報）',
  url: 'URL直接入力', csv: 'CSVインポート',
}
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

export function CollectionPage({ projects, profiles, initialProjectId }: {
  projects: Project[]; profiles: Profile[]; initialProjectId: string
}) {
  const [projectId, setProjectId] = useState(initialProjectId || projects[0]?.id || '')
  const [source, setSource] = useState<CollectionSource>('serper')
  const [keywords, setKeywords] = useState('')
  const [region, setRegion] = useState('全国')
  const [maxResults, setMaxResults] = useState(20)
  const [file, setFile] = useState<File | null>(null)
  const [csvPreview, setCsvPreview] = useState<CsvPreview | null>(null)
  const [csvMapping, setCsvMapping] = useState<Record<string, string>>({})
  const [jobs, setJobs] = useState<CollectionJob[]>([])
  const [companies, setCompanies] = useState<Company[]>([])
  const [operations, setOperations] = useState<OperationJob[]>([])
  const [schedules, setSchedules] = useState<SearchSchedule[]>([])
  const [analytics, setAnalytics] = useState<SearchAnalytics[]>([])
  const [performance, setPerformance] = useState<CollectionPerformance[]>([])
  const [reviewAnalytics, setReviewAnalytics] = useState<AiReviewAnalytics[]>([])
  const [scheduleName, setScheduleName] = useState('定期検索')
  const [intervalHours, setIntervalHours] = useState(168)
  const [companyLimit, setCompanyLimit] = useState(10000)
  const [loading, setLoading] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [aiAnalyzing, setAiAnalyzing] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const project = projects.find(item => item.id === projectId)
  const profile = profiles.find(item => item.id === project?.target_profile_id)
  const projectRegion = project?.region
  const suggestedKeywords = useMemo(() => profile?.search_keywords ?? [], [profile])
  const suggestedKeywordText = suggestedKeywords.join('\n')

  const reload = useCallback(async () => {
    if (!projectId) { setJobs([]); setCompanies([]); setOperations([]); setSchedules([]); setAnalytics([]); setPerformance([]); setReviewAnalytics([]); return }
    const [nextJobs, nextCompanies, nextOperations, nextSchedules, nextAnalytics, nextPerformance, nextReviewAnalytics] = await Promise.all([
      allPages<CollectionJob>(`/projects/${projectId}/collection-jobs`),
      allPages<Company>(`/projects/${projectId}/companies`),
      api<OperationJob[]>(`/projects/${projectId}/operations`),
      api<SearchSchedule[]>(`/projects/${projectId}/search-schedules`),
      api<SearchAnalytics[]>(`/projects/${projectId}/search-analytics`),
      api<CollectionPerformance[]>(`/projects/${projectId}/collection-performance`),
      api<AiReviewAnalytics[]>(`/projects/${projectId}/ai-review-analytics`),
    ])
    setJobs(nextJobs); setCompanies(nextCompanies); setOperations(nextOperations); setSchedules(nextSchedules)
    setAnalytics(nextAnalytics); setPerformance(nextPerformance); setReviewAnalytics(nextReviewAnalytics)
  }, [projectId])

  useEffect(() => { reload().catch(e => setError(errorMessage(e))) }, [reload])
  useEffect(() => {
    if (!operations.some(job => ['queued', 'running'].includes(job.status))) return
    const timer = window.setInterval(() => void reload().catch(e => setError(errorMessage(e))), 2000)
    return () => window.clearInterval(timer)
  }, [operations, reload])
  useEffect(() => {
    if (projectRegion) setRegion(projectRegion)
    if (suggestedKeywordText) setKeywords(suggestedKeywordText)
  }, [projectId, projectRegion, suggestedKeywordText])

  async function submit(event: FormEvent) {
    event.preventDefault(); setError(''); setNotice(''); setLoading(true)
    try {
      if (!projectId) throw new Error('プロジェクトを選択してください。')
      let result: CollectionJob[]
      if (source === 'csv') {
        if (!file) { setError('CSVファイルを選択してください。'); return }
        const form = new FormData(); form.append('file', file)
        if (csvPreview) form.append('column_mapping', JSON.stringify(csvMapping))
        result = [await upload<CollectionJob>(`/projects/${projectId}/collection-jobs/csv`, form)]
      } else if (source === 'url') {
        const urls = keywords.split('\n').map(value => value.trim()).filter(Boolean)
        result = [await api<CollectionJob>(`/projects/${projectId}/collection-jobs/urls`, 'POST', { urls })]
      } else {
        const values = keywords.split('\n').map(value => value.trim()).filter(Boolean)
        await api<OperationJob>(`/projects/${projectId}/operations`, 'POST', {
          operation_type: 'collect_search', source, keywords: values, region, max_results: maxResults,
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
    setAnalyzing(true); setError(''); setNotice('')
    try {
      if (!companyIds.length) {
        await api<OperationJob>(`/projects/${projectId}/operations`, 'POST', {
          operation_type: 'web_analysis', company_ids: [], force: false,
        })
        await reload(); setNotice('Web解析をバックグラウンド処理へ登録しました。'); return
      }
      const results = await api<Company[]>(`/projects/${projectId}/web-analysis`, 'POST', {
        company_ids: companyIds, limit: companyIds.length, force: false,
      })
      await reload()
      setNotice(results.length
        ? `${results.length}社のWeb解析を完了しました。`
        : '解析対象の企業はありません。')
    } catch (e) { setError(errorMessage(e)) }
    finally { setAnalyzing(false) }
  }

  async function analyzeAi(companyIds: string[] = []) {
    setAiAnalyzing(true); setError(''); setNotice('')
    try {
      if (!companyIds.length) {
        await api<OperationJob>(`/projects/${projectId}/operations`, 'POST', {
          operation_type: 'ai_analysis', company_ids: [], force: false,
        })
        await reload(); setNotice('AI判定をバックグラウンド処理へ登録しました。'); return
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
    <p className="muted">企業は営業プロジェクトごとに収集・保存されます。</p>
  </section>

  return <div className="grid gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(360px,.95fr)]"><section className="space-y-6">
    <form className="panel form-panel max-w-none" onSubmit={submit}>
      <h2>収集条件</h2><p className="muted">収集元と検索条件を指定します。</p>
      {error && <p className="error" role="alert">{error}</p>}
      {notice && <p className="notice" role="status">{notice}</p>}
      <fieldset disabled={loading}>
        <Field label="プロジェクト"><select required value={projectId}
          onChange={e => setProjectId(e.target.value)}>{projects.map(item =>
          <option key={item.id} value={item.id}>{item.project_name}</option>)}</select></Field>
        <Field label="収集元"><select value={source} onChange={e => {
          const next = e.target.value as CollectionSource; setSource(next); setFile(null)
          setKeywords(next === 'url' ? '' : suggestedKeywordText)
        }}>{Object.entries(sourceNames).map(([value, label]) =>
          <option key={value} value={value}>{label}</option>)}</select></Field>
        {source === 'csv' ? <Field label="CSVファイル（UTF-8・最大5MB・1000行）">
          <input type="file" accept=".csv,text/csv" required onChange={e => void selectCsv(e.target.files?.[0] ?? null)} />
        </Field> : <Field label={source === 'url' ? 'URL（1行に1件）' : '検索キーワード（1行に1件）'}>
          <textarea required rows={8} value={keywords} onChange={e => setKeywords(e.target.value)}
            placeholder={source === 'url' ? 'https://example.com' : '検索キーワード'} />
        </Field>}
        {(['serper', 'google_places', 'gbizinfo'].includes(source)) && <div className="grid gap-5 sm:grid-cols-2">
          <Field label="地域"><input required maxLength={500} value={region} onChange={e => setRegion(e.target.value)} /></Field>
          <Field label="キーワードごとの最大件数"><input type="number" min={1}
            max={source === 'google_places' ? 60 : 100} value={maxResults}
            onChange={e => setMaxResults(Number(e.target.value))} /></Field>
        </div>}
        {source === 'csv' && csvPreview && <div className="mt-4"><p className="muted text-sm">{csvPreview.row_count}行を検出しました。取込先ごとにCSV列を指定してください。</p><div className="grid gap-3 mt-3 sm:grid-cols-2">{Object.entries({ company_name: '会社名', website_url: 'WebサイトURL', phone: '電話', email: 'メール', address: '住所' }).map(([field, label]) => <Field key={field} label={label}><select required value={csvMapping[field] ?? ''} onChange={e => setCsvMapping({ ...csvMapping, [field]: e.target.value })}><option value="">列を選択</option>{csvPreview.headers.map(header => <option key={header} value={header}>{header}</option>)}</select></Field>)}</div><div className="overflow-x-auto"><table><thead><tr>{csvPreview.headers.map(header => <th key={header}>{header}</th>)}</tr></thead><tbody>{csvPreview.sample_rows.map((row, index) => <tr key={index}>{csvPreview.headers.map(header => <td key={header}>{row[header]}</td>)}</tr>)}</tbody></table></div></div>}
        <div className="actions"><button type="submit">{loading ? (['serper', 'google_places', 'gbizinfo'].includes(source) ? '登録中…' : '収集中…') : '収集を開始'}</button></div>
      </fieldset>
    </form>
    <div className="panel"><h2>定期収集テンプレート</h2><p className="muted mt-2 text-sm">現在の検索条件を保存し、ワーカーで定期実行します。</p>
      <Field label="テンプレート名"><input maxLength={200} value={scheduleName} onChange={e => setScheduleName(e.target.value)} /></Field>
      <div className="grid gap-4 sm:grid-cols-2"><Field label="実行間隔（時間）"><input type="number" min={1} max={720} value={intervalHours} onChange={e => setIntervalHours(Number(e.target.value))} /></Field>
        <Field label="プロジェクト企業上限"><input type="number" min={1} max={100000} value={companyLimit} onChange={e => setCompanyLimit(Number(e.target.value))} /></Field></div>
      <button type="button" disabled={!['serper', 'google_places', 'gbizinfo'].includes(source)} onClick={() => void createSchedule()}>現在の検索条件を保存</button>
      {schedules.map(schedule => <article className="job-row block" key={schedule.id}><div className="flex justify-between gap-3"><strong>{schedule.name}</strong><span className="badge">{schedule.active ? '有効' : '停止中'}</span></div>
        <p className="muted my-2 text-sm">{schedule.keywords.join(' / ')}・{schedule.interval_hours}時間ごと・上限{schedule.company_limit}社</p>
        <p className="muted text-sm">次回 {new Date(schedule.next_run_at).toLocaleString('ja-JP')}</p>{schedule.last_error && <p className="error mt-2 mb-0">{schedule.last_error}</p>}
        <div className="mt-3 flex flex-wrap gap-2"><button type="button" className="secondary" onClick={() => void api(`/search-schedules/${schedule.id}/run`, 'POST').then(reload).catch(e => setError(errorMessage(e)))}>今すぐ実行</button>
          <button type="button" className="secondary" onClick={() => void api(`/search-schedules/${schedule.id}`, 'PUT', {
            name: schedule.name, source: schedule.source, keywords: schedule.keywords,
            region: schedule.region, max_results: schedule.max_results,
            interval_hours: schedule.interval_hours, company_limit: schedule.company_limit,
            active: !schedule.active,
          }).then(reload).catch(e => setError(errorMessage(e)))}>{schedule.active ? '停止' : '再開'}</button>
          <button type="button" className="danger" onClick={() => void api(`/search-schedules/${schedule.id}`, 'DELETE').then(reload).catch(e => setError(errorMessage(e)))}>削除</button></div>
      </article>)}
      {analytics.length > 0 && <div className="mt-6 overflow-x-auto"><h3 className="mb-3">テンプレート別成果</h3><table><thead><tr><th>テンプレート</th><th>検索数</th><th>発見</th><th>保存</th><th>保存率</th><th>重複率</th><th>公式外</th><th>エラー</th></tr></thead>
        <tbody>{analytics.map(item => <tr key={item.schedule_id}><td>{item.name}</td><td>{item.run_count}</td><td>{item.found_count}</td><td>{item.saved_count}</td><td>{item.save_rate}%</td><td>{item.duplicate_rate}%</td><td>{item.excluded_count}</td><td>{item.error_count}</td></tr>)}</tbody></table></div>}
      {reviewAnalytics.length > 0 && <div className="mt-6 overflow-x-auto"><h3 className="mb-2">AI判定レビュー精度</h3><p className="muted mb-3 text-sm">人手レビューを検索語ごとに集計しています。精度が低い検索語はターゲット条件の見直し候補です。</p><table><thead><tr><th>検索語</th><th>レビュー数</th><th>正しい</th><th>精度</th></tr></thead><tbody>{reviewAnalytics.map(item => <tr key={item.source_keyword}><td>{item.source_keyword}</td><td>{item.reviewed_count}</td><td>{item.correct_count}</td><td>{item.accuracy_rate}%</td></tr>)}</tbody></table></div>}
      {performance.length > 0 && <div className="mt-6 overflow-x-auto"><h3 className="mb-2">収集精度・速度の実績</h3><p className="muted mb-3 text-sm">保存率が低い検索語、公式外が多い検索語、時間がかかる収集元を比較して、検索条件を見直せます。</p><table><thead><tr><th>収集元</th><th>検索語</th><th>実行</th><th>発見</th><th>保存</th><th>保存率</th><th>公式外率</th><th>重複</th><th>エラー</th><th>平均時間</th></tr></thead>
        <tbody>{performance.map(item => <tr key={`${item.source}:${item.keyword}`}><td>{sourceNames[item.source]}</td><td>{item.keyword || '検索語なし'}</td><td>{item.run_count}</td><td>{item.found_count}</td><td>{item.saved_count}</td><td>{item.save_rate}%</td><td>{item.excluded_rate}%</td><td>{item.duplicate_count}</td><td>{item.error_count}</td><td>{(item.average_processing_ms / 1000).toFixed(1)}秒</td></tr>)}</tbody></table></div>}
    </div></section>
    <section className="space-y-6">
      <div className="panel"><div className="flex flex-wrap items-center justify-between gap-4"><div><h2>保存済み企業</h2>
        <p className="muted mt-2 text-sm">Webサイトから企業情報・SNS・問い合わせ先を抽出します。</p></div>
        <div className="flex flex-wrap items-center gap-2"><span className="badge">{companies.length} 社</span>
          <button type="button" disabled={analyzing || !companies.some(item => item.website_url && ['pending', 'failed'].includes(item.analysis_status))}
            onClick={() => void analyze()}>{analyzing ? '解析中…' : '未解析を解析'}</button>
          <button type="button" disabled={aiAnalyzing || !companies.some(item => item.analysis_status === 'completed' && item.ai_status !== 'completed')}
            onClick={() => void analyzeAi()}>{aiAnalyzing ? '判定中…' : '未判定をAI判定'}</button></div></div>
        {companies.slice(0, 5).map(company => <article key={company.id} className="job-row">
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
              <button type="button" className="secondary" disabled={analyzing}
                onClick={() => void analyze([company.id])}>Web解析</button>}
            {company.analysis_status === 'completed' && <button type="button" className="secondary"
              disabled={aiAnalyzing} onClick={() => void analyzeAi([company.id])}>AI判定</button>}</div>
        </article>)}
      </div>
      <div className="panel"><div className="flex items-center justify-between gap-4"><h2>最近の収集ジョブ</h2>
        <button type="button" className="secondary" disabled={loading} onClick={() => void reload()}>更新</button></div>
        {jobs.length === 0 ? <p className="muted mt-4">収集履歴はまだありません。</p> : jobs.slice(0, 10).map(job =>
          <article className="job-row block" key={job.id}>
            <div className="flex justify-between gap-3"><strong>{sourceNames[job.source]}</strong>
              <span className="badge">{statusNames[job.status]}</span></div>
            {(job.keyword || job.region) && <p className="muted my-2 text-sm">{[job.keyword, job.region].filter(Boolean).join(' / ')}</p>}
            <div className="job-stats"><span>発見 {job.found_count}</span><span>保存 {job.saved_count}</span>
              <span>重複 {job.duplicate_count}</span><span>公式外 {job.excluded_count}</span><span>エラー {job.error_count}</span><span>{job.processing_ms}ms</span></div>
            {job.error_message && <p className="error mt-3 mb-0">{job.error_message}</p>}
            {job.source === 'csv' && job.error_count > 0 && <button type="button" className="secondary mt-3" onClick={() => void download(`/collection-jobs/${job.id}/errors.csv`, 'csv-import-errors.csv').catch(e => setError(errorMessage(e)))}>行別エラーをダウンロード</button>}
          </article>)}
      </div>
      <div className="panel"><div className="flex items-center justify-between gap-4"><h2>バックグラウンド処理</h2>
        <button type="button" className="secondary" onClick={() => void reload()}>更新</button></div>
        {operations.length === 0 ? <p className="muted mt-4">処理履歴はまだありません。</p> : operations.map(job =>
            <article className="job-row block" key={job.id}><div className="flex justify-between gap-3"><strong>{job.operation_type === 'web_analysis' ? 'Web解析' : job.operation_type === 'ai_analysis' ? 'AI判定' : '検索収集'}</strong><span className="badge">{operationStatusNames[job.status]}</span></div>
            <p className="muted my-2 text-sm">{job.processed_count} / {job.total_count} 件（成功 {job.success_count}・失敗 {job.failed_count}・試行 {job.attempt_count}）</p>
            {job.error_message && <p className="error mb-0">{job.error_message}</p>}
            {['queued', 'running'].includes(job.status) && <button type="button" className="danger" onClick={() => void api(`/operations/${job.id}/cancel`, 'POST').then(reload).catch(e => setError(errorMessage(e)))}>キャンセル</button>}
            {['failed', 'cancelled'].includes(job.status) && <button type="button" className="secondary" onClick={() => void api(`/operations/${job.id}/retry`, 'POST').then(reload).catch(e => setError(errorMessage(e)))}>再実行</button>}
          </article>)}
      </div>
    </section>
  </div>
}
