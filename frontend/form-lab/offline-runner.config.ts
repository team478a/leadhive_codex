import { defineConfig } from '@playwright/test'

if (process.env.LEADHIVE_OFFLINE_FORM_INPUT !== '1' || !process.env.LEADHIVE_OFFLINE_INPUT_FILE) {
  throw new Error('Offline input runner is OFF. Explicitly enable it and specify a private local input file.')
}
export default defineConfig({ testDir: '.', testMatch: 'offline-runner.case.ts', workers: 1,
  timeout: 30_000, outputDir: '../test-results/offline-input-runner', reporter: 'list',
  use: { trace: 'off', screenshot: 'off', video: 'off',
    launchOptions: process.env.LEADHIVE_OFFLINE_BROWSER_EXECUTABLE
      ? { executablePath: process.env.LEADHIVE_OFFLINE_BROWSER_EXECUTABLE } : {} } })
