import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import { CollectionFactReview, type FactCondition } from './CollectionFactReview'
import { presenceLabels } from './externalPresenceShared'
import { conditionOutcomes as labels, conditionPriorities as priorities, conditionReasons as reasons } from './collectionConditionLabels'

type Condition = { id: string; priority: 'MUST' | 'WANT' | 'EXCLUDE'; type: string; operator: string; value: string }
export type ConditionRevision = { id: string; project_id: string; version: number; payload_hash: string; snapshot: { conditions: Condition[]; original_request?: string } }
type Candidate = { company_id: string; company_name: string; state: string; want_matched: number; want_unknown: number; conditions: (FactCondition & { id: string; priority: string; outcome: string; reason: string; evidence_url: string })[] }
type Report = { candidates: Candidate[]; total_candidates: number; evaluated_count: number; page_counts: Record<string, number>; note: string }
const kinds: Record<string, string> = { MEDIA_EXISTS: '掲載・SNSの存在', OFFICIAL_SITE: '確認済み公式サイト', AREA: '地域（根拠を人が確認）', INDUSTRY: '業種（根拠を人が確認）', ACTIVE_JOB: '現在募集中（検証未対応）', UNRESOLVED: 'その他・解釈待ち' }
const newCondition = (): Condition => ({ id: crypto.randomUUID(), priority: 'MUST', type: 'MEDIA_EXISTS', operator: 'EXISTS', value: 'INSTAGRAM' })

