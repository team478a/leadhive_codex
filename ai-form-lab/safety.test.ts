import test from 'node:test';
import assert from 'node:assert/strict';
import { startFixture } from '../frontend/form-lab/fixtures.ts';
import { allowed, guardedBody } from './safety.ts';
import { mkdirSync, mkdtempSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

test('exact loopback URL and GET only; no credentials/query/fragment/external/other local service', () => {
  const urls = { html: 'http://127.0.0.1:49152/lab/html' };
  assert.equal(allowed(urls.html, 'GET', urls), true);
  for (const method of ['POST', 'PUT', 'DELETE', 'HEAD']) assert.equal(allowed(urls.html, method, urls), false);
  for (const url of ['https://example.com/', 'http://127.0.0.1:49153/lab/html', urls.html + '?x', urls.html + '#x', 'http://user@127.0.0.1:49152/lab/html']) assert.equal(allowed(url, 'GET', urls), false);
});

test('provider failure stops calls, enforces endpoint/output bound, logs no credential or payload', async () => {
  const originalCwd = process.cwd();
  const originalFetch = globalThis.fetch;
  mkdirSync('results', { recursive: true });
  const isolated = mkdtempSync(resolve('results/provider-test-'));
  let calls = 0;
  try {
    process.chdir(isolated);
    mkdirSync('results');
    globalThis.fetch = async (_url, init) => {
      calls++;
      const body = JSON.parse(String(init?.body));
      assert.equal(body.max_output_tokens, 1024);
      assert.equal(body.store, false);
      return new Response(JSON.stringify({ error: { code: 'credit_balance_exhausted' } }), { status: 429 });
    };
    const { providerFetch } = await import('./model.ts');
    await assert.rejects(providerFetch('https://example.com/', {}), /PROVIDER_DENIED/);
    await providerFetch('https://api.openai.com/v1/responses', { body: JSON.stringify({ input: 'SYNTHETIC_PAYLOAD', model: 'gpt-5.4-mini-2026-03-17' }), headers: { Authorization: 'SYNTHETIC_CREDENTIAL' } });
    assert.equal((await providerFetch('https://api.openai.com/v1/responses', {})).status, 400);
    assert.equal(calls, 1);
    const ledger = readFileSync('results/model-usage.jsonl', 'utf8');
    assert.match(ledger, /credit_balance_exhausted/);
    assert.doesNotMatch(ledger, /SYNTHETIC_PAYLOAD|SYNTHETIC_CREDENTIAL/);
  } finally {
    globalThis.fetch = originalFetch;
    process.chdir(originalCwd);
  }
});

test('redirect is rejected before following, POST denied before network, fixture final action disabled', async () => {
  const fixture = await startFixture(true);
  try {
    const body = await guardedBody(fixture.urls.html, 'GET', { html: fixture.urls.html });
    assert.match(body.body, /会社名/);
    assert.match(body.body, /type="submit" disabled/);
    await assert.rejects(guardedBody(fixture.urls.redirect, 'GET', { redirect: fixture.urls.redirect }), /REDIRECT_DENIED/);
    await assert.rejects(guardedBody(fixture.urls.html, 'POST', fixture.urls), /NETWORK_DENIED/);
    assert.equal(fixture.postCount(), 0);
    assert.equal(fixture.forbiddenCount(), 0);
  } finally { await fixture.stop(); }
});
