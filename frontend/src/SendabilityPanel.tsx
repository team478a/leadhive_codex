import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'

type Reason = { code: string; message: string; next_action: string }
type Assessment = {
  company_id: string; definition_version: string; evaluated_at: string; status: string
  reasons: Reason[]; live_destination_checked: boolean
  destinations: { type: string; destination: string; purpose: string; status: string; reasons: Reason[]; core_permission: string }[]
}
const states: Record<string, string> = { READY: '準備候補', REVIEW: '要確認', HOLD: '保留', BLOCKED: '利用不可' }

export function SendabilityPanel({ companyId, updatedAt, inventoryRevision }: { companyId: string; updatedAt: string; inventoryRevision: number }) {
  const [data, setData] = useState<Assessment | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    api<Assessment>(`/companies/${companyId}/sendability`).then(value => {
      if (active) { setData(value); setError('') }
    }).catch(e => { if (active) { setData(null); setError(errorMessage(e)) } })
    return () => { active = false }
  }, [companyId, updatedAt, inventoryRevision])
  return <section className="mt-5" aria-label="窓口の利用可否と理由">
    <h3>窓口の利用可否と理由</h3>
    <p className="muted">保存済み情報からの準備診断です。現在のサイトへの接続、送信承認、送信は行いません。用途の確認証跡を保存する機能は次工程のため、READYへの確定はまだ行いません。</p>
    {error && <p role="alert">判定を取得できません：{error}</p>}
    {data?.company_id === companyId && <>
      <p role="status">判定：{states[data.status] ?? '未判定'}（{data.status}）</p>
      <p className="muted">{data.definition_version} / {new Date(data.evaluated_at).toLocaleString('ja-JP')} 現在。DM READY・送信許可とは別の判定です。</p>
      <ul>{data.reasons.map(reason => <li key={reason.code}><strong>{reason.message}</strong>：{reason.next_action} <small>({reason.code})</small></li>)}</ul>
      {data.destinations.map(item => <details key={`${item.type}:${item.destination}`} className="mt-3 break-all">
        <summary>{item.type}：{item.destination} / {states[item.status] ?? '未判定'}（{item.status}）</summary>
        <p>既存連絡可否：{item.core_permission} / 用途登録：{item.purpose}。ALLOWEDだけでは準備完了になりません。</p>
        <ul>{item.reasons.map(reason => <li key={reason.code}>{reason.message}：{reason.next_action} <small>({reason.code})</small></li>)}</ul>
      </details>)}
    </>}
  </section>
}
