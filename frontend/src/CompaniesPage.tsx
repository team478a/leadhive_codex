import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, download, errorMessage } from './api'
import type { Activity, AssigneeAnalytics, CollectionSource, Company, CompanyFilterValues, CompanyPage, ContactPerson, DataQuality, DuplicateCandidate, OperationJob, OutreachChannel, OutreachQueueItem, Project, SalesStatus, SavedCompanyFilter } from './types'

const statusNames: Record<SalesStatus, string> = {
  unreviewed: '未確認', target: '営業対象', approached: 'アプローチ済', replied: '返信あり',
  meeting: '商談', won: '成約', lost: '失注', excluded: '対象外',
}
const sourceNames: Record<CollectionSource, string> = {
  serper: 'Google検索', google_places: 'Google Maps', url: 'URL', csv: 'CSV',
}
const channelNames: Record<OutreachChannel, string> = { email: 'メール', form: 'フォーム', call: '電話', sns: 'SNS' }
const dueNames = { overdue: '期限超過', today: '本日', upcoming: '今後', unset: '期限なし' }
const emptyContact = { name: '', department: '', title: '', email: '', phone: '', source_url: '', verification_status: 'unknown', notes: '' }
type Filters = CompanyFilterValues
const defaults: Filters = { rank: '', minScore: '', region: '', status: '', source: '', keyword: '', assignee: '', followup: '', sort: 'score_desc' }

function queryString(filters: Filters, page: number) {
  const params = new URLSearchParams({ limit: '25', offset: String(page * 25), sort: filters.sort })
  if (filters.rank) params.set('rank', filters.rank)
  if (filters.minScore) params.set('min_score', filters.minScore)
  if (filters.region) params.set('region', filters.region)
  if (filters.status) params.set('status', filters.status)
  if (filters.source) params.set('source', filters.source)
  if (filters.keyword) params.set('keyword', filters.keyword)
  if (filters.assignee) params.set('assignee', filters.assignee)
  if (filters.followup) params.set('followup', filters.followup)
  return params.toString()
}

