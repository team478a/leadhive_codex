import { useCallback, useEffect, useState } from 'react'
import { api, download, errorMessage } from './api'
import type { OperationJob } from './types'

type ReadinessItem = {
  company_id: string
  company_name: string
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

export function FormDmReadinessPanel({ projectId }: { projectId: string }) {
  const [offset, setOffset] = useState(0)
  const [data, setData] = useState<Readiness | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [starting, setStarting] = useState(false)
  const refresh = useCallback(async () => {
    if (!projectId) { setData(null); return null }
    setBusy(true); setError('')
    try {
      const result = await api<Readiness>(`/projects/${projectId}/form-dm-readiness?offset=${offset}`)
      if (!result || typeof result.total !== 'number' || !Array.isArray(result.items) || !result.counts) {
        throw new Error('フォームDM診断の応答形式が不正です。再読み込みしてください。')
      }
      setData(result)
      return result
    }
    catch (e) { setError(errorMessage(e)); return null }
    finally { setBusy(false) }
  }, [projectId, offset])
  const recalculate = useCallback(async () => {
    if (!projectId) return
    setStarting(true); setError('')
    try {
      await api(`/projects/${projectId}/form-dm-readiness/recalculate`, 'POST')
      await refresh()
    } catch (e) { setError(errorMessage(e)) }
    finally { setStarting(false) }
  }, [projectId, refresh])
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
      <p className="muted mt-2 text-sm">フォームが見つかった企業を、既存の承認準備判定で分類します。保存済み情報のみを使い、外部アクセス・送信・設定変更は行いません。</p></div>
      <div className="flex gap-2"><button className="secondary" disabled={starting || Boolean(data?.active_job)} onClick={() => void recalculate()}>{data?.last_aggregated_at ? '再集計' : '集計開始'}</button><button className="secondary" disabled={busy || !data?.total} onClick={() => void download(`/projects/${projectId}/form-dm-readiness?format=csv`, 'form-dm-readiness.csv').catch(e => setError(errorMessage(e)))}>CSV出力</button></div>
    </div>
    {error && <p className="error mt-3" role="alert">{error}</p>}
    {data?.last_aggregated_at && <p className="muted mt-3 text-sm">最終集計：{new Date(data.last_aggregated_at).toLocaleString('ja-JP')}</p>}
    {data?.active_job && <p className="muted mt-3 text-sm">再集計中：{data.active_job.processed_count}/{data.active_job.total_count}社</p>}
    {data && <><div className="mt-4 flex flex-wrap gap-2" aria-label="送信可否の理由別件数">
      {Object.entries(data.counts).map(([code, count]) => <span className="badge" key={code}>{labels[code] ?? code}: {count}社</span>)}
    </div><p className="muted mt-2 text-xs">CAPTCHAの該当数は、他の主理由がある企業も含む参考値です。</p><p className="muted mt-3 text-sm">対象 {data.total}社 · 表示 {Math.min(offset + data.items.length, data.total)} / {data.total}社 · 読み取り専用</p>
    {data.items.map(item => <article className="border-t py-3" key={item.company_id}>
      <strong>{item.company_name}</strong><p className="mt-1">主な理由：{labels[item.primary_reason] ?? item.primary_reason}</p>
      {item.secondary_reasons.length > 0 && <p className="muted text-sm">他の理由：{item.secondary_reasons.map(reason => labels[reason] ?? reason).join('、')}</p>}
      {/^https?:\/\//i.test(item.form_url) && <a className="text-sm break-all" href={item.form_url} target="_blank" rel="noreferrer">フォームURLを開く ↗</a>}
    </article>)}
    {data.total > data.limit && <div className="actions mt-3"><button className="secondary" disabled={busy || offset === 0} onClick={() => setOffset(value => Math.max(0, value - data.limit))}>前の20件</button><button className="secondary" disabled={busy || offset + data.limit >= data.total} onClick={() => setOffset(value => value + data.limit)}>次の20件</button></div>}
    </>}
  </section>
}
