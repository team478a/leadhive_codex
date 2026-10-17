import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import { Field } from './forms'

interface Limits {
  daily_limit: number; hourly_limit: number; minimum_interval_seconds: number
  site_interval_seconds: number; paused: boolean; version: number; can_manage: boolean; execution_enabled: boolean
}

export function FormDispatchLimitsSettingsPanel() {
  const [limits, setLimits] = useState<Limits | null>(null)
  const [saved, setSaved] = useState<Limits | null>(null)
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const refresh = async () => {
    const value = await api<Limits>('/form-dispatch-limits')
    setLimits(value); setSaved(value)
  }
  useEffect(() => {
    let active = true
    api<Limits>('/form-dispatch-limits').then(value => {
      if (active) { setLimits(value); setSaved(value) }
    }).catch(reason => { if (active) setError(errorMessage(reason)) })
    return () => { active = false }
  }, [])
  async function save() {
    if (!limits) return
    setBusy(true); setError(''); setNotice('')
    try {
      const updated = await api<Limits>('/form-dispatch-limits', 'PUT', {
        daily_limit: limits.daily_limit, hourly_limit: limits.hourly_limit,
        minimum_interval_seconds: limits.minimum_interval_seconds,
        site_interval_seconds: limits.site_interval_seconds, paused: limits.paused,
        expected_version: limits.version, password,
      })
      setLimits(updated); setSaved(updated); setPassword(''); setNotice('フォーム上限を保存しました。実送信設定は変更していません。')
    } catch (reason) { setError(errorMessage(reason)) } finally { setBusy(false) }
  }
  return <section className="panel mt-6" aria-label="フォーム送信上限">
    <h2>フォーム送信上限</h2>
    <p className="muted mt-2">環境全体の24時間・1時間上限、試行間隔、一時停止を設定します。上限変更では実送信を有効化しません。</p>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {saved && <p className="mt-3">保存済み：直近24時間{saved.daily_limit}件・直近1時間{saved.hourly_limit}件・間隔{saved.minimum_interval_seconds}秒・同じサイト{saved.site_interval_seconds}秒 / {saved.paused ? '一時停止中' : '上限に従って実行'} / 実行{saved.execution_enabled ? '有効' : 'OFF'}</p>}
    {limits && <fieldset disabled={busy || !limits.can_manage} className="mt-4 space-y-3">
      <div className="detail-grid"><Field label="フォーム24時間上限"><input type="number" min="1" max="1000" value={limits.daily_limit} onChange={event => setLimits({ ...limits, daily_limit: Number(event.target.value) })} /></Field>
        <Field label="フォーム1時間上限"><input type="number" min="1" max="100" value={limits.hourly_limit} onChange={event => setLimits({ ...limits, hourly_limit: Number(event.target.value) })} /></Field>
        <Field label="フォーム試行間隔（秒）"><input type="number" min="60" max="86400" value={limits.minimum_interval_seconds} onChange={event => setLimits({ ...limits, minimum_interval_seconds: Number(event.target.value) })} /></Field>
        <Field label="同じサイトへの試行間隔（秒）"><input type="number" min="60" max="86400" value={limits.site_interval_seconds} onChange={event => setLimits({ ...limits, site_interval_seconds: Number(event.target.value) })} /></Field></div>
      <label><input type="checkbox" checked={limits.paused} onChange={event => setLimits({ ...limits, paused: event.target.checked })} /> フォーム実行を一時停止</label>
      <Field label="上限変更用管理者パスワード"><input type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} /></Field>
      <p>結果不明・失敗した試行も上限に数えます。承認期限内に処理できる件数を予約してください。</p>
      <div className="actions"><button type="button" disabled={!limits.can_manage || !password} onClick={() => void save()}>管理者再認証してフォーム上限を保存</button><button type="button" className="secondary" onClick={() => void refresh().catch(reason => setError(errorMessage(reason)))}>保存済み上限を再取得</button></div>
    </fieldset>}
  </section>
}
