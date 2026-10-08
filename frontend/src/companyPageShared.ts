import type { CollectionSource, CompanyFilterValues, OutreachChannel, SalesStatus } from './types'

export const statusNames: Record<SalesStatus, string> = {
  unreviewed: '未確認', target: '営業対象', approached: 'アプローチ済', replied: '返信あり',
  meeting: '商談', won: '成約', lost: '失注', excluded: '対象外',
}
export const sourceNames: Record<CollectionSource, string> = {
  serper: 'Google検索', google_places: 'Google Maps', gbizinfo: 'gBizINFO', url: 'URL', csv: 'CSV',
}
export const channelNames: Record<OutreachChannel, string> = { email: 'メール', form: 'フォーム', call: '電話', sns: 'SNS' }
export const dueNames = { overdue: '期限超過', today: '本日', upcoming: '今後', unset: '期限なし' }
export const emptyContact = { name: '', department: '', title: '', email: '', phone: '', source_url: '', verification_status: 'unknown', notes: '' }
export const defaultCompanyFilters: CompanyFilterValues = { rank: '', minScore: '', region: '', status: '', source: '', keyword: '', assignee: '', followup: '', sort: 'score_desc' }

export function companyQueryString(filters: CompanyFilterValues, page: number) {
  const params = new URLSearchParams({ limit: '25', offset: String(page * 25), sort: filters.sort })
  if (filters.rank) params.set('rank', filters.rank)
  if (filters.minScore) params.set('min_score', filters.minScore)
  if (filters.region) params.set('region', filters.region)
  if (filters.status) params.set('status', filters.status)
  if (filters.source) params.set('source', filters.source)
  if (filters.keyword) params.set('keyword', filters.keyword)
  if (filters.assignee) params.set('assignee', filters.assignee)
  if (filters.followup) params.set('followup', filters.followup)
  return params.toString()
}
