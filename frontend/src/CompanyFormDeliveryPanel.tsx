import type { Company, FormDelivery, FormPreview } from './types'

type Props = {
  company: Company
  delivery: FormDelivery | null
  preview: FormPreview | null
  values: Record<string, string>
  confirmed: boolean
  assistOutcome: FormDelivery['status']
  assistNote: string
  assistConfirmed: boolean
  busy: boolean
  onValuesChange: (value: Record<string, string>) => void
  onConfirmedChange: (value: boolean) => void
  onAssistOutcomeChange: (value: FormDelivery['status']) => void
  onAssistNoteChange: (value: string) => void
  onAssistConfirmedChange: (value: boolean) => void
  onRecordAssist: () => void
  onCopyAssist: () => void
  onInspect: () => void
  onSubmit: () => void
}

export function CompanyFormDeliveryPanel({ company, delivery, preview, values, confirmed, assistOutcome, assistNote, assistConfirmed, busy, onValuesChange, onConfirmedChange, onAssistOutcomeChange, onAssistNoteChange, onAssistConfirmedChange, onRecordAssist, onCopyAssist, onInspect, onSubmit }: Props) {
  return <div className="mt-6"><h3>フォーム送信</h3><p className="muted text-sm">Form Intelligenceで準備完了になった優先フォームを使用します。変更、CAPTCHA、確認が必要なフォームはCodex支援へ引き渡します。</p>{delivery ? <div className="mt-4"><p className="muted text-sm">送信方法：{delivery.delivery_method === 'direct' ? 'LeadHive通常フォーム' : 'Codex支援'}</p><p className="muted text-sm">状態：{delivery.status === 'submitted' ? '送信済み' : delivery.status === 'failed' ? '失敗' : '保留'}</p>{delivery.completion_evidence && <p className="muted text-sm">完了確認：{delivery.completion_evidence}{delivery.confirmation_used ? '（確認画面から最終送信）' : ''}</p>}{delivery.final_url && <p className="muted text-xs break-all">完了ページ：<a href={delivery.final_url} target="_blank" rel="noreferrer">{delivery.final_url}</a></p>}{delivery.profile_fingerprint && <p className="muted text-xs">解析Fingerprint：{delivery.profile_fingerprint.slice(0, 12)}…</p>}{delivery.result_note && <p className="muted text-sm">メモ：{delivery.result_note}</p>}{delivery.delivery_method === 'codex_assisted' && delivery.status !== 'submitted' && <div className="mt-4"><label className="field">結果<select value={assistOutcome} onChange={e => onAssistOutcomeChange(e.target.value as FormDelivery['status'])}><option value="pending">保留</option><option value="submitted">送信済み</option><option value="failed">失敗</option></select></label><label className="field">メモ<textarea rows={3} maxLength={500} value={assistNote} onChange={e => onAssistNoteChange(e.target.value)} placeholder="例：CAPTCHAが解けず保留" /></label><label className="checkbox-row"><input type="checkbox" checked={assistConfirmed} onChange={e => onAssistConfirmedChange(e.target.checked)} />Codex上で確認した結果を記録します。</label><div className="actions"><button disabled={busy || !assistConfirmed} onClick={onRecordAssist}>Codex支援の結果を記録</button></div></div>}</div> : <><div className="actions"><button className="secondary" disabled={busy || company.do_not_contact} onClick={onCopyAssist}>Codex支援用の指示をコピー</button></div><div className="mt-4"><h4>Codex支援の送信結果</h4><label className="field">結果<select value={assistOutcome} onChange={e => onAssistOutcomeChange(e.target.value as FormDelivery['status'])}><option value="pending">保留</option><option value="submitted">送信済み</option><option value="failed">失敗</option></select></label><label className="field">メモ<textarea rows={3} maxLength={500} value={assistNote} onChange={e => onAssistNoteChange(e.target.value)} placeholder="例：CAPTCHAが解けず保留" /></label><label className="checkbox-row"><input type="checkbox" checked={assistConfirmed} onChange={e => onAssistConfirmedChange(e.target.checked)} />Codex上で確認した結果を記録します。</label><div className="actions"><button disabled={busy || !assistConfirmed || company.do_not_contact} onClick={onRecordAssist}>Codex支援の結果を記録</button></div></div>{!preview ? <div className="actions"><button className="secondary" disabled={busy || company.do_not_contact} onClick={onInspect}>解析済みフォームを確認</button></div> : <><p className="muted text-xs mt-3 break-all">送信先: {preview.form_url} / Fingerprint: {preview.fingerprint.slice(0, 12)}…</p><div className="detail-grid mt-3">{preview.fields.map(field => <label className="field" key={field.name}>{field.label}{field.required && ' *'}<span className="muted text-xs">自動判定：{field.mapped_key}（{Math.round(field.confidence * 100)}%）</span>{field.field_type === 'textarea' ? <textarea rows={5} value={values[field.name] ?? ''} onChange={e => onValuesChange({ ...values, [field.name]: e.target.value })} /> : field.field_type === 'select' ? <select value={values[field.name] ?? ''} onChange={e => onValuesChange({ ...values, [field.name]: e.target.value })}><option value="">選択してください</option>{field.options.map(option => <option value={option} key={option}>{option}</option>)}</select> : <input type={field.field_type} value={values[field.name] ?? ''} onChange={e => onValuesChange({ ...values, [field.name]: e.target.value })} />}</label>)}</div><label className="checkbox-row mt-4"><input type="checkbox" checked={confirmed} onChange={e => onConfirmedChange(e.target.checked)} />入力内容、送信先、解析結果を確認し、このフォーム送信を承認します。</label><div className="actions"><button disabled={busy || !confirmed || company.do_not_contact} onClick={onSubmit}>フォームを送信</button></div></>}</>}</div>
}
