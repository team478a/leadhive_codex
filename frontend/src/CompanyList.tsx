import type { Company, FormProfileSummary, SalesStatus } from './types'
import { statusNames } from './companyPageShared'

type Props = {
  companies: Company[]
  total: number
  checked: string[]
  page: number
  busy: boolean
  bulkAssignee: string
  formProfiles: Record<string, FormProfileSummary>
  setChecked: (value: string[]) => void
  setBulkAssignee: (value: string) => void
  setPage: (value: number) => void
  onBulkStatus: (status: SalesStatus) => void
  onAssign: () => void
  onAnalyzeSelected: () => void
  onOpen: (company: Company) => void
}

export function CompanyList({ companies, total, checked, page, busy, bulkAssignee, formProfiles, setChecked, setBulkAssignee, setPage, onBulkStatus, onAssign, onAnalyzeSelected, onOpen }: Props) {
  return <>
    <div className="section-heading mt-7"><h2>企業一覧</h2><span className="badge">全 {total} 社</span></div>
    <div className="mb-3 flex flex-wrap items-center gap-2"><span className="muted text-sm">{checked.length}社を選択</span><select className="max-w-48" defaultValue="" onChange={e => { if (e.target.value) onBulkStatus(e.target.value as SalesStatus); e.target.value = '' }}><option value="">営業状況を一括変更</option>{Object.entries(statusNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><input className="max-w-48" aria-label="一括担当者" placeholder="担当者名（空欄で解除）" value={bulkAssignee} onChange={e => setBulkAssignee(e.target.value)} /><button className="secondary" disabled={!checked.length || busy} onClick={onAssign}>担当者を設定</button><button disabled={!checked.length || busy} onClick={onAnalyzeSelected}>フォーム解析</button></div>
    <section className="company-table-wrap"><table className="company-table"><thead><tr><th><input aria-label="このページをすべて選択" type="checkbox" checked={companies.length > 0 && checked.length === companies.length} onChange={e => setChecked(e.target.checked ? companies.map(c => c.id) : [])} /></th><th>ランク</th><th>企業</th><th>地域</th><th>連絡先</th><th>フォーム解析</th><th>担当・次回</th><th>営業状況</th><th></th></tr></thead><tbody>
      {companies.map(company => { const form = formProfiles[company.id]; return <tr key={company.id}><td><input aria-label={`${company.company_name}を選択`} type="checkbox" checked={checked.includes(company.id)} onChange={e => setChecked(e.target.checked ? [...checked, company.id] : checked.filter(id => id !== company.id))} /></td><td><strong>{company.rank ?? '—'}</strong><br /><span className="muted text-xs">{company.score ?? '—'}点</span></td><td><strong>{company.company_name}</strong><p className="muted text-xs">{company.business_type || company.ai_summary || '業種未判定'}</p></td><td>{company.prefecture || company.address || '—'}</td><td>{company.email || company.phone || (company.contact_url ? 'フォームあり' : '—')}</td><td><span className={`form-status ${(form?.form_status ?? 'UNANALYZED').toLowerCase()}`}>{form?.form_status === 'READY' ? '準備完了' : form?.form_status === 'REVIEW_REQUIRED' ? '要確認' : form?.form_status === 'BLOCKED' ? '対象外' : form?.form_status === 'STALE' ? '変更あり' : form?.form_status === 'ERROR' ? '失敗' : '未解析'}</span>{form?.last_analyzed_at && <p className="muted text-xs">{new Date(form.last_analyzed_at).toLocaleDateString('ja-JP')}</p>}</td><td>{company.assignee || '未設定'}<p className="muted text-xs">{company.next_followup_at ? new Date(company.next_followup_at).toLocaleString('ja-JP') : '期限なし'}</p></td><td><span className="badge">{statusNames[company.status]}</span></td><td><button className="secondary" onClick={() => onOpen(company)}>詳細</button></td></tr> })}
      {companies.length === 0 && <tr><td colSpan={9} className="text-center muted">条件に一致する企業はありません。</td></tr>}</tbody></table></section>
    <div className="mt-4 flex items-center justify-between"><button className="secondary" disabled={page === 0} onClick={() => setPage(page - 1)}>前へ</button><span className="muted text-sm">{page + 1} / {Math.max(1, Math.ceil(total / 25))} ページ</span><button className="secondary" disabled={(page + 1) * 25 >= total} onClick={() => setPage(page + 1)}>次へ</button></div>
  </>
}
