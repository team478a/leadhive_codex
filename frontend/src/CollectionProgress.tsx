import type { OperationJob } from './types'

const stopNames: Record<string, string> = {
  TARGET_REACHED: '目標件数に到達', QUERIES_EXHAUSTED: '新規対象が増えず検索を終了',
  REQUEST_BUDGET_REACHED: '検索上限に到達', SOURCE_ERROR: '検索サービスでエラー',
}

export function CollectionProgress({ progress }: { progress: NonNullable<OperationJob['collection_progress']> }) {
  return <div className="muted my-2 text-sm">
    <p>{progress.conditions_applied ? '条件一致' : '新規候補'} {progress.collected_count} / {progress.target_count} 件・検索 {progress.requests} / {progress.request_budget} 回{progress.stop_reason && `・${stopNames[progress.stop_reason] ?? progress.stop_reason}`}</p>
    {progress.conditions_applied && <p>発見候補 {progress.discovered_count ?? '未集計'} 件・確認待ち {progress.review_required_count ?? '未集計'} 件・条件不一致 {progress.no_match_count ?? '未集計'} 件。確認待ちは条件一致や送信可能件数には含めません。</p>}
  </div>
}
