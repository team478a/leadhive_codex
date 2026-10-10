import type { OperationJob } from './types'

const stopNames: Record<string, string> = {
  TARGET_REACHED: '目標件数に到達', QUERIES_EXHAUSTED: '新規対象が増えず検索を終了',
  REQUEST_BUDGET_REACHED: '検索上限に到達', SOURCE_ERROR: '検索サービスでエラー',
}

export function CollectionProgress({ progress }: { progress: NonNullable<OperationJob['collection_progress']> }) {
  return <div className="muted my-2 text-sm">
    <p>{progress.conditions_applied ? '条件一致' : '新規候補'} {progress.collected_count} / {progress.target_count} 件・検索 {progress.requests} / {progress.request_budget} 回{progress.stop_reason && `・${stopNames[progress.stop_reason] ?? progress.stop_reason}`}</p>
    {progress.conditions_applied && <p>発見候補 {progress.discovered_count ?? '未集計'} 件・確認待ち {progress.review_required_count ?? '未集計'} 件・条件不一致 {progress.no_match_count ?? '未集計'} 件。確認待ちは条件一致や送信可能件数には含めません。</p>}
    {progress.scheduler_version && <p>検索語 {progress.planned_queries ?? '未集計'} 件・未検索 {progress.unsearched_queries ?? '未集計'} 件・継続候補 {progress.pending_queries ?? '未集計'} 件・エラー {progress.failed_queries ?? '未集計'} 件・ページ上限 {progress.capped_queries ?? '未集計'} 件。{progress.coverage_status === 'PARTIAL' ? '一部の検索が残っています。' : '設定範囲の検索を停止しました。'}地域内の全企業を取得できたという意味ではありません。</p>}
    {!!progress.unknown_attempts && <p>結果不明の検索 {progress.unknown_attempts} 回も検索予算に含めています。</p>}
    {progress.region_mode === 'prefecture_order' && <p>地域順の検索：{progress.planned_regions}地域・未検索{progress.unsearched_regions}地域{progress.current_region && `・次の継続地域 ${progress.current_region}`}。上限で停止した地域は自動で追加検索しません。</p>}
  </div>
}
