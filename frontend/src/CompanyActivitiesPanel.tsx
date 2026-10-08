import type { Activity } from './types'

type Props = {
  activities: Activity[]
  activityType: string
  activityNote: string
  busy: boolean
  onActivityTypeChange: (value: string) => void
  onActivityNoteChange: (value: string) => void
  onAdd: () => void
}

export function CompanyActivitiesPanel({ activities, activityType, activityNote, busy, onActivityTypeChange, onActivityNoteChange, onAdd }: Props) {
  return <section className="panel mt-7"><h2>活動履歴</h2><div className="detail-grid"><label className="field">活動種別<select value={activityType} onChange={e => onActivityTypeChange(e.target.value)}><option value="note">メモ</option><option value="call">電話</option><option value="email">メール</option><option value="form">フォーム</option><option value="sns">SNS</option><option value="meeting">商談</option></select></label><label className="field">活動内容<textarea rows={3} value={activityNote} onChange={e => onActivityNoteChange(e.target.value)} /></label></div><div className="actions"><button disabled={busy || !activityNote.trim()} onClick={onAdd}>履歴を追加</button></div>{activities.map(item => <article className="job-row" key={item.id}><div><strong>{item.activity_type}</strong><p>{item.note}</p></div><time className="muted text-sm">{new Date(item.created_at).toLocaleString('ja-JP')}</time></article>)}</section>
}
