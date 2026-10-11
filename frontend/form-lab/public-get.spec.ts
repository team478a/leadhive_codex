import { test, expect } from '@playwright/test'
import { EventEmitter } from 'node:events'
import type { request, RequestOptions } from 'node:https'
import type { IncomingMessage } from 'node:http'
import { PublicGetter } from './public-get'

function transport(status = 200, robots = 'User-agent: *\nAllow: /', mime = 'text/html') {
  const calls: { url: URL; options: RequestOptions }[] = []
  const mock = (url: URL, options: RequestOptions, callback: (response: IncomingMessage) => void) => {
    calls.push({ url, options })
    const req = new EventEmitter() as EventEmitter & { end(): void; destroy(): void; setTimeout(): void }
    req.setTimeout = () => {}
    req.destroy = () => { req.emit('error', Error('stopped')); req.emit('close') }
    req.end = () => queueMicrotask(() => {
      const isRobots = url.pathname === '/robots.txt'
      const res = new EventEmitter() as EventEmitter & { statusCode: number; headers: Record<string, string>; destroy(error?: Error): void }
      res.statusCode = isRobots ? 200 : status
      res.headers = { 'content-type': isRobots ? 'text/plain' : mime }
      res.destroy = () => { res.emit('error', Error('stopped')); req.emit('close') }
      // Real IncomingMessage.destroy() does not synchronously emit error with no argument.
      if (!isRobots && status !== 200) res.destroy = () => req.emit('close')
      callback(res as unknown as IncomingMessage)
      if (isRobots || status === 200) { res.emit('data', Buffer.from(isRobots ? robots : '<form></form>')); res.emit('end'); req.emit('close') }
    })
    return req
  }
  return { calls, io: { resolve: async () => ['8.8.8.8'], request: mock as unknown as typeof request } }
}

test('native GET transport pins validated DNS, verifies TLS, carries no credentials and enforces budget', async () => {
  const mock = transport()
  const getter = new PublicGetter('https://synthetic.example/contact', 2, mock.io)
  await getter.fetch('https://synthetic.example/contact', 'document')
  expect(getter.count).toBe(2)
  for (const call of mock.calls) {
    expect(call.options.method).toBe('GET'); expect(call.options.rejectUnauthorized).toBe(true)
    expect(call.options.agent).toBe(false); expect(call.options.ca).toBeTruthy()
    expect(call.options.headers).not.toHaveProperty('Authorization'); expect(call.options.headers).not.toHaveProperty('Cookie')
    call.options.lookup!('synthetic.example', { all: false }, (_error, address, family) => { expect(address).toBe('8.8.8.8'); expect(family).toBe(4) })
    call.options.lookup!('synthetic.example', { all: true }, (_error, addresses) => expect(addresses).toEqual([{ address: '8.8.8.8', family: 4 }]))
  }
  await expect(getter.fetch('https://synthetic.example/other', 'document')).rejects.toThrow('GET_BUDGET')
  expect(mock.calls).toHaveLength(2)
})

test('unsafe DNS and foreign origins are rejected before any request', async () => {
  for (const addresses of [['127.0.0.1'], ['8.8.8.8', '10.0.0.1'], []]) {
    const mock = transport(); mock.io.resolve = async () => addresses
    const getter = new PublicGetter('https://synthetic.example', 32, mock.io)
    await expect(getter.fetch('https://synthetic.example', 'document')).rejects.toThrow('UNSAFE_DNS')
    expect(mock.calls).toHaveLength(0)
  }
  const mock = transport(); const getter = new PublicGetter('https://synthetic.example', 32, mock.io)
  await expect(getter.fetch('https://other.example', 'document')).rejects.toThrow('FOREIGN_ORIGIN')
  expect(mock.calls).toHaveLength(0)
})

test('robots, redirect and wrong MIME stop the native reader', async () => {
  for (const [status, robots, mime, reason] of [
    [200, 'User-agent: *\nDisallow: /contact', 'text/html', 'ROBOTS_BLOCKED'],
    [302, '', 'text/html', 'HTTP_OR_REDIRECT_REJECTED'],
    [200, '', 'application/json', 'MIME_REJECTED'],
  ] as const) {
    const mock = transport(status, robots, mime)
    await expect(new PublicGetter('https://synthetic.example/contact', 32, mock.io).fetch('https://synthetic.example/contact', 'document')).rejects.toThrow(reason)
    expect(mock.calls.length).toBeLessThanOrEqual(2)
  }
})
