import { spawn } from 'node:child_process';
import { dirname, resolve as resolvePath } from 'node:path';
import { existsSync, mkdirSync, renameSync, writeFileSync } from 'node:fs';
import { startFixture } from '../frontend/form-lab/fixtures.ts';
const mode = process.argv[2];
if (!['ai', 'baseline'].includes(mode)) throw new Error('Mode must be ai or baseline');
if (!process.env.npm_execpath) throw new Error('Use npm run test:ai or npm run test:baseline');
if (mode === 'ai' && !process.env.OPENAI_API_KEY) throw new Error('OPENAI_API_KEY required in process environment');
mkdirSync('results', { recursive: true });
const stamp = new Date().toISOString().replaceAll(':', '-');
for (const path of [`results/${mode}`, `results/${mode}-metrics.jsonl`, `results/${mode}-safety.json`,
  ...(mode === 'ai' ? ['results/model-usage.jsonl', 'results/model-reservations.jsonl'] : [])]) {
  if (existsSync(path)) renameSync(path, `${path}.previous-${stamp}`);
}
const fixture = await startFixture(true);
let exit = 1;
try {
  exit = await new Promise<number>(resolve => {
    const child = spawn(process.execPath, [resolvePath(dirname(process.env.npm_execpath!), 'npx-cli.js'),
      '--no-install', 'e2e', 'run', '--tag', mode,
      '--repeat-each', '2', '--no-cache', '--output', `results/${mode}`, '--reporter', 'list,markdown',
      ...(mode === 'ai' ? ['--max-failures', '1'] : [])], {
      stdio: 'inherit', env: { ...process.env, LAB_URLS: JSON.stringify(fixture.urls), E2E_TELEMETRY_DISABLED: '1' },
    });
    child.on('error', () => resolve(3));
    child.on('exit', code => resolve(code ?? 3));
  });
} finally {
  writeFileSync(`results/${mode}-safety.json`, JSON.stringify({ postRequests: fixture.postCount(), forbiddenRequests: fixture.forbiddenCount(), productionConnected: false }));
  await fixture.stop();
}
process.exitCode = exit;
