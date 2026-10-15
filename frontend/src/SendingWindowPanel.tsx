import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'

type WindowSettings = { enabled: boolean; start_minute: number; end_minute: number; timezone: string; allowed_now: boolean }
const clock = (minute: number) => `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`
const minutes = (value: string) => { const [hour, minute] = value.split(':').map(Number); return hour * 60 + minute }

export function SendingWindowPanel() {
  const [saved, setSaved] = useState<WindowSettings | null>(null)
  const [enabled, setEnabled] = useState(true)
  const [start, setStart] = useState('08:00')
  const [end, setEnd] = useState('20:00')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  useEffect(() => {
    let active = true
    api<WindowSettings>('/admin/sending-window').then(value => {
      if (!active) return
      setSaved(value); setEnabled(value.enabled); setStart(clock(value.start_minute)); setEnd(clock(value.end_minute))
    }).catch(e => { if (active) setError(errorMessage(e)) })
    return () => { active = false }
  }, [])
  async function save() {
    if (!start || !end || minutes(start) >= minutes(end)) { setError('終了時刻は開始時刻より後にしてください。'); return }
    setBusy(true); setError(''); setNotice('')
    try {
      const value = await api<WindowSettings>('/admin/sending-window', 'PUT', { enabled, start_minute: minutes(start), end_minute: minutes(end) })
      setSaved(value); setNotice('送信可能時間を保存しました。')
    } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  return <section className="mt-6" aria-label="送信可能時間">
    <h3>送信可能時間</h3>
    <p className="muted">曜日を問わず、毎日この時間帯だけメール・フォームを送信します（日本時間）。時間外は待機し、次の時間帯に承認・送信上限を再確認して再開します。</p>
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p className="notice" role="status">{notice}</p>}
    <label className="field"><span><input type="checkbox" disabled={busy || !saved} checked={enabled} onChange={e => setEnabled(e.target.checked)} /> 送信する時間帯を制限する</span></label>
    <div className="detail-grid">
      <label className="field">送信開始時刻<input type="time" disabled={busy || !saved} value={start} onChange={e => setStart(e.target.value)} /></label>
      <label className="field">送信終了時刻<input type="time" disabled={busy || !saved} value={end} onChange={e => setEnd(e.target.value)} /></label>
    </div>
    <p className="muted">保存済み：{saved ? (saved.enabled ? `毎日 ${clock(saved.start_minute)}〜${clock(saved.end_minute)}（保存時点：${saved.allowed_now ? '時間内' : '時間外・待機'}）` : '時間帯の制限なし') : '確認中'}</p>
    <p className="muted">終了時刻以降は新しい送信を開始しません。承認期限は延長されず、結果不明の送信は自動再送しません。PCとworkerが稼働している間に処理します。</p>
    <button className="button secondary" disabled={busy || !saved} onClick={() => void save()}>送信可能時間を保存</button>
  </section>
}
