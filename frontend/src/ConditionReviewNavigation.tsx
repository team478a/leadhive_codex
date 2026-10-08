import type { FactCondition } from './CollectionFactReview'
import { matchesReviewFilter } from './conditionReviewFilter'

export type ReviewCandidate = { company_id: string; state: string; conditions: (FactCondition & { priority: string; outcome: string })[] }
const filters: Record<string, string> = { ALL: 'すべて', REVIEW_REQUIRED: '確認待ち', AREA: '地域の確認待ち', INDUSTRY: '業種の確認待ち', OFFICIAL_SITE: '公式サイトの確認待ち', MEDIA_EXISTS: '掲載・SNSの確認待ち' }
export function ConditionReviewNavigation({ candidates, filter, onFilter, busy = false }: { candidates: ReviewCandidate[]; filter: string; onFilter: (value: string) => void; busy?: boolean }) {
  const visible = candidates.filter(c => matchesReviewFilter(c, filter))
  function next(button: HTMLButtonElement) {
    const container = button.closest('[data-condition-results]')
    const rows = Array.from(container?.querySelectorAll<HTMLDetailsElement>('details[data-condition-candidate][data-review-required="true"]') ?? [])
    if (!rows.length) return
    const current = rows.findIndex(row => row.open)
    const selected = rows[(current + 1) % rows.length]
    rows.forEach(row => { row.open = row === selected })
    selected.querySelector<HTMLElement>(':scope > summary')?.focus()
    selected.scrollIntoView({ block: 'nearest', behavior: 'auto' })
  }
  return <div className="space-y-2">
    <label>表示ページ内の絞り込み<select value={filter} disabled={busy} onChange={e => onFilter(e.target.value)}>{Object.entries(filters).map(([value, label]) => <option key={value} value={value}>{label}（{candidates.filter(c => matchesReviewFilter(c, value)).length}件）</option>)}</select></label>
    <p className="muted">表示中の候補だけを絞り込みます。他の候補はページ送りで確認してください。確認結果は自動保存しません。</p>
    <button type="button" disabled={busy || !visible.some(c => c.state === 'REVIEW_REQUIRED')} onClick={e => next(e.currentTarget)}>次の確認候補を開く</button>
    {filter !== 'ALL' && !visible.length && <p role="status">このページに該当する候補はありません。他のページも確認してください。</p>}
  </div>
}
