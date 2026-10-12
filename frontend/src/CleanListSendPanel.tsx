import { useEffect, useRef, useState } from 'react'
import { api, errorMessage } from './api'
import type { ApprovalProposal } from './ApprovedEmailPanel'

interface Preview {
  items: ApprovalProposal[]; skipped: Record<string, number>
  email_enabled: boolean; form_enabled: boolean
}
interface Chunk { channel: 'email' | 'form'; items: ApprovalProposal[]; key: string; done: boolean }

export function CleanListSendPanel({ projectId, canWrite, onBusyChange }: {
  projectId: string; canWrite: boolean; onBusyChange: (busy: boolean) => void
}) {
  const [preview, setPreview] = useState<Preview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [retry, setRetry] = useState(false)
  const plan = useRef<Chunk[] | null>(null)
  const locked = useRef(false)
  useEffect(() => {
    let live = true
    api<Preview>(`/projects/${projectId}/bulk-send-preview`).then(value => {
      if (live) setPreview(value)
    }).catch(e => { if (live) setError(errorMessage(e)) })
    return () => { live = false }
  }, [projectId])
  async function reload() {
    setError(''); setPreview(null)
    try { setPreview(await api<Preview>(`/projects/${projectId}/bulk-send-preview`)) }
    catch (e) { setError(errorMessage(e)) }
  }
  const emails = preview?.items?.filter(i => i.channel === 'email').length ?? 0
  const forms = preview?.items?.filter(i => i.channel === 'form').length ?? 0
  const enabled = !!preview && (!emails || preview.email_enabled) && (!forms || preview.form_enabled)
  async function start() {
    if (locked.current || !preview || !canWrite || !enabled) return
    locked.current = true; setBusy(true); onBusyChange(true); setError(''); setNotice('')
    if (!plan.current) {
      plan.current = []
      for (const channel of ['email', 'form'] as const) {
        const items = preview.items.filter(i => i.channel === channel)
        const size = channel === 'email' ? 10000 : 100
        for (let offset = 0; offset < items.length; offset += size) {
          plan.current.push({ channel, items: items.slice(offset, offset + size), key: crypto.randomUUID(), done: false })
        }
      }
    }
    let count = plan.current.filter(c => c.done).reduce((n, c) => n + c.items.length, 0)
    try {
      for (const chunk of plan.current) {
        if (chunk.done) continue
        const items = chunk.items.map(i => ({ request_id: i.id, expected_hash: i.payload_hash, expected_version: i.payload_version }))
        if (chunk.channel === 'email') {
          await api(`/projects/${projectId}/approved-email-batches`, 'POST', {
            items, name: 'クリーニング済みリストの一括送信', daily_limit: 500, hourly_limit: 60, idempotency_key: chunk.key,
          })
        } else {
          const response = await api<{ results: { error: string | null; reservation: unknown }[] }>(
            `/projects/${projectId}/approved-form-dispatches`, 'POST', { items, idempotency_key: chunk.key })
          const failed = response.results.filter(r => r.error || !r.reservation)
          if (response.results.length !== items.length || failed.length) {
            setNotice(`完了した予約群：${count}件。このフォーム群は${response.results.filter(r => r.reservation).length}件予約済みです。`)
            setError(failed.map(r => r.error || '予約結果を確認できません。').join(' / ') || '予約結果を確認できません。')
            setRetry(true); return
          }
        }
        chunk.done = true; count += chunk.items.length
        setNotice(`${count}件を送信予約しました。残りを登録中…`)
      }
      setNotice(`${count}件の送信予約が完了しました。ワーカーが送信上限に従って順次処理します。送信結果は承認キュー・メール配信状況で確認してください。`)
      setRetry(false); plan.current = null
      await reload()
    } catch (e) {
      setError(errorMessage(e)); setRetry(true)
      setNotice(`${count}件の予約を確認しました。未完了の予約は同じ予約キーで再試行します。接続エラーでも予約済みの場合があります。`)
    } finally { locked.current = false; setBusy(false); onBusyChange(false) }
  }
  return <section className="panel mb-5 space-y-3" aria-label="クリーニング済みリストの一括送信">
    <h2>クリーニング済みリストから送信</h2>
    <p>営業NG・まとめサイトを除外し、人が宛先・文面を承認した企業だけを一括送信します。未承認は承認キューで確認してください。</p>
    {preview && <p>送信対象：メール {emails}件 / フォーム {forms}件（リスト全体）</p>}
    {preview && Object.entries(preview.skipped ?? {}).map(([reason, n]) => <p className="muted text-sm" key={reason}>{reason}：{n}件</p>)}
    <p className="muted text-sm">メールは24時間500件・1時間60件以内で、SMTPの上限も適用します。フォームは運用設定の共通上限に従います。確認画面・CAPTCHAなどの特殊フォームは対象外です。</p>
    {preview && !enabled && <p role="alert">連絡方法の送信が停止中です。管理者へ設定の確認を依頼してください。</p>}
    {error && <p role="alert" className="error">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {!preview && !error && !notice && <p aria-live="polite">送信対象を確認中…</p>}
    <div className="actions flex-wrap">
      <button disabled={!canWrite || busy || !preview || !enabled || !(emails + forms)} onClick={() => void start()}>
        {busy ? '送信予約を登録中…' : retry ? '未完了の予約を再試行' : `承認済み${emails + forms}件を一括送信開始`}
      </button>
      <button className="secondary" disabled={busy || retry} onClick={() => void reload()}>送信対象を更新</button>
    </div>
    {preview && !emails && !forms && <p>送信できる承認済み文面はありません。「営業準備」で文面を作成し、「承認キュー」で宛先・文面を承認してください。</p>}
    {!!preview?.items?.length && <details><summary>送信対象の宛先・文面を見る</summary>
      {preview.items.map(i => <article key={i.id} className="mt-3 break-words"><h3>{i.company_name}</h3><p>{i.channel === 'email' ? i.recipient : i.form_url}</p><p>{i.subject}</p><p className="whitespace-pre-wrap">{i.body}</p></article>)}
    </details>}
  </section>
}
