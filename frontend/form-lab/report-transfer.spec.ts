import { test, expect } from '@playwright/test'
import { createServer } from 'node:http'
import { reportOrigin, transferReport } from './report-transfer'
const binding = { trialId: '11111111-1111-4111-8111-111111111111', companyId: 'company', projectId: 'project', requestHash: 'a'.repeat(64), htmlHash: 'b'.repeat(64) }
const transfer = { origin: 'https://cloud.example', token: 'lh_diag_' + 'a'.repeat(64), expiresAt: new Date(Date.now() + 60000).toISOString() }
test('report transport is default disabled, origin pinned, no redirect/cookie/retry', async () => {
  let calls = 0
  const transport: typeof fetch = async (url, init) => {
    calls++
    expect(String(url)).toBe(`https://cloud.example/api/pc-input-trials/${binding.trialId}/result`)
    expect(init?.credentials).toBe('omit'); expect(init?.redirect).toBe('error'); expect(init?.method).toBe('POST')
    expect(init?.headers).toMatchObject({ Authorization: `Bearer ${transfer.token}` })
    expect(init?.body).not.toContain('lh_diag_')
    return Response.json({ recorded: true, alreadyRecorded: false })
  }
  expect(await transferReport(transfer, { binding }, undefined, false, transport)).toBe('DISABLED')
  expect(await transferReport({ ...transfer, origin: 'https://evil.example' }, { binding }, transfer.origin, false, transport)).toBe('FAILED')
  expect(await transferReport({ ...transfer, expiresAt: 'invalid' }, { binding }, transfer.origin, false, transport)).toBe('FAILED')
  expect(calls).toBe(0)
  expect(await transferReport(transfer, { binding }, transfer.origin, false, transport)).toBe('RECORDED')
  expect(calls).toBe(1)
  expect(() => reportOrigin('https://cloud.example/path')).toThrow()
  expect(() => reportOrigin('http://cloud.example', true)).toThrow()
  expect(() => reportOrigin('https://user:secret@cloud.example')).toThrow()
  expect(await transferReport(transfer, { binding }, transfer.origin, false, async () => { throw Error('secret must not be exposed') })).toBe('FAILED')
  expect(await transferReport(transfer, { binding }, transfer.origin, false, async () => new Response('<html>frontend fallback</html>'))).toBe('FAILED')
  expect(await transferReport(transfer, { binding }, transfer.origin, false, async () => Response.json({ recorded: false, alreadyRecorded: false }))).toBe('FAILED')
})
test('explicit loopback POST arrives once and redirect never reaches its target', async () => {
  let arrivals = 0; let redirected = 0
  const server = createServer((req, res) => {
    if (req.url === '/secret') { redirected++; res.end(); return }
    arrivals++; res.writeHead(arrivals === 1 ? 200 : 302, { Location: '/secret', 'Content-Type': 'application/json' }); res.end(JSON.stringify({ recorded: true, alreadyRecorded: false }))
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const address = server.address(); if (!address || typeof address === 'string') throw Error('fixture')
  const origin = `http://127.0.0.1:${address.port}`
  try {
    const local = { ...transfer, origin }
    expect(await transferReport(local, { binding }, origin)).toBe('FAILED')
    expect(arrivals).toBe(0)
    expect(await transferReport(local, { binding }, origin, true)).toBe('RECORDED')
    expect(await transferReport(local, { binding }, origin, true)).toBe('FAILED')
    expect(arrivals).toBe(2); expect(redirected).toBe(0)
  } finally { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())) }
})
