import { useRef, useState } from 'react'
import { api, errorMessage } from './api'

export type TargetOption = {
  name: string; reason: string; search_keywords: string[]; positive_keywords: string[]
  negative_keywords: string[]; exclusion_keywords: string[]
}
type Proposal = {
  service_summary: string; evidence_quotes: string[]; targets: TargetOption[]; limitations: string[]
  source_url: string; observed_at: string; input_tokens: number | null; output_tokens: number | null
}

export function TargetProfileAssistant({ onApply }: {
  onApply: (target: TargetOption, summary: string, source: string) => void
}) {
  const [url, setUrl] = useState('')
  const [goal, setGoal] = useState('')
  const [targetMode, setTargetMode] = useState('customers')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [selected, setSelected] = useState(0)
  const [applied, setApplied] = useState(false)
  const revision = useRef(0)
  function changed() { revision.current++; setProposal(null); setApplied(false); setError('') }
  async function suggest() {
    let parsed: URL
    try {
      parsed = new URL(url)
      if (!['https:', 'http:'].includes(parsed.protocol) || parsed.username || parsed.password) throw Error()
    } catch { setError('公開されているサービスページのhttp/https URLを入力してください。'); return }
    const requestedRevision = revision.current
    setBusy(true); setError(''); setProposal(null); setApplied(false)
    try {
      const result = await api<Proposal>('/target-profiles/propose-from-url', 'POST', { url: parsed.href, sales_goal: goal, target_mode: targetMode })
      if (requestedRevision === revision.current) { setProposal(result); setSelected(0) }
    } catch (e) { if (requestedRevision === revision.current) setError(errorMessage(e)) }
    finally { setBusy(false) }
  }
  return <section aria-label="URLからAI提案" className="mb-6 rounded-lg border border-[#d7dfd9] p-4">
    <h3>URLから営業ターゲットを提案</h3>
    <p className="muted mt-2">サービスのURL → AI分析 → ターゲット選択 → 検索語を設定。手入力もできます。</p>
    <label className="field mt-3">販売したいサービスのURL<input type="url" maxLength={2000} placeholder="https://example.com/service" value={url} onChange={e => { changed(); setUrl(e.target.value) }} /></label>
    <label className="field">探したい営業先<select value={targetMode} onChange={e => { changed(); setTargetMode(e.target.value) }}><option value="customers">サービスを使う購入者</option><option value="partners">代理店・OEM提携先</option></select></label>
    <p className="muted text-sm">購入者は業種＋公式サイトで探します。サービスの課題や機能を検索語に混ぜません。</p>
    <label className="field">営業目的（任意）<textarea maxLength={2000} rows={2} placeholder="例：来店・予約を増やしたいカフェに販売したい" value={goal} onChange={e => { changed(); setGoal(e.target.value) }} /></label>
    <p className="muted text-sm">指定ページの本文を保存済みキーでAIへ送ります。1回の提案で1ページ解析・AI最大1回。API費用が発生します。検索・収集・保存・送信は開始しません。</p>
    <button type="button" className="mt-3" disabled={busy || !url.trim()} onClick={() => void suggest()}>{busy ? 'サービスを分析しています…' : 'AIにターゲットを提案してもらう'}</button>
    {error && <p className="error mt-3" role="alert">{error}</p>}
    {proposal && <div className="mt-4">
      <h3>サービスの分析</h3><p className="whitespace-pre-wrap mt-2">{proposal.service_summary}</p>
      <p className="muted text-sm">確認元：<a href={proposal.source_url} target="_blank" rel="noreferrer">サービスページ ↗</a></p>
      {proposal.evidence_quotes.length > 0 && <details className="mt-2"><summary>分析に使った原文</summary>{proposal.evidence_quotes.map(q => <blockquote key={q} className="mt-2">{q}</blockquote>)}</details>}
      <fieldset className="mt-4"><legend>営業ターゲットを選ぶ</legend>{proposal.targets.map((target, index) => <label key={index} className="mt-3 block rounded border border-[#d7dfd9] p-3"><span className="flex items-center gap-2"><input type="radio" className="!w-4 shrink-0 !p-0" name="ai-target-option" checked={selected === index} onChange={() => { setSelected(index); setApplied(false) }} /><strong>{target.name}</strong></span><span className="mt-2 block">{target.reason}</span><span className="muted mt-2 block">検索語：{target.search_keywords.join(' / ')}</span></label>)}</fieldset>
      {proposal.limitations.length > 0 && <div className="notice mt-3"><strong>確認が必要なこと</strong><ul>{proposal.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></div>}
      <p className="muted mt-3">AIの提案は仮説です。対象と検索語を確認し、下の設定へ反映してから編集・保存してください。</p>
      <button type="button" className="mt-3" onClick={() => { onApply(proposal.targets[selected], proposal.service_summary + (goal.trim() ? `\n営業目的: ${goal.trim()}` : ''), proposal.source_url); setApplied(true) }}>このターゲット案を設定へ反映</button>
      {applied && <p role="status" className="notice mt-2">下の設定に反映しました。内容を確認して保存してください。</p>}
    </div>}
  </section>
}
