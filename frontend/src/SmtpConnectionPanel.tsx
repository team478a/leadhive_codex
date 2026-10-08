import { useState } from 'react'
import { api, errorMessage } from './api'

type Result = { ok: boolean; stage: string; message: string; tls_verified: boolean; authenticated: boolean; checked_at: string }

export function SmtpConnectionPanel({ settingsVersion }: { settingsVersion: string }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<{ value: Result; version: string } | null>(null)
  async function check() {
    setBusy(true); setError(''); setResult(null)
    try {
      const value = await api<Result>('/admin/smtp-settings/connection-test', 'POST')
      setResult({ value, version: settingsVersion })
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  const current = result?.version === settingsVersion ? result.value : null
  return <section className="mt-7 border-t pt-5" aria-label="SMTP接続確認">
    <h3>メールを送らず接続確認</h3>
    <p className="muted text-sm mt-2">保存済みの設定でサーバー接続・暗号化・認証を確認します。変更した設定は先に保存してください。到達確認や配信通知の接続確認は含みません。</p>
    <div className="actions"><button className="secondary" disabled={busy} onClick={() => void check()}>{busy ? '接続確認中…' : 'メールを送らず接続確認'}</button></div>
    {error && <p className="error" role="alert">{error}</p>}
    {current && <div role={current.ok ? 'status' : 'alert'} className={current.ok ? 'notice' : 'error'}>
      <p>{current.message}</p>
      <p className="text-sm">暗号化：{current.tls_verified ? '確認済み' : '未確認'} / 認証：{current.authenticated ? '確認済み' : '未確認'}</p>
      <p className="text-sm">確認日時：{new Date(current.checked_at).toLocaleString('ja-JP')}</p>
    </div>}
  </section>
}
