import { useCallback, useEffect, useState } from 'react'
import { api, download, errorMessage } from './api'

type StageCount = { order: number; stage: string; label: string; count: number }
type ReasonCount = { reason: string; label: string; count: number }
type PipelineSummary = {
  total_companies: number
  generated_at: string
  readiness_aggregated_at: string | null
  stages: StageCount[]
  missing_form_reasons: ReasonCount[]
  readiness_reasons: ReasonCount[]
}

function ReasonDetails({ label, rows }: { label: string; rows: ReasonCount[] }) {
  return <details className="mt-2 text-sm">
    <summary>{label}</summary>
    <div className="mt-2 flex flex-wrap gap-2">
      {rows.map(row => <span className={row.count === 0 ? 'badge opacity-50' : 'badge'} key={row.reason}>{row.label}：{row.count}社</span>)}
    </div>
  </details>
}

export function PipelineStagesSummary({ projectId, compact = false }: { projectId: string; compact?: boolean }) {
  const [data, setData] = useState<PipelineSummary | null>(null)
  const [error, setError] = useState('')
  const load = useCallback(async () => {
    if (!projectId) return
    setError('')
    try { setData(await api<PipelineSummary>(`/projects/${projectId}/pipeline-stages/summary`)) }
    catch (e) { setError(errorMessage(e)) }
  }, [projectId])
  useEffect(() => { void load() }, [load])
  if (compact) return <div className="mt-3">
    <button type="button" className="secondary" onClick={() => void download(`/projects/${projectId}/pipeline-stages.csv`, 'leadhive-pipeline-stages.csv').catch(e => setError(errorMessage(e)))}>段階CSVをダウンロード</button>
    {error && <p className="error mt-2" role="alert">{error}</p>}
  </div>
  return <div className="mt-4 rounded border p-3" aria-label="全体の流れ">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h3>全体の流れ（全{data?.total_companies ?? '—'}社）</h3>
        <p className="muted mt-1 text-sm">全企業を、最初に止まっている段階へ1社1件で分類します。</p></div>
      <button type="button" className="secondary" disabled={!data} onClick={() => void download(`/projects/${projectId}/pipeline-stages.csv`, 'leadhive-pipeline-stages.csv').catch(e => setError(errorMessage(e)))}>段階CSVをダウンロード</button>
    </div>
    {error && <p className="error mt-3" role="alert">{error}</p>}
    {data && <>
      <div className="mt-3 grid gap-2 md:grid-cols-2">
        {data.stages.map(stage => <div className={stage.count === 0 ? 'rounded border p-2 opacity-50' : 'rounded border p-2'} key={stage.stage}>
          <span>{stage.label}：{stage.count}社</span>
          {stage.stage === 'FORM_NOT_FOUND' && <ReasonDetails label="フォーム未発見の内訳" rows={data.missing_form_reasons} />}
          {stage.stage === 'BLOCKED_AT_READINESS' && <ReasonDetails label="送信可否で停止の内訳" rows={data.readiness_reasons} />}
        </div>)}
      </div>
      <p className="muted mt-3 text-xs">{data.readiness_aggregated_at
        ? `送信可否の内訳は、最後の再集計（${new Date(data.readiness_aggregated_at).toLocaleString('ja-JP')}）の時点の結果です。`
        : '送信可否はまだ集計されていません。'}</p>
    </>}
  </div>
}
