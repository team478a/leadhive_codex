import type { CompanyFilterValues, SavedCompanyFilter } from './types'

type Props = {
  items: SavedCompanyFilter[]
  currentFilters: CompanyFilterValues
  filterName: string
  editingId: string
  editingName: string
  busy: boolean
  onFilterNameChange: (value: string) => void
  onEditingNameChange: (value: string) => void
  onSave: () => void
  onApply: (filters: CompanyFilterValues) => void
  onOverwrite: (item: SavedCompanyFilter) => void
  onStartRename: (item: SavedCompanyFilter) => void
  onCancelRename: () => void
  onRename: (item: SavedCompanyFilter) => void
  onDelete: (item: SavedCompanyFilter) => void
}

export function CompanySavedFiltersPanel({ items, filterName, editingId, editingName, busy, onFilterNameChange, onEditingNameChange, onSave, onApply, onOverwrite, onStartRename, onCancelRename, onRename, onDelete }: Props) {
  return <section className="panel mt-6"><div className="flex flex-wrap items-end justify-between gap-4"><div><h2>保存フィルター</h2><p className="muted mt-2 text-sm">適用中の絞り込み条件を名前付きで保存します。</p></div><div className="flex flex-wrap items-end gap-2"><label className="field mb-0">フィルター名<input value={filterName} maxLength={200} onChange={e => onFilterNameChange(e.target.value)} placeholder="例：佐藤担当の期限超過" /></label><button disabled={busy || !filterName.trim()} onClick={onSave}>現在の条件を保存</button></div></div>{items.length === 0 ? <p className="muted mt-4">保存済みフィルターはありません。</p> : <div className="grid gap-3 mt-4 sm:grid-cols-2 xl:grid-cols-3">{items.map(item => <article className="job-row block" key={item.id}>{editingId === item.id ? <><label className="field">保存名<input aria-label={`${item.name}の保存名`} maxLength={200} value={editingName} onChange={e => onEditingNameChange(e.target.value)} /></label><div className="flex gap-2"><button disabled={busy || !editingName.trim()} onClick={() => onRename(item)}>名前を保存</button><button className="secondary" onClick={onCancelRename}>キャンセル</button></div></> : <><strong>{item.name}</strong><div className="flex flex-wrap gap-2 mt-3"><button className="secondary" onClick={() => onApply(item.filters)}>適用</button><button className="secondary" disabled={busy} onClick={() => onOverwrite(item)}>現在の条件で上書き</button><button className="secondary" onClick={() => onStartRename(item)}>名前変更</button><button className="danger" disabled={busy} onClick={() => onDelete(item)}>削除</button></div></>}</article>)}</div>}</section>
}

