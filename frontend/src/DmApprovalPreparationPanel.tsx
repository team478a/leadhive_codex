import { useState } from 'react'
import { api, errorMessage } from './api'

type Preview = { status: string; reason: string | null; preparation_hash: string | null; dm_ready: boolean; proposal: { recipient: string | null; form_url: string | null; form_action_url: string | null; subject: string; body: string; sender: Record<string, string>; field_values: Record<string, string> } | null; approval_request: { id: string; status: string; expires_at: string; valid: boolean } | null }

export function DmApprovalPreparationPanel({ preparationId, canPrepare }: { preparationId: string; canPrepare: boolean }) {
  const [preview, setPreview] = useState<Preview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function load() { const result = await api<Preview>(`/dm-preparations/${preparationId}/approval-preview`); setPreview(result); return result }
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
      {preview.proposal && <>
        <p>宛先：{preview.proposal.recipient || preview.proposal.form_url}</p>
        {preview.proposal.form_action_url && <p>フォーム受付先：{preview.proposal.form_action_url}</p>}
        <p>送信者：{Object.values(preview.proposal.sender).filter(Boolean).join(' / ')}</p>
        <pre className="whitespace-pre-wrap">{preview.proposal.subject}{'\n'}{preview.proposal.body}</pre>
        <dl>{Object.entries(preview.proposal.field_values).map(([key, value]) => <div key={key}><dt>{key}</dt><dd className="whitespace-pre-wrap">{value}</dd></div>)}</dl>
        {!preview.dm_ready && canPrepare && <button disabled={busy} onClick={() => void act(true)}>承認待ち提案を準備</button>}
      </>}
      {preview.approval_request && <p>提案状態：{preview.approval_request.status} / 期限：{new Date(preview.approval_request.expires_at).toLocaleString('ja-JP')} / {preview.approval_request.valid ? '有効' : '再準備が必要'}</p>}
      <p className="muted">提案作成は送信の承認ではありません。Human承認画面で根拠・宛先・固定された入力内容を確認し、再認証して承認してください。この操作では送信しません。</p>
    </>}
  </section>
}
