import type { OutreachChannel, OutreachQueueItem, SalesStatus } from './types'
import { channelNames, dueNames, statusNames } from './companyPageShared'

type Props = {
  items: OutreachQueueItem[]
  target: OutreachQueueItem | null
  channel: OutreachChannel
  outcome: SalesStatus
  note: string
  followup: string
  busy: boolean
  onStart: (item: OutreachQueueItem) => void
  onChannelChange: (value: OutreachChannel) => void
  onOutcomeChange: (value: SalesStatus) => void
  onNoteChange: (value: string) => void
  onFollowupChange: (value: string) => void
  onRecord: () => void
  onCancel: () => void
}

export function CompanyOutreachQueuePanel({ items, target, channel, outcome, note, followup, busy, onStart, onChannelChange, onOutcomeChange, onNoteChange, onFollowupChange, onRecord, onCancel }: Props) {
  return <section className="panel mt-6"><div className="flex items-center justify-between gap-3"><div><h2>営業アプローチキュー</h2><p className="muted mt-2 text-sm">期限超過を優先し、連絡可能な営業対象を処理します。</p></div><span className="badge">{items.length} 社</span></div><div className="company-table-wrap mt-4"><table className="company-table"><thead><tr><th>企業</th><th>推奨経路</th><th>担当者</th><th>期限</th><th>状況</th><th></th></tr></thead><tbody>{items.map(item => <tr key={item.company.id}><td><strong>{item.company.company_name}</strong><p className="muted text-xs">{item.company.rank ?? '—'} / {item.company.score ?? '—'}点</p></td><td>{channelNames[item.recommended_channel]}<p className="muted text-xs">{item.available_channels.map(itemChannel => channelNames[itemChannel]).join(' / ')}</p></td><td>{item.company.assignee || '未設定'}</td><td><span className="badge">{dueNames[item.due_state]}</span><p className="muted text-xs">{item.company.next_followup_at ? new Date(item.company.next_followup_at).toLocaleString('ja-JP') : '—'}</p></td><td>{statusNames[item.company.status]}</td><td><button className="secondary" onClick={() => onStart(item)}>対応する</button></td></tr>)}{items.length === 0 && <tr><td colSpan={6} className="text-center muted">連絡可能な営業対象はありません。</td></tr>}</tbody></table></div>{target && <div className="mt-5"><h3>{target.company.company_name}への対応記録</h3><div className="detail-grid"><div><label className="field">連絡経路<select value={channel} onChange={e => onChannelChange(e.target.value as OutreachChannel)}>{target.available_channels.map(itemChannel => <option key={itemChannel} value={itemChannel}>{channelNames[itemChannel]}</option>)}</select></label><label className="field">結果<select value={outcome} onChange={e => onOutcomeChange(e.target.value as SalesStatus)}><option value="approached">アプローチ済</option><option value="replied">返信あり</option><option value="meeting">商談</option><option value="lost">失注</option></select></label><label className="field">次回対応日時<input type="datetime-local" value={followup} onChange={e => onFollowupChange(e.target.value)} /></label></div><label className="field">対応内容<textarea rows={5} maxLength={10000} value={note} onChange={e => onNoteChange(e.target.value)} placeholder="送信内容、通話結果、次回確認事項" /></label></div><div className="actions"><button disabled={busy || !note.trim()} onClick={onRecord}>対応を記録</button><button className="secondary" onClick={onCancel}>キャンセル</button></div></div>}</section>
}
