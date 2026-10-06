import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import type { HumanDestinationChoice } from './DestinationChoice'

type Template = { id: string; name: string; channel: string; subject: string; body: string; hash: string }
type Preparation = { id: string; status: string; reason: string | null; choice_version: number; expires_at: string; prepared_by_user_id: string; snapshot: {
  subject: string; body: string; destination: { type: string; destination: string }
  template: { name: string }; evidence: { source_url: string; fact: string; evidence_excerpt: string; observed_at: string; confidence: string }
} }
type Options = { context_hash: string; can_prepare: boolean; human_choice: HumanDestinationChoice & { active_destination: { id: string; type: string; destination: string; payload_hash: string } | null }; templates: Template[]; preparations: Preparation[] }
const reasons: Record<string, string> = { PREPARATION_EXPIRED: '準備記録の期限切れ', DESTINATION_CHOICE_CHANGED: '窓口選択・安全条件の変更', DESTINATION_CHANGED: '宛先情報の変更', SALES_CONTEXT_CHANGED: '営業条件の変更', TEMPLATE_CHANGED: 'テンプレートの変更・削除' }

export function DmPreparationPanel({ companyId, projectId }: { companyId: string; projectId: string }) {
  const [data, setData] = useState<Options | null>(null)
  const [revision, setRevision] = useState(0)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [templateId, setTemplateId] = useState('')
  const [source, setSource] = useState('')
  const [fact, setFact] = useState('')
  const [excerpt, setExcerpt] = useState('')
  const [observed, setObserved] = useState(false)
  const [name, setName] = useState('')
  const [subject, setSubject] = useState('')
  const [base, setBase] = useState('')
  useEffect(() => {
    let active = true
    api<Options>(`/companies/${companyId}/dm-preparation`).then(value => { if (active) { setData(value) } }).catch(e => { if (active) { setData(null); setError(errorMessage(e)) } })
    return () => { active = false }
  }, [companyId, revision])
  const choice = data?.human_choice
  const selected = choice?.state === 'CURRENT' ? choice.active_destination : null
  const templates = data?.templates.filter(t => t.channel === selected?.type) ?? []
  const template = templates.find(t => t.id === templateId)
  async function save(createTemplate: boolean) {
    if (!data || !selected) return
    setBusy(true); setError('')
    try {
      if (createTemplate) {
        const result = await api<{ id: string }>(`/projects/${projectId}/outreach-templates`, 'POST', {
          name, channel: selected.type, subject: selected.type === 'email' ? subject : '',
          body: '{{company_name}} ご担当者様\n\n{{personalization}}\n\n' + base.trim(),
        })
        setTemplateId(result.id); setName(''); setSubject(''); setBase('')
      } else if (template) {
        await api(`/companies/${companyId}/dm-preparation`, 'POST', {
          template_id: template.id, expected_template_hash: template.hash,
          expected_context_hash: data.context_hash, expected_destination_hash: selected.payload_hash,
          expected_choice_version: choice?.version, source_url: source, fact,
          evidence_excerpt: excerpt, fact_observed: observed,
        })
        setObserved(false)
      }
      setRevision(v => v + 1)
    } catch (e) { setError(errorMessage(e)); setRevision(v => v + 1) } finally { setBusy(false) }
  }
  return <section className="mt-5 break-all" aria-label="根拠付きDM下書き準備">
    <h3>根拠付きDM下書き準備</h3>
    <p className="muted">選択した窓口と公開情報の根拠を固定して下書きを保存します。AI通信・サイト接続は行いません。根拠はHumanの確認記録で、独立した事実検証ではありません。送信者・フォーム入力値の確定前なので、DM READY・送信承認・送信には進みません。</p>
    {!selected && <p>有効な窓口を準備対象に選択すると、下書きを準備できます。</p>}
    {selected && data?.can_prepare && <>
      <p>対象窓口：{selected.type} / {selected.destination} / 選択版 {choice?.version}</p>
      <details><summary>基本文面テンプレートを作成</summary>
        <p>会社名と根拠付きの一文は自動で差し込みます。サービス説明・提案・CTA・署名を基本文面にまとめてください。</p>
        <label className="field">基本文面の名前<input value={name} maxLength={200} disabled={busy} onChange={e => setName(e.target.value)} /></label>
        {selected.type === 'email' && <label className="field">基本文面の件名<input value={subject} maxLength={300} disabled={busy} onChange={e => setSubject(e.target.value)} /></label>}
        <label className="field">サービス説明・提案・CTA・署名<textarea rows={6} value={base} maxLength={9000} disabled={busy} onChange={e => setBase(e.target.value)} /></label>
        <button className="secondary" disabled={busy || !name.trim() || !base.trim() || (selected.type === 'email' && !subject.trim())} onClick={() => void save(true)}>基本文面を登録</button>
      </details>
      <label className="field">DMの基本文面<select value={templateId} disabled={busy} onChange={e => setTemplateId(e.target.value)}><option value="">選択してください</option>{templates.map(t => <option key={t.id} value={t.id}>{t.name}{t.body.includes('{{personalization}}') ? '' : '（個別化差し込み未対応）'}</option>)}</select></label>
      {template && <details><summary>使用する基本文面を確認</summary><pre className="whitespace-pre-wrap">{template.subject} {'\n'}{template.body}</pre></details>}
      <label className="field">個別情報の根拠URL<input value={source} maxLength={2048} disabled={busy} onChange={e => { setSource(e.target.value); setObserved(false) }} placeholder="公式サイト内の公開ページ" /></label>
      <label className="field">確認した公開情報の引用<textarea value={excerpt} maxLength={2000} disabled={busy} onChange={e => { setExcerpt(e.target.value); setObserved(false) }} /></label>
      <label className="field">DMに使う事実<input value={fact} maxLength={500} disabled={busy} onChange={e => { setFact(e.target.value); setObserved(false) }} placeholder="上の引用に含まれる事実を10文字以上で入力" /></label>
      <label className="checkbox-row"><input type="checkbox" checked={observed} disabled={busy} onChange={e => setObserved(e.target.checked)} />この公式ページで事実と引用を確認しました</label>
      <button disabled={busy || !template || !observed || !source.trim() || fact.trim().length < 10 || !excerpt.includes(fact.trim())} onClick={() => void save(false)}>根拠付き下書きを保存</button>
    </>}
    {error && <p role="alert">{error}</p>}
    {data?.preparations.map(p => <article className="mt-4" key={p.id} aria-label="保存した根拠付き下書き">
      <p role="status">{p.status === 'DRAFT_PREPARED' ? '下書き準備済み' : '要再確認'}（{p.status}）{p.reason && `：${reasons[p.reason] ?? p.reason}`}</p>
      <p>宛先：{p.snapshot.destination.type} / {p.snapshot.destination.destination} / 選択版 {p.choice_version}</p>
      <p>基本文面：{p.snapshot.template.name} / 確認者ID：{p.prepared_by_user_id} / 期限：{new Date(p.expires_at).toLocaleString('ja-JP')}</p>
      {p.snapshot.subject && <p>件名：{p.snapshot.subject}</p>}
      <pre className="whitespace-pre-wrap">{p.snapshot.body}</pre>
      <p>使った事実：{p.snapshot.evidence.fact}</p>
      <p>根拠：<a href={p.snapshot.evidence.source_url} target="_blank" rel="noreferrer">{p.snapshot.evidence.source_url}</a> / Human確認日時：{new Date(p.snapshot.evidence.observed_at).toLocaleString('ja-JP')}</p>
      <blockquote>{p.snapshot.evidence.evidence_excerpt}</blockquote>
    </article>)}
    {data && <p className="muted">最新10件の準備記録を表示しています。</p>}
  </section>
}
