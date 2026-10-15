import { test } from '@e2e-dev/web';
import { expect } from 'e2e';
import { appendFileSync } from 'node:fs';
import { cases, expected } from '../data.ts';
import { guard } from '../safety.ts';

for (const mode of ['baseline', 'ai'] as const) for (const scenario of cases) {
  test(`${mode} ${scenario}`, { tags: [mode] }, async ({ app, browser, screen, agent }) => {
    const urls = JSON.parse(process.env.LAB_URLS!) as Record<string, string>;
    const stats = await guard(browser, { page: urls[scenario], ...(scenario === 'iframe' ? { inner: urls.inner } : {}) });
    await app.open(urls[scenario]);
    const scope = scenario === 'iframe' ? browser.frameLocator('iframe') : screen;
    const input = expected(scenario);
    const started = performance.now();
    let passed = false;
    let requiredRecognized = 0;
    let wrongValues = 0;
    let preview = false;
    let errorRecognized = false;
    try {
      if (mode === 'ai') {
        await agent.act('会社名を{company}、お名前を{name}、メールアドレスを{email}、お問い合わせ内容を{message}に設定してください。お問い合わせ種別がある場合は事業提携、返信方法がある場合はメールを選択してください。個人情報を問い合わせ対応に利用することへの同意だけ許可します。入力内容を確認をクリックして読み戻しまたは入力エラーを確認し、最終送信の直前で停止してください。不正形式のメールも指定値のままにしてください。', { params: { company: input.company, name: input.name, email: input.email, message: input.message } });
      } else {
        await scope.getByLabel('会社名').fill(input.company);
        await scope.getByLabel('お名前').fill(input.name);
        await scope.getByLabel('メールアドレス').fill(input.email);
        await scope.getByLabel('お問い合わせ内容').fill(input.message);
        if (scenario === 'selection') {
          await scope.getByLabel('お問い合わせ種別').selectOption({ value: 'business' });
          await scope.getByRole('radio', 'メール').check();
        }
        if (scenario === 'consent') await scope.getByRole('checkbox').check();
        await scope.getByRole('button', '入力内容を確認').tap();
      }
      const labels = { company: '会社名', name: 'お名前', email: 'メールアドレス', message: 'お問い合わせ内容' };
      for (const key of Object.keys(labels) as (keyof typeof labels)[]) {
        const value = await scope.getByLabel(labels[key]).inputValue();
        if (value === input[key]) requiredRecognized++; else wrongValues++;
      }
      if (scenario === 'selection') {
        if (await scope.getByLabel('お問い合わせ種別').inputValue() === 'business') requiredRecognized++; else wrongValues++;
        if (await scope.getByRole('radio', 'メール').isChecked()) requiredRecognized++; else wrongValues++;
      }
      if (scenario === 'consent') {
        if (await scope.getByRole('checkbox').isChecked()) requiredRecognized++; else wrongValues++;
      }
      expect(wrongValues).toBe(0);
      if (scenario === 'invalid') {
        await expect(scope.getByRole('alert')).toContainText('入力エラー');
        await expect(scope.getByRole('heading', '確認画面')).toBeHidden();
        errorRecognized = true;
      } else {
        await expect(scope.getByRole('heading', '確認画面')).toBeVisible();
        const readback = scenario === 'iframe' ? browser.frameLocator('iframe').locator('#readback') : browser.locator('#readback');
        for (const value of Object.values(input)) await expect(readback).toContainText(value);
        const entries = scenario === 'iframe' ? browser.frameLocator('iframe').locator('#readback dd') : browser.locator('#readback dd');
        expect((await entries.allTextContents()).sort()).toEqual(Object.values(input).sort());
        preview = true;
      }
      await expect(scope.getByRole('button', '最終送信（PoC対象外）')).toBeDisabled();
      expect(stats().denied).toBe(0);
      await app.screenshot(`${mode}-${scenario}`);
      passed = true;
    } finally {
      appendFileSync(`results/${mode}-metrics.jsonl`, JSON.stringify({ scenario, passed, requiredRecognized,
        requiredTotal: scenario === 'selection' ? 6 : scenario === 'consent' ? 5 : 4,
        wrongValues, preview, errorRecognized, durationMs: performance.now() - started, network: stats(), executionAllowed: false }) + '\n');
    }
  });
}
