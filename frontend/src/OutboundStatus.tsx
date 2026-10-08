import { useEffect, useState } from 'react'
import { api } from './api'

export function OutboundStatus() {
  const [enabled, setEnabled] = useState<boolean | null>(null)
  useEffect(() => {
    let active = true
    const refresh = async () => {
      try {
        const value = await api<{ outbound_enabled: boolean }>('/outreach-execution-status')
        if (active) setEnabled(value.outbound_enabled === true)
      } catch { if (active) setEnabled(null) }
    }
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 30000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])
  return <div className="notice" role="note" aria-label="外部送信の運用状態" aria-live="polite">
    {enabled === false ? '外部送信は停止中です。収集・解析・文面準備・承認は利用できます。メール・フォーム・テスト送信・Codex送信支援は実行できません。'
      : enabled === true ? '外部送信の停止設定は解除されています。承認・送信条件の確認が必要です。'
        : '外部送信の設定を確認できていません。送信せず、状態を確認してください。'}
  </div>
}
