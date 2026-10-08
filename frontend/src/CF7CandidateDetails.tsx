export interface CF7Control { name: string; label: string; kind: string; required: boolean; checkbox_value: string }
interface Value { name: string; value: string }
export interface CF7Snapshot {
  contract: {
    form_url: string; endpoint: string; payload_version: number; dom_fingerprint: string
    subject: string; body: string; sender: Value[]; field_values: Value[]
    controls: CF7Control[]; selections: { name: string; checked: boolean }[]
  }
  contract_hash: string; wire_sha256: string; wire_size: number
}
export interface CF7Observation { observed_at: string; expires_at: string; evidence_hash: string }
export function CF7CandidateDetails({ snapshot, hash, observation }: {
  snapshot: CF7Snapshot; hash?: string | null; observation?: CF7Observation | null
}) {
  const contract = snapshot.contract
  const values = new Map(contract.field_values.map(v => [v.name, v.value]))
  const selections = new Map(contract.selections.map(v => [v.name, v.checked]))
  return <section aria-label="CF7候補の確認内容" className="space-y-3">
    <p>保存済みの検証用証拠です。現在の企業サイトを確認した結果ではありません。承認しても送信できません。</p>
    <p className="break-all">フォームURL: {contract.form_url}</p>
    <p className="break-all">REST endpoint: {contract.endpoint}</p>
    <p className="break-words">送信者: {contract.sender.filter(v => v.value).map(v => `${v.name}: ${v.value}`).join(' / ')}</p>
    <p>件名: {contract.subject || '件名なし'}</p>
    <p className="whitespace-pre-wrap break-words">本文: {contract.body}</p>
    <h3>入力値と同意（フォームの順序）</h3>
    <dl>{contract.controls.map(control => <div key={control.name}>
      <dt className="break-words">{control.label} / {control.name}{control.required ? '（必須）' : '（任意）'}</dt>
      <dd className="whitespace-pre-wrap break-words">{control.kind === 'checkbox'
        ? `${selections.get(control.name) ? '選択する' : '選択しない'} / 値: ${control.checkbox_value}`
        : values.get(control.name) || '未入力'}</dd>
    </div>)}</dl>
    {observation && <>
      <p>証拠観察日時: {new Date(observation.observed_at).toLocaleString('ja-JP')}</p>
      <p>証拠期限: {new Date(observation.expires_at).toLocaleString('ja-JP')}</p>
    </>}
    <details><summary>検証情報・hash</summary>
      <p>候補version: {contract.payload_version}</p>
      <p className="break-all">snapshot hash: {hash}</p>
      <p className="break-all">contract hash: {snapshot.contract_hash}</p>
      <p className="break-all">証拠hash: {observation?.evidence_hash}</p>
      <p className="break-all">DOM fingerprint: {contract.dom_fingerprint}</p>
      <p className="break-all">wire hash: {snapshot.wire_sha256} / {snapshot.wire_size} bytes</p>
    </details>
  </section>
}
