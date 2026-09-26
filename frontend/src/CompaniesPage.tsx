import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, download, errorMessage } from './api'
import { CompanyActivitiesPanel } from './CompanyActivitiesPanel'
import { CompanyCodexFormQueue } from './CompanyCodexFormQueue'
import { CompanyContactsPanel } from './CompanyContactsPanel'
import { CompanyDealsPanel } from './CompanyDealsPanel'
import { CompanyDetailsPanel } from './CompanyDetailsPanel'
import { CompanyFilters } from './CompanyFilters'
import { CompanyFollowupTasksPanel } from './CompanyFollowupTasksPanel'
import { CompanyFormDeliveryPanel } from './CompanyFormDeliveryPanel'
import { CompanyFormBatchesPanel } from './CompanyFormBatchesPanel'
import { CompanyFormIntelligencePanel } from './CompanyFormIntelligencePanel'
import { CompanyEmailDeliveryPanel } from './CompanyEmailDeliveryPanel'
import { CompanyEmailCampaignsPanel } from './CompanyEmailCampaignsPanel'
import { CompanyList } from './CompanyList'
import { AssigneeAnalyticsPanel, DealPipelinePanel } from './CompanyReportingPanels'
import { CompanyQualityPanels } from './CompanyQualityPanels'
import { CompanyOutreachQueuePanel } from './CompanyOutreachQueuePanel'
import { CompanyOutreachDraftPanel } from './CompanyOutreachDraftPanel'
import { CompanyReplyQueuePanel } from './CompanyReplyQueuePanel'
import { CompanySavedFiltersPanel } from './CompanySavedFiltersPanel'
import { CompanyAiReviewPanel, CompanyExperimentPanel } from './CompanyOptimizationPanels'
import { companyQueryString, defaultCompanyFilters, emptyContact } from './companyPageShared'
import type { Activity, AiReview, Deal, DealPipeline, EmailCampaign, FormCodexTask, FormDeliveryBatch, OutreachExperiment, OutreachExperimentResult, AnalysisRefreshSchedule, AssigneeAnalytics, Company, CompanyFilterValues, CompanyPage, ContactPerson, DataQuality, DuplicateCandidate, EmailDelivery, FollowupTask, FormAnalysisLog, FormAssist, FormDelivery, FormMappedKey, FormPreview, FormProfile, FormProfileField, FormProfileSummary, OperationJob, OutreachChannel, OutreachDraft, OutreachDraftApproval, OutreachQueueItem, OutreachTemplate, Project, ReplyQueueItem, SalesStatus, SavedCompanyFilter } from './types'

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
  const [formProfileSummaries, setFormProfileSummaries] = useState<Record<string, FormProfileSummary>>({})
  const [formProfiles, setFormProfiles] = useState<FormProfile[]>([])
  const [formAnalysisLogs, setFormAnalysisLogs] = useState<FormAnalysisLog[]>([])
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
  const query = useMemo(() => companyQueryString(filters, page), [filters, page])
  const reload = useCallback(async () => {
    if (!projectId) { setCompanies([]); setSavedFilters([]); setAssigneeAnalytics([]); setOutreachQueue([]); setFollowupTasks([]); setReplyQueue([]); setFormBatches([]); setFormCodexTasks([]); setEmailCampaigns([]); setFormProfileSummaries({}); setDealPipeline(null); return }
    const [result, nextQuality, nextDuplicates, nextSavedFilters, nextAssigneeAnalytics, nextOutreachQueue, nextFollowupTasks, nextReplyQueue, nextRefreshSchedule, nextFormBatches, nextOutreachTemplates, nextEmailCampaigns, nextFormCodexTasks, nextDealPipeline, nextFormProfileSummaries] = await Promise.all([
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
      api<FormProfileSummary[]>(`/projects/${projectId}/form-profiles/summary`),
    ])
    setCompanies(result.items); setTotal(result.total); setQuality(nextQuality)
    setDuplicates(nextDuplicates); setSavedFilters(nextSavedFilters)
    setAssigneeAnalytics(nextAssigneeAnalytics); setOutreachQueue(nextOutreachQueue); setFollowupTasks(nextFollowupTasks); setReplyQueue(nextReplyQueue); setChecked([])
    setFormBatches(nextFormBatches); setFormCodexTasks(nextFormCodexTasks); setOutreachTemplates(nextOutreachTemplates); setEmailCampaigns(nextEmailCampaigns); setDealPipeline(nextDealPipeline); setRefreshSchedule(nextRefreshSchedule)
    setFormProfileSummaries(Object.fromEntries(nextFormProfileSummaries.map(item => [item.company_id, item])))
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
    if (!selected) {
      setAiReview(null); setDeals([]); setExperiments([]); setExperimentResults([]); setFormProfiles([]); setFormAnalysisLogs([])
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
    const [nextActivities, nextContacts, nextDrafts, nextTemplates, nextFormProfiles] = await Promise.all([
      api<Activity[]>(`/companies/${company.id}/activities`),
      api<ContactPerson[]>(`/companies/${company.id}/contacts`),
      api<OutreachDraft[]>(`/companies/${company.id}/outreach-drafts`),
      api<OutreachTemplate[]>(`/projects/${company.project_id}/outreach-templates`),
      api<FormProfile[]>(`/companies/${company.id}/form-profiles`),
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
    setFormProfiles(nextFormProfiles)
    const primaryProfile = nextFormProfiles.find(item => item.is_primary) ?? nextFormProfiles[0]
    setFormAnalysisLogs(primaryProfile ? await api<FormAnalysisLog[]>(`/form-profiles/${primaryProfile.id}/logs`) : [])
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
  async function loadSelectedFormProfiles(company: Company) {
    const profiles = await api<FormProfile[]>(`/companies/${company.id}/form-profiles`)
    setFormProfiles(profiles)
    const primary = profiles.find(item => item.is_primary) ?? profiles[0]
    setFormAnalysisLogs(primary ? await api<FormAnalysisLog[]>(`/form-profiles/${primary.id}/logs`) : [])
    if (primary) {
      setFormProfileSummaries(current => ({ ...current, [company.id]: {
        company_id: company.id, profile_id: primary.id, form_status: primary.form_status,
        form_found: primary.form_found, sales_contact_status: primary.sales_contact_status,
        captcha_type: primary.captcha_type, last_analyzed_at: primary.last_analyzed_at,
      } }))
    }
  }
  async function analyzeSelectedForm() {
    if (!selected) return
    setBusy(true); setError(''); setNotice('')
    try {
      const profiles = await api<FormProfile[]>(`/companies/${selected.id}/form-intelligence/analyze`, 'POST')
      setFormProfiles(profiles)
      const primary = profiles.find(item => item.is_primary) ?? profiles[0]
      setFormAnalysisLogs(primary ? await api<FormAnalysisLog[]>(`/form-profiles/${primary.id}/logs`) : [])
      if (primary) setFormProfileSummaries(current => ({ ...current, [selected.id]: { company_id: selected.id, profile_id: primary.id, form_status: primary.form_status, form_found: primary.form_found, sales_contact_status: primary.sales_contact_status, captcha_type: primary.captcha_type, last_analyzed_at: primary.last_analyzed_at } }))
      setNotice(`${profiles.length}件のフォーム候補を解析しました。`)
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function enqueueSelectedFormAnalysis() {
    if (!projectId || checked.length === 0) return
    setBusy(true); setError(''); setNotice('')
    try {
      const job = await api<OperationJob>(`/projects/${projectId}/form-intelligence/jobs`, 'POST', { company_ids: checked, force: false })
      setNotice(`${checked.length}社のフォーム解析を登録しました（ジョブ ${job.id.slice(0, 8)}）。`)
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function selectPrimaryForm(profile: FormProfile) {
    if (!selected) return
    setBusy(true); setError(''); setNotice('')
    try {
      await api<FormProfile>(`/form-profiles/${profile.id}/select-primary`, 'POST')
      await loadSelectedFormProfiles(selected)
      setNotice('優先フォームを変更しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function correctFormField(field: FormProfileField, mappedKey: FormMappedKey, recommendedValue: string) {
    if (!selected) return
    setBusy(true); setError(''); setNotice('')
    try {
      await api<FormProfileField>(`/form-profile-fields/${field.id}`, 'PATCH', { mapped_key: mappedKey, recommended_value: recommendedValue, reason: '管理画面で修正' })
      await loadSelectedFormProfiles(selected)
      setNotice('フォーム項目の判定を修正しました。')
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
    <CompanyEmailCampaignsPanel
      selectedCount={checked.length}
      templates={outreachTemplates}
      campaigns={emailCampaigns}
      name={emailCampaignName}
      templateId={emailCampaignTemplateId}
      followupDays={emailCampaignFollowupDays}
      confirmed={emailCampaignConfirmed}
      busy={busy}
      onNameChange={setEmailCampaignName}
      onTemplateChange={setEmailCampaignTemplateId}
      onFollowupDaysChange={setEmailCampaignFollowupDays}
      onConfirmedChange={setEmailCampaignConfirmed}
      onCreate={() => void createEmailCampaign()}
      onChangeCampaign={(campaign, action) => void changeEmailCampaign(campaign, action)}
    />
    <CompanyCodexFormQueue items={formCodexTasks} busy={busy} onCopy={task => void copyBatchCodexTask(task)} onUpdate={(task, status) => void updateFormCodexTask(task, status)} />
    <CompanyFormBatchesPanel selectedCount={checked.length} templates={outreachTemplates} templateId={formBatchTemplateId} batches={formBatches} confirmed={formBatchConfirmed} busy={busy} onTemplateChange={setFormBatchTemplateId} onConfirmedChange={setFormBatchConfirmed} onCreate={() => void createFormBatch()} onExecute={batch => void executeFormBatch(batch)} onCancel={batch => void cancelFormBatch(batch)} onRetry={itemId => void retryFormBatchItem(itemId)} />
    <CompanyReplyQueuePanel
      items={replyQueue}
      target={replyTarget}
      outcome={replyOutcome}
      note={replyNote}
      followup={replyFollowup}
      busy={busy}
      onStart={startReply}
      onOutcomeChange={setReplyOutcome}
      onNoteChange={setReplyNote}
      onFollowupChange={setReplyFollowup}
      onRecord={() => void recordReplyResponse()}
      onCancel={() => setReplyTarget(null)}
    />
    <CompanyFollowupTasksPanel
      items={followupTasks}
      target={followupTarget}
      action={followupAction}
      note={followupTaskNote}
      scheduledAt={followupTaskDate}
      busy={busy}
      onStart={startFollowupTask}
      onActionChange={setFollowupAction}
      onNoteChange={setFollowupTaskNote}
      onScheduledAtChange={setFollowupTaskDate}
      onResolve={() => void resolveFollowupTask()}
      onCancel={() => setFollowupTarget(null)}
    />
    <CompanyOutreachQueuePanel
      items={outreachQueue}
      target={outreachTarget}
      channel={outreachChannel}
      outcome={outreachOutcome}
      note={outreachNote}
      followup={outreachFollowup}
      busy={busy}
      onStart={startOutreach}
      onChannelChange={setOutreachChannel}
      onOutcomeChange={setOutreachOutcome}
      onNoteChange={setOutreachNote}
      onFollowupChange={setOutreachFollowup}
      onRecord={() => void recordOutreach()}
      onCancel={() => setOutreachTarget(null)}
    />
    <CompanySavedFiltersPanel
      items={savedFilters}
      currentFilters={filters}
      filterName={filterName}
      editingId={editingFilterId}
      editingName={editingFilterName}
      busy={busy}
      onFilterNameChange={setFilterName}
      onEditingNameChange={setEditingFilterName}
      onSave={() => void saveFilter()}
      onApply={nextFilters => { setDraft(nextFilters); setFilters(nextFilters); setPage(0) }}
      onOverwrite={item => void updateFilter(item, item.name, filters)}
      onStartRename={item => { setEditingFilterId(item.id); setEditingFilterName(item.name) }}
      onCancelRename={() => setEditingFilterId('')}
      onRename={item => void updateFilter(item, editingFilterName, item.filters)}
      onDelete={item => void deleteFilter(item.id)}
    />
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
      formProfiles={formProfileSummaries}
      setChecked={setChecked}
      setBulkAssignee={setBulkAssignee}
      setPage={setPage}
      onBulkStatus={nextStatus => void bulkStatus(nextStatus)}
      onAssign={() => void assignSelected()}
      onAnalyzeSelected={() => void enqueueSelectedFormAnalysis()}
      onOpen={company => void open(company)}
    />
    {selected && <CompanyDetailsPanel
      company={selected}
      values={companyEdit}
      protectedFields={protectedFields}
      doNotContact={doNotContact}
      exclusionReason={exclusionReason}
      contactQuality={contactQuality}
      status={status}
      note={notes}
      followup={followup}
      busy={busy}
      onValuesChange={setCompanyEdit}
      onProtectedFieldsChange={setProtectedFields}
      onDoNotContactChange={setDoNotContact}
      onExclusionReasonChange={setExclusionReason}
      onContactQualityChange={setContactQuality}
      onStatusChange={setStatus}
      onNoteChange={setNotes}
      onFollowupChange={setFollowup}
      onSaveCompany={() => void saveCompany()}
      onSaveContactControl={() => void saveContactControl()}
      onSaveStatus={() => void save()}
      onClose={() => setSelected(null)}
    />}
    {selected && <CompanyFormIntelligencePanel
      company={selected}
      profiles={formProfiles}
      logs={formAnalysisLogs}
      busy={busy}
      onAnalyze={() => void analyzeSelectedForm()}
      onSelectPrimary={profile => void selectPrimaryForm(profile)}
      onCorrect={(field, mappedKey, recommendedValue) => void correctFormField(field, mappedKey, recommendedValue)}
    />}
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
    {selected && <CompanyOutreachDraftPanel
      company={selected}
      contacts={contacts}
      drafts={outreachDrafts}
      selectedDraft={selectedDraft}
      templates={outreachTemplates}
      approvals={draftApprovals}
      channel={draftChannel}
      contactId={draftContactId}
      instruction={draftInstruction}
      templateName={templateName}
      busy={busy}
      onChannelChange={setDraftChannel}
      onContactChange={setDraftContactId}
      onInstructionChange={setDraftInstruction}
      onTemplateNameChange={setTemplateName}
      onSelectedDraftChange={setSelectedDraft}
      onGenerate={() => void generateDraft()}
      onSelect={draft => void selectDraft(draft)}
      onSave={() => void saveDraft()}
      onCopy={() => void copyDraft()}
      onDelete={() => void deleteDraft()}
      onSaveTemplate={() => void saveTemplate()}
      onApplyTemplate={template => void applyTemplate(template)}
      onDeleteTemplate={template => void deleteTemplate(template)}
    >
        {selectedDraft?.channel === 'email' && <CompanyEmailDeliveryPanel
          company={selected}
          contacts={contacts}
          delivery={emailDelivery}
          recipient={deliveryRecipient}
          scheduledAt={deliverySchedule}
          confirmed={deliveryConfirmed}
          busy={busy}
          onRecipientChange={setDeliveryRecipient}
          onScheduledAtChange={setDeliverySchedule}
          onConfirmedChange={setDeliveryConfirmed}
          onSchedule={() => void scheduleEmailDelivery()}
          onCancel={() => void cancelEmailDelivery()}
          onRetry={() => void retryEmailDelivery()}
        />}
        {selectedDraft?.channel === 'form' && <CompanyFormDeliveryPanel
          company={selected}
          delivery={formDelivery}
          preview={formPreview}
          values={formValues}
          confirmed={formConfirmed}
          assistOutcome={assistOutcome}
          assistNote={assistNote}
          assistConfirmed={assistConfirmed}
          busy={busy}
          onValuesChange={setFormValues}
          onConfirmedChange={setFormConfirmed}
          onAssistOutcomeChange={setAssistOutcome}
          onAssistNoteChange={setAssistNote}
          onAssistConfirmedChange={setAssistConfirmed}
          onRecordAssist={() => void recordFormAssistDelivery()}
          onCopyAssist={() => void copyFormAssist()}
          onInspect={() => void inspectForm()}
          onSubmit={() => void submitForm()}
        />}
    </CompanyOutreachDraftPanel>}
    {selected && <CompanyAiReviewPanel
      review={aiReview}
      verdict={aiReviewVerdict}
      note={aiReviewNote}
      busy={busy}
      onVerdictChange={setAiReviewVerdict}
      onNoteChange={setAiReviewNote}
      onSave={() => void saveAiReview()}
    />}
    {selected && <CompanyDealsPanel
      deals={deals}
      title={dealTitle}
      stage={dealStage}
      amount={dealAmount}
      closeDate={dealCloseDate}
      owner={dealOwner}
      nextStep={dealNextStep}
      lostReason={dealLostReason}
      busy={busy}
      onTitleChange={setDealTitle}
      onStageChange={setDealStage}
      onAmountChange={setDealAmount}
      onCloseDateChange={setDealCloseDate}
      onOwnerChange={setDealOwner}
      onNextStepChange={setDealNextStep}
      onLostReasonChange={setDealLostReason}
      onCreate={() => void createDeal()}
    />}
    {selected && <CompanyExperimentPanel
      templates={outreachTemplates}
      experiments={experiments}
      results={experimentResults}
      hasSelectedDraft={Boolean(selectedDraft)}
      name={experimentName}
      templateA={experimentA}
      templateB={experimentB}
      experimentId={experimentId}
      busy={busy}
      onNameChange={setExperimentName}
      onTemplateAChange={setExperimentA}
      onTemplateBChange={setExperimentB}
      onExperimentChange={id => void loadExperimentResults(id)}
      onCreate={() => void createExperiment()}
      onApply={() => void applyExperiment()}
    />}
    {selected && <CompanyActivitiesPanel
      activities={activities}
      activityType={activityType}
      activityNote={activityNote}
      busy={busy}
      onActivityTypeChange={setActivityType}
      onActivityNoteChange={setActivityNote}
      onAdd={() => void addActivity()}
    />}
  </>
}
