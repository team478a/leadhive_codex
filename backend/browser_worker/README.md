# Isolated browser worker (synthetic-only safety foundation)

This service is an offline-only foundation. It runs packaged synthetic HTML
fixtures, fills explicitly selected text-like controls, reads the values back,
and closes Chromium after every task. The `browser_form_analysis` OperationJob
uses the existing lease/cancel/recovery and active-job deduplication model, but
accepts packaged fixture names only. Neither its API nor its worker accepts
target URLs or external-domain lists. It does not visit real sites or submit
forms. The browser delivery flag remains fail-closed.

## Safety and resource limits

- One task at a time (`MAX_CONCURRENT_JOBS = 1`) and a 90-second hard timeout.
- A fresh Chromium process and isolated context are created for each task;
  context and browser are closed in `finally`, so cookies and browser memory do
  not carry over between tasks.
- Chromium is launched with the container-local `--proxy-server`, with proxy
  bypasses for loopback disabled, QUIC/WebRTC disabled, and Chromium hostname
  resolution blocked. Browser-context routing also aborts every fixture
  network request. The HTTPS CONNECT proxy only accepts allowlisted hosts on
  port 443, resolves DNS on each connection using the existing isolated pinned
  DNS resolver, rejects any non-public answer, and connects to the validated
  numeric address. A task without an approved site/domain policy has an empty
  allowlist. No arbitrary proxy or direct URL is accepted by the synthetic job.
- The reusable pre-navigation helper fetches `robots.txt` through that proxy
  before a page navigation and shares the `SafeFetcher` robots parser. Errors
  fail closed; 404 follows `SafeFetcher`'s allow behavior and 401/403 deny.
- Main-frame navigations are checked for password controls, login/sign-in
  wording, and login paths. A match stops the task. Downloads are disabled and
  cancelled, new windows are closed, file pickers are blocked, and form
  submission methods/events are intercepted.
- Only fixture names packaged under `fixtures/` can be opened. File inputs,
  checkboxes, radio buttons, password fields, and other unsupported controls
  cannot be filled by this B1 runner.
- A dedicated browser worker claims only `browser_form_analysis` jobs using
  `FOR UPDATE SKIP LOCKED`, renews leases while running, observes cancellation,
  and recovers expired jobs subject to the shared retry limit. The application
  worker explicitly excludes this operation type. The service writes a
  `browser-`-prefixed row to the existing `worker_heartbeats` table on startup
  and every 30 seconds.

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
non-root user. The current endpoint and worker remain synthetic-only, and this
service is not approved for visiting untrusted sites. The CONNECT proxy and
preflight helpers are implemented as prerequisites for a later approved phase;
they do not enable live navigation in this release. The tests use only
synthetic fixtures and localhost servers.

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
- httpcore 1.0.9: BSD-3-Clause; already present in LeadHive's backend lock and
  used by the shared pinned-read transport module.
- Its pinned runtime dependencies used here (AnyIO 4.15.1, certifi 2026.7.22,
  and h11 0.16.0) are already present in the backend lock; licenses are MIT,
  Mozilla Public License 2.0, and MIT, respectively.
- Playwright's packaged Chromium: Chromium's third-party licenses; provided by
  the pinned Microsoft Playwright image.
- SQLAlchemy, psycopg, pydantic-settings, and their pinned support packages are
  already used by LeadHive; see `requirements.lock` for the exact versions.
- Crawlee, browser-use, Stagehand, Firefox autofill code, stealth plugins, and
  CAPTCHA-solving services are not added or used in B1.
