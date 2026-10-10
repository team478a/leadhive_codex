import type { TrialBinding } from '../src/offlineHandoffContract'
export type Transfer = { origin: string; token: string; expiresAt: string }
export type TransferStatus = 'RECORDED' | 'FAILED' | 'DISABLED' | 'NOT_REQUESTED'

export function reportOrigin(value: string, loopback = false) {
  const url = new URL(value)
  if (url.username || url.password || url.pathname !== '/' || url.search || url.hash
    || url.protocol !== 'https:' && !(loopback && url.protocol === 'http:' && ['127.0.0.1', '[::1]'].includes(url.hostname))
    || url.protocol === 'https:' && url.port && url.port !== '443') throw Error('Invalid report origin')
  return url.origin
}
// A single bounded POST only to an independently configured LeadHive origin.
// The archived page never receives this credential. No cookie, redirect or retry.
export async function transferReport(transfer: unknown, report: { binding: TrialBinding },
  trustedOrigin: string | undefined, loopback = false, transport: typeof fetch = fetch): Promise<TransferStatus> {
  if (!transfer) return 'NOT_REQUESTED'
  if (!trustedOrigin) return 'DISABLED'
  try {
    const value = transfer as Transfer
    const origin = reportOrigin(trustedOrigin, loopback)
    if (reportOrigin(value.origin, loopback) !== origin || !/^lh_diag_[a-f0-9]{64}$/.test(value.token)
      || !Number.isFinite(Date.parse(value.expiresAt)) || Date.parse(value.expiresAt) <= Date.now()
      || !/^[0-9a-f-]{36}$/.test(report.binding.trialId)) return 'FAILED'
    const body = JSON.stringify(report)
    if (Buffer.byteLength(body) > 16_000) return 'FAILED'
    const response = await transport(`${origin}/api/pc-input-trials/${report.binding.trialId}/result`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${value.token}` },
      body, credentials: 'omit', redirect: 'error', signal: AbortSignal.timeout(15_000),
    })
    if (response.status !== 200 || response.headers.get('content-type')?.split(';')[0].trim() !== 'application/json' || !response.body) {
      await response.body?.cancel(); return 'FAILED'
    }
    const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let length = 0
    try {
      while (true) {
        const chunk = await reader.read(); if (chunk.done) break
        length += chunk.value.length
        if (length > 4096) { await reader.cancel(); return 'FAILED' }
        chunks.push(chunk.value)
      }
    } finally { reader.releaseLock() }
    const confirmation = JSON.parse(Buffer.concat(chunks).toString('utf8'))
    return confirmation?.recorded === true && typeof confirmation.alreadyRecorded === 'boolean'
      && Object.keys(confirmation).every(key => ['recorded', 'alreadyRecorded'].includes(key)) ? 'RECORDED' : 'FAILED'
  } catch { return 'FAILED' }
}
