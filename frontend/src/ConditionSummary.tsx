import { useEffect, useRef, useState } from 'react'
import { api, errorMessage } from './api'
import { conditionOutcomes, conditionPriorities, conditionReasons, conditionValue } from './collectionConditionLabels'

type Summary = {
  scope: 'PROJECT' | 'COLLECTION'; evaluated_at: string; total_candidates: number; evaluated_count: number; unevaluated_count: number; complete: boolean
  counts: Record<string, number>; excluded_duplicate_count: number; requested_count: number | null; shortfall: number | null; target_met: boolean | null; note: string
  reasons: { condition_id: string; value: string; priority: string; outcome: string; reason: string; affected_candidates: number }[]
}

export function ConditionSummary({ requestId, disabled }: { requestId: string; disabled: boolean }) {
  const [value, setValue] = useState<Summary | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const generation = useRef(0)
  useEffect(() => () => { generation.current += 1 }, [])
  async function read() {
    const current = ++generation.current
    setBusy(true); setError(''); setValue(null)
    try {
      const response = await api<Summary>(`/collection-conditions/${requestId}/summary?limit=500`)
      if (current === generation.current) setValue(response)
    } catch (e) { if (current === generation.current) setError(errorMessage(e)) }
    finally { if (current === generation.current) setBusy(false) }
  }
  return <section aria-label="条件一致と不足件数" className="panel min-w-0">
    <h3>条件一致と不足件数</h3>
    <p>表示ページの件数とは別に、保存済み候補を最大500件まで集計します。条件の変更・追加検索は行いません。</p>
    <button type="button" disabled={disabled || busy} onClick={() => void read()}>{busy ? '集計中…' : '条件一致と不足件数を集計'}</button>
    {error && <p role="alert" className="error">{error}</p>}
    {value && <>
      <p>{value.scope === 'COLLECTION' ? '指定した収集の候補' : 'このプロジェクトの保存済み候補'}：{value.total_candidates}件。集計済み {value.evaluated_count}件。{value.complete ? '全件集計' : `一部集計（未集計 ${value.unevaluated_count}件）`}。</p>
      <p>条件一致 {value.counts.MATCH}件 / 不一致・除外 {value.counts.NO_MATCH}件 / 確認待ち {value.counts.REVIEW_REQUIRED}件{!value.complete && '（集計済み候補内の件数）'}</p>
      <p>登録済み重複 {value.excluded_duplicate_count}件（目標件数から除外）。未判明の重複まで解消済みという意味ではありません。</p>
      <p>目標：{value.requested_count === null ? '指定なし' : `${value.requested_count}件`}。不足：{value.shortfall === null ? (value.requested_count === null ? '目標未指定' : '未確定（一部集計のため）') : `${value.shortfall}件`}。</p>
      {value.target_met === true && <p>条件一致の目標件数を満たしています。送信可能・送信承認済みという意味ではありません。</p>}
      <p className="muted">集計日時：{new Date(value.evaluated_at).toLocaleString('ja-JP')}。根拠や候補の変更後は再集計してください。確認結果の保存・判定結果の再表示後は集計をクリアします。</p>
      <h4>一致を止めている条件と理由</h4>
      {!value.reasons.length && <p>集計済み候補に停止理由はありません。候補が0件の場合も同じ表示になります。</p>}
      <ul>{value.reasons.slice(0, 10).map(r => <li key={`${r.condition_id}-${r.outcome}-${r.reason}`}>
        {conditionPriorities[r.priority]}・{conditionValue(r.value)}：{conditionOutcomes[r.outcome]}、{conditionReasons[r.reason] ?? r.reason}（{r.affected_candidates}件）
      </li>)}</ul>
      {value.reasons.length > 10 && <p>件数の多い上位10項目を表示しています。その他の理由は個別の条件判定結果で確認してください。</p>}
      <p className="muted">{value.note}</p>
    </>}
  </section>
}