export function CompaniesPage({ projects, initialProjectId }: { projects: Project[]; initialProjectId: string }) {
  const [projectId, setProjectId] = useState(initialProjectId || projects[0]?.id || '')
  const [draft, setDraft] = useState<Filters>(defaults)
  const [filters, setFilters] = useState<Filters>(defaults)
  const [companies, setCompanies] = useState<Company[]>([])
  const [total, setTotal] = useState(0)
  const [quality, setQuality] = useState<DataQuality | null>(null)
  const [duplicates, setDuplicates] = useState<DuplicateCandidate[]>([])
  const [savedFilters, setSavedFilters] = useState<SavedCompanyFilter[]>([])
  const [assigneeAnalytics, setAssigneeAnalytics] = useState<AssigneeAnalytics[]>([])
  const [outreachQueue, setOutreachQueue] = useState<OutreachQueueItem[]>([])
  const [outreachTarget, setOutreachTarget] = useState<OutreachQueueItem | null>(null)
  const [outreachChannel, setOutreachChannel] = useState<OutreachChannel>('email')
  const [outreachOutcome, setOutreachOutcome] = useState<SalesStatus>('approached')
  const [outreachNote, setOutreachNote] = useState('')
  const [outreachFollowup, setOutreachFollowup] = useState('')
  const [filterName, setFilterName] = useState('')
  const [editingFilterId, setEditingFilterId] = useState('')
  const [editingFilterName, setEditingFilterName] = useState('')
  const [staleDays, setStaleDays] = useState(90)
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
  const [activities, setActivities] = useState<Activity[]>([])
  const [contacts, setContacts] = useState<ContactPerson[]>([])
  const [contactDraft, setContactDraft] = useState<Record<string, string>>(emptyContact)
  const [editingContactId, setEditingContactId] = useState('')
  const [activityType, setActivityType] = useState('note')
  const [activityNote, setActivityNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const query = useMemo(() => queryString(filters, page), [filters, page])
  const reload = useCallback(async () => {
    if (!projectId) { setCompanies([]); setSavedFilters([]); setAssigneeAnalytics([]); setOutreachQueue([]); return }
    const [result, nextQuality, nextDuplicates, nextSavedFilters, nextAssigneeAnalytics, nextOutreachQueue] = await Promise.all([
      api<CompanyPage>(`/projects/${projectId}/company-list?${query}`),
      api<DataQuality>(`/projects/${projectId}/data-quality?stale_days=${staleDays}`),
      api<DuplicateCandidate[]>(`/projects/${projectId}/duplicate-candidates`),
      api<SavedCompanyFilter[]>(`/projects/${projectId}/saved-company-filters`),
      api<AssigneeAnalytics[]>(`/projects/${projectId}/assignee-analytics`),
      api<OutreachQueueItem[]>(`/projects/${projectId}/outreach-queue?limit=25`),
    ])
    setCompanies(result.items); setTotal(result.total); setQuality(nextQuality)
    setDuplicates(nextDuplicates); setSavedFilters(nextSavedFilters)
    setAssigneeAnalytics(nextAssigneeAnalytics); setOutreachQueue(nextOutreachQueue); setChecked([])
  }, [projectId, query, staleDays])
  useEffect(() => { reload().catch(e => setError(errorMessage(e))) }, [reload])
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
    const [nextActivities, nextContacts] = await Promise.all([
      api<Activity[]>(`/companies/${company.id}/activities`),
      api<ContactPerson[]>(`/companies/${company.id}/contacts`),
    ])
    setActivities(nextActivities); setContacts(nextContacts)
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
    <section className="panel"><div className="filter-grid">
      <label className="field">プロジェクト<select value={projectId} onChange={e => { setProjectId(e.target.value); setSelected(null); setPage(0) }}>{projects.map(project => <option key={project.id} value={project.id}>{project.project_name}</option>)}</select></label>
      <label className="field">キーワード<input value={draft.keyword} onChange={e => setDraft({ ...draft, keyword: e.target.value })} placeholder="会社名・業種・AI要約" /></label>
      <label className="field">ランク<select value={draft.rank} onChange={e => setDraft({ ...draft, rank: e.target.value })}><option value="">すべて</option>{['A', 'B', 'C', '対象外'].map(value => <option key={value}>{value}</option>)}</select></label>
      <label className="field">最低スコア<input type="number" min="0" max="100" value={draft.minScore} onChange={e => setDraft({ ...draft, minScore: e.target.value })} /></label>
      <label className="field">地域<input value={draft.region} onChange={e => setDraft({ ...draft, region: e.target.value })} /></label>
      <label className="field">営業状況<select value={draft.status} onChange={e => setDraft({ ...draft, status: e.target.value })}><option value="">すべて</option>{Object.entries(statusNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label className="field">収集元<select value={draft.source} onChange={e => setDraft({ ...draft, source: e.target.value })}><option value="">すべて</option>{Object.entries(sourceNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label className="field">担当者<input value={draft.assignee} onChange={e => setDraft({ ...draft, assignee: e.target.value })} /></label>
      <label className="field">フォロー期限<select value={draft.followup} onChange={e => setDraft({ ...draft, followup: e.target.value })}><option value="">すべて</option><option value="overdue">期限超過</option><option value="today">本日</option><option value="upcoming">今後</option><option value="unset">未設定</option></select></label>
      <label className="field">並び順<select value={draft.sort} onChange={e => setDraft({ ...draft, sort: e.target.value })}><option value="score_desc">スコア順</option><option value="newest">新しい順</option><option value="company_name">会社名順</option></select></label>
    </div><div className="flex flex-wrap justify-end gap-2"><button className="secondary" onClick={() => { setDraft(defaults); setFilters(defaults); setPage(0) }}>リセット</button><button onClick={() => { setFilters(draft); setPage(0) }}>絞り込む</button>
      <button className="secondary" onClick={() => void download(`/projects/${projectId}/companies.csv?${query}`, 'leadhive-companies.csv').catch(e => setError(errorMessage(e)))}>CSV出力</button></div></section>
    <section className="panel mt-6"><div className="flex items-center justify-between gap-3"><div><h2>営業アプローチキュー</h2><p className="muted mt-2 text-sm">期限超過を優先し、連絡可能な営業対象を処理します。</p></div><span className="badge">{outreachQueue.length} 社</span></div>
      <div className="company-table-wrap mt-4"><table className="company-table"><thead><tr><th>企業</th><th>推奨経路</th><th>担当者</th><th>期限</th><th>状況</th><th></th></tr></thead><tbody>{outreachQueue.map(item => <tr key={item.company.id}><td><strong>{item.company.company_name}</strong><p className="muted text-xs">{item.company.rank ?? '—'} / {item.company.score ?? '—'}点</p></td><td>{channelNames[item.recommended_channel]}<p className="muted text-xs">{item.available_channels.map(channel => channelNames[channel]).join(' / ')}</p></td><td>{item.company.assignee || '未設定'}</td><td><span className="badge">{dueNames[item.due_state]}</span><p className="muted text-xs">{item.company.next_followup_at ? new Date(item.company.next_followup_at).toLocaleString('ja-JP') : '—'}</p></td><td>{statusNames[item.company.status]}</td><td><button className="secondary" onClick={() => startOutreach(item)}>対応する</button></td></tr>)}{outreachQueue.length === 0 && <tr><td colSpan={6} className="text-center muted">連絡可能な営業対象はありません。</td></tr>}</tbody></table></div>
      {outreachTarget && <div className="mt-5"><h3>{outreachTarget.company.company_name}への対応記録</h3><div className="detail-grid"><div><label className="field">連絡経路<select value={outreachChannel} onChange={e => setOutreachChannel(e.target.value as OutreachChannel)}>{outreachTarget.available_channels.map(channel => <option key={channel} value={channel}>{channelNames[channel]}</option>)}</select></label><label className="field">結果<select value={outreachOutcome} onChange={e => setOutreachOutcome(e.target.value as SalesStatus)}><option value="approached">アプローチ済</option><option value="replied">返信あり</option><option value="meeting">商談</option><option value="lost">失注</option></select></label><label className="field">次回対応日時<input type="datetime-local" value={outreachFollowup} onChange={e => setOutreachFollowup(e.target.value)} /></label></div><label className="field">対応内容<textarea rows={5} maxLength={10000} value={outreachNote} onChange={e => setOutreachNote(e.target.value)} placeholder="送信内容、通話結果、次回確認事項" /></label></div><div className="actions"><button disabled={busy || !outreachNote.trim()} onClick={() => void recordOutreach()}>対応を記録</button><button className="secondary" onClick={() => setOutreachTarget(null)}>キャンセル</button></div></div>}
    </section>
    <section className="panel mt-6"><div className="flex flex-wrap items-end justify-between gap-4"><div><h2>保存フィルター</h2><p className="muted mt-2 text-sm">適用中の絞り込み条件を名前付きで保存します。</p></div>
      <div className="flex flex-wrap items-end gap-2"><label className="field mb-0">フィルター名<input value={filterName} maxLength={200} onChange={e => setFilterName(e.target.value)} placeholder="例：佐藤担当の期限超過" /></label><button disabled={busy || !filterName.trim()} onClick={() => void saveFilter()}>現在の条件を保存</button></div></div>
      {savedFilters.length === 0 ? <p className="muted mt-4">保存済みフィルターはありません。</p> : <div className="grid gap-3 mt-4 sm:grid-cols-2 xl:grid-cols-3">{savedFilters.map(item => <article className="job-row block" key={item.id}>{editingFilterId === item.id ? <><label className="field">保存名<input aria-label={`${item.name}の保存名`} maxLength={200} value={editingFilterName} onChange={e => setEditingFilterName(e.target.value)} /></label><div className="flex gap-2"><button disabled={busy || !editingFilterName.trim()} onClick={() => void updateFilter(item, editingFilterName, item.filters)}>名前を保存</button><button className="secondary" onClick={() => setEditingFilterId('')}>キャンセル</button></div></> : <><strong>{item.name}</strong><div className="flex flex-wrap gap-2 mt-3"><button className="secondary" onClick={() => { setDraft(item.filters); setFilters(item.filters); setPage(0) }}>適用</button><button className="secondary" disabled={busy} onClick={() => void updateFilter(item, item.name, filters)}>現在の条件で上書き</button><button className="secondary" onClick={() => { setEditingFilterId(item.id); setEditingFilterName(item.name) }}>名前変更</button><button className="danger" disabled={busy} onClick={() => void deleteFilter(item.id)}>削除</button></div></>}</article>)}</div>}</section>
    <section className="panel mt-6"><div className="flex items-center justify-between gap-3"><div><h2>担当者別営業成果</h2><p className="muted mt-2 text-sm">担当企業数と現在の営業状況、期限超過を比較します。</p></div><span className="badge">{assigneeAnalytics.length} 人</span></div>
      <div className="company-table-wrap mt-4"><table className="company-table"><thead><tr><th>担当者</th><th>担当企業</th><th>アプローチ</th><th>返信</th><th>商談</th><th>成約</th><th>期限超過</th></tr></thead><tbody>{assigneeAnalytics.map(item => <tr key={item.assignee}><td><strong>{item.assignee}</strong></td><td>{item.total}</td><td>{item.approached}</td><td>{item.replied}</td><td>{item.meetings}</td><td>{item.won}</td><td>{item.overdue}</td></tr>)}{assigneeAnalytics.length === 0 && <tr><td colSpan={7} className="text-center muted">集計対象の企業はありません。</td></tr>}</tbody></table></div></section>
    {quality && <section className="panel mt-6"><div className="flex flex-wrap items-center justify-between gap-4"><div><h2>データ品質</h2><p className="muted mt-2 text-sm">欠損情報とWeb解析の更新状況を確認します。</p></div>
      <div className="flex flex-wrap items-end gap-2"><label className="field mb-0">再解析期限（日）<input className="max-w-32" type="number" min={1} max={3650} value={staleDays} onChange={e => setStaleDays(Number(e.target.value))} /></label>
        <button disabled={busy || quality.reanalyzable === 0} onClick={() => void reanalyzeQuality()}>失敗・期限切れを再解析</button></div></div>
      <div className="grid gap-3 mt-5 sm:grid-cols-2 xl:grid-cols-4">{[
        ['Webサイトなし', quality.missing_website], ['住所なし', quality.missing_address],
        ['電話なし', quality.missing_phone], ['メールなし', quality.missing_email],
        ['連絡先なし', quality.missing_contact], ['解析失敗', quality.failed_analysis],
        [`${quality.stale_days}日超過`, quality.stale_analysis], ['再解析対象', quality.reanalyzable],
      ].map(([label, value]) => <div className="metric" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div></section>}
    <section className="panel mt-6"><div className="flex items-center justify-between gap-3"><div><h2>重複候補</h2><p className="muted mt-2 text-sm">メール・電話・会社名と住所の一致を確認して統合します。</p></div><span className="badge">{duplicates.length} 組</span></div>
      {duplicates.length === 0 ? <p className="muted mt-4">重複候補はありません。</p> : duplicates.map(item => <article className="job-row block" key={`${item.left.id}-${item.right.id}`}><p className="muted text-sm">一致：{item.reasons.map(reason => reason === 'email' ? 'メール' : reason === 'phone' ? '電話' : '会社名＋住所').join(' / ')}</p>
        <div className="grid gap-3 mt-3 sm:grid-cols-2"><div><strong>{item.left.company_name}</strong><p className="muted text-sm">{item.left.email || item.left.phone || item.left.address}</p><button disabled={busy} className="secondary mt-2" onClick={() => void mergeCompanies(item.left, item.right)}>こちらへ統合</button></div>
          <div><strong>{item.right.company_name}</strong><p className="muted text-sm">{item.right.email || item.right.phone || item.right.address}</p><button disabled={busy} className="secondary mt-2" onClick={() => void mergeCompanies(item.right, item.left)}>こちらへ統合</button></div></div></article>)}</section>
    <div className="section-heading mt-7"><h2>企業一覧</h2><span className="badge">全 {total} 社</span></div>
    <div className="mb-3 flex flex-wrap items-center gap-2"><span className="muted text-sm">{checked.length}社を選択</span><select className="max-w-48" defaultValue="" onChange={e => { if (e.target.value) void bulkStatus(e.target.value as SalesStatus); e.target.value = '' }}><option value="">営業状況を一括変更</option>{Object.entries(statusNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><input className="max-w-48" aria-label="一括担当者" placeholder="担当者名（空欄で解除）" value={bulkAssignee} onChange={e => setBulkAssignee(e.target.value)} /><button className="secondary" disabled={!checked.length || busy} onClick={() => void assignSelected()}>担当者を設定</button></div>
    <section className="company-table-wrap"><table className="company-table"><thead><tr><th><input aria-label="このページをすべて選択" type="checkbox" checked={companies.length > 0 && checked.length === companies.length} onChange={e => setChecked(e.target.checked ? companies.map(c => c.id) : [])} /></th><th>ランク</th><th>企業</th><th>地域</th><th>連絡先</th><th>担当・次回</th><th>営業状況</th><th></th></tr></thead><tbody>
      {companies.map(company => <tr key={company.id}><td><input aria-label={`${company.company_name}を選択`} type="checkbox" checked={checked.includes(company.id)} onChange={e => setChecked(e.target.checked ? [...checked, company.id] : checked.filter(id => id !== company.id))} /></td><td><strong>{company.rank ?? '—'}</strong><br /><span className="muted text-xs">{company.score ?? '—'}点</span></td><td><strong>{company.company_name}</strong><p className="muted text-xs">{company.business_type || company.ai_summary || '業種未判定'}</p></td><td>{company.prefecture || company.address || '—'}</td><td>{company.email || company.phone || (company.contact_url ? 'フォームあり' : '—')}</td><td>{company.assignee || '未設定'}<p className="muted text-xs">{company.next_followup_at ? new Date(company.next_followup_at).toLocaleString('ja-JP') : '期限なし'}</p></td><td><span className="badge">{statusNames[company.status]}</span></td><td><button className="secondary" onClick={() => void open(company)}>詳細</button></td></tr>)}
      {companies.length === 0 && <tr><td colSpan={8} className="text-center muted">条件に一致する企業はありません。</td></tr>}</tbody></table></section>
    <div className="mt-4 flex items-center justify-between"><button className="secondary" disabled={page === 0} onClick={() => setPage(page - 1)}>前へ</button><span className="muted text-sm">{page + 1} / {Math.max(1, Math.ceil(total / 25))} ページ</span><button className="secondary" disabled={(page + 1) * 25 >= total} onClick={() => setPage(page + 1)}>次へ</button></div>
    {selected && <section className="panel mt-7" aria-label="企業詳細"><div className="flex justify-between gap-4"><div><p className="eyebrow">COMPANY DETAIL</p><h2>{selected.company_name}</h2></div><button className="secondary" onClick={() => setSelected(null)}>閉じる</button></div>
      <div className="detail-grid"><div><h3>基本情報を編集</h3>{[['company_name', '会社名'], ['address', '住所'], ['prefecture', '都道府県'], ['city', '市区町村'], ['phone', '電話'], ['email', 'メール'], ['assignee', '担当者']].map(([key, label]) => <div key={key}><label className="field">{label}<input value={companyEdit[key] ?? ''} onChange={e => setCompanyEdit({ ...companyEdit, [key]: e.target.value })} /></label>{key !== 'assignee' && <label className="checkbox-row text-sm"><input type="checkbox" checked={protectedFields.includes(key)} onChange={e => setProtectedFields(e.target.checked ? [...protectedFields, key] : protectedFields.filter(field => field !== key))} />{label}をWeb再解析から保護</label>}</div>)}</div>
        <div><h3>問い合わせ先を編集</h3>{[['contact_url', 'フォーム'], ['instagram_url', 'Instagram'], ['x_url', 'X'], ['tiktok_url', 'TikTok'], ['facebook_url', 'Facebook'], ['youtube_url', 'YouTube'], ['line_url', 'LINE']].map(([key, label]) => <div key={key}><label className="field">{label}<input value={companyEdit[key] ?? ''} onChange={e => setCompanyEdit({ ...companyEdit, [key]: e.target.value })} /></label><label className="checkbox-row text-sm"><input type="checkbox" checked={protectedFields.includes(key)} onChange={e => setProtectedFields(e.target.checked ? [...protectedFields, key] : protectedFields.filter(field => field !== key))} />{label}をWeb再解析から保護</label></div>)}</div></div>
      <div className="actions"><button disabled={busy} onClick={() => void saveCompany()}>企業情報を保存</button></div>
      <div className="detail-grid"><div><h3>連絡禁止・除外</h3><label className="checkbox-row"><input type="checkbox" checked={doNotContact} onChange={e => setDoNotContact(e.target.checked)} />この企業への連絡を禁止</label><label className="field">除外理由<input maxLength={500} required={doNotContact} value={exclusionReason} onChange={e => setExclusionReason(e.target.value)} placeholder="例：連絡拒否、既存顧客、競合" /></label></div><div><h3>連絡先品質</h3><label className="field">確認状態<select value={contactQuality} onChange={e => setContactQuality(e.target.value as Company['contact_quality_status'])}><option value="unknown">未確認</option><option value="observed">Web取得済み</option><option value="verified">人手確認済み</option><option value="invalid">無効</option></select></label><p className="muted text-sm">取得元：{selected.contact_source_url || '未記録'}</p><p className="muted text-sm">最終確認：{selected.contact_checked_at ? new Date(selected.contact_checked_at).toLocaleString('ja-JP') : '未確認'}</p></div></div><div className="actions"><button disabled={busy || (doNotContact && !exclusionReason.trim())} onClick={() => void saveContactControl()}>連絡制御を保存</button></div>
      <div className="detail-grid"><div><h3>AI分析</h3><p><strong>{selected.rank ?? '未判定'} / {selected.score ?? '—'}点</strong> {selected.business_type}</p><p>{selected.ai_summary || 'AI要約はありません。'}</p><p className="muted">{selected.ai_reason}</p></div><div><h3>強み・懸念</h3><p>{selected.ai_strengths.join(' / ') || '—'}</p><p className="muted">{selected.ai_concerns.join(' / ') || '—'}</p><p>推奨：{selected.ai_recommended_approach || '—'}</p></div></div>
      <div className="mt-5"><h3>Web解析ページ</h3>{selected.scraped_urls.length === 0 ? <p className="muted text-sm">解析ページの記録はありません。</p> : <ul className="mt-2 list-disc pl-5 text-sm">{selected.scraped_urls.map(url => <li className="break-all" key={url}><a href={url} target="_blank" rel="noreferrer">{url}</a></li>)}</ul>}</div>
      <div className="detail-grid"><div><label className="field">営業状況<select value={status} onChange={e => setStatus(e.target.value as SalesStatus)}>{Object.entries(statusNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="field">次回対応日時<input type="datetime-local" value={followup} onChange={e => setFollowup(e.target.value)} /></label></div><label className="field">メモ<textarea rows={5} maxLength={20000} value={notes} onChange={e => setNotes(e.target.value)} /></label></div>
      <div className="actions"><button disabled={busy} onClick={() => void save()}>{busy ? '保存中…' : '営業状況を保存'}</button></div></section>}
    {selected && <section className="panel mt-7" aria-label="先方担当者"><div className="flex items-center justify-between gap-3"><div><h2>先方担当者</h2><p className="muted mt-2 text-sm">相手企業の担当者・責任者と連絡先を管理します。</p></div><span className="badge">{contacts.length} 人</span></div>
      <div className="grid gap-3 mt-4 sm:grid-cols-2">{contacts.map(contact => <article className="job-row block" key={contact.id}><div className="flex items-start justify-between gap-3"><div><strong>{contact.name}</strong><p className="muted text-sm">{[contact.department, contact.title].filter(Boolean).join(' / ') || '部署・役職未設定'}</p></div><span className="badge">{contact.verification_status === 'verified' ? '確認済み' : contact.verification_status === 'invalid' ? '無効' : '未確認'}</span></div><p className="mt-2 text-sm">{contact.email || 'メールなし'} / {contact.phone || '電話なし'}</p>{contact.notes && <p className="muted text-sm">{contact.notes}</p>}<div className="flex gap-2 mt-3"><button className="secondary" onClick={() => editContact(contact)}>編集</button><button className="danger" disabled={busy} onClick={() => void deleteContactPerson(contact)}>削除</button></div></article>)}{contacts.length === 0 && <p className="muted">登録済みの先方担当者はいません。</p>}</div>
      <div className="mt-5"><h3>{editingContactId ? '先方担当者を編集' : '先方担当者を追加'}</h3><div className="detail-grid"><div><label className="field">担当者氏名<input maxLength={200} value={contactDraft.name} onChange={e => setContactDraft({ ...contactDraft, name: e.target.value })} /></label><label className="field">部署<input maxLength={200} value={contactDraft.department} onChange={e => setContactDraft({ ...contactDraft, department: e.target.value })} /></label><label className="field">役職<input maxLength={200} value={contactDraft.title} onChange={e => setContactDraft({ ...contactDraft, title: e.target.value })} /></label><label className="field">確認状態<select value={contactDraft.verification_status} onChange={e => setContactDraft({ ...contactDraft, verification_status: e.target.value })}><option value="unknown">未確認</option><option value="verified">確認済み</option><option value="invalid">無効</option></select></label></div><div><label className="field">担当者メール<input maxLength={320} value={contactDraft.email} onChange={e => setContactDraft({ ...contactDraft, email: e.target.value })} /></label><label className="field">担当者電話<input maxLength={100} value={contactDraft.phone} onChange={e => setContactDraft({ ...contactDraft, phone: e.target.value })} /></label><label className="field">取得元URL<input maxLength={5000} value={contactDraft.source_url} onChange={e => setContactDraft({ ...contactDraft, source_url: e.target.value })} /></label><label className="field">担当者メモ<textarea rows={3} maxLength={10000} value={contactDraft.notes} onChange={e => setContactDraft({ ...contactDraft, notes: e.target.value })} /></label></div></div><div className="actions"><button disabled={busy || !contactDraft.name?.trim()} onClick={() => void saveContactPerson()}>{editingContactId ? '担当者情報を更新' : '担当者を追加'}</button>{editingContactId && <button className="secondary" onClick={() => { setEditingContactId(''); setContactDraft(emptyContact) }}>キャンセル</button>}</div></div>
    </section>}
    {selected && <section className="panel mt-7"><h2>活動履歴</h2><div className="detail-grid"><label className="field">活動種別<select value={activityType} onChange={e => setActivityType(e.target.value)}><option value="note">メモ</option><option value="call">電話</option><option value="email">メール</option><option value="form">フォーム</option><option value="sns">SNS</option><option value="meeting">商談</option></select></label><label className="field">活動内容<textarea rows={3} value={activityNote} onChange={e => setActivityNote(e.target.value)} /></label></div><div className="actions"><button disabled={busy || !activityNote.trim()} onClick={() => void addActivity()}>履歴を追加</button></div>{activities.map(item => <article className="job-row" key={item.id}><div><strong>{item.activity_type}</strong><p>{item.note}</p></div><time className="muted text-sm">{new Date(item.created_at).toLocaleString('ja-JP')}</time></article>)}</section>}
  </>
}
