# Scrapling isolated acquisition / extraction trial

Production dependencies, workers, stored company information and sending are unchanged.
`SCRAPLING_PROBE_ENABLED` defaults to false; setting it true only permits this explicit
probe, it does not select Scrapling inside `web_analysis.analyze`.

Create a separate Python 3.12 venv and install `requirements.lock`, then
`python -m playwright install chromium`. Run from the repository root with
`PYTHONPATH=backend`:

```text
python -m pytest backend/scrapling-lab/tests -q
```

For the explicitly authorized private URL cohort, set `SCRAPLING_PROBE_ENABLED=true`
in this CLI process only, keep `OUTBOUND_ENABLED=false`, and run:

```text
python backend/scripts/compare_scrapling.py --csv PRIVATE.csv --private-dir OUTSIDE_REPO --aggregate AGGREGATE.json --limit 100 --live-get
```

The CSV `URL` / `website_url` field supplies the original company URL. The first
100 rows form the fixed cohort; failures remain in the denominator. No search API,
AI, database, approval, POST or company updates. At most 8 GET attempts per case
(including robots / redirects), maximum 100 cases. Existing SafeFetcher remains
the only live acquisition path. No retries through an alternate HTTP client after
robots/access denial. No secondary pages in this scoped root-page comparison.

Snapshots and per-case fields are written once outside Git. The aggregate has no
company names, domains, phone numbers, addresses, emails or individual URLs.
Recompute without website GET by replacing `--live-get` with `--replay-dir ORIGINAL_DIR`;
use a new private output directory and aggregate path. Snapshot request URL and
HTML SHA-256 are checked, and old results are not overwritten.

Optional Human truth JSON must contain `source_sha256` matching the original CSV
and `cases` keyed by case-001 etc. Each label needs `human_verified=true`, `reviewer`,
`reviewed_at`, and the exact confirmed field values. Missing fields are unlabeled;
explicit empty strings are verified absence. Acquisition failures count as errors
when a field has an actual Human label. Source CSV fields are not truth by default.

Three methods share the exact acquired HTML:

1. Existing BeautifulSoup + `extract_page`.
2. Scrapling Selector normalization + the same PageData extractor.
3. Scrapling DynamicFetcher in a disposable browser, replaying those HTML bytes.

The browser routes only its first exact GET navigation to the saved HTML. All
other requests are aborted; service workers/downloads/popup/form-submit helpers are
disabled. An owned, non-forwarding loopback proxy and disabled DNS are additional
backstops because upstream swallows setup-hook errors. No normal / stealth HTTP
fetchers, CAPTCHA solving, impersonation, proxy rotation or challenge bypass.
Process deadline 20s; DOM navigation timeout 5s, inline-JS settle 200ms; one attempt.
This is not an OS security sandbox and must not become a production browser adapter.

External JS bundles, CDN resources, XHR APIs and external frames are deliberately
unavailable. Thus this trial measures static normalization and **inline-JS replay**,
not the full DynamicFetcher live-network success rate. Availability/disagreement
is not accuracy, and extracting a contact link is not proving a usable form.
Full-site crawl / target fit / HTTP-backend substitution require a separate trial
with pinned DNS and independently enforced browser egress before production use.
