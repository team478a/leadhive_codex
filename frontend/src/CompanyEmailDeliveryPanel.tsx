import type { Company, ContactPerson, EmailDelivery } from './types'

type Props = {
  company: Company
  contacts: ContactPerson[]
  delivery: EmailDelivery | null
  recipient: string
  scheduledAt: string
  confirmed: boolean
  busy: boolean
  onRecipientChange: (value: string) => void
  onScheduledAtChange: (value: string) => void
  onConfirmedChange: (value: boolean) => void
  onSchedule: () => void
  onCancel: () => void
  onRetry: () => void
}

export function CompanyEmailDeliveryPanel({ company, contacts, delivery, recipient, scheduledAt, confirmed, busy, onRecipientChange, onScheduledAtChange, onConfirmedChange, onSchedule, onCancel, onRetry }: Props) {
  return <div className="mt-6"><h3>メール送信</h3>{delivery ? <><p className="muted text-sm">宛先：{delivery.recipient_name ? `${delivery.recipient_name} / ` : ''}{delivery.recipient_email}</p><p className="muted text-sm">状態：{delivery.status === 'queued' ? '送信待ち' : delivery.status === 'running' ? '送信中' : delivery.status === 'sent' ? '送信済み' : delivery.status === 'failed' ? '失敗' : 'キャンセル済み'}{delivery.sent_at ? `（${new Date(delivery.sent_at).toLocaleString('ja-JP')}）` : ''}</p>{delivery.error_message && <p className="error">{delivery.error_message}</p>}{delivery.status === 'queued' && <div className="actions"><button className="danger" disabled={busy} onClick={onCancel}>送信予約をキャンセル</button></div>}{delivery.status === 'failed' && <><label className="field">再送日時（空欄ならすぐ送信）<input type="datetime-local" value={scheduledAt} onChange={e => onScheduledAtChange(e.target.value)} /></label><label className="checkbox-row"><input type="checkbox" checked={confirmed} onChange={e => onConfirmedChange(e.target.checked)} />宛先・件名・本文を確認し、このメールの再送を承認します。</label><div className="actions"><button disabled={busy || !confirmed} onClick={onRetry}>再送を予約</button></div></>}</> : <><div className="detail-grid"><label className="field">送信先<select value={recipient} onChange={e => onRecipientChange(e.target.value)}><option value="">選択してください</option>{company.email && <option value={company.email}>{company.company_name}（代表）: {company.email}</option>}{contacts.filter(contact => contact.email && contact.verification_status !== 'invalid').map(contact => <option value={contact.email} key={contact.id}>{contact.name}: {contact.email}</option>)}</select></label><label className="field">送信日時（空欄ならすぐ送信）<input type="datetime-local" value={scheduledAt} onChange={e => onScheduledAtChange(e.target.value)} /></label></div><label className="checkbox-row"><input type="checkbox" checked={confirmed} onChange={e => onConfirmedChange(e.target.checked)} />宛先・件名・本文を確認し、このメールの送信を承認します。</label><div className="actions"><button disabled={busy || !recipient || !confirmed || company.do_not_contact} onClick={onSchedule}>送信を承認</button></div></>}</div>
}
