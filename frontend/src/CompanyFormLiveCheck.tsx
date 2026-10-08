import { useEffect, useState } from 'react'
import { api } from './api'

type ContractShape = { reviewed_lab_version: boolean; hidden_complete: boolean; hidden_shape_valid: boolean; extra_hidden: number; invalid_names: number; repeated_names: number; radio_controls: number; select_controls: number; checkbox_controls: number; checked_checkboxes: number; disabled_controls: number }
type CF7Static = { contract_shape?: ContractShape | null; status: string; version?: string | null; form_count?: number; markers_complete?: boolean; form_id_valid?: boolean; rest_link_same_origin?: boolean; missing_names?: number; file_inputs?: number; unsupported_controls?: number; base_override?: boolean }
type Result = { checked_at: string | null; structure_status: string; sales_prohibition_detected: boolean; captcha_state: string; message: string; freshness: string; expires_at: string | null; fingerprint_match?: boolean | null; action_match?: boolean | null; method_is_post?: boolean | null; cf7_static?: CF7Static | null }
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
      {result.cf7_static && result.cf7_static.status !== 'NOT_CF7' && <div className="mt-3" aria-label="CF7の静的構造確認">
        <strong>CF7の静的構造確認</strong>
        <p>{result.freshness !== 'CURRENT' ? '以前の観察結果です。現在の構造とは限りません。' : '取得したHTMLだけの確認です。送信対応・営業許可・承認を意味しません。'}</p>
        {result.cf7_static.status === 'CF7_CANDIDATE' ? <>
          <p>保存マーカー：CF7候補 / バージョン：{result.cf7_static.version ?? '未確認'}</p>
          <p>基本マーカー：{result.cf7_static.markers_complete && result.cf7_static.form_id_valid ? '確認できた' : '不足・確認が必要'}</p>
          <p>同一サイトのRESTリンク：{result.cf7_static.rest_link_same_origin ? '見つかった（接続・受付は未検証）' : '未確認'}</p>
          <p>項目名不足：{result.cf7_static.missing_names ?? '未確認'}件 / ファイル欄：{result.cf7_static.file_inputs ?? '未確認'}件 / 限定対応外の項目：{result.cf7_static.unsupported_controls ?? '未確認'}件</p>
          <div aria-label="限定契約との差分">
            <p>限定契約との照合（送信可否の判定ではありません）</p>
            {result.cf7_static.contract_shape ? <>
              <p>HTML記載の版：{['6.1.4', '6.2'].includes(result.cf7_static.version ?? '') ? '隔離環境で検証した版と一致（実サイト受付・実行版は未検証）' : '管理下テストの対象外・追加検証が必要'}</p>
              {result.cf7_static.version === '6.2' && <p>6.2の契約は管理下fixture専用です。既存の実サイト候補準備（6.1.4限定）には使用できません。</p>}
              <p>hidden 6項目：{result.cf7_static.contract_shape.hidden_complete ? 'そろっている' : '不足あり'} / 6.1.4候補契約の形式と対応関係：{result.cf7_static.contract_shape.hidden_shape_valid ? '限定形式に一致' : '不一致・確認が必要'}</p>
              <p>契約外hidden：{result.cf7_static.contract_shape.extra_hidden}件 / 項目名の形式不一致：{result.cf7_static.contract_shape.invalid_names}件 / 項目名の重複：{result.cf7_static.contract_shape.repeated_names}件</p>
              <p>未対応のラジオ：{result.cf7_static.contract_shape.radio_controls}件 / 選択リスト：{result.cf7_static.contract_shape.select_controls}件 / 無効化された項目：{result.cf7_static.contract_shape.disabled_controls}件</p>
              <p>チェック欄：{result.cf7_static.contract_shape.checkbox_controls}件（初期選択済み：{result.cf7_static.contract_shape.checked_checkboxes}件）。同意内容と選択値は人による確認が必要です。</p>
            </> : <p>以前の診断には限定契約の照合結果がありません。未確認として扱います。</p>}
          </div>
          {result.cf7_static.base_override && <p>ページの基準URL指定があります。別途確認が必要です。</p>}
        </> : <p>{result.cf7_static.status === 'LIMIT_EXCEEDED' ? '解析サイズの上限を超えました。' : result.cf7_static.status === 'FORM_MISSING' ? '指定位置のフォームを確認できませんでした。' : '限定解析で構造を確認できませんでした。'}送信許可には使いません。</p>}
      </div>}
      <p>{result.message}</p><p className="text-xs">確認日時：{result.checked_at ? new Date(result.checked_at).toLocaleString('ja-JP') : '未記録'}</p>
      <p className="text-xs">再確認の目安：{result.expires_at ? new Date(result.expires_at).toLocaleString('ja-JP') : '未記録'}</p>
    </div>}
  </section>
}
