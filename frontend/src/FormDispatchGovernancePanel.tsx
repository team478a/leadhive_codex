import { useEffect, useRef, useState } from 'react'
import { api, errorMessage } from './api'
import { Field } from './forms'
import type { ApprovalProposal } from './ApprovedEmailPanel'

interface Limits {
  daily_limit: number; hourly_limit: number; minimum_interval_seconds: number
  site_interval_seconds: number
  paused: boolean; version: number; can_manage: boolean; execution_enabled: boolean
}
export function FormDispatchGovernancePanel({ projectId, items, canWrite, refresh }: {
  projectId: string; items: ApprovalProposal[]; canWrite: boolean; refresh: () => Promise<void>
}) {
  const [limits, setLimits] = useState<Limits | null>(null)
  const [savedLimits, setSavedLimits] = useState<Limits | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [password, setPassword] = useState('')
  const [adminPassword, setAdminPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const key = useRef<string | null>(null)
  const candidates = items.filter(i => i.channel === 'form' && ['PENDING', 'APPROVED'].includes(i.status))
  const chosen = candidates.filter(i => selected.includes(i.id))
  const pending = chosen.filter(i => i.status === 'PENDING')
  const approved = chosen.filter(i => i.status === 'APPROVED')
  const selections = (rows: ApprovalProposal[]) => rows.map(i => ({ request_id: i.id, expected_hash: i.payload_hash, expected_version: i.payload_version }))
  useEffect(() => {
    let live = true
    api<Limits>('/form-dispatch-limits').then(v => { if (live) { setLimits(v); setSavedLimits(v) } }).catch(e => { if (live) setError(errorMessage(e)) })
    return () => { live = false }
  }, [])
  async function act(fn: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try { await fn(); await refresh() } catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false); setPassword(''); setAdminPassword('') }
  }
  return <section className="panel mt-4" aria-label="フォーム一括承認と上限管理">
    <h2>フォームの一括Human承認・予約</h2>
    <p>このページの宛先・各社の入力値を確認して選択してください。一括承認と予約は別操作です。期限は最大24時間で、期限切れは実行できません。</p>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    <fieldset disabled={busy || !canWrite}>
      {candidates.map(i => <details key={i.id} className="my-3"><summary>{i.company_name} / {i.status} / v{i.payload_version}</summary>
        <p className="break-all">宛先: {i.form_url} / POST先: {i.form_action_url || '未確定'}</p>
        <p>送信者: {i.sender.name} / {i.sender.email}</p><p>{i.subject}</p><p className="whitespace-pre-wrap break-words">{i.body}</p>
        {Object.entries(i.field_values).map(([name, value]) => <p className="break-words" key={name}>{name}: {value}</p>)}
        <p>期限: {new Date(i.expires_at).toLocaleString('ja-JP')}</p>
        <label><input type="checkbox" checked={selected.includes(i.id)} disabled={!i.form_action_url} onChange={() => { key.current = null; setSelected(v => v.includes(i.id) ? v.filter(x => x !== i.id) : [...v, i.id]) }} /> {i.company_name}の入力内容を確認して選択</label>
      </details>)}
      <button type="button" className="secondary" disabled={!candidates.some(i => i.form_action_url)} onClick={() => { setSelected(candidates.filter(i => i.form_action_url).map(i => i.id)); key.current = null }}>このページのフォームをまとめて選択</button>{' '}
      <button type="button" className="secondary" onClick={() => { setSelected([]); key.current = null }}>フォーム選択を解除</button>
      <Field label="フォーム一括承認用ログインパスワード"><input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></Field>
      <button type="button" disabled={!pending.length || !password} onClick={() => act(async () => {
        const proof = await api<{ challenge_token: string }>(`/projects/${projectId}/bulk-approval/challenge`, 'POST', { items: selections(pending) })
        await api(`/projects/${projectId}/bulk-approval/verify`, 'POST', { challenge_token: proof.challenge_token, password })
        await api(`/projects/${projectId}/bulk-approval/approve`, 'POST', { challenge_token: proof.challenge_token })
        setNotice(`${pending.length}件をHuman承認しました。まだ予約していません。`)
      })}>フォーム{pending.length}件を一括Human承認</button>{' '}
      <button type="button" disabled={!approved.length} onClick={() => act(async () => {
        key.current ??= crypto.randomUUID()
        const result = await api<{ results: { request_id: string; reservation: unknown; error: string | null }[] }>(`/projects/${projectId}/approved-form-dispatches`, 'POST', { items: selections(approved), idempotency_key: key.current })
        const failures = result.results.filter(r => r.error)
        setNotice(`${result.results.length - failures.length}件を予約済みとして確認しました。${failures.length}件は未予約です。${limits?.execution_enabled ? '' : '実送信はOFFです。'}`)
        if (failures.length) setError(failures.map(r => `${r.request_id}: ${r.error}`).join(' / '))
      })}>承認済みフォーム{approved.length}件を一括予約</button>
    </fieldset>
    {limits && <div className="mt-4">
      <h3>環境全体のフォーム送信上限</h3>
      <p>保存済み: 直近24時間{savedLimits?.daily_limit}件・直近1時間{savedLimits?.hourly_limit}件・間隔{savedLimits?.minimum_interval_seconds}秒・同じサイト{savedLimits?.site_interval_seconds ?? 300}秒 / {savedLimits?.paused ? '一時停止中' : '上限に従って実行'} / 実行{savedLimits?.execution_enabled ? '有効' : 'OFF'}</p>
      <p>上限変更では実送信を有効化しません。結果不明・失敗した試行も上限に数えます。承認期限内に処理できる件数を予約してください。</p>
      {limits.can_manage && <fieldset disabled={busy}>
        <Field label="フォーム24時間上限"><input type="number" min="1" max="1000" value={limits.daily_limit} onChange={e => setLimits({ ...limits, daily_limit: Number(e.target.value) })} /></Field>
        <Field label="フォーム1時間上限"><input type="number" min="1" max="100" value={limits.hourly_limit} onChange={e => setLimits({ ...limits, hourly_limit: Number(e.target.value) })} /></Field>
        <Field label="フォーム試行間隔（秒）"><input type="number" min="60" max="86400" value={limits.minimum_interval_seconds} onChange={e => setLimits({ ...limits, minimum_interval_seconds: Number(e.target.value) })} /></Field>
        <Field label="同じサイトへの試行間隔（秒）"><input type="number" min="60" max="86400" value={limits.site_interval_seconds ?? 300} onChange={e => setLimits({ ...limits, site_interval_seconds: Number(e.target.value) })} /></Field>
        <label><input type="checkbox" checked={limits.paused} onChange={e => setLimits({ ...limits, paused: e.target.checked })} /> フォーム実行を一時停止</label>
        <Field label="上限変更用管理者パスワード"><input type="password" autoComplete="current-password" value={adminPassword} onChange={e => setAdminPassword(e.target.value)} /></Field>
        <p>上限の増加・停止解除は今後の予約実行に反映されます。内容を確認して保存してください。</p>
        <button type="button" disabled={!adminPassword} onClick={() => act(async () => {
          const updated = await api<Limits>('/form-dispatch-limits', 'PUT', { daily_limit: limits.daily_limit, hourly_limit: limits.hourly_limit, minimum_interval_seconds: limits.minimum_interval_seconds, site_interval_seconds: limits.site_interval_seconds ?? 300, paused: limits.paused, expected_version: limits.version, password: adminPassword })
          setLimits(updated); setSavedLimits(updated); setNotice('フォーム上限を保存しました。実送信設定は変更していません。')
        })}>管理者再認証してフォーム上限を保存</button>{' '}
        <button type="button" className="secondary" onClick={() => act(async () => { const next = await api<Limits>('/form-dispatch-limits'); setLimits(next); setSavedLimits(next) })}>保存済み上限を再取得</button>
      </fieldset>}
    </div>}
  </section>
}
