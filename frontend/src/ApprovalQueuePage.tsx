import { useEffect, useState, type FormEvent } from 'react'
import { api, errorMessage } from './api'
import { Field } from './forms'
import { ApprovedEmailPanel, type ApprovalProposal as Proposal } from './ApprovedEmailPanel'
import { FormApprovalPreparationPanel } from './FormApprovalPreparationPanel'
import { FormAdapterPlanDetails } from './FormAdapterPlanDetails'
import { CF7CandidatePreparationPanel } from './CF7CandidatePreparationPanel'
import { CF7CandidateDetails } from './CF7CandidateDetails'
import { ApprovedFormPanel } from './ApprovedFormPanel'
import type { Company, Project, ProjectMember } from './types'

interface AuditEvent { id: string; event: string; principal_type: string; timestamp: string; reason: string | null }
const names: Record<string, string> = { PENDING: '承認待ち', APPROVED: '承認済み（未送信）', REJECTED: '却下', EXPIRED: '期限切れ', REVOKED: '取消済み', CONSUMED: '送信実行に使用済み' }
const date = (value: string) => new Date(value).toLocaleString('ja-JP')
const reasonNames: Record<string, string> = {
  "company target changed": "対象企業・宛先情報が変わりました。最新の窓口で再準備してください。",
  "form profile or mapping changed": "フォーム構造・入力項目が変わりました。解析と入力値を再確認してください。",
  "form sender settings changed": "フォーム送信者設定が変わりました。新しい設定で再準備してください。",
  "source draft changed": "元の文面が変わりました。新しい内容で再準備してください。",
  "lead completion evidence, destination or sender changed": "下書き・根拠・窓口・送信者が変更または無効になりました。最新の情報で再準備してください。",
  'CF7 candidate evidence or payload changed': '保存済み証拠・文面・送信者・連絡可否のいずれかが変更または無効になりました。確認して再準備してください。',
  'CF7 real candidate evidence or payload changed': '実サイトの入力確認・フォーム証拠・文面・送信者・連絡可否が変更または失効しました。企業詳細から再準備してください。',
  'superseded by CF7 revision': '改訂候補を作成したため、旧候補を無効にしました。',
  'request expired': '候補の有効期限が切れました。新しい有効な証拠で再準備してください。',
}

