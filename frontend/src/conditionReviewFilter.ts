import type { ReviewCandidate } from './ConditionReviewNavigation'

export function matchesReviewFilter(candidate: ReviewCandidate, filter: string) {
  if (filter === 'ALL') return true
  if (candidate.state !== 'REVIEW_REQUIRED') return false
  return filter === 'REVIEW_REQUIRED' || candidate.conditions.some(c => c.type === filter && c.priority !== 'WANT' && c.outcome === 'UNKNOWN')
}
