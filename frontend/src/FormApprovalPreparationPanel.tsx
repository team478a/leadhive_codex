import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import { Field } from './forms'
import type { Company, OutreachDraft } from './types'
import { FormAdapterPlanDetails } from './FormAdapterPlanDetails'

interface Preview {
  preparation_hash: string; company_name: string
  proposal: { form_url: string; form_action_url?: string; subject: string; body: string; sender: Record<string, string>; adapter_plan?: Record<string, unknown> | null }
  adapter_plan_hash?: string
  fields: { name: string; label: string; required: boolean; value: string }[]
}

export function FormApprovalPreparationPanel({ projectId, refresh }: {
  projectId: string; refresh: () => Promise<void>
}) {
  const [companies, setCompanies] = useState<Company[]>([])
  const [drafts, setDrafts] = useState<OutreachDraft[]>([])
  const [companyId, setCompanyId] = useState('')
  const [draftId, setDraftId] = useState('')
  const [preview, setPreview] = useState<Preview | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [offset, setOffset] = useState(0)
  const [opened, setOpened] = useState(false)
  const [mode, setMode] = useState<'direct' | 'adapter'>('direct')
  const [adapterEnabled, setAdapterEnabled] = useState(false)
  useEffect(() => {
    let live = true
    api<{ enabled: boolean }>('/form-adapter-preparation-status')
      .then(result => { if (live) setAdapterEnabled(result.enabled) })
      .catch(() => { if (live) setAdapterEnabled(false) })
    return () => { live = false }
  }, [])
  async function act(fn: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try { await fn() } catch (e) { setError(errorMessage(e)); setPreview(null) }
    finally { setBusy(false) }
  }
  async function loadCompanies(next: number) {
    await act(async () => {
      const result = await api<{ items: Company[] }>(`/projects/${projectId}/company-list?limit=100&offset=${next}`)
      setCompanies(result.items); setOffset(next); setCompanyId(''); setDrafts([])
      setDraftId(''); setPreview(null); setOpened(true)
    })
  }
  async function chooseCompany(id: string) {
    setCompanyId(id); setDrafts([]); setDraftId(''); setPreview(null)
    if (!id) return
    await act(async () => {
      const result = await api<OutreachDraft[]>(`/companies/${id}/outreach-drafts`)
      setDrafts(result.filter(draft => draft.channel === 'form'))
    })
  }
  async function prepare() {
    if (!preview) return
    await act(async () => {
      await api(`/outreach-drafts/${draftId}/form-${mode === 'adapter' ? 'adapter' : 'approval'}-request`, 'POST', {
        expected_preparation_hash: preview.preparation_hash,
      })
      setPreview(null); setNotice('承認待ちに追加しました。下の一覧で内容を確認し、再認証して承認してください。送信は行っていません。')
      await refresh()
    })
  }
  return <article className="panel">
    <h2>フォームDraftから承認候補を準備</h2>
    <p className="muted">保存済みの解析結果と送信者設定を使います。準備・承認では企業サイトへのアクセス・送信は行いません。承認後の送信予約は別操作です。</p>
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    <fieldset disabled={busy || !projectId}>
      {adapterEnabled && <Field label="フォーム準備方式"><select value={mode} onChange={e => { setMode(e.target.value as 'direct' | 'adapter'); setPreview(null) }}>
        <option value="direct">通常フォーム</option>
        <option value="adapter">管理下フォーム・予約のみ（送信不可）</option>
      </select></Field>}
      <button type="button" className="secondary" onClick={() => loadCompanies(0)}>フォーム候補を選ぶ</button>
      {opened && <>
        <Field label="フォーム提案先の会社"><select value={companyId} onChange={e => chooseCompany(e.target.value)}>
          <option value="">選択してください</option>
          {companies.map(company => <option key={company.id} value={company.id}>{company.company_name}</option>)}
        </select></Field>
        <button type="button" className="secondary" disabled={offset === 0} onClick={() => loadCompanies(Math.max(0, offset - 100))}>前の100社</button>{' '}
        <button type="button" className="secondary" disabled={companies.length < 100} onClick={() => loadCompanies(offset + 100)}>次の100社</button>
        {companyId && !drafts.length && <p>フォーム用Draftがありません。企業一覧で営業文面を保存してください。</p>}
        <Field label="フォーム用Draft"><select value={draftId} onChange={e => { setDraftId(e.target.value); setPreview(null) }}>
          <option value="">選択してください</option>
          {drafts.map(draft => <option key={draft.id} value={draft.id}>{draft.subject || '件名なし'}</option>)}
        </select></Field>
        <button type="button" disabled={!draftId} onClick={() => act(async () => {
          setPreview(await api<Preview>(`/outreach-drafts/${draftId}/form-${mode === 'adapter' ? 'adapter' : 'approval'}-preview`))
        })}>保存済みの入力内容を確認</button>
      </>}
      {preview && <section className="mt-4">
        <h3>{preview.company_name} のフォーム提案</h3>
        <p className="break-all">フォームURL: {preview.proposal.form_url}</p>
        <p className="break-all">POST先: {preview.proposal.form_action_url || '未確定'}</p>
        <p>送信者: {Object.values(preview.proposal.sender).filter(Boolean).join(' / ')}</p>
        <p>件名: {preview.proposal.subject}</p>
        <p className="whitespace-pre-wrap break-words">{preview.proposal.body}</p>
        {preview.proposal.adapter_plan && <FormAdapterPlanDetails plan={preview.proposal.adapter_plan} hash={preview.adapter_plan_hash} />}
        <dl>{preview.fields.map(field => <div key={field.name}>
          <dt>{field.label}{field.required ? '（必須）' : ''}</dt>
          <dd className="whitespace-pre-wrap break-words">{field.value || '未入力'}</dd>
        </div>)}</dl>
        <p className="muted">変更は送信者設定・Draft・フォーム解析で行い、再取得してください。</p>
        <button type="button" onClick={prepare}>フォーム提案を承認待ちに追加</button>
      </section>}
    </fieldset>
  </article>
}
