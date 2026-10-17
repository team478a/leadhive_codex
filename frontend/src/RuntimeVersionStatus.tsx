import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'

type WorkerVersion = {
  instance_id: string
  worker_type: 'application' | 'browser'
  commit_id: string
  host_name: string
  last_seen_at: string
}
type RuntimeInfo = { api_commit: string; workers: WorkerVersion[] }

function normalizeRuntimeInfo(value: unknown): RuntimeInfo {
  if (!value || typeof value !== 'object') return { api_commit: 'unknown', workers: [] }
  const candidate = value as Partial<RuntimeInfo>
  return {
    api_commit: typeof candidate.api_commit === 'string' ? candidate.api_commit : 'unknown',
    workers: Array.isArray(candidate.workers) ? candidate.workers.map(worker => ({
      ...worker,
      instance_id: typeof worker.instance_id === 'string' ? worker.instance_id : '',
      worker_type: worker.worker_type === 'browser' ? 'browser' : 'application',
    })) : [],
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

  const applicationWorkers = info?.workers.filter(worker => worker.worker_type === 'application') ?? []
  const browserWorkers = info?.workers.filter(worker => worker.worker_type === 'browser') ?? []
  const mismatch = info !== null && applicationWorkers.some(worker =>
    info.api_commit !== 'unknown' && worker.commit_id !== 'unknown' && worker.commit_id !== info.api_commit,
  )

  const renderWorkers = (workers: WorkerVersion[], label: string) => workers.length
    ? workers.map(worker => <p key={`${worker.instance_id}-${worker.last_seen_at}`}>{label}版: {worker.commit_id} · {worker.host_name}</p>)
    : <p>直近5分以内の{label}稼働記録はありません。</p>

  return <section className="muted mt-8 border-t pt-3 text-xs" aria-label="稼働バージョン">
    {error ? <p>稼働版を確認できません: {error}</p> : <>
      <p>API版: {info?.api_commit ?? '確認中…'}</p>
      {renderWorkers(applicationWorkers, '本体ワーカー')}
      {renderWorkers(browserWorkers, 'ブラウザーワーカー')}
      {mismatch && <p className="error mt-2" role="alert">APIとワーカーの版が違います。ワーカーを更新してください</p>}
    </>}
  </section>
}
