import { presenceLabels } from './externalPresenceShared'

export const conditionOutcomes: Record<string, string> = { MATCH: '一致', NO_MATCH: '不一致', REVIEW_REQUIRED: '確認待ち', UNKNOWN: '未確認' }
export const conditionPriorities: Record<string, string> = { MUST: '必須', WANT: '希望', EXCLUDE: '除外' }
export const conditionReasons: Record<string, string> = {
  VERIFICATION_UNSUPPORTED: 'この条件の検証は未対応', OFFICIAL_SITE_UNCONFIRMED: '公式サイトの根拠が未確認', PRESENCE_FOUND: '関連するページを確認', OFFICIAL_SITE_CONFIRMED: '公式サイトの根拠を確認',
  EVIDENCE_EXPIRED: '根拠の有効期間が終了', NEGATIVE_EVIDENCE_UNAVAILABLE: '有効な調査記録なし', SEARCH_NO_MATCH: '追加調査で見つからず', NOT_CHECKED: '未調査', ENTITY_CHANGED: '企業情報変更後の再確認が必要', SEARCH_BUDGET_EXHAUSTED: '検索上限に到達', ERROR: '調査結果を確認できません',
  SOURCE_TERMS_REVIEW_REQUIRED: 'この情報源の追加利用条件の確認が必要', PROTECTED_PRESENCE_CONFLICT: '手動で保護した情報と異なるため確認が必要', SEARCH_FAILED: '検索サービスのエラー', SEARCH_INCOMPLETE: '調査が完了していません', ENTITY_UNCERTAIN: 'この企業のページか確認が必要',
}
export function conditionValue(value: string) { return presenceLabels[value] ?? (value === 'OFFICIAL_SITE' ? '公式サイト' : value) }
