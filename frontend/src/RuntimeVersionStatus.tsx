import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'

type WorkerVersion = { commit_id: string; host_name: string; last_seen_at: string }
type RuntimeInfo = { api_commit: string; workers: WorkerVersion[] }

function normalizeRuntimeInfo(value: unknown): RuntimeInfo {
  if (!value || typeof value !== 'object') return { api_commit: 'unknown', workers: [] }
  const candidate = value as Partial<RuntimeInfo>
  return {
    api_commit: typeof candidate.api_commit === 'string' ? candidate.api_commit : 'unknown',
    workers: Array.isArray(candidate.workers) ? candidate.workers : [],
  }
}

export function RuntimeVersionStatus() {
  const [info, setInfo] = useState<RuntimeInfo | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    const refresh = () => api<RuntimeInfo>('/runtime-info')
      .then(value => { if (active) { setInfo(normalizeRuntimeInfo(value)); setError('') } })
      .catch(reason => { if (active) setError(errorMessage(reason)) })
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 60_000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])

  const mismatch = info?.workers.some(worker =>
    info.api_commit !== 'unknown' && worker.commit_id !== 'unknown' && worker.commit_id !== info.api_commit,
  ) ?? false

  return <section className="muted mt-8 border-t pt-3 text-xs" aria-label="稼働バージョン">
    {error ? <p>稼働版を確認できません: {error}</p> : <>
      <p>API版: {info?.api_commit ?? '確認中…'}</p>
      {info?.workers.length
        ? info.workers.map(worker => <p key={`${worker.host_name}-${worker.commit_id}-${worker.last_seen_at}`}>Worker版: {worker.commit_id} · {worker.host_name}</p>)
        : <p>直近5分以内のワーカー稼働記録はありません。</p>}
      {mismatch && <p className="error mt-2" role="alert">APIとワーカーの版が違います。ワーカーを更新してください</p>}
    </>}
  </section>
}
