import { useEffect, useState } from 'react'
import { allPages, api, errorMessage } from './api'
import { presenceLabels } from './externalPresenceShared'
import type { Company } from './types'

type Evidence = { id: string; platform: string; url: string; observed_at: string }

export function PresenceEvidenceQueue({ projectId }: { projectId: string }) {
  const [rows, setRows] = useState<Evidence[]>([])
  const [companies, setCompanies] = useState<Company[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [companiesLoading, setCompaniesLoading] = useState(false)
  const [companiesLoadAttempted, setCompaniesLoadAttempted] = useState(false)
  const [selected, setSelected] = useState<Record<string, string>>({})
  const [offset, setOffset] = useState(0)
  const [opened, setOpened] = useState(false)
  useEffect(() => {
    let cancelled = false
    api<Evidence[]>(`/projects/${projectId}/external-presence-evidence?unassigned=true&offset=${offset}&limit=20`)
      .then(value => { if (!cancelled) { setRows(value); setError('') } })
      .catch(e => { if (!cancelled) setError(errorMessage(e)) })
    return () => { cancelled = true }
  }, [projectId, offset])
  useEffect(() => {
    if (!opened || companies.length || companiesLoading || companiesLoadAttempted) return
    let cancelled = false
    setCompaniesLoading(true)
    setCompaniesLoadAttempted(true)
    allPages<Company>(`/projects/${projectId}/companies`)
      .then(value => { if (!cancelled) setCompanies(value) })
      .catch(e => { if (!cancelled) setError(errorMessage(e)) })
      .finally(() => { if (!cancelled) setCompaniesLoading(false) })
    return () => { cancelled = true }
  }, [projectId, opened, companies.length, companiesLoading, companiesLoadAttempted])
  async function link(row: Evidence) {
    setBusy(true); setError('')
    try {
      await api(`/external-presence-evidence/${row.id}/link`, 'POST', {
        company_id: selected[row.id], expected_url: row.url, confirmed: true,
      })
      setRows(await api<Evidence[]>(`/projects/${projectId}/external-presence-evidence?unassigned=true&offset=${offset}&limit=20`))
    } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false) }
  }
  return <details className="panel" onToggle={event => setOpened(event.currentTarget.open)}><summary>発見した掲載・SNSページの関連確認</summary>
    <p className="muted">企業との関連が不明なページを保存しています。ページを開き、会社・店舗の情報が一致することを確認してから関連づけてください。送信承認ではありません。</p>
    {companiesLoading && <p className="muted" role="status">関連づけ候補を読み込んでいます…</p>}
    {error && !companies.length && companiesLoadAttempted && <button type="button" className="secondary" onClick={() => { setError(''); setCompaniesLoadAttempted(false) }}>候補の読み込みを再試行</button>}
    {error && <p className="error" role="alert">{error}</p>}
    {!rows.length && <p>このページに確認待ちはありません。</p>}
    {rows.map(row => <article className="job-row block" key={row.id}>
      <a href={row.url} target="_blank" rel="noopener noreferrer">{presenceLabels[row.platform]}のページを確認 ↗</a>
      <label className="field">関連する企業・店舗<select aria-label="関連する企業・店舗" value={selected[row.id] || ''}
        onChange={e => setSelected({ ...selected, [row.id]: e.target.value })}>
        <option value="">選択してください</option>{companies.map(c => <option value={c.id} key={c.id}>{c.company_name}</option>)}
      </select></label>
      <button type="button" disabled={busy || !selected[row.id]} onClick={() => void link(row)}>ページと企業の一致を確認して保存</button>
    </article>)}
    <div className="actions"><button type="button" className="secondary" disabled={!offset || busy} onClick={() => setOffset(Math.max(0, offset - 20))}>前の20件</button>
      <button type="button" className="secondary" disabled={rows.length < 20 || busy} onClick={() => setOffset(offset + 20)}>次の20件</button></div>
  </details>
}
