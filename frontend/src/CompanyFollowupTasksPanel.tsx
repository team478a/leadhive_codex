import { useEffect, useRef } from 'react'
import type { FollowupTask } from './types'
import { dueNames, statusNames } from './companyPageShared'

type Action = 'completed' | 'rescheduled'

type Props = {
  items: FollowupTask[]
  target: FollowupTask | null
  action: Action
  note: string
  scheduledAt: string
  busy: boolean
  onStart: (task: FollowupTask) => void
  onActionChange: (value: Action) => void
  onNoteChange: (value: string) => void
  onScheduledAtChange: (value: string) => void
  onResolve: () => void
  onCancel: () => void
}

export function CompanyFollowupTasksPanel({ items, target, action, note, scheduledAt, busy, onStart, onActionChange, onNoteChange, onScheduledAtChange, onResolve, onCancel }: Props) {
  const targetPanelRef = useRef<HTMLDivElement>(null)
  useEffect(() => { if (target) targetPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }) }, [target])
  return <section className="panel mt-6"><div className="flex items-center justify-between gap-3"><div><h2>追客タスク</h2><p className="muted mt-2 text-sm">期限がある次回対応を完了または延期します。</p></div><span className="badge">{items.length} 件</span></div><div className="company-table-wrap mt-4"><table className="company-table"><thead><tr><th>企業</th><th>担当</th><th>期限</th><th>営業状況</th><th></th></tr></thead><tbody>{items.map(task => <tr key={task.company.id}><td><strong>{task.company.company_name}</strong><p className="muted text-xs">{task.company.rank ?? '—'} / {task.company.score ?? '—'}点</p></td><td>{task.company.assignee || '未設定'}</td><td><span className="badge">{dueNames[task.due_state]}</span><p className="muted text-xs">{task.company.next_followup_at ? new Date(task.company.next_followup_at).toLocaleString('ja-JP') : '—'}</p></td><td>{statusNames[task.company.status]}</td><td><button className="secondary" onClick={() => onStart(task)}>完了・延期</button></td></tr>)}{items.length === 0 && <tr><td colSpan={5} className="text-center muted">期限が設定された追客タスクはありません。</td></tr>}</tbody></table></div>{target && <div ref={targetPanelRef} className="mt-5"><h3>{target.company.company_name}の追客タスク</h3><div className="detail-grid"><div><label className="field">処理<select value={action} onChange={e => onActionChange(e.target.value as Action)}><option value="completed">完了</option><option value="rescheduled">延期</option></select></label>{action === 'rescheduled' && <label className="field">次回対応日時<input type="datetime-local" value={scheduledAt} onChange={e => onScheduledAtChange(e.target.value)} /></label>}</div><label className="field">対応メモ<textarea rows={4} maxLength={10000} value={note} onChange={e => onNoteChange(e.target.value)} placeholder="例：先方都合により来週へ延期" /></label></div><div className="actions"><button disabled={busy || !note.trim() || (action === 'rescheduled' && !scheduledAt)} onClick={onResolve}>{action === 'completed' ? 'タスクを完了' : 'タスクを延期'}</button><button className="secondary" onClick={onCancel}>キャンセル</button></div></div>}</section>
}
