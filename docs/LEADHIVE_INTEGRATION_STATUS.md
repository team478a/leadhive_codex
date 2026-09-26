# LeadHive Integration Status

## Scope

This document records the result of integration STEP 1 through STEP 4. No merge into `main`, branch deletion, new Form Intelligence implementation, or Phase 6 real-data validation was performed.

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
| STEP 4 verified implementation HEAD | `f27081088da19749235c6ebf9e8d1af9b3d28c3e` |

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

## Verification

| Check | Result |
| --- | --- |
| Ruff check | PASS: 0 errors |
| Ruff format check | PASS: 143 files already formatted |
| Backend tests | PASS: 131 passed, 2 deprecation warnings |
| Representative CRUD tests | PASS: 30 passed, 2 deprecation warnings |
| Frontend typecheck | PASS |
| Frontend lint | PASS |
| Frontend build | PASS |
| Migration topology | PASS: 49 revisions, 1 root, 1 head, 0 missing `down_revision` references |
| Alembic head | `8e2c4a7f1b90` |
| Migration downgrade / upgrade / model diff | PASS: downgrade to base, upgrade to head, and `alembic check` |
| Fresh database schema verification | PASS: 35 tables, 73 foreign keys, 0 schema errors, 0 orphan rows |
| Existing-data snapshot verification | PASS: source and restored row count 2, 35 tables, 73 foreign keys, 0 schema errors, 0 orphan rows |
| Existing migration semantics | PASS: 0 AST changes compared with the start SHA |
| E2E Desktop | PASS |
| E2E Mobile | PASS |
| GitHub Actions | PASS: all 5 jobs on STEP 3 verified implementation HEAD |

GitHub Actions result: <https://github.com/team478a/leadhive_codex/actions/runs/36241568098>

## Unresolved items

- GitHub Actions reports that Node.js 20 based actions are currently forced to Node.js 24. The affected action major versions should be updated when supported versions are available or selected.
- GitHub Actions reports the scheduled `ubuntu-latest` migration to Ubuntu 26. Pin or validate the runner image before that migration if deterministic runner behavior is required.
- Two backend test deprecation warnings remain in Starlette/httpx and AnyIO compatibility paths. They do not fail the suite.

No blocking error remains in STEP 1 through STEP 4. The branch is ready to begin STEP 5 under a separate instruction.
