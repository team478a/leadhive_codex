// Synthetic fixture only: construct browser bytes without fetch, submit, or navigation.
const { createRequire } = require('node:module')
const path = require('node:path')
const load = createRequire(path.resolve(__dirname, '../../frontend/package.json'))
const { chromium } = load('@playwright/test')

async function main() {
  if (process.env.CF7_OFFLINE_ENCODING_TEST !== '1') throw Error('Explicit offline lab opt-in required')
  let raw = ''
  for await (const chunk of process.stdin) {
    raw += chunk
    if (raw.length > 200000) throw Error('Fixture size limit')
  }
  const fixture = JSON.parse(raw)
  const browser = await chromium.launch({ headless: true })
  try {
    const context = await browser.newContext({ offline: true, javaScriptEnabled: false })
    let requests = 0
    await context.route('**/*', route => { requests++; return route.abort() })
    const page = await context.newPage()
    const result = await page.evaluate(async ({ evidence, rows }) => {
      const form = document.createElement('form')
      const controls = Object.fromEntries(evidence.controls.map(c => [c.name, c]))
      const values = Object.fromEntries(rows.map(r => [r.name, r.values]))
      for (const name of evidence.dom_order) {
        const hidden = Object.hasOwn(evidence.hidden, name)
        const control = controls[name]
        const field = document.createElement(!hidden && control.kind === 'textarea' ? 'textarea' : 'input')
        field.name = name
        if (hidden) { field.type = 'hidden'; field.value = evidence.hidden[name] }
        else if (control.kind === 'checkbox') { field.type = 'checkbox'; field.value = control.checkbox_value; field.checked = values[name].length > 0 }
        else { if (control.kind !== 'textarea') field.type = control.kind; field.value = values[name][0] ?? '' }
        form.append(field)
      }
      document.body.append(form)
      // Constructing Request serializes FormData; it does not perform a request.
      const request = new Request('https://offline.invalid/', { method: 'POST', body: new FormData(form) })
      const bytes = new Uint8Array(await request.arrayBuffer())
      let binary = ''
      for (const byte of bytes) binary += String.fromCharCode(byte)
      return { content_type: request.headers.get('content-type'), body_base64: btoa(binary) }
    }, fixture)
    if (requests !== 0) throw Error('Unexpected request')
    process.stdout.write(JSON.stringify({ ...result, external_requests: requests }))
  } finally { await browser.close() }
}
main().catch(() => { process.stderr.write('Offline browser serialization failed\n'); process.exitCode = 1 })
