import { useEffect, useRef, useState } from 'react'
import { api, errorMessage } from './api'
import { Field } from './forms'
import type { Company, OutreachDraft } from './types'
import type { ApprovalProposal } from './ApprovedEmailPanel'
import { CF7CandidateDetails, type CF7Control, type CF7Snapshot } from './CF7CandidateDetails'

interface Preview {
  preparation_hash: string | null; required_selections?: CF7Control[]
  cf7_candidate_snapshot?: CF7Snapshot; company_name: string
  cf7_candidate_snapshot_hash?: string
  observed_at: string; expires_at: string; observation_hash: string
}
export function CF7CandidatePreparationPanel({ projectId, refresh, revision }: {
  projectId: string; refresh: () => Promise<void>; revision?: ApprovalProposal
}) {
  const [enabled, setEnabled] = useState(false)
  const [companies, setCompanies] = useState<Company[]>([])
  const [drafts, setDrafts] = useState<OutreachDraft[]>([])
  const [companyId, setCompanyId] = useState('')
  const [draftId, setDraftId] = useState(revision?.source_draft_id ?? '')
  const [offset, setOffset] = useState(0)
  const [controls, setControls] = useState<CF7Control[]>([])
  const [choices, setChoices] = useState<Record<string, boolean>>({})
  const [preview, setPreview] = useState<Preview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [reviewed, setReviewed] = useState(false)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    api<{ enabled: boolean }>('/cf7-candidate-preparation-status')
      .then(v => { if (alive.current) setEnabled(v.enabled) }).catch(() => { if (alive.current) setEnabled(false) })
    return () => { alive.current = false }
  }, [])
  const base = revision ? `/approval-requests/${revision.id}/cf7-revision-preview` : `/outreach-drafts/${draftId}/cf7-candidate-preview`
  const expected = revision ? { expected_hash: revision.payload_hash, expected_version: revision.payload_version } : {}
  const selections = controls.map(c => ({ name: c.name, checked: choices[c.name] === true }))
  function clear() { setPreview(null); setControls([]); setChoices({}); setReviewed(false) }
  async function act(fn: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try { await fn() } catch (e) { if (alive.current) { setError(`${errorMessage(e)} 最新の証拠・文面を取得し直してください。`); clear() } }
    finally { if (alive.current) setBusy(false) }
  }
  async function loadCompanies(next: number) {
    clear(); setCompanyId(''); setDraftId(''); setDrafts([])
    await act(async () => {
      const result = await api<{ items: Company[] }>(`/projects/${projectId}/company-list?limit=100&offset=${next}`)
      if (alive.current) { setCompanies(result.items); setOffset(next) }
    })
  }
  async function chooseCompany(id: string) {
    clear(); setCompanyId(id); setDraftId(''); setDrafts([])
    if (!id) return
    await act(async () => {
      const result = await api<OutreachDraft[]>(`/companies/${id}/outreach-drafts`)
      if (alive.current) setDrafts(result.filter(d => d.channel === 'form'))
    })
  }
  async function loadEvidence() {
    clear()
    await act(async () => {
      const result = await api<Preview>(base)
      if (!alive.current) return
      setControls(result.required_selections ?? result.cf7_candidate_snapshot?.contract.controls.filter(c => c.kind === 'checkbox') ?? [])
      setPreview(result)
    })
  }
  async function selectedPreview() {
    setReviewed(false)
    await act(async () => {
      const result = await api<Preview>(base, 'POST', { selections, ...expected })
      if (alive.current) setPreview(result)
    })
  }
  async function save() {
    if (!preview?.preparation_hash || !reviewed) return
    await act(async () => {
      await api(revision ? `/approval-requests/${revision.id}/cf7-revisions` : `/outreach-drafts/${draftId}/cf7-candidate-request`, 'POST', {
        selections, expected_preparation_hash: preview.preparation_hash, ...expected,
      })
      if (!alive.current) return
      clear(); setNotice('承認待ちに保存しました。最新の候補を選び、再認証して承認してください。送信はできません。')
      await refresh()
    })
  }
  if (!enabled) return null
  return <section className="panel" aria-label={revision ? 'CF7候補の改訂' : 'CF7候補の準備'}>
    <h2>{revision ? 'CF7候補を改訂・再準備' : 'CF7候補を準備（送信不可）'}</h2>
    <p>検証環境専用です。企業サイトへのアクセス・送信・予約は行いません。</p>
    {revision && <p>文面・送信者の変更は元のDraft・設定で行ってください。旧承認は引き継がず、同意も選び直します。</p>}
    {error && <p role="alert" className="error">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    <fieldset disabled={busy || !projectId}>
      {!revision && <>
        <button type="button" onClick={() => loadCompanies(0)}>CF7候補の会社を選ぶ</button>
        <Field label="CF7候補の会社"><select value={companyId} onChange={e => chooseCompany(e.target.value)}>
          <option value="">選択してください</option>{companies.map(c => <option key={c.id} value={c.id}>{c.company_name}</option>)}
        </select></Field>
        <button type="button" className="secondary" disabled={offset === 0} onClick={() => loadCompanies(Math.max(0, offset - 100))}>CF7 前の100社</button>{' '}
        <button type="button" className="secondary" disabled={companies.length < 100} onClick={() => loadCompanies(offset + 100)}>CF7 次の100社</button>
        <Field label="CF7フォームDraft"><select value={draftId} onChange={e => { setDraftId(e.target.value); clear() }}>
          <option value="">選択してください</option>{drafts.map(d => <option key={d.id} value={d.id}>{d.subject || '件名なし'}</option>)}
        </select></Field>
        {companyId && !drafts.length && <p>フォーム用Draftがありません。企業一覧で文面を保存してください。</p>}
      </>}
      <button type="button" disabled={!draftId} onClick={loadEvidence}>CF7証拠・同意欄を取得</button>
      {preview && <>
        <p>証拠期限: {new Date(preview.expires_at).toLocaleString('ja-JP')}</p>
        {controls.map(c => <Field key={c.name} label={`${c.label}${c.required ? '（必須）' : '（任意）'}`}>
          <select value={choices[c.name] === undefined ? '' : String(choices[c.name])} onChange={e => {
            const value = e.target.value
            setChoices(old => { const next = { ...old }; if (!value) delete next[c.name]; else next[c.name] = value === 'true'; return next })
            setPreview(old => old ? { ...old, preparation_hash: null, cf7_candidate_snapshot: undefined } : null); setReviewed(false)
          }}><option value="">選択してください</option><option value="true">選択する</option><option value="false">選択しない</option></select>
        </Field>)}
        <button type="button" disabled={controls.some(c => choices[c.name] === undefined || (c.required && !choices[c.name]))} onClick={selectedPreview}>CF7選択済み内容を確認</button>
        {preview.cf7_candidate_snapshot && preview.preparation_hash && <>
          <CF7CandidateDetails snapshot={preview.cf7_candidate_snapshot} hash={preview.cf7_candidate_snapshot_hash} observation={{ observed_at: preview.observed_at, expires_at: preview.expires_at, evidence_hash: preview.observation_hash }} />
          <p className="break-all">準備hash: {preview.preparation_hash}</p>
          <label><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)} /> 入力値・同意・期限を確認しました（送信不可）</label>
          <button type="button" disabled={!reviewed} onClick={save}>{revision ? 'CF7改訂候補を承認待ちに保存' : 'CF7候補を承認待ちに保存'}</button>
        </>}
      </>}
    </fieldset>
  </section>
}
