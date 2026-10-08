import { useState } from 'react'
import { api } from './api'

type Report = {
  snapshot_hash: string; can_record: boolean; review_status: string; reasons: string[]
  reviewed_at?: string; review_expires_at?: string
  snapshot: { form_url: string; plugin_version: string | null; rows: { position: number; name: string; label: string; required: boolean; values: string[]; state: string }[] }
}
const reasons: Record<string, string> = {
  CONTACT_BLOCKED: '連絡禁止・営業禁止のため記録できません。', CAPTCHA: 'CAPTCHAは人の操作が必要です。',
  CF7_UNVERIFIED: 'CF7の保存情報が未確認です。', OBSERVATION_UNVERIFIED: '現在のフォームを確認してください。',
  VERSION_UNVERIFIED: '未対応または未確認の版です。', HIDDEN_UNVERIFIED: 'hiddenの対応関係が未確認です。現在のフォームを再確認してください。',
  REST_ROOT_UNVERIFIED: 'REST送信先の確認が必要です。', UNSUPPORTED_STRUCTURE: '未対応の項目・同名項目・追加hiddenがあります。',
  DRAFT_MISSING: 'フォーム用の下書きがありません。', INPUT_REVIEW_REQUIRED: '未確定の入力・選択があります。', REQUIRED_VALUE_MISSING: '必須の入力値が不足しています。',
}

export function CompanyFormInputPreparation({ profileId, readOnly }: { profileId: string; readOnly: boolean }) {
  const [report, setReport] = useState<Report | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function load() {
    setBusy(true); setConfirmed(false); setError(''); setReport(null)
    try { setReport(await api<Report>(`/form-profiles/${profileId}/input-preparation`)) }
    catch (err) { setError(err instanceof Error ? err.message : '確認票を取得できませんでした。') }
    finally { setBusy(false) }
  }
  async function record() {
    if (!report?.can_record || !confirmed) return
    setBusy(true); setError('')
    try {
      setReport(await api<Report>(`/form-profiles/${profileId}/input-preparation/reviews`, 'POST', { expected_snapshot_hash: report.snapshot_hash, input_content_confirmed: true }))
      setConfirmed(false)
    } catch (err) {
      setConfirmed(false); setReport(null)
      setError(err instanceof Error ? err.message : '記録できませんでした。確認票を読み直してください。')
    } finally { setBusy(false) }
  }
  return <section aria-label="入力内容の確認票" className="notice mt-4">
    <h3>入力内容の確認票</h3>
    <p>保存済みの送信者・下書き・選択値をまとめます。ブラウザ入力・送信承認・送信は行いません。</p>
    <button type="button" className="secondary mt-2" disabled={busy} onClick={load}>{busy ? '確認中…' : '入力内容をまとめて確認'}</button>
    {error && <p role="alert" className="error mt-2">{error}</p>}
    {report && <div className="mt-3">
      <p className="break-all">対象ページ：{report.snapshot.form_url}</p>
      <p>版：{report.snapshot.plugin_version ?? '未確認'} / {({ NOT_RECORDED: '入力確認は未記録', RECORDED: '入力確認を記録済み（送信承認ではありません）', INVALIDATED: '内容が変更・未確認になりました。再確認が必要です。', EXPIRED: '確認記録が期限切れです。' } as Record<string, string>)[report.review_status] ?? '未確認'}</p>
      {report.reviewed_at && <p>確認日時：{new Date(report.reviewed_at).toLocaleString('ja-JP')} / 期限：{report.review_expires_at ? new Date(report.review_expires_at).toLocaleString('ja-JP') : '未確認'}</p>}
      {report.reasons.map(code => <p key={code}>{reasons[code] ?? '追加確認が必要です。'}</p>)}
      {report.snapshot.rows.map(row => <details key={`${row.position}:${row.name}`} className="mt-2">
        <summary>{row.label || row.name || '名称未確認'}{row.required ? '（必須）' : ''}：{row.values.length ? '値あり' : '空欄・未確定'}</summary>
        {row.values.map((value, index) => <p className="break-all whitespace-pre-wrap" key={index}>{value}</p>)}
      </details>)}
      <p className="text-xs break-all mt-2">確認票hash：{report.snapshot_hash}</p>
      {!readOnly && report.can_record && report.review_status !== 'RECORDED' && <>
        <label className="flex gap-2 mt-2"><input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} />宛先ページ・入力値・選択内容を確認しました（送信承認ではありません）</label>
        <button type="button" className="secondary mt-2" disabled={!confirmed || busy} onClick={record}>入力内容の確認を記録</button>
      </>}
    </div>}
  </section>
}
