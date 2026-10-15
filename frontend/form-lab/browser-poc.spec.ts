import { test, expect, type Browser } from '@playwright/test'
import { startFixture, scenarios, type Fixture } from './fixtures'
import { anonymousProposal, installGuard, runPoc as executePoc, type Proposal } from './browser-poc'

let fixture: Fixture
let viewMode: 'desktop' | 'mobile'
test.beforeEach(async ({ browser }, testInfo) => {
  expect(browser.isConnected()).toBe(true)
  fixture = await startFixture()
  viewMode = testInfo.project.name === 'mobile' ? 'mobile' : 'desktop'
})
test.afterEach(async () => { await fixture.stop() })

async function runPoc(browser: Browser, fixture: Fixture, scenario: string, proposal: Proposal = anonymousProposal, maxActions = 12) {
  return executePoc(browser, fixture, scenario, proposal, maxActions, 5000, viewMode)
}

for (const scenario of scenarios) {
  test(`preview ${scenario}`, async ({ browser }, testInfo) => {
    const result = await runPoc(browser, fixture, scenario)
    expect(result.operationStatus).toBe('BROWSER_VERIFIED')
    expect(result.confirmationReached).toBe(true)
    const required = [...new Set(result.controls.filter(control => control.required).map(control => control.name))].sort()
    expect(required).toEqual((['name', 'email', 'message',
      ...(scenario === 'selection' ? ['topic', 'reply'] : []), ...(scenario === 'consent' ? ['privacy'] : [])]).sort())
    expect(result.salesAuthorization).toBe('UNKNOWN')
    expect(result.executionAllowed).toBe(false)
    expect(result.log.at(-1)).toBe('STOP_BEFORE_FINAL_SEND')
    expect(result.blockedRequests).toBe(0)
    expect(result.viewportWidth).toBe(viewMode === 'mobile' ? 390 : 1280)
    expect(fixture.postCount()).toBe(0)
    await testInfo.attach('poc-result', { body: JSON.stringify(result), contentType: 'application/json' })
  })
}

for (const [scenario, reason] of [
  ['prohibited', 'SALES_PROHIBITED'], ['captcha', 'CAPTCHA'],
  ['password', 'HUMAN_INPUT_REQUIRED'], ['unknown', 'REQUIRED_FIELD_UNKNOWN'],
  ['robots', 'ROBOTS_BLOCKED'], ['terms', 'TERMS_BLOCKED'],
] as const) {
  test(`stop ${scenario}`, async ({ browser }) => {
    const result = await runPoc(browser, fixture, scenario)
    expect(result.reason).toBe(reason)
    expect(result.operationStatus).not.toBe('BROWSER_VERIFIED')
    expect(result.confirmationReached).toBe(false)
    expect(result.executionAllowed).toBe(false)
    expect(result.log).not.toContain('FILL')
    expect(fixture.postCount()).toBe(0)
    if (scenario === 'prohibited') expect(result.salesAuthorization).toBe('PROHIBITED')
  })
}

test('missing consent is never automatically checked', async ({ browser }) => {
  const result = await runPoc(browser, fixture, 'consent', { ...anonymousProposal, consents: {} })
  expect(result.reason).toBe('CONSENT_REVIEW_REQUIRED')
  expect(result.operationStatus).toBe('HUMAN_REQUIRED')
  expect(result.log).not.toContain('FILL')
  expect(fixture.postCount()).toBe(0)
})

test('unknown selection is not guessed', async ({ browser }) => {
  const result = await runPoc(browser, fixture, 'selection', { ...anonymousProposal, selections: { topic: 'unknown' } })
  expect(result.reason).toBe('CHOICE_REVIEW_REQUIRED')
  expect(result.log).not.toContain('FILL')
  expect(fixture.postCount()).toBe(0)
})

test('input validation error stops before final operation', async ({ browser }) => {
  const result = await runPoc(browser, fixture, 'invalid', {
    ...anonymousProposal, values: { ...anonymousProposal.values, email: 'not-an-email' },
  })
  expect(result.reason).toBe('FORM_VALIDATION_ERROR')
  expect(result.confirmationReached).toBe(false)
  expect(result.executionAllowed).toBe(false)
  expect(fixture.postCount()).toBe(0)
})

test('operation budget is bounded', async ({ browser }) => {
  const result = await runPoc(browser, fixture, 'html', anonymousProposal, 3)
  expect(result.reason).toBe('OPERATION_BUDGET')
  expect(result.actions).toBe(3)
  expect(fixture.postCount()).toBe(0)
})

test('unregistered redirect is blocked before the next GET', async ({ browser }) => {
  const result = await runPoc(browser, fixture, 'redirect')
  expect(result.blockedRequests).toBeGreaterThan(0)
  expect(result.operationStatus).toBe('TECHNICAL_UNKNOWN')
  expect(result.executionAllowed).toBe(false)
  expect(fixture.postCount()).toBe(0)
  expect(fixture.forbiddenCount()).toBe(0)
})

test('POST and unregistered requests are blocked at the transport', async ({ browser }) => {
  const context = await browser.newContext({ serviceWorkers: 'block' })
  const state = { blockedRequests: 0, log: [] as string[] }
  try {
    await installGuard(context, new Set([fixture.urls.html]), 5000, performance.now(), state)
    const page = await context.newPage()
    await page.goto(fixture.urls.html)
    const result = await page.evaluate(async () => {
      const responses = await Promise.all([
        fetch('/never-send', { method: 'POST', body: 'synthetic' }).then(() => true, () => false),
        fetch('/unregistered-target').then(() => true, () => false),
      ])
      return responses
    })
    expect(result).toEqual([false, false])
    expect(state.blockedRequests).toBe(2)
    expect(fixture.postCount()).toBe(0)
    expect(fixture.forbiddenCount()).toBe(0)
  } finally { await context.close() }
})

test('arbitrary origins are rejected without opening a context', async ({ browser }) => {
  for (const origin of ['https://example.com', 'http://localhost:80', 'http://169.254.169.254']) {
    await expect(runPoc(browser, { ...fixture, origin }, 'html')).rejects.toThrow('Only owned loopback')
  }
  expect(fixture.postCount()).toBe(0)
})

test('changed payload requires a new snapshot hash', async ({ browser }) => {
  const first = await runPoc(browser, fixture, 'html')
  const second = await runPoc(browser, fixture, 'html', {
    ...anonymousProposal, values: { ...anonymousProposal.values, message: '変更した匿名本文' },
  })
  expect(first.payloadHash).not.toBe(second.payloadHash)
  expect(first.fingerprint).toBe(second.fingerprint)
  expect(second.executionAllowed).toBe(false)
  expect(fixture.postCount()).toBe(0)
})

test('changed structure stops before preview', async ({ browser }) => {
  const result = await runPoc(browser, fixture, 'changed')
  expect(result.reason).toBe('STRUCTURE_CHANGED')
  expect(result.confirmationReached).toBe(false)
  expect(result.executionAllowed).toBe(false)
  expect(fixture.postCount()).toBe(0)
})

test('unregistered iframe cannot receive input', async ({ browser }) => {
  const result = await runPoc(browser, fixture, 'foreign-frame')
  expect(result.operationStatus).toBe('TECHNICAL_UNKNOWN')
  expect(result.blockedRequests).toBeGreaterThan(0)
  expect(result.log).not.toContain('FILL')
  expect(fixture.forbiddenCount()).toBe(0)
  expect(fixture.postCount()).toBe(0)
})
