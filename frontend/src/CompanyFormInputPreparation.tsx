import { useState } from 'react'
import { api } from './api'

type Report = {
  snapshot_hash: string; can_record: boolean; review_status: string; reasons: string[]
  reviewed_at?: string; review_expires_at?: string
  snapshot: { form_url: string; plugin_version: string | null; rows: { position: number; name: string; label: string; required: boolean; values: string[]; state: string }[] }
}
type ContractPreview = { status: string; reasons: string[]; contract_hash: string | null; encoding_preview?: { wire_size: number; wire_sha256: string } | null; contract: { endpoint: string; contract_family: string; parts: { name: string }[] } | null }
type HandoffPreview = { status: string; reasons: string[]; snapshot_hash: string | null; snapshot: { expires_at: string; contract: { endpoint: string; parts: { name: string; value: string; kind: string }[] }; input_review: { actor_user_id: string } } | null }
const contractReasons: Record<string, string> = {
  WIRE_ENCODING_UNSUPPORTED: '送信データの変換条件・サイズ上限を満たしていません。送信せず確認してください。',
  INPUT_CONFIRMATION_REQUIRED: '現在の入力内容を人が確認・記録してください。', CONFIRMATION_EXPIRED: '確認記録またはフォーム観測が期限切れです。',
  OBSERVATION_UNVERIFIED: '現在のフォーム構造が未確認です。', OBSERVATION_CHANGED: 'フォーム観測が変わりました。入力内容を確認し直してください。',
  INPUT_SNAPSHOT_CHANGED: '入力内容の確認票が変更されています。', CONTRACT_EVIDENCE_UNVERIFIED: '送信先設定・項目順序・hiddenの証拠が不足、変更、または未対応です。「現在のフォームを確認」後に入力内容を確認し直してください。',
}
const reasons: Record<string, string> = {
  CONTACT_BLOCKED: '連絡禁止・営業禁止のため記録できません。', CAPTCHA: 'CAPTCHAは人の操作が必要です。',
  CF7_UNVERIFIED: 'CF7の保存情報が未確認です。', OBSERVATION_UNVERIFIED: '現在のフォームを確認してください。',
  VERSION_UNVERIFIED: '未対応または未確認の版です。', HIDDEN_UNVERIFIED: 'hiddenの対応関係が未確認です。現在のフォームを再確認してください。',
  REST_ROOT_UNVERIFIED: 'REST送信先の確認が必要です。', UNSUPPORTED_STRUCTURE: '未対応の項目・同名項目・追加hiddenがあります。',
  DRAFT_MISSING: 'フォーム用の下書きがありません。', INPUT_REVIEW_REQUIRED: '未確定の入力・選択があります。', REQUIRED_VALUE_MISSING: '必須の入力値が不足しています。',
}

