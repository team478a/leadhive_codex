import { useState } from 'react'
import { api } from './api'

type Result = { checked_at: string; structure_status: string; sales_prohibition_detected: boolean; captcha_state: string; message: string }
const names: Record<string, string> = { SAME_STRUCTURE: '保存済み構造と一致', CHANGED: '構造または送信先に変更あり', REDIRECTED: 'ページ移動あり・再確認が必要', FORM_NOT_FOUND: '保存済みフォームが見つかりません', FETCH_FAILED: 'ページを確認できませんでした' }

export function CompanyFormLiveCheck({ profileId, readOnly, onRefresh }: { profileId: string; readOnly: boolean; onRefresh: () => Promise<void> }) {
  const [result, setResult] = useState<Result | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function check() {
    setBusy(true); setError(''); setResult(null)
    try {
      setResult(await api<Result>(`/form-profiles/${profileId}/live-check`, 'POST'))
      await onRefresh()
    } catch (err) { setError(err instanceof Error ? err.message : '現在のフォームを確認できませんでした。') }
    finally { setBusy(false) }
  }
  return <section className="mt-4" aria-label="現在のフォーム確認">
    <p className="muted text-sm">現在のページだけを取得して、保存済み構造・営業禁止・CAPTCHAを確認します。入力・送信は行いません。</p>
    {!readOnly && <button className="secondary mt-3" disabled={busy} onClick={check}>{busy ? '現在のページを確認中…' : '現在のフォームを確認'}</button>}
    {error && <p className="error mt-3" role="alert">{error}</p>}
    {result && <div className="notice mt-3" role="status">
      <strong>{names[result.structure_status] ?? '未確認'}</strong>
      <p>営業禁止表記：{result.sales_prohibition_detected ? '検出・送信対象外' : '未検出（営業許可ではありません）'}</p>
      <p>CAPTCHA：{result.captcha_state === 'DETECTED' ? '検出・人の操作が必要' : result.captcha_state === 'NOT_DETECTED_STATIC' ? '静的HTMLでは未検出・画面確認が必要' : '未確認'}</p>
      <p>{result.message}</p><p className="text-xs">確認日時：{new Date(result.checked_at).toLocaleString('ja-JP')}</p>
    </div>}
  </section>
}
