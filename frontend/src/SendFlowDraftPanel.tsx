import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import type { Company, CompanyPage, OperationJob, OutreachTemplate } from './types'
import { SalesPreparationPanel } from './SalesPreparationPanel'
import { FormDmReadinessPanel } from './FormDmReadinessPanel'

type BulkResults = { created: string[]; skipped_existing: string[]; excluded: { company_id: string; reason_code: string; reason?: string }[] }
type BulkJob = OperationJob & { bulk_template_results?: BulkResults }
const exclusionLabels: Record<string, string> = {
  company_not_found: '企業が見つかりません', form_profile_missing: 'フォーム解析結果なし',
  form_profile_changed: 'フォーム情報が変更済み', company_do_not_contact: '連絡禁止',
  suppression_email: 'メール抑止', suppression_domain: 'ドメイン抑止',
  suppression_phone: '電話番号抑止', destination_missing: '送信先なし',
  form_sales_prohibited: 'フォームでの営業禁止', rendered_content_too_long: '本文が長すぎます',
  non_company_suspected: '非企業の疑い',
}

export function SendFlowDraftPanel({ projectId, channel, canWrite, onNeedTemplate, onCreated, onNext }: {
  projectId: string; channel: 'email' | 'form'; canWrite: boolean
  onNeedTemplate: (templateId?: string) => void; onCreated: (channel: 'email' | 'form') => void; onNext: () => void
}) {
  const [showAi, setShowAi] = useState(false)
  const [templates, setTemplates] = useState<OutreachTemplate[]>([])
  const [templateId, setTemplateId] = useState('')
  const [companies, setCompanies] = useState<Company[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [selectEligibleEmailCompanies, setSelectEligibleEmailCompanies] = useState(false)
  const [formTargetCount, setFormTargetCount] = useState<number | null>(null)
  const [readinessDetailsOpen, setReadinessDetailsOpen] = useState(false)
  const [job, setJob] = useState<BulkJob | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const filteredTemplates = templates.filter(template => template.channel === channel)
  const activeJob = Boolean(job && ['queued', 'running'].includes(job.status))
  const jobId = job?.id
  const jobStatus = job?.status

  useEffect(() => {
    let live = true
    Promise.all([
      api<OutreachTemplate[]>(`/projects/${projectId}/outreach-templates`),
      api<CompanyPage>(`/projects/${projectId}/company-list?offset=${offset}&limit=20&sort=company_name`),
      api<{ counts: Record<string, number> }>(`/projects/${projectId}/form-dm-readiness`),
    ]).then(([nextTemplates, page, readiness]) => {
      if (!live) return
      setTemplates(nextTemplates); setCompanies(page.items); setTotal(page.total)
      setFormTargetCount(readiness.counts.NO_FORM_DRAFT ?? 0)
      setTemplateId(current => current && nextTemplates.some(item => item.id === current && item.channel === channel)
        ? current : nextTemplates.find(item => item.channel === channel)?.id ?? '')
    }).catch(e => { if (live) setError(errorMessage(e)) })
    return () => { live = false }
  }, [channel, offset, projectId])

  useEffect(() => {
    if (!jobId || !['queued', 'running'].includes(jobStatus ?? '')) return
    const timer = window.setInterval(() => {
      api<OperationJob[]>(`/projects/${projectId}/operations?limit=100`).then(rows => {
        const current = rows.find(row => row.id === jobId) as BulkJob | undefined
        if (!current) return
        setJob(current)
        if (['completed', 'failed', 'cancelled'].includes(current.status)) {
          setNotice(current.status === 'completed' ? '一括下書き作成が完了しました。送信可否を再集計します。' : '一括下書き作成が完了しませんでした。進捗を確認してください。')
          onCreated(channel)
        }
      }).catch(e => setError(errorMessage(e)))
    }, 1800)
    return () => window.clearInterval(timer)
  }, [channel, jobId, jobStatus, onCreated, projectId])

  async function createDrafts() {
    if (!canWrite || !templateId || activeJob || (channel === 'email' && !selectedIds.length && !selectEligibleEmailCompanies)) return
    setBusy(true); setError(''); setNotice(''); setJob(null)
    try {
      const createdJob = await api<BulkJob>(`/projects/${projectId}/outreach-drafts/bulk-from-template`, 'POST', {
        template_id: templateId, channel,
        ...(channel === 'form' ? { readiness_reason: 'NO_FORM_DRAFT' } : selectEligibleEmailCompanies
          ? { readiness_reason: 'NO_EMAIL_DRAFT' } : { company_ids: selectedIds }),
      })
      setJob(createdJob)
      if (createdJob.status === 'completed') {
        setNotice('一括下書き作成が完了しました。送信可否を再集計します。')
        onCreated(channel)
      } else if (createdJob.status === 'queued' || createdJob.status === 'running') {
        setNotice('バックグラウンドで下書きを作成しています。')
      } else {
        setError(createdJob.error_message || 'ジョブを開始できませんでした。')
      }
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }

  const results = job?.bulk_template_results
  const exclusionCounts = Object.entries((results?.excluded ?? []).reduce<Record<string, number>>((counts, item) => {
    counts[item.reason_code] = (counts[item.reason_code] ?? 0) + 1
    return counts
  }, {}))

  return <section className="space-y-4" aria-label="送信先と文面の準備">
    {!showAi && <>
      <p className="muted text-sm">テンプレートから下書きだけを作成します。AI・承認・予約・送信は行いません。既存Draftは上書きせずスキップします。</p>
      <label className="field">使用するテンプレート<select disabled={activeJob} value={templateId} onChange={event => setTemplateId(event.target.value)}><option value="">選択してください</option>{filteredTemplates.map(template => <option key={template.id} value={template.id}>{template.name}</option>)}</select></label>
      {!filteredTemplates.length && <p className="panel">{channel === 'email' ? 'メール用' : 'フォーム用'}テンプレートがありません。<button type="button" className="secondary ml-2" onClick={() => onNeedTemplate()}>テンプレートを作る</button></p>}
      {!!filteredTemplates.length && <button type="button" className="secondary" disabled={activeJob} onClick={() => onNeedTemplate(templateId)}>選択中のテンプレートを編集</button>}
      {channel === 'email' ? <>
        <p>連絡先メールがあり、連絡禁止ではなく、メール下書きがない会社を対象にします（最大500社）。表示 {companies.length} / {total}社 · 手動選択 {selectedIds.length} / 500社</p>
        <div className="actions"><button type="button" className="secondary" aria-pressed={selectEligibleEmailCompanies} disabled={!canWrite || activeJob} onClick={() => { setSelectEligibleEmailCompanies(true); setSelectedIds([]) }}>条件に合う会社をすべて選択（最大500社）</button></div>
        {selectEligibleEmailCompanies && <p role="status" className="muted text-sm">下書き作成時にサーバーが条件に合う会社を最大500社選択します。</p>}
        <div className="border rounded-lg divide-y">
          {companies.map(company => {
            const eligible = Boolean(company.email?.trim()) && !company.do_not_contact
            const selected = selectedIds.includes(company.id)
            return <label key={company.id} className="flex items-start gap-3 p-3">
              <input type="checkbox" disabled={!canWrite || !eligible || activeJob || selectEligibleEmailCompanies || (!selected && selectedIds.length >= 500)} checked={selected} onChange={() => { setSelectEligibleEmailCompanies(false); setSelectedIds(current => selected ? current.filter(id => id !== company.id) : [...current, company.id]) }} />
              <span><strong>{company.company_name}</strong><span className="block muted text-sm">{company.email || 'メール未登録'}{company.do_not_contact ? ' · 連絡禁止' : ''}</span></span>
            </label>
          })}
        </div>
        <div className="actions mt-2"><button type="button" className="secondary" disabled={offset === 0 || activeJob} onClick={() => setOffset(value => Math.max(0, value - 20))}>前の20社</button><span>{total ? `${Math.floor(offset / 20) + 1} / ${Math.ceil(total / 20)}` : '0社'}</span><button type="button" className="secondary" disabled={offset + companies.length >= total || activeJob} onClick={() => setOffset(value => value + 20)}>次の20社</button></div>
      </> : <div className="rounded-lg border p-4"><strong>送信可否：フォーム文面なし</strong><p className="muted mt-2">最新の集計で「フォーム文面なし」と判定された企業から、最大500社を対象にします。集計対象 {formTargetCount ?? '…'}社。</p></div>}
      {error && <p role="alert" className="error">{error}</p>}{notice && <p role="status">{notice}</p>}
      {job && <div className="rounded-lg border p-4" role="status" aria-label="一括作成の進捗">
        <strong>{job.status === 'completed' ? '作成完了' : job.status === 'failed' ? '失敗' : job.status === 'cancelled' ? '停止' : '作成中'} · {job.processed_count}/{job.total_count}社</strong>
        {!!results && <><p className="mt-2">作成 {results.created.length}社 · 既存のためスキップ {results.skipped_existing.length}社 · 対象外 {results.excluded.length}社</p>
          {!!results.excluded.length && <details className="mt-2"><summary>対象外の理由を見る</summary>
            {exclusionCounts.map(([reason, count]) => <p className="muted text-sm" key={reason}>{exclusionLabels[reason] ?? reason}: {count}社</p>)}
            {results.excluded.slice(0, 10).map(item => <p className="muted text-xs" key={item.company_id}>{item.reason || exclusionLabels[item.reason_code] || item.reason_code}</p>)}
          </details>}
        </>}
      </div>}
      <div className="actions flex-wrap">
        <button disabled={!canWrite || busy || activeJob || !templateId || (channel === 'email' && !selectedIds.length && !selectEligibleEmailCompanies) || (channel === 'form' && !formTargetCount)} onClick={() => void createDrafts()}>{busy ? '登録中…' : activeJob ? 'バックグラウンド処理中…' : channel === 'form' ? `フォーム下書きを一括作成（最大${Math.min(formTargetCount ?? 0, 500)}社）` : selectEligibleEmailCompanies ? '条件一致企業に下書きを作成（最大500社）' : `選択した${selectedIds.length}社に下書きを作成`}</button>
        {job?.status === 'completed' && <button type="button" className="secondary" onClick={onNext}>{channel === 'form' ? '次へ：フォームを確認' : '次へ：承認して送る'}</button>}
      </div>
      <details className="mt-4" onToggle={event => setReadinessDetailsOpen(event.currentTarget.open)}><summary>フォームの送信可否集計・詳細</summary>{readinessDetailsOpen && <div className="mt-4"><p className="muted text-sm mb-3">フォーム文面なしの一括作成対象と、送信可否の理由を確認できます。</p><FormDmReadinessPanel projectId={projectId} canWrite={canWrite} /></div>}</details>
    </>}
    <details className="mt-4" open={showAi} onToggle={event => setShowAi(event.currentTarget.open)}>
      <summary>AIで会社ごとに文面を作成</summary>
      {showAi && <div className="mt-4"><SalesPreparationPanel key={`ai-preparation-${projectId}-${channel}`} projectId={projectId} fixedChannel={channel} /></div>}
    </details>
    {!canWrite && <p className="muted">閲覧のみです。下書き作成は所有者または編集者が行えます。</p>}
  </section>
}
