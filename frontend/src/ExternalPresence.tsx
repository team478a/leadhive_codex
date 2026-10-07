import { useState } from 'react'
import { api, errorMessage } from './api'

import { presenceGroups, presenceLabels, type PresencePlan } from './externalPresenceShared'

type Presence = {
  platform: string; status: 'FOUND' | 'NOT_FOUND' | 'NOT_CHECKED' | 'ERROR'
  url: string; source_url: string; observed_at: string | null; reason: string
}
const statusLabels = { FOUND: 'あり', NOT_FOUND: '調査で見つからず', NOT_CHECKED: '未調査', ERROR: '確認未完了' }

export function PresenceSearchControls({ value, onChange }: {
  value: PresencePlan; onChange: (value: PresencePlan) => void
}) {
  const active = Object.values(value.modes).filter(m => m !== 'AUTO').length
  return <details className="mt-4"><summary>追加で調べる情報（{active}項目・上限{value.max_extra_searches}検索）</summary>
    <p className="muted text-sm">検索中に見つかった情報は、設定に関係なく保存します。ONにした項目は、見つからなかった場合も追加で調査します。</p>
    <p className="muted text-sm">必須条件はOFFより優先します。予算不足・企業との関連不明は、条件を満たしたと扱いません。円換算費用は未算定です。</p>
    <div className="grid gap-3 sm:grid-cols-3">{Object.entries(presenceGroups).map(([group, platforms]) =>
      <label className="field" key={group}>{group}をまとめて設定<select aria-label={`${group}一括設定`} defaultValue="" onChange={e => {
        const mode = e.target.value as 'AUTO' | 'SEARCH'
        if (!mode) return
        const modes = { ...value.modes }
        for (const platform of platforms) if (modes[platform] !== 'REQUIRED') modes[platform] = mode
        onChange({ ...value, modes }); e.target.value = ''
      }}><option value="">選択してください</option><option value="AUTO">OFF：追加検索しない</option>
        <option value="SEARCH">ON：追加検索する</option></select></label>)}</div>
    <div className="grid gap-3 sm:grid-cols-2">{Object.entries(presenceLabels).map(([platform, label]) =>
      <label className="field" key={platform}>{label}<select aria-label={`${label}追加調査`}
        value={value.modes[platform] || 'AUTO'} onChange={e => onChange({ ...value,
          modes: { ...value.modes, [platform]: e.target.value as 'AUTO' | 'SEARCH' | 'REQUIRED' } })}>
        <option value="AUTO">OFF：発見済みのみ保存</option><option value="SEARCH">ON：未発見なら追加検索</option>
        <option value="REQUIRED">必須：存在を検証</option></select></label>)}</div>
    <label className="field">追加検索の上限<input aria-label="追加検索の上限" type="number" min={0} max={30}
      value={value.max_extra_searches} onChange={e => onChange({ ...value, max_extra_searches: Number(e.target.value) })} /></label>
  </details>
}

export function CompanyPresence({ companyId }: { companyId: string }) {
  const [rows, setRows] = useState<Presence[] | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function load() {
    if (busy) return
    setBusy(true); setError('')
    try { setRows(await api<Presence[]>(`/companies/${companyId}/external-presences`)) }
    catch (e) { setError(errorMessage(e)) }
    finally { setBusy(false) }
  }
  return <details className="mt-2" onToggle={e => { if (e.currentTarget.open && !rows && !busy) void load() }}>
    <summary>掲載媒体・SNS・求人</summary>{busy && <p>読込中…</p>}{error && <p role="alert">{error}<button onClick={() => void load()}>再読込</button></p>}
    {rows && ['SNS', '掲載媒体', '求人'].map((group, index) => <div key={group}><strong>{group}</strong><ul>
      {rows.filter(r => index === 0 ? ['INSTAGRAM', 'X', 'FACEBOOK', 'YOUTUBE', 'TIKTOK'].includes(r.platform) :
        index === 2 ? ['INDEED', 'KYUJIN_BOX'].includes(r.platform) :
          !['INSTAGRAM', 'X', 'FACEBOOK', 'YOUTUBE', 'TIKTOK', 'INDEED', 'KYUJIN_BOX'].includes(r.platform)).map(r =>
        <li key={r.platform}>{presenceLabels[r.platform]}：{r.status === 'FOUND' ?
          <a href={r.url} target="_blank" rel="noopener noreferrer">あり ↗</a> : statusLabels[r.status]}
          {r.observed_at && <span className="muted text-xs">（{new Date(r.observed_at).toLocaleDateString('ja-JP')}確認）</span>}
          {r.status === 'ERROR' && <span className="muted text-xs"> {r.reason === 'SEARCH_BUDGET_EXHAUSTED' ? '検索上限に到達' : '関連・取得を確認できません'}</span>}
        </li>)}</ul></div>)}
  </details>
}
