import { defineConfig, devices } from '@playwright/test'

// UI-only fixtures: no database, credentials, paid API or external form access.
export default defineConfig({
  testDir: './operator-tests', outputDir: './test-results/operator-guide', workers: 1,
  use: { baseURL: 'http://127.0.0.1:15174' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['iPhone 13'], defaultBrowserType: 'chromium' } },
  ],
  webServer: { command: 'npm run dev -- --port 15174', url: 'http://127.0.0.1:15174', reuseExistingServer: false },
})
