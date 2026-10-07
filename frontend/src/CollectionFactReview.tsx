import { useState } from 'react'
import { api, errorMessage } from './api'

export type FactCondition = { type: string; value: string; review_version?: number; company_fact_hash?: string; evidence_excerpt?: string; observed_value?: string }
export function CollectionFactReview({ companyId, condition, onSaved }: { companyId: string; condition: FactCondition; onSaved: () => void }) {
  const [outcome, setOutcome] = useState('MATCH')
  const [source, setSource] = useState('')
  const [excerpt, setExcerpt] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  if (!['AREA', 'INDUSTRY'].includes(condition.type)) return null
  async function save() {
    setBusy(true); setError('')
    try {
      await api(`/companies/${companyId}/collection-fact-reviews`, 'POST', { condition_type: condition.type, value: condition.value, outcome, source_url: source, evidence_excerpt: excerpt, expected_version: condition.review_version ?? 0, expected_company_hash: condition.company_fact_hash })
      setSource(''); setExcerpt(''); onSaved()
    } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false) }
  }
  return <details><summary>地域・業種の根拠を確認する：{condition.value}</summary>
    <p>登録情報（未検証・AI推定を含む）：{condition.observed_value || '不明'}。検索語やAI推定だけで一致と判断しないでください。</p>
    {condition.evidence_excerpt && <p>前回の確認内容：{condition.evidence_excerpt}</p>}
    <p>人がこの企業・店舗について確認した結果を記録します。有効期間は24時間。送信承認ではありません。</p>
    {error && <p role="alert" className="error">{error}</p>}
    <fieldset disabled={busy}>
      <label>確認結果<select value={outcome} onChange={e => setOutcome(e.target.value)}><option value="MATCH">条件に一致</option><option value="NO_MATCH">条件に不一致</option><option value="UNKNOWN">確認を取り消す・判断不能</option></select></label>
      <label>確認した公開ページURL<input type="url" value={source} onChange={e => setSource(e.target.value)} /></label>
      <label>確認内容・理由<textarea value={excerpt} maxLength={1000} onChange={e => setExcerpt(e.target.value)} /></label>
      <button type="button" disabled={excerpt.trim().length < 10 || (outcome !== 'UNKNOWN' && !source.trim())} onClick={() => void save()}>人の確認結果を保存</button>
    </fieldset>
  </details>
}
