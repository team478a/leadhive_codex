import { useEffect, useState } from 'react'
import { api, ApiError } from './api'
import { FormObservationJobControls } from './FormObservationJobControls'

type Evidence = {
  id: string; operation_job_id: string; observed_at: string; expires_at: string; snapshot_hash: string
  freshness: 'CURRENT' | 'EXPIRED' | 'SOURCE_CHANGED' | 'RETIRED' | 'INVALID'
  reason: 'STATIC_ONLY_UNVERIFIED' | 'SALES_PROHIBITED' | 'CAPTCHA_DETECTED' | 'STRUCTURE_REQUIRES_REVIEW' | 'INTEGRITY_INVALID'
  diagnostic: { sales_permission: 'UNCERTAIN' | 'PROHIBITED'; captcha_state: 'UNVERIFIED' | 'DETECTED' } | null
}
type Result = {
  available: boolean; items: Evidence[]; has_more: boolean
  latest_job: { id: string; status: string; processed_count: number; success_count: number; failed_count: number } | null
}
const freshness = { CURRENT: '有効期限内（未検証）', EXPIRED: '期限切れ', SOURCE_CHANGED: '企業URL変更後の古い観察', RETIRED: '取り下げ済み', INVALID: '整合性確認に失敗' }
const reasons = { STATIC_ONLY_UNVERIFIED: '静的HTMLのみ。動作・営業可否は未検証です。', SALES_PROHIBITED: '営業禁止表記を検出しました。', CAPTCHA_DETECTED: 'CAPTCHAを検出しました。人による確認が必要です。', STRUCTURE_REQUIRES_REVIEW: 'フォーム構造を自動で確認できません。人による確認が必要です。', INTEGRITY_INVALID: '保存証拠の整合性を確認できないため、判定内容を表示しません。' }
const jobs: Record<string, string> = { queued: '待機中', running: '実行中', completed: '完了', failed: '失敗', cancelled: 'キャンセル' }

export function CompanyFormObservationsPanel({ companyId }: { companyId: string }) {
  const [result, setResult] = useState<Result | null>(null)
  const [error, setError] = useState('')
  const [offset, setOffset] = useState(0)
  const [reload, setReload] = useState(0)
  useEffect(() => { setOffset(0) }, [companyId])
  useEffect(() => {
    let active = true
    setResult(null); setError('')
    api<Result>(`/companies/${companyId}/form-observations?limit=10&offset=${offset}`)
      .then(value => { if (active) setResult(value) })
      .catch(e => { if (active) setError(e instanceof ApiError && e.status === 404 ? '観察履歴を利用できません。APIの対応状況と閲覧権限を確認してください。' : '観察履歴を取得できません。時間をおいて再度確認してください。') })
    return () => { active = false }
  }, [companyId, offset, reload])
  return <section className="panel mt-7" aria-label="静的フォーム観察履歴">
    <h3>静的フォーム観察履歴</h3>
    <p role="note">診断専用の管理下テスト証拠です。送信許可・Human Approval・送信準備完了を意味しません。既存のフォーム判定や送信制御を更新しません。</p>
    <FormObservationJobControls companyId={companyId} onUpdated={() => setReload(value => value + 1)} />
    {error && <p role="alert">{error}</p>}
    {!result && !error && <p>読み込み中…</p>}
    {result && !result.available && <p>観察保存機能が未導入です。既存の企業機能は利用できます。</p>}
    {result?.available && <>
      {result.latest_job && <p>最新の観察処理：{jobs[result.latest_job.status] ?? '不明'}（処理 {result.latest_job.processed_count} / 成功 {result.latest_job.success_count} / 失敗 {result.latest_job.failed_count}）。過去の保存結果とは別の状態です。</p>}
      {result.items.length === 0 && <p>このページに保存済みの観察はありません。</p>}
      {result.items.map(item => <article key={item.id}>
        <h4>{freshness[item.freshness]}</h4>
        <p>{reasons[item.reason]}</p>
        <p>営業可否：{item.diagnostic?.sales_permission === 'PROHIBITED' ? '禁止表記あり' : '不明・未検証'} / CAPTCHA：{item.diagnostic?.captcha_state === 'DETECTED' ? '検出あり' : '不明・未検証'}</p>
        <p>観察日時：{new Date(item.observed_at).toLocaleString()} / 有効期限：{new Date(item.expires_at).toLocaleString()}</p>
        <p style={{ overflowWrap: 'anywhere' }}>証拠hash：{item.snapshot_hash}</p>
      </article>)}
      {offset > 0 && <button type="button" onClick={() => setOffset(Math.max(0, offset - 10))}>前の観察</button>}
      {result.has_more && offset < 10000 && <button type="button" onClick={() => setOffset(offset + 10)}>次の観察</button>}
      {result.has_more && offset >= 10000 && <p>古い履歴の表示上限に達しました。</p>}
    </>}
  </section>
}
