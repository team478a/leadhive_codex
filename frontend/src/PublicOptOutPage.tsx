import { useState, type FormEvent } from 'react'
import { api, errorMessage } from './api'
import { Field } from './forms'

export function PublicOptOutPage() {
  const [target, setTarget] = useState('')
  const [verificationEmail, setVerificationEmail] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const result = await api<{ message: string }>('/public/opt-out/request', 'POST', {
        target,
        verification_email: verificationEmail,
      })
      setNotice(result.message)
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  return <main className="min-h-screen bg-[#f6f7f4] px-4 py-12 sm:px-8">
    <section className="panel mx-auto max-w-xl">
      <p className="brand text-[#173c35]">⬡ LeadHive</p>
      <h1 className="mt-6 text-2xl font-bold">LeadHiveからの送信停止</h1>
      <p className="muted mt-3">
        ご本人確認後、指定したメールアドレスまたはドメインを共通の送信停止リストに登録します。
        確認が完了するまでは送信停止は登録されません。
      </p>
      <form className="mt-6" onSubmit={submit}>
        <Field label="停止対象のメールアドレスまたはドメイン">
          <input
            autoComplete="email"
            required
            maxLength={320}
            value={target}
            onChange={event => setTarget(event.target.value)}
            placeholder="info@example.jp または example.jp"
          />
        </Field>
        <Field label="確認用メールアドレス">
          <input
            type="email"
            autoComplete="email"
            required
            maxLength={320}
            value={verificationEmail}
            onChange={event => setVerificationEmail(event.target.value)}
            placeholder="privacy@example.jp"
          />
        </Field>
        <p className="muted mb-4 text-sm">
          メールアドレスを停止する場合はそのアドレス宛て、ドメインを停止する場合はそのドメインのメールアドレス宛てに確認メールを送ります。
        </p>
        {error && <p className="error mb-4" role="alert">{error}</p>}
        {notice && <p className="mb-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800" role="status">{notice}</p>}
        <button type="submit" disabled={busy}>
          {busy ? '確認メールを送信中…' : '確認メールを受け取る'}
        </button>
      </form>
      <p className="muted mt-6 text-xs">このページで依頼しただけでは登録されません。確認メール内のボタンを押して完了してください。</p>
    </section>
  </main>
}
