export type SiteHint = { kind: string; homepage_candidate: string; reference_url: string }

const labels: Record<string, string> = {
  ARTICLE_OWNER_REVIEW: '検索で記事ページを発見しました。掲載元のサイト候補です。公式サイトか確認してください。',
  REFERENCE_SITE: '検索で掲載媒体・比較サイトを発見しました。企業サイトとは分けて確認してください。',
  REFERENCE_DOCUMENT: '検索で資料ファイルを発見しました。企業サイトとしては登録していません。',
  BUSINESS_SITE_REVIEW: '検索でサイト候補を発見しました。企業主体・公式サイトは未確認です。',
}

function publicLink(url: string) { return /^https?:\/\//.test(url) }

export function CollectionSiteHint({ hint }: { hint?: SiteHint | null }) {
  if (!hint) return null
  return <span className="block text-sm">収集URL：{labels[hint.kind] ?? '企業サイト候補です。公式サイトか確認してください。'}{' '}
    {publicLink(hint.homepage_candidate) && <a href={hint.homepage_candidate} target="_blank" rel="noopener noreferrer">サイト候補 ↗</a>}{' '}
    {publicLink(hint.reference_url) && <a href={hint.reference_url} target="_blank" rel="noopener noreferrer">発見ページ ↗</a>}
  </span>
}
