import { useId, useState } from 'react'
import { api, errorMessage } from './api'
import { outcomeLabels } from './rawBenchmarkTypes'

export type RawRow = { id: string; candidate_key: string; snapshot_hash: string; payload: Record<string, string | number | string[]>; review: { version: number; outcome: string; reason: string; evidence_url: string; entity_key: string; duplicate_of: string | null; reviewer: string; reviewed_at: string; duration_seconds: number } | null }

export function RawLeadReview({ row, rows, canReview, onSaved }: { row: RawRow; rows: RawRow[]; canReview: boolean; onSaved: () => void }) {
  const reasonId = useId()
  const outcomeId = useId()
  const duplicateId = useId()
  const [session, setSession] = useState('')
  const [outcome, setOutcome] = useState('UNCERTAIN')
  const [reason, setReason] = useState('')
  const [evidence, setEvidence] = useState('')
  const [entity, setEntity] = useState('')
  const [duplicate, setDuplicate] = useState('')
  const [observed, setObserved] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function start() {
    setBusy(true); setError('')
    try { const v = await api<{ session_id: string }>(`/raw-benchmarks/snapshots/${row.id}/review-start`, 'POST', { snapshot_hash: row.snapshot_hash }); setSession(v.session_id) }
    catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function save() {
    setBusy(true); setError('')
    try {
      await api(`/raw-benchmarks/snapshots/${row.id}/reviews`, 'POST', { snapshot_hash: row.snapshot_hash, session_id: session, expected_version: row.review?.version ?? 0, outcome, reason, evidence_url: evidence, entity_key: entity, duplicate_of: outcome === 'DUPLICATE' ? duplicate : null })
      setSession(''); setObserved(false); onSaved()
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  return <details className="panel mt-3 break-all" aria-label={`Raw候補 ${row.id}`}>
    <summary>{String(row.payload.company_name || '名称不明')} / {row.review ? outcomeLabels[row.review.outcome] : '未レビュー'}</summary>
    <dl>{Object.entries(row.payload).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value || '—')}</dd></div>)}</dl>
    <p>Raw Snapshot hash：{row.snapshot_hash}</p>
    {row.review && <p>Humanレビュー版 {row.review.version} / 確認者 {row.review.reviewer} / {new Date(row.review.reviewed_at).toLocaleString('ja-JP')} / {row.review.duration_seconds}秒<br />理由：{row.review.reason}<br />根拠：{row.review.evidence_url}<br />照合ID：{row.review.entity_key || '—'}</p>}
    {canReview && (!session ? <button className="secondary" disabled={busy} onClick={() => void start()}>Humanレビューを開始</button> : <fieldset disabled={busy}>
      <p>開始時刻から作業時間を測ります。4時間以内に保存してください。確認していない候補は正解にしないでください。</p>
      <div className="field"><label htmlFor={outcomeId}>Raw判定</label><select id={outcomeId} value={outcome} onChange={e => { setOutcome(e.target.value); setObserved(false) }}>{Object.entries(outcomeLabels).map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select></div>
      {outcome === 'CORRECT' && <label className="field">店舗照合ID<input value={entity} pattern="[A-Za-z0-9_-]+" maxLength={100} onChange={e => { setEntity(e.target.value); setObserved(false) }} placeholder="例 store-001。同じ店舗は同じID。会社名・電話は使わない" /></label>}
      {outcome === 'DUPLICATE' && <div className="field"><label htmlFor={duplicateId}>重複先</label><select id={duplicateId} value={duplicate} onChange={e => { setDuplicate(e.target.value); setObserved(false) }}><option value="">先に確認した同じ店舗を選択</option>{rows.filter(r => r.id !== row.id && r.review?.entity_key).map(r => <option key={r.id} value={r.id}>{r.payload.company_name} / {r.review?.entity_key}</option>)}</select></div>}
      <div className="field"><label htmlFor={reasonId}>Raw判定の理由</label><textarea id={reasonId} value={reason} maxLength={1000} onChange={e => { setReason(e.target.value); setObserved(false) }} /></div>
      <label className="field">Raw判定の根拠URL<input value={evidence} maxLength={2048} onChange={e => { setEvidence(e.target.value); setObserved(false) }} placeholder="秘密情報のない公開URL。アプリはアクセスしません" /></label>
      <label className="checkbox-row"><input type="checkbox" checked={observed} onChange={e => setObserved(e.target.checked)} />このRaw候補の判定と根拠を自分で確認しました</label>
      <button disabled={busy || !observed || reason.trim().length < 2 || !evidence.trim() || (outcome === 'CORRECT' && !entity.trim()) || (outcome === 'DUPLICATE' && !duplicate)} onClick={() => void save()}>Rawレビューを記録</button>
      <button className="secondary" onClick={() => { setSession(''); setObserved(false) }}>レビューをやめる</button>
    </fieldset>)}
    {error && <p role="alert">{error}</p>}
  </details>
}
