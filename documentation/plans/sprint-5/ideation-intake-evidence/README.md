# Ideation intake redesign (S1/S5) - Postgres fresh-database evidence (N2)

Review round 2 follow-up (Opus APPROVE-WITH-NITS on HEAD `2b07d14d`). The
migration 0010 backfill, the forked-tenant edge insert, and the
`ideas_idea_number_seq` sequence only run on Postgres (module migrations are
Postgres-only, a no-op under the sqlite pytest engine) - this is a real,
throwaway-database check to prove they actually work, separate from the
pytest suite.

Worktree: `foundryx-shared-service-intake`, branch `feat/ideation-intake-s1-s5`,
HEAD `2b07d14d`. Database: a brand-new native Postgres database,
`foundryx_service_intake` (created and dropped in this session; never touched
`foundryx_service`, `fx_shared_local`, or any `foundryx_service_s*`).

## Commands run

```
psql -d postgres -c "CREATE DATABASE foundryx_service_intake OWNER foundryx;"

cd foundryx-shared-service-intake/service_backend
DATABASE_URL=postgresql://foundryx:foundryx@localhost:5432/foundryx_service_intake \
  /Users/tehjayson/Documents/foundryx/foundryx-shared-service/service_backend/.venv/bin/python \
  -m scripts.bootstrap_db
```

## Finding: `pg_trgm` is never installed on a genuinely fresh database

`bootstrap_db` finished with exit 0 and `app_ideation.alembic_version_ideation`
correctly read `0010_ideation_intake_contract` - but `\dx` on the fresh
database showed no `pg_trgm` extension. Root cause (pre-existing, NOT
introduced by this lane): `modules/ideation/bootstrap.py::install()` calls
`create_schema_and_tables()` -> `IdeationBase.metadata.create_all(engine)`
**before** `_bootstrap_one_module` calls `run_module_migrations()`. On a
truly empty database this means the ideation tables (and, since review
round 1, the `ideas_idea_number_seq` sequence - it is now declared on
`IdeationBase.metadata` on purpose) already exist by the time
`run_module_migrations` inspects the schema, so it takes the "legacy
create_all schema - adopt Alembic with NO DDL" branch (`command.stamp(cfg,
"head")`) instead of `command.upgrade(cfg, "head")`. The version table
correctly reads `head`, but none of the migrations' actual SQL (in
particular migration `0002_ideation_dedup_trgm`'s
`CREATE EXTENSION IF NOT EXISTS pg_trgm` + GIN index) ever ran. Every
`create_idea` dedup call then 500s with
`psycopg2.errors.UndefinedFunction: function similarity(text, unknown) does
not exist`.

This is an existing gap in `_bootstrap_one_module`'s ordering, not specific
to migration 0010 - it just happens to be the first time a truly from-empty
`bootstrap_db` run against a fresh Postgres database was exercised for this
module in this lane. It does not affect `foundryx_service` or the other
long-lived local databases (their module schemas were built up over time
while `pg_trgm` already existed from an earlier, non-adopted migration run).
**Not fixed here** (tester scope) - recommend a backlog item: either run
`run_module_migrations` before `install()`'s `create_all`, or have
`create_schema_and_tables` skip tables covered by the module's own Alembic
history. Worked around for this evidence run only with a manual
`CREATE EXTENSION IF NOT EXISTS pg_trgm;` (as the `foundryx` role, which does
have the grant to create it) before driving the flow below.

## Flow check (`IntakeService.create_idea`, real Postgres, pg_trgm dedup)

Throwaway script (scratchpad only, never in the repo tree) opened a session,
created a software product + delivery base for the default tenant, and drove:

| Step | Assertion | Result |
|---|---|---|
| Turn 1 (problem + title) | `status == "collecting"` | OK |
| `skip: ["proposed_solution"]` | `next_field == "impact"` | OK |
| Answer impact | `status == "review"` | OK |
| `confirm: true` | `status == "complete"` | OK |
| | `idea_number == "IDEA-0001"` | OK (sequence reset to 1 first - a manual `SELECT nextval(...)` sanity check earlier in this same session had already advanced it once) |
| | `link` ends with `/public/ideas/<status_token>` | OK - `https://n2-verify.example.com/public/ideas/bF-IXI3baDtwPsrHdn5AT7FCHNZC2jeK` |
| | `ideas` row has `status_token` set | OK |
| Second draft, similar problem | `status == "duplicate_candidate"` | OK |
| `duplicate_choice: "vote"` | `status == "voted"`, `idea_number` matches the original capture | OK |
| | draft 2's row is at the `duplicate` status | OK - proves the new `idea-tr-draft-vote` (`draft -> duplicate`) edge exists and fires on Postgres |
| `SELECT nextval('app_ideation.ideas_idea_number_seq')` | returns an int, no error | OK (returned `2`) |
| `alembic_version_ideation` | `0010_ideation_intake_contract` | OK |

