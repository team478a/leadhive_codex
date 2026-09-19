import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'

export default function setup() {
  const python = process.env.PYTHON || (process.platform === 'win32' ?
    '../backend/.venv/Scripts/python.exe' : '../backend/.venv/bin/python')
  process.env.E2E_EMAIL = `e2e-${randomBytes(8).toString('hex')}@example.com`
  process.env.E2E_PASSWORD = randomBytes(24).toString('hex')
  execFileSync(python, ['../backend/tests/e2e_user.py', 'create'], { env: process.env })
  return () => {
    execFileSync(python, ['../backend/tests/e2e_user.py', 'cleanup'], { env: process.env })
  }
}
