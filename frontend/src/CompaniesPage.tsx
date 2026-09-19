import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, download, errorMessage } from './api'
import type { CollectionSource, Company, Project, SalesStatus } from './types'

const statusNames: Record<SalesStatus, string> = {
  unreviewed: '未確認', target: '営業対象', approached: 'アプローチ済', replied: '返信あり',
  meeting: '商談', won: '成約', lost: '失注', excluded: '対象外',
}
const sourceNames: Record<CollectionSource, string> = {
  serper: 'Google検索', google_places: 'Google Maps', url: 'URL', csv: 'CSV',
}
type Filters = { rank: string; minScore: string; region: string; status: string; source: string; keyword: string; sort: string }
const defaults: Filters = { rank: '', minScore: '', region: '', status: '', source: '', keyword: '', sort: 'score_desc' }

function queryString(filters: Filters) {
  const params = new URLSearchParams({ limit: '100', sort: filters.sort })
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
  const [selected, setSelected] = useState<Company | null>(null)
  const [status, setStatus] = useState<SalesStatus>('unreviewed')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const query = useMemo(() => queryString(filters), [filters])
  const reload = useCallback(async () => {
    if (!projectId) { setCompanies([]); return }
    setCompanies(await api<Company[]>(`/projects/${projectId}/company-list?${query}`))
  }, [projectId, query])
  useEffect(() => { reload().catch(e => setError(errorMessage(e))) }, [reload])
  function open(company: Company) {
    setSelected(company); setStatus(company.status); setNotes(company.notes); setNotice('')
  }
  async function save() {
    if (!selected) return
    setBusy(true); setError('')
    try {
      const updated = await api<Company>(`/companies/${selected.id}/sales`, 'PATCH', { status, notes })
      setSelected(updated); await reload(); setNotice('営業状況を保存しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  if (projects.length === 0) return <section className="panel empty"><h2>先にプロジェクトを作成してください</h2></section>
  return <>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p className="notice" role="status">{notice}</p>}
    <section className="panel"><div className="filter-grid">
      <label className="field">プロジェクト<select value={projectId} onChange={e => { setProjectId(e.target.value); setSelected(null) }}>{projects.map(project => <option key={project.id} value={project.id}>{project.project_name}</option>)}</select></label>
      <label className="field">キーワード<input value={draft.keyword} onChange={e => setDraft({ ...draft, keyword: e.target.value })} placeholder="会社名・業種・AI要約" /></label>
      <label className="field">ランク<select value={draft.rank} onChange={e => setDraft({ ...draft, rank: e.target.value })}><option value="">すべて</option>{['A', 'B', 'C', '対象外'].map(value => <option key={value}>{value}</option>)}</select></label>
      <label className="field">最低スコア<input type="number" min="0" max="100" value={draft.minScore} onChange={e => setDraft({ ...draft, minScore: e.target.value })} /></label>
      <label className="field">地域<input value={draft.region} onChange={e => setDraft({ ...draft, region: e.target.value })} /></label>
      <label className="field">営業状況<select value={draft.status} onChange={e => setDraft({ ...draft, status: e.target.value })}><option value="">すべて</option>{Object.entries(statusNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label className="field">収集元<select value={draft.source} onChange={e => setDraft({ ...draft, source: e.target.value })}><option value="">すべて</option>{Object.entries(sourceNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label className="field">並び順<select value={draft.sort} onChange={e => setDraft({ ...draft, sort: e.target.value })}><option value="score_desc">スコア順</option><option value="newest">新しい順</option><option value="company_name">会社名順</option></select></label>
    </div><div className="flex flex-wrap justify-end gap-2"><button className="secondary" onClick={() => { setDraft(defaults); setFilters(defaults) }}>リセット</button><button onClick={() => setFilters(draft)}>絞り込む</button>
      <button className="secondary" onClick={() => void download(`/projects/${projectId}/companies.csv?${query}`, 'leadhive-companies.csv').catch(e => setError(errorMessage(e)))}>CSV出力</button></div></section>
    <div className="section-heading mt-7"><h2>企業一覧</h2><span className="badge">{companies.length} 社</span></div>
    <section className="company-table-wrap"><table className="company-table"><thead><tr><th>ランク</th><th>企業</th><th>地域</th><th>連絡先</th><th>営業状況</th><th></th></tr></thead><tbody>
      {companies.map(company => <tr key={company.id}><td><strong>{company.rank ?? '—'}</strong><br /><span className="muted text-xs">{company.score ?? '—'}点</span></td><td><strong>{company.company_name}</strong><p className="muted text-xs">{company.business_type || company.ai_summary || '業種未判定'}</p></td><td>{company.prefecture || company.address || '—'}</td><td>{company.email || company.phone || (company.contact_url ? 'フォームあり' : '—')}</td><td><span className="badge">{statusNames[company.status]}</span></td><td><button className="secondary" onClick={() => open(company)}>詳細</button></td></tr>)}
      {companies.length === 0 && <tr><td colSpan={6} className="text-center muted">条件に一致する企業はありません。</td></tr>}</tbody></table></section>
    {selected && <section className="panel mt-7" aria-label="企業詳細"><div className="flex justify-between gap-4"><div><p className="eyebrow">COMPANY DETAIL</p><h2>{selected.company_name}</h2></div><button className="secondary" onClick={() => setSelected(null)}>閉じる</button></div>
      <div className="detail-grid"><div><h3>基本情報</h3><p>{selected.address || '住所未登録'}</p><p>{selected.phone || '電話未登録'} / {selected.email || 'メール未登録'}</p>{selected.website_url && <a href={selected.website_url} target="_blank" rel="noreferrer">Webサイト</a>}</div>
        <div><h3>問い合わせ先</h3><div className="flex flex-wrap gap-3">{selected.contact_url && <a href={selected.contact_url} target="_blank" rel="noreferrer">フォーム</a>}{selected.instagram_url && <a href={selected.instagram_url} target="_blank" rel="noreferrer">Instagram</a>}{selected.x_url && <a href={selected.x_url} target="_blank" rel="noreferrer">X</a>}{selected.tiktok_url && <a href={selected.tiktok_url} target="_blank" rel="noreferrer">TikTok</a>}{selected.facebook_url && <a href={selected.facebook_url} target="_blank" rel="noreferrer">Facebook</a>}{selected.line_url && <a href={selected.line_url} target="_blank" rel="noreferrer">LINE</a>}</div></div></div>
      <div className="detail-grid"><div><h3>AI分析</h3><p><strong>{selected.rank ?? '未判定'} / {selected.score ?? '—'}点</strong> {selected.business_type}</p><p>{selected.ai_summary || 'AI要約はありません。'}</p><p className="muted">{selected.ai_reason}</p></div><div><h3>強み・懸念</h3><p>{selected.ai_strengths.join(' / ') || '—'}</p><p className="muted">{selected.ai_concerns.join(' / ') || '—'}</p><p>推奨：{selected.ai_recommended_approach || '—'}</p></div></div>
      <div className="detail-grid"><label className="field">営業状況<select value={status} onChange={e => setStatus(e.target.value as SalesStatus)}>{Object.entries(statusNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="field">メモ<textarea rows={5} maxLength={20000} value={notes} onChange={e => setNotes(e.target.value)} /></label></div>
      <div className="actions"><button disabled={busy} onClick={() => void save()}>{busy ? '保存中…' : '営業状況を保存'}</button></div></section>}
  </>
}
