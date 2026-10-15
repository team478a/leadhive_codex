import { useState } from 'react'
import type { Company } from './types'

export function CompanySalesNgAction({ company, busy, readOnly, onMark }: {
  company: Company
  busy: boolean
  readOnly: boolean
  onMark: (reason: string) => Promise<void>
}) {
  const [reason, setReason] = useState('')
  const alreadyListed = company.do_not_contact && company.exclusion_reason.startsWith('営業NG：')
  return <section className="notice mt-4" aria-label="営業NG登録">
    <h3>{alreadyListed ? '営業NGリストに登録済み' : '営業NGを見つけたら、ここから除外'}</h3>
    <p>登録するとメール・フォームの送信対象から外れます。確認した禁止表示や連絡拒否の理由を記録してください。</p>
    {company.do_not_contact && <p className="text-sm break-all">現在の禁止理由：{company.exclusion_reason || '連絡禁止'}</p>}
    {readOnly ? <p>営業NGの登録は所有者または編集者が行います。</p> : !alreadyListed && <>
      <label className="field">営業NGの理由<input maxLength={350} value={reason} disabled={busy} onChange={event => setReason(event.target.value)} placeholder="例：問い合わせページに営業目的の連絡禁止と記載" /></label>
      <button disabled={busy || !reason.trim()} onClick={() => void onMark(reason.trim())}>営業NGリストへ移す</button>
    </>}
    {alreadyListed && <p>再解析しても自動解除されません。</p>}
  </section>
}
