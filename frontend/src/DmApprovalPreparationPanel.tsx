import { useCallback, useState } from 'react'
import { api, errorMessage } from './api'
import { ApprovalQueuePage } from './ApprovalQueuePage'

type Preview = { status: string; reason: string | null; preparation_hash: string | null; dm_ready: boolean; proposal: { recipient: string | null; form_url: string | null; form_action_url: string | null; subject: string; body: string; sender: Record<string, string>; field_values: Record<string, string> } | null; approval_request: { id: string; status: string; expires_at: string; valid: boolean } | null }

export function DmApprovalPreparationPanel({ preparationId, projectId, canPrepare, onEdit }: { preparationId: string; projectId: string; canPrepare: boolean; onEdit?: () => void }) {
  const [preview, setPreview] = useState<Preview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [reviewOpen, setReviewOpen] = useState(false)
  const load = useCallback(async () => { const result = await api<Preview>(`/dm-preparations/${preparationId}/approval-preview`); setPreview(result); return result }, [preparationId])
  async function act(prepare: boolean) {
    setBusy(true); setError('')
    try {
      if (prepare && preview?.preparation_hash) await api(`/dm-preparations/${preparationId}/approval-request`, 'POST', { expected_preparation_hash: preview.preparation_hash })
      await load()
    } catch (e) { setError(errorMessage(e)); setPreview(null) } finally { setBusy(false) }
  }
  return <section aria-label="DM承認準備" className="mt-4">
    <button className="secondary" disabled={busy} onClick={() => void act(false)}>入力内容を確認</button>
    {error && <p role="alert">{error}</p>}
    {preview && <>
      <p role="status">{preview.dm_ready ? 'DM READY（承認・送信は別操作）' : preview.status === 'HOLD' ? '準備保留' : '入力確認済み・提案作成前'}{preview.reason && `：${preview.reason}`}</p>
      {preview.proposal && !reviewOpen && <>
        <p>宛先：{preview.proposal.recipient || preview.proposal.form_url}</p>
        {preview.proposal.form_action_url && <p>フォーム受付先：{preview.proposal.form_action_url}</p>}
        <p>送信者：{Object.values(preview.proposal.sender).filter(Boolean).join(' / ')}</p>
        <pre className="whitespace-pre-wrap">{preview.proposal.subject}{'\n'}{preview.proposal.body}</pre>
        <dl>{Object.entries(preview.proposal.field_values).map(([key, value]) => <div key={key}><dt>{key}</dt><dd className="whitespace-pre-wrap">{value}</dd></div>)}</dl>
        {!preview.dm_ready && canPrepare && <button disabled={busy} onClick={() => void act(true)}>承認待ち提案を準備</button>}
      </>}
      {preview.approval_request && <p>提案状態：{preview.approval_request.status} / 期限：{new Date(preview.approval_request.expires_at).toLocaleString('ja-JP')} / {preview.approval_request.valid ? '有効' : '再準備が必要'}</p>}
      {preview.approval_request && <>
        <div className="actions">
          <button className="secondary" disabled={busy} onClick={() => setReviewOpen(value => !value)}>{reviewOpen ? '確認画面を閉じる' : 'この画面で内容を確認・承認'}</button>
          {canPrepare && onEdit && <button className="secondary" disabled={busy} onClick={() => { setReviewOpen(false); onEdit() }}>下書きを修正する</button>}
        </div>
        {reviewOpen && <section aria-label="DMの確認と承認" className="mt-4">
          <ApprovalQueuePage key={preview.approval_request.id} projects={[]} projectRoles={{}} inlineRequest={{ id: preview.approval_request.id, projectId, canWrite: canPrepare, onChanged: load, onBusyChange: setBusy }} />
          <button className="secondary" disabled={busy} onClick={() => { setReviewOpen(false); void act(false) }}>保留・確認を終了</button>
          <p className="muted text-sm">保留しても承認・取消は行いません。承認待ちの提案は承認待ちのまま残ります。</p>
        </section>}
      </>}
      <p className="muted">提案作成は送信の承認ではありません。Human承認画面で根拠・宛先・固定された入力内容を確認し、再認証して承認してください。この操作では送信しません。</p>
    </>}
  </section>
}
