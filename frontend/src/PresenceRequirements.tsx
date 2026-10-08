import { useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import { presenceLabels } from './externalPresenceShared'

type Report = {
  required_platforms: string[]
  candidates: { company_id: string; requirement_state: 'MATCH' | 'NO_MATCH' | 'REVIEW_REQUIRED' }[]
}
export function PresenceRequirements({ jobId }: { jobId: string }) {
  const [report, setReport] = useState<Report | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let cancelled = false
    api<Report>(`/collection-jobs/${jobId}/external-presence-report`).then(value => {
      if (!cancelled) setReport(value)
    }).catch(e => { if (!cancelled) setError(errorMessage(e)) })
    return () => { cancelled = true }
  }, [jobId])
  if (error) return <p className="error">媒体条件の集計を取得できません：{error}</p>
  if (!report?.required_platforms.length) return null
  return <p className="text-sm">必須媒体：{report.required_platforms.map(p => presenceLabels[p]).join('・')}。
    一致 {report.candidates.filter(c => c.requirement_state === 'MATCH').length}件、
    不一致 {report.candidates.filter(c => c.requirement_state === 'NO_MATCH').length}件、
    確認待ち {report.candidates.filter(c => c.requirement_state === 'REVIEW_REQUIRED').length}件。
    不一致・確認待ちは完全一致リストとして扱いません。</p>
}
