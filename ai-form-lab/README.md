# LeadHive AI Form Lab

Phase 4A isolation: no database, production API, dispatch, approval or worker.
Requires Node `^22.22.3 || >=24.8.0`; existing frontend dependencies are unchanged.

```sh
cd ai-form-lab
npm ci
npx e2e-web install chromium
npm run typecheck
npm run test:safety
npm run test:baseline
# OPENAI_API_KEY must be injected into this process securely. Never commit it.
npm run test:ai
npm run summarize
```

The launcher invokes `npx e2e run` with one worker, two repeats, no replay cache,
zero test retries. Results are under ignored `results/`; old artifacts are
renamed rather than overwritten. AI stops after the first failed trial. Restarting
the whole run starts a new **$5 maximum reserved cost budget**, so do not retry
automatically. Exact model is `gpt-5.4-mini-2026-03-17`; text-only input $0.75/M,
output $4.50/M. UTF-8 request size conservatively reserves input tokens; each
response is limited to 1,024 output tokens. Usage is recorded without request
headers, credentials or payload. Rate/credit/auth errors disable further API
calls. Actual unknown usage/cost stays null. There is no key file loader.

All samples use anonymous synthetic values. Every browser HTTP request is
intercepted; only exact fixture URLs, GET, literal 127.0.0.1 and the fresh port
are permitted. The interception fulfills a manually fetched, size/time-limited
response, never follows redirects and never uses route.continue(). Service
workers are blocked; WebSocket, EventSource, beacon, popup and submit are disabled.
Final buttons are disabled as a separate guard; the fixture rejects all non-GET.
This is a fixture-only safety boundary, **not a production browser sandbox**.

`baseline` uses deterministic selectors through the e2e web engine's Playwright
surface. The pre-existing `frontend/form-lab` 44 desktop/mobile Playwright tests
remain the regression suite. Both comparison paths use the same optional company
field, values and seven scenarios. The seventh scenario intentionally retains an
invalid email: recognizing an error and stopping is its successful outcome.

Screenshots and step traces are saved by e2e. Only aggregate JSON is committed.
Do not adapt this lab to real forms or reuse browser sessions. Before a production
adapter, enforce Core permission, suppression, human approval payload/fingerprint,
SSRF/robots/terms rules independently of the AI agent.
