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
  active_job: OperationJob | null
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
}

export function FormDmReadinessPanel({ projectId, canWrite }: { projectId: string; canWrite: boolean }) {
  const [offset, setOffset] = useState(0)
  const [suspectedOnly, setSuspectedOnly] = useState(false)
  const [data, setData] = useState<Readiness | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [starting, setStarting] = useState(false)
  const [reviewingCompanyId, setReviewingCompanyId] = useState('')
  const [reviewNotice, setReviewNotice] = useState('')
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
  return <section className="panel mb-5" aria-label="フォームDM送信可否">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h2>フォームDMの送信可否</h2>
      <p className="muted mt-2 text-sm">フォームが見つかった企業を、既存の承認準備判定で分類します。非企業の疑いを人が確認した結果は収集リスト確認に記録します。自動で外部アクセス・送信は行いません。</p></div>
      <div className="flex gap-2"><button className="secondary" disabled={starting || Boolean(data?.active_job)} onClick={() => void recalculate()}>{data?.last_aggregated_at ? '再集計' : '集計開始'}</button><button className="secondary" disabled={busy || !data?.total} onClick={() => void download(`/projects/${projectId}/form-dm-readiness?format=csv${suspectedOnly ? '&suspected_only=true' : ''}`, 'form-dm-readiness.csv').catch(e => setError(errorMessage(e)))}>CSV出力</button></div>
    </div>
    {error && <p className="error mt-3" role="alert">{error}</p>}
    {reviewNotice && <p className="muted mt-3" role="status">{reviewNotice}</p>}
    {data?.last_aggregated_at && <p className="muted mt-3 text-sm">最終集計：{new Date(data.last_aggregated_at).toLocaleString('ja-JP')}</p>}
    {data?.active_job && <p className="muted mt-3 text-sm">再集計中：{data.active_job.processed_count}/{data.active_job.total_count}社</p>}
    {data && <><div className="mt-4 flex flex-wrap gap-2" aria-label="送信可否の理由別件数">
      {Object.entries(data.counts).map(([code, count]) => code === 'NON_COMPANY_SUSPECTED'
        ? <button type="button" className="badge" key={code} aria-pressed={suspectedOnly} onClick={() => { setSuspectedOnly(value => !value); setOffset(0) }}>{labels[code] ?? code}: {count}社</button>
        : <span className="badge" key={code}>{labels[code] ?? code}: {count}社</span>)}
    </div><p className="muted mt-2 text-xs">CAPTCHAの該当数は、他の主理由がある企業も含む参考値です。非企業の疑い件数を押すと対象を絞り込めます。</p><p className="muted mt-3 text-sm">{suspectedOnly ? '非企業の疑い' : '対象'} {data.total}社 · 表示 {Math.min(offset + data.items.length, data.total)} / {data.total}社 · 集計結果（外部送信なし）</p>
    {data.items.map(item => <article className="border-t py-3" key={item.company_id}>
      <strong>{item.company_name}</strong><p className="mt-1">主な理由：{labels[item.primary_reason] ?? item.primary_reason}</p>
      {item.secondary_reasons.length > 0 && <p className="muted text-sm">他の理由：{item.secondary_reasons.map(reason => labels[reason] ?? reason).join('、')}</p>}
      {[item.primary_reason, ...item.secondary_reasons].includes('NON_COMPANY_SUSPECTED') && canWrite && <div className="actions mt-2" aria-label={`${item.company_name}の非企業確認`}>
        <button type="button" className="secondary" disabled={busy || starting || Boolean(data.active_job) || reviewingCompanyId !== ''} onClick={() => void reviewCompany(item, true)}>会社として確認済み（対象に戻す）</button>
        <button type="button" className="secondary" disabled={busy || starting || Boolean(data.active_job) || reviewingCompanyId !== ''} onClick={() => void reviewCompany(item, false)}>対象外にする</button>
      </div>}
      {/^https?:\/\//i.test(item.form_url) && <a className="text-sm break-all" href={item.form_url} target="_blank" rel="noreferrer">フォームURLを開く ↗</a>}
    </article>)}
    {data.total > data.limit && <div className="actions mt-3"><button className="secondary" disabled={busy || offset === 0} onClick={() => setOffset(value => Math.max(0, value - data.limit))}>前の20件</button><button className="secondary" disabled={busy || offset + data.limit >= data.total} onClick={() => setOffset(value => value + data.limit)}>次の20件</button></div>}
    </>}
  </section>
}
