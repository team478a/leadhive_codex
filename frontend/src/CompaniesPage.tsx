import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, download, errorMessage } from './api'
import { CompanyContactsPanel } from './CompanyContactsPanel'
import { CompanyFilters } from './CompanyFilters'
import { CompanyList } from './CompanyList'
import { AssigneeAnalyticsPanel, DealPipelinePanel } from './CompanyReportingPanels'
import { CompanyQualityPanels } from './CompanyQualityPanels'
import { channelNames, companyQueryString, defaultCompanyFilters, dueNames, emptyContact, statusNames } from './companyPageShared'
import type { Activity, AiReview, Deal, DealPipeline, EmailCampaign, FormCodexTask, FormDeliveryBatch, OutreachExperiment, OutreachExperimentResult, AnalysisRefreshSchedule, AssigneeAnalytics, Company, CompanyFilterValues, CompanyPage, ContactPerson, DataQuality, DuplicateCandidate, EmailDelivery, FollowupTask, FormAssist, FormDelivery, FormPreview, OperationJob, OutreachChannel, OutreachDraft, OutreachDraftApproval, OutreachQueueItem, OutreachTemplate, Project, ReplyQueueItem, SalesStatus, SavedCompanyFilter } from './types'

type Filters = CompanyFilterValues

export function CompaniesPage({ projects, initialProjectId, initialReplyInboundEmailId, initialFollowupCompanyId }: {
  projects: Project[]
  initialProjectId: string
  initialReplyInboundEmailId: string | null
  initialFollowupCompanyId: string | null
}) {
  const [projectId, setProjectId] = useState(initialProjectId || projects[0]?.id || '')
  const [draft, setDraft] = useState<Filters>(defaultCompanyFilters)
  const [filters, setFilters] = useState<Filters>(defaultCompanyFilters)
  const [companies, setCompanies] = useState<Company[]>([])
  const [total, setTotal] = useState(0)
  const [quality, setQuality] = useState<DataQuality | null>(null)
  const [duplicates, setDuplicates] = useState<DuplicateCandidate[]>([])
  const [savedFilters, setSavedFilters] = useState<SavedCompanyFilter[]>([])
  const [assigneeAnalytics, setAssigneeAnalytics] = useState<AssigneeAnalytics[]>([])
  const [outreachQueue, setOutreachQueue] = useState<OutreachQueueItem[]>([])
  const [followupTasks, setFollowupTasks] = useState<FollowupTask[]>([])
  const [replyQueue, setReplyQueue] = useState<ReplyQueueItem[]>([])
  const [replyTarget, setReplyTarget] = useState<ReplyQueueItem | null>(null)
  const [replyOutcome, setReplyOutcome] = useState<'replied' | 'meeting' | 'won' | 'lost'>('replied')
  const [replyNote, setReplyNote] = useState('')
  const [replyFollowup, setReplyFollowup] = useState('')
  const [followupTarget, setFollowupTarget] = useState<FollowupTask | null>(null)
  const [followupAction, setFollowupAction] = useState<'completed' | 'rescheduled'>('completed')
  const [followupTaskNote, setFollowupTaskNote] = useState('')
  const [followupTaskDate, setFollowupTaskDate] = useState('')
  const [outreachTarget, setOutreachTarget] = useState<OutreachQueueItem | null>(null)
  const [outreachChannel, setOutreachChannel] = useState<OutreachChannel>('email')
  const [outreachOutcome, setOutreachOutcome] = useState<SalesStatus>('approached')
  const [outreachNote, setOutreachNote] = useState('')
  const [outreachFollowup, setOutreachFollowup] = useState('')
  const [filterName, setFilterName] = useState('')
  const [editingFilterId, setEditingFilterId] = useState('')
  const [editingFilterName, setEditingFilterName] = useState('')
  const [staleDays, setStaleDays] = useState(90)
  const [refreshSchedule, setRefreshSchedule] = useState<AnalysisRefreshSchedule | null>(null)
  const [refreshInterval, setRefreshInterval] = useState(168)
  const [refreshStaleDays, setRefreshStaleDays] = useState(90)
  const [refreshBatchLimit, setRefreshBatchLimit] = useState(100)
  const [page, setPage] = useState(0)
  const [checked, setChecked] = useState<string[]>([])
  const [selected, setSelected] = useState<Company | null>(null)
  const [companyEdit, setCompanyEdit] = useState<Record<string, string>>({})
  const [protectedFields, setProtectedFields] = useState<string[]>([])
  const [doNotContact, setDoNotContact] = useState(false)
  const [exclusionReason, setExclusionReason] = useState('')
  const [contactQuality, setContactQuality] = useState<Company['contact_quality_status']>('unknown')
  const [status, setStatus] = useState<SalesStatus>('unreviewed')
  const [notes, setNotes] = useState('')
  const [followup, setFollowup] = useState('')
  const [bulkAssignee, setBulkAssignee] = useState('')
  const [aiReview, setAiReview] = useState<AiReview | null>(null)
  const [aiReviewVerdict, setAiReviewVerdict] = useState<'correct' | 'incorrect'>('correct')
  const [aiReviewNote, setAiReviewNote] = useState('')
  const [deals, setDeals] = useState<Deal[]>([])
  const [dealPipeline, setDealPipeline] = useState<DealPipeline | null>(null)
  const [dealTitle, setDealTitle] = useState('')
  const [dealStage, setDealStage] = useState<Deal['stage']>('lead')
  const [dealAmount, setDealAmount] = useState(0)
  const [dealCloseDate, setDealCloseDate] = useState('')
  const [dealOwner, setDealOwner] = useState('')
  const [dealNextStep, setDealNextStep] = useState('')
  const [dealLostReason, setDealLostReason] = useState('')
  const [experiments, setExperiments] = useState<OutreachExperiment[]>([])
  const [experimentName, setExperimentName] = useState('')
  const [experimentA, setExperimentA] = useState('')
  const [experimentB, setExperimentB] = useState('')
  const [experimentId, setExperimentId] = useState('')
  const [experimentResults, setExperimentResults] = useState<OutreachExperimentResult[]>([])
  const [activities, setActivities] = useState<Activity[]>([])
  const [contacts, setContacts] = useState<ContactPerson[]>([])
  const [outreachDrafts, setOutreachDrafts] = useState<OutreachDraft[]>([])
  const [outreachTemplates, setOutreachTemplates] = useState<OutreachTemplate[]>([])
  const [emailCampaigns, setEmailCampaigns] = useState<EmailCampaign[]>([])
  const [emailCampaignTemplateId, setEmailCampaignTemplateId] = useState('')
  const [emailCampaignName, setEmailCampaignName] = useState('')
  const [emailCampaignFollowupDays, setEmailCampaignFollowupDays] = useState(0)
  const [emailCampaignConfirmed, setEmailCampaignConfirmed] = useState(false)
  const [formBatches, setFormBatches] = useState<FormDeliveryBatch[]>([])
  const [formCodexTasks, setFormCodexTasks] = useState<FormCodexTask[]>([])
  const [formBatchTemplateId, setFormBatchTemplateId] = useState('')
  const [formBatchConfirmed, setFormBatchConfirmed] = useState(false)
  const [draftApprovals, setDraftApprovals] = useState<OutreachDraftApproval[]>([])
  const [templateName, setTemplateName] = useState('')
  const [selectedDraft, setSelectedDraft] = useState<OutreachDraft | null>(null)
  const [emailDelivery, setEmailDelivery] = useState<EmailDelivery | null>(null)
  const [deliveryRecipient, setDeliveryRecipient] = useState('')
  const [deliverySchedule, setDeliverySchedule] = useState('')
  const [deliveryConfirmed, setDeliveryConfirmed] = useState(false)
  const [formPreview, setFormPreview] = useState<FormPreview | null>(null)
  const [formValues, setFormValues] = useState<Record<string, string>>({})
  const [formConfirmed, setFormConfirmed] = useState(false)
  const [formDelivery, setFormDelivery] = useState<FormDelivery | null>(null)
  const [assistOutcome, setAssistOutcome] = useState<FormDelivery['status']>('pending')
  const [assistNote, setAssistNote] = useState('')
  const [assistConfirmed, setAssistConfirmed] = useState(false)
  const [draftChannel, setDraftChannel] = useState<OutreachDraft['channel']>('email')
  const [draftContactId, setDraftContactId] = useState('')
  const [draftInstruction, setDraftInstruction] = useState('')
  const [contactDraft, setContactDraft] = useState<Record<string, string>>(emptyContact)
  const [editingContactId, setEditingContactId] = useState('')
  const [activityType, setActivityType] = useState('note')
  const [activityNote, setActivityNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const openedReplyInboundEmailId = useRef<string | null>(null)
  const openedFollowupCompanyId = useRef<string | null>(null)
  const followupPanelRef = useRef<HTMLDivElement>(null)
  const query = useMemo(() => companyQueryString(filters, page), [filters, page])
  const reload = useCallback(async () => {
    if (!projectId) { setCompanies([]); setSavedFilters([]); setAssigneeAnalytics([]); setOutreachQueue([]); setFollowupTasks([]); setReplyQueue([]); setFormBatches([]); setFormCodexTasks([]); setEmailCampaigns([]); setDealPipeline(null); return }
    const [result, nextQuality, nextDuplicates, nextSavedFilters, nextAssigneeAnalytics, nextOutreachQueue, nextFollowupTasks, nextReplyQueue, nextRefreshSchedule, nextFormBatches, nextOutreachTemplates, nextEmailCampaigns, nextFormCodexTasks, nextDealPipeline] = await Promise.all([
      api<CompanyPage>(`/projects/${projectId}/company-list?${query}`),
      api<DataQuality>(`/projects/${projectId}/data-quality?stale_days=${staleDays}`),
      api<DuplicateCandidate[]>(`/projects/${projectId}/duplicate-candidates`),
      api<SavedCompanyFilter[]>(`/projects/${projectId}/saved-company-filters`),
      api<AssigneeAnalytics[]>(`/projects/${projectId}/assignee-analytics`),
      api<OutreachQueueItem[]>(`/projects/${projectId}/outreach-queue?limit=25`),
      api<FollowupTask[]>(`/projects/${projectId}/followup-tasks?limit=25`),
      api<ReplyQueueItem[]>(`/projects/${projectId}/reply-queue?limit=25`),
      api<AnalysisRefreshSchedule | null>(`/projects/${projectId}/analysis-refresh-schedule`),
      api<FormDeliveryBatch[]>(`/projects/${projectId}/form-delivery-batches`),
      api<OutreachTemplate[]>(`/projects/${projectId}/outreach-templates`),
      api<EmailCampaign[]>(`/projects/${projectId}/email-campaigns`),
      api<FormCodexTask[]>(`/projects/${projectId}/form-codex-queue`),
      api<DealPipeline>(`/projects/${projectId}/deal-pipeline`),
    ])
    setCompanies(result.items); setTotal(result.total); setQuality(nextQuality)
    setDuplicates(nextDuplicates); setSavedFilters(nextSavedFilters)
    setAssigneeAnalytics(nextAssigneeAnalytics); setOutreachQueue(nextOutreachQueue); setFollowupTasks(nextFollowupTasks); setReplyQueue(nextReplyQueue); setChecked([])
    setFormBatches(nextFormBatches); setFormCodexTasks(nextFormCodexTasks); setOutreachTemplates(nextOutreachTemplates); setEmailCampaigns(nextEmailCampaigns); setDealPipeline(nextDealPipeline); setRefreshSchedule(nextRefreshSchedule)
    if (nextRefreshSchedule) {
      setRefreshInterval(nextRefreshSchedule.interval_hours)
      setRefreshStaleDays(nextRefreshSchedule.stale_days)
      setRefreshBatchLimit(nextRefreshSchedule.batch_limit)
    }
  }, [projectId, query, staleDays])
  useEffect(() => { reload().catch(e => setError(errorMessage(e))) }, [reload])
  useEffect(() => {
    if (
      initialReplyInboundEmailId
      && initialReplyInboundEmailId !== openedReplyInboundEmailId.current
    ) {
      const item = replyQueue.find(reply => reply.inbound_email_id === initialReplyInboundEmailId)
      if (item) {
        setReplyTarget(item); setReplyOutcome('replied'); setReplyNote(''); setReplyFollowup('')
        openedReplyInboundEmailId.current = initialReplyInboundEmailId
      }
    }
  }, [initialReplyInboundEmailId, replyQueue])
  useEffect(() => {
    if (
      initialFollowupCompanyId
      && initialFollowupCompanyId !== openedFollowupCompanyId.current
    ) {
      const task = followupTasks.find(item => item.company.id === initialFollowupCompanyId)
      if (task) {
        startFollowupTask(task)
        openedFollowupCompanyId.current = initialFollowupCompanyId
      }
    }
  }, [initialFollowupCompanyId, followupTasks])
  useEffect(() => {
    if (followupTarget) followupPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [followupTarget])
  useEffect(() => {
    if (!selected) {
      setAiReview(null); setDeals([]); setExperiments([]); setExperimentResults([])
      return
    }
    Promise.all([
      api<AiReview | null>(`/companies/${selected.id}/ai-review`),
      api<Deal[]>(`/companies/${selected.id}/deals`),
      api<OutreachExperiment[]>(`/projects/${selected.project_id}/outreach-experiments`),
    ]).then(([review, nextDeals, nextExperiments]) => {
      setAiReview(review); setAiReviewVerdict(review?.verdict ?? 'correct'); setAiReviewNote(review?.note ?? '')
      setDeals(nextDeals); setExperiments(nextExperiments)
    }).catch(e => setError(errorMessage(e)))
  }, [selected])
  async function open(company: Company) {
    setSelected(company); setStatus(company.status); setNotes(company.notes); setNotice('')
    setCompanyEdit(Object.fromEntries([
      'company_name', 'address', 'prefecture', 'city', 'phone', 'email', 'contact_url',
      'instagram_url', 'x_url', 'tiktok_url', 'facebook_url', 'youtube_url', 'line_url', 'assignee',
    ].map(key => [key, String(company[key as keyof Company] ?? '')])))
    setFollowup(company.next_followup_at?.slice(0, 16) ?? '')
    setProtectedFields(company.protected_fields)
    setDoNotContact(company.do_not_contact); setExclusionReason(company.exclusion_reason)
    setContactQuality(company.contact_quality_status)
    const [nextActivities, nextContacts, nextDrafts, nextTemplates] = await Promise.all([
      api<Activity[]>(`/companies/${company.id}/activities`),
      api<ContactPerson[]>(`/companies/${company.id}/contacts`),
      api<OutreachDraft[]>(`/companies/${company.id}/outreach-drafts`),
      api<OutreachTemplate[]>(`/projects/${company.project_id}/outreach-templates`),
    ])
    const firstDraft = nextDrafts[0] ?? null
    const [nextDelivery, nextFormDelivery, nextApprovals] = await Promise.all([
      firstDraft?.channel === 'email'
        ? api<EmailDelivery | null>(`/outreach-drafts/${firstDraft.id}/email-delivery`) : Promise.resolve(null),
      firstDraft?.channel === 'form'
        ? api<FormDelivery | null>(`/outreach-drafts/${firstDraft.id}/form-delivery`) : Promise.resolve(null),
      firstDraft ? api<OutreachDraftApproval[]>(`/outreach-drafts/${firstDraft.id}/approvals`) : Promise.resolve([]),
    ])
    setActivities(nextActivities); setContacts(nextContacts); setOutreachDrafts(nextDrafts); setOutreachTemplates(nextTemplates); setDraftApprovals(nextApprovals)
    setSelectedDraft(firstDraft); setEmailDelivery(nextDelivery); setFormDelivery(nextFormDelivery); setDeliveryRecipient(company.email)
    setDeliverySchedule(''); setDeliveryConfirmed(false); setFormPreview(null); setFormValues({}); setFormConfirmed(false); setAssistOutcome('pending'); setAssistNote(''); setAssistConfirmed(false); setDraftContactId(''); setDraftInstruction('')
  }
  async function save() {
    if (!selected) return
    setBusy(true); setError('')
    try {
      const updated = await api<Company>(`/companies/${selected.id}/sales`, 'PATCH', {
        status, notes, next_followup_at: followup ? new Date(followup).toISOString() : null,
      })
      setSelected(updated); await reload(); setNotice('営業状況を保存しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function bulkStatus(nextStatus: SalesStatus) {
    if (!checked.length) return
    setBusy(true); setError('')
    try {
      await api(`/projects/${projectId}/companies/bulk-sales`, 'PATCH', {
        company_ids: checked, status: nextStatus,
      })
      await reload(); setNotice(`${checked.length}社の営業状況を更新しました。`)
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function saveCompany() {
    if (!selected) return
    setBusy(true); setError('')
    try {
      const updated = await api<Company>(`/companies/${selected.id}`, 'PUT', {
        ...companyEdit, protected_fields: protectedFields,
      })
      setSelected(updated); await reload(); setNotice('企業情報を保存しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function assignSelected() {
    if (!checked.length) return
    setBusy(true); setError('')
    try {
      await api(`/projects/${projectId}/companies/bulk-assignee`, 'PATCH', {
        company_ids: checked, assignee: bulkAssignee,
      })
      await reload(); setNotice(`${checked.length}社の担当者を更新しました。`)
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function addActivity() {
    if (!selected || !activityNote.trim()) return
    setBusy(true); setError('')
    try {
      await api(`/companies/${selected.id}/activities`, 'POST', {
        activity_type: activityType, note: activityNote,
      })
      setActivityNote(''); setActivities(await api<Activity[]>(`/companies/${selected.id}/activities`))
      setNotice('活動履歴を追加しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  function editContact(contact: ContactPerson) {
    setEditingContactId(contact.id)
    setContactDraft(Object.fromEntries(Object.keys(emptyContact).map(key => [key, String(contact[key as keyof ContactPerson] ?? '')])))
  }
  async function saveContactPerson() {
    if (!selected || !contactDraft.name?.trim()) return
    setBusy(true); setError(''); setNotice('')
    try {
      const path = editingContactId ? `/contacts/${editingContactId}` : `/companies/${selected.id}/contacts`
      await api(path, editingContactId ? 'PUT' : 'POST', contactDraft)
      setContacts(await api<ContactPerson[]>(`/companies/${selected.id}/contacts`))
      setEditingContactId(''); setContactDraft(emptyContact)
      setNotice(editingContactId ? '先方担当者を更新しました。' : '先方担当者を追加しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function deleteContactPerson(contact: ContactPerson) {
    if (!window.confirm(`「${contact.name}」を削除しますか？`)) return
    setBusy(true); setError(''); setNotice('')
    try {
      await api(`/contacts/${contact.id}`, 'DELETE')
      if (selected) setContacts(await api<ContactPerson[]>(`/companies/${selected.id}/contacts`))
      if (editingContactId === contact.id) { setEditingContactId(''); setContactDraft(emptyContact) }
      setNotice('先方担当者を削除しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function generateDraft() {
    if (!selected) return
    setBusy(true); setError(''); setNotice('')
    try {
      const generated = await api<OutreachDraft>(`/companies/${selected.id}/outreach-drafts/generate`, 'POST', {
        channel: draftChannel, contact_person_id: draftContactId || null, instruction: draftInstruction,
      })
      setOutreachDrafts([generated, ...outreachDrafts]); setSelectedDraft(generated)
      setEmailDelivery(null); setDeliveryRecipient(selected.email); setDeliverySchedule(''); setDeliveryConfirmed(false)
      setNotice('営業文面を生成して保存しました。内容を確認してから使用してください。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function saveDraft() {
    if (!selectedDraft) return
    setBusy(true); setError(''); setNotice('')
    try {
      const updated = await api<OutreachDraft>(`/outreach-drafts/${selectedDraft.id}`, 'PUT', {
        subject: selectedDraft.subject, body: selectedDraft.body,
      })
      setSelectedDraft(updated)
      setOutreachDrafts(outreachDrafts.map(item => item.id === updated.id ? updated : item))
      setNotice('営業文面を保存しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function deleteDraft() {
    if (!selectedDraft || !window.confirm('この営業文面を削除しますか？')) return
    setBusy(true); setError(''); setNotice('')
    try {
      await api(`/outreach-drafts/${selectedDraft.id}`, 'DELETE')
      const remaining = outreachDrafts.filter(item => item.id !== selectedDraft.id)
      const nextDraft = remaining[0] ?? null
      setOutreachDrafts(remaining); setSelectedDraft(nextDraft); setEmailDelivery(null)
      setNotice('営業文面を削除しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function copyDraft() {
    if (!selectedDraft) return
    const text = selectedDraft.subject ? `${selectedDraft.subject}\n\n${selectedDraft.body}` : selectedDraft.body
    try { await navigator.clipboard.writeText(text); setNotice('営業文面をコピーしました。') }
    catch { setError('コピーできませんでした。文面を選択してコピーしてください。') }
  }
  async function saveTemplate() {
    if (!selectedDraft || !selected || !templateName.trim()) return
    setBusy(true); setError(''); setNotice('')
    try {
      const template = await api<OutreachTemplate>(`/projects/${selected.project_id}/outreach-templates`, 'POST', {
        name: templateName, channel: selectedDraft.channel, subject: selectedDraft.subject, body: selectedDraft.body,
      })
      setOutreachTemplates([...outreachTemplates, template]); setTemplateName(''); setNotice('営業文面テンプレートを保存しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function applyTemplate(template: OutreachTemplate) {
    if (!selectedDraft || !window.confirm(`「${template.name}」を現在の文面へ適用しますか？`)) return
    setBusy(true); setError(''); setNotice('')
    try {
      const updated = await api<OutreachDraft>(`/outreach-drafts/${selectedDraft.id}/apply-template`, 'POST', { template_id: template.id })
      setSelectedDraft(updated); setOutreachDrafts(outreachDrafts.map(item => item.id === updated.id ? updated : item)); setNotice('テンプレートを適用しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function deleteTemplate(template: OutreachTemplate) {
    if (!window.confirm(`テンプレート「${template.name}」を削除しますか？`)) return
    setBusy(true); setError(''); setNotice('')
    try { await api(`/outreach-templates/${template.id}`, 'DELETE'); setOutreachTemplates(outreachTemplates.filter(item => item.id !== template.id)); setNotice('テンプレートを削除しました。') }
    catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function selectDraft(draft: OutreachDraft) {
    setSelectedDraft(draft); setDeliveryConfirmed(false); setDeliverySchedule(''); setFormPreview(null); setFormValues({}); setFormConfirmed(false)
    setAssistOutcome('pending'); setAssistNote(''); setAssistConfirmed(false)
    try {
      const [nextEmailDelivery, nextFormDelivery, nextApprovals] = await Promise.all([
        draft.channel === 'email' ? api<EmailDelivery | null>(`/outreach-drafts/${draft.id}/email-delivery`) : Promise.resolve(null),
        draft.channel === 'form' ? api<FormDelivery | null>(`/outreach-drafts/${draft.id}/form-delivery`) : Promise.resolve(null),
        api<OutreachDraftApproval[]>(`/outreach-drafts/${draft.id}/approvals`),
      ])
      setEmailDelivery(nextEmailDelivery); setFormDelivery(nextFormDelivery); setDraftApprovals(nextApprovals)
    } catch (e) { setError(errorMessage(e)) }
  }
  async function inspectForm() {
    if (!selectedDraft) return
    setBusy(true); setError(''); setNotice('')
    try {
      const preview = await api<FormPreview>(`/outreach-drafts/${selectedDraft.id}/form-preview`)
      setFormPreview(preview)
      setFormValues(Object.fromEntries(preview.fields.map(field => [field.name, field.value || (/(message|inquiry|contact|内容|問い合わせ)/i.test(field.name) ? selectedDraft.body : '')])))
      setNotice('フォーム項目を読み込みました。内容を確認してから送信してください。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function submitForm() {
    if (!selectedDraft || !formPreview || !formConfirmed) return
    if (!window.confirm('このフォームへ入力内容を送信しますか？')) return
    setBusy(true); setError(''); setNotice('')
    try {
      await api(`/outreach-drafts/${selectedDraft.id}/form-delivery`, 'POST', { field_values: formValues, confirmed: true })
      setNotice('フォームへの送信リクエストを実行しました。企業の活動履歴を確認してください。')
      setFormConfirmed(false)
      if (selected) await open(selected)
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function copyFormAssist() {
    if (!selectedDraft) return
    setBusy(true); setError(''); setNotice('')
    try {
      const assist = await api<FormAssist>(`/outreach-drafts/${selectedDraft.id}/form-assist`)
      await navigator.clipboard.writeText(`${assist.instructions}\n\n会社: ${assist.company_name}\nフォームURL: ${assist.form_url}\n\n本文:\n${assist.body}`)
      setNotice('Codex支援用の操作指示をコピーしました。Codexでブラウザ操作を依頼してください。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function recordFormAssistDelivery() {
    if (!selectedDraft || !assistConfirmed) return
    if (!window.confirm('Codex上で確認したフォーム送信結果を記録しますか？')) return
    setBusy(true); setError(''); setNotice('')
    try {
      const delivery = await api<FormDelivery>(`/outreach-drafts/${selectedDraft.id}/form-assist-delivery`, 'POST', {
        status: assistOutcome, note: assistNote, confirmed: true,
      })
      setFormDelivery(delivery); setAssistConfirmed(false)
      setNotice(`Codex支援フォーム送信を「${assistOutcome === 'submitted' ? '送信済み' : assistOutcome === 'failed' ? '失敗' : '保留'}」として記録しました。`)
      if (selected) await open(selected)
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function scheduleEmailDelivery() {
    if (!selectedDraft || !deliveryRecipient || !deliveryConfirmed) return
    if (!window.confirm(`「${deliveryRecipient}」へこの内容を送信予約しますか？`)) return
    setBusy(true); setError(''); setNotice('')
    try {
      const saved = await api<OutreachDraft>(`/outreach-drafts/${selectedDraft.id}`, 'PUT', {
        subject: selectedDraft.subject, body: selectedDraft.body,
      })
      setSelectedDraft(saved); setOutreachDrafts(outreachDrafts.map(item => item.id === saved.id ? saved : item))
      const delivery = await api<EmailDelivery>(`/outreach-drafts/${saved.id}/email-delivery`, 'POST', {
        recipient_email: deliveryRecipient,
        scheduled_for: deliverySchedule ? new Date(deliverySchedule).toISOString() : null,
        confirmed: true,
      })
      setEmailDelivery(delivery); setDeliveryConfirmed(false)
      setNotice(deliverySchedule ? 'メール送信を予約しました。' : 'メール送信を承認しました。ワーカーが送信します。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function cancelEmailDelivery() {
    if (!emailDelivery || !window.confirm('このメール送信予約をキャンセルしますか？')) return
    setBusy(true); setError(''); setNotice('')
    try {
      const delivery = await api<EmailDelivery>(`/email-deliveries/${emailDelivery.id}/cancel`, 'POST')
      setEmailDelivery(delivery); setNotice('メール送信予約をキャンセルしました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function retryEmailDelivery() {
    if (!emailDelivery || !deliveryConfirmed) return
    if (!window.confirm(`「${emailDelivery.recipient_email}」へ再送予約しますか？`)) return
    setBusy(true); setError(''); setNotice('')
    try {
      const delivery = await api<EmailDelivery>(`/email-deliveries/${emailDelivery.id}/retry`, 'POST', {
        scheduled_for: deliverySchedule ? new Date(deliverySchedule).toISOString() : null,
        confirmed: true,
      })
      setEmailDelivery(delivery); setDeliveryConfirmed(false); setNotice('メールの再送を予約しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  function startOutreach(item: OutreachQueueItem) {
    setOutreachTarget(item); setOutreachChannel(item.recommended_channel)
    setOutreachOutcome('approached'); setOutreachNote(''); setOutreachFollowup('')
  }
  async function recordOutreach() {
    if (!outreachTarget || !outreachNote.trim()) return
    setBusy(true); setError(''); setNotice('')
    try {
      await api(`/companies/${outreachTarget.company.id}/outreach`, 'POST', {
        channel: outreachChannel, outcome: outreachOutcome, note: outreachNote,
        next_followup_at: outreachFollowup ? new Date(outreachFollowup).toISOString() : null,
      })
      setOutreachTarget(null); await reload(); setNotice('アプローチと次回対応を記録しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  function startReply(item: ReplyQueueItem) {
    setReplyTarget(item); setReplyOutcome('replied'); setReplyNote(''); setReplyFollowup('')
  }
  async function recordReplyResponse() {
    if (!replyTarget || !replyNote.trim()) return
    setBusy(true); setError(''); setNotice('')
    try {
      const updated = await api<Company>(`/companies/${replyTarget.company.id}/reply-response`, 'POST', {
        inbound_email_id: replyTarget.inbound_email_id, outcome: replyOutcome, note: replyNote,
        next_followup_at: replyFollowup ? new Date(replyFollowup).toISOString() : null,
      })
      setReplyTarget(null); await reload()
      if (selected?.id === updated.id) await open(updated)
      setNotice('返信対応と次回対応を記録しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  function startFollowupTask(task: FollowupTask) {
    setFollowupTarget(task); setFollowupAction('completed'); setFollowupTaskNote('')
    setFollowupTaskDate(task.company.next_followup_at?.slice(0, 16) ?? '')
  }
  async function resolveFollowupTask() {
    if (!followupTarget || !followupTaskNote.trim()) return
    if (!window.confirm(followupAction === 'completed' ? 'この追客タスクを完了しますか？' : 'この追客タスクを延期しますか？')) return
    setBusy(true); setError(''); setNotice('')
    try {
      const updated = await api<Company>(`/companies/${followupTarget.company.id}/followup-task`, 'POST', {
        action: followupAction, note: followupTaskNote,
        next_followup_at: followupAction === 'rescheduled' && followupTaskDate ? new Date(followupTaskDate).toISOString() : null,
      })
      setFollowupTarget(null); await reload()
      if (selected?.id === updated.id) await open(updated)
      setNotice(followupAction === 'completed' ? '追客タスクを完了しました。' : '追客タスクを延期しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function createEmailCampaign() {
    if (!projectId || !emailCampaignTemplateId || !emailCampaignName.trim() || checked.length === 0 || !emailCampaignConfirmed) return
    setBusy(true); setError(''); setNotice('')
    try {
      const campaign = await api<EmailCampaign>(`/projects/${projectId}/email-campaigns`, 'POST', { name: emailCampaignName, template_id: emailCampaignTemplateId, company_ids: checked, followup_days: emailCampaignFollowupDays, confirmed: true })
      setEmailCampaigns([campaign, ...emailCampaigns]); setEmailCampaignName(''); setEmailCampaignConfirmed(false)
      setNotice(`一括メールキャンペーンを作成しました。送信待ち ${campaign.queued_count} 件です。`)
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function changeEmailCampaign(campaign: EmailCampaign, action: 'pause' | 'resume') {
    setBusy(true); setError('')
    try { const updated = await api<EmailCampaign>(`/email-campaigns/${campaign.id}/${action}`, 'POST'); setEmailCampaigns(emailCampaigns.map(item => item.id === updated.id ? updated : item)); setNotice(action === 'pause' ? 'メールキャンペーンを停止しました。' : 'メールキャンペーンを再開しました。') }
    catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function createFormBatch() {
    if (!projectId || !formBatchTemplateId || checked.length === 0) return
    setBusy(true); setError(''); setNotice('')
    try {
      const batch = await api<FormDeliveryBatch>(`/projects/${projectId}/form-delivery-batches`, 'POST', { template_id: formBatchTemplateId, company_ids: checked })
      setFormBatches([batch, ...formBatches]); setFormBatchConfirmed(false); setNotice(`一括フォームDMを${batch.items.length}社分作成しました。送信前に対象を確認してください。`)
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function executeFormBatch(batch: FormDeliveryBatch) {
    if (!formBatchConfirmed) return
    setBusy(true); setError(''); setNotice('')
    try {
      const updated = await api<FormDeliveryBatch>(`/form-delivery-batches/${batch.id}/execute`, 'POST', { confirmed: true, limit: 20 })
      setFormBatches(formBatches.map(item => item.id === updated.id ? updated : item)); setFormBatchConfirmed(false)
      const counts = updated.items.reduce<Record<string, number>>((result, item) => ({ ...result, [item.status]: (result[item.status] ?? 0) + 1 }), {})
      setNotice(`一括フォームDMを処理しました。送信済み ${counts.submitted ?? 0} / 手動対応 ${counts.manual_required ?? 0} / 残り ${counts.queued ?? 0}`)
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function retryFormBatchItem(itemId: string) {
    if (!window.confirm('この失敗したフォーム送信を、次回の一括実行対象に戻しますか？')) return
    setBusy(true); setError(''); setNotice('')
    try {
      const updated = await api<FormDeliveryBatch>(`/form-delivery-batch-items/${itemId}/retry`, 'POST', { confirmed: true })
      setFormBatches(formBatches.map(item => item.id === updated.id ? updated : item))
      setNotice('フォーム送信を再試行待ちに戻しました。実行前に改めて承認してください。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function copyBatchCodexTask(task: FormCodexTask) {
    try {
      await navigator.clipboard.writeText(`${task.instructions}\n\n会社: ${task.company_name}\nフォームURL: ${task.form_url}\n保留理由: ${task.reason}\n\n本文:\n${task.body}`)
      setNotice(`${task.company_name}のCodex支援用指示をコピーしました。`)
    } catch { setError('クリップボードへのコピーに失敗しました。') }
  }

  async function updateFormCodexTask(task: FormCodexTask, status: 'running' | 'submitted' | 'failed') {
    const completed = status === 'submitted' || status === 'failed'
    if (completed && !window.confirm(status === 'submitted' ? 'Codex上で送信完了を確認しましたか？' : 'Codex上で送信失敗を確認しましたか？')) return
    setBusy(true); setError(''); setNotice('')
    try {
      const updated = await api<FormCodexTask>(`/form-codex-queue/${task.item_id}`, 'POST', { status, confirmed: completed })
      setFormCodexTasks(formCodexTasks.map(item => item.item_id === updated.item_id ? updated : item).filter(item => item.codex_status === 'open' || item.codex_status === 'running'))
      await reload()
      setNotice(status === 'running' ? 'Codex支援フォームを作業中にしました。' : status === 'submitted' ? 'Codex支援フォームの送信完了を記録しました。' : 'Codex支援フォームの失敗を記録しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }

  async function cancelFormBatch(batch: FormDeliveryBatch) {
    setBusy(true); setError('')
    try { const updated = await api<FormDeliveryBatch>(`/form-delivery-batches/${batch.id}/cancel`, 'POST'); setFormBatches(formBatches.map(item => item.id === updated.id ? updated : item)); setNotice('一括フォームDMを中止しました。') }
    catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function saveAiReview() {
    if (!selected) return
    setBusy(true); setError(''); setNotice('')
    try {
      const review = await api<AiReview>(`/companies/${selected.id}/ai-review`, 'PUT', { verdict: aiReviewVerdict, note: aiReviewNote })
      setAiReview(review); setNotice('AI判定レビューを保存しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function createDeal() {
    if (!selected || !dealTitle.trim()) return
    setBusy(true); setError(''); setNotice('')
    try {
      const deal = await api<Deal>(`/companies/${selected.id}/deals`, 'POST', {
        title: dealTitle, stage: dealStage, expected_amount: dealAmount,
        expected_close_date: dealCloseDate || null, owner: dealOwner, next_step: dealNextStep, lost_reason: dealLostReason,
      })
      setDeals([deal, ...deals]); setDealTitle(''); setDealAmount(0); setDealCloseDate(''); setDealNextStep(''); setDealLostReason('')
      setNotice('案件を追加しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function createExperiment() {
    if (!selected || !experimentName.trim() || !experimentA || !experimentB) return
    setBusy(true); setError(''); setNotice('')
    try {
      const experiment = await api<OutreachExperiment>(`/projects/${selected.project_id}/outreach-experiments`, 'POST', { name: experimentName, template_a_id: experimentA, template_b_id: experimentB, active: true })
      setExperiments([experiment, ...experiments]); setExperimentId(experiment.id); setExperimentName('')
      setNotice('A/Bテストを作成しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function applyExperiment() {
    if (!selectedDraft || !experimentId) return
    setBusy(true); setError(''); setNotice('')
    try {
      const assignment = await api<{ experiment_id: string; variant: 'A' | 'B'; template: OutreachTemplate }>(`/outreach-experiments/${experimentId}/apply/${selectedDraft.id}`, 'POST')
      const updated = { ...selectedDraft, subject: assignment.template.subject, body: assignment.template.body }
      setSelectedDraft(updated); setOutreachDrafts(outreachDrafts.map(item => item.id === updated.id ? updated : item))
      setNotice(`A/Bテストの${assignment.variant}案を適用しました。送信後に成果へ集計されます。`)
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function loadExperimentResults(id: string) {
    setExperimentId(id)
    if (!id) { setExperimentResults([]); return }
    try { setExperimentResults(await api<OutreachExperimentResult[]>(`/outreach-experiments/${id}/results`)) }
    catch (e) { setError(errorMessage(e)) }
  }
  async function saveContactControl() {
    if (!selected) return
    setBusy(true); setError('')
    try {
      const updated = await api<Company>(`/companies/${selected.id}/contact-control`, 'PATCH', {
        do_not_contact: doNotContact, exclusion_reason: exclusionReason,
        contact_quality_status: contactQuality,
      })
      setSelected(updated); await reload(); setNotice('連絡制御と連絡先品質を保存しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function reanalyzeQuality() {
    setBusy(true); setError(''); setNotice('')
    try {
      const job = await api<OperationJob>(`/projects/${projectId}/data-quality/reanalyze`, 'POST', {
        scope: 'failed_or_stale', stale_days: staleDays,
      })
      setNotice(`${job.total_count || quality?.reanalyzable || 0}社を再解析ジョブへ登録しました。`)
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function saveRefreshSchedule(active = refreshSchedule?.active ?? true) {
    setBusy(true); setError(''); setNotice('')
    try {
      await api(`/projects/${projectId}/analysis-refresh-schedule`, 'PUT', {
        interval_hours: refreshInterval, stale_days: refreshStaleDays,
        batch_limit: refreshBatchLimit, active,
      })
      await reload(); setNotice('自動再解析設定を保存しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function runRefreshSchedule() {
    setBusy(true); setError(''); setNotice('')
    try {
      const job = await api<OperationJob>(`/projects/${projectId}/analysis-refresh-schedule/run`, 'POST')
      await reload(); setNotice(`${job.total_count || refreshBatchLimit}社までの自動再解析を登録しました。`)
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function deleteRefreshSchedule() {
    setBusy(true); setError(''); setNotice('')
    try {
      await api(`/projects/${projectId}/analysis-refresh-schedule`, 'DELETE')
      setRefreshSchedule(null); setNotice('自動再解析設定を削除しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function mergeCompanies(target: Company, source: Company) {
    if (!window.confirm(`「${source.company_name}」を「${target.company_name}」へ統合しますか？`)) return
    setBusy(true); setError(''); setNotice('')
    try {
      await api(`/projects/${projectId}/companies/merge`, 'POST', {
        target_id: target.id, source_id: source.id,
      })
      setSelected(null); await reload(); setNotice('重複企業を統合しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function saveFilter() {
    if (!filterName.trim()) return
    setBusy(true); setError(''); setNotice('')
    try {
      await api(`/projects/${projectId}/saved-company-filters`, 'POST', {
        name: filterName, filters,
      })
      setFilterName(''); await reload(); setNotice('現在の絞り込み条件を保存しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function deleteFilter(filterId: string) {
    setBusy(true); setError(''); setNotice('')
    try {
      await api(`/saved-company-filters/${filterId}`, 'DELETE')
      await reload(); setNotice('保存フィルターを削除しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function updateFilter(item: SavedCompanyFilter, name: string, nextFilters: Filters) {
    if (!name.trim()) return
    setBusy(true); setError(''); setNotice('')
    try {
      await api(`/saved-company-filters/${item.id}`, 'PUT', { name, filters: nextFilters })
      setEditingFilterId(''); setEditingFilterName(''); await reload()
      setNotice(nextFilters === filters ? '保存フィルターを現在の条件で上書きしました。' : '保存フィルター名を変更しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  if (projects.length === 0) return <section className="panel empty"><h2>先にプロジェクトを作成してください</h2></section>
  return <>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p className="notice" role="status">{notice}</p>}
    <CompanyFilters
      projects={projects}
      projectId={projectId}
      draft={draft}
      setDraft={setDraft}
      onProjectChange={nextProjectId => { setProjectId(nextProjectId); setSelected(null); setPage(0) }}
      onReset={() => { setDraft(defaultCompanyFilters); setFilters(defaultCompanyFilters); setPage(0) }}
      onApply={() => { setFilters(draft); setPage(0) }}
      onDownload={() => void download(`/projects/${projectId}/companies.csv?${query}`, 'leadhive-companies.csv').catch(e => setError(errorMessage(e)))}
    />
    <DealPipelinePanel pipeline={dealPipeline} />
    <section className="panel mt-6"><div className="flex flex-wrap items-end justify-between gap-4"><div><h2>一括メール送信</h2><p className="muted mt-2 text-sm">一覧で選択した企業へメール文面を予約します。送信上限と間隔は既存のメールワーカーが適用し、返信後の追客日数も設定できます。</p></div><span className="badge">選択 {checked.length} 社</span></div><div className="detail-grid mt-4"><label className="field">キャンペーン名<input maxLength={200} value={emailCampaignName} onChange={e => setEmailCampaignName(e.target.value)} placeholder="例：9月初回メール" /></label><label className="field">メール文面テンプレート<select value={emailCampaignTemplateId} onChange={e => setEmailCampaignTemplateId(e.target.value)}><option value="">選択してください</option>{outreachTemplates.filter(item => item.channel === 'email').map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label className="field">送信後の追客（日後）<input type="number" min={0} max={365} value={emailCampaignFollowupDays} onChange={e => setEmailCampaignFollowupDays(Number(e.target.value))} /></label></div><label className="checkbox-row mt-3"><input type="checkbox" checked={emailCampaignConfirmed} onChange={e => setEmailCampaignConfirmed(e.target.checked)} />対象企業、文面、連絡禁止・送信済み企業の除外を確認し、一括メール送信を承認します。</label><div className="actions"><button disabled={busy || !emailCampaignName.trim() || !emailCampaignTemplateId || checked.length === 0 || !emailCampaignConfirmed} onClick={() => void createEmailCampaign()}>一括メールを予約</button></div>{emailCampaigns.map(campaign => <article className="job-row mt-4" key={campaign.id}><div><strong>{campaign.name}</strong><p className="muted text-sm">送信待ち {campaign.queued_count} / 送信済み {campaign.sent_count} / 失敗 {campaign.failed_count} / 返信 {campaign.replied_count} / 商談 {campaign.meeting_count} / 成約 {campaign.won_count} / 追客 {campaign.followup_days || 0}日後</p></div><div className="actions">{campaign.status === 'paused' ? <button className="secondary" disabled={busy} onClick={() => void changeEmailCampaign(campaign, 'resume')}>再開</button> : <button className="secondary" disabled={busy || campaign.status === 'completed'} onClick={() => void changeEmailCampaign(campaign, 'pause')}>停止</button>}<span className="badge">{campaign.status === 'queued' ? '配信中' : campaign.status === 'paused' ? '停止中' : '完了'}</span></div></article>)}{emailCampaigns.length === 0 && <p className="muted mt-4">メールキャンペーンはまだありません。</p>}</section>
    <section className="panel mt-6"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2>Codex支援フォームの作業キュー</h2><p className="muted mt-2 text-sm">通常フォームで完結しない案件を、Codexに渡す指示としてまとめます。送信前の確認と最終送信は担当者が行います。</p></div><span className="badge">{formCodexTasks.length} 件</span></div>{formCodexTasks.length === 0 ? <p className="muted mt-4">Codex支援が必要なフォームはありません。</p> : formCodexTasks.map(task => <article className="job-row mt-4" key={task.item_id}><div><strong>{task.company_name}</strong><p className="muted text-sm">{task.reason} / {task.codex_status === 'running' ? `作業中: ${task.codex_assignee || '担当未設定'}` : '未着手'}</p><p className="muted text-xs break-all">{task.form_url}</p></div><div className="actions"><a className="secondary" href={task.form_url} target="_blank" rel="noreferrer">フォームを開く</a><button className="secondary" disabled={busy} onClick={() => void copyBatchCodexTask(task)}>Codex用指示をコピー</button>{task.codex_status === 'open' && <button className="secondary" disabled={busy} onClick={() => void updateFormCodexTask(task, 'running')}>作業開始</button>}<button disabled={busy} onClick={() => void updateFormCodexTask(task, 'submitted')}>送信済みを記録</button><button className="danger" disabled={busy} onClick={() => void updateFormCodexTask(task, 'failed')}>失敗を記録</button></div></article>)}</section>
    <section className="panel mt-6"><div className="flex flex-wrap items-end justify-between gap-4"><div><h2>一括フォームDM</h2><p className="muted mt-2 text-sm">一覧で選択した企業へ同じフォーム文面をキュー化します。通常フォームだけを承認後に最大20社ずつ送信し、入力項目が不足するフォームはCodex支援対象として残します。</p></div><span className="badge">選択 {checked.length} 社</span></div><div className="detail-grid mt-4"><label className="field">フォーム文面テンプレート<select value={formBatchTemplateId} onChange={e => setFormBatchTemplateId(e.target.value)}><option value="">選択してください</option>{outreachTemplates.filter(item => item.channel === 'form').map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label></div><div className="actions"><button disabled={busy || !formBatchTemplateId || checked.length === 0} onClick={() => void createFormBatch()}>選択企業で一括DMを作成</button></div>{formBatches.map(batch => <article className="job-row block mt-4" key={batch.id}><div className="flex flex-wrap justify-between gap-3"><div><strong>一括フォームDM</strong><p className="muted text-sm">{new Date(batch.created_at).toLocaleString('ja-JP')} / {batch.items.length}社</p></div><span className="badge">{batch.status === 'ready' ? '送信待ち' : batch.status === 'running' ? '実行中' : batch.status === 'completed' ? '完了' : '中止'}</span></div><div className="job-stats mt-3">{Object.entries(batch.items.reduce<Record<string, number>>((result, item) => ({ ...result, [item.status]: (result[item.status] ?? 0) + 1 }), {})).map(([status, count]) => <span key={status}>{({ queued: '送信待ち', submitted: '送信済み', failed: '失敗', manual_required: 'Codex支援', skipped: '対象外' }[status] ?? status)} {count}</span>)}</div>{batch.status === 'ready' && <><label className="checkbox-row mt-3"><input type="checkbox" checked={formBatchConfirmed} onChange={e => setFormBatchConfirmed(e.target.checked)} />対象企業、文面、送信済み・連絡禁止の除外を確認し、通常フォームへの一括送信を承認します。</label><div className="actions"><button disabled={busy || !formBatchConfirmed} onClick={() => void executeFormBatch(batch)}>最大20社を順次送信</button><button className="danger" disabled={busy} onClick={() => void cancelFormBatch(batch)}>中止</button></div></>}{batch.items.filter(item => item.status === 'manual_required').map(item => <p className="muted text-sm mt-2" key={item.id}>{item.company_name}：Codex支援が必要です（{item.reason}）</p>)}{batch.items.filter(item => item.status === 'failed').map(item => <div className="actions mt-2" key={item.id}><span className="error text-sm">{item.company_name}：{item.reason || '送信に失敗しました。'}</span><button className="secondary" disabled={busy} onClick={() => void retryFormBatchItem(item.id)}>再試行待ちに戻す</button></div>)}</article>)}{formBatches.length === 0 && <p className="muted mt-4">一括フォームDMはまだありません。</p>}</section>
    <section className="panel mt-6"><div className="flex items-center justify-between gap-3"><div><h2>返信対応キュー</h2><p className="muted mt-2 text-sm">受信した返信を確認し、商談化・失注・次回対応を記録します。</p></div><span className="badge">{replyQueue.length} 件</span></div>
      <div className="company-table-wrap mt-4"><table className="company-table"><thead><tr><th>企業</th><th>受信内容</th><th>受信日時</th><th>担当</th><th></th></tr></thead><tbody>{replyQueue.map(item => <tr key={item.inbound_email_id}><td><strong>{item.company.company_name}</strong><p className="muted text-xs">{item.company.email || item.sender_email}</p></td><td><strong>{item.subject || '件名なし'}</strong><p className="muted text-xs">{item.preview}</p></td><td>{new Date(item.received_at).toLocaleString('ja-JP')}</td><td>{item.company.assignee || '未設定'}</td><td><button className="secondary" onClick={() => startReply(item)}>対応する</button></td></tr>)}{replyQueue.length === 0 && <tr><td colSpan={5} className="text-center muted">対応待ちの返信はありません。</td></tr>}</tbody></table></div>
      {replyTarget && <div className="mt-5"><h3>{replyTarget.company.company_name}への返信対応</h3><p className="muted text-sm mt-2">{replyTarget.sender_email} / {replyTarget.subject || '件名なし'}</p><p className="mt-2 text-sm whitespace-pre-wrap">{replyTarget.preview || '本文の要約はありません。'}</p><div className="detail-grid mt-4"><div><label className="field">対応結果<select value={replyOutcome} onChange={e => setReplyOutcome(e.target.value as 'replied' | 'meeting' | 'won' | 'lost')}><option value="replied">返信確認・継続対応</option><option value="meeting">商談化</option><option value="won">成約</option><option value="lost">失注</option></select></label><label className="field">次回対応日時<input type="datetime-local" value={replyFollowup} onChange={e => setReplyFollowup(e.target.value)} /></label></div><label className="field">対応内容<textarea rows={4} maxLength={10000} value={replyNote} onChange={e => setReplyNote(e.target.value)} placeholder="返信内容、対応方針、商談日時など" /></label></div><div className="actions"><button disabled={busy || !replyNote.trim()} onClick={() => void recordReplyResponse()}>返信対応を記録</button><button className="secondary" onClick={() => setReplyTarget(null)}>キャンセル</button></div></div>}
    </section>
    <section className="panel mt-6"><div className="flex items-center justify-between gap-3"><div><h2>追客タスク</h2><p className="muted mt-2 text-sm">期限がある次回対応を完了または延期します。</p></div><span className="badge">{followupTasks.length} 件</span></div>
      <div className="company-table-wrap mt-4"><table className="company-table"><thead><tr><th>企業</th><th>担当</th><th>期限</th><th>営業状況</th><th></th></tr></thead><tbody>{followupTasks.map(task => <tr key={task.company.id}><td><strong>{task.company.company_name}</strong><p className="muted text-xs">{task.company.rank ?? '—'} / {task.company.score ?? '—'}点</p></td><td>{task.company.assignee || '未設定'}</td><td><span className="badge">{dueNames[task.due_state]}</span><p className="muted text-xs">{task.company.next_followup_at ? new Date(task.company.next_followup_at).toLocaleString('ja-JP') : '—'}</p></td><td>{statusNames[task.company.status]}</td><td><button className="secondary" onClick={() => startFollowupTask(task)}>完了・延期</button></td></tr>)}{followupTasks.length === 0 && <tr><td colSpan={5} className="text-center muted">期限が設定された追客タスクはありません。</td></tr>}</tbody></table></div>
      {followupTarget && <div ref={followupPanelRef} className="mt-5"><h3>{followupTarget.company.company_name}の追客タスク</h3><div className="detail-grid"><div><label className="field">処理<select value={followupAction} onChange={e => setFollowupAction(e.target.value as 'completed' | 'rescheduled')}><option value="completed">完了</option><option value="rescheduled">延期</option></select></label>{followupAction === 'rescheduled' && <label className="field">次回対応日時<input type="datetime-local" value={followupTaskDate} onChange={e => setFollowupTaskDate(e.target.value)} /></label>}</div><label className="field">対応メモ<textarea rows={4} maxLength={10000} value={followupTaskNote} onChange={e => setFollowupTaskNote(e.target.value)} placeholder="例：先方都合により来週へ延期" /></label></div><div className="actions"><button disabled={busy || !followupTaskNote.trim() || (followupAction === 'rescheduled' && !followupTaskDate)} onClick={() => void resolveFollowupTask()}>{followupAction === 'completed' ? 'タスクを完了' : 'タスクを延期'}</button><button className="secondary" onClick={() => setFollowupTarget(null)}>キャンセル</button></div></div>}
    </section>
    <section className="panel mt-6"><div className="flex items-center justify-between gap-3"><div><h2>営業アプローチキュー</h2><p className="muted mt-2 text-sm">期限超過を優先し、連絡可能な営業対象を処理します。</p></div><span className="badge">{outreachQueue.length} 社</span></div>
      <div className="company-table-wrap mt-4"><table className="company-table"><thead><tr><th>企業</th><th>推奨経路</th><th>担当者</th><th>期限</th><th>状況</th><th></th></tr></thead><tbody>{outreachQueue.map(item => <tr key={item.company.id}><td><strong>{item.company.company_name}</strong><p className="muted text-xs">{item.company.rank ?? '—'} / {item.company.score ?? '—'}点</p></td><td>{channelNames[item.recommended_channel]}<p className="muted text-xs">{item.available_channels.map(channel => channelNames[channel]).join(' / ')}</p></td><td>{item.company.assignee || '未設定'}</td><td><span className="badge">{dueNames[item.due_state]}</span><p className="muted text-xs">{item.company.next_followup_at ? new Date(item.company.next_followup_at).toLocaleString('ja-JP') : '—'}</p></td><td>{statusNames[item.company.status]}</td><td><button className="secondary" onClick={() => startOutreach(item)}>対応する</button></td></tr>)}{outreachQueue.length === 0 && <tr><td colSpan={6} className="text-center muted">連絡可能な営業対象はありません。</td></tr>}</tbody></table></div>
      {outreachTarget && <div className="mt-5"><h3>{outreachTarget.company.company_name}への対応記録</h3><div className="detail-grid"><div><label className="field">連絡経路<select value={outreachChannel} onChange={e => setOutreachChannel(e.target.value as OutreachChannel)}>{outreachTarget.available_channels.map(channel => <option key={channel} value={channel}>{channelNames[channel]}</option>)}</select></label><label className="field">結果<select value={outreachOutcome} onChange={e => setOutreachOutcome(e.target.value as SalesStatus)}><option value="approached">アプローチ済</option><option value="replied">返信あり</option><option value="meeting">商談</option><option value="lost">失注</option></select></label><label className="field">次回対応日時<input type="datetime-local" value={outreachFollowup} onChange={e => setOutreachFollowup(e.target.value)} /></label></div><label className="field">対応内容<textarea rows={5} maxLength={10000} value={outreachNote} onChange={e => setOutreachNote(e.target.value)} placeholder="送信内容、通話結果、次回確認事項" /></label></div><div className="actions"><button disabled={busy || !outreachNote.trim()} onClick={() => void recordOutreach()}>対応を記録</button><button className="secondary" onClick={() => setOutreachTarget(null)}>キャンセル</button></div></div>}
    </section>
    <section className="panel mt-6"><div className="flex flex-wrap items-end justify-between gap-4"><div><h2>保存フィルター</h2><p className="muted mt-2 text-sm">適用中の絞り込み条件を名前付きで保存します。</p></div>
      <div className="flex flex-wrap items-end gap-2"><label className="field mb-0">フィルター名<input value={filterName} maxLength={200} onChange={e => setFilterName(e.target.value)} placeholder="例：佐藤担当の期限超過" /></label><button disabled={busy || !filterName.trim()} onClick={() => void saveFilter()}>現在の条件を保存</button></div></div>
      {savedFilters.length === 0 ? <p className="muted mt-4">保存済みフィルターはありません。</p> : <div className="grid gap-3 mt-4 sm:grid-cols-2 xl:grid-cols-3">{savedFilters.map(item => <article className="job-row block" key={item.id}>{editingFilterId === item.id ? <><label className="field">保存名<input aria-label={`${item.name}の保存名`} maxLength={200} value={editingFilterName} onChange={e => setEditingFilterName(e.target.value)} /></label><div className="flex gap-2"><button disabled={busy || !editingFilterName.trim()} onClick={() => void updateFilter(item, editingFilterName, item.filters)}>名前を保存</button><button className="secondary" onClick={() => setEditingFilterId('')}>キャンセル</button></div></> : <><strong>{item.name}</strong><div className="flex flex-wrap gap-2 mt-3"><button className="secondary" onClick={() => { setDraft(item.filters); setFilters(item.filters); setPage(0) }}>適用</button><button className="secondary" disabled={busy} onClick={() => void updateFilter(item, item.name, filters)}>現在の条件で上書き</button><button className="secondary" onClick={() => { setEditingFilterId(item.id); setEditingFilterName(item.name) }}>名前変更</button><button className="danger" disabled={busy} onClick={() => void deleteFilter(item.id)}>削除</button></div></>}</article>)}</div>}</section>
    <AssigneeAnalyticsPanel items={assigneeAnalytics} />
    <CompanyQualityPanels
      quality={quality}
      staleDays={staleDays}
      busy={busy}
      refreshSchedule={refreshSchedule}
      refreshInterval={refreshInterval}
      refreshStaleDays={refreshStaleDays}
      refreshBatchLimit={refreshBatchLimit}
      duplicates={duplicates}
      onStaleDaysChange={setStaleDays}
      onReanalyze={() => void reanalyzeQuality()}
      onRefreshIntervalChange={setRefreshInterval}
      onRefreshStaleDaysChange={setRefreshStaleDays}
      onRefreshBatchLimitChange={setRefreshBatchLimit}
      onSaveRefreshSchedule={active => void saveRefreshSchedule(active)}
      onRunRefreshSchedule={() => void runRefreshSchedule()}
      onDeleteRefreshSchedule={() => void deleteRefreshSchedule()}
      onMerge={(primary, duplicate) => void mergeCompanies(primary, duplicate)}
    />
    <CompanyList
      companies={companies}
      total={total}
      checked={checked}
      page={page}
      busy={busy}
      bulkAssignee={bulkAssignee}
      setChecked={setChecked}
      setBulkAssignee={setBulkAssignee}
      setPage={setPage}
      onBulkStatus={nextStatus => void bulkStatus(nextStatus)}
      onAssign={() => void assignSelected()}
      onOpen={company => void open(company)}
    />
    {selected && <section className="panel mt-7" aria-label="企業詳細"><div className="flex justify-between gap-4"><div><p className="eyebrow">COMPANY DETAIL</p><h2>{selected.company_name}</h2></div><button className="secondary" onClick={() => setSelected(null)}>閉じる</button></div>
      <div className="detail-grid"><div><h3>基本情報を編集</h3>{[['company_name', '会社名'], ['address', '住所'], ['prefecture', '都道府県'], ['city', '市区町村'], ['phone', '電話'], ['email', 'メール'], ['assignee', '担当者']].map(([key, label]) => <div key={key}><label className="field">{label}<input value={companyEdit[key] ?? ''} onChange={e => setCompanyEdit({ ...companyEdit, [key]: e.target.value })} /></label>{key !== 'assignee' && <label className="checkbox-row text-sm"><input type="checkbox" checked={protectedFields.includes(key)} onChange={e => setProtectedFields(e.target.checked ? [...protectedFields, key] : protectedFields.filter(field => field !== key))} />{label}をWeb再解析から保護</label>}</div>)}</div>
        <div><h3>問い合わせ先を編集</h3>{[['contact_url', 'フォーム'], ['instagram_url', 'Instagram'], ['x_url', 'X'], ['tiktok_url', 'TikTok'], ['facebook_url', 'Facebook'], ['youtube_url', 'YouTube'], ['line_url', 'LINE']].map(([key, label]) => <div key={key}><label className="field">{label}<input value={companyEdit[key] ?? ''} onChange={e => setCompanyEdit({ ...companyEdit, [key]: e.target.value })} /></label><label className="checkbox-row text-sm"><input type="checkbox" checked={protectedFields.includes(key)} onChange={e => setProtectedFields(e.target.checked ? [...protectedFields, key] : protectedFields.filter(field => field !== key))} />{label}をWeb再解析から保護</label></div>)}</div></div>
      <div className="actions"><button disabled={busy} onClick={() => void saveCompany()}>企業情報を保存</button></div>
      <div className="detail-grid"><div><h3>連絡禁止・除外</h3><label className="checkbox-row"><input type="checkbox" checked={doNotContact} onChange={e => setDoNotContact(e.target.checked)} />この企業への連絡を禁止</label><label className="field">除外理由<input maxLength={500} required={doNotContact} value={exclusionReason} onChange={e => setExclusionReason(e.target.value)} placeholder="例：連絡拒否、既存顧客、競合" /></label></div><div><h3>連絡先品質</h3><label className="field">確認状態<select value={contactQuality} onChange={e => setContactQuality(e.target.value as Company['contact_quality_status'])}><option value="unknown">未確認</option><option value="observed">Web取得済み</option><option value="verified">人手確認済み</option><option value="invalid">無効</option></select></label><p className="muted text-sm">取得元：{selected.contact_source_url || '未記録'}</p><p className="muted text-sm">最終確認：{selected.contact_checked_at ? new Date(selected.contact_checked_at).toLocaleString('ja-JP') : '未確認'}</p></div></div><div className="actions"><button disabled={busy || (doNotContact && !exclusionReason.trim())} onClick={() => void saveContactControl()}>連絡制御を保存</button></div>
      <div className="detail-grid"><div><h3>AI分析</h3><p><strong>{selected.rank ?? '未判定'} / {selected.score ?? '—'}点</strong> {selected.business_type}</p><p>{selected.ai_summary || 'AI要約はありません。'}</p><p className="muted">{selected.ai_reason}</p></div><div><h3>強み・懸念</h3><p>{selected.ai_strengths.join(' / ') || '—'}</p><p className="muted">{selected.ai_concerns.join(' / ') || '—'}</p><p>推奨：{selected.ai_recommended_approach || '—'}</p></div></div>
      <div className="mt-5"><h3>Web解析ページ</h3>{selected.scraped_urls.length === 0 ? <p className="muted text-sm">解析ページの記録はありません。</p> : <ul className="mt-2 list-disc pl-5 text-sm">{selected.scraped_urls.map(url => <li className="break-all" key={url}><a href={url} target="_blank" rel="noreferrer">{url}</a></li>)}</ul>}</div>
      <div className="detail-grid"><div><label className="field">営業状況<select value={status} onChange={e => setStatus(e.target.value as SalesStatus)}>{Object.entries(statusNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="field">次回対応日時<input type="datetime-local" value={followup} onChange={e => setFollowup(e.target.value)} /></label></div><label className="field">メモ<textarea rows={5} maxLength={20000} value={notes} onChange={e => setNotes(e.target.value)} /></label></div>
      <div className="actions"><button disabled={busy} onClick={() => void save()}>{busy ? '保存中…' : '営業状況を保存'}</button></div></section>}
    {selected && <CompanyContactsPanel
      contacts={contacts}
      contactDraft={contactDraft}
      editingContactId={editingContactId}
      busy={busy}
      onEdit={editContact}
      onDelete={contact => void deleteContactPerson(contact)}
      onDraftChange={setContactDraft}
      onSave={() => void saveContactPerson()}
      onCancel={() => { setEditingContactId(''); setContactDraft(emptyContact) }}
    />}
    {selected && <section className="panel mt-7" aria-label="営業文面"><div className="flex items-center justify-between gap-3"><div><h2>営業文面</h2><p className="muted mt-2 text-sm">企業分析を基に下書きを生成します。内容を確認・編集してから使用してください。</p></div><span className="badge">{outreachDrafts.length} 件</span></div>
      <div className="detail-grid mt-4"><div><label className="field">連絡経路<select value={draftChannel} onChange={e => setDraftChannel(e.target.value as OutreachDraft['channel'])}><option value="email">メール</option><option value="form">問い合わせフォーム</option><option value="sns">SNS</option></select></label><label className="field">宛先担当者<select value={draftContactId} onChange={e => setDraftContactId(e.target.value)}><option value="">担当者指定なし</option>{contacts.filter(contact => contact.verification_status !== 'invalid').map(contact => <option value={contact.id} key={contact.id}>{contact.name}{contact.title ? `（${contact.title}）` : ''}</option>)}</select></label></div><label className="field">追加指示<textarea rows={4} maxLength={1000} value={draftInstruction} onChange={e => setDraftInstruction(e.target.value)} placeholder="例：初回連絡なので短く、無料相談を案内" /></label></div><div className="actions"><button disabled={busy || selected.do_not_contact || selected.ai_status !== 'completed'} onClick={() => void generateDraft()}>{busy ? '生成中…' : '文面を生成'}</button></div>{selected.do_not_contact && <p className="error">連絡禁止の企業には文面を生成できません。</p>}{selected.ai_status !== 'completed' && <p className="muted text-sm">文面生成にはAI企業分析の完了が必要です。</p>}
      {outreachDrafts.length > 0 && <div className="flex flex-wrap gap-2 mt-5">{outreachDrafts.map(draft => <button className={selectedDraft?.id === draft.id ? '' : 'secondary'} key={draft.id} onClick={() => void selectDraft(draft)}>{draft.channel === 'email' ? 'メール' : draft.channel === 'form' ? 'フォーム' : 'SNS'}・{new Date(draft.created_at).toLocaleString('ja-JP')}</button>)}</div>}
      {selectedDraft && <div className="mt-5">{selectedDraft.channel === 'email' && <label className="field">件名<input maxLength={300} value={selectedDraft.subject} onChange={e => setSelectedDraft({ ...selectedDraft, subject: e.target.value })} /></label>}<label className="field">本文<textarea rows={12} maxLength={10000} value={selectedDraft.body} onChange={e => setSelectedDraft({ ...selectedDraft, body: e.target.value })} /></label><p className="muted text-sm">生成：{selectedDraft.ai_provider} / {selectedDraft.ai_model}</p><div className="actions"><button disabled={busy || !selectedDraft.body.trim()} onClick={() => void saveDraft()}>編集内容を保存</button><button className="secondary" onClick={() => void copyDraft()}>コピー</button><button className="danger" disabled={busy} onClick={() => void deleteDraft()}>削除</button></div>
        <div className="mt-5"><h3>文面テンプレート</h3><div className="actions"><input aria-label="テンプレート名" maxLength={200} value={templateName} onChange={e => setTemplateName(e.target.value)} placeholder="例：初回メール" /><button disabled={busy || !templateName.trim()} onClick={() => void saveTemplate()}>現在の文面を保存</button></div>{outreachTemplates.filter(template => template.channel === selectedDraft.channel).length === 0 ? <p className="muted text-sm">この連絡経路のテンプレートはありません。</p> : <div className="grid gap-2 mt-3">{outreachTemplates.filter(template => template.channel === selectedDraft.channel).map(template => <article className="job-row" key={template.id}><div><strong>{template.name}</strong><p className="muted text-xs">{template.subject || '件名なし'} / {template.body.slice(0, 80)}</p></div><div className="actions"><button className="secondary" disabled={busy} onClick={() => void applyTemplate(template)}>適用</button><button className="danger" disabled={busy} onClick={() => void deleteTemplate(template)}>削除</button></div></article>)}</div>}</div>
        <div className="mt-5"><h3>承認履歴</h3>{draftApprovals.length === 0 ? <p className="muted text-sm">まだ承認履歴はありません。</p> : draftApprovals.map(approval => <article className="job-row" key={approval.id}><div><strong>{approval.approval_type === 'email' ? 'メール送信承認' : approval.approval_type === 'form_direct' ? 'フォーム送信承認' : 'Codex支援フォーム承認'}</strong><p className="muted text-xs">{approval.subject || '件名なし'} / {approval.body.slice(0, 120)}</p></div><time className="muted text-xs">{approval.delivered_at ? `送信済み ${new Date(approval.delivered_at).toLocaleString('ja-JP')}` : `承認 ${new Date(approval.approved_at).toLocaleString('ja-JP')}`}</time></article>)}</div>
        {selectedDraft.channel === 'email' && <div className="mt-6"><h3>メール送信</h3>{emailDelivery ? <><p className="muted text-sm">宛先：{emailDelivery.recipient_name ? `${emailDelivery.recipient_name} / ` : ''}{emailDelivery.recipient_email}</p><p className="muted text-sm">状態：{emailDelivery.status === 'queued' ? '送信待ち' : emailDelivery.status === 'running' ? '送信中' : emailDelivery.status === 'sent' ? '送信済み' : emailDelivery.status === 'failed' ? '失敗' : 'キャンセル済み'}{emailDelivery.sent_at ? `（${new Date(emailDelivery.sent_at).toLocaleString('ja-JP')}）` : ''}</p>{emailDelivery.error_message && <p className="error">{emailDelivery.error_message}</p>}{emailDelivery.status === 'queued' && <div className="actions"><button className="danger" disabled={busy} onClick={() => void cancelEmailDelivery()}>送信予約をキャンセル</button></div>}{emailDelivery.status === 'failed' && <><label className="field">再送日時（空欄ならすぐ送信）<input type="datetime-local" value={deliverySchedule} onChange={e => setDeliverySchedule(e.target.value)} /></label><label className="checkbox-row"><input type="checkbox" checked={deliveryConfirmed} onChange={e => setDeliveryConfirmed(e.target.checked)} />宛先・件名・本文を確認し、このメールの再送を承認します。</label><div className="actions"><button disabled={busy || !deliveryConfirmed} onClick={() => void retryEmailDelivery()}>再送を予約</button></div></>}</> : <><div className="detail-grid"><label className="field">送信先<select value={deliveryRecipient} onChange={e => setDeliveryRecipient(e.target.value)}><option value="">選択してください</option>{selected.email && <option value={selected.email}>{selected.company_name}（代表）: {selected.email}</option>}{contacts.filter(contact => contact.email && contact.verification_status !== 'invalid').map(contact => <option value={contact.email} key={contact.id}>{contact.name}: {contact.email}</option>)}</select></label><label className="field">送信日時（空欄ならすぐ送信）<input type="datetime-local" value={deliverySchedule} onChange={e => setDeliverySchedule(e.target.value)} /></label></div><label className="checkbox-row"><input type="checkbox" checked={deliveryConfirmed} onChange={e => setDeliveryConfirmed(e.target.checked)} />宛先・件名・本文を確認し、このメールの送信を承認します。</label><div className="actions"><button disabled={busy || !deliveryRecipient || !deliveryConfirmed || selected.do_not_contact} onClick={() => void scheduleEmailDelivery()}>送信を承認</button></div></>}</div>}
        {selectedDraft.channel === 'form' && <div className="mt-6">
          <h3>フォーム送信</h3>
          <p className="muted text-sm">通常フォームはこの画面から送信できます。CAPTCHAや複数画面のフォームはCodex支援へ引き渡します。</p>
          {formDelivery ? <div className="mt-4">
            <p className="muted text-sm">送信方法：{formDelivery.delivery_method === 'direct' ? 'LeadHive通常フォーム' : 'Codex支援'}</p>
            <p className="muted text-sm">状態：{formDelivery.status === 'submitted' ? '送信済み' : formDelivery.status === 'failed' ? '失敗' : '保留'}</p>
            {formDelivery.result_note && <p className="muted text-sm">メモ：{formDelivery.result_note}</p>}
            {formDelivery.delivery_method === 'codex_assisted' && formDelivery.status !== 'submitted' && <div className="mt-4">
              <label className="field">結果<select value={assistOutcome} onChange={e => setAssistOutcome(e.target.value as FormDelivery['status'])}><option value="pending">保留</option><option value="submitted">送信済み</option><option value="failed">失敗</option></select></label>
              <label className="field">メモ<textarea rows={3} maxLength={500} value={assistNote} onChange={e => setAssistNote(e.target.value)} placeholder="例：CAPTCHAが解けず保留" /></label>
              <label className="checkbox-row"><input type="checkbox" checked={assistConfirmed} onChange={e => setAssistConfirmed(e.target.checked)} />Codex上で確認した結果を記録します。</label>
              <div className="actions"><button disabled={busy || !assistConfirmed} onClick={() => void recordFormAssistDelivery()}>Codex支援の結果を記録</button></div>
            </div>}
          </div> : <>
            <div className="actions"><button className="secondary" disabled={busy || selected.do_not_contact} onClick={() => void copyFormAssist()}>Codex支援用の指示をコピー</button></div>
            <div className="mt-4"><h4>Codex支援の送信結果</h4>
              <label className="field">結果<select value={assistOutcome} onChange={e => setAssistOutcome(e.target.value as FormDelivery['status'])}><option value="pending">保留</option><option value="submitted">送信済み</option><option value="failed">失敗</option></select></label>
              <label className="field">メモ<textarea rows={3} maxLength={500} value={assistNote} onChange={e => setAssistNote(e.target.value)} placeholder="例：CAPTCHAが解けず保留" /></label>
              <label className="checkbox-row"><input type="checkbox" checked={assistConfirmed} onChange={e => setAssistConfirmed(e.target.checked)} />Codex上で確認した結果を記録します。</label>
              <div className="actions"><button disabled={busy || !assistConfirmed || selected.do_not_contact} onClick={() => void recordFormAssistDelivery()}>Codex支援の結果を記録</button></div>
            </div>
            {!formPreview ? <div className="actions"><button className="secondary" disabled={busy || selected.do_not_contact} onClick={() => void inspectForm()}>フォーム項目を確認</button></div> : <>
              <p className="muted text-xs mt-3 break-all">送信先: {formPreview.form_url}</p>
              <div className="detail-grid mt-3">{formPreview.fields.map(field => <label className="field" key={field.name}>{field.label}{field.required && ' *'}{field.field_type === 'textarea' ? <textarea rows={5} value={formValues[field.name] ?? ''} onChange={e => setFormValues({ ...formValues, [field.name]: e.target.value })} /> : field.field_type === 'select' ? <select value={formValues[field.name] ?? ''} onChange={e => setFormValues({ ...formValues, [field.name]: e.target.value })}><option value="">選択してください</option>{field.options.map(option => <option value={option} key={option}>{option}</option>)}</select> : <input type={field.field_type} value={formValues[field.name] ?? ''} onChange={e => setFormValues({ ...formValues, [field.name]: e.target.value })} />}</label>)}</div>
              <label className="checkbox-row mt-4"><input type="checkbox" checked={formConfirmed} onChange={e => setFormConfirmed(e.target.checked)} />入力内容と送信先を確認し、このフォーム送信を承認します。</label>
              <div className="actions"><button disabled={busy || !formConfirmed || selected.do_not_contact} onClick={() => void submitForm()}>フォームを送信</button></div>
            </>}
          </>}
        </div>}
      </div>}
    </section>}
    {selected && <section className="panel mt-7"><h2>AI判定レビュー</h2><p className="muted mt-2 text-sm">実際の営業対象としての妥当性を記録し、検索語ごとの精度改善に使います。</p><div className="detail-grid mt-4"><label className="field">判定<select value={aiReviewVerdict} onChange={e => setAiReviewVerdict(e.target.value as 'correct' | 'incorrect')}><option value="correct">正しい</option><option value="incorrect">誤り</option></select></label><label className="field">レビュー理由<textarea rows={3} maxLength={5000} value={aiReviewNote} onChange={e => setAiReviewNote(e.target.value)} placeholder="例：対象業種ではない、決裁者が明確" /></label></div><div className="actions"><button disabled={busy} onClick={() => void saveAiReview()}>レビューを保存</button></div>{aiReview && <p className="muted text-sm mt-3">最終レビュー：{aiReview.verdict === 'correct' ? '正しい' : '誤り'} / {new Date(aiReview.updated_at).toLocaleString('ja-JP')}</p>}</section>}
    {selected && <section className="panel mt-7"><h2>案件管理</h2><p className="muted mt-2 text-sm">商談後の見込み、次の対応、受注・失注を企業ごとに記録します。</p><div className="detail-grid mt-4"><label className="field">案件名<input maxLength={300} value={dealTitle} onChange={e => setDealTitle(e.target.value)} placeholder="例：採用支援サービス導入" /></label><label className="field">段階<select value={dealStage} onChange={e => setDealStage(e.target.value as Deal['stage'])}><option value="lead">見込み</option><option value="proposal">提案</option><option value="negotiation">交渉</option><option value="won">受注</option><option value="lost">失注</option></select></label><label className="field">見込金額（円）<input type="number" min={0} value={dealAmount} onChange={e => setDealAmount(Number(e.target.value))} /></label><label className="field">受注見込日<input type="date" value={dealCloseDate} onChange={e => setDealCloseDate(e.target.value)} /></label><label className="field">担当者<input maxLength={200} value={dealOwner} onChange={e => setDealOwner(e.target.value)} /></label><label className="field">次の対応<textarea rows={2} maxLength={5000} value={dealNextStep} onChange={e => setDealNextStep(e.target.value)} /></label>{dealStage === 'lost' && <label className="field">失注理由<textarea rows={2} maxLength={500} value={dealLostReason} onChange={e => setDealLostReason(e.target.value)} /></label>}</div><div className="actions"><button disabled={busy || !dealTitle.trim()} onClick={() => void createDeal()}>案件を追加</button></div>{deals.map(deal => <article className="job-row" key={deal.id}><div><strong>{deal.title}</strong><p className="muted text-sm">{({ lead: '見込み', proposal: '提案', negotiation: '交渉', won: '受注', lost: '失注' }[deal.stage])} / {deal.expected_amount.toLocaleString()}円 / {deal.owner || '担当未設定'}</p>{deal.next_step && <p className="text-sm">次の対応：{deal.next_step}</p>}</div><span className="badge">{deal.expected_close_date || '日付未設定'}</span></article>)}{deals.length === 0 && <p className="muted mt-4">登録済み案件はありません。</p>}</section>}
    {selected && <section className="panel mt-7"><h2>営業文面 A/Bテスト</h2><p className="muted mt-2 text-sm">同じ種別のテンプレートを2案用意し、企業IDで均等に割り当てます。送信後の返信・商談・成約を案ごとに比較します。</p><div className="detail-grid mt-4"><label className="field">テスト名<input maxLength={200} value={experimentName} onChange={e => setExperimentName(e.target.value)} placeholder="例：9月件名比較" /></label><label className="field">A案<select value={experimentA} onChange={e => setExperimentA(e.target.value)}><option value="">選択してください</option>{outreachTemplates.map(template => <option key={template.id} value={template.id}>{template.name}</option>)}</select></label><label className="field">B案<select value={experimentB} onChange={e => setExperimentB(e.target.value)}><option value="">選択してください</option>{outreachTemplates.map(template => <option key={template.id} value={template.id}>{template.name}</option>)}</select></label></div><div className="actions"><button disabled={busy || !experimentName.trim() || !experimentA || !experimentB || experimentA === experimentB} onClick={() => void createExperiment()}>A/Bテストを作成</button></div><div className="detail-grid mt-4"><label className="field">利用するA/Bテスト<select value={experimentId} onChange={e => void loadExperimentResults(e.target.value)}><option value="">選択してください</option>{experiments.filter(item => item.active).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><div className="actions self-end"><button className="secondary" disabled={busy || !selectedDraft || !experimentId} onClick={() => void applyExperiment()}>現在の文面へ均等割当を適用</button></div></div>{experimentId && <div className="company-table-wrap mt-4"><table className="company-table"><thead><tr><th>案</th><th>送信済み</th><th>返信</th><th>商談</th><th>成約</th><th>返信率</th></tr></thead><tbody>{experimentResults.map(item => <tr key={item.variant}><td>{item.variant}案</td><td>{item.delivered}</td><td>{item.replied}</td><td>{item.meetings}</td><td>{item.won}</td><td>{item.reply_rate}%</td></tr>)}</tbody></table></div>}</section>}
    {selected && <section className="panel mt-7"><h2>活動履歴</h2><div className="detail-grid"><label className="field">活動種別<select value={activityType} onChange={e => setActivityType(e.target.value)}><option value="note">メモ</option><option value="call">電話</option><option value="email">メール</option><option value="form">フォーム</option><option value="sns">SNS</option><option value="meeting">商談</option></select></label><label className="field">活動内容<textarea rows={3} value={activityNote} onChange={e => setActivityNote(e.target.value)} /></label></div><div className="actions"><button disabled={busy || !activityNote.trim()} onClick={() => void addActivity()}>履歴を追加</button></div>{activities.map(item => <article className="job-row" key={item.id}><div><strong>{item.activity_type}</strong><p>{item.note}</p></div><time className="muted text-sm">{new Date(item.created_at).toLocaleString('ja-JP')}</time></article>)}</section>}
  </>
}
