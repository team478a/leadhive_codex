import { defineConfig, devices } from '@playwright/test'

const testDatabase = process.env.TEST_DATABASE_URL
if (!testDatabase || !new URL(testDatabase).pathname.endsWith('_test')) {
  throw new Error('Set TEST_DATABASE_URL to a dedicated PostgreSQL database ending in _test')
}
const python = process.env.PYTHON || (process.platform === 'win32' ?
  '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')

export default defineConfig({
  timeout: 60_000,
  expect: { timeout: 15_000 },
  testDir: './tests', workers: 1, fullyParallel: false,
  globalSetup: './tests/setup.ts',
  use: { baseURL: 'http://localhost:15173', screenshot: 'only-on-failure' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['iPhone 13'], defaultBrowserType: 'chromium' } },
  ],
  webServer: [
    {
      command: `"${python}" -m uvicorn app.main:app --host 127.0.0.1 --port 18039`,
      url: 'http://127.0.0.1:18039/api/health', reuseExistingServer: false,
      env: {
        OUTBOUND_ENABLED: 'false', DATABASE_URL: testDatabase, CORS_ORIGINS: 'http://localhost:15173', COOKIE_SECURE: 'false',
        SETTINGS_ENCRYPTION_KEY: 'TXo8wyai6a-uQTN15jhU7_la86LCSPzFR6pMXGkYslM=',
        HUMAN_APPROVED_EMAIL_ENABLED: 'false', SMTP_FROM_EMAIL: 'sender@example.com', SMTP_FROM_NAME: 'A2 Human',
        FORM_ADAPTER_PREPARATION_ENABLED: 'true', // Dedicated _test DB, reservation only.
        CF7_CANDIDATE_PREPARATION_ENABLED: process.env.CF7_E2E_DISPOSABLE_DATABASE === 'true' ? 'true' : 'false',
        PUBLIC_APP_URL: 'https://leadhive.example',
      },
    },
    {
      command: 'npm run dev -- --port 15173', url: 'http://localhost:15173',
      reuseExistingServer: false, env: { API_PROXY_TARGET: 'http://127.0.0.1:18039' },
    },
  ],
})