export function CompanyFormInputPreparation({ profileId, readOnly }: { profileId: string; readOnly: boolean }) {
  const [report, setReport] = useState<Report | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [contract, setContract] = useState<ContractPreview | null>(null)
  const [handoff, setHandoff] = useState<HandoffPreview | null>(null)
  const [approvalNotice, setApprovalNotice] = useState('')
  async function load() {
    setBusy(true); setConfirmed(false); setError(''); setReport(null); setContract(null); setHandoff(null); setApprovalNotice('')
    try { setReport(await api<Report>(`/form-profiles/${profileId}/input-preparation`)) }
    catch (err) { setError(err instanceof Error ? err.message : '確認票を取得できませんでした。') }
    finally { setBusy(false) }
  }
  async function record() {
    if (!report?.can_record || !confirmed) return
    setBusy(true); setError(''); setContract(null); setHandoff(null); setApprovalNotice('')
    try {
      setReport(await api<Report>(`/form-profiles/${profileId}/input-preparation/reviews`, 'POST', { expected_snapshot_hash: report.snapshot_hash, input_content_confirmed: true }))
      setConfirmed(false)
    } catch (err) {
      setConfirmed(false); setReport(null)
      setError(err instanceof Error ? err.message : '記録できませんでした。確認票を読み直してください。')
    } finally { setBusy(false) }
  }
  async function inspectContract() {
    setBusy(true); setError(''); setContract(null); setHandoff(null); setApprovalNotice('')
    try { setContract(await api<ContractPreview>(`/form-profiles/${profileId}/contract-preview`)) }
    catch (err) { setError(err instanceof Error ? err.message : '契約プレビューを取得できませんでした。') }
    finally { setBusy(false) }
  }
  async function inspectHandoff() {
    setBusy(true); setError(''); setHandoff(null); setApprovalNotice('')
    try { setHandoff(await api<HandoffPreview>(`/form-profiles/${profileId}/approval-handoff-preview`)) }
    catch (err) { setContract(null); setError(err instanceof Error ? err.message : '引き継ぎ内容を取得できませんでした。') }
    finally { setBusy(false) }
  }
  async function requestApproval() {
    if (readOnly || !handoff?.snapshot_hash || handoff.status !== 'PREPARATION_ONLY') return
    setBusy(true); setError(''); setApprovalNotice('')
    try {
      const item = await api<{ status: string }>(`/form-profiles/${profileId}/approval-handoff-request`, 'POST', { expected_handoff_hash: handoff.snapshot_hash })
      setApprovalNotice(item.status === 'APPROVED' ? '同じ候補は承認済みです。送信は行っていません。' : '承認キューへ追加しました。承認キューで内容確認とパスワード再認証を行ってください。送信は行っていません。')
    } catch (err) { setHandoff(null); setContract(null); setError(err instanceof Error ? err.message : '承認候補を作成できませんでした。再確認してください。') }
    finally { setBusy(false) }
  }
  return <section aria-label="入力内容の確認票" className="notice mt-4">
    <h3>入力内容の確認票</h3>
    <p>保存済みの送信者・下書き・選択値をまとめます。ブラウザ入力・送信承認・送信は行いません。</p>
    <button type="button" className="secondary mt-2" disabled={busy} onClick={load}>{busy ? '確認中…' : '入力内容をまとめて確認'}</button>
    {error && <p role="alert" className="error mt-2">{error}</p>}
    {report && <div className="mt-3">
      <p className="break-all">対象ページ：{report.snapshot.form_url}</p>
      <p>版：{report.snapshot.plugin_version ?? '未確認'} / {({ NOT_RECORDED: '入力確認は未記録', RECORDED: '入力確認を記録済み（送信承認ではありません）', INVALIDATED: '内容が変更・未確認になりました。再確認が必要です。', EXPIRED: '確認記録が期限切れです。' } as Record<string, string>)[report.review_status] ?? '未確認'}</p>
      {report.reviewed_at && <p>確認日時：{new Date(report.reviewed_at).toLocaleString('ja-JP')} / 期限：{report.review_expires_at ? new Date(report.review_expires_at).toLocaleString('ja-JP') : '未確認'}</p>}
      {report.reasons.map(code => <p key={code}>{reasons[code] ?? '追加確認が必要です。'}</p>)}
      {report.snapshot.rows.map(row => <details key={`${row.position}:${row.name}`} className="mt-2">
        <summary>{row.label || row.name || '名称未確認'}{row.required ? '（必須）' : ''}：{row.values.length ? '値あり' : '空欄・未確定'}</summary>
        {row.values.map((value, index) => <p className="break-all whitespace-pre-wrap" key={index}>{value}</p>)}
      </details>)}
      <p className="text-xs break-all mt-2">確認票hash：{report.snapshot_hash}</p>
      {!readOnly && report.can_record && report.review_status !== 'RECORDED' && <>
        <label className="flex gap-2 mt-2"><input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} />宛先ページ・入力値・選択内容を確認しました（送信承認ではありません）</label>
        <button type="button" className="secondary mt-2" disabled={!confirmed || busy} onClick={record}>入力内容の確認を記録</button>
      </>}
      {report.review_status === 'RECORDED' && <button type="button" className="secondary mt-2" disabled={busy} onClick={inspectContract}>フォーム証拠と入力を照合</button>}
      {contract && <div aria-label="契約プレビュー" className="mt-3">
        <p>{contract.status === 'PREVIEW_ONLY' ? '照合済み・送信不可の契約プレビュー' : '証拠照合は保留です。'}</p>
        <p>これは送信承認ではありません。実行時の安全確認と承認・送信接続は別工程です。</p>
        {contract.reasons.map(code => <p key={code}>{contractReasons[code] ?? '追加確認が必要です。'}</p>)}
        {contract.contract && <><p>版別契約：{contract.contract.contract_family} / 項目数：{contract.contract.parts.length}</p><p className="break-all">確認したREST送信先：{contract.contract.endpoint}</p><p className="text-xs break-all">契約hash：{contract.contract_hash}</p></>}
        {contract.encoding_preview && <p>送信データの変換確認：{contract.encoding_preview.wire_size.toLocaleString('ja-JP')} bytes（送信は実行しません）</p>}
        {!readOnly && contract.status === 'PREVIEW_ONLY' && <button type="button" className="secondary mt-2" disabled={busy} onClick={inspectHandoff}>承認へ引き継ぐ内容を確認</button>}
      </div>}
      {handoff && <div aria-label="承認引き継ぎプレビュー" className="mt-3">
        <p>{handoff.status === 'PREPARATION_ONLY' ? approvalNotice ? '承認キューへ引き継ぎました（送信不可）。' : '承認引き継ぎ用の内容を照合しました。送信承認は未作成です。' : '内容が変更・期限切れ・未確認のため、引き継ぎを保留しています。'}</p>
        <p>入力確認と送信承認は別です。この画面から承認・送信は行えません。</p>
        {handoff.reasons.map(code => <p key={code}>{contractReasons[code] ?? '追加確認が必要です。'}</p>)}
        {handoff.snapshot && <>
          <p className="break-all">対象送信先：{handoff.snapshot.contract.endpoint}</p>
          <p>内容の有効期限：{new Date(handoff.snapshot.expires_at).toLocaleString('ja-JP')}</p>
          <details><summary>引き継ぐ入力内容</summary>{handoff.snapshot.contract.parts.filter(part => part.kind !== 'metadata').map(part => <p className="break-all whitespace-pre-wrap" key={part.name}>{part.name}：{part.value || '空欄'}</p>)}</details>
          <p className="text-xs break-all">引き継ぎhash：{handoff.snapshot_hash}</p>
          {!readOnly && handoff.status === 'PREPARATION_ONLY' && !approvalNotice && <button type="button" className="secondary mt-2" disabled={busy} onClick={requestApproval}>候補内容を承認キューへ追加（送信不可）</button>}
        </>}
        {approvalNotice && <p role="status">{approvalNotice}</p>}
      </div>}
    </div>}
  </section>
}
