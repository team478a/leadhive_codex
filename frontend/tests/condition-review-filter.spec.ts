import { test, expect } from '@playwright/test'
import { matchesReviewFilter } from '../src/conditionReviewFilter'
import type { ReviewCandidate } from '../src/ConditionReviewNavigation'

function candidate(state: string, type: string, priority: string, outcome: string): ReviewCandidate {
  return { company_id: 'fixture', state, conditions: [{ type, value: 'fixture', priority, outcome }] }
}
test('Review filters keep optional unknown facts out of mandatory review queues', () => {
  expect(matchesReviewFilter(candidate('REVIEW_REQUIRED', 'AREA', 'MUST', 'UNKNOWN'), 'AREA')).toBe(true)
  expect(matchesReviewFilter(candidate('REVIEW_REQUIRED', 'INDUSTRY', 'EXCLUDE', 'UNKNOWN'), 'INDUSTRY')).toBe(true)
  expect(matchesReviewFilter(candidate('REVIEW_REQUIRED', 'AREA', 'WANT', 'UNKNOWN'), 'AREA')).toBe(false)
  expect(matchesReviewFilter(candidate('NO_MATCH', 'AREA', 'MUST', 'UNKNOWN'), 'AREA')).toBe(false)
  expect(matchesReviewFilter(candidate('REVIEW_REQUIRED', 'AREA', 'MUST', 'MATCH'), 'AREA')).toBe(false)
  expect(matchesReviewFilter(candidate('MATCH', 'AREA', 'WANT', 'UNKNOWN'), 'ALL')).toBe(true)
  expect(matchesReviewFilter(candidate('REVIEW_REQUIRED', 'AREA', 'MUST', 'UNKNOWN'), 'REVIEW_REQUIRED')).toBe(true)
})
