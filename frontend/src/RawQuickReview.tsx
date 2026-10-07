import { useEffect, useId, useRef, useState } from 'react'
import { api, errorMessage } from './api'
import type { RawRow } from './RawLeadReview'
import { outcomeLabels } from './rawBenchmarkTypes'

function publicLink(value: unknown) {
  try {
    const url = new URL(String(value || ''))
    const host = url.hostname.toLowerCase()
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password ||
      host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local') || host.includes(':') ||
      /^(127\.|10\.|192\.168\.|169\.254\.|0\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host)) return ''
    url.search = ''; url.hash = ''
    return url.href
  } catch { return '' }
}

function ReviewCard({ row, rows, region, industry, canReview, onSaved, onSkip }: {
  row: RawRow; rows: RawRow[]; region: string; industry: string; canReview: boolean
  onSaved: () => Promise<void>; onSkip: () => void
}) {
  const id = useId()
  const [session, setSession] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const request = useRef<Promise<{ session_id: string }> | null>(null)
  const link = publicLink(row.payload.reference_url) || publicLink(row.payload.website)
  const [evidence, setEvidence] = useState(row.review?.evidence_url || link)
  const [note, setNote] = useState('')
  const [outside, setOutside] = useState(false)
  const [duplicate, setDuplicate] = useState(false)
  const [original, setOriginal] = useState('')
  const earlier = rows.slice(0, rows.findIndex(r => r.id === row.id)).filter(r => r.review?.entity_key)
  useEffect(() => {
    if (!canReview) return
    let active = true
    const pending = request.current ?? api<{ session_id: string }>(`/raw-benchmarks/snapshots/${row.id}/review-start`, 'POST', { snapshot_hash: row.snapshot_hash })
    request.current = pending
    pending.then(v => { if (active) { setSession(v.session_id); setError('') } }).catch(e => { request.current = null; if (active) setError(errorMessage(e)) })
    return () => { active = false }
  }, [row.id, row.snapshot_hash, canReview, attempt])
  async function record(outcome: string) {
    if (!session || busy) return
    setBusy(true); setError('')
    try {
      await api(`/raw-benchmarks/snapshots/${row.id}/reviews`, 'POST', {
        snapshot_hash: row.snapshot_hash, session_id: session, expected_version: row.review?.version ?? 0,
        outcome, reason: note.trim() || `利用者が掲載情報を確認し「${outcomeLabels[outcome]}」と判定`,
        evidence_url: evidence, entity_key: outcome === 'CORRECT' ? (row.review?.entity_key || `lead-${row.id}`) : '',
        duplicate_of: outcome === 'DUPLICATE' ? original : null,
      })
      setSession(''); await onSaved()
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  const disabled = busy || !session || !publicLink(evidence)
  return <article aria-label="確認する候補" className="panel mt-3 break-words">
    <h3>{String(row.payload.company_name || '名前が取得できませんでした')}</h3>
    <p className="mt-3">この候補は「{region}」の「{industry}」に合っていますか？</p>
    <dl className="mt-3"><dt>住所</dt><dd>{String(row.payload.address || '検索結果に住所の記載なし')}</dd><dt>電話番号</dt><dd>{String(row.payload.phone || '検索結果に電話番号の記載なし')}</dd></dl>
    {link && <a href={link} target="_blank" rel="noopener noreferrer" className="inline-flex rounded-lg border border-[#c9d8ce] px-5 py-3 font-semibold text-[#235c4c] mt-3">掲載ページを開く ↗</a>}
    <p className="muted mt-3">掲載ページで地域・業種を確認し、下から選んでください。選ぶと判定を保存して次へ進みます。</p>
    {!canReview ? <p>閲覧のみの権限です。確認結果は編集できません。</p> : <>
      {!link && <label className="field mt-3">確認したページのURL<input value={evidence} maxLength={2048} onChange={e => setEvidence(e.target.value)} /></label>}
      <details className="mt-3"><summary>メモ・確認先を変更する（任意）</summary>
        <label className="field">確認メモ<textarea value={note} maxLength={1000} onChange={e => setNote(e.target.value)} /></label>
        {link && <label className="field">確認したページのURL<input value={evidence} maxLength={2048} onChange={e => setEvidence(e.target.value)} /></label>}
      </details>
      {earlier.length > 0 && <p className="muted mt-3">確認済みの会社・店舗と同じなら「確認済みの候補と同じ対象」を選んでください。</p>}
      <div className="actions flex-wrap justify-start mt-5">
        <button disabled={disabled} onClick={() => void record('CORRECT')}>対象に合うと確認して次へ</button>
        <button className="secondary" disabled={busy || !session} onClick={() => { setOutside(!outside); setDuplicate(false) }}>対象外・違う</button>
        <button className="secondary" disabled={disabled} onClick={() => void record('UNCERTAIN')}>判断できないとして次へ</button>
      </div>
      {outside && <div className="actions flex-wrap justify-start mt-3" aria-label="対象外の理由">{[
        ['WRONG_INDUSTRY', '業種が違う'], ['WRONG_AREA', '地域が違う'],
        ['PORTAL_OR_AGGREGATOR', '予約・まとめサイト'], ['WRONG_ENTITY', '別の会社・店舗'],
        ['CLOSED_OR_INACTIVE', '閉店・営業終了'],
      ].map(([value, label]) => <button key={value} className="secondary" disabled={disabled} onClick={() => void record(value)}>{label}と確認して次へ</button>)}</div>}
      {earlier.length > 0 && <button className="secondary mt-3" disabled={busy || !session} onClick={() => { setDuplicate(!duplicate); setOutside(false) }}>確認済みの候補と同じ対象</button>}
      {duplicate && <div className="mt-3"><label htmlFor={`${id}-duplicate`}>同じ対象を選択</label><select id={`${id}-duplicate`} value={original} disabled={busy} onChange={e => setOriginal(e.target.value)}><option value="">選択してください</option>{earlier.map(r => <option key={r.id} value={r.id}>{String(r.payload.company_name)}</option>)}</select><button className="secondary mt-3" disabled={disabled || !original} onClick={() => void record('DUPLICATE')}>同じ対象と確認して次へ</button></div>}
      <button className="secondary mt-3" disabled={busy} onClick={onSkip}>保存せず後で確認</button>
      {!session && !error && <p role="status">確認の準備中…</p>}
    </>}
    {error && <div role="alert" className="error mt-3">{error}{!session && <button onClick={() => setAttempt(v => v + 1)}>もう一度準備する</button>}<p>保存に失敗した場合は次の候補に進みません。</p><button className="secondary" disabled={busy} onClick={() => void onSaved()}>最新の状態を読み直す</button></div>}
  </article>
}

export function RawQuickReview({ rows, region, industry, canReview, onSaved }: {
  rows: RawRow[]; region: string; industry: string; canReview: boolean; onSaved: () => Promise<void>
}) {
  const [skipped, setSkipped] = useState<string[]>([])
  const [history, setHistory] = useState('')
  const representatives = rows.filter((r, i) => rows.findIndex(v => v.candidate_key === r.candidate_key) === i)
  const pending = representatives.filter(r => !r.review)
  const current = history ? representatives.find(r => r.id === history) : pending.find(r => !skipped.includes(r.id))
  return <section aria-label="候補の確認" className="mt-5">
    <h2>集めた候補を確認する</h2>
    <p role="status">候補 {representatives.length}件 ／ 確認済み {representatives.length - pending.length}件 ／ 未確認 {pending.length}件</p>
    <p className="muted">同じ検索結果はまとめて表示しています。判断は他の取得結果へ自動転記されません。</p>
    {current ? <ReviewCard key={`${current.id}:${current.review?.version ?? 0}`} row={current} rows={rows} region={region} industry={industry} canReview={canReview}
      onSaved={async () => { setHistory(''); await onSaved() }} onSkip={() => { setHistory(''); setSkipped(v => [...v, current.id]) }} />
      : pending.length ? <div className="panel mt-3"><p>残りは後で確認する候補です。判定は保存されていません。</p><button onClick={() => setSkipped([])}>残りの確認を再開</button></div>
        : <div className="panel mt-3"><p>{rows.length ? '表示した候補の確認が終わりました。各回の取得結果との照合は詳細画面で確認できます。' : '候補はまだありません。検索条件を設定すると、ここから順番に確認できます。'}</p></div>}
    {representatives.some(r => r.review) && <details className="mt-5"><summary>確認済みの候補を見る・判定を直す</summary>{representatives.filter(r => r.review).map(r => <button key={r.id} className="secondary mt-3" onClick={() => setHistory(r.id)}>{String(r.payload.company_name)}：{outcomeLabels[r.review!.outcome]}</button>)}</details>}
  </section>
}
