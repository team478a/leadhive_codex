type GuideDestination = 'collection' | 'results' | 'settings'

export function OnboardingGuide({
  open,
  projectCount,
  totalCompanies,
  isAdmin,
  onClose,
  onCreateProject,
  onNavigate,
}: {
  open: boolean
  projectCount: number
  totalCompanies: number
  isAdmin: boolean
  onClose: () => void
  onCreateProject: () => void
  onNavigate: (destination: GuideDestination) => void
}) {
  if (!open) return null

  const hasProject = projectCount > 0
  const hasCompanies = totalCompanies > 0
  const nextAction = !hasProject
    ? { label: '収集ターゲットを設定する', action: onCreateProject }
    : !hasCompanies
      ? { label: '企業を集める', action: () => onNavigate('collection') }
      : { label: '収集結果を確認する', action: () => onNavigate('results') }

  return <div className="guide-backdrop" role="presentation">
    <section className="guide-dialog" role="dialog" aria-modal="true" aria-labelledby="guide-title">
      <div className="guide-header">
        <div>
          <p className="eyebrow">QUICK START</p>
          <h2 id="guide-title">3ステップで始めましょう</h2>
          <p className="muted mt-2">まずリストを集めます。DM準備・承認・送信は、別の「営業作業」メニューで行います。</p>
        </div>
        <button type="button" className="guide-close" aria-label="使い方ガイドを閉じる" onClick={onClose}>×</button>
      </div>

      <ol className="guide-steps">
        <li className={hasProject ? 'guide-step completed' : 'guide-step current'}>
          <span className="guide-step-number">{hasProject ? '✓' : '1'}</span>
          <div>
            <div className="guide-step-title"><strong>収集ターゲットを設定</strong>{hasProject && <span className="badge">完了</span>}</div>
            <p className="muted">対象・地域とリスト名を保存します。サービスURLから対象の提案もできます。</p>
          </div>
        </li>
        <li className={hasCompanies ? 'guide-step completed' : hasProject ? 'guide-step current' : 'guide-step'}>
          <span className="guide-step-number">{hasCompanies ? '✓' : '2'}</span>
          <div>
            <div className="guide-step-title"><strong>企業を集める</strong>{hasCompanies && <span className="badge">完了</span>}</div>
            <p className="muted">キーワード・都道府県・目標件数で検索するか、URL・CSVを取り込みます。</p>
          </div>
        </li>
        <li className={hasCompanies ? 'guide-step current' : 'guide-step'}>
          <span className="guide-step-number">3</span>
          <div>
            <div className="guide-step-title"><strong>収集結果を確認する</strong></div>
            <p className="muted">集まった候補が対象に合うか確認します。営業担当は同じプロジェクトを選び、DM準備へ進めます。</p>
          </div>
        </li>
      </ol>

      <div className="guide-tip">
        <strong>はじめはAPIキー不要です</strong>
        <p>URL入力またはCSV取込なら、外部サービスを設定せずに試せます。</p>
        {isAdmin && <button type="button" className="guide-link" onClick={() => onNavigate('settings')}>外部サービスの設定を見る</button>}
      </div>

      <div className="guide-actions">
        <button type="button" className="secondary" onClick={onClose}>あとで見る</button>
        <button type="button" onClick={nextAction.action}>{nextAction.label}</button>
      </div>
    </section>
  </div>
}
