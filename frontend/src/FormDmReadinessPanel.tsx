import { useCallback, useEffect, useState } from 'react'
import { api, download, errorMessage } from './api'
import type { OperationJob } from './types'

type ReadinessItem = {
  company_id: string
  company_name: string
  company_updated_at: string
  form_url: string
  primary_reason: string
  secondary_reasons: string[]
}
type Readiness = {
  counts: Record<string, number>
  total: number
  offset: number
  limit: number
  items: ReadinessItem[]
  last_aggregated_at: string | null
  last_aggregated_by_commit: string | null
  last_aggregated_by_host: string | null
  active_job: OperationJob | null
  active_reanalysis_job: OperationJob | null
  browser_analysis_enabled: boolean
  browser_analysis_job: OperationJob | null
  browser_analysis_counts: {
    total: number
    contact_page_no_form: number
    embed_unverified: number
    contact_form_7: number
    multipart: number
    confirmation: number
    javascript_submission: number
    last_analyzed_at: string | null
  }
  read_only: boolean
  external_requests: number
}

const labels: Record<string, string> = {
  CONTACT_PROHIBITED: '連絡禁止・営業NG',
  NON_COMPANY_SUSPECTED: '非企業の疑い',
  NON_COMPANY_LOCATION_RECORD: '店舗・施設などの所在地記録',
  NON_COMPANY_NAME_MISSING: '会社名が空欄または記号のみ',
  NON_COMPANY_PUBLIC_DOMAIN: '行政・公的機関のドメイン',
  NON_COMPANY_ARTICLE_STYLE_NAME: '記事・お知らせ風の名称',
  NON_COMPANY_REVIEW_NG: '人が会社ではないと確認',
  ALREADY_SENT_OR_UNKNOWN: '送信済み・予約済み・結果不明',
  CAPTCHA_VISIBLE: 'CAPTCHA（表示型）',
  CAPTCHA_INVISIBLE: 'CAPTCHA（非表示型）',
  CAPTCHA_LEGACY: 'CAPTCHA（旧解析結果・再解析が必要）',
  CF7: 'Contact Form 7',
  JS_SUBMIT: 'JavaScript送信',
  EXTERNAL_ACTION: '外部送信先',
  MULTIPART_OR_FILE: 'ファイル・multipart',
  FILE_ATTACHMENT: 'ファイル添付欄あり',
  MULTIPART_ONLY: 'multipart形式のみ（添付欄なし）',
  NON_POST_METHOD: 'POST以外',
  DUPLICATE_INPUTS: '同名の複数入力',
  MISSING_NAME_ATTRIBUTE: 'name属性なし',
  NO_NATIVE_SUBMIT: '標準の送信ボタンなし',
  CUSTOM_SUBMIT_HANDLER: '送信ボタンの独自処理',
  NO_INPUT_FIELDS: '入力項目なし',
  JAVASCRIPT_CONFIRMATION: '確認ボタンがJavaScript',
  OTHER_UNSUPPORTED: 'その他の非対応',
  CONFIRMATION_PAGE: '確認画面あり',
  CONFIRMATION_UNKNOWN: '確認画面未判定',
  NEEDS_CONSENT_REVIEW: '同意確認が必要',
  NEEDS_CHOICE_REVIEW: '選択肢確認が必要',
  NEEDS_MAPPING_REVIEW: '入力項目確認が必要',
  NO_FORM_DRAFT: 'フォーム文面なし',
  SENDER_SETTINGS: '送信者設定不足',
  READY: '準備可能',
  BROWSER_READY: 'ブラウザー送信準備可能',
}

