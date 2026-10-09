import { createOpenAI } from '@ai-sdk/openai';
import { appendFileSync, existsSync, readFileSync } from 'node:fs';

const prior = existsSync('results/model-usage.jsonl')
  ? readFileSync('results/model-usage.jsonl', 'utf8').trim().split('\n').filter(Boolean).map(line => JSON.parse(line)) : [];
const reservations = existsSync('results/model-reservations.jsonl')
  ? readFileSync('results/model-reservations.jsonl', 'utf8').trim().split('\n').filter(Boolean).map(line => JSON.parse(line)) : [];
let calls = reservations.length;
let reservedUsd = reservations.reduce((sum: number, row: { reserve: number }) => sum + row.reserve, 0);
let stopped = prior.some(row => row.status !== 200);
// Fixed text-only model and pricing; no arbitrary URL/provider overrides.
export const providerFetch: typeof fetch = async (input, init) => {
  if (stopped) return new Response(JSON.stringify({ error: { code: 'lab_provider_stopped', message: 'Provider failed; further calls disabled.' } }), { status: 400, headers: { 'Content-Type': 'application/json' } });
  if (String(input) !== 'https://api.openai.com/v1/responses') throw new Error('PROVIDER_DENIED');
  const payload = JSON.parse(String(init?.body));
  payload.max_output_tokens = 1024;
  payload.store = false;
  payload.stream = false;
  const body = JSON.stringify(payload);
  if (body.includes('data:image/') || Buffer.byteLength(body) > 64000) throw new Error('MODEL_INPUT_BUDGET');
  // UTF-8 bytes conservatively upper-bound text tokens, including tools/schema.
  const reserve = (Buffer.byteLength(body) * 0.75 + 1024 * 4.5) / 1e6;
  if (++calls > 112 || reservedUsd + reserve > 5) throw new Error('MODEL_COST_BUDGET');
  reservedUsd += reserve;
  // Reserve before I/O, so lost responses still count against the next invocation.
  appendFileSync('results/model-reservations.jsonl', JSON.stringify({ call: calls, reserve }) + '\n');
  const response = await fetch(input, { ...init, body, redirect: 'error' });
  let usage: unknown = null;
  let errorCode: string | null = null;
  try { const json = await response.clone().json(); usage = json.usage ?? null; errorCode = json.error?.code ?? null; } catch { /* retain unknown */ }
  appendFileSync('results/model-usage.jsonl', JSON.stringify({ call: calls, status: response.status, usage, errorCode, reserve, reservedUsd }) + '\n');
  stopped = !response.ok;
  return response;
};
export const model = createOpenAI({ fetch: providerFetch }).responses('gpt-5.4-mini-2026-03-17');
