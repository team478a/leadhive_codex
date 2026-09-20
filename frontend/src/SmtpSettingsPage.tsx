import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import type { InboundEmail, InboundEmailCompanyCandidate, InboundMailSettings, SmtpSettings } from './types'

const empty = {
  host: '', port: 587, username: '', from_email: '', from_name: 'LeadHive',
  use_starttls: true, timeout_seconds: 20,
  max_emails_per_day: 100, minimum_interval_seconds: 60,
}
const inboundEmpty = {
  host: '', port: 993, username: '', mailbox: 'INBOX', use_ssl: true,
  timeout_seconds: 20, poll_interval_seconds: 300, active: false,
}

export function SmtpSettingsPage({ defaultRecipient }: { defaultRecipient: string }) {
  const [form, setForm] = useState(empty)
  const [password, setPassword] = useState('')
  const [configured, setConfigured] = useState(false)
  const [recipient, setRecipient] = useState(defaultRecipient)
  const [inboundForm, setInboundForm] = useState(inboundEmpty)
  const [inboundPassword, setInboundPassword] = useState('')
  const [inboundConfigured, setInboundConfigured] = useState(false)
  const [inboundEmails, setInboundEmails] = useState<InboundEmail[]>([])
  const [matchQueries, setMatchQueries] = useState<Record<string, string>>({})
  const [matchCandidates, setMatchCandidates] = useState<Record<string, InboundEmailCompanyCandidate[]>>({})
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
        max_emails_per_day: value.max_emails_per_day,
        minimum_interval_seconds: value.minimum_interval_seconds,
      })
      setConfigured(value.password_configured)
    }).catch(e => setError(errorMessage(e)))
    api<InboundMailSettings | null>('/admin/inbound-mail-settings').then(value => {
      if (!value) return
      setInboundForm({
        host: value.host, port: value.port, username: value.username, mailbox: value.mailbox,
        use_ssl: value.use_ssl, timeout_seconds: value.timeout_seconds,
        poll_interval_seconds: value.poll_interval_seconds, active: value.active,
      })
      setInboundConfigured(value.password_configured)
    }).catch(e => setError(errorMessage(e)))
    api<InboundEmail[]>('/admin/inbound-emails?limit=20').then(setInboundEmails).catch(e => setError(errorMessage(e)))
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
  async function saveInbound() {
    setBusy(true); setError(''); setNotice('')
    try {
      const saved = await api<InboundMailSettings>('/admin/inbound-mail-settings', 'PUT', {
        ...inboundForm, password: inboundPassword || null,
      })
      setInboundConfigured(saved.password_configured); setInboundPassword('')
      setNotice('受信メール設定を保存しました。パスワードは再表示されません。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function testInbound() {
    setBusy(true); setError(''); setNotice('')
    try {
      await api('/admin/inbound-mail-settings/test', 'POST')
      setNotice('受信メールサーバーへ接続できました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function syncInbound() {
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await api<{ processed: number }>('/admin/inbound-mail-settings/sync', 'POST')
      setInboundEmails(await api<InboundEmail[]>('/admin/inbound-emails?limit=20'))
      setNotice(`受信メールを${result.processed}件取り込みました。`)
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function findMatchCandidates(inboundEmail: InboundEmail) {
    const query = (matchQueries[inboundEmail.id] || inboundEmail.sender_email).trim()
    if (!query) return
    setBusy(true); setError(''); setNotice('')
    try {
      const candidates = await api<InboundEmailCompanyCandidate[]>(`/admin/inbound-email-companies?query=${encodeURIComponent(query)}`)
      setMatchCandidates({ ...matchCandidates, [inboundEmail.id]: candidates })
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  async function matchInbound(inboundEmail: InboundEmail, company: InboundEmailCompanyCandidate) {
    if (!window.confirm(`「${inboundEmail.subject || inboundEmail.sender_email}」を${company.company_name}へ紐付けますか？`)) return
    setBusy(true); setError(''); setNotice('')
    try {
      const matched = await api<InboundEmail>(`/admin/inbound-emails/${inboundEmail.id}/match`, 'POST', { company_id: company.id })
      setInboundEmails(inboundEmails.map(item => item.id === matched.id ? matched : item))
      setMatchCandidates({ ...matchCandidates, [inboundEmail.id]: [] })
      setNotice(`${company.company_name}へ返信メールを紐付けました。`)
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  return <section className="panel max-w-3xl" aria-label="SMTP設定"><p className="eyebrow">ADMIN SETTINGS</p><h2>メール送信設定</h2>
    <p className="muted mt-2">承認済みメールとテストメールに使うSMTPサーバーを設定します。パスワードは暗号化して保存され、画面には再表示されません。</p>
    {error && <p className="error mt-4" role="alert">{error}</p>}{notice && <p className="notice mt-4" role="status">{notice}</p>}
    <div className="detail-grid mt-5"><label className="field">SMTPホスト<input required value={form.host} onChange={e => setForm({ ...form, host: e.target.value })} placeholder="smtp.example.com" /></label><label className="field">ポート<input type="number" min={1} max={65535} value={form.port} onChange={e => setForm({ ...form, port: Number(e.target.value) })} /></label><label className="field">ユーザー名<input value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} autoComplete="username" /></label><label className="field">パスワード{configured && <span className="muted text-xs">（設定済み。変更時だけ入力）</span>}<input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="new-password" /></label><label className="field">送信元メールアドレス<input type="email" required value={form.from_email} onChange={e => setForm({ ...form, from_email: e.target.value })} /></label><label className="field">送信者名<input maxLength={200} value={form.from_name} onChange={e => setForm({ ...form, from_name: e.target.value })} /></label><label className="field">接続タイムアウト（秒）<input type="number" min={1} max={120} value={form.timeout_seconds} onChange={e => setForm({ ...form, timeout_seconds: Number(e.target.value) })} /></label><label className="field">24時間の送信上限<input type="number" min={1} max={10000} value={form.max_emails_per_day} onChange={e => setForm({ ...form, max_emails_per_day: Number(e.target.value) })} /></label><label className="field">メール間隔（秒）<input type="number" min={0} max={3600} value={form.minimum_interval_seconds} onChange={e => setForm({ ...form, minimum_interval_seconds: Number(e.target.value) })} /></label><label className="checkbox-row mt-7"><input type="checkbox" checked={form.use_starttls} onChange={e => setForm({ ...form, use_starttls: e.target.checked })} />STARTTLSを使用する</label></div>
    <p className="muted mt-3 text-sm">営業メールだけに適用します。テストメールは上限・間隔に含みません。</p><div className="actions"><button disabled={busy || !form.host || !form.from_email} onClick={() => void save()}>SMTP設定を保存</button></div>
    <div className="mt-7 border-t pt-5"><h3>テスト送信</h3><p className="muted text-sm mt-2">保存済みの設定でテストメールを1通だけ送信します。</p><label className="field mt-3">テスト送信先<input type="email" value={recipient} onChange={e => setRecipient(e.target.value)} /></label><div className="actions"><button className="secondary" disabled={busy || !configured || !recipient} onClick={() => void sendTest()}>テストメールを送信</button></div></div>
    <div className="mt-7 border-t pt-5"><h3>受信メール・返信取込</h3><p className="muted text-sm mt-2">IMAP受信箱の未読メールを定期的に確認します。企業または担当者のメールアドレスに一意に一致した返信だけを自動で紐付けます。</p>
      <div className="detail-grid mt-4"><label className="field">IMAPホスト<input value={inboundForm.host} onChange={e => setInboundForm({ ...inboundForm, host: e.target.value })} placeholder="imap.example.com" /></label><label className="field">ポート<input type="number" min={1} max={65535} value={inboundForm.port} onChange={e => setInboundForm({ ...inboundForm, port: Number(e.target.value) })} /></label><label className="field">受信ユーザー名<input type="email" value={inboundForm.username} onChange={e => setInboundForm({ ...inboundForm, username: e.target.value })} autoComplete="username" /></label><label className="field">受信パスワード{inboundConfigured && <span className="muted text-xs">（設定済み。変更時だけ入力）</span>}<input type="password" value={inboundPassword} onChange={e => setInboundPassword(e.target.value)} autoComplete="new-password" /></label><label className="field">メールボックス<input value={inboundForm.mailbox} onChange={e => setInboundForm({ ...inboundForm, mailbox: e.target.value })} /></label><label className="field">接続タイムアウト（秒）<input type="number" min={1} max={120} value={inboundForm.timeout_seconds} onChange={e => setInboundForm({ ...inboundForm, timeout_seconds: Number(e.target.value) })} /></label><label className="field">確認間隔（秒）<input type="number" min={60} max={86400} value={inboundForm.poll_interval_seconds} onChange={e => setInboundForm({ ...inboundForm, poll_interval_seconds: Number(e.target.value) })} /></label><label className="checkbox-row mt-7"><input type="checkbox" checked={inboundForm.use_ssl} onChange={e => setInboundForm({ ...inboundForm, use_ssl: e.target.checked })} />SSLを使用する</label><label className="checkbox-row mt-7"><input type="checkbox" checked={inboundForm.active} onChange={e => setInboundForm({ ...inboundForm, active: e.target.checked })} />自動取込を有効にする</label></div>
      <div className="actions"><button disabled={busy || !inboundForm.host || !inboundForm.username} onClick={() => void saveInbound()}>受信設定を保存</button><button className="secondary" disabled={busy || !inboundConfigured} onClick={() => void testInbound()}>接続をテスト</button><button className="secondary" disabled={busy || !inboundConfigured || !inboundForm.active} onClick={() => void syncInbound()}>今すぐ確認</button></div>
      {inboundEmails.length > 0 && <div className="company-table-wrap mt-5"><table className="company-table"><thead><tr><th>受信日時</th><th>送信者</th><th>種別</th><th>件名</th><th>紐付け</th></tr></thead><tbody>{inboundEmails.map(item => <tr key={item.id}><td>{new Date(item.received_at).toLocaleString('ja-JP')}</td><td>{item.sender_email}</td><td>{item.classification === 'bounce' ? '不達通知' : item.classification === 'unsubscribe' ? '配信停止' : item.classification === 'reply' ? '返信' : 'その他'}</td><td><strong>{item.subject || '件名なし'}</strong><p className="muted text-xs">{item.preview}</p></td><td>{item.company_name || '未照合'}<p className="muted text-xs">{item.match_type === 'contact_person' ? '担当者メール' : item.match_type === 'company_email' ? '企業メール' : item.match_type === 'manual' ? '手動紐付け' : '確認が必要'}</p>{item.match_type === 'unmatched' && <div className="mt-3"><label className="field mb-2">紐付け先を検索<input aria-label={`${item.subject || item.sender_email}の紐付け先`} value={matchQueries[item.id] ?? item.sender_email} onChange={e => setMatchQueries({ ...matchQueries, [item.id]: e.target.value })} /></label><button className="secondary" disabled={busy} onClick={() => void findMatchCandidates(item)}>企業を検索</button>{matchCandidates[item.id]?.map(company => <button className="secondary mt-2 mr-2" disabled={busy} key={company.id} onClick={() => void matchInbound(item, company)}>{company.company_name}へ紐付け</button>)}</div>}</td></tr>)}</tbody></table></div>}
    </div>
  </section>
}
