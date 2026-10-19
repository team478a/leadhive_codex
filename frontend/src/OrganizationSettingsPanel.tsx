import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from './api'

type Organization = { id: string; name: string; role?: 'owner' | 'admin'; status: string }
type Member = { id: string; user_id: string; email: string; role: 'owner' | 'admin' }
type Suppression = {
  id: string; domain: string; email: string; phone?: string; reason: string; source: string
  created_at: string; released_at: string | null; release_reason: string; releasable?: boolean
}
type MergePreview = {
  source: { id: string; name: string }; target: { id: string; name: string }
  projects: { id: string; name: string; owner_email: string }[]
  members: { id: string; email: string; role: string }[]
}

export function OrganizationSettingsPanel({ isAdmin }: { isAdmin: boolean }) {
  const [organizations, setOrganizations] = useState<Organization[]>([])
  const [allOrganizations, setAllOrganizations] = useState<Organization[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [members, setMembers] = useState<Member[]>([])
  const [suppressions, setSuppressions] = useState<Suppression[]>([])
  const [globalSuppressions, setGlobalSuppressions] = useState<Suppression[]>([])
  const [memberEmail, setMemberEmail] = useState('')
  const [memberRole, setMemberRole] = useState<'owner' | 'admin'>('admin')
  const [globalDomain, setGlobalDomain] = useState('')
  const [globalEmail, setGlobalEmail] = useState('')
  const [globalPhone, setGlobalPhone] = useState('')
  const [globalReason, setGlobalReason] = useState('')
  const [releaseReasons, setReleaseReasons] = useState<Record<string, string>>({})
  const [mergeSourceId, setMergeSourceId] = useState('')
  const [mergeTargetId, setMergeTargetId] = useState('')
  const [mergePreview, setMergePreview] = useState<MergePreview | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  const loadOrganizations = useCallback(async () => {
    const rows = await api<Organization[]>('/organizations')
    setOrganizations(rows)
    const operatorRows = isAdmin ? await api<Organization[]>('/admin/organizations') : rows
    setAllOrganizations(operatorRows)
    setSelectedId(current => rows.some(row => row.id === current) ? current : rows[0]?.id ?? '')
    if (isAdmin) setGlobalSuppressions(await api<Suppression[]>('/admin/global-suppression-entries'))
  }, [isAdmin])

  const loadSelected = useCallback(async (id: string) => {
    if (!id) { setMembers([]); setSuppressions([]); return }
    const [nextMembers, nextSuppressions] = await Promise.all([
      api<Member[]>(`/organizations/${id}/members`),
      api<{ items: Suppression[] }>(`/organizations/${id}/suppression-entries?offset=0&limit=100`),
    ])
    setMembers(nextMembers); setSuppressions(nextSuppressions.items)
  }, [])

  useEffect(() => { loadOrganizations().catch(reason => setError(errorMessage(reason))) }, [loadOrganizations])
  useEffect(() => { if (selectedId) loadSelected(selectedId).catch(reason => setError(errorMessage(reason))) }, [loadSelected, selectedId])

  async function run(action: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try { await action() } catch (reason) { setError(errorMessage(reason)) }
    finally { setBusy(false) }
  }

  async function addMember() {
    if (!selectedId || !memberEmail.trim()) return
    await run(async () => {
      await api(`/organizations/${selectedId}/members`, 'POST', { email: memberEmail.trim(), role: memberRole })
      setMemberEmail(''); setMemberRole('admin'); await loadSelected(selectedId)
      setNotice('利用企業の管理者を追加しました。プロジェクトへのアクセス権は追加されません。')
    })
  }

  async function removeMember(member: Member) {
    if (!selectedId || !window.confirm(`${member.email} を利用企業から削除しますか？プロジェクトへのアクセス権は別管理です。`)) return
    await run(async () => {
      await api(`/organizations/${selectedId}/members/${member.id}`, 'DELETE')
      await loadSelected(selectedId); setNotice('利用企業のメンバーを削除しました。')
    })
  }

  async function release(entry: Suppression, global = false) {
    const reason = releaseReasons[entry.id]?.trim() ?? ''
    if (!reason || !window.confirm('停止理由と解除根拠を確認しましたか？監査記録を残して解除します。')) return
    await run(async () => {
      const base = global ? '/admin/global-suppression-entries' : `/organizations/${selectedId}/suppression-entries`
      await api(`${base}/${entry.id}/release`, 'POST', { reason })
      setReleaseReasons(current => ({ ...current, [entry.id]: '' }))
      if (global) setGlobalSuppressions(await api<Suppression[]>('/admin/global-suppression-entries'))
      else await loadSelected(selectedId)
      setNotice('送信停止を解除し、監査記録を保存しました。')
    })
  }

  async function addGlobalSuppression() {
    if (!globalDomain.trim() && !globalEmail.trim() && !globalPhone.trim()) return
    if (!globalReason.trim()) return
    await run(async () => {
      await api('/admin/global-suppression-entries', 'POST', {
        domain: globalDomain,
        email: globalEmail,
        phone: globalPhone,
        reason: globalReason,
      })
      setGlobalDomain(''); setGlobalEmail(''); setGlobalPhone(''); setGlobalReason('')
      setGlobalSuppressions(await api<Suppression[]>('/admin/global-suppression-entries'))
      setNotice('運営共通の送信停止を登録し、監査記録を保存しました。')
    })
  }

  async function previewMerge() {
    if (!mergeSourceId || !mergeTargetId || mergeSourceId === mergeTargetId) return
    await run(async () => setMergePreview(await api<MergePreview>(
      `/admin/organizations/merge-preview?source_organization_id=${mergeSourceId}&target_organization_id=${mergeTargetId}`,
    )))
  }

  async function mergeOrganizations() {
    if (!mergePreview || !window.confirm(
      `${mergePreview.source.name} を ${mergePreview.target.name} に統合します。` +
      `\nプロジェクト ${mergePreview.projects.length}件、メンバー ${mergePreview.members.length}人、送信停止を移します。` +
      '\nプロジェクトアクセス権は変えずに続けますか？',
    )) return
    await run(async () => {
      await api('/admin/organizations/merge', 'POST', {
        source_organization_id: mergePreview.source.id,
        target_organization_id: mergePreview.target.id,
        expected_project_ids: mergePreview.projects.map(project => project.id),
        confirmed: true,
      })
      setMergePreview(null); await loadOrganizations()
      setNotice('利用企業を統合しました。既存のプロジェクト権限は変更していません。')
    })
  }

  function releaseControl(entry: Suppression, global = false) {
    const nonReleasable = !global && (entry.releasable === false ||
      ['email_unsubscribe', 'reply_unsubscribe', 'complaint', 'bounce', 'global_opt_out'].includes(entry.source))
    if (nonReleasable) return <span className="badge">解除不可（相手からの申出・苦情等）</span>
    return <div className="detail-grid mt-3">
      <label className="field">解除理由<input maxLength={500} value={releaseReasons[entry.id] ?? ''}
        onChange={event => setReleaseReasons(current => ({ ...current, [entry.id]: event.target.value }))} /></label>
      <button className="secondary" disabled={busy || !releaseReasons[entry.id]?.trim()}
        onClick={() => void release(entry, global)}>{global ? '運営判断で解除' : '利用企業の送信停止を解除'}</button>
    </div>
  }

  return <div className="grid gap-5">
    <section className="panel">
      <h2>利用企業の送信停止</h2>
      <p className="muted mt-2">プロジェクト単位のアクセス権は変わりません。相手の配信停止・返信・苦情は解除できません。</p>
      {error && <p className="error mt-3" role="alert">{error}</p>}
      {notice && <p className="notice mt-3" role="status">{notice}</p>}
      {!organizations.length ? <p className="muted mt-4">利用企業のowner/adminではありません。プロジェクトの招待は従来どおりプロジェクト単位です。</p> : <>
        <label className="field mt-4">利用企業<select value={selectedId} onChange={event => setSelectedId(event.target.value)}>
          {organizations.map(organization => <option key={organization.id} value={organization.id}>{organization.name}{organization.role ? `（${organization.role}）` : ''}</option>)}
        </select></label>
        <h3 className="mt-5">owner / admin</h3>
        {members.map(member => <article className="job-row" key={member.id}><div><strong>{member.email}</strong><p className="muted text-sm">{member.role}</p></div>
          {members.length > 1 && <button className="danger" disabled={busy} onClick={() => void removeMember(member)}>削除</button>}</article>)}
        {organizations.find(item => item.id === selectedId)?.role === 'owner' && <div className="detail-grid mt-3">
          <label className="field">管理者のメール<input type="email" value={memberEmail} onChange={event => setMemberEmail(event.target.value)} /></label>
          <label className="field">権限<select value={memberRole} onChange={event => setMemberRole(event.target.value as 'owner' | 'admin')}><option value="admin">admin</option><option value="owner">owner</option></select></label>
          <button disabled={busy || !memberEmail.trim()} onClick={() => void addMember()}>{memberRole}を追加</button>
        </div>}
        <h3 className="mt-6">送信停止 {suppressions.length}件</h3>
        {suppressions.map(entry => <article className="job-row block" key={entry.id}>
          <strong>{entry.domain || entry.email || entry.phone || '宛先未記録'}</strong>
          <p className="muted text-sm">{entry.reason} · {entry.source} · {entry.released_at ? `解除済み：${new Date(entry.released_at).toLocaleString('ja-JP')}` : '有効'}</p>
          {!entry.released_at && releaseControl(entry)}
        </article>)}
        {!suppressions.length && <p className="muted mt-3">利用企業の送信停止はありません。</p>}
      </>}
    </section>
    {isAdmin && <>
      <section className="panel">
        <h2>共通送信停止（運営）</h2>
        <p className="muted mt-2">運営判断による停止と本人確認済みの依頼です。解除は運営判断と理由を監査記録に残して行います。</p>
        <div className="detail-grid mt-3">
          <label className="field">ドメイン<input maxLength={253} value={globalDomain} onChange={event => setGlobalDomain(event.target.value)} placeholder="example.jp" /></label>
          <label className="field">メール<input type="email" maxLength={320} value={globalEmail} onChange={event => setGlobalEmail(event.target.value)} placeholder="privacy@example.jp" /></label>
          <label className="field">電話番号<input maxLength={100} value={globalPhone} onChange={event => setGlobalPhone(event.target.value)} /></label>
          <label className="field">設定理由<input required maxLength={500} value={globalReason} onChange={event => setGlobalReason(event.target.value)} /></label>
        </div>
        <button className="secondary" disabled={busy || (!globalDomain.trim() && !globalEmail.trim() && !globalPhone.trim()) || !globalReason.trim()} onClick={() => void addGlobalSuppression()}>共通送信停止を追加</button>
        {globalSuppressions.map(entry => <article className="job-row block" key={entry.id}>
          <strong>{entry.domain || entry.email}</strong><p className="muted text-sm">{entry.reason} · {entry.source} · {entry.released_at ? '解除済み' : '有効'}</p>
          {!entry.released_at && releaseControl(entry, true)}
        </article>)}
        {!globalSuppressions.length && <p className="muted mt-3">共通送信停止はありません。</p>}
      </section>
      <section className="panel">
        <h2>利用企業の統合</h2>
        <p className="muted mt-2">所属・メンバー・送信停止を統合します。project_accessは変更しません。</p>
        <div className="detail-grid mt-3">
          <label className="field">統合元<select value={mergeSourceId} onChange={event => { setMergeSourceId(event.target.value); setMergePreview(null) }}><option value="">選択</option>{allOrganizations.filter(org => org.status === 'active').map(org => <option key={org.id} value={org.id}>{org.name}</option>)}</select></label>
          <label className="field">統合先<select value={mergeTargetId} onChange={event => { setMergeTargetId(event.target.value); setMergePreview(null) }}><option value="">選択</option>{allOrganizations.filter(org => org.status === 'active').map(org => <option key={org.id} value={org.id}>{org.name}</option>)}</select></label>
        </div>
        <button className="secondary mt-3" disabled={busy || !mergeSourceId || !mergeTargetId || mergeSourceId === mergeTargetId} onClick={() => void previewMerge()}>影響をプレビュー</button>
        {mergePreview && <div className="mt-4"><p><strong>{mergePreview.source.name}</strong> → <strong>{mergePreview.target.name}</strong></p>
          <p>移動するプロジェクト：{mergePreview.projects.length}件</p>
          {mergePreview.projects.map(project => <p className="muted text-sm" key={project.id}>{project.name} · owner {project.owner_email}</p>)}
          <p className="mt-2">移動するメンバー：{mergePreview.members.length}人</p>
          {mergePreview.members.map(member => <p className="muted text-sm" key={member.id}>{member.email} · {member.role}</p>)}
          <button className="danger mt-3" disabled={busy} onClick={() => void mergeOrganizations()}>内容を確認して統合</button>
        </div>}
      </section>
    </>}
  </div>
}
