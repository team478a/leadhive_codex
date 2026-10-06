import { useId, useState } from 'react'
import { api, errorMessage } from './api'
import type { RawRow } from './RawLeadReview'

type Preview = { left_id: string; right_id: string; pair_hash: string; features: Record<string, unknown>; version: number; outcome: string | null }

export function RawPairReview({ rows, canReview, onSaved }: { rows: RawRow[]; canReview: boolean; onSaved: () => void }) {
  const id = useId()
  const [left, setLeft] = useState('')
  const [right, setRight] = useState('')
  const [preview, setPreview] = useState<Preview | null>(null)
  const [session, setSession] = useState('')
  const [outcome, setOutcome] = useState('UNSURE')
  const [reason, setReason] = useState('')
  const [evidence, setEvidence] = useState('')
  const [checked, setChecked] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const clear = () => { setPreview(null); setSession(''); setChecked(false); setError('') }
  async function compare() {
    setBusy(true); clear()
    try { setPreview(await api<Preview>(`/raw-benchmarks/pairs/${left}/${right}`)) }
    catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function start() {
    if (!preview) return
    setBusy(true); setError('')
    try {
      const hash = rows.find(r => r.id === preview.left_id)?.snapshot_hash
      const v = await api<{ session_id: string }>(`/raw-benchmarks/snapshots/${preview.left_id}/review-start`, 'POST', { snapshot_hash: hash })
      setSession(v.session_id); setReason(''); setEvidence(''); setChecked(false); setOutcome('UNSURE')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function save() {
    if (!preview) return
    setBusy(true); setError('')
    try {
      await api(`/raw-benchmarks/pairs/${preview.left_id}/${preview.right_id}/reviews`, 'POST', { session_id: session, pair_hash: preview.pair_hash, expected_version: preview.version, outcome, reason, evidence_url: evidence })
      setPreview(await api<Preview>(`/raw-benchmarks/pairs/${left}/${right}`)); setSession(''); setChecked(false); onSaved()
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  return <section aria-label="Raw Entity Pair Review" className="panel mt-5 break-all">
    <h3>Human Entity Pair Review</h3>
    <p>SAME / DIFFERENT / UNSUREを独立した履歴として保存します。企業統合・CORRECTの自動付与・学習モデルの訓練は行いません。類似度は確率ではなく、欠損同士は一致扱いしません。</p>
    <div className="field"><label htmlFor={`${id}-left`}>Pair候補1</label><select id={`${id}-left`} value={left} disabled={busy} onChange={e => { setLeft(e.target.value); clear() }}><option value="">選択</option>{rows.map(r => <option key={r.id} value={r.id}>{r.payload.company_name} / {r.id.slice(0, 8)}</option>)}</select></div>
    <div className="field"><label htmlFor={`${id}-right`}>Pair候補2</label><select id={`${id}-right`} value={right} disabled={busy} onChange={e => { setRight(e.target.value); clear() }}><option value="">選択</option>{rows.filter(r => r.id !== left).map(r => <option key={r.id} value={r.id}>{r.payload.company_name} / {r.id.slice(0, 8)}</option>)}</select></div>
    <button disabled={busy || !left || !right || left === right} onClick={() => void compare()}>Pair特徴を比較</button>
    {preview && <>{rows.filter(r => r.id === left || r.id === right).map(r => <dl key={r.id}><dt>{String(r.payload.company_name)} / {r.id.slice(0, 8)}</dt><dd>住所: {String(r.payload.address || '不明')} / 電話: {String(r.payload.phone || '不明')} / website: {String(r.payload.website || '不明')} / reference: {String(r.payload.reference_url || '不明')}</dd></dl>)}<pre className="whitespace-pre-wrap break-all">{JSON.stringify(preview.features, null, 2)}</pre><p>Pair版 {preview.version} / {preview.outcome ?? '未判定'}</p>
      {canReview && (!session ? <button disabled={busy} onClick={() => void start()}>Human Pairレビューを開始</button> : <fieldset disabled={busy}>
        <div className="field"><label htmlFor={`${id}-outcome`}>Pair判定</label><select id={`${id}-outcome`} value={outcome} onChange={e => { setOutcome(e.target.value); setChecked(false) }}>{['SAME', 'DIFFERENT', 'UNSURE'].map(v => <option key={v}>{v}</option>)}</select></div>
        <div className="field"><label htmlFor={`${id}-reason`}>Pair判定理由</label><textarea id={`${id}-reason`} value={reason} maxLength={1000} onChange={e => { setReason(e.target.value); setChecked(false) }} /></div>
        <label className="field">Pair根拠URL<input value={evidence} maxLength={2048} onChange={e => { setEvidence(e.target.value); setChecked(false) }} /></label>
        <label className="checkbox-row"><input type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)} />この2候補を自分で比較しました</label>
        <button disabled={!checked || reason.trim().length < 2 || !evidence.trim()} onClick={() => void save()}>Pair判定を記録</button>
      </fieldset>)}
    </>}
    {error && <p role="alert">{error}</p>}
  </section>
}
