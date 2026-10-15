import { test } from '@playwright/test'
import { readFile, stat, writeFile } from 'node:fs/promises'
import { runLiveInput, transferLiveResult } from './live-input'
test('one human-requested live form input, no confirmation or send', async ({ browser }, info) => {
  const path = process.env.LEADHIVE_LIVE_INPUT_FILE!
  if ((await stat(path)).size > 100_000) throw Error('TASK_SIZE_LIMIT')
  const task = JSON.parse(await readFile(path, 'utf8')) as unknown
  let result: unknown
  try { result = await runLiveInput(browser, task, process.env.LEADHIVE_LIVE_INPUT_SERVER!) }
  catch (error) {
    const t = task && typeof task === 'object' ? task as Record<string, unknown> : {}
    const code = error instanceof Error && /^[A-Z_]{3,100}$/.test(error.message) ? error.message : 'LIVE_INPUT_STOPPED'
    result = { definition: 'live-form-input-only-v1', status: 'TECHNICAL_UNKNOWN', reason: code,
      trialId: t.trialId, companyId: t.companyId, projectId: t.projectId, requestHash: t.requestHash,
      fieldsFilled: 0, blockedRequests: 0, confirmationReached: false, source: 'PC_REPORTED_UNVERIFIED', sent: false, approvalGranted: false, executionAllowed: false }
  }
  await writeFile(info.outputPath('live-input-result.json'), JSON.stringify(result, null, 2), 'utf8')
  const transfer = await transferLiveResult(task, result, process.env.LEADHIVE_LIVE_INPUT_SERVER!)
  await writeFile(info.outputPath('result-transfer.json'), JSON.stringify({ transfer }), 'utf8')
  console.log(transfer === 'RECORDED' ? 'Unsent result recorded in LeadHive.' : transfer === 'FAILED'
    ? 'Result transfer not confirmed. Keep the local result JSON for manual import.' : 'Automatic transfer not requested.')
  console.log('Input-only result saved. No confirmation, approval or send.')
})
