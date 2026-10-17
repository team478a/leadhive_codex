# Isolated browser worker (B1)

This service is an offline-only foundation. It runs packaged synthetic HTML
fixtures, fills explicitly selected text-like controls, reads the values back,
and closes Chromium after every task. It does not accept target URLs, read
production queues, visit real sites, or submit forms. The browser delivery flag
is fail-closed until a later approved phase implements dispatch integration.

## Safety and resource limits

- One task at a time (`MAX_CONCURRENT_JOBS = 1`) and a 90-second hard timeout.
- A fresh Chromium process and isolated context are created for each task;
  context and browser are closed in `finally`, so cookies and browser memory do
  not carry over between tasks.
- Browser-context routing aborts every network request. Service workers are
  blocked, downloads are disabled/cancelled, popups are blocked, and form
  submission methods/events are intercepted.
- Only fixture names packaged under `fixtures/` can be opened. File inputs,
  checkboxes, radio buttons, password fields, and other unsupported controls
  cannot be filled by this B1 runner.
- The service writes a `browser-`-prefixed row to the existing
  `worker_heartbeats` table on startup and every 30 seconds.

## Local synthetic tests

From `backend/`, install `browser_worker/requirements.lock` and run:

```powershell
python -m pip install -r browser_worker/requirements.lock pytest==9.1.1
python -m playwright install chromium
python -m browser_worker --self-test
python -m pytest browser_worker/tests -q
```

The official Playwright Python image already contains Chromium and its system
dependencies; the Python package is installed separately. The image runs as a
non-root user. This B1 image is not approved for visiting untrusted sites.
Before any live browsing is enabled, a later phase must add and test OS-level
egress controls, robots.txt and public-IP checks, per-job approved-domain
allowlists, login detection on navigated pages, and lease/cancel/recovery queue
integration.

## Candidate service settings (not provisioned)

The Render service is intentionally not added to `render-staging.yaml` because
that file provisions paid resources and the owner has not selected a host or
budget. A future Blueprint entry will use `type: worker`, the Dockerfile at
`backend/browser_worker/Dockerfile`, one instance, the same database, and
`BROWSER_FORM_DELIVERY_ENABLED=false`. The initial planning estimate is one
vCPU and 2 GB RAM for a single Chromium job; actual plan and monthly cost remain
an owner decision. Do not synchronize a paid service from this example.

## Dependencies and licenses

- Playwright for Python 1.63.0: Apache-2.0; the new browser automation runtime.
- Playwright's packaged Chromium: Chromium's third-party licenses; provided by
  the pinned Microsoft Playwright image.
- SQLAlchemy, psycopg, pydantic-settings, and their pinned support packages are
  already used by LeadHive; see `requirements.lock` for the exact versions.
- Crawlee, browser-use, Stagehand, Firefox autofill code, stealth plugins, and
  CAPTCHA-solving services are not added or used in B1.