export function ApprovalQueuePage({ projects, projectRoles }: {
  projects: Project[]; projectRoles: Record<string, ProjectMember['role']>
}) {
  const [projectId, setProjectId] = useState(projects[0]?.id ?? '')
  const [items, setItems] = useState<Proposal[]>([])
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [companies, setCompanies] = useState<Company[]>([])
  const [selected, setSelected] = useState<Proposal | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [password, setPassword] = useState('')
  const [reason, setReason] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [companyId, setCompanyId] = useState('')
  const [channel, setChannel] = useState<'email' | 'form'>('email')
  const [target, setTarget] = useState('')
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [senderName, setSenderName] = useState('')
  const [senderEmail, setSenderEmail] = useState('')
  const [fieldValues, setFieldValues] = useState('{}')
  const [offset, setOffset] = useState(0)
  const [cf7Reviewed, setCf7Reviewed] = useState(false)
  useEffect(() => { setCf7Reviewed(false) }, [selected?.id, selected?.payload_hash, selected?.status])
  const canWrite = ['owner', 'editor'].includes(projectRoles[projectId] ?? '')
  useEffect(() => {
    if (!projectId) return
    let live = true
    setError(''); setSelected(null); setPassword(''); setReason('')
    Promise.all([
      api<Proposal[]>(`/projects/${projectId}/approval-requests?limit=50&offset=${offset}`),
      api<AuditEvent[]>(`/projects/${projectId}/approval-audit?limit=100`),
    ]).then(([next, ledger]) => { if (live) { setItems(next); setEvents(ledger) } })
      .catch(e => { if (live) setError(errorMessage(e)) })
    return () => { live = false }
  }, [projectId, offset])
  async function refresh() {
    const [next, ledger] = await Promise.all([
      api<Proposal[]>(`/projects/${projectId}/approval-requests?limit=50&offset=${offset}`),
      api<AuditEvent[]>(`/projects/${projectId}/approval-audit?limit=100`),
    ])
    setItems(next); setEvents(ledger)
    if (selected) setSelected(next.find(item => item.id === selected.id) ?? null)
  }
  async function act(fn: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try { await fn() } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false); setPassword('') }
  }
  async function approve() {
    if (!selected) return
    await act(async () => {
      const expected = { expected_hash: selected.payload_hash, expected_version: selected.payload_version }
      try {
        const challenge = await api<{ challenge_token: string }>(`/approval-requests/${selected.id}/challenge`, 'POST', expected)
        await api(`/approval-requests/${selected.id}/challenge/verify`, 'POST', { challenge_token: challenge.challenge_token, password })
        await api(`/approval-requests/${selected.id}/approve`, 'POST', { ...expected, challenge_token: challenge.challenge_token })
      } catch (e) { await refresh().catch(() => {}); throw e }
      setNotice('承認を記録しました。送信は行っていません。'); await refresh()
    })
  }
  async function decide(action: 'reject' | 'revoke') {
    if (!selected) return
    await act(async () => {
      await api(`/approval-requests/${selected.id}/${action}`, 'POST', {
        expected_hash: selected.payload_hash, expected_version: selected.payload_version, reason,
      })
      setNotice(action === 'reject' ? '提案を却下しました。' : '承認・提案を取り消しました。'); await refresh()
    })
  }
  async function openCreate() {
    await act(async () => {
      const result = await api<{ items: Company[] }>(`/projects/${projectId}/company-list?limit=100`)
      setCompanies(result.items); setCompanyId(result.items[0]?.id ?? ''); setCreateOpen(true)
    })
  }
  async function create(event: FormEvent) {
    event.preventDefault()
    await act(async () => {
      const fields: unknown = JSON.parse(fieldValues)
      if (!fields || typeof fields !== 'object' || Array.isArray(fields) || Object.values(fields).some(v => typeof v !== 'string')) throw new Error('フィールド値は文字列のJSONオブジェクトで入力してください。')
      await api(`/projects/${projectId}/approval-requests`, 'POST', {
        company_id: companyId, channel, delivery_method: channel === 'email' ? 'email' : 'form_direct',
        recipient: channel === 'email' ? target : null, form_url: channel === 'form' ? target : null,
        subject, body, sender: { name: senderName, email: senderEmail }, field_values: fields,
      })
      setCreateOpen(false); setNotice('承認待ちの提案を作成しました。'); await refresh()
    })
  }
  return <section className="space-y-6">
    <p className="muted">提案の宛先と内容を確認し、ログインパスワードで再認証して承認してください。承認だけでは送信しません。承認済みメールは別操作で予約でき、実行設定が有効な場合だけワーカーが送信します。承認の有効期限は作成から最大24時間です。</p>
    <Field label="承認プロジェクト"><select value={projectId} onChange={e => { setProjectId(e.target.value); setOffset(0); setCreateOpen(false); setNotice('') }}>
      {projects.map(project => <option key={project.id} value={project.id}>{project.project_name}</option>)}
    </select></Field>
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    <ApprovedEmailPanel key={projectId} projectId={projectId} items={items} canWrite={canWrite} refresh={refresh} />
    <ApprovedFormPanel key={`form-dispatch-${projectId}`} projectId={projectId} items={items} canWrite={canWrite} refresh={refresh} />
    {canWrite && <FormApprovalPreparationPanel key={`form-${projectId}`} projectId={projectId} refresh={refresh} />}
    {canWrite && <CF7CandidatePreparationPanel key={`cf7-${projectId}`} projectId={projectId} refresh={refresh} />}
    <fieldset disabled={busy || !projectId}>
      <div className="flex flex-wrap gap-3"><button type="button" className="secondary" onClick={() => act(refresh)}>最新の状態を取得</button>
        {canWrite && <button type="button" onClick={openCreate}>承認待ち提案を作成</button>}</div>
      {createOpen && canWrite && <form onSubmit={create} className="panel mt-4">
        <h2>新しい提案（送信しません）</h2>
        <Field label="提案先の会社"><select required value={companyId} onChange={e => setCompanyId(e.target.value)}>{companies.map(company => <option key={company.id} value={company.id}>{company.company_name}</option>)}</select></Field>
        <Field label="チャネル"><select value={channel} onChange={e => { setChannel(e.target.value as 'email' | 'form'); setTarget('') }}><option value="email">メール</option><option value="form">フォーム</option></select></Field>
        <Field label={channel === 'email' ? '宛先メール' : 'フォームURL'}><input required type={channel === 'email' ? 'email' : 'url'} value={target} onChange={e => setTarget(e.target.value)} /></Field>
        <Field label="送信者名"><input required value={senderName} onChange={e => setSenderName(e.target.value)} /></Field>
        <Field label="送信者メール"><input required type="email" value={senderEmail} onChange={e => setSenderEmail(e.target.value)} /></Field>
        <Field label="件名"><input value={subject} onChange={e => setSubject(e.target.value)} /></Field>
        <Field label="本文"><textarea required value={body} onChange={e => setBody(e.target.value)} /></Field>
        {channel === 'form' && <Field label="フォーム入力値（JSON）"><textarea value={fieldValues} onChange={e => setFieldValues(e.target.value)} /></Field>}
        <button type="submit" disabled={!companyId}>提案を保存</button> <button type="button" className="secondary" onClick={() => setCreateOpen(false)}>閉じる</button>
      </form>}
      <div className="panel mt-4"><h2>Human Approval Queue</h2>
        {!items.length && <p>このページに承認提案はありません。</p>}
        <ul>{items.map(item => <li key={item.id}><button type="button" className="secondary my-2" onClick={() => { setSelected(item); setPassword(''); setReason('') }}>{item.company_name} · {item.channel} · v{item.payload_version} · {names[item.status] ?? item.status}</button></li>)}</ul>
        <button type="button" className="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>前の50件</button>{' '}
        <button type="button" className="secondary" disabled={items.length < 50} onClick={() => setOffset(offset + 50)}>次の50件</button>
      </div>
      {selected && <article className="panel mt-4">
        <h2>{selected.company_name} の提案内容</h2>
        {selected.delivery_method === 'cf7_candidate_only' && <p role="status">CF7候補内容の承認のみです。送信予約・実送信には使用できません。</p>}
        {selected.delivery_method === 'cf7_real_candidate_only' && <section aria-label="実サイトCF7候補の承認資料">
          <p role="status">実サイトCF7候補内容の承認です。承認後も送信予約・実送信には使用できません。</p>
          {selected.cf7_real_handoff ? <>
            <p>版別契約：{selected.cf7_real_handoff.snapshot.contract.contract_family} / 変換データ：{selected.cf7_real_handoff.snapshot.encoding.wire_size.toLocaleString('ja-JP')} bytes</p>
            <p>入力確認日時：{date(selected.cf7_real_handoff.snapshot.input_review.reviewed_at)} / 証拠期限：{date(selected.cf7_real_handoff.snapshot.expires_at)}</p>
            <p className="break-all">引き継ぎhash：{selected.cf7_real_handoff.snapshot_hash}</p>
          </> : <p role="alert">確認資料を表示できません。最新状態を取得してください。</p>}
        </section>}
        {selected.delivery_method === 'cf7_candidate_only' && <>
          {selected.cf7_candidate_snapshot ? <CF7CandidateDetails snapshot={selected.cf7_candidate_snapshot} hash={selected.cf7_candidate_snapshot_hash} observation={selected.cf7_observation} />
            : <p role="alert">候補証拠を表示できません。最新の状態を取得してください。</p>}
          <p className="break-all">履歴ID: {selected.proposal_id} / 改訂元: {selected.supersedes_request_id || '初版'}</p>
          {['EXPIRED', 'REVOKED', 'REJECTED'].includes(selected.status) && <p>この候補は承認に使えません。証拠・Draft・送信者・連絡禁止状態を確認し、改訂候補を再準備してください。新たな再認証・承認が必要です。</p>}
        </>}
        <dl><dt>チャネル / 状態</dt><dd>{selected.channel} / {names[selected.status]}</dd>
          <dt>宛先 / フォームURL</dt><dd className="break-all">{selected.recipient ?? selected.form_url}</dd>
          {selected.channel === 'form' && <><dt>POST先</dt><dd className="break-all">{selected.form_action_url || '未確定・再解析が必要'}</dd></>}
          <dt>送信者</dt><dd>{Object.entries(selected.sender).filter(([, v]) => v).map(([k, v]) => <div key={k}>{k}: {v}</div>)}</dd>
          {selected.lead_dm_evidence && <><dt>個別情報の根拠（Human確認記録）</dt><dd><p>{selected.lead_dm_evidence.evidence.fact}</p><a href={selected.lead_dm_evidence.evidence.source_url} target="_blank" rel="noreferrer">{selected.lead_dm_evidence.evidence.source_url}</a><blockquote>{selected.lead_dm_evidence.evidence.evidence_excerpt}</blockquote><p>窓口選択版 {selected.lead_dm_evidence.choice_version} / 確認日時 {date(selected.lead_dm_evidence.evidence.observed_at)}</p></dd></>}
          <dt>件名</dt><dd>{selected.subject}</dd><dt>本文</dt><dd className="whitespace-pre-wrap break-words">{selected.body}</dd>
          <dt>フィールド値</dt><dd>{Object.entries(selected.field_values).map(([k, v]) => <div key={k}>{k}: {v}</div>)}</dd>
          {selected.execution_plan && <><dt>検証用の操作計画（送信不可）</dt><dd><p>匿名フォームの計画を承認します。送信予約・実行には使用できません。</p><pre className="whitespace-pre-wrap break-all">{JSON.stringify(selected.execution_plan, null, 2)}</pre></dd><dt>操作計画hash</dt><dd className="break-all">{selected.execution_plan_hash}</dd></>}
          {selected.adapter_plan && <><dt>予約用の操作計画</dt><dd><FormAdapterPlanDetails plan={selected.adapter_plan} hash={selected.adapter_plan_hash} /></dd></>}
          <dt>提案者</dt><dd>{selected.created_by_principal_type === 'AGENT' ? 'Agent' : 'Human'}</dd>
          <dt>作成 / 有効期限</dt><dd>{date(selected.created_at)} / {date(selected.expires_at)}</dd>
          <dt>payload version / hash</dt><dd className="break-all">{selected.payload_version} / {selected.payload_hash}</dd>
          {(selected.rejection_reason || selected.invalidation_reason) && <><dt>理由</dt><dd>{reasonNames[selected.rejection_reason || selected.invalidation_reason || ''] || selected.rejection_reason || selected.invalidation_reason}</dd></>}
        </dl>
        {canWrite && selected.status === 'PENDING' && <form onSubmit={e => { e.preventDefault(); void approve() }}>
          <Field label="承認用パスワード（再認証）"><input type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} /></Field>
          {selected.delivery_method === 'cf7_candidate_only' && <label><input type="checkbox" checked={cf7Reviewed} onChange={e => setCf7Reviewed(e.target.checked)} /> CF7の入力値・同意・証拠期限を確認しました</label>}
          {selected.delivery_method === 'cf7_real_candidate_only' && <label><input type="checkbox" checked={cf7Reviewed} onChange={e => setCf7Reviewed(e.target.checked)} /> 実サイトの宛先・入力内容・証拠期限を確認しました（送信不可）</label>}
          <button type="submit" disabled={selected.delivery_method === 'cf7_candidate_only' && (!cf7Reviewed || !selected.cf7_candidate_snapshot || !selected.cf7_observation) || selected.delivery_method === 'cf7_real_candidate_only' && (!cf7Reviewed || !selected.cf7_real_handoff)}>{['cf7_candidate_only', 'cf7_real_candidate_only'].includes(selected.delivery_method ?? '') ? 'CF7候補内容を承認（送信不可）' : '内容を確認して承認'}</button>
        </form>}
        {canWrite && ['PENDING', 'APPROVED'].includes(selected.status) && <div className="mt-4">
          <Field label="却下・取消の理由"><input maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} /></Field>
          {selected.status === 'PENDING' && <button type="button" className="secondary" disabled={!reason.trim()} onClick={() => decide('reject')}>却下</button>}{' '}
          <button type="button" className="secondary" disabled={!reason.trim()} onClick={() => decide('revoke')}>取消</button>
        </div>}
        {canWrite && selected.delivery_method === 'cf7_candidate_only' && <CF7CandidatePreparationPanel key={`cf7-revision-${selected.id}`} projectId={projectId} refresh={refresh} revision={selected} />}
      </article>}
    </fieldset>
    <details className="panel"><summary>監査記録（最新100件）</summary><ul>{events.map(event => <li key={event.id}>{date(event.timestamp)} · {event.principal_type} · {event.event} · {event.reason}</li>)}</ul></details>
  </section>
}
