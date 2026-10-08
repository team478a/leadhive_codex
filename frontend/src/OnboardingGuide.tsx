type GuideDestination = 'collection' | 'companies' | 'settings'

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
    ? { label: '最初のプロジェクトを作る', action: onCreateProject }
    : !hasCompanies
      ? { label: '企業を集める', action: () => onNavigate('collection') }
      : { label: '企業一覧を見る', action: () => onNavigate('companies') }

  return <div className="guide-backdrop" role="presentation">
    <section className="guide-dialog" role="dialog" aria-modal="true" aria-labelledby="guide-title">
      <div className="guide-header">
        <div>
          <p className="eyebrow">QUICK START</p>
          <h2 id="guide-title">3ステップで始めましょう</h2>
          <p className="muted mt-2">まずは企業を1社登録するところまで進めれば、LeadHiveの基本操作を確認できます。</p>
        </div>
        <button type="button" className="guide-close" aria-label="使い方ガイドを閉じる" onClick={onClose}>×</button>
      </div>

      <ol className="guide-steps">
        <li className={hasProject ? 'guide-step completed' : 'guide-step current'}>
          <span className="guide-step-number">{hasProject ? '✓' : '1'}</span>
          <div>
            <div className="guide-step-title"><strong>プロジェクトを作る</strong>{hasProject && <span className="badge">完了</span>}</div>
            <p className="muted">標準プロファイルを選び、案件名・提案内容・対象地域を入力します。</p>
          </div>
        </li>
        <li className={hasCompanies ? 'guide-step completed' : hasProject ? 'guide-step current' : 'guide-step'}>
          <span className="guide-step-number">{hasCompanies ? '✓' : '2'}</span>
          <div>
            <div className="guide-step-title"><strong>企業を集める</strong>{hasCompanies && <span className="badge">完了</span>}</div>
            <p className="muted">最初は会社URLを1件貼る方法が簡単です。検索やCSV取込も利用できます。</p>
          </div>
        </li>
        <li className={hasCompanies ? 'guide-step current' : 'guide-step'}>
          <span className="guide-step-number">3</span>
          <div>
            <div className="guide-step-title"><strong>企業一覧で確認する</strong></div>
            <p className="muted">企業情報・連絡先・優先度を確認し、営業対象を決めます。</p>
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
