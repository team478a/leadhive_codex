import { defineConfig, devices } from '@playwright/test'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  testDir: '.', testMatch: '*.spec.ts', workers: 1, fullyParallel: false,
  timeout: 30_000, expect: { timeout: 5000 },
  outputDir: '../test-results/form-browser-poc',
  reporter: [['list'], ['json', { outputFile: fileURLToPath(new URL('../test-results/form-browser-poc/report.json', import.meta.url)) }]],
  use: { trace: 'off', screenshot: 'off', video: 'off' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['iPhone 13'], defaultBrowserType: 'chromium' } },
  ],
})
