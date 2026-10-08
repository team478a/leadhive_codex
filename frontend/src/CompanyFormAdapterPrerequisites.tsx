export type AdapterPrerequisites = {
  checks: { code: string; status: string; message: string; next_action: string }[]
  cf7_shape_issues: string[]
  next_action: string
  cf7_readiness?: {
    status: string; observed_version: string | null; lab_contract_status: string; freshness: string
    reasons: { code: string; message: string; next_action: string }[]
  }
}
const titles: Record<string, string> = { CONTACT_PERMISSION: '営業可否', STRUCTURE_COMPARISON: '保存構造の比較', FIELD_IDENTITY: '入力先の特定', CHOICE_REVIEW: '複数選択の確認履歴', CF7_CONTRACT_SHAPE: 'CF7限定契約との差分', EXECUTION_ROUTE: '実行経路', HUMAN_APPROVAL: '送信承認' }
const states: Record<string, string> = { OBSERVED: '保存済み情報あり', REVIEW: '確認が必要', BLOCKED: '送信禁止', NOT_APPLICABLE: '該当する保存情報なし', HUMAN_REQUIRED: '人の操作が必要', UNSUPPORTED: '未対応', SEPARATE_REVIEW: '別工程で確認' }
const issues: Record<string, string> = { STATIC_SHAPE_UNVERIFIED: '有効な静的差分情報が不足', VERSION_UNVERIFIED: '管理下テストと同じ版か未確認', HIDDEN_INCOMPLETE: '必要なhidden項目が不足・未確認', HIDDEN_SHAPE_UNVERIFIED: 'hidden形状との一致が未確認', EXTRA_HIDDEN: '限定契約外のhidden項目', FIELD_NAMES_OUTSIDE_CONTRACT: '限定契約外の項目名', REPEATED_NAMES: '同名項目あり', RADIO_UNSUPPORTED: 'radio項目の対応検証が必要', SELECT_UNSUPPORTED: 'select項目の対応検証が必要', DISABLED_CONTROLS: '無効化された項目あり', CHECKBOX_CONTRACT_UNCONNECTED: 'checkbox確認履歴と実行用契約は未接続' }

export function CompanyFormAdapterPrerequisites({ report }: { report: AdapterPrerequisites }) {
  return <section className="notice mt-4" aria-label="フォーム対応の前提条件">
    <h3>フォーム対応の前提条件</h3>
    <p className="muted mt-2">保存済み情報の点検です。「情報あり」は実サイト対応済み・営業許可・送信承認を意味しません。</p>
    {report.cf7_readiness && report.cf7_readiness.status !== 'NOT_APPLICABLE' && <section aria-label="CF7対応状況" className="mt-3">
      <strong>CF7対応状況：{({ BLOCKED: '送信対象外', HUMAN_REQUIRED: '人の操作が必要', HOLD: '実サイト送信は保留' } as Record<string, string>)[report.cf7_readiness.status] ?? '未確認'}</strong>
      <p>HTML記載の版：{report.cf7_readiness.observed_version ?? '未確認'} / 隔離環境の契約検証：{report.cf7_readiness.lab_contract_status === 'VERIFIED_FIXTURE_ONLY' ? '検証済み（実サイト対応ではありません）' : '未確認'}</p>
      <p>{report.cf7_readiness.freshness === 'CURRENT' ? '24時間以内の観測です。実行時の状態やプラグインの実版を保証しません。' : '以前の情報または未確認です。現在のフォームを確認してください。'}</p>
      {report.cf7_readiness.reasons.map((reason, index) => <details className="mt-2" key={reason.code} open={index === 0}>
        <summary>{index === 0 ? '最初に確認すること：' : ''}{reason.message}</summary>
        <p className="mt-2">{reason.next_action}</p>
      </details>)}
    </section>}
    {report.checks.map(check => <details className="mt-3" key={check.code}>
      <summary>{titles[check.code] ?? '確認項目'}：{states[check.status] ?? '未確認'}</summary>
      <p className="mt-2">{check.message}</p><p className="mt-2">次の作業：{check.next_action}</p>
    </details>)}
    {report.cf7_shape_issues.length > 0 && <div className="mt-3"><strong>CF7の未確認・未対応構成</strong><ul>{report.cf7_shape_issues.map(code => <li key={code}>{issues[code] ?? '追加確認が必要'}</li>)}</ul></div>}
    <p className="mt-3">{report.next_action}</p>
  </section>
}
