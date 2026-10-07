import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import { presenceLabels } from './externalPresenceShared'

type Condition = { id: string; priority: 'MUST' | 'WANT' | 'EXCLUDE'; type: string; operator: string; value: string }
type Revision = { id: string; version: number; payload_hash: string; snapshot: { conditions: Condition[] } }
type Candidate = { company_id: string; company_name: string; state: string; want_matched: number; want_unknown: number; conditions: { id: string; priority: string; type: string; value: string; outcome: string; reason: string; evidence_url: string }[] }
type Report = { candidates: Candidate[]; total_candidates: number; evaluated_count: number; page_counts: Record<string, number>; note: string }
const kinds: Record<string, string> = { MEDIA_EXISTS: '掲載・SNSの存在', OFFICIAL_SITE: '確認済み公式サイト', AREA: '地域（検証未対応）', INDUSTRY: '業種（検証未対応）', ACTIVE_JOB: '現在募集中（検証未対応）', UNRESOLVED: 'その他・解釈待ち' }
const labels: Record<string, string> = { MATCH: '一致', NO_MATCH: '不一致', REVIEW_REQUIRED: '確認待ち', UNKNOWN: '未確認' }
const priorities: Record<string, string> = { MUST: '必須', WANT: '希望', EXCLUDE: '除外' }
const reasons: Record<string, string> = { VERIFICATION_UNSUPPORTED: 'この条件の検証は未対応', OFFICIAL_SITE_UNCONFIRMED: '公式サイトの根拠が未確認', PRESENCE_FOUND: '関連するページを確認', EVIDENCE_EXPIRED: '根拠の有効期間が終了', NEGATIVE_EVIDENCE_UNAVAILABLE: '有効な調査記録なし', SEARCH_NO_MATCH: '追加調査で見つからず', NOT_CHECKED: '未調査', ENTITY_CHANGED: '企業情報変更後の再確認が必要', SEARCH_BUDGET_EXHAUSTED: '検索上限に到達', ERROR: '調査結果を確認できません' }
const newCondition = (): Condition => ({ id: crypto.randomUUID(), priority: 'MUST', type: 'MEDIA_EXISTS', operator: 'EXISTS', value: 'INSTAGRAM' })

