import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import type { RuntimeCapacity } from './types'

function bytes(value: number | null) {
  if (value === null) return '取得不可'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let amount = value
  let unit = 0
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1 }
  return `${amount.toFixed(unit < 2 ? 0 : 1)} ${units[unit]}`
}

function seconds(value: number) {
  if (value < 60) return `${value.toFixed(1)}秒`
  return `${(value / 60).toFixed(1)}分`
}

export function RuntimeCapacityPanel() {
  const [capacity, setCapacity] = useState<RuntimeCapacity | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function load() {
    setBusy(true); setError('')
    try { setCapacity(await api<RuntimeCapacity>('/admin/runtime-capacity')) }
    catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false) }
  }

  useEffect(() => { void load() }, [])

  return <section className="mt-7 border-t pt-5" aria-label="実行環境">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2>実行環境</h2><p className="muted mt-2">worker、CPU・メモリ、DB接続と直近24時間の処理量を読み取り専用で表示します。</p></div><button className="secondary" disabled={busy} onClick={() => void load()}>{busy ? '更新中…' : '更新'}</button></div>
    {error && <p className="error mt-4" role="alert">{error}</p>}
    {capacity && <>
      <div className="detail-grid mt-5">
        <div><strong>CPU</strong><p>{capacity.process.cpu_count ?? '取得不可'} CPU / cgroup上限 {capacity.process.cpu_limit === null ? 'なし・取得不可' : capacity.process.cpu_limit.toFixed(2)}</p></div>
        <div><strong>メモリ</strong><p>{bytes(capacity.process.memory_current_bytes)} / {bytes(capacity.process.memory_limit_bytes)}</p></div>
        <div><strong>DB接続</strong><p>{capacity.database.current_connections ?? '取得不可'} / {capacity.database.max_connections ?? '取得不可'}、pool {capacity.database.pool_size}+{capacity.database.max_overflow}</p></div>
        <div><strong>DB容量</strong><p>{bytes(capacity.database.database_size_bytes)} / shared_buffers {capacity.database.shared_buffers ?? '取得不可'}</p></div>
      </div>
      <h3 className="mt-6">worker</h3>
      {!capacity.workers.length ? <p className="muted mt-2">直近5分のheartbeatはありません。</p> : <div className="company-table-wrap mt-3"><table className="company-table"><thead><tr><th>instance</th><th>種別</th><th>版・最終記録</th><th>実行中</th><th>仕事の絞り込み</th></tr></thead><tbody>{capacity.workers.map(worker => <tr key={worker.instance_id}><td>{worker.instance_id}<p className="muted text-xs">{worker.host_name}</p></td><td>{worker.worker_type}</td><td>{worker.commit_id}<p className="muted text-xs">{new Date(worker.last_seen_at).toLocaleString('ja-JP')}</p></td><td>{worker.current_operation ? <>{worker.current_operation.operation_type}<p className="muted text-xs">{worker.current_operation.project_name}</p></> : '待機中・取得不可'}</td><td>{worker.include_operation_types?.join(', ') || '全種類・未記録'}{worker.exclude_operation_types?.length ? <p className="muted text-xs">除外: {worker.exclude_operation_types.join(', ')}</p> : null}</td></tr>)}</tbody></table></div>}
      <h3 className="mt-6">直近24時間</h3>
      {!capacity.jobs_last_24_hours.length ? <p className="muted mt-2">処理履歴はありません。</p> : <div className="company-table-wrap mt-3"><table className="company-table"><thead><tr><th>仕事</th><th>件数</th><th>合計実行時間</th><th>平均待ち時間</th></tr></thead><tbody>{capacity.jobs_last_24_hours.map(row => <tr key={row.operation_type}><td>{row.operation_type}</td><td>{row.count}</td><td>{seconds(row.total_run_seconds)}</td><td>{seconds(row.average_wait_seconds)}</td></tr>)}</tbody></table></div>}
      <p className="muted mt-3 text-xs">取得日時: {new Date(capacity.generated_at).toLocaleString('ja-JP')}</p>
    </>}
  </section>
}
