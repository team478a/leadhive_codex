import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { cases } from './data.ts';
function lines(file: string): Record<string, any>[] {
  return existsSync(file) ? readFileSync(file, 'utf8').trim().split('\n').filter(Boolean).map(line => JSON.parse(line)) : [];
}
function summarize(mode: string) {
  const path = `results/${mode}/report.json`;
  if (!existsSync(path)) return { status: 'NOT_RUN', comparisons: cases.map(scenario => ({ scenario, measured: false })) };
  const report = JSON.parse(readFileSync(path, 'utf8'));
  const metrics = lines(`results/${mode}-metrics.jsonl`);
  const comparisons = cases.map(scenario => {
    const results = report.run.results.filter((r: any) => r.selected && r.titlePath.join(' ').endsWith(scenario));
    const rows = metrics.filter(r => r.scenario === scenario);
    const passed = results.filter((r: any) => r.status === 'passed').length;
    const providerBlocked = mode === 'ai' && report.run.results.some((r: any) => JSON.stringify(r.attempts).includes('MODEL_PROVIDER_FAILED'));
    return { scenario, trials: results.length, passed, measurementStatus: providerBlocked ? 'PROVIDER_BLOCKED' : 'MEASURED',
      successRate: !providerBlocked && results.length ? passed / results.length : null,
      requiredRecognitionRate: !providerBlocked && rows.length ? rows.reduce((n, r) => n + r.requiredRecognized, 0) / rows.reduce((n, r) => n + r.requiredTotal, 0) : null,
      wrongValues: !providerBlocked && rows.length ? rows.reduce((n, r) => n + r.wrongValues, 0) : null,
      previewReached: providerBlocked ? null : rows.filter(r => r.preview).length,
      errorsRecognized: providerBlocked ? null : rows.filter(r => r.errorRecognized).length,
      durationMs: rows.length ? rows.map(r => r.durationMs) : null,
      repeatable: providerBlocked ? null : results.length === 2 && passed === 2 };
  });
  return { status: report.run.status, summary: report.run.summary, comparisons,
    safety: JSON.parse(readFileSync(`results/${mode}-safety.json`, 'utf8')),
    modelTokensReportedByRunner: report.run.usage.modelTokens ?? null };
}
const usage = lines('results/model-usage.jsonl');
const knownUsage = usage.every(r => r.usage?.input_tokens != null && r.usage?.output_tokens != null);
const inputTokens = knownUsage ? usage.reduce((n, r) => n + r.usage.input_tokens, 0) : null;
const outputTokens = knownUsage ? usage.reduce((n, r) => n + r.usage.output_tokens, 0) : null;
const cost = inputTokens === null || outputTokens === null ? null : (inputTokens * 0.75 + outputTokens * 4.5) / 1e6;
writeFileSync('results/comparison.json', JSON.stringify({ generatedAt: new Date().toISOString(),
  commit: execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(),
  model: 'gpt-5.4-mini-2026-03-17', priceSource: 'https://developers.openai.com/api/docs/models/gpt-5.4-mini',
  baseline: summarize('baseline'), ai: summarize('ai'),
  cost: { calls: usage.length, inputTokens, outputTokens, estimatedUsdNoCacheDiscount: cost, budgetUsd: 5,
    realFormSendSuccessRate: null }, productionConnected: false }, null, 2) + '\n');
