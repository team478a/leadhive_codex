import { readFileSync, writeFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import process from 'node:process'

const [input, output] = process.argv.slice(2)
const codeCommit = process.argv[4] || process.env.GITHUB_SHA || null
if (codeCommit && !/^[0-9a-f]{40}$/.test(codeCommit)) throw new Error('Invalid code commit')
if (!input || !output || input === output) throw new Error('Distinct input report and output required')
const report = JSON.parse(readFileSync(input, 'utf8'))
const stats = report.stats
if (stats.unexpected || stats.flaky || stats.skipped || !stats.expected) throw new Error('Only a complete successful run can be summarized')
const rows = []
function visit(suite) {
  for (const spec of suite.specs || []) for (const test of spec.tests || []) for (const result of test.results || []) {
    for (const attachment of result.attachments || []) if (attachment.name === 'poc-result') {
      rows.push({ project: test.projectName, scenario: spec.title.replace('preview ', ''),
        ...JSON.parse(attachment.body ? Buffer.from(attachment.body, 'base64').toString('utf8') : readFileSync(attachment.path, 'utf8')) })
    }
  }
  for (const child of suite.suites || []) visit(child)
}
for (const suite of report.suites) visit(suite)
if (rows.length !== 12 || rows.some(row => row.executionAllowed || row.operationStatus !== 'BROWSER_VERIFIED')) throw new Error('Expected six anonymous fixtures on desktop/mobile')
const required = rows.reduce((total, row) => total + new Set(row.controls.filter(control => control.required).map(control => control.name)).size, 0)
const summary = {
  definition: 'localhost-browser-preview-poc-v1',
  code_commit: codeCommit,
  successful_tests: stats.expected, failed_tests: stats.unexpected,
  fixture_trials: rows.length, operation_success_rate: 1,
  confirmation_reached: rows.filter(row => row.confirmationReached).length,
  required_groups_recognized: required, required_groups_expected: 42,
  required_recognition_rate: required / 42,
  erroneous_operations: stats.unexpected,
  duration_ms: stats.duration,
  external_company_requests: 0, form_post: 0, email_sent: 0, approvals: 0,
  real_form_success_rate: null, estimated_execution_cost: null,
  trials: rows.map(row => ({ scenario: row.scenario, project: row.project,
    duration_ms: row.durationMs, actions: row.actions, confirmation_reached: row.confirmationReached,
    required_groups: new Set(row.controls.filter(control => control.required).map(control => control.name)).size,
    operation_status: row.operationStatus, sales_authorization: row.salesAuthorization,
    viewport_width: row.viewportWidth,
    execution_allowed: row.executionAllowed })),
}
writeFileSync(output, JSON.stringify(summary, null, 2) + '\n')
