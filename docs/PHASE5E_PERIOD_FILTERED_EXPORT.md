# Phase 5E: captured-time period export

## Goal and baseline

Baseline main: `5e0c96bee66fea17a947a73aa99b6500f2465564` (PR #88).
Evaluation history previously exported all saved records before applying its period.
More than 1000 historical records therefore prevented even a small current-period evaluation.
This change selects the requested period in SQL before the existing bounded fetch.

## Contract

`GET /api/projects/{project_id}/feedback-export?start=...&end=...`
accepts paired timezone-aware ISO timestamps. Start is inclusive; end is exclusive.
Missing one bound, naive timestamps, or a non-positive range returns 422.
No bounds retains the legacy export contract. Period output adds the normalized UTC bounds.
Saving an evaluation uses these same bounds; checkpoint validation still applies afterward.

Captured event clocks are used:

| Record | Timestamp |
|---|---|
| Human collection review | stored `reviewed_at` |
| Form diagnostic | stored `observed_at` |
| Site identity Human review | immutable event `created_at` |

Activity insertion time does not determine inclusion. Site review companions are fetched
by selected review ID and project/company binding, even if inserted later. Current mutable
Company URLs never replace the original captured prediction. WEB_DECISION and companions
do not count as independent evaluation events in period exports.

## Completeness, safety and limits

The 1000 combined evaluation-record ceiling remains. Each query fetches at most 1001 rows
to detect overflow. A period exceeding the limit returns 413 and asks for a shorter period;
there is no truncated successful export. Malformed JSON, invalid/unknown event timestamps,
or ambiguous duplicate companions return 409 rather than a partial result or unsafe cast.
Unknown timestamp records cannot be presumed outside the requested period.

PostgreSQL 16 `pg_input_is_valid` guards JSON and timestamp casts. This introduces no
dependency, SQL function, model, migration or stored-data rewrite. Owner authorization,
admin/feature-flag evaluation-save checks, Agent rejection, provenance validation,
private URL redaction and no-store response headers remain in place.
Export is read-only. Human labels and system diagnostics remain distinct.
No external API, AI call, approval, rule activation or outbound delivery is added.

## Validation

Dedicated PostgreSQL 16 `_test` database only; synthetic fixtures.
Tests cover over-1000 out-of-period collection/form/site histories, captured time versus
insertion time, timezone conversion, half-open boundaries, exactly 1000 and overflow,
malformed JSON/timestamps, companion-ID retrieval and duplicate rejection, owner/Agent
boundaries, no source-record mutation and actual evaluation-save integration.

Final test results and CI links are recorded in the PR for its exact head.
Existing offline replay and frontend checks are also retained.

## Remaining limits

This bounds materialized results; it does not establish large-database query latency.
Prefix/JSON scans can still depend on historical table size. Performance must be measured
before claiming million-record scalability. PostgreSQL older than 16 is unsupported.
Unfiltered proposal analysis still has its existing 1000-record limit; this change only
connects evaluation history to period export. No live production benchmark, deployment,
or runtime improvement is claimed. Existing stored evaluations are not rewritten.

See [evaluation history administration](PHASE5E_EVALUATION_ADMIN_HISTORY.md).
