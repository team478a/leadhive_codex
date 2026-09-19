export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      method, credentials: 'include',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, '接続できません。APIの起動とネットワークを確認してください。')
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    if (response.status === 401 && path !== '/auth/login') {
      window.dispatchEvent(new Event('session-expired'))
    }
    throw new ApiError(response.status,
      typeof data.detail === 'string' ? data.detail : '処理に失敗しました。時間をおいて再度お試しください。')
  }
  return response.status === 204 ? undefined as T : response.json()
}

export async function upload<T>(path: string, form: FormData): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, { method: 'POST', credentials: 'include', body: form })
  } catch {
    throw new ApiError(0, '接続できません。APIの起動とネットワークを確認してください。')
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    if (response.status === 401) window.dispatchEvent(new Event('session-expired'))
    throw new ApiError(response.status,
      typeof data.detail === 'string' ? data.detail : 'アップロードに失敗しました。')
  }
  return response.json()
}

export async function download(path: string, filename: string) {
  const response = await fetch(`/api${path}`, { credentials: 'include' })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    if (response.status === 401) window.dispatchEvent(new Event('session-expired'))
    throw new ApiError(response.status,
      typeof data.detail === 'string' ? data.detail : 'ダウンロードに失敗しました。')
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
