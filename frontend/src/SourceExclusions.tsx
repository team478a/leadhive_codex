import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'

type Rule = { id: string; domain: string; reason: string; evidence_url: string; active: boolean }

export function SourceExclusions({ projectId }: { projectId: string }) {
  const [rows, setRows] = useState<Rule[]>([])
  const [url, setUrl] = useState('')
  const [reason, setReason] = useState('まとめサイト・掲載媒体')
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    setRows([]); setUrl(''); setConfirmed(false); setError('')
    if (projectId) api<Rule[]>(`/projects/${projectId}/source-exclusions`).then(r => { if (active) setRows(r) }).catch(e => { if (active) setError(errorMessage(e)) })
    return () => { active = false }
  }, [projectId])
  async function change(id?: string) {
    setBusy(true); setError('')
    try {
      const path = `/projects/${projectId}/source-exclusions`
      await api(id ? `${path}/${id}/deactivate` : path, 'POST', id ? undefined : { evidence_url: url.trim(), reason: reason.trim(), confirmed_domain_wide: confirmed })
      setRows(await api<Rule[]>(path)); setUrl(''); setConfirmed(false)
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  return <details className="panel mt-4"><summary>再収集しない掲載媒体（{rows.filter(r => r.active).length}ドメイン）</summary>
    <p className="muted mt-3">このProjectだけに適用します。企業サイト内の記事1ページを理由に、企業ドメイン全体を登録しないでください。検索結果には再登場する場合がありますが、企業登録・Web解析を省きます。</p>
    <label className="field">除外する媒体の根拠URL<input type="url" value={url} onChange={e => { setUrl(e.target.value); setConfirmed(false) }} placeholder="https://example.com/list" /></label>
    <label className="field">ドメイン除外の理由<input value={reason} onChange={e => setReason(e.target.value)} /></label>
    <label className="flex gap-2"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />企業公式サイトではなく、ドメイン全体が掲載媒体であることを確認しました</label>
    <button className="secondary mt-3" disabled={busy || !confirmed || !projectId || !url.trim() || !reason.trim()} onClick={() => void change()}>除外ドメインを記録</button>
    {rows.map(r => <div className="job-row flex-wrap break-all" key={r.id}><div>{r.domain} / {r.active ? '除外中' : '解除済み'}<p className="muted">{r.reason}</p><a href={r.evidence_url} target="_blank" rel="noreferrer">根拠ページ</a></div>{r.active && <button className="secondary" disabled={busy} onClick={() => void change(r.id)}>除外を解除</button>}</div>)}
    {error && <p role="alert" className="error">{error}</p>}
  </details>
}
