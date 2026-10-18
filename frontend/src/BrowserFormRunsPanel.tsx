import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from './api'

type BrowserRun = {
  id: string
  mode: 'dry_run' | 'submit'
  status: string
  form_url: string
  reason: string
  created_at: string
  finished_at: string | null
  screenshot_before_url: string | null
  screenshot_after_url: string | null
}

const statusLabels: Record<string, string> = {
  queued: '待機中', checking: 'ブラウザー実行中', submitted: '送信完了を確認',
  failed: '失敗', unknown: '結果不明・再送禁止', blocked: '安全条件で停止',
  cancelled: '取消済み', dry_run_completed: 'dry-run完了（送信なし）',
}

export function BrowserFormRunsPanel({
  companyId, profileId, canWrite, doNotContact,
}: {
  companyId: string; profileId: string | null; canWrite: boolean; doNotContact: boolean
}) {
  const [runs, setRuns] = useState<BrowserRun[]>([])
  const [dryRunEnabled, setDryRunEnabled] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const refresh = useCallback(async () => {
    const [nextRuns, limits] = await Promise.all([
      api<BrowserRun[]>(`/companies/${companyId}/browser-form-runs?limit=20`),
      api<{ browser_form_dry_run_enabled: boolean }>('/form-dispatch-limits'),
    ])
    setRuns(nextRuns)
    setDryRunEnabled(limits.browser_form_dry_run_enabled)
  }, [companyId])

  useEffect(() => {
    let live = true
    void refresh().catch(reason => { if (live) setError(errorMessage(reason)) })
    return () => { live = false }
  }, [refresh])

  useEffect(() => {
    if (!runs.some(run => ['queued', 'checking'].includes(run.status))) return
    const timer = window.setInterval(() => { void refresh().catch(reason => setError(errorMessage(reason))) }, 4000)
    return () => window.clearInterval(timer)
  }, [refresh, runs])

  async function startDryRun() {
    if (!profileId) return
    setBusy(true); setError(''); setNotice('')
    try {
      await api<{ id: string; status: string }>(
        `/form-profiles/${profileId}/browser-form-dry-run`, 'POST',
      )
      setNotice('dry-runを予約しました。フォームへ入力して読み戻しますが、送信はしません。')
      await refresh()
    } catch (reason) { setError(errorMessage(reason)) }
    finally { setBusy(false) }
  }

  async function cancel(runId: string) {
    setBusy(true); setError('')
    try {
      await api(`/browser-form-runs/${runId}/cancel`, 'POST')
      await refresh()
    } catch (reason) { setError(errorMessage(reason)) }
    finally { setBusy(false) }
  }

  return <section className="panel mt-5" aria-label="ブラウザーフォーム実行結果">
    <h3>ブラウザーフォーム dry-run・結果</h3>
    <p className="muted text-sm">dry-runは確認済みフォームに入力して読み戻し、画面を保存します。送信ボタンは押しません。実送信は承認済み予約だけが対象です。</p>
    {!dryRunEnabled && <p className="muted text-sm">ブラウザーdry-run機能はOFFです。有効になるまで実行できません。</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {canWrite && <button type="button" disabled={busy || !dryRunEnabled || !profileId || doNotContact} onClick={() => void startDryRun()}>
      {busy ? '予約中…' : '確認済みフォームでdry-run（送信なし）'}
    </button>}
    {!runs.length ? <p className="muted mt-3">ブラウザーフォーム実行結果はありません。</p> : runs.map(run => <article className="job-row mt-3" key={run.id}>
      <div>
        <strong>{run.mode === 'dry_run' ? 'dry-run' : '承認済み送信'} / {statusLabels[run.status] ?? run.status}</strong>
        <p className="muted text-xs break-all">{run.form_url}</p>
        {run.reason && <p className={run.status === 'unknown' ? 'error' : 'muted text-sm'}>{run.reason}</p>}
        {run.finished_at && <time className="muted text-xs">{new Date(run.finished_at).toLocaleString('ja-JP')}</time>}
        {(run.screenshot_before_url || run.screenshot_after_url) && <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
          {run.screenshot_before_url && <figure><figcaption className="muted text-xs">送信前</figcaption><img className="max-h-80 rounded border" src={`/api${run.screenshot_before_url}`} alt="フォーム実行前の画面" /></figure>}
          {run.screenshot_after_url && <figure><figcaption className="muted text-xs">送信後</figcaption><img className="max-h-80 rounded border" src={`/api${run.screenshot_after_url}`} alt="フォーム実行後の画面" /></figure>}
        </div>}
      </div>
      {canWrite && run.mode === 'dry_run' && ['queued', 'checking'].includes(run.status) && <button className="secondary" disabled={busy} onClick={() => void cancel(run.id)}>取消</button>}
    </article>)}
    <button className="secondary mt-3" disabled={busy} onClick={() => void refresh().catch(reason => setError(errorMessage(reason)))}>結果を更新</button>
  </section>
}