export function CollectionConditions({ projectId }: { projectId: string }) {
  const [conditions, setConditions] = useState<Condition[]>([newCondition()])
  const [latest, setLatest] = useState<Revision | null>(null)
  const [report, setReport] = useState<Report | null>(null)
  const [offset, setOffset] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  useEffect(() => {
    let active = true
    if (!projectId) return
    api<Revision[]>(`/projects/${projectId}/collection-conditions?limit=1`).then(rows => {
      if (active) { setLatest(rows[0] ?? null); if (rows[0]) setConditions(rows[0].snapshot.conditions) }
    }).catch(e => { if (active) setError(errorMessage(e)) })
    return () => { active = false }
  }, [projectId])
  const readResults = useCallback(async () => {
    if (!latest) return
    setBusy(true); setError('')
    try { setReport(await api<Report>(`/collection-conditions/${latest.id}/results?offset=${offset}&limit=20`)) }
    catch (e) { setReport(null); setError(errorMessage(e)) }
    finally { setBusy(false) }
  }, [latest, offset])
  useEffect(() => { void readResults() }, [readResults])
  function update(index: number, change: Partial<Condition>) {
    setConditions(rows => rows.map((c, i) => i === index ? { ...c, ...change } : c))
  }
  async function confirm() {
    setBusy(true); setError(''); setNotice('')
    try {
      const row = await api<Revision>(`/projects/${projectId}/collection-conditions`, 'POST', { conditions, expected_version: latest?.version ?? 0, confirmed: true })
      setOffset(0); setReport(null); setLatest(row); setNotice(`条件を第${row.version}版として確定しました。検索や送信は開始していません。`)
    } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false) }
  }
  return <details className="panel min-w-0"><summary className="font-semibold">対象条件を確認・分類する</summary>
    <p>必須条件はすべて一致した場合のみ採用。希望条件は採用を妨げず、除外条件が一致した対象は除外します。未確認の必須・除外条件は確認待ちです。</p>
    <p className="muted">保存済み情報の確認機能です。地域・業種・募集中の自動検証と、自然文の条件解析はまだ未対応です。</p>
    {error && <p role="alert" className="error">{error}</p>}{notice && <p role="status" className="notice">{notice}</p>}
    <fieldset disabled={busy || !projectId} className="space-y-3">
      {conditions.map((c, i) => <div key={c.id} className="grid gap-2 min-w-0">
        <label>条件{i + 1}の優先度<select aria-label={`条件${i + 1}の優先度`} value={c.priority} onChange={e => update(i, { priority: e.target.value as Condition['priority'] })}><option value="MUST">必須（MUST）</option><option value="WANT">希望（WANT）</option><option value="EXCLUDE">除外（EXCLUDE）</option></select></label>
        <label>条件{i + 1}の種類<select value={c.type} onChange={e => update(i, { type: e.target.value, operator: ['MEDIA_EXISTS', 'OFFICIAL_SITE'].includes(e.target.value) ? 'EXISTS' : 'EQUALS', value: e.target.value === 'MEDIA_EXISTS' ? 'INSTAGRAM' : e.target.value === 'OFFICIAL_SITE' ? 'OFFICIAL_SITE' : '' })}>{Object.entries(kinds).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label>
        {c.type === 'MEDIA_EXISTS' ? <label>条件{i + 1}の媒体<select value={c.value} onChange={e => update(i, { value: e.target.value })}>{Object.entries(presenceLabels).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label> : c.type !== 'OFFICIAL_SITE' && <label>条件{i + 1}の内容<input maxLength={300} value={c.value} onChange={e => update(i, { value: e.target.value })} /></label>}
        <button type="button" disabled={conditions.length === 1} onClick={() => setConditions(rows => rows.filter((_, n) => n !== i))}>条件{i + 1}を削除</button>
      </div>)}
      <button type="button" disabled={conditions.length >= 20} onClick={() => setConditions(rows => [...rows, newCondition()])}>条件を追加</button>
      <button type="button" onClick={() => void confirm()}>条件を確認して確定</button>
    </fieldset>
    {latest && <section aria-label="条件判定結果">
      <p>確定条件：第{latest.version}版。以下は確定版の判定です。入力の変更は再確定するまで反映されません。</p>
      <button type="button" disabled={busy} onClick={() => void readResults()}>最新の根拠で再表示</button>
      {report && <><p>表示ページ内：一致 {report.page_counts.MATCH}件、不一致 {report.page_counts.NO_MATCH}件、確認待ち {report.page_counts.REVIEW_REQUIRED}件（候補全体 {report.total_candidates}件）</p>
        <p className="muted">条件一致はDM準備完了・送信承認を意味しません。</p>
        {!report.candidates.length && <p>保存済みの候補はありません。</p>}
        {report.candidates.map(c => <details key={c.company_id}><summary>{c.company_name}：{labels[c.state]}（希望一致 {c.want_matched}、希望未確認 {c.want_unknown}）</summary>
          {c.conditions.map(r => <p key={r.id}>{priorities[r.priority]}・{presenceLabels[r.value] ?? (r.type === 'OFFICIAL_SITE' ? '公式サイト' : r.value)}：{labels[r.outcome]}。{reasons[r.reason] ?? r.reason} {r.evidence_url && <a href={r.evidence_url} target="_blank" rel="noopener noreferrer">根拠 ↗</a>}</p>)}
        </details>)}
        <div className="flex flex-wrap gap-2"><button type="button" disabled={busy || offset === 0} onClick={() => setOffset(n => Math.max(0, n - 20))}>前の20件</button><button type="button" disabled={busy || offset + 20 >= report.total_candidates} onClick={() => setOffset(n => n + 20)}>次の20件</button></div>
      </>}
    </section>}
  </details>
}
