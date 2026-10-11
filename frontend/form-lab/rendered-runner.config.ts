import { defineConfig } from '@playwright/test'

if (process.env.LEADHIVE_RENDERED_INPUT !== '1' || !process.env.LEADHIVE_RENDERED_INPUT_FILE) {
  throw Error('Rendered input is OFF. Explicitly enable it and specify a private snapshot file.')
}
export default defineConfig({ testDir: '.', testMatch: 'rendered-runner.case.ts', workers: 1,
  timeout: 30_000, outputDir: '../test-results/rendered-input-runner', reporter: 'list',
  use: { trace: 'off', screenshot: 'off', video: 'off' } })
