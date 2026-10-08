import type { CompletionWorkRow, CompletionQueueFilters } from './completionWorkQueueTypes'

// A navigation queue over received observations, never an authorization or retry queue.
export function CompletionWorkQueue({ rows, complete, onOpenCompany, filters, onFiltersChange }: {
  rows: CompletionWorkRow[]
  complete: boolean
  onOpenCompany: (id: string, filters: CompletionQueueFilters) => void
  filters: CompletionQueueFilters
  onFiltersChange: (value: CompletionQueueFilters) => void
}) {
  const { state, reason, page } = filters
  const rowReasons = (row: CompletionWorkRow) => [...row.reasons, ...(row.benchmark?.extra_reasons ?? [])]
  const reasons = new Map<string, { message: string; count: number }>()
  for (const row of rows) for (const code of new Set(rowReasons(row).map(r => r.code))) {
    const item = rowReasons(row).find(r => r.code === code)!
    reasons.set(code, { message: item.message, count: (reasons.get(code)?.count ?? 0) + 1 })
  }
  const needsDeliveryReview = (row: CompletionWorkRow) => row.delivery_funnel.results.UNKNOWN > 0 || row.delivery_funnel.unverified_records > 0
  const filtered = rows.filter(row => (
    state === 'ALL' || (state === 'DM_READY' ? row.dm_ready : state === 'DM_NOT_READY' ? !row.dm_ready : state === 'DELIVERY_REVIEW' ? needsDeliveryReview(row) : row.status === state)
  ) && (reason === 'ALL' || rowReasons(row).some(r => r.code === reason)))
  const lastPage = Math.max(0, Math.ceil(filtered.length / 25) - 1)
  const currentPage = Math.min(page, lastPage)
  const visible = filtered.slice(currentPage * 25, (currentPage + 1) * 25)
  return <section className="mt-5" aria-label="Lead Completion作業キュー">
    <h4>停止理由別の作業キュー</h4>
    <p className="muted">{complete ? '全件診断済み' : '部分集計・未診断分を含みません'}。取得済みの診断から企業詳細を開けます。修正後は再集計してください。複数理由や別窓口の理由も含みます。DM READYは送信許可ではありません。</p>
    <div className="detail-grid">
      <label className="field">作業キューの状態<select value={state} onChange={e => { onFiltersChange({ ...filters, state: e.target.value, page: 0 }) }}>
        <option value="ALL">すべて</option><option value="DM_NOT_READY">DM未準備</option><option value="DM_READY">DM READY・承認状態は詳細で確認</option>
        <option value="REVIEW">窓口REVIEW</option><option value="HOLD">窓口HOLD</option><option value="BLOCKED">窓口BLOCKED</option><option value="READY">窓口READY</option><option value="DELIVERY_REVIEW">結果不明・証跡のHuman確認</option>
      </select></label>
      <label className="field">作業キューの停止理由<select value={reason} onChange={e => { onFiltersChange({ ...filters, reason: e.target.value, page: 0 }) }}>
        <option value="ALL">すべての理由</option>{reason !== 'ALL' && !reasons.has(reason) && <option value={reason}>以前の理由・今回の診断範囲に該当なし（{reason}）</option>}{[...reasons].sort((a, b) => b[1].count - a[1].count || a[0].localeCompare(b[0])).map(([code, item]) => <option key={code} value={code}>{item.message}（{item.count}件）</option>)}
      </select></label>
    </div>
    <p role="status">作業対象 {filtered.length}件 / 診断済み {rows.length}件（{currentPage + 1} / {lastPage + 1}ページ、25件ずつ）</p>
    {visible.length === 0 && <p>該当する診断済み候補はありません。</p>}
    {visible.map(row => <article className="panel mt-3 break-words" key={row.company_id} aria-label={`作業候補 ${row.company_name ?? '削除・統合された候補'}`}>
      <strong>{row.company_name ?? '削除・統合された候補'}</strong>
      <p>窓口：{row.status} / {row.dm_ready ? 'DM READY' : 'DM未準備'}</p>
      {row.dm_ready_reason && <p>{row.dm_ready_reason}</p>}
      {row.status === 'BLOCKED' && <p>禁止理由を確認してください。スコアや下書きで禁止状態を解除できません。</p>}
      {needsDeliveryReview(row) && <p>結果不明または証跡不一致があります。Human確認が必要です。自動再送しません。</p>}
      {row.delivery_funnel.sent && <p>送信実行の履歴があります。送信履歴と重複窓口を確認してください。</p>}
      <ul>{rowReasons(row).map((item, i) => <li key={`${item.code}:${i}`}>{item.message} — {item.next_action} <small>({item.code})</small></li>)}</ul>
      <button className="secondary mt-3" disabled={row.company_name === null} onClick={() => onOpenCompany(row.company_id, { ...filters, page: currentPage })}>詳細を開く</button>
    </article>)}
    <div className="actions"><button className="secondary" disabled={currentPage === 0} onClick={() => onFiltersChange({ ...filters, page: currentPage - 1 })}>前の25件</button><button className="secondary" disabled={currentPage >= lastPage} onClick={() => onFiltersChange({ ...filters, page: currentPage + 1 })}>次の25件</button></div>
  </section>
}
