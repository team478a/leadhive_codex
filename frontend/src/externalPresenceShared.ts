export const presenceLabels: Record<string, string> = {
  INSTAGRAM: 'Instagram', X: 'X', FACEBOOK: 'Facebook', YOUTUBE: 'YouTube', TIKTOK: 'TikTok',
  HOTPEPPER: 'HotPepper', HOTPEPPER_BEAUTY: 'HotPepper Beauty', TABELOG: '食べログ',
  GURUNAVI: 'ぐるなび', EPARK: 'EPARK', RAKUTEN_BEAUTY: '楽天ビューティ',
  INDEED: 'Indeed', KYUJIN_BOX: '求人ボックス',
}
export type PresencePlan = {
  modes: Record<string, 'AUTO' | 'SEARCH' | 'REQUIRED'>
  required_platforms: string[]
  max_extra_searches: number
  timeout_seconds: number
}
export const defaultPresencePlan: PresencePlan = {
  modes: {}, required_platforms: [], max_extra_searches: 5, timeout_seconds: 60,
}
export const presenceGroups: Record<string, string[]> = {
  SNS: ['INSTAGRAM', 'X', 'FACEBOOK', 'YOUTUBE', 'TIKTOK'],
  掲載媒体: ['HOTPEPPER', 'HOTPEPPER_BEAUTY', 'TABELOG', 'GURUNAVI', 'EPARK', 'RAKUTEN_BEAUTY'],
  求人: ['INDEED', 'KYUJIN_BOX'],
}
