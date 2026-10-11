import { test, expect } from '@playwright/test'
import { startFixture, scenarios, type Fixture } from './fixtures'
import { anonymousProposal, runPoc, installGuard } from './browser-poc'

let fixture: Fixture
test.beforeEach(async () => { fixture = await startFixture() })
test.afterEach(async () => { await fixture.stop() })

for (const scenario of [...scenarios, 'rendered']) {
  test(`input only ${scenario}: read back without confirmation or send`, async ({ browser }, info) => {
    const result = await runPoc(browser, fixture, scenario, anonymousProposal, 12, 5000,
      info.project.name === 'mobile' ? 'mobile' : 'desktop', true)
    expect(result.reason).toBe('FIXTURE_INPUT_VERIFIED')
    expect(result.inputReadbackVerified).toBe(true)
    expect(result.confirmationReached).toBe(false)
    expect(result.executionAllowed).toBe(false)
    expect(result.salesAuthorization).toBe('UNKNOWN')
    expect(result.log).toContain('NETWORK_FROZEN_BEFORE_INPUT')
    expect(result.log).not.toContain('PREVIEW_ONLY')
    expect(result.log.at(-1)).toBe('STOP_BEFORE_CONFIRMATION_OR_SEND')
    expect(result.blockedRequests).toBe(0)
    expect(fixture.postCount()).toBe(0)
    expect(fixture.forbiddenCount()).toBe(0)
    await info.attach('input-only-result', { body: JSON.stringify(result), contentType: 'application/json' })
  })
}

for (const [scenario, reason] of [
  ['prohibited', 'SALES_PROHIBITED'], ['captcha', 'CAPTCHA'],
  ['changed', 'STRUCTURE_CHANGED'], ['lateProhibited', 'SALES_PROHIBITED'],
  ['autosave', 'NETWORK_BLOCKED'], ['getAutosave', 'NETWORK_BLOCKED'],
  ['submitOnInput', 'NETWORK_BLOCKED'], ['unknown', 'REQUIRED_FIELD_UNKNOWN'],
  ['password', 'HUMAN_INPUT_REQUIRED'],
]) {
  test(`input only stops ${scenario}`, async ({ browser }, info) => {
    const result = await runPoc(browser, fixture, scenario, anonymousProposal, 12, 5000,
      info.project.name === 'mobile' ? 'mobile' : 'desktop', true)
    expect(result.reason).toBe(reason)
    expect(result.inputReadbackVerified).toBe(false)
    expect(result.confirmationReached).toBe(false)
    expect(result.executionAllowed).toBe(false)
    expect(result.log).not.toContain('PREVIEW_ONLY')
    if (scenario === 'prohibited' || scenario === 'captcha') expect(result.log).not.toContain('FILL')
    if (scenario === 'lateProhibited') expect(result.log.filter(entry => entry === 'FILL')).toHaveLength(1)
    expect(fixture.postCount()).toBe(0)
    expect(fixture.forbiddenCount()).toBe(0)
  })
}

test('frozen phase blocks even allowlisted GET and WebSocket traffic', async ({ browser }) => {
  const context = await browser.newContext({ serviceWorkers: 'block' })
  const phase = { frozen: false }
  const state = { blockedRequests: 0, log: [] as string[] }
  try {
    await installGuard(context, new Set([fixture.urls.html]), 5000, performance.now(), state, phase)
    const page = await context.newPage()
    await page.goto(fixture.urls.html)
    phase.frozen = true
    expect(await page.evaluate(() => fetch(location.href).then(() => true, () => false))).toBe(false)
    expect(state.blockedRequests).toBe(1)
    await page.evaluate(() => { new WebSocket(location.origin.replace('http:', 'ws:') + '/socket') })
    await expect.poll(() => state.blockedRequests).toBe(2)
    expect(state.log).toContain('WEBSOCKET_BLOCKED')
    expect(fixture.postCount()).toBe(0)
    expect(fixture.forbiddenCount()).toBe(0)
  } finally { await context.close() }
})

test('invalid values stop without clicking confirmation', async ({ browser }) => {
  const result = await runPoc(browser, fixture, 'invalid', {
    ...anonymousProposal, values: { ...anonymousProposal.values, email: 'invalid-email' },
  }, 12, 5000, 'desktop', true)
  expect(result.reason).toBe('FORM_VALIDATION_ERROR')
  expect(result.inputReadbackVerified).toBe(false)
  expect(result.confirmationReached).toBe(false)
  expect(fixture.postCount()).toBe(0)
})

test('consent is not inferred in input only mode', async ({ browser }) => {
  const result = await runPoc(browser, fixture, 'consent', { ...anonymousProposal, consents: {} }, 12, 5000, 'desktop', true)
  expect(result.reason).toBe('CONSENT_REVIEW_REQUIRED')
  expect(result.log).not.toContain('FILL')
  expect(result.inputReadbackVerified).toBe(false)
  expect(fixture.postCount()).toBe(0)
})

test('input only and preview are different payload and operation snapshots', async ({ browser }) => {
  const input = await runPoc(browser, fixture, 'html', anonymousProposal, 12, 5000, 'desktop', true)
  const preview = await runPoc(browser, fixture, 'html')
  expect(input.inputReadbackVerified).toBe(true)
  expect(preview.confirmationReached).toBe(true)
  expect(input.payloadHash).not.toBe(preview.payloadHash)
  expect(input.fingerprint).not.toBe(preview.fingerprint)
  expect(fixture.postCount()).toBe(0)
})
