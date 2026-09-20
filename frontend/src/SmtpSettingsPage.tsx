import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import type { SmtpSettings } from './types'

const empty = {
  host: '', port: 587, username: '', from_email: '', from_name: 'LeadHive',
  use_starttls: true, timeout_seconds: 20,
}

export function SmtpSettingsPage({ defaultRecipient }: { defaultRecipient: string }) {
  const [form, setForm] = useState(empty)
  const [password, setPassword] = useState('')
  const [configured, setConfigured] = useState(false)
  const [recipient, setRecipient] = useState(defaultRecipient)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  useEffect(() => {
    api<SmtpSettings | null>('/admin/smtp-settings').then(value => {
      if (!value) return
      setForm({
        host: value.host, port: value.port, username: value.username,
        from_email: value.from_email, from_name: value.from_name,
        use_starttls: value.use_starttls, timeout_seconds: value.timeout_seconds,
      })
      setConfigured(value.password_configured)
    }).catch(e => setError(errorMessage(e)))
  }, [])
  async function save() {
    setBusy(true); setError(''); setNotice('')
    try {
      const saved = await api<SmtpSettings>('/admin/smtp-settings', 'PUT', {
        ...form, password: password || null,
      })
      setConfigured(saved.password_configured); setPassword('')
      setNotice('SMTP設定を保存しました。パスワードは再表示されません。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function sendTest() {
    if (!recipient || !window.confirm(`「${recipient}」へテストメールを送信しますか？`)) return
    setBusy(true); setError(''); setNotice('')
    try {
      await api('/admin/smtp-settings/test', 'POST', { recipient_email: recipient })
      setNotice('テストメールを送信しました。受信箱をご確認ください。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  return <section className="panel max-w-3xl" aria-label="SMTP設定"><p className="eyebrow">ADMIN SETTINGS</p><h2>メール送信設定</h2>
    <p className="muted mt-2">承認済みメールとテストメールに使うSMTPサーバーを設定します。パスワードは暗号化して保存され、画面には再表示されません。</p>
    {error && <p className="error mt-4" role="alert">{error}</p>}{notice && <p className="notice mt-4" role="status">{notice}</p>}
    <div className="detail-grid mt-5"><label className="field">SMTPホスト<input required value={form.host} onChange={e => setForm({ ...form, host: e.target.value })} placeholder="smtp.example.com" /></label><label className="field">ポート<input type="number" min={1} max={65535} value={form.port} onChange={e => setForm({ ...form, port: Number(e.target.value) })} /></label><label className="field">ユーザー名<input value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} autoComplete="username" /></label><label className="field">パスワード{configured && <span className="muted text-xs">（設定済み。変更時だけ入力）</span>}<input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="new-password" /></label><label className="field">送信元メールアドレス<input type="email" required value={form.from_email} onChange={e => setForm({ ...form, from_email: e.target.value })} /></label><label className="field">送信者名<input maxLength={200} value={form.from_name} onChange={e => setForm({ ...form, from_name: e.target.value })} /></label><label className="field">接続タイムアウト（秒）<input type="number" min={1} max={120} value={form.timeout_seconds} onChange={e => setForm({ ...form, timeout_seconds: Number(e.target.value) })} /></label><label className="checkbox-row mt-7"><input type="checkbox" checked={form.use_starttls} onChange={e => setForm({ ...form, use_starttls: e.target.checked })} />STARTTLSを使用する</label></div>
    <div className="actions"><button disabled={busy || !form.host || !form.from_email} onClick={() => void save()}>SMTP設定を保存</button></div>
    <div className="mt-7 border-t pt-5"><h3>テスト送信</h3><p className="muted text-sm mt-2">保存済みの設定でテストメールを1通だけ送信します。</p><label className="field mt-3">テスト送信先<input type="email" value={recipient} onChange={e => setRecipient(e.target.value)} /></label><div className="actions"><button className="secondary" disabled={busy || !configured || !recipient} onClick={() => void sendTest()}>テストメールを送信</button></div></div>
  </section>
}
