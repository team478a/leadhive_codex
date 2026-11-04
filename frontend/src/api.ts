export class ApiError extends Error {
  constructor(public status: number, message: string, public fields: string[] = [], public requestId = '') { super(message) }
}

function responseError(status: number, data: { detail?: unknown; issues?: unknown }, fallback: string, requestId = '') {
  const message = typeof data.detail === 'string' ? data.detail : fallback
  const issues = Array.isArray(data.issues)
    ? data.issues.filter((issue): issue is { field: string; message: string } =>
      Boolean(issue) && typeof issue === 'object'
      && typeof issue.field === 'string' && typeof issue.message === 'string')
    : []
  const fields = [...new Set(issues.map(issue => issue.field))]
  const reasons = issues.map(issue => `${issue.field}: ${issue.message}`)
  const detail = reasons.length ? `${message} ${reasons.join(' ')}` : message
  const supportCode = requestId && status >= 500 ? `（エラーID: ${requestId.slice(0, 12)}）` : ''
  return new ApiError(status, `${detail}${supportCode}`, fields, requestId)
}

function networkError(method: string, path: string) {
  const safePath = path.split('?')[0]
    .replace(/\/projects\/[^/]+/g, '/projects/:project')
    .replace(/\/companies\/[^/]+/g, '/companies/:company')
    .replace(/\/operations\/[^/]+/g, '/operations/:operation')
  return new ApiError(0, `接続できません（${method} ${safePath}）。ネットワークを確認して再試行してください。`)
}

export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const attempts = method === 'GET' ? 5 : 1
  let response: Response | undefined
  let lastNetworkError = false
  let delay = 0
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (delay) await new Promise(resolve => window.setTimeout(resolve, delay))
    try {
      response = await fetch(`/api${path}`, {
        method, credentials: 'include',
        headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      })
      lastNetworkError = false
    } catch {
      lastNetworkError = true
      if (method === 'GET' && attempt + 1 < attempts) {
        delay = Math.min(1000 * (2 ** attempt), 8000) + Math.floor(Math.random() * 251)
        continue
      }
      break
    }
    if (response.status !== 503) break
    const unavailable = await response.clone().json().catch(() => ({}))
    if (unavailable.detail !== 'データベースを利用できません。') break
    if (attempt + 1 >= attempts) break
    const retryAfterHeader = response.headers.get('Retry-After')
    const retryAfter = retryAfterHeader === null ? Number.NaN : Number(retryAfterHeader)
    const baseDelay = Number.isFinite(retryAfter) && retryAfter >= 0
      ? Math.min(retryAfter * 1000, 10_000)
      : Math.min(1000 * (2 ** attempt), 8000)
    delay = baseDelay + Math.floor(Math.random() * 251)
  }
  if (!response || lastNetworkError) throw networkError(method, path)
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    if (response.status === 401 && path !== '/auth/login') {
      window.dispatchEvent(new Event('session-expired'))
    }
    throw responseError(response.status, data, '処理に失敗しました。時間をおいて再度お試しください。', response.headers.get('X-Request-ID') ?? '')
  }
  return response.status === 204 ? undefined as T : response.json()
}

export async function upload<T>(path: string, form: FormData): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, { method: 'POST', credentials: 'include', body: form })
  } catch {
    throw networkError('POST', path)
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    if (response.status === 401) window.dispatchEvent(new Event('session-expired'))
    throw responseError(response.status, data, 'アップロードに失敗しました。', response.headers.get('X-Request-ID') ?? '')
  }
  return response.json()
}

export async function download(path: string, filename: string) {
  const response = await fetch(`/api${path}`, { credentials: 'include' })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    if (response.status === 401) window.dispatchEvent(new Event('session-expired'))
    throw responseError(response.status, data, 'ダウンロードに失敗しました。', response.headers.get('X-Request-ID') ?? '')
  }
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url; anchor.download = filename; anchor.click()
  URL.revokeObjectURL(url)
}

export async function allPages<T>(path: string): Promise<T[]> {
  const result: T[] = []
  for (let offset = 0; ; offset += 100) {
    const page = await api<T[]>(`${path}?offset=${offset}&limit=100`)
    result.push(...page)
    if (page.length < 100) return result
  }
}

export function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : '処理に失敗しました。もう一度お試しください。'
}
