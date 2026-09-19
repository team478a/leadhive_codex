import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, download, errorMessage } from './api'
import type { Activity, CollectionSource, Company, CompanyPage, DataQuality, OperationJob, Project, SalesStatus } from './types'

const statusNames: Record<SalesStatus, string> = {
  unreviewed: '未確認', target: '営業対象', approached: 'アプローチ済', replied: '返信あり',
  meeting: '商談', won: '成約', lost: '失注', excluded: '対象外',
}
const sourceNames: Record<CollectionSource, string> = {
  serper: 'Google検索', google_places: 'Google Maps', url: 'URL', csv: 'CSV',
}
type Filters = { rank: string; minScore: string; region: string; status: string; source: string; keyword: string; sort: string }
const defaults: Filters = { rank: '', minScore: '', region: '', status: '', source: '', keyword: '', sort: 'score_desc' }

function queryString(filters: Filters, page: number) {
  const params = new URLSearchParams({ limit: '25', offset: String(page * 25), sort: filters.sort })
  if (filters.rank) params.set('rank', filters.rank)
  if (filters.minScore) params.set('min_score', filters.minScore)
  if (filters.region) params.set('region', filters.region)
  if (filters.status) params.set('status', filters.status)
  if (filters.source) params.set('source', filters.source)
  if (filters.keyword) params.set('keyword', filters.keyword)
  return params.toString()
}

