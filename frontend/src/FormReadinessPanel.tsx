import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import { Field } from './forms'

interface Row {
  company_id: string; company_name: string; category: string; form_url: string
  form_status: string; analysis_version: string | null; last_analyzed_at: string | null
  review_reason: string; permission: { status: string; reason_code: string; message: string }
}
interface Overview { counts: Record<string, number>; company_total: number; total: number; items: Row[]; analysis_version: string }
const labels: Record<string, string> = {
  candidate: '解析条件の候補', unanalyzed: '未解析', prohibited: '営業禁止', do_not_contact: '連絡禁止',
  review: '内容・項目の確認', captcha: 'CAPTCHA・人の操作が必要', confirmation: '確認画面・段階の確認',
  stale: '変更検出・再解析', error: '解析エラー', missing_form: 'フォーム未発見', legacy: '旧解析・再解析',
}

const nextActions: Record<string, string> = {
  candidate: '企業詳細で窓口の用途・連絡制御・送信履歴を確認し、文面と送信者を準備します。候補であっても送信承認は別途必要です。',
  unanalyzed: '企業詳細で公式サイトURLを確認し、必要な範囲だけフォーム解析を行います。',
  prohibited: '営業禁止の根拠を企業詳細で確認してください。項目修正や文面作成で禁止状態は解除できません。',
  do_not_contact: '連絡禁止の理由を企業詳細で確認してください。この一覧から禁止を解除したり送信したりはできません。',
  review: '企業詳細のフォーム事前解析で、窓口の用途と未確定の必須項目・選択肢を確認します。',
  captcha: 'CAPTCHAは人の操作・確認が必要です。自動処理やCodex支援で回避せず、企業詳細で対応範囲を確認します。',
  confirmation: '企業詳細で確認画面と必須項目を確認します。確認画面の発見は送信経路の検証完了ではありません。',
  stale: '保存情報が変わっています。企業詳細で変更内容を確認し、必要な範囲を再解析して確認し直します。',
  error: '企業詳細の解析ログで取得失敗の理由を確認します。取得失敗はフォームがない証拠ではありません。',
  missing_form: '企業詳細で問い合わせ導線と埋め込みの診断を確認します。静的HTMLでの未検出をフォームなしと判断しないでください。',
  legacy: '古い解析結果です。企業詳細で解析日時と対象URLを確認し、必要な範囲を再解析します。',
}

function nextAction(row: Row) {
  if (row.permission.status !== 'ALLOWED') {
    return row.permission.status === 'PROHIBITED'
      ? '連絡制御によって停止しています。企業詳細で禁止・Suppression・配信停止などの理由を確認してください。フォームがあっても送信には進めません。'
      : '連絡できるか未確定です。企業詳細で連絡制御の理由を先に確認してください。候補表示から営業許可を推測しないでください。'
  }
  return nextActions[row.category] ?? '企業詳細で解析状態と停止理由を確認してください。分類不明のまま送信準備完了とは扱いません。'
}

export function FormReadinessPanel({ projectId, onOpen }: { projectId: string; onOpen: (id: string) => Promise<void> }) {
  const [data, setData] = useState<Overview | null>(null)
  const [category, setCategory] = useState('all')
  const [offset, setOffset] = useState(0)
  const [refresh, setRefresh] = useState(0)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    let live = true
    setBusy(true); setError(''); setData(null)
    api<Overview>(`/projects/${projectId}/form-readiness?category=${category}&limit=25&offset=${offset}`)
      .then(next => { if (live) setData(next) }).catch(e => { if (live) setError(errorMessage(e)) })
      .finally(() => { if (live) setBusy(false) })
    return () => { live = false }
  }, [projectId, category, offset, refresh])
  return <section className="panel mt-4" aria-label="フォーム候補の集計">
    <h2>フォーム候補の集計</h2>
    <p>選択中のプロジェクト全体が対象です。企業一覧のキーワード・ランクなどの絞り込みとは別に集計します。</p>
    <p>保存済み解析を企業ごとに集計します。候補数は解析条件による参考値です。Suppression・送信履歴・文面・送信者・承認などは準備時に再確認するため、送信許可の件数ではありません。</p>
    {error && <p className="error" role="alert">{error}</p>}
    {busy && !data && <p role="status">フォーム候補を読み込み中…</p>}
    <p>プロジェクト全体: {data?.company_total ?? '—'}社 / 現行解析: {data?.analysis_version ?? '—'}</p>
    <div className="flex flex-wrap gap-2">{Object.entries(labels).map(([name, label]) => <button type="button" className="secondary" key={name} disabled={busy} onClick={() => { setCategory(name); setOffset(0) }}>{label}: {data ? data.counts[name] ?? 0 : '—'}社</button>)}</div>
    <Field label="フォーム集計の表示対象"><select value={category} disabled={busy} onChange={e => { setCategory(e.target.value); setOffset(0) }}>
      <option value="all">すべて</option>{Object.entries(labels).map(([name, label]) => <option key={name} value={name}>{label}</option>)}
    </select></Field>
    <button type="button" className="secondary" disabled={busy} onClick={() => setRefresh(refresh + 1)}>フォーム集計を更新</button>
    <p>表示対象: {data?.total ?? '—'}社</p>
    {!busy && data?.items.length === 0 && <p>この表示範囲に該当する企業はありません。表示対象やページを変更して確認できます。</p>}
    {data?.items.map(row => <article className="border rounded p-3 my-3" key={row.company_id}>
      <p>{row.company_name} / {labels[row.category] ?? row.category}</p>
      <p className="break-all">{row.form_url || 'フォームURL未登録'}</p>
      <p>解析: {row.form_status} / version {row.analysis_version ?? '未解析'} / {row.last_analyzed_at ? new Date(row.last_analyzed_at).toLocaleString('ja-JP') : '解析日時なし'}</p>
      {row.review_reason && <p>{row.review_reason}</p>}
      <p>{row.permission.status === 'ALLOWED' ? '連絡制御: 制限未検出（Human承認・送信許可ではありません）' : `連絡制御: ${row.permission.message}`}</p>
      <p className="notice mt-2">次にすること：{nextAction(row)}</p>
      <button type="button" className="secondary" disabled={busy} onClick={async () => {
        setBusy(true); setError('')
        try { await onOpen(row.company_id) } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
      }}>{row.company_name}の企業詳細を確認</button>
    </article>)}
    <button type="button" className="secondary" disabled={busy || offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>フォーム集計の前の25社</button>{' '}
    <button type="button" className="secondary" disabled={busy || !data || offset + data.items.length >= data.total} onClick={() => setOffset(offset + 25)}>フォーム集計の次の25社</button>
  </section>
}
