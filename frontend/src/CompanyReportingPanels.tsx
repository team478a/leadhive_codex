import type { AssigneeAnalytics, DealPipeline } from './types'

const dealStageNames: Record<string, string> = { lead: '見込み', proposal: '提案', negotiation: '交渉', won: '受注', lost: '失注' }

export function DealPipelinePanel({ pipeline }: { pipeline: DealPipeline | null }) {
  if (!pipeline) return null
  return <section className="panel mt-6"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2>案件パイプライン</h2><p className="muted mt-2 text-sm">このプロジェクト全体の見込み案件、金額、次の対応を確認できます。</p></div><span className="badge">見込金額 {pipeline.total_amount.toLocaleString()}円</span></div><div className="job-stats mt-4">{Object.entries(pipeline.by_stage).map(([stage, count]) => <span key={stage}>{dealStageNames[stage] ?? stage} {count}</span>)}</div>{pipeline.items.length === 0 ? <p className="muted mt-4">登録済み案件はありません。</p> : <div className="company-table-wrap mt-4"><table className="company-table"><thead><tr><th>企業</th><th>案件</th><th>段階</th><th>見込金額</th><th>次の対応</th><th>予定日</th></tr></thead><tbody>{pipeline.items.slice(0, 20).map(deal => <tr key={deal.id}><td>{deal.company_name}</td><td>{deal.title}</td><td>{dealStageNames[deal.stage]}</td><td>{deal.expected_amount.toLocaleString()}円</td><td>{deal.next_step || '未設定'}</td><td>{deal.expected_close_date || '未設定'}</td></tr>)}</tbody></table></div>}</section>
}

export function AssigneeAnalyticsPanel({ items }: { items: AssigneeAnalytics[] }) {
  return <section className="panel mt-6"><div className="flex items-center justify-between gap-3"><div><h2>担当者別営業成果</h2><p className="muted mt-2 text-sm">担当企業数と現在の営業状況、期限超過を比較します。</p></div><span className="badge">{items.length} 人</span></div><div className="company-table-wrap mt-4"><table className="company-table"><thead><tr><th>担当者</th><th>担当企業</th><th>アプローチ</th><th>返信</th><th>商談</th><th>成約</th><th>期限超過</th></tr></thead><tbody>{items.map(item => <tr key={item.assignee}><td><strong>{item.assignee}</strong></td><td>{item.total}</td><td>{item.approached}</td><td>{item.replied}</td><td>{item.meetings}</td><td>{item.won}</td><td>{item.overdue}</td></tr>)}{items.length === 0 && <tr><td colSpan={7} className="text-center muted">集計対象の企業はありません。</td></tr>}</tbody></table></div></section>
}