All assertions passed (`ALL N2 FLOW CHECKS PASSED`).

## Migration downgrade/upgrade round-trip

There is no bare `alembic downgrade`/`upgrade` CLI entry point for a
per-module migration: `modules/ideation/alembic/env.py` reads
`version_table` / `version_table_schema` / `target_metadata` from
`Config.attributes`, which `app/module_platform/migrations.py::
run_module_migrations` sets at runtime - never written to an `alembic.ini`
file. A throwaway script replicated that exact `Config` construction (the
real "CLI path" this module has - `alembic.command.downgrade`/`upgrade`,
the same entry points the `alembic` binary itself dispatches to) and ran:

```
command.downgrade(cfg, "0009_ideation_is_test")
command.upgrade(cfg, "head")
```

Results:
- Before: `0010_ideation_intake_contract`.
- After downgrade: `0009_ideation_is_test`; `title`/`submitter_tier`/
  `idea_number`/`status_token`/`intake_state` columns confirmed DROPPED
  (`information_schema.columns` query returned empty).
- After re-upgrade: back to `0010_ideation_intake_contract`; all five
  columns confirmed back. The 0010 backfill also re-ran correctly: both
  existing non-draft rows (the captured `IDEA-0001` idea AND the
  voted-away `duplicate`-status draft from the flow check above) were
  re-minted `idea_number`/`status_token` values (`IDEA-0001`, `IDEA-0002`)
  in `created_at, id` order - confirming the backfill's "any non-draft
  status, not just captured" scope works as designed, including on a
  round-trip.

Idempotent both ways; no errors.

## Cleanup

```
psql -d postgres -c "DROP DATABASE foundryx_service_intake;"
```

Confirmed dropped; `foundryx_service`, `fx_shared_local`, and every
`foundryx_service_s*` database were verified present and untouched
throughout. No throwaway script was committed to the repo tree.

## Browser smoke of the public status page (agent-browser, hand-test stack, 2026-09-25)

Stack: is-test worktree detached at 71dc37dc, `bootstrap_db` applied migration 0010 on `fx_shared_local` (IDEA-0001 backfilled with a token), frontend rebuilt and started on :3001.

- `public-status-1280.png` - `/public/ideas/<token of IDEA-0001>` at 1280: number, label "Idea IDEA-0001" (no title, pre-lane idea), status pill "New", no sidebar, no login prompt.
- `public-status-375.png` - same page at 375: one column, `innerWidth 375 == scrollWidth 375` (no horizontal scroll).
- `public-status-notfound-375.png` - `/public/ideas/IDEA-0001` (an idea number, not a token): the plain "This link isn't available." state.
- Backend direct: `GET :8001/public/ideas/<token>` -> `{"title":null,"status":"New","ideaNumber":"IDEA-0001"}`; `GET :8001/public/ideas/IDEA-0001` -> 404 `{"error":{"code":"not_found","message":"Not found."}}`.
- Known local cosmetic: the public layout's branding logo image is missing on this local stack (shared pre-auth layout, not this lane).
