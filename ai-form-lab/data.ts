export const cases = ['html', 'dynamic', 'confirmation', 'iframe', 'selection', 'consent', 'invalid'] as const;
export const values = { name: '匿名テスト', company: '匿名テスト株式会社', email: 'fixture@example.com', message: 'localhostの模擬問い合わせです。最終送信しません。' };
export function expected(scenario: string) {
  return { ...values, ...(scenario === 'invalid' ? { email: 'invalid-email' } : {}),
    ...(scenario === 'selection' ? { topic: 'business', reply: 'email' } : {}),
    ...(scenario === 'consent' ? { privacy: 'agree' } : {}) };
}
