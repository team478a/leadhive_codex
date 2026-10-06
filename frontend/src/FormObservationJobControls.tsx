import { useEffect, useState } from 'react'
import { api, ApiError } from './api'

type Job = {
  id: string; status: string; cancel_requested: boolean; recoverable: boolean; reason_code: string | null
  events: { id: string; event_type: string; reason_code: string; principal_type: string; created_at: string }[]
  events_has_more: boolean
}
type Result = { available: boolean; can_start: boolean; can_manage: boolean; items: Job[] }
const reasons: Record<string, string> = {
  QUEUED: '登録済み', CLAIMED: '取得処理を開始', CANCELLED: '停止要求・停止', EVIDENCE_SAVED: '診断証拠を保存',
  CLAIM_REJECTED: '開始条件が変わったため停止', OBSERVATION_FAILED: '取得・解析・保存のいずれかに失敗（詳細分類は未対応）',
  BINDING_CHANGED: '企業・ジョブの結合情報が変更', LEASE_CHANGED: '処理の担当が変更', WORKER_LOST: '担当処理の有効期限切れ',
  PERMISSION_CHANGED: '実行者の権限が変更', SOURCE_CHANGED: '企業URLが変更', LAB_DISABLED: '検証機能が無効',
}
const states: Record<string, string> = { queued: '待機中', running: '実行中', completed: '診断保存完了', failed: '失敗', cancelled: '停止済み' }

export function FormObservationJobControls({ companyId, onUpdated }: { companyId: string; onUpdated: () => void }) {
  const [result, setResult] = useState<Result | null>(null)
  const [reload, setReload] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    api<Result>(`/companies/${companyId}/form-observation-jobs?limit=1`)
      .then(value => { if (active) { setResult(value); setError('') } })
      .catch(() => {
        if (active) {
          if (reload > 0) setError('最新の状態を取得できません。表示は更新前の状態です。再度更新してください。')
          else setResult(null)
        }
      })
    return () => { active = false }
  }, [companyId, reload])
  if (!result?.available || (!result.can_start && result.items.length === 0)) return null
  const job = result.items[0]
  const pending = job && ['queued', 'running'].includes(job.status)
  async function action(path: string) {
    setBusy(true); setError('')
    try {
      const updated = await api<Job>(path, 'POST', {})
      setResult(value => value ? { ...value, items: [updated] } : value)
      setReload(value => value + 1); onUpdated()
    } catch (e) {
      setError(e instanceof ApiError && e.status === 409 ? '現在の状態では操作できません。状態を更新して確認してください。' : '操作できません。権限と接続状態を確認してください。')
    } finally { setBusy(false) }
  }
  return <div aria-label="管理下観察ジョブ操作">
    <p>管理下テスト専用です。登録だけでは取得は始まりません。専用の検証runnerによる実行が必要です。</p>
    {error && <p role="alert">{error}</p>}
    {result.can_start && <button type="button" disabled={busy || !!pending} onClick={() => action(`/companies/${companyId}/form-observation-jobs`)}>管理下の観察を登録</button>}
    {result.can_manage && <button type="button" disabled={busy} onClick={() => { setReload(value => value + 1); onUpdated() }}>観察ジョブの状態を更新</button>}
    {job && <>
      <p>ジョブ状態：{states[job.status] ?? '不明'}{job.cancel_requested && job.status === 'running' ? '（停止要求済み）' : ''}</p>
      {job.reason_code && <p>{reasons[job.reason_code] ?? '詳細を確認できません'}</p>}
      {result.can_manage && pending && <button type="button" disabled={busy || job.cancel_requested} onClick={() => action(`/form-observation-jobs/${job.id}/cancel`)}>観察ジョブを停止</button>}
      {result.can_manage && job.recoverable && <button type="button" disabled={busy} onClick={() => action(`/form-observation-jobs/${job.id}/recover`)}>期限切れの観察ジョブを終了</button>}
      <ul>{job.events.map(event => <li key={event.id}>{new Date(event.created_at).toLocaleString()}：{reasons[event.reason_code] ?? '不明'}（{event.principal_type === 'HUMAN' ? '利用者操作' : 'システム処理'}）</li>)}</ul>
      {job.events_has_more && <p>直近50件の監査記録を表示しています。</p>}
    </>}
  </div>
}
