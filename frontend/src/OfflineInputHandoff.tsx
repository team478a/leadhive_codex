import { useState } from 'react'
import type { Activity, Company } from './types'
import { bindInput, sanitizeReport, trialPrefix, type TrialBinding } from './offlineHandoffContract'
const statusLabels: Record<string, string> = { OFFLINE_INPUT_VERIFIED: '保存HTMLへの入力成功', HUMAN_REQUIRED: '人の確認が必要', BLOCKED: '営業NG・停止', TECHNICAL_UNKNOWN: '入力を確認できず停止' }
const reasonLabels: Record<string, string> = { STOP_BEFORE_CONFIRMATION_OR_SEND: '入力を読み戻して確認。確認・送信ボタンは操作していません。', CAPTCHA: 'CAPTCHAのため人の操作が必要です。', SALES_PROHIBITED: '営業禁止のため入力していません。', NETWORK_REQUIRED: '外部通信が必要です。保存HTMLだけでは確認できません。', REQUIRED_FIELD_UNKNOWN: '必須項目の入力値が分かりません。', CONSENT_REVIEW_REQUIRED: '同意内容の確認が必要です。', CHOICE_REVIEW_REQUIRED: '選択肢の指定・確認が必要です。', STRUCTURE_CHANGED: '入力中にフォーム構造が変わりました。', READBACK_MISMATCH: '入力値の読み戻しが一致しません。', FORM_VALIDATION_ERROR: 'フォームの入力チェックに失敗しました。', TIMEOUT: '制限時間に達しました。', FORM_AMBIGUOUS: '操作するフォームを一つに特定できません。' }

export function OfflineInputHandoff({ company, activities, readOnly, busy, prohibited, onSave }: {
  company: Company; activities: Activity[]; readOnly: boolean; busy: boolean; prohibited: boolean; onSave: (note: string) => Promise<boolean>
}) {
  const storageKey = `offline-input:${company.project_id}:${company.id}`
  const [binding, setBinding] = useState<TrialBinding | null>(() => {
    try { const v = JSON.parse(sessionStorage.getItem(storageKey) || 'null'); return v?.companyId === company.id && v?.projectId === company.project_id ? v : null } catch { return null }
  })
  const [message, setMessage] = useState('')
  const [processing, setProcessing] = useState(false)
  async function read(file: File) {
    if (file.size > 1_000_000) throw Error('ファイルは1MB以下にしてください。')
    try { return JSON.parse(await file.text()) as unknown } catch { throw Error('JSONファイルを確認してください。') }
  }
  async function prepare(file: File) {
    setProcessing(true); setMessage('')
    try {
      const task = await bindInput(await read(file), company.id, company.project_id, prohibited)
      const link = document.createElement('a'); const url = URL.createObjectURL(new Blob([JSON.stringify(task)], { type: 'application/json' }))
      link.href = url; link.download = `offline-input-${task.binding.trialId}.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
      sessionStorage.setItem(storageKey, JSON.stringify(task.binding)); setBinding(task.binding)
      setMessage('PC実行用の依頼を保存しました。HTML・入力値はクラウドへ送っていません。')
    } catch (e) { setMessage(e instanceof Error ? e.message : '依頼を作成できませんでした。') } finally { setProcessing(false) }
  }
  async function importResult(file: File) {
    if (!binding) return
    setProcessing(true); setMessage('')
    try {
      const value = sanitizeReport(await read(file), binding)
      if (activities.some(a => a.note.startsWith(trialPrefix) && a.note.includes(binding.trialId))) throw Error('この依頼の結果は記録済みです。')
      if (await onSave(trialPrefix + JSON.stringify(value))) { setMessage('PCの診断報告を記録しました。未認証の報告であり、人の確認・送信承認ではありません。'); sessionStorage.removeItem(storageKey); setBinding(null) }
    } catch (e) { setMessage(e instanceof Error ? e.message : '結果を記録できませんでした。') } finally { setProcessing(false) }
  }
  return <section className="panel mt-4" aria-label="保存HTMLのPC入力試行">
    <h3>PCで保存HTMLの入力を試す</h3>
    <p>保存HTMLと入力値のJSONから実行依頼を作り、PCランナーの結果をこの企業へ戻します。実サイトを開かず、送信しません。</p>
    {prohibited && <p className="notice">営業NGです。依頼もBLOCKEDとなり、入力は行いません。</p>}
    {!readOnly && <>
      <label className="field">保存HTMLの入力JSON<input type="file" accept=".json,application/json" disabled={busy || processing} onChange={e => { const f = e.target.files?.[0]; e.target.value = ''; if (f) void prepare(f) }} /></label>
      {binding && <><p>依頼作成済み。PCで実行後、結果JSONを選んでください。同じブラウザタブで再読込しても依頼情報を維持します。</p>
        <code>npm run trial:offline-form-input</code>
        <p>PC側でLEADHIVE_OFFLINE_FORM_INPUT=1とLEADHIVE_OFFLINE_INPUT_FILEに依頼ファイルを設定します。</p>
        <label className="field">PC入力試行の結果JSON<input type="file" accept=".json,application/json" disabled={busy || processing} onChange={e => { const f = e.target.files?.[0]; e.target.value = ''; if (f) void importResult(f) }} /></label></>}
    </>}
    {readOnly && <p>所有者・編集者が依頼作成と記録を行います。</p>}
    {message && <p role="status">{message}</p>}
    <p className="muted text-sm">PC報告は署名されていません。企業とhashの照合は取り違え防止であり、結果の真正性を保証しません。入力内容を含む依頼は安全に保管してください。</p>
    {activities.filter(a => a.company_id === company.id && a.note.startsWith(trialPrefix)).slice(0, 5).map(a => {
      try { const v = JSON.parse(a.note.slice(trialPrefix.length)); return v.source === 'PC_REPORTED_UNVERIFIED' && v.sent === false && v.companyId === company.id
        ? <article key={a.id}><strong>PC報告・未認証・未送信</strong><p>{statusLabels[String(v.status)] || '未分類'} / {reasonLabels[String(v.reason)] || `未分類の停止（${String(v.reason)}）`}</p><p>{new Date(a.created_at).toLocaleString('ja-JP')}</p></article> : null } catch { return null }
    })}
  </section>
}
