import { useEffect, useState } from 'react'
import { api } from './api'

type Result = { checked_at: string | null; structure_status: string; sales_prohibition_detected: boolean; captcha_state: string; message: string; freshness: string; expires_at: string | null; fingerprint_match?: boolean | null; action_match?: boolean | null; method_is_post?: boolean | null }
const names: Record<string, string> = { SAME_STRUCTURE: '保存済み構造と一致', CHANGED: '構造または送信先に変更あり', UNSUPPORTED_METHOD: '通常のPOST送信経路に未対応', SAVED_BASELINE_INCOMPLETE: '保存済みの比較情報が不足・再解析が必要', REDIRECTED: 'ページ移動あり・再確認が必要', FORM_NOT_FOUND: '保存済みフォームが見つかりません', FETCH_FAILED: 'ページを確認できませんでした' }

export function CompanyFormLiveCheck({ profileId, fingerprint, readOnly, onRefresh }: { profileId: string; fingerprint: string; readOnly: boolean; onRefresh: () => Promise<void> }) {
  const [result, setResult] = useState<Result | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    api<Result | null>(`/form-profiles/${profileId}/live-check`)
      .then(data => { if (active) { setResult(data); setError(''); setLoading(false) } })
      .catch(err => { if (active) { setError(err instanceof Error ? err.message : '保存済み確認結果を取得できませんでした。'); setLoading(false) } })
    return () => { active = false }
  }, [profileId, fingerprint])
  async function check() {
    setBusy(true); setError('')
    try {
      setResult(await api<Result>(`/form-profiles/${profileId}/live-check`, 'POST'))
      await onRefresh()
    } catch (err) { setError(err instanceof Error ? err.message : '現在のフォームを確認できませんでした。') }
    finally { setBusy(false) }
  }
  async function refreshTarget() {
    setBusy(true); setError('')
    try {
      const refreshed = await api<{ refresh_applied: boolean; message?: string }>(`/form-profiles/${profileId}/refresh-target`, 'POST')
      await onRefresh()
      setResult(await api<Result | null>(`/form-profiles/${profileId}/live-check`))
      if (!refreshed.refresh_applied) setError(refreshed.message || '手動確認済み情報を保護して停止しました。')
    } catch (err) {
      setError(err instanceof Error ? err.message : '再解析できませんでした。')
      try { await onRefresh(); setResult(await api<Result | null>(`/form-profiles/${profileId}/live-check`)) } catch { /* Keep the original failure visible. */ }
    }
    finally { setBusy(false) }
  }
  return <section className="mt-4" aria-label="現在のフォーム確認">
    <p className="muted text-sm">現在のページだけを取得して、保存済み構造・営業禁止・CAPTCHAを確認します。入力・送信は行いません。</p>
    {!readOnly && <button className="secondary mt-3" disabled={busy || loading} onClick={check}>{busy ? '現在のページを確認中…' : '現在のフォームを確認'}</button>}
    {error && <p className="error mt-3" role="alert">{error}</p>}
    {!result && !error && <p className="muted mt-3">{loading ? '保存済み結果を読み込み中…' : '現在のページの確認結果は未保存です。'}</p>}
    {result && <div className="notice mt-3" role="status">
      <p>{result.freshness === 'CURRENT' ? '保存済みの確認結果（24時間以内の観測）' : result.freshness === 'EXPIRED' ? '確認から24時間が経過しました。再確認が必要です。' : result.freshness === 'SOURCE_CHANGED' ? '保存されたフォーム情報が変わりました。この確認結果は以前の情報です。' : '確認結果の有効性を確認できません。再確認が必要です。'}</p>
      <strong>{names[result.structure_status] ?? '未確認'}</strong>
      {!readOnly && ['SAVED_BASELINE_INCOMPLETE', 'CHANGED'].includes(result.structure_status) && <div className="mt-3"><p>このページだけを再解析します。手動確認済み情報と異なる場合は上書きせず停止します。</p><button className="secondary mt-2" disabled={busy} onClick={refreshTarget}>このフォームだけ再解析</button></div>}
      {result.fingerprint_match !== undefined && <p>入力項目：{result.fingerprint_match === null ? '比較元が未保存' : result.fingerprint_match ? '保存済みと一致' : '変更あり'}</p>}
      {result.action_match !== undefined && <p>送信先：{result.action_match === null ? '比較元が未保存' : result.action_match ? '保存済みと一致' : '変更あり'}</p>}
      <p>営業禁止表記：{result.sales_prohibition_detected ? '検出・送信対象外' : '未検出（営業許可ではありません）'}</p>
      <p>CAPTCHA：{result.captcha_state === 'DETECTED' ? '検出・人の操作が必要' : result.captcha_state === 'NOT_DETECTED_STATIC' ? '静的HTMLでは未検出・画面確認が必要' : '未確認'}</p>
      <p>{result.message}</p><p className="text-xs">確認日時：{result.checked_at ? new Date(result.checked_at).toLocaleString('ja-JP') : '未記録'}</p>
      <p className="text-xs">再確認の目安：{result.expires_at ? new Date(result.expires_at).toLocaleString('ja-JP') : '未記録'}</p>
    </div>}
  </section>
}
