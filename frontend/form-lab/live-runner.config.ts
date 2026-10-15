import { defineConfig } from '@playwright/test'
if (process.env.LEADHIVE_LIVE_FORM_INPUT !== '1' || !process.env.LEADHIVE_LIVE_INPUT_FILE || !process.env.LEADHIVE_LIVE_INPUT_SERVER) throw Error('Live input is OFF; explicit local opt-in, task and trusted server are required.')
export default defineConfig({ testDir: '.', testMatch: 'live-runner.case.ts', workers: 1, timeout: 75_000,
  outputDir: '../test-results/live-input-runner', reporter: 'list', use: { headless: false, trace: 'off', screenshot: 'off', video: 'off',
    launchOptions: process.env.LEADHIVE_OFFLINE_BROWSER_EXECUTABLE ? { executablePath: process.env.LEADHIVE_OFFLINE_BROWSER_EXECUTABLE } : {} } })
