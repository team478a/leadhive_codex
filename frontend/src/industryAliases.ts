export const industryAliasKey = 'industry_review_aliases'

export function aliasText(value: unknown): string {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return ''
  return Object.entries(value).filter(([, aliases]) => Array.isArray(aliases)).map(([industry, aliases]) => `${industry}: ${(aliases as unknown[]).filter(a => typeof a === 'string').join(', ')}`).join('\n')
}

export function parseAliases(text: string): Record<string, string[]> {
  const mapping: Record<string, string[]> = Object.create(null) as Record<string, string[]>
  for (const row of text.split('\n').map(s => s.trim()).filter(Boolean)) {
    const parts = row.split(/[:：]/)
    if (parts.length !== 2 || !parts[0].trim() || !parts[1].trim()) throw Error('業種の別名は「業種名: 別名1, 別名2」の形式で入力してください。')
    const industry = parts[0].trim()
    if (Object.hasOwn(mapping, industry)) throw Error('同じ業種の別名は1行にまとめてください。')
    mapping[industry] = parts[1].split(/[,、]/).map(s => s.trim()).filter(Boolean)
  }
  return mapping
}