export function FormDmReadinessPanel({ projectId, canWrite }: { projectId: string; canWrite: boolean }) {
  const [offset, setOffset] = useState(0)
  const [suspectedOnly, setSuspectedOnly] = useState(false)
  const [data, setData] = useState<Readiness | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [starting, setStarting] = useState(false)
  const [browserJob, setBrowserJob] = useState<OperationJob | null>(null)
  const [reviewingCompanyId, setReviewingCompanyId] = useState('')
  const [reviewNotice, setReviewNotice] = useState('')
  const [reanalysisJob, setReanalysisJob] = useState<OperationJob | null>(null)
  const refresh = useCallback(async () => {
    if (!projectId) { setData(null); return null }
    setBusy(true); setError('')
    try {
      const filter = suspectedOnly ? '&suspected_only=true' : ''
      const result = await api<Readiness>(`/projects/${projectId}/form-dm-readiness?offset=${offset}${filter}`)
      if (!result || typeof result.total !== 'number' || !Array.isArray(result.items) || !result.counts) {
        throw new Error('フォームDM診断の応答形式が不正です。再読み込みしてください。')
      }
      setData(result)
      if (result.active_reanalysis_job) setReanalysisJob(result.active_reanalysis_job)
      return result
    }
    catch (e) { setError(errorMessage(e)); return null }
    finally { setBusy(false) }
  }, [projectId, offset, suspectedOnly])
  const recalculate = useCallback(async () => {
    if (!projectId) return
    setStarting(true); setError('')
    try {
      await api(`/projects/${projectId}/form-dm-readiness/recalculate`, 'POST')
      await refresh()
    } catch (e) { setError(errorMessage(e)) }
    finally { setStarting(false) }
  }, [projectId, refresh])
  async function reanalyzeReason(reason: string) {
    if (!projectId) return
    setStarting(true); setError('')
    try {
      const job = await api<OperationJob>(
        `/projects/${projectId}/form-dm-readiness/reanalyze?reason=${encodeURIComponent(reason)}`,
        'POST',
      )
      setReanalysisJob(job)
    } catch (e) { setError(errorMessage(e)) }
    finally { setStarting(false) }
  }
  const startBrowserAnalysis = useCallback(async () => {
    if (!projectId) return
    setStarting(true); setError('')
    try {
      const job = await api<OperationJob>(`/projects/${projectId}/browser-form-analysis/recalculate`, 'POST')
      setBrowserJob(job)
    } catch (e) { setError(errorMessage(e)) }
    finally { setStarting(false) }
  }, [projectId])
  async function reviewCompany(item: ReadinessItem, confirmed: boolean) {
    setReviewingCompanyId(item.company_id); setError(''); setReviewNotice('')
    try {
      await api(`/companies/${item.company_id}/collection-feedback`, 'POST', {
        subject: 'company', outcome: confirmed ? 'OK' : 'NG',
        reason: confirmed ? 'company_verified' : 'wrong_company',
        expected_updated_at: item.company_updated_at,
        note: 'フォーム送信可否の非企業の疑いを人が確認',
      })
      setReviewNotice(confirmed ? '会社として確認し、対象に戻しました。' : '非企業として対象外に記録しました。')
      await recalculate()
    } catch (e) { setError(errorMessage(e)) }
    finally { setReviewingCompanyId('') }
  }
  useEffect(() => {
    void refresh().then(result => {
      if (result && !result.last_aggregated_at && !result.active_job) void recalculate()
    })
  }, [recalculate, refresh])
  useEffect(() => {
    if (!data?.active_job) return
    const timer = window.setInterval(() => { void refresh() }, 3000)
    return () => window.clearInterval(timer)
  }, [data?.active_job, refresh])
  const reanalysisJobId = reanalysisJob?.id
  const reanalysisJobStatus = reanalysisJob?.status
  useEffect(() => {
    if (!reanalysisJobId || !['queued', 'running'].includes(reanalysisJobStatus ?? '')) return
    const timer = window.setInterval(() => {
      void api<OperationJob>(`/projects/${projectId}/form-dm-readiness/reanalysis-jobs/${reanalysisJobId}`)
        .then(setReanalysisJob)
        .catch(e => setError(errorMessage(e)))
    }, 3000)
    return () => window.clearInterval(timer)
  }, [projectId, reanalysisJobId, reanalysisJobStatus])
  const reanalysisBusy = Boolean(reanalysisJob && ['queued', 'running'].includes(reanalysisJob.status))
  useEffect(() => {
    if (data?.browser_analysis_job) setBrowserJob(data.browser_analysis_job)
  }, [data?.browser_analysis_job])
  useEffect(() => {
    if (!browserJob?.id || !['queued', 'running'].includes(browserJob.status)) return
    const timer = window.setInterval(() => {
      api<OperationJob[]>(`/projects/${projectId}/operations?limit=100`).then(rows => {
        const current = rows.find(job => job.id === browserJob.id)
        if (!current) return
        setBrowserJob(current)
        if (['completed', 'failed', 'cancelled'].includes(current.status)) void refresh()
      }).catch(e => setError(errorMessage(e)))
    }, 2000)
    return () => window.clearInterval(timer)
  }, [browserJob?.id, browserJob?.status, projectId, refresh])
  const browserBusy = Boolean(browserJob && ['queued', 'running'].includes(browserJob.status))
  return <section className="panel mb-5" aria-label="フォームDM送信可否">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h2>フォームDMの送信可否</h2>
      <p className="muted mt-2 text-sm">フォームが見つかった企業を、既存の承認準備判定で分類します。集計自体は保存情報のみを使います。理由別の再解析ボタンを押すと対象企業だけフォーム解析しますが、送信・承認は行いません。非企業の疑いを人が確認した結果は収集リスト確認に記録します。</p></div>
      <div className="flex gap-2"><button className="secondary" disabled={starting || Boolean(data?.active_job) || reanalysisBusy || browserBusy} onClick={() => void recalculate()}>{data?.last_aggregated_at ? '再集計' : '集計開始'}</button><button className="secondary" disabled={busy || !data?.total} onClick={() => void download(`/projects/${projectId}/form-dm-readiness?format=csv${suspectedOnly ? '&suspected_only=true' : ''}`, 'form-dm-readiness.csv').catch(e => setError(errorMessage(e)))}>CSV出力</button></div>
    </div>
    {error && <p className="error mt-3" role="alert">{error}</p>}
    {reviewNotice && <p className="muted mt-3" role="status">{reviewNotice}</p>}
    {data?.last_aggregated_at && <p className="muted mt-3 text-sm">最終集計：{new Date(data.last_aggregated_at).toLocaleString('ja-JP')} · Worker版 {data.last_aggregated_by_commit || 'unknown'}（{data.last_aggregated_by_host || 'host不明'}）</p>}
    {data?.active_job && <p className="muted mt-3 text-sm">再集計中：{data.active_job.processed_count}/{data.active_job.total_count}社</p>}
    {reanalysisJob && <p className="muted mt-3 text-sm" role="status">
      {reanalysisBusy
        ? `フォーム再解析中（${labels[reanalysisJob.readiness_reanalysis_reason || ''] ?? reanalysisJob.readiness_reanalysis_reason}）：${reanalysisJob.processed_count}/${reanalysisJob.total_count}社（該当 ${reanalysisJob.readiness_reanalysis_matched_count ?? reanalysisJob.total_count}社、1回最大500社。送信・承認なし）`
        : reanalysisJob.status === 'completed'
          ? `フォーム再解析が完了しました：${reanalysisJob.success_count}社成功、${reanalysisJob.failed_count}社失敗。送信・承認は行っていません。再解析結果を集計するには「再集計」を押してください。`
          : `フォーム再解析は${reanalysisJob.status === 'cancelled' ? 'キャンセル' : '失敗'}しました：${reanalysisJob.processed_count}/${reanalysisJob.total_count}社。${reanalysisJob.error_message || ''}`}
    </p>}
    {data?.browser_analysis_counts && <div className="mt-3 rounded border p-3" aria-label="ブラウザ解析の集計">
      <p className="font-semibold">ブラウザ解析済み：{data.browser_analysis_counts.total}社</p>
      <div className="mt-2 flex flex-wrap gap-2 text-sm">
        <span className="badge">問い合わせページ到達・フォームなし：{data.browser_analysis_counts.contact_page_no_form}社</span>
        <span className="badge">埋め込み未確認：{data.browser_analysis_counts.embed_unverified}社</span>
        <span className="badge">Contact Form 7：{data.browser_analysis_counts.contact_form_7}社</span>
        <span className="badge">multipart：{data.browser_analysis_counts.multipart}社</span>
        <span className="badge">確認画面：{data.browser_analysis_counts.confirmation}社</span>
        <span className="badge">JavaScript送信：{data.browser_analysis_counts.javascript_submission}社</span>
      </div>
      <p className="muted mt-2 text-xs">表示後DOMの解析は読み取り専用です。フォームへの入力・送信、外部埋め込み先への接続は行いません。</p>
      <div className="actions mt-2">
        <button type="button" className="secondary" disabled={!canWrite || !data.browser_analysis_enabled || starting || reanalysisBusy || Boolean(data.active_job) || browserBusy} onClick={() => void startBrowserAnalysis()}>
          {browserJob && ['queued', 'running'].includes(browserJob.status) ? `ブラウザ解析中 ${browserJob.processed_count}/${browserJob.total_count}社` : 'ブラウザで最大100社を解析'}
        </button>
      </div>
      {!data.browser_analysis_enabled && <p className="muted text-xs">実サイト解析は既定でOFFです。田中さんの承認後に管理者がAPI・Worker双方の設定を有効化します。</p>}
      {browserJob && ['failed', 'cancelled'].includes(browserJob.status) && <p className="error text-sm" role="alert">{browserJob.error_message || 'ブラウザ解析が完了しませんでした。'}</p>}
      {data.browser_analysis_counts.last_analyzed_at && <p className="muted text-xs">最終ブラウザ解析：{new Date(data.browser_analysis_counts.last_analyzed_at).toLocaleString('ja-JP')}</p>}
    </div>}
    {data && <><div className="mt-4 flex flex-wrap gap-2" aria-label="送信可否の理由別件数">
      {Object.entries(data.counts).map(([code, count]) => <div className="flex flex-wrap items-center gap-1" key={code}>
        {code === 'NON_COMPANY_SUSPECTED'
          ? <button type="button" className="badge" aria-pressed={suspectedOnly} onClick={() => { setSuspectedOnly(value => !value); setOffset(0) }}>{labels[code] ?? code}: {count}社</button>
          : <span className="badge">{labels[code] ?? code}: {count}社</span>}
        {canWrite && count > 0 && code !== 'BROWSER_READY' && <button
          type="button"
          className="secondary text-xs"
          disabled={busy || starting || Boolean(data.active_job) || reanalysisBusy || browserBusy || reviewingCompanyId !== ''}
          onClick={() => void reanalyzeReason(code)}
        >この{Math.min(count, 500)}社を再解析{count > 500 ? `（全${count}社）` : ''}</button>}
      </div>)}
    </div><p className="muted mt-2 text-xs">CAPTCHAの該当数は、他の主理由がある企業も含む参考値です。非企業の疑い件数を押すと対象を絞り込めます。</p><p className="muted mt-3 text-sm">{suspectedOnly ? '非企業の疑い' : '対象'} {data.total}社 · 表示 {Math.min(offset + data.items.length, data.total)} / {data.total}社 · 集計結果（外部送信なし）</p>
    {data.items.map(item => <article className="border-t py-3" key={item.company_id}>
      <strong>{item.company_name}</strong><p className="mt-1">主な理由：{labels[item.primary_reason] ?? item.primary_reason}</p>
      {item.secondary_reasons.length > 0 && <p className="muted text-sm">他の理由：{item.secondary_reasons.map(reason => labels[reason] ?? reason).join('、')}</p>}
      {[item.primary_reason, ...item.secondary_reasons].includes('NON_COMPANY_SUSPECTED') && canWrite && <div className="actions mt-2" aria-label={`${item.company_name}の非企業確認`}>
        <button type="button" className="secondary" disabled={busy || starting || Boolean(data.active_job) || reanalysisBusy || browserBusy || reviewingCompanyId !== ''} onClick={() => void reviewCompany(item, true)}>会社として確認済み（対象に戻す）</button>
        <button type="button" className="secondary" disabled={busy || starting || Boolean(data.active_job) || reanalysisBusy || browserBusy || reviewingCompanyId !== ''} onClick={() => void reviewCompany(item, false)}>対象外にする</button>
      </div>}
      {/^https?:\/\//i.test(item.form_url) && <a className="text-sm break-all" href={item.form_url} target="_blank" rel="noreferrer">フォームURLを開く ↗</a>}
    </article>)}
    {data.total > data.limit && <div className="actions mt-3"><button className="secondary" disabled={busy || offset === 0} onClick={() => setOffset(value => Math.max(0, value - data.limit))}>前の20件</button><button className="secondary" disabled={busy || offset + data.limit >= data.total} onClick={() => setOffset(value => value + data.limit)}>次の20件</button></div>}
    </>}
  </section>
}
