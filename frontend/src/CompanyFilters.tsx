import type { Dispatch, SetStateAction } from 'react'
import type { CompanyFilterValues, Project } from './types'
import { sourceNames, statusNames } from './companyPageShared'

type Props = {
  projects: Project[]
  projectId: string
  draft: CompanyFilterValues
  setDraft: Dispatch<SetStateAction<CompanyFilterValues>>
  onProjectChange: (projectId: string) => void
  onReset: () => void
  onApply: () => void
  onDownload: () => void
}

export function CompanyFilters({ projects, projectId, draft, setDraft, onProjectChange, onReset, onApply, onDownload }: Props) {
  return <section className="panel"><div className="filter-grid">
    <label className="field">プロジェクト<select value={projectId} onChange={e => onProjectChange(e.target.value)}>{projects.map(project => <option key={project.id} value={project.id}>{project.project_name}</option>)}</select></label>
    <label className="field">キーワード<input value={draft.keyword} onChange={e => setDraft({ ...draft, keyword: e.target.value })} placeholder="会社名・業種・AI要約" /></label>
    <label className="field">ランク<select value={draft.rank} onChange={e => setDraft({ ...draft, rank: e.target.value })}><option value="">すべて</option>{['A', 'B', 'C', '対象外'].map(value => <option key={value}>{value}</option>)}</select></label>
    <label className="field">最低スコア<input type="number" min="0" max="100" value={draft.minScore} onChange={e => setDraft({ ...draft, minScore: e.target.value })} /></label>
    <label className="field">地域<input value={draft.region} onChange={e => setDraft({ ...draft, region: e.target.value })} /></label>
    <label className="field">営業状況<select value={draft.status} onChange={e => setDraft({ ...draft, status: e.target.value })}><option value="">すべて</option>{Object.entries(statusNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    <label className="field">収集元<select value={draft.source} onChange={e => setDraft({ ...draft, source: e.target.value })}><option value="">すべて</option>{Object.entries(sourceNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    <label className="field">担当者<input value={draft.assignee} onChange={e => setDraft({ ...draft, assignee: e.target.value })} /></label>
    <label className="field">フォロー期限<select value={draft.followup} onChange={e => setDraft({ ...draft, followup: e.target.value })}><option value="">すべて</option><option value="overdue">期限超過</option><option value="today">本日</option><option value="upcoming">今後</option><option value="unset">未設定</option></select></label>
    <label className="field">並び順<select value={draft.sort} onChange={e => setDraft({ ...draft, sort: e.target.value })}><option value="score_desc">スコア順</option><option value="newest">新しい順</option><option value="company_name">会社名順</option></select></label>
  </div><div className="flex flex-wrap justify-end gap-2"><button className="secondary" onClick={onReset}>リセット</button><button onClick={onApply}>絞り込む</button><button className="secondary" onClick={onDownload}>CSV出力</button></div></section>
}
