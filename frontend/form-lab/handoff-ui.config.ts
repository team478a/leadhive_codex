import { defineConfig, devices } from '@playwright/test'
export default defineConfig({ testDir: '.', testMatch: 'handoff-ui.case.ts', workers: 1, timeout: 30_000,
  use: { baseURL: 'http://127.0.0.1:15179', screenshot: 'off', trace: 'off', video: 'off' },
  outputDir: '../test-results/handoff-ui',
  webServer: { command: 'npm run dev -- --host 127.0.0.1 --port 15179 --strictPort', url: 'http://127.0.0.1:15179', reuseExistingServer: false },
  projects: [{ name: 'desktop', use: devices['Desktop Chrome'] }, { name: 'mobile', use: { ...devices['iPhone 13'], defaultBrowserType: 'chromium' } }] })
