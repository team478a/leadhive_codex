# LeadHive Integration Status

## Scope

This document records the result of integration STEP 1 through STEP 6. No merge into `main`, branch deletion, new Form Intelligence implementation, or Phase 6 real-data validation was performed.

## Integration baseline

| Item | Value |
| --- | --- |
| Integration branch | `codex/integration` |
| Start time | 2026-09-26 19:27:18 JST |
| Start SHA | `78ed40a3860da7aa2b61a3c5cf2a1a36bd32e53d` |
| `origin/codex/smtp-settings-ui` HEAD at start | `78ed40a3860da7aa2b61a3c5cf2a1a36bd32e53d` |
| `origin/main` HEAD at start | `b66ed40c533476d2adb7ad74940e6b9f86faa34b` |
| Existing remote `codex/*` branches at start | 33 |
| Existing branches contained by the baseline | `main` and all 33 remote `codex/*` branches |
| STEP 5 verified implementation HEAD | `6cbd04fcb145d9eab0bb6545958512fb7fcf3da3` |
| STEP 6 verified implementation HEAD | `824e80a016dd84486aa5351b6847b6ef5e433f77` |

## STEP 2 changes

- Formatted the backend with Ruff and resolved all 79 lint errors.
- Kept all existing Alembic migrations semantically unchanged; AST comparison against the start SHA found zero semantic changes across 49 migration files.
- Split GitHub Actions into independent `backend-lint`, `backend-tests`, `migration-validation`, `frontend`, and `e2e` jobs so failures are isolated.
- Added an explicit `alembic upgrade head` before the GitHub Actions E2E run.

## STEP 3 changes

- Added `evaluate_contact_permission` as the single contact decision service. It returns `ALLOWED`, `PROHIBITED`, or `UNCERTAIN` with a stable reason code and reads the existing Company, Suppression, contact quality, and Form Profile facts without storing a duplicate canonical result.
- Applied the decision to individual email, email retry, email campaigns, email worker delivery, direct form delivery, Codex-assisted form delivery, bulk form creation and retry, and form worker delivery.
- Added a final worker check so a destination added to the Suppression List after approval cannot be sent.
- Routed uncertain forms to manual review and kept prohibited forms blocked. CAPTCHA, stale, unanalysed, and unsupported forms are never automatically submitted.
- Added representative outsider, viewer, and editor write-access tests and enabled PATCH in CORS preflight handling.
- Added no migration and changed no database model.

## STEP 4 changes

- Added `backend/scripts/verify_database_state.py` to compare the migrated PostgreSQL schema with SQLAlchemy metadata and detect foreign-key orphan rows.
- Added the database-state verifier to the GitHub Actions migration validation job.
- Verified a fresh isolated PostgreSQL 16 database through `upgrade head`, `downgrade base`, `upgrade head`, and `alembic check`.
- Streamed a snapshot of the current local database into a separate isolated database, upgraded it to head, and verified schema, constraints, row counts, and referential integrity. The source database was already at Alembic head, so this was a no-op migration from the current revision.
- Ran the representative Project and Company CRUD API tests against an isolated database.
- Added no migration and changed no database model or existing local data.

## STEP 5 changes

- Added a partial unique index that permits only one `queued` or `running` operation for each project and operation type. The Migration stops with an explicit error if pre-existing active duplicates require manual resolution.
- Added a shared race-safe enqueue function and applied it to manual operations, scheduled search, scheduled reanalysis, data-quality reanalysis, Form Intelligence, and form-delivery batches.
- Kept `FOR UPDATE SKIP LOCKED` job claiming and verified all five operation types are claimed exactly once by two workers.
- Serialized Email Delivery claiming with a PostgreSQL advisory transaction lock. Running deliveries now count toward the daily limit and minimum interval, preventing two workers from exceeding configured delivery limits.
- Added real PostgreSQL concurrency tests for simultaneous enqueue, five operation types, expired operation leases, scheduled search, Email Delivery claiming, and expired Email Delivery recovery.
- Added Migration `c1d9f6a2b4e8`; no existing Migration was modified.

## STEP 6 changes

- Ran the complete backend, frontend, migration, desktop E2E, and mobile E2E verification set against the integration candidate.
- Strengthened the Windows distribution builder so it verifies the saved ZIP checksum, every manifest hash, missing files, unlisted files, PowerShell syntax, required files, and the packaged Compose configuration after extraction.
- Added a `windows-package` GitHub Actions job on `windows-latest`, closing the Windows distribution validation gap recorded by the branch audit.
- Generated `LeadHive-Windows-Local-824e80a.zip` locally. It contains 189 manifested files and has SHA-256 `41b4e7764b47b28ff8ccf3639c7f7688babca800e407b504a926e29b7a0deebc`.
- Added no migration and changed no database model or existing local data.

## Verification

| Check | Result |
| --- | --- |
| Ruff check | PASS: 0 errors |
| Ruff format check | PASS: 145 files already formatted |
| Backend tests | PASS: 136 passed, 2 deprecation warnings |
| Representative CRUD tests | PASS: 30 passed, 2 deprecation warnings |
| Two-worker concurrency tests | PASS: 5 passed, 2 deprecation warnings |
| Frontend typecheck | PASS |
| Frontend lint | PASS |
| Frontend build | PASS |
| Migration topology | PASS: 50 revisions, 1 root, 1 head, 0 missing `down_revision` references |
| Alembic head | `c1d9f6a2b4e8` |
| Migration downgrade / upgrade / model diff | PASS: downgrade to base, upgrade to head, and `alembic check` |
| Fresh database schema verification | PASS: 35 tables, 73 foreign keys, 0 schema errors, 0 orphan rows |
| Existing-data snapshot verification | PASS: restored `8e2c4a7f1b90` snapshot upgraded to `c1d9f6a2b4e8`; row count 2, 35 tables, 73 foreign keys, 0 schema errors, 0 orphan rows |
| Existing migration semantics | PASS: 0 AST changes compared with the start SHA |
| E2E Desktop | PASS |
| E2E Mobile | PASS |
| Windows distribution package | PASS: ZIP checksum, 189 manifest entries, required files, PowerShell syntax, and Compose configuration |
| GitHub Actions | PASS: all 6 jobs on STEP 6 verified implementation HEAD |

GitHub Actions result: <https://github.com/team478a/leadhive_codex/actions/runs/36245164980>

## Unresolved items

- GitHub Actions reports that Node.js 20 based actions are currently forced to Node.js 24. The affected action major versions should be updated when supported versions are available or selected.
- GitHub Actions reports the scheduled `ubuntu-latest` migration to Ubuntu 26. Pin or validate the runner image before that migration if deterministic runner behavior is required.
- Two backend test deprecation warnings remain in Starlette/httpx and AnyIO compatibility paths. They do not fail the suite.

No blocking error remains in STEP 1 through STEP 6. The branch is ready to begin STEP 7 under a separate instruction.
