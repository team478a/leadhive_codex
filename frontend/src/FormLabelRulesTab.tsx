import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import { formMappedKeyLabels } from './formMappingLabels'
import type { FormMappedKey, OperationJob } from './types'

export type UnresolvedLabel = { normalized_label: string; field_type: string; form_count: number; example_labels: string[] }
type Rule = { id: string; normalized_label: string; field_type: string; mapped_key: FormMappedKey; recommended_value: string; status: 'ACTIVE' | 'RETIRED'; created_at: string; retired_at: string | null }
type AiSuggestion = { id: string; normalized_label: string; field_type: string; suggested_mapped_key: FormMappedKey | 'unknown'; confidence: number; sample_count: number; provider: string; model: string; status: 'ACTIVE' | 'ACCEPTED' | 'DISMISSED' | 'UNAVAILABLE'; reason: string }
type RulesResponse = { rules: Rule[]; ai_suggestions?: AiSuggestion[]; ai_available?: boolean; active_job: OperationJob | null; allowed_mapped_keys: FormMappedKey[] }
type Preview = { form_count: number; examples: { company_name: string; form_url: string }[] }

export function FormLabelRulesTab({ projectId, canWrite, unresolved, onChanged }: { projectId: string; canWrite: boolean; unresolved: UnresolvedLabel[]; onChanged: () => Promise<void> }) {
  const [data, setData] = useState<RulesResponse | null>(null)
  const [mapping, setMapping] = useState<Record<string, FormMappedKey>>({})
  const [recommended, setRecommended] = useState<Record<string, string>>({})
  const [busyKey, setBusyKey] = useState(''); const [error, setError] = useState(''); const [notice, setNotice] = useState('')
  const load = useCallback(async () => {
    try { setData(await api<RulesResponse>(`/projects/${projectId}/form-label-rules`)) }
    catch (cause) { setError(errorMessage(cause)) }
  }, [projectId])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (!data) return
    setMapping(current => {
      const next = { ...current }
      for (const suggestion of data.ai_suggestions ?? []) {
        if (suggestion.status !== 'ACTIVE') continue
        const key = `${suggestion.normalized_label}\u0000${suggestion.field_type}`
        if (!next[key]) next[key] = suggestion.suggested_mapped_key as FormMappedKey
      }
      return next
    })
  }, [data])
  useEffect(() => {
    if (!data?.active_job || !['queued', 'running'].includes(data.active_job.status)) return
    const timer = window.setInterval(() => {
      api<RulesResponse>(`/projects/${projectId}/form-label-rules`).then(async result => {
        const completed = Boolean(data.active_job) && !result.active_job
        setData(result)
        if (completed) await onChanged()
      }).catch(cause => setError(errorMessage(cause)))
    }, 2000)
    return () => window.clearInterval(timer)
  }, [data?.active_job, onChanged, projectId])
  const rowKey = (row: UnresolvedLabel) => `${row.normalized_label}\u0000${row.field_type}`
  const openSuggestion = useCallback((row: UnresolvedLabel) => data?.ai_suggestions?.find(suggestion => suggestion.normalized_label === row.normalized_label && suggestion.field_type === row.field_type && ['ACTIVE', 'UNAVAILABLE'].includes(suggestion.status)), [data?.ai_suggestions])
  const requestAi = useCallback(async (row: UnresolvedLabel) => {
    const key = rowKey(row)
    if (busyKey) return
    setBusyKey(`ai:${key}`); setError(''); setNotice('')
    try {
      const suggestion = await api<AiSuggestion>(`/projects/${projectId}/form-label-rules/ai-suggestions`, 'POST', { normalized_label: row.normalized_label, field_type: row.field_type })
      if (suggestion.status === 'ACTIVE') {
        setMapping(current => ({ ...current, [key]: suggestion.suggested_mapped_key as FormMappedKey }))
        setNotice('安全条件を満たすAI候補を表示しました。保存するまでは項目に反映されません。')
      } else {
        setNotice('安全条件を満たすAI候補はありませんでした。人が対応先を選んでください。')
      }
      await load()
    } catch (cause) { setError(errorMessage(cause)) } finally { setBusyKey('') }
  }, [busyKey, load, projectId])
  const dismissAi = useCallback(async (suggestion: AiSuggestion) => {
    setBusyKey(`ai:${suggestion.id}`); setError(''); setNotice('')
    try {
      await api(`/projects/${projectId}/form-label-rules/ai-suggestions/${suggestion.id}/dismiss`, 'POST')
      setNotice('AI候補を破棄しました。項目への反映はありません。')
      await load()
    } catch (cause) { setError(errorMessage(cause)) } finally { setBusyKey('') }
  }, [load, projectId])
  const save = useCallback(async (row: UnresolvedLabel) => {
    const key = rowKey(row); const mappedKey = mapping[key]
    if (!mappedKey || busyKey) return
    setBusyKey(key); setError(''); setNotice('')
    try {
      const query = new URLSearchParams({ normalized_label: row.normalized_label, field_type: row.field_type })
      const preview = await api<Preview>(`/projects/${projectId}/form-label-rules/preview?${query.toString()}`)
      const examples = preview.examples.map(item => `・${item.company_name}\n  ${item.form_url}`).join('\n')
      const confirmed = window.confirm(`このルールを保存し、対象${preview.form_count}フォームへの反映を開始します。\n\n確認例（最大5件）\n${examples || '対象例はありません'}\n\n送信・承認は行いません。`)
      if (!confirmed) return
      const suggestion = openSuggestion(row)
      await api(`/projects/${projectId}/form-label-rules`, 'POST', { normalized_label: row.normalized_label, field_type: row.field_type, mapped_key: mappedKey, recommended_value: recommended[key] || '', ai_suggestion_id: suggestion?.status === 'ACTIVE' && suggestion.suggested_mapped_key === mappedKey ? suggestion.id : null })
      setNotice('項目名ルールを保存し、バックグラウンド反映を開始しました。')
      await load()
    } catch (cause) { setError(errorMessage(cause)) } finally { setBusyKey('') }
  }, [busyKey, load, mapping, openSuggestion, projectId, recommended])
  const retire = useCallback(async (rule: Rule) => {
    if (!window.confirm(`「${rule.normalized_label}」のルールを無効にします。反映済みの項目は保持されます。`)) return
    setBusyKey(rule.id); setError(''); setNotice('')
    try { await api(`/projects/${projectId}/form-label-rules/${rule.id}/retire`, 'POST'); setNotice('ルールを無効にしました。反映済みの項目は保持しています。'); await load() }
    catch (cause) { setError(errorMessage(cause)) } finally { setBusyKey('') }
  }, [load, projectId])
  const reset = useCallback(async (rule: Rule) => {
    if (!window.confirm(`「${rule.normalized_label}」のルールで決めた項目だけを未決定に戻します。手動・ポリシーの決定には触れません。`)) return
    setBusyKey(rule.id); setError(''); setNotice('')
    try { await api(`/projects/${projectId}/form-label-rules/${rule.id}/reset`, 'POST'); setNotice('このルール由来の項目を未決定に戻す処理を開始しました。'); await load() }
    catch (cause) { setError(errorMessage(cause)) } finally { setBusyKey('') }
  }, [load, projectId])
  const active = data?.rules.filter(rule => rule.status === 'ACTIVE') ?? []
  const retired = data?.rules.filter(rule => rule.status === 'RETIRED') ?? []
  return <section className="mt-4 border-t pt-4" aria-label="項目名ごとのルール">
    <h3>項目名ごとにまとめて決める</h3><p className="muted mt-2 text-sm">辞書で決まらなかった必須項目だけに反映します。手動・同意ポリシー・辞書の決定は上書きしません。</p><p className="muted mt-2 text-sm">AI候補は保存済みの項目名・型・選択肢だけで作成します。全例一致・高確信度・型整合を満たした候補だけを表示し、人がルールを保存するまで反映しません。</p>
    {error && <p role="alert" className="error mt-3">{error}</p>}{notice && <p role="status" className="mt-3">{notice}</p>}
    {data?.active_job && <p role="status" className="mt-3">処理中 {data.active_job.processed_count}/{data.active_job.total_count}フォーム（成功 {data.active_job.success_count}・失敗 {data.active_job.failed_count}）</p>}
    <div className="company-table-wrap mt-4"><table className="company-table"><thead><tr><th>項目名・型</th><th>フォーム数・例</th><th>対応先</th><th>操作</th></tr></thead><tbody>{unresolved.map(row => {
      const key = rowKey(row); const options = data?.allowed_mapped_keys ?? []
      const suggestion = openSuggestion(row)
      return <tr key={key}><td><strong>{row.normalized_label || '名称不明'}</strong><p className="muted">{row.field_type}</p></td><td>{row.form_count}フォーム<p className="muted text-xs">{row.example_labels.join(' / ')}</p></td><td><select aria-label={`${row.normalized_label}の対応先`} disabled={!canWrite || Boolean(data?.active_job)} value={mapping[key] || ''} onChange={event => setMapping(current => ({ ...current, [key]: event.target.value as FormMappedKey }))}><option value="">選択してください</option>{options.map(mappedKey => <option key={mappedKey} value={mappedKey}>{formMappedKeyLabels[mappedKey]}</option>)}</select>{['select', 'radio'].includes(row.field_type) && <input className="mt-2" aria-label={`${row.normalized_label}の既定値`} placeholder="既定の選択値（任意）" value={recommended[key] || ''} onChange={event => setRecommended(current => ({ ...current, [key]: event.target.value }))} />}{suggestion?.status === 'ACTIVE' && <p className="mt-2 text-sm">AI候補: <strong>{formMappedKeyLabels[suggestion.suggested_mapped_key as FormMappedKey] || suggestion.suggested_mapped_key}</strong>（確信度 {Math.round(suggestion.confidence * 100)}%・{suggestion.sample_count}例一致）</p>}{suggestion?.status === 'UNAVAILABLE' && <p className="muted mt-2 text-sm">AI候補なし: {suggestion.reason}</p>}</td><td>{!suggestion && <button type="button" className="secondary mb-2" disabled={!canWrite || !data?.ai_available || Boolean(data?.active_job) || busyKey === `ai:${key}`} onClick={() => void requestAi(row)}>{busyKey === `ai:${key}` ? 'AI候補を確認中…' : 'AI候補を表示'}</button>}{suggestion && <button type="button" className="secondary mb-2" disabled={!canWrite || Boolean(data?.active_job) || busyKey === `ai:${suggestion.id}`} onClick={() => void dismissAi(suggestion)}>AI候補を破棄</button>}{data?.ai_available === false && <p className="muted text-xs">OpenAI APIキーが未設定です。</p>}<button type="button" disabled={!canWrite || !mapping[key] || Boolean(data?.active_job) || busyKey === key} onClick={() => void save(row)}>このルールを保存して{row.form_count}フォームに反映</button></td></tr>
    })}</tbody></table></div>
    {!unresolved.length && <p className="mt-3">未解決の必須項目名はありません。</p>}
    <h3 className="mt-5">保存済みのルール</h3>
    {[...active, ...retired].map(rule => <div className="border-t py-3" key={rule.id}><strong>{rule.normalized_label}（{rule.field_type}）→ {formMappedKeyLabels[rule.mapped_key] || rule.mapped_key}</strong>{rule.recommended_value && <p className="muted">既定値: {rule.recommended_value}</p>}<p className="muted text-xs">{rule.status === 'ACTIVE' ? '有効' : '無効'}</p>{canWrite && rule.status === 'ACTIVE' && <button className="secondary mt-2 mr-2" disabled={Boolean(data?.active_job) || busyKey === rule.id} onClick={() => void retire(rule)}>無効にする</button>}{canWrite && <button className="secondary mt-2" disabled={Boolean(data?.active_job) || busyKey === rule.id} onClick={() => void reset(rule)}>このルールで決めた項目を未決定に戻す</button>}</div>)}
    {!data?.rules.length && <p className="mt-3">保存済みのルールはありません。</p>}
    {!canWrite && <p className="muted mt-3 text-sm">閲覧のみです。ルールの保存・変更は編集者以上が行えます。</p>}
  </section>
}
