import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from './api'

type CountRow = Record<string, string | number | null> & { count: number }
type UsageRow = {
  kind: string
  provider: string
  model: string
  status: string
  currency: string | null
  event_count: number
  estimated_cost: string | null
  cost_missing_count: number
  input_tokens: number | null
  output_tokens: number | null
  input_tokens_missing_count: number
  output_tokens_missing_count: number
}
type UsageReport = {
  window_days: number
  window_start: string
  generated_at: string
  coverage: {
    processing_usage_partial: boolean
    historical_proposal_events_available: boolean
    note: string
  }
  collection_jobs: CountRow[]
  active_collection_jobs: Array<{ source: string; count: number }>
  companies_by_source: CountRow[]
  operation_jobs: CountRow[]
  active_operation_jobs: Array<{ operation_type: string; status: string; count: number }>
  form_delivery_batches: CountRow[]
  active_form_delivery_batches: number
  latest_form_delivery_batch_at: string | null
  processing_usage: UsageRow[]
  external_presence_searches: CountRow[]
  collection_condition_requests: number
  collection_fact_reviews: number
  feature_usage_events: CountRow[]
  historical_proposal_calls: number | null
  raw: Record<string, number>
  completion_metrics: Record<string, number>
  legacy_input_activity_counts: Record<string, string | number>
  cf7_fixture_observations: Record<string, string | number>
}

function CountTable({ title, rows, columns }: {
  title: string
  rows: CountRow[]
  columns: Array<{ key: string; label: string }>
}) {
  return <section className="panel">
    <h3>{title}</h3>
    {rows.length === 0 ? <p className="muted mt-3">該当する記録はありません。</p> : <div className="overflow-x-auto mt-3">
      <table className="w-full text-sm"><thead><tr>{columns.map(column => <th className="text-left p-2" key={column.key}>{column.label}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => <tr className="border-t" key={`${title}-${index}`}>
          {columns.map(column => <td className="p-2" key={column.key}>{row[column.key] ?? '—'}</td>)}
        </tr>)}</tbody>
      </table>
    </div>}
  </section>
}

function NumberGrid({ title, values }: { title: string; values: Record<string, number | string> }) {
  return <section className="panel">
    <h3>{title}</h3>
    <dl className="grid gap-3 sm:grid-cols-2 mt-3">{Object.entries(values).map(([label, value]) => <div className="card" key={label}>
      <dt className="muted text-sm">{label}</dt><dd className="text-xl font-semibold mt-1">{value}</dd>
    </div>)}</dl>
  </section>
}