export function CollectionConditions({ projectId, onConfirmed, onApplied, onDraftChanged }: { projectId: string; onConfirmed?: (row: ConditionRevision | null) => void; onApplied?: (row: ConditionRevision) => void; onDraftChanged?: (dirty: boolean) => void }) {
  const [conditions, setConditions] = useState<Condition[]>([newCondition()])
  const [latest, setLatest] = useState<ConditionRevision | null>(null)
  const [report, setReport] = useState<Report | null>(null)
  const [offset, setOffset] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [requestText, setRequestText] = useState('')
  const [originalRequest, setOriginalRequest] = useState('')
  const [warnings, setWarnings] = useState<string[]>([])
  useEffect(() => {
    let active = true
    if (!projectId) return
    api<ConditionRevision[]>(`/projects/${projectId}/collection-conditions?limit=1`).then(rows => {
      if (active) { setLatest(rows[0] ?? null); if (rows[0]) { setConditions(rows[0].snapshot.conditions); setOriginalRequest(rows[0].snapshot.original_request ?? '') } }
    }).catch(e => { if (active) setError(errorMessage(e)) })
    return () => { active = false }
  }, [projectId])
  useEffect(() => { onConfirmed?.(latest) }, [latest, onConfirmed])
  const readResults = useCallback(async () => {
    if (!latest) return
    setBusy(true); setError('')
    try { setReport(await api<Report>(`/collection-conditions/${latest.id}/results?offset=${offset}&limit=20`)) }
    catch (e) { setReport(null); setError(errorMessage(e)) }
    finally { setBusy(false) }
  }, [latest, offset])
  useEffect(() => { void readResults() }, [readResults])
  function update(index: number, change: Partial<Condition>) {
    onDraftChanged?.(true)
    setConditions(rows => rows.map((c, i) => i === index ? { ...c, ...change } : c))
  }
  async function propose() {
    setBusy(true); setError(''); setNotice('')
    try {
      const proposal = await api<{ conditions: Condition[]; warnings: string[]; original_request: string }>(`/projects/${projectId}/collection-conditions/propose`, 'POST', { text: requestText })
      setConditions(proposal.conditions); setWarnings(proposal.warnings); setOriginalRequest(proposal.original_request)
      onDraftChanged?.(true)
      setNotice('条件案を作りました。内容を確認して確定してください。検索は開始していません。')
    } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false) }
  }
  async function confirm() {
    setBusy(true); setError(''); setNotice('')
    try {
      const row = await api<ConditionRevision>(`/projects/${projectId}/collection-conditions`, 'POST', { conditions, original_request: originalRequest, expected_version: latest?.version ?? 0, confirmed: true })
      setOffset(0); setReport(null); setLatest(row); setNotice(`条件を第${row.version}版として確定しました。検索や送信は開始していません。`)
      onApplied?.(row)
      onDraftChanged?.(false)
    } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false) }
  }
  return <details className="panel min-w-0"><summary className="font-semibold">対象条件を確認・分類する</summary>
    <p>必須条件はすべて一致した場合のみ採用。希望条件は採用を妨げず、除外条件が一致した対象は除外します。未確認の必須・除外条件は確認待ちです。</p>
    <p className="muted">地域・業種は候補ごとに根拠を確認できます。募集中の検証と自然文の条件解析はまだ未対応です。</p>
    {error && <p role="alert" className="error">{error}</p>}{notice && <p role="status" className="notice">{notice}</p>}
    <fieldset disabled={busy || !projectId} className="space-y-3">
      <label>探したい対象<textarea rows={3} maxLength={2000} value={requestText} onChange={e => { setRequestText(e.target.value); onDraftChanged?.(true) }} placeholder={'姫路市の美容院でInstagramあり\n希望:公式サイトあり'} /></label>
      <p className="muted">例の書き方、または「地域:姫路市」「業種:美容院」「除外:Instagramあり」を1行ずつ入力できます。複雑な文・件数・求人の現在性は自動解釈しません。</p>
      <button type="button" disabled={!requestText.trim()} onClick={() => void propose()}>文章から条件案を作る</button>
      {warnings.length > 0 && <div role="status">{warnings.map((warning, i) => <p key={i}>{warning}</p>)}</div>}
      {conditions.map((c, i) => <div key={c.id} className="grid gap-2 min-w-0">
        <label>条件{i + 1}の優先度<select aria-label={`条件${i + 1}の優先度`} value={c.priority} onChange={e => update(i, { priority: e.target.value as Condition['priority'] })}><option value="MUST">必須（MUST）</option><option value="WANT">希望（WANT）</option><option value="EXCLUDE">除外（EXCLUDE）</option></select></label>
        <label>条件{i + 1}の種類<select value={c.type} onChange={e => update(i, { type: e.target.value, operator: ['MEDIA_EXISTS', 'OFFICIAL_SITE'].includes(e.target.value) ? 'EXISTS' : 'EQUALS', value: e.target.value === 'MEDIA_EXISTS' ? 'INSTAGRAM' : e.target.value === 'OFFICIAL_SITE' ? 'OFFICIAL_SITE' : '' })}>{Object.entries(kinds).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label>
        {c.type === 'MEDIA_EXISTS' ? <label>条件{i + 1}の媒体<select value={c.value} onChange={e => update(i, { value: e.target.value })}>{Object.entries(presenceLabels).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label> : c.type !== 'OFFICIAL_SITE' && <label>条件{i + 1}の内容<input maxLength={300} value={c.value} onChange={e => update(i, { value: e.target.value })} /></label>}
        <button type="button" disabled={conditions.length === 1} onClick={() => { onDraftChanged?.(true); setConditions(rows => rows.filter((_, n) => n !== i)) }}>条件{i + 1}を削除</button>
      </div>)}
      <button type="button" disabled={conditions.length >= 20} onClick={() => { onDraftChanged?.(true); setConditions(rows => [...rows, newCondition()]) }}>条件を追加</button>
      <button type="button" onClick={() => { setConditions(latest?.snapshot.conditions ?? [newCondition()]); setWarnings([]); setOriginalRequest(latest?.snapshot.original_request ?? ''); setRequestText(''); onDraftChanged?.(false); setNotice('未確定の変更を取り消しました。') }}>未確定の変更を取り消す</button>
      <button type="button" disabled={Boolean(requestText.trim() && requestText !== originalRequest) || conditions.some(c => c.type === 'UNRESOLVED' || !c.value.trim())} onClick={() => void confirm()}>条件を確認して確定</button>
      {requestText.trim() && requestText !== originalRequest && <p>文章を変更しました。「文章から条件案を作る」で内容を反映してから確定してください。</p>}
      <p className="muted">確定すると今回の収集に条件を選択します。地域・業種が各1つの必須条件なら検索欄にも反映します。件数・追加調査予算は変更しません。「収集を開始」を押すまで実行しません。</p>
    </fieldset>
    {latest && <section aria-label="条件判定結果">
      <p>確定条件：第{latest.version}版。以下は確定版の判定です。入力の変更は再確定するまで反映されません。</p>
      <button type="button" disabled={busy} onClick={() => void readResults()}>最新の根拠で再表示</button>
      {report && <><p>表示ページ内：一致 {report.page_counts.MATCH}件、不一致 {report.page_counts.NO_MATCH}件、確認待ち {report.page_counts.REVIEW_REQUIRED}件（候補全体 {report.total_candidates}件）</p>
        <p className="muted">条件一致はDM準備完了・送信承認を意味しません。</p>
        {!report.candidates.length && <p>保存済みの候補はありません。</p>}
        {report.candidates.map(c => <details key={c.company_id}><summary>{c.company_name}：{labels[c.state]}（希望一致 {c.want_matched}、希望未確認 {c.want_unknown}）</summary>
          {c.conditions.map(r => <div key={r.id}><p>{priorities[r.priority]}・{presenceLabels[r.value] ?? (r.type === 'OFFICIAL_SITE' ? '公式サイト' : r.value)}：{labels[r.outcome]}。{reasons[r.reason] ?? r.reason} {r.evidence_url && <a href={r.evidence_url} target="_blank" rel="noopener noreferrer">根拠 ↗</a>}</p><CollectionFactReview companyId={c.company_id} condition={r} onSaved={() => void readResults()} /></div>)}
        </details>)}
        <div className="flex flex-wrap gap-2"><button type="button" disabled={busy || offset === 0} onClick={() => setOffset(n => Math.max(0, n - 20))}>前の20件</button><button type="button" disabled={busy || offset + 20 >= report.total_candidates} onClick={() => setOffset(n => n + 20)}>次の20件</button></div>
      </>}
    </section>}
  </details>
}
