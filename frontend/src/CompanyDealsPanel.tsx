import type { Deal } from './types'

type Props = {
  deals: Deal[]
  title: string
  stage: Deal['stage']
  amount: number
  closeDate: string
  owner: string
  nextStep: string
  lostReason: string
  busy: boolean
  onTitleChange: (value: string) => void
  onStageChange: (value: Deal['stage']) => void
  onAmountChange: (value: number) => void
  onCloseDateChange: (value: string) => void
  onOwnerChange: (value: string) => void
  onNextStepChange: (value: string) => void
  onLostReasonChange: (value: string) => void
  onCreate: () => void
}

const stageNames: Record<Deal['stage'], string> = { lead: '見込み', proposal: '提案', negotiation: '交渉', won: '受注', lost: '失注' }

export function CompanyDealsPanel({ deals, title, stage, amount, closeDate, owner, nextStep, lostReason, busy, onTitleChange, onStageChange, onAmountChange, onCloseDateChange, onOwnerChange, onNextStepChange, onLostReasonChange, onCreate }: Props) {
  return <section className="panel mt-7"><h2>案件管理</h2><p className="muted mt-2 text-sm">商談後の見込み、次の対応、受注・失注を企業ごとに記録します。</p><div className="detail-grid mt-4"><label className="field">案件名<input maxLength={300} value={title} onChange={e => onTitleChange(e.target.value)} placeholder="例：採用支援サービス導入" /></label><label className="field">段階<select value={stage} onChange={e => onStageChange(e.target.value as Deal['stage'])}><option value="lead">見込み</option><option value="proposal">提案</option><option value="negotiation">交渉</option><option value="won">受注</option><option value="lost">失注</option></select></label><label className="field">見込金額（円）<input type="number" min={0} value={amount} onChange={e => onAmountChange(Number(e.target.value))} /></label><label className="field">受注見込日<input type="date" value={closeDate} onChange={e => onCloseDateChange(e.target.value)} /></label><label className="field">担当者<input maxLength={200} value={owner} onChange={e => onOwnerChange(e.target.value)} /></label><label className="field">次の対応<textarea rows={2} maxLength={5000} value={nextStep} onChange={e => onNextStepChange(e.target.value)} /></label>{stage === 'lost' && <label className="field">失注理由<textarea rows={2} maxLength={500} value={lostReason} onChange={e => onLostReasonChange(e.target.value)} /></label>}</div><div className="actions"><button disabled={busy || !title.trim()} onClick={onCreate}>案件を追加</button></div>{deals.map(deal => <article className="job-row" key={deal.id}><div><strong>{deal.title}</strong><p className="muted text-sm">{stageNames[deal.stage]} / {deal.expected_amount.toLocaleString()}円 / {deal.owner || '担当未設定'}</p>{deal.next_step && <p className="text-sm">次の対応：{deal.next_step}</p>}</div><span className="badge">{deal.expected_close_date || '日付未設定'}</span></article>)}{deals.length === 0 && <p className="muted mt-4">登録済み案件はありません。</p>}</section>
}
