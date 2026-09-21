import type { AiReview, OutreachExperiment, OutreachExperimentResult, OutreachTemplate } from './types'

type AiReviewProps = {
  review: AiReview | null
  verdict: 'correct' | 'incorrect'
  note: string
  busy: boolean
  onVerdictChange: (value: 'correct' | 'incorrect') => void
  onNoteChange: (value: string) => void
  onSave: () => void
}

export function CompanyAiReviewPanel({ review, verdict, note, busy, onVerdictChange, onNoteChange, onSave }: AiReviewProps) {
  return <section className="panel mt-7"><h2>AI判定レビュー</h2><p className="muted mt-2 text-sm">実際の営業対象としての妥当性を記録し、検索語ごとの精度改善に使います。</p><div className="detail-grid mt-4"><label className="field">判定<select value={verdict} onChange={e => onVerdictChange(e.target.value as 'correct' | 'incorrect')}><option value="correct">正しい</option><option value="incorrect">誤り</option></select></label><label className="field">レビュー理由<textarea rows={3} maxLength={5000} value={note} onChange={e => onNoteChange(e.target.value)} placeholder="例：対象業種ではない、決裁者が明確" /></label></div><div className="actions"><button disabled={busy} onClick={onSave}>レビューを保存</button></div>{review && <p className="muted text-sm mt-3">最終レビュー：{review.verdict === 'correct' ? '正しい' : '誤り'} / {new Date(review.updated_at).toLocaleString('ja-JP')}</p>}</section>
}

type ExperimentProps = {
  templates: OutreachTemplate[]
  experiments: OutreachExperiment[]
  results: OutreachExperimentResult[]
  hasSelectedDraft: boolean
  name: string
  templateA: string
  templateB: string
  experimentId: string
  busy: boolean
  onNameChange: (value: string) => void
  onTemplateAChange: (value: string) => void
  onTemplateBChange: (value: string) => void
  onExperimentChange: (value: string) => void
  onCreate: () => void
  onApply: () => void
}

export function CompanyExperimentPanel({ templates, experiments, results, hasSelectedDraft, name, templateA, templateB, experimentId, busy, onNameChange, onTemplateAChange, onTemplateBChange, onExperimentChange, onCreate, onApply }: ExperimentProps) {
  return <section className="panel mt-7"><h2>営業文面 A/Bテスト</h2><p className="muted mt-2 text-sm">同じ種別のテンプレートを2案用意し、企業IDで均等に割り当てます。送信後の返信・商談・成約を案ごとに比較します。</p><div className="detail-grid mt-4"><label className="field">テスト名<input maxLength={200} value={name} onChange={e => onNameChange(e.target.value)} placeholder="例：9月件名比較" /></label><label className="field">A案<select value={templateA} onChange={e => onTemplateAChange(e.target.value)}><option value="">選択してください</option>{templates.map(template => <option key={template.id} value={template.id}>{template.name}</option>)}</select></label><label className="field">B案<select value={templateB} onChange={e => onTemplateBChange(e.target.value)}><option value="">選択してください</option>{templates.map(template => <option key={template.id} value={template.id}>{template.name}</option>)}</select></label></div><div className="actions"><button disabled={busy || !name.trim() || !templateA || !templateB || templateA === templateB} onClick={onCreate}>A/Bテストを作成</button></div><div className="detail-grid mt-4"><label className="field">利用するA/Bテスト<select value={experimentId} onChange={e => onExperimentChange(e.target.value)}><option value="">選択してください</option>{experiments.filter(item => item.active).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><div className="actions self-end"><button className="secondary" disabled={busy || !hasSelectedDraft || !experimentId} onClick={onApply}>現在の文面へ均等割当を適用</button></div></div>{experimentId && <div className="company-table-wrap mt-4"><table className="company-table"><thead><tr><th>案</th><th>送信済み</th><th>返信</th><th>商談</th><th>成約</th><th>返信率</th></tr></thead><tbody>{results.map(item => <tr key={item.variant}><td>{item.variant}案</td><td>{item.delivered}</td><td>{item.replied}</td><td>{item.meetings}</td><td>{item.won}</td><td>{item.reply_rate}%</td></tr>)}</tbody></table></div>}</section>
}