export function UsageReportPage() {
  const [report, setReport] = useState<UsageReport | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setReport(await api<UsageReport>('/admin/usage-report'))
    } catch (cause) {
      setError(errorMessage(cause))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void reload() }, [reload])

  if (loading) return <p role="status">利用状況を集計しています…</p>
  if (error) return <section className="panel"><p className="error" role="alert">{error}</p><button onClick={() => void reload()}>再読み込み</button></section>
  if (!report) return null

  return <div className="space-y-5">
    <section className="panel">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h2>機能の利用状況</h2><p className="muted mt-2">直近{report.window_days}日 · 集計時刻 {new Date(report.generated_at).toLocaleString('ja-JP')}</p></div>
        <button className="secondary" onClick={() => void reload()}>更新</button>
      </div>
      <p className="notice mt-4">{report.coverage.note}</p>
      <p className="muted text-sm mt-2">件数はDB内の記録数です。検索job数・保存企業数・計測済みAPI記録・請求額を同一視しないでください。</p>
    </section>

    <CountTable title="収集job（source・status別）" rows={report.collection_jobs} columns={[
      { key: 'source', label: '収集元' }, { key: 'status', label: '状態' }, { key: 'count', label: '90日件数' },
    ]} />
    <CountTable title="収集後に保存された企業（source別）" rows={report.companies_by_source} columns={[
      { key: 'source', label: '保存source' }, { key: 'count', label: '90日件数' },
    ]} />
    <NumberGrid title="現在の収集job" values={Object.fromEntries(report.active_collection_jobs.map(row => [row.source, row.count]))} />
    <CountTable title="OperationJob（type・status別）" rows={report.operation_jobs.map(row => ({ ...row, count: Number(row.count) }))} columns={[
      { key: 'operation_type', label: '処理' }, { key: 'status', label: '状態' }, { key: 'count', label: '90日件数' },
    ]} />
    <CountTable title="現在実行中・待機中のOperationJob" rows={report.active_operation_jobs.map(row => ({ ...row, count: row.count }))} columns={[
      { key: 'operation_type', label: '処理' }, { key: 'status', label: '状態' }, { key: 'count', label: '現在件数' },
    ]} />
    <section className="panel">
      <h3>旧フォームDMバッチ</h3>
      <p className="mt-2">現在のready/running：<strong>{report.active_form_delivery_batches}件</strong></p>
      <p className="muted mt-1">最後に作成された日時：{report.latest_form_delivery_batch_at ? new Date(report.latest_form_delivery_batch_at).toLocaleString('ja-JP') : '記録なし'}</p>
      <ul className="mt-2">{report.form_delivery_batches.map(row => <li key={String(row.status)}>{row.status}：{row.count}件（90日）</li>)}</ul>
    </section>
    <CountTable title="計測済みの外部検索・AI利用（部分計測）" rows={report.processing_usage.map(row => ({
      kind: row.kind === 'search' ? '検索' : 'AI', provider: row.provider, model: row.model || '—', status: row.status,
      currency: row.currency ?? '通貨不明', count: row.event_count,
      cost: row.estimated_cost === null ? `未計測 ${row.cost_missing_count}件` : `${row.estimated_cost} ${row.currency ?? ''}`,
      tokens: `入力 ${row.input_tokens ?? '—'} / 出力 ${row.output_tokens ?? '—'}`,
    }))} columns={[
      { key: 'kind', label: '種別' }, { key: 'provider', label: 'provider' }, { key: 'model', label: 'model' },
      { key: 'status', label: '結果' }, { key: 'count', label: '記録件数' }, { key: 'cost', label: '費用推定' }, { key: 'tokens', label: 'token合計' },
    ]} />
    <CountTable title="SNS検索の試行記録（完了API回数ではありません）" rows={report.external_presence_searches} columns={[
      { key: 'platform', label: '媒体' }, { key: 'status', label: '状態' }, { key: 'count', label: '90日件数' },
    ]} />
    <NumberGrid title="収集条件" values={{
      '確定条件revision': report.collection_condition_requests,
      '人による事実確認': report.collection_fact_reviews,
      '条件提案（記録開始後）': report.feature_usage_events.filter(row => row.event_type === 'collection_condition_proposal').reduce((sum, row) => sum + Number(row.count), 0),
      '条件提案（過去分）': report.historical_proposal_calls === null ? '計測記録なし' : report.historical_proposal_calls,
    }} />
    <CountTable title="新しい内容非保存イベント（90日）" rows={report.feature_usage_events.map(row => ({
      ...row,
      event_type: ({
        collection_condition_proposal: '収集条件の提案',
        pc_input_trial_issued: 'PC入力試行の発行',
        pc_input_report_recorded: 'PC入力結果の記録',
        live_input_trial_issued: 'ライブ入力試行の発行',
        live_input_report_recorded: 'ライブ入力結果の記録',
      } as Record<string, string>)[String(row.event_type)] ?? row.event_type,
      outcome: row.outcome === 'completed' ? '記録済み' : '失敗',
    }))} columns={[
      { key: 'event_type', label: '機能' }, { key: 'outcome', label: '結果' }, { key: 'count', label: '件数' },
    ]} />
    <NumberGrid title="RAW・レビュー記録（90日）" values={{
      'ベンチマーク': report.raw.benchmarks,
      '検索実行': report.raw.query_runs,
      '候補snapshot': report.raw.snapshots,
      'レビューsession': report.raw.review_sessions,
      '候補レビュー': report.raw.lead_reviews,
      '候補ペアレビュー': report.raw.pair_reviews,
    }} />
    <NumberGrid title="完成度レビュー記録（90日・画面閲覧数ではありません）" values={{
      'cohort': report.completion_metrics.cohorts,
      'レビューsession': report.completion_metrics.review_sessions,
    }} />
    <NumberGrid title="入力試行（旧Activity prefixからの集計・90日）" values={{
      'PC入力依頼': report.legacy_input_activity_counts.pc_trials,
      'PC入力報告': report.legacy_input_activity_counts.pc_reports,
      'ライブ入力依頼': report.legacy_input_activity_counts.live_trials,
      'ライブ入力報告': report.legacy_input_activity_counts.live_reports,
      '計測範囲': report.legacy_input_activity_counts.coverage,
    }} />
    <NumberGrid title="CF7制御fixture観測（本番利用数ではありません）" values={{
      '合計': report.cf7_fixture_observations.total,
      '有効': report.cf7_fixture_observations.active,
      '期限切れ': report.cf7_fixture_observations.expired,
      '対象範囲': report.cf7_fixture_observations.coverage,
    }} />
  </div>
}
