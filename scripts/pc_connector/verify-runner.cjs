// Integrity check, not a signature or an execution attestation.
const fs = require('node:fs'); const path = require('node:path'); const crypto = require('node:crypto')
try {
  const root = path.resolve(__dirname, '../..')
  const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'))
  if (manifest.definition !== 'pc-input-package-v1' || manifest.outbound !== false) throw Error()
  if (!manifest.files || !['runtime/node.exe', 'runtime/chromium/chrome.exe', 'frontend/node_modules/playwright/cli.js',
    'frontend/form-lab/offline-runner.config.ts', 'scripts/pc_connector/Run-Offline-Input.ps1'].every(name => name in manifest.files)) throw Error()
  for (const [name, hash] of Object.entries(manifest.files)) {
    if (!/^[a-f0-9]{64}$/.test(hash) || path.isAbsolute(name) || name.includes(':') || name.split(/[\\/]/).includes('..')) throw Error()
    const target = path.join(root, name); const real = fs.realpathSync(target)
    if (!real.toLowerCase().startsWith((root + path.sep).toLowerCase())) throw Error()
    if (crypto.createHash('sha256').update(fs.readFileSync(target)).digest('hex') !== hash) throw Error()
  }
  console.log('Package integrity PASS')
} catch { console.error('Package integrity FAILED. Extract a fresh trusted package.'); process.exitCode = 1 }