export function CompaniesPage({ projects, initialProjectId }: { projects: Project[]; initialProjectId: string }) {
  const [projectId, setProjectId] = useState(initialProjectId || projects[0]?.id || '')
  const [draft, setDraft] = useState<Filters>(defaults)
  const [filters, setFilters] = useState<Filters>(defaults)
  const [companies, setCompanies] = useState<Company[]>([])
  const [total, setTotal] = useState(0)
  const [quality, setQuality] = useState<DataQuality | null>(null)
  const [staleDays, setStaleDays] = useState(90)
  const [page, setPage] = useState(0)
  const [checked, setChecked] = useState<string[]>([])
  const [selected, setSelected] = useState<Company | null>(null)
  const [companyEdit, setCompanyEdit] = useState<Record<string, string>>({})
  const [status, setStatus] = useState<SalesStatus>('unreviewed')
  const [notes, setNotes] = useState('')
  const [followup, setFollowup] = useState('')
  const [activities, setActivities] = useState<Activity[]>([])
  const [activityType, setActivityType] = useState('note')
  const [activityNote, setActivityNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const query = useMemo(() => queryString(filters, page), [filters, page])
  const reload = useCallback(async () => {
    if (!projectId) { setCompanies([]); return }
    const [result, nextQuality] = await Promise.all([
      api<CompanyPage>(`/projects/${projectId}/company-list?${query}`),
      api<DataQuality>(`/projects/${projectId}/data-quality?stale_days=${staleDays}`),
    ])
    setCompanies(result.items); setTotal(result.total); setQuality(nextQuality); setChecked([])
  }, [projectId, query, staleDays])
  useEffect(() => { reload().catch(e => setError(errorMessage(e))) }, [reload])
  async function open(company: Company) {
    setSelected(company); setStatus(company.status); setNotes(company.notes); setNotice('')
    setCompanyEdit(Object.fromEntries([
      'company_name', 'address', 'prefecture', 'city', 'phone', 'email', 'contact_url',
      'instagram_url', 'x_url', 'tiktok_url', 'facebook_url', 'youtube_url', 'line_url',
    ].map(key => [key, String(company[key as keyof Company] ?? '')])))
    setFollowup(company.next_followup_at?.slice(0, 16) ?? '')
    setActivities(await api<Activity[]>(`/companies/${company.id}/activities`))
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
      const updated = await api<Company>(`/companies/${selected.id}`, 'PUT', companyEdit)
      setSelected(updated); await reload(); setNotice('企業情報を保存しました。')
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
  async function reanalyzeQuality() {
    setBusy(true); setError(''); setNotice('')
    try {
      const job = await api<OperationJob>(`/projects/${projectId}/data-quality/reanalyze`, 'POST', {
        scope: 'failed_or_stale', stale_days: staleDays,
      })
      setNotice(`${job.total_count || quality?.reanalyzable || 0}社を再解析ジョブへ登録しました。`)
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
      <label className="field">並び順<select value={draft.sort} onChange={e => setDraft({ ...draft, sort: e.target.value })}><option value="score_desc">スコア順</option><option value="newest">新しい順</option><option value="company_name">会社名順</option></select></label>
    </div><div className="flex flex-wrap justify-end gap-2"><button className="secondary" onClick={() => { setDraft(defaults); setFilters(defaults); setPage(0) }}>リセット</button><button onClick={() => { setFilters(draft); setPage(0) }}>絞り込む</button>
      <button className="secondary" onClick={() => void download(`/projects/${projectId}/companies.csv?${query}`, 'leadhive-companies.csv').catch(e => setError(errorMessage(e)))}>CSV出力</button></div></section>
    {quality && <section className="panel mt-6"><div className="flex flex-wrap items-center justify-between gap-4"><div><h2>データ品質</h2><p className="muted mt-2 text-sm">欠損情報とWeb解析の更新状況を確認します。</p></div>
      <div className="flex flex-wrap items-end gap-2"><label className="field mb-0">再解析期限（日）<input className="max-w-32" type="number" min={1} max={3650} value={staleDays} onChange={e => setStaleDays(Number(e.target.value))} /></label>
        <button disabled={busy || quality.reanalyzable === 0} onClick={() => void reanalyzeQuality()}>失敗・期限切れを再解析</button></div></div>
      <div className="grid gap-3 mt-5 sm:grid-cols-2 xl:grid-cols-4">{[
        ['Webサイトなし', quality.missing_website], ['住所なし', quality.missing_address],
        ['電話なし', quality.missing_phone], ['メールなし', quality.missing_email],
        ['連絡先なし', quality.missing_contact], ['解析失敗', quality.failed_analysis],
        [`${quality.stale_days}日超過`, quality.stale_analysis], ['再解析対象', quality.reanalyzable],
      ].map(([label, value]) => <div className="metric" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div></section>}
    <div className="section-heading mt-7"><h2>企業一覧</h2><span className="badge">全 {total} 社</span></div>
    <div className="mb-3 flex flex-wrap items-center gap-2"><span className="muted text-sm">{checked.length}社を選択</span><select className="max-w-48" defaultValue="" onChange={e => { if (e.target.value) void bulkStatus(e.target.value as SalesStatus); e.target.value = '' }}><option value="">営業状況を一括変更</option>{Object.entries(statusNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
    <section className="company-table-wrap"><table className="company-table"><thead><tr><th><input aria-label="このページをすべて選択" type="checkbox" checked={companies.length > 0 && checked.length === companies.length} onChange={e => setChecked(e.target.checked ? companies.map(c => c.id) : [])} /></th><th>ランク</th><th>企業</th><th>地域</th><th>連絡先</th><th>営業状況</th><th></th></tr></thead><tbody>
      {companies.map(company => <tr key={company.id}><td><input aria-label={`${company.company_name}を選択`} type="checkbox" checked={checked.includes(company.id)} onChange={e => setChecked(e.target.checked ? [...checked, company.id] : checked.filter(id => id !== company.id))} /></td><td><strong>{company.rank ?? '—'}</strong><br /><span className="muted text-xs">{company.score ?? '—'}点</span></td><td><strong>{company.company_name}</strong><p className="muted text-xs">{company.business_type || company.ai_summary || '業種未判定'}</p></td><td>{company.prefecture || company.address || '—'}</td><td>{company.email || company.phone || (company.contact_url ? 'フォームあり' : '—')}</td><td><span className="badge">{statusNames[company.status]}</span></td><td><button className="secondary" onClick={() => void open(company)}>詳細</button></td></tr>)}
      {companies.length === 0 && <tr><td colSpan={7} className="text-center muted">条件に一致する企業はありません。</td></tr>}</tbody></table></section>
    <div className="mt-4 flex items-center justify-between"><button className="secondary" disabled={page === 0} onClick={() => setPage(page - 1)}>前へ</button><span className="muted text-sm">{page + 1} / {Math.max(1, Math.ceil(total / 25))} ページ</span><button className="secondary" disabled={(page + 1) * 25 >= total} onClick={() => setPage(page + 1)}>次へ</button></div>
    {selected && <section className="panel mt-7" aria-label="企業詳細"><div className="flex justify-between gap-4"><div><p className="eyebrow">COMPANY DETAIL</p><h2>{selected.company_name}</h2></div><button className="secondary" onClick={() => setSelected(null)}>閉じる</button></div>
      <div className="detail-grid"><div><h3>基本情報を編集</h3>{[['company_name', '会社名'], ['address', '住所'], ['prefecture', '都道府県'], ['city', '市区町村'], ['phone', '電話'], ['email', 'メール']].map(([key, label]) => <label className="field" key={key}>{label}<input value={companyEdit[key] ?? ''} onChange={e => setCompanyEdit({ ...companyEdit, [key]: e.target.value })} /></label>)}</div>
        <div><h3>問い合わせ先を編集</h3>{[['contact_url', 'フォーム'], ['instagram_url', 'Instagram'], ['x_url', 'X'], ['tiktok_url', 'TikTok'], ['facebook_url', 'Facebook'], ['youtube_url', 'YouTube'], ['line_url', 'LINE']].map(([key, label]) => <label className="field" key={key}>{label}<input value={companyEdit[key] ?? ''} onChange={e => setCompanyEdit({ ...companyEdit, [key]: e.target.value })} /></label>)}</div></div>
      <div className="actions"><button disabled={busy} onClick={() => void saveCompany()}>企業情報を保存</button></div>
      <div className="detail-grid"><div><h3>AI分析</h3><p><strong>{selected.rank ?? '未判定'} / {selected.score ?? '—'}点</strong> {selected.business_type}</p><p>{selected.ai_summary || 'AI要約はありません。'}</p><p className="muted">{selected.ai_reason}</p></div><div><h3>強み・懸念</h3><p>{selected.ai_strengths.join(' / ') || '—'}</p><p className="muted">{selected.ai_concerns.join(' / ') || '—'}</p><p>推奨：{selected.ai_recommended_approach || '—'}</p></div></div>
      <div className="detail-grid"><div><label className="field">営業状況<select value={status} onChange={e => setStatus(e.target.value as SalesStatus)}>{Object.entries(statusNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="field">次回対応日時<input type="datetime-local" value={followup} onChange={e => setFollowup(e.target.value)} /></label></div><label className="field">メモ<textarea rows={5} maxLength={20000} value={notes} onChange={e => setNotes(e.target.value)} /></label></div>
      <div className="actions"><button disabled={busy} onClick={() => void save()}>{busy ? '保存中…' : '営業状況を保存'}</button></div></section>}
    {selected && <section className="panel mt-7"><h2>活動履歴</h2><div className="detail-grid"><label className="field">活動種別<select value={activityType} onChange={e => setActivityType(e.target.value)}><option value="note">メモ</option><option value="call">電話</option><option value="email">メール</option><option value="form">フォーム</option><option value="sns">SNS</option><option value="meeting">商談</option></select></label><label className="field">活動内容<textarea rows={3} value={activityNote} onChange={e => setActivityNote(e.target.value)} /></label></div><div className="actions"><button disabled={busy || !activityNote.trim()} onClick={() => void addActivity()}>履歴を追加</button></div>{activities.map(item => <article className="job-row" key={item.id}><div><strong>{item.activity_type}</strong><p>{item.note}</p></div><time className="muted text-sm">{new Date(item.created_at).toLocaleString('ja-JP')}</time></article>)}</section>}
  </>
}
