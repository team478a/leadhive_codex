# Isolated browser worker (synthetic and gated read-only analysis)

Synthetic mode runs packaged fixtures and can fill explicitly selected test
controls for offline tests. Rendered-page mode performs read-only, GET-only
analysis of server-selected contact-page URLs. It is gated by
`BROWSER_FORM_ANALYSIS_ENABLED`, which defaults to `false` in the API, worker
image, and staging configuration. Do not enable it or run real-site jobs until
Tanaka has approved the target scope. Neither mode submits forms.

## Safety and resource limits

- One task at a time (`MAX_CONCURRENT_JOBS = 1`) and a 90-second hard timeout.
- A fresh Chromium process and isolated context are created for each task;
  context and browser are closed in `finally`, so cookies and browser memory do
  not carry over between tasks.
- Chromium is launched with the container-local `--proxy-server`, with proxy
  bypasses for loopback disabled, QUIC/WebRTC disabled, and Chromium hostname
  resolution blocked. Browser-context routing aborts every synthetic-fixture
  network request. Rendered analysis permits only HTTPS GET requests to the
  target site's host. The HTTPS CONNECT proxy only accepts allowlisted hosts on
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
- The synthetic API accepts only fixture names packaged under `fixtures/`.
  Rendered-analysis targets are selected server-side from eligible saved
  `FormProfile` rows, revalidated by the worker, and capped at 100 per job.
- Rendered DOM snapshots redact input and textarea values before parsing. The
  existing field, consent/choice, CAPTCHA, sales-prohibition, and Japanese
  contact-policy checks are reused; fingerprints cover structural DOM only.
  External embeds are not opened and remain classified as unverified.
- Same-site analysis is serialized with a database advisory lock and waits at
  least one second after each page. Rendered-analysis mode never fills
  controls, clicks submit buttons, or sends form data.
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
non-root user. The synthetic endpoint remains fixture-only. The gated
rendered-analysis path is implemented but is not approved or enabled for
real-site use. Tests use only synthetic fixtures and localhost servers.

## Candidate service settings (not provisioned)

The proposed Render Background Worker is fully commented out in
`deploy/cloud/render-staging.yaml`; syncing it would create a paid resource and
is not part of this change. After separate approval, API and worker settings
must both explicitly enable `BROWSER_FORM_ANALYSIS_ENABLED`. The browser
delivery flag remains false. Do not synchronize a paid service before that
approval.

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
