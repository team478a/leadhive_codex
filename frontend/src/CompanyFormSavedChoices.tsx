import { useEffect, useRef, useState } from 'react'

export type SavedChoiceStructure = {
  source_hash: string
  groups: { group_id: string; name: string; label: string; source_hash: string; required_observed: boolean; warnings: string[]; options: { option_id: string; label: string; value: string | null }[] }[]
}
const warnings: Record<string, string> = {
  PURPOSE_AND_RULE_UNCONFIRMED: '用途と選択条件は未確認です。元フォームで確認してください。',
  STORED_ORDER_ONLY: '選択肢は保存順です。現在のページの並び順は未確認です。',
  FIELD_IDENTITY_UNCERTAIN: '項目名が不明、または別の種類の欄と重複しています。',
  REPEATED_SAVED_FIELDS: '同名の保存項目をまとめた候補です。実際に同じグループか確認が必要です。',
  INCOMPLETE_OPTIONS: '選択値が不足しています。元フォームの確認が必要です。',
  AMBIGUOUS_VALUES: '同じ選択値が複数あります。安全に選択内容を固定できません。',
  CONSENT_REVIEW_REQUIRED: '同意に関する項目です。業務内容の選択とは別に、人による内容確認が必要です。',
}

export function CompanyFormSavedChoices({ profileId, structure }: { profileId: string; structure: SavedChoiceStructure | null }) {
  const previous = useRef<{ profileId: string; hash: string; hasGroups: boolean } | null>(null)
  const [changed, setChanged] = useState(false)
  useEffect(() => {
    if (!structure) return
    if (previous.current?.profileId !== profileId) setChanged(false)
    else if (previous.current.hash !== structure.source_hash && (previous.current.hasGroups || structure.groups.length > 0)) setChanged(true)
    previous.current = { profileId, hash: structure.source_hash, hasGroups: structure.groups.length > 0 }
  }, [profileId, structure])
  if (!structure || (structure.groups.length === 0 && !changed)) return null
  return <section className="mt-4" aria-label="同名チェック項目の確認資料">
    <h3>複数選択の確認資料</h3>
    <p className="notice mt-2">保存済みの選択肢をまとめた資料です。ここでは選択の保存・同意・承認・送信は行いません。</p>
    {changed && <p className="notice mt-3" role="status">以前表示した項目・選択肢・フォーム構造から変更があります。元フォームで再確認してください。</p>}
    {structure.groups.length === 0 && <p className="muted mt-3">現在の保存情報には、複数選択の候補がありません。</p>}
    {structure.groups.map(group => <article className="panel mt-3" key={`${group.group_id}:${group.source_hash}`}>
      <strong className="break-all">{group.label || group.name || '名称不明'}</strong>
      <p className="muted text-sm mt-2">項目名：{group.name || '未記録'} ／ 保存済み選択肢：{group.options.length}件</p>
      <p className="mt-2">{group.required_observed ? '必須の表示を観測していますが、グループの選択条件は未確認です。' : '必須条件は保存情報だけでは確定できません。'}</p>
      <ol className="mt-3">{group.options.map(option => <li className="break-all" key={option.option_id}>
        {option.label || option.value || '名称不明'}{option.label && option.label !== option.value && <span className="muted text-sm">（選択値：{option.value ?? '未記録'}）</span>}
      </li>)}</ol>
      <ul className="muted text-sm mt-3">{group.warnings.map(code => <li key={code}>{warnings[code] ?? '追加の確認が必要です。'}</li>)}</ul>
    </article>)}
  </section>
}
