/** Public IPv4 HTTPS GET only. DNS is validated and pinned to the TLS connection. */
import { resolve4 } from 'node:dns/promises'
import { BlockList, isIP } from 'node:net'
import { request } from 'node:https'
import { rootCertificates } from 'node:tls'

const denied = new BlockList()
for (const [ip, mask] of [['0.0.0.0', 8], ['10.0.0.0', 8], ['100.64.0.0', 10], ['127.0.0.0', 8],
  ['169.254.0.0', 16], ['172.16.0.0', 12], ['192.0.0.0', 24], ['192.0.2.0', 24], ['192.88.99.0', 24],
  ['192.168.0.0', 16], ['198.18.0.0', 15], ['198.51.100.0', 24], ['203.0.113.0', 24], ['224.0.0.0', 4], ['240.0.0.0', 4]] as const) denied.addSubnet(ip, mask, 'ipv4')
export function publicIPv4(address: string) { return isIP(address) === 4 && !denied.check(address, 'ipv4') }
export function publicTarget(value: string) {
  const url = new URL(value)
  if (value.length > 2048 || (/[\s\\]/.test(value) || Array.from(value).some(c => c.charCodeAt(0) < 32 || c.charCodeAt(0) === 127)) || url.protocol !== 'https:' || url.port
    || url.username || url.password || url.hash || isIP(url.hostname) || !/^[a-z0-9.-]+$/.test(url.hostname)
    || url.hostname.endsWith('.') || !url.hostname.includes('.') || url.hostname.split('.').some(p => !p || p.startsWith('-') || p.endsWith('-'))) throw Error('TARGET_REJECTED')
  return url
}
export function robotsPermits(text: string, path: string) {
  const groups: { agents: string[]; rules: { allow: boolean; path: string }[] }[] = []
  let agents: string[] = [], rules: { allow: boolean; path: string }[] = []
  const flush = () => { if (agents.length) groups.push({ agents, rules }); agents = []; rules = [] }
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.split('#')[0].trim(); if (!line) continue
    const index = line.indexOf(':'); if (index < 0) throw Error('ROBOTS_INVALID')
    const key = line.slice(0, index).toLowerCase(), value = line.slice(index + 1).trim()
    if (key === 'user-agent') { if (rules.length) flush(); agents.push(value.toLowerCase()) }
    else if (['allow', 'disallow'].includes(key)) {
      if (!agents.length || value && !value.startsWith('/')) throw Error('ROBOTS_INVALID')
      if (value) rules.push({ allow: key === 'allow', path: value })
    }
  }
  flush()
  const specific = groups.filter(g => g.agents.some(a => a !== '*' && 'leadhiveinputobserver'.includes(a)))
  const applicable = specific.length ? specific : groups.filter(g => g.agents.includes('*'))
  const matching = applicable.flatMap(g => g.rules).filter(rule => {
    const suffix = rule.path.endsWith('$') ? '$' : ''
    const pattern = (suffix ? rule.path.slice(0, -1) : rule.path).split('*').map(p => p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('.*')
    return new RegExp('^' + pattern + suffix).test(path)
  }).sort((a, b) => b.path.replace(/[*$]/g, '').length - a.path.replace(/[*$]/g, '').length || Number(b.allow) - Number(a.allow))
  return !matching.length || matching[0].allow
}
type Response = { status: number; contentType: string; body: string }
export class PublicGetter {
  readonly source: URL
  readonly started = performance.now()
  count = 0
  bytes = 0
  private robots: string | null = null
  private chain: Promise<unknown> = Promise.resolve()
  constructor(source: string, private maxRequests = 32,
    private io: { resolve: (host: string) => Promise<string[]>; request: typeof request } = { resolve: resolve4, request }) {
    this.source = publicTarget(source); if (!Number.isInteger(maxRequests) || maxRequests < 1 || maxRequests > 32) throw Error('GET_BUDGET')
  }
  private async once(url: URL, robot = false): Promise<Response> {
    if (url.origin !== this.source.origin || this.count >= this.maxRequests || performance.now() - this.started > 60_000) throw Error('GET_BUDGET')
    const deadline = 60_000 - (performance.now() - this.started)
    let timer: ReturnType<typeof setTimeout> | undefined
    const answers = await Promise.race([this.io.resolve(url.hostname), new Promise<never>((_, reject) => { timer = setTimeout(() => reject(Error('DNS_TIMEOUT')), Math.min(5000, deadline)) })]).finally(() => clearTimeout(timer))
    if (!answers.length || answers.some(a => !publicIPv4(a))) throw Error('UNSAFE_DNS')
    const response = await new Promise<Response>((resolve, reject) => {
      const req = this.io.request(url, { method: 'GET', agent: false, ca: [...rootCertificates], rejectUnauthorized: true,
        lookup: (_host, opts, callback) => opts.all ? callback(null, [{ address: answers[0], family: 4 }]) : callback(null, answers[0], 4),
        headers: { 'User-Agent': 'LeadHiveInputObserver', 'Accept-Encoding': 'identity', Connection: 'close' } }, res => {
        if (res.statusCode !== 200 && !(robot && res.statusCode === 404)) { res.destroy(); reject(Error('HTTP_OR_REDIRECT_REJECTED')); return }
        if (res.headers['content-encoding'] && res.headers['content-encoding'] !== 'identity') { res.destroy(); reject(Error('ENCODING_REJECTED')); return }
        const chunks: Buffer[] = []; let size = 0
        res.on('data', (chunk: Buffer) => {
          size += chunk.length
          if (size > (robot ? 64_000 : 500_000) || this.bytes + size > 2_000_000) { res.destroy(Error('BYTE_BUDGET')); return }
          chunks.push(chunk)
        })
        res.on('error', () => reject(Error('RESPONSE_FAILED')))
        res.on('end', () => {
          this.bytes += size
          try { resolve({ status: res.statusCode!, contentType: String(res.headers['content-type'] || '').toLowerCase(), body: new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks)) }) }
          catch { reject(Error('UTF8_REQUIRED')) }
        })
      })
      const totalTimer = setTimeout(() => req.destroy(Error('GET_TIMEOUT')), Math.max(1, 60_000 - (performance.now() - this.started)))
      req.on('close', () => clearTimeout(totalTimer))
      req.setTimeout(10_000, () => req.destroy(Error('GET_TIMEOUT')))
      req.on('error', () => reject(Error('GET_FAILED'))); this.count++; req.end()
    })
    await new Promise(resolve => setTimeout(resolve, 1000))
    return response
  }
  fetch(value: string, kind: 'document' | 'script' | 'stylesheet'): Promise<{ body: string; contentType: string }> {
    const task = this.chain.then(async () => {
      const url = publicTarget(value)
      if (url.origin !== this.source.origin) throw Error('FOREIGN_ORIGIN')
      if (this.robots === null) {
        const policy = await this.once(new URL('/robots.txt', this.source), true)
        this.robots = policy.status === 404 ? '' : policy.body
      }
      if (!robotsPermits(this.robots, url.pathname + url.search)) throw Error('ROBOTS_BLOCKED')
      const response = await this.once(url)
      const mime = response.contentType.split(';')[0].trim()
      const allowed = { document: ['text/html'], script: ['application/javascript', 'text/javascript', 'application/x-javascript'], stylesheet: ['text/css'] }
      if (!allowed[kind].includes(mime)) throw Error('MIME_REJECTED')
      return { body: response.body, contentType: response.contentType }
    })
    this.chain = task.catch(() => {}); return task
  }
}
