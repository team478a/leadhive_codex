import type { AnalysisRefreshSchedule, Company, DataQuality, DuplicateCandidate } from './types'

type Props = {
  quality: DataQuality | null
  staleDays: number
  busy: boolean
  refreshSchedule: AnalysisRefreshSchedule | null
  refreshInterval: number
  refreshStaleDays: number
  refreshBatchLimit: number
  duplicates: DuplicateCandidate[]
  onStaleDaysChange: (value: number) => void
  onReanalyze: () => void
  onRefreshIntervalChange: (value: number) => void
  onRefreshStaleDaysChange: (value: number) => void
  onRefreshBatchLimitChange: (value: number) => void
  onSaveRefreshSchedule: (active?: boolean) => void
  onRunRefreshSchedule: () => void
  onDeleteRefreshSchedule: () => void
  onMerge: (primary: Company, duplicate: Company) => void
}

export function CompanyQualityPanels({ quality, staleDays, busy, refreshSchedule, refreshInterval, refreshStaleDays, refreshBatchLimit, duplicates, onStaleDaysChange, onReanalyze, onRefreshIntervalChange, onRefreshStaleDaysChange, onRefreshBatchLimitChange, onSaveRefreshSchedule, onRunRefreshSchedule, onDeleteRefreshSchedule, onMerge }: Props) {
  return <>
    {quality && <section className="panel mt-6"><div className="flex flex-wrap items-center justify-between gap-4"><div><h2>データ品質</h2><p className="muted mt-2 text-sm">欠損情報とWeb解析の更新状況を確認します。</p></div><div className="flex flex-wrap items-end gap-2"><label className="field mb-0">再解析期限（日）<input className="max-w-32" type="number" min={1} max={3650} value={staleDays} onChange={e => onStaleDaysChange(Number(e.target.value))} /></label><button disabled={busy || quality.reanalyzable === 0} onClick={onReanalyze}>失敗・期限切れを再解析</button></div></div><div className="grid gap-3 mt-5 sm:grid-cols-2 xl:grid-cols-4">{[['Webサイトなし', quality.missing_website], ['住所なし', quality.missing_address], ['電話なし', quality.missing_phone], ['メールなし', quality.missing_email], ['連絡先なし', quality.missing_contact], ['解析失敗', quality.failed_analysis], [`${quality.stale_days}日超過`, quality.stale_analysis], ['再解析対象', quality.reanalyzable]].map(([label, value]) => <div className="metric" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div></section>}
    <section className="panel mt-6"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2>自動再解析</h2><p className="muted mt-2 text-sm">解析失敗または期限切れの企業情報を定期的に更新します。</p></div>{refreshSchedule && <span className="badge">{refreshSchedule.active ? '有効' : '停止中'}</span>}</div><div className="filter-grid mt-4"><label className="field">実行間隔（時間）<input type="number" min={1} max={720} value={refreshInterval} onChange={e => onRefreshIntervalChange(Number(e.target.value))} /></label><label className="field">期限切れ判定（日）<input type="number" min={1} max={3650} value={refreshStaleDays} onChange={e => onRefreshStaleDaysChange(Number(e.target.value))} /></label><label className="field">1回の最大件数<input type="number" min={1} max={100} value={refreshBatchLimit} onChange={e => onRefreshBatchLimitChange(Number(e.target.value))} /></label></div>{refreshSchedule && <><p className="muted text-sm">次回 {new Date(refreshSchedule.next_run_at).toLocaleString('ja-JP')}</p>{refreshSchedule.last_enqueued_at && <p className="muted text-sm">最終登録 {new Date(refreshSchedule.last_enqueued_at).toLocaleString('ja-JP')}</p>}{refreshSchedule.last_error && <p className="error mt-2 mb-0">{refreshSchedule.last_error}</p>}</>}<div className="actions"><button disabled={busy} onClick={() => onSaveRefreshSchedule()}>{refreshSchedule ? '設定を保存' : '自動再解析を設定'}</button>{refreshSchedule && <><button className="secondary" disabled={busy} onClick={onRunRefreshSchedule}>今すぐ対象を登録</button><button className="secondary" disabled={busy} onClick={() => onSaveRefreshSchedule(!refreshSchedule.active)}>{refreshSchedule.active ? '停止' : '再開'}</button><button className="danger" disabled={busy} onClick={onDeleteRefreshSchedule}>削除</button></>}</div></section>
    <section className="panel mt-6"><div className="flex items-center justify-between gap-3"><div><h2>重複候補</h2><p className="muted mt-2 text-sm">メール・電話・会社名と住所の一致を確認して統合します。</p></div><span className="badge">{duplicates.length} 組</span></div>{duplicates.length === 0 ? <p className="muted mt-4">重複候補はありません。</p> : duplicates.map(item => <article className="job-row block" key={`${item.left.id}-${item.right.id}`}><p className="muted text-sm">一致：{item.reasons.map(reason => reason === 'email' ? 'メール' : reason === 'phone' ? '電話' : '会社名＋住所').join(' / ')}</p><div className="grid gap-3 mt-3 sm:grid-cols-2"><div><strong>{item.left.company_name}</strong><p className="muted text-sm">{item.left.email || item.left.phone || item.left.address}</p><button disabled={busy} className="secondary mt-2" onClick={() => onMerge(item.left, item.right)}>こちらへ統合</button></div><div><strong>{item.right.company_name}</strong><p className="muted text-sm">{item.right.email || item.right.phone || item.right.address}</p><button disabled={busy} className="secondary mt-2" onClick={() => onMerge(item.right, item.left)}>こちらへ統合</button></div></div></article>)}</section>
  </>
}
