import { useState } from 'react'
import { api, errorMessage } from './api'

export type FactCondition = { type: string; value: string; review_version?: number; company_fact_hash?: string; evidence_excerpt?: string; observed_value?: string; review_hints?: { status: string; reason: string; terms?: string[]; excerpts: { text: string; source_url: string; observed_at: string; matched_term?: string }[] } }
export function CollectionFactReview({ companyId, condition, onSaved }: { companyId: string; condition: FactCondition; onSaved: () => void }) {
  const [outcome, setOutcome] = useState('MATCH')
  const [source, setSource] = useState('')
  const [excerpt, setExcerpt] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [hintUsed, setHintUsed] = useState(false)
  const [hintChecked, setHintChecked] = useState('')
  const hintContext = JSON.stringify([companyId, condition.type, condition.value, condition.company_fact_hash, condition.review_version, source, excerpt, outcome])
  const hintConfirmed = hintChecked === hintContext
  if (!['AREA', 'INDUSTRY'].includes(condition.type)) return null
  async function save() {
    setBusy(true); setError('')
    try {
      await api(`/companies/${companyId}/collection-fact-reviews`, 'POST', { condition_type: condition.type, value: condition.value, outcome, source_url: source, evidence_excerpt: excerpt, expected_version: condition.review_version ?? 0, expected_company_hash: condition.company_fact_hash })
      setSource(''); setExcerpt(''); setHintUsed(false); setHintChecked(''); onSaved()
    } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false) }
  }
  return <details><summary>地域・業種の根拠を確認する：{condition.value}</summary>
    <p>登録情報（未検証・AI推定を含む）：{condition.observed_value || '不明'}。検索語やAI推定だけで一致と判断しないでください。</p>
    {condition.evidence_excerpt && <p>前回の確認内容：{condition.evidence_excerpt}</p>}
    <p>人がこの企業・店舗について確認した結果を記録します。有効期間は24時間。送信承認ではありません。</p>
    {condition.type === 'INDUSTRY' && <section aria-label="業種の確認を助ける文章">
      <p>保存済み公式サイト本文の候補です。業種名の記載だけでは、この企業の業種が一致する証明になりません。顧客事例・求人・否定表現や、別店舗の説明ではないか確認してください。</p>
      {condition.review_hints?.terms && <p>確認候補の表記：{condition.review_hints.terms.join('・')}（条件の変更ではありません）</p>}
      {condition.review_hints?.excerpts.map((hint, i) => <div key={`${hint.source_url}-${i}`}>
        {hint.matched_term && <p>見つかった表記：{hint.matched_term}</p>}
        <blockquote>{hint.text}</blockquote>
        <p>取得日時：{new Date(hint.observed_at).toLocaleString('ja-JP')} <a href={hint.source_url} target="_blank" rel="noopener noreferrer">候補の公開ページ ↗</a></p>
        <button type="button" disabled={busy} onClick={() => { setSource(hint.source_url); setExcerpt(hint.text); setHintUsed(true); setHintChecked('') }}>この文章を確認欄に入れる</button>
      </div>)}
      {!condition.review_hints?.excerpts.length && <p>{condition.review_hints?.status === 'NO_LITERAL_MATCH' ? '条件の業種名を含む文章は見つかりません。「業種に不一致」という判定ではありません。' : '出典と取得日時を確認できる有効な本文がありません。公開ページを確認して入力してください。'}</p>}
    </section>}
    {error && <p role="alert" className="error">{error}</p>}
    <fieldset disabled={busy}>
      <label>確認結果<select value={outcome} onChange={e => setOutcome(e.target.value)}><option value="MATCH">条件に一致</option><option value="NO_MATCH">条件に不一致</option><option value="UNKNOWN">確認を取り消す・判断不能</option></select></label>
      <label>確認した公開ページURL<input type="url" value={source} onChange={e => { setSource(e.target.value); setHintChecked('') }} /></label>
      <label>確認内容・理由<textarea value={excerpt} maxLength={1000} onChange={e => { setExcerpt(e.target.value); setHintChecked('') }} /></label>
      {hintUsed && <label><input type="checkbox" checked={hintConfirmed} onChange={e => setHintChecked(e.target.checked ? hintContext : '')} />公開ページとこの企業・店舗の事業内容を確認しました</label>}
      <button type="button" disabled={excerpt.trim().length < 10 || (outcome !== 'UNKNOWN' && (!source.trim() || hintUsed && !hintConfirmed))} onClick={() => void save()}>人の確認結果を保存</button>
    </fieldset>
  </details>
}
