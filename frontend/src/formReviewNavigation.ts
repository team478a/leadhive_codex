/** In-page handoff only: never changes route, destination selection or approval. */
function samePage(left: string, right: string) {
  try {
    const a = new URL(left); const b = new URL(right)
    if (!['http:', 'https:'].includes(a.protocol) || !['http:', 'https:'].includes(b.protocol)) return false
    if (a.username || a.password || b.username || b.password) return false
    // Inventory removes trailing path slashes. This is navigation only, not a send comparison.
    return a.origin === b.origin && a.pathname.replace(/\/+$/, '') === b.pathname.replace(/\/+$/, '') && a.search === b.search
  } catch { return false }
}

export function openDestinationReview(companyId: string, formUrl: string): boolean {
  const section = document.getElementById(`destination-review-${companyId}`)
  if (!section) return false
  const matches = Array.from(section.querySelectorAll<HTMLDetailsElement>('details[data-form-destination]'))
    .filter(element => samePage(element.dataset.formDestination || '', formUrl))
  if (matches.length === 1) {
    const destination = matches[0]
    destination.open = true
    destination.scrollIntoView({ block: 'start' })
    destination.querySelector('summary')?.focus({ preventScroll: true })
  }
  return matches.length === 1
}

export function openFormReview(companyId: string, formUrl: string): boolean {
  const section = document.getElementById(`form-review-${companyId}`)
  const matches = section && Array.from(section.querySelectorAll<HTMLElement>('[data-review-form-url]'))
    .filter(element => samePage(element.dataset.reviewFormUrl || '', formUrl))
  if (!matches || matches.length !== 1) return false
  const profile = matches[0]
  profile.scrollIntoView({ block: 'start' }); profile.focus({ preventScroll: true })
  return true
}
