import type { ReplyQueueItem } from './types'

type Outcome = 'replied' | 'meeting' | 'won' | 'lost'

type Props = {
  items: ReplyQueueItem[]
  target: ReplyQueueItem | null
  outcome: Outcome
  note: string
  followup: string
  busy: boolean
  onStart: (item: ReplyQueueItem) => void
  onOutcomeChange: (value: Outcome) => void
  onNoteChange: (value: string) => void
  onFollowupChange: (value: string) => void
  onRecord: () => void
  onCancel: () => void
}

export function CompanyReplyQueuePanel({ items, target, outcome, note, followup, busy, onStart, onOutcomeChange, onNoteChange, onFollowupChange, onRecord, onCancel }: Props) {
  return <section className="panel mt-6"><div className="flex items-center justify-between gap-3"><div><h2>返信対応キュー</h2><p className="muted mt-2 text-sm">受信した返信を確認し、商談化・失注・次回対応を記録します。</p></div><span className="badge">{items.length} 件</span></div><div className="company-table-wrap mt-4"><table className="company-table"><thead><tr><th>企業</th><th>受信内容</th><th>受信日時</th><th>担当</th><th></th></tr></thead><tbody>{items.map(item => <tr key={item.inbound_email_id}><td><strong>{item.company.company_name}</strong><p className="muted text-xs">{item.company.email || item.sender_email}</p></td><td><strong>{item.subject || '件名なし'}</strong><p className="muted text-xs">{item.preview}</p></td><td>{new Date(item.received_at).toLocaleString('ja-JP')}</td><td>{item.company.assignee || '未設定'}</td><td><button className="secondary" onClick={() => onStart(item)}>対応する</button></td></tr>)}{items.length === 0 && <tr><td colSpan={5} className="text-center muted">対応待ちの返信はありません。</td></tr>}</tbody></table></div>{target && <div className="mt-5"><h3>{target.company.company_name}への返信対応</h3><p className="muted text-sm mt-2">{target.sender_email} / {target.subject || '件名なし'}</p><p className="mt-2 text-sm whitespace-pre-wrap">{target.preview || '本文の要約はありません。'}</p><div className="detail-grid mt-4"><div><label className="field">対応結果<select value={outcome} onChange={e => onOutcomeChange(e.target.value as Outcome)}><option value="replied">返信確認・継続対応</option><option value="meeting">商談化</option><option value="won">成約</option><option value="lost">失注</option></select></label><label className="field">次回対応日時<input type="datetime-local" value={followup} onChange={e => onFollowupChange(e.target.value)} /></label></div><label className="field">対応内容<textarea rows={4} maxLength={10000} value={note} onChange={e => onNoteChange(e.target.value)} placeholder="返信内容、対応方針、商談日時など" /></label></div><div className="actions"><button disabled={busy || !note.trim()} onClick={onRecord}>返信対応を記録</button><button className="secondary" onClick={onCancel}>キャンセル</button></div></div>}</section>
}
