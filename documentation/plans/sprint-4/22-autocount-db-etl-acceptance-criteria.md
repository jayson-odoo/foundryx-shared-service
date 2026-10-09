# 22 - AutoCount direct-DB ETL (multi-dialect SQL source → Sorento) - User Acceptance Criteria

> **Status:** DRAFT - contract for `documentation/plans/sprint-4/22-autocount-db-etl.md`
> **Builds on:** `13-autocount-esb.md` (source seam, mapping engine, watermark, staging),
> `14-autocount-sorento-masters.md` (SorentoSink, dry-run gate), `15`/`16` (mapping UI + formulas).
> **Reverses:** plan 13's out-of-scope ruling "Direct SQL Server read path | Unnecessary -
> `LastModifiedFrom` covers it (D4)". The customer agreement changed: DB integration lands first.
> **Companion repo:** Sorento CRM (`/Users/tehjayson/Documents/foundryx/sorento_crm`). Its side is
> built in a **standalone session** against the cross-repo contract in the plan's Appendix A; the
> `[XR]` group below states what this repo must be able to rely on.
> **Source of decisions:** grill session 2026-08-30 (22 questions, §Decision Log below).

## Scope

**In:** generic read-only SQL source (MS SQL Server, PostgreSQL, MySQL) as a new `source_impl`
behind the existing `EntitySource` seam; connection provider with Test Connection; schema browser;
SQL query editor with preview; column-picker mapping on the existing mapping engine; two-cadence
scheduling (incremental watermark + reconcile hash-diff, Celery beat); delete propagation
(hard-delete-with-deactivate-fallback); activate-once gate then auto-push; run history.
Entities: suppliers, customers, products, warehouses, product_categories, units_of_measure,
sales agents, sales orders + lines, purchase orders + lines.

**Out:** any write to the source DB (hard rule). Stock balances (API path, ~2 weeks later, backlog).
Payment terms (standing decision; Sorento Phase D absent). On-prem connector agent (backlog).
Cron expressions (backlog). True CDC/binlog (backlog). Generic ETL engine extraction to platform
core (backlog). Editing the API-path flow (untouched; manual sync + review gate stay as-is).

## Definitions

- **Task** - the per-(company, entity) DB extraction config: connection, query, key columns,
  watermark column, compared columns, from-date (documents), two intervals, status.
- **Incremental run** - watermark-bounded fetch (`WHERE <watermark> > :mark`); adds/updates only.
- **Reconcile run** - full extract + row-hash diff over compared columns; catches deletes and
  rows an unreliable watermark missed.
- **Row hash** - deterministic hash of the compared columns of one source row, keyed by source_ref.
- **Activation** - the one-time human gate: successful dry-run preview → explicit Activate; after
  it, scheduled runs push without approval.
- **Delete intent** - a staged record carrying `op=delete` produced when reconcile finds a
  previously-seen source_ref missing from the source.

---

## Group A - SQL connection provider `[BE]`/`[FE]`

### AC-22-01 `[BE]` Generic SQL provider registered
**Given** the autocount module is installed
**When** connection providers are listed
**Then** a SQL-database provider exists with fields: dbType (select: `mssql` | `postgresql` |
`mysql`), host, port, database, username, and password (secret, Fernet, write-only, blank = keep)
**And** it follows the core `connections` contract (tenant-scoped, partial PATCH merges config).

### AC-22-02 `[BE]` Test Connection works per dialect
**Given** a saved SQL connection
**When** Test Connection runs
**Then** it connects with the dialect matching dbType and executes a trivial probe (`SELECT 1`)
**And** success/failure returns within a bounded timeout (no hanging request)
**And** failure reports a sanitized message (never credentials, never a raw driver stack).

### AC-22-03 `[BE]` Read-only is enforced structurally
**Given** any query execution path in this feature (preview, incremental, reconcile)
**When** a statement is submitted
**Then** only a single SELECT (or WITH...SELECT) statement is accepted - multiple statements,
INSERT/UPDATE/DELETE/DDL/EXEC are rejected with 422 before touching the source
**And** sessions are opened read-only where the dialect supports it (Postgres/MySQL
READ ONLY transaction), with a per-query statement timeout on every dialect
**And** the docs/UI advise provisioning a read-only DB login (defense in depth, not the only guard).

### AC-22-04 `[FE]` Connection UI
**Given** the connections surface
**When** the user creates a SQL-database connection
**Then** the provider's fields render from the registry (no hand-rolled form), dbType is a select,
port defaults per dialect (1433/5432/3306), and Test Connection gives inline success/failure.

## Group B - Schema browse + query preview `[BE]`/`[FE]`

### AC-22-05 `[BE]` Schema introspection endpoint
**Given** a working SQL connection
**When** the schema is requested
**Then** schemas → tables → columns (name + type) are returned via dialect-agnostic introspection
**And** the result is cached per connection with an explicit refresh, never fetched per keystroke.

### AC-22-06 `[BE]` Query preview
**Given** a candidate SELECT
**When** preview runs
**Then** at most 100 rows are returned (dialect-appropriate wrapping), with result column names
and types
**And** the SELECT-only guard (AC-22-03) and timeout apply
**And** a failing query returns the DB error message sanitized (no credentials/DSN echo).

### AC-22-07 `[FE]` Editor surface
**Given** the task editor (one surface, tabs: Query · Mapping · Schedule · Review & Activate · Runs)
**When** the user builds an extraction
**Then** the left panel shows the schema tree (searchable, tables only, Expand all; clicking a
table opens its columns side panel), a table action inserts a starter `SELECT * FROM <table>`,
the SQL editor is CodeMirror-grade in v1 (SQL syntax highlight, autocomplete from the introspected
schema, bracket match), and Test Query renders the preview grid with row count
**And** key/watermark/compared-column pickers offer the actual preview result columns (dropdowns,
not free text)
**And** loading, empty (0 rows), error, and success states are all designed.

## Group C - DB source behind the seam `[BE]`

### AC-22-08 `[BE]` New source_impl, seam refactor
**Given** `ac_entity_config.source_impl = 'sql_db'`
**When** a sync job runs
**Then** the source factory receives company/connection context and builds its own transport - the
HTTP `AutoCountClient` is no longer constructed unconditionally in `sync.py`
**And** the API path (`autocount_read`) behaves byte-identically to before the refactor (existing
autocount test suite stays green)
**And** an unknown source_impl still fails loudly.

### AC-22-09 `[BE]` Flat-row mapping
**Given** a DB task's query result rows (flat columns, aliases allowed)
**When** mapping executes
**Then** the existing `ac_field_mapping` table + `MappingEngine` are reused with source_path =
result column name (no `Data.0.*` synthesis)
**And** transforms and formulas (slice 16) work unchanged on DB rows.

### AC-22-10 `[BE]` source_ref parity with the API path
**Given** a company that previously synced an entity via the API path
**When** the same entity is switched to the DB path with key columns matching the API identity
**Then** minted source_refs are identical (`{DatabaseName}:{key}` scheme preserved)
**And** a dry-run against Sorento reports `updated`/no-change for already-synced rows, never a
duplicate `created` wave.

### AC-22-11 `[BE]` Task config validation
**Given** a task being saved
**When** validation runs
**Then** key columns are required and must exist in the preview result columns; watermark column,
if set, must exist and be an orderable type; compared columns default to all result columns minus
key columns; documents (SO/PO) require a from-date (default: today)
**And** violations are 422 with field errors, not 500.

## Group D - Scheduling + change detection `[BE]`

### AC-22-12 `[BE]` Two cadences per task
**Given** an active task
**When** schedules are configured
**Then** incremental interval accepts ≥ 1 minute, and reconcile offers two modes day one:
"Daily at HH:MM" (tenant timezone) or every N hours (≥ 1h)
**And** a task whose table has no watermark column runs hash-diff as its incremental and the
minimum incremental interval is forced to 15 minutes.

### AC-22-13 `[BE]` Beat sweep dispatch
**Given** Celery beat runs the sweep
**When** a task's next-run time is due
**Then** a background job (existing `background_jobs` machinery) is enqueued with mode
`incremental` or `reconcile`
**And** the sweep itself does no extraction work
**And** dev/test (eager mode) executes inline without beat.

### AC-22-14 `[BE]` Overlap guard
**Given** a task's previous run is still executing
**When** its next tick becomes due
**Then** the tick is skipped (recorded as skipped in run history, not queued behind)
**And** two workers cannot run the same (company, entity) concurrently.

### AC-22-15 `[BE]` Incremental correctness
**Given** a watermark task
**When** an incremental run completes
**Then** only rows with watermark > stored mark were fetched, the mark advances to the max seen
(never the clock), and a run with zero changes writes a run-history row with zero counts
**And** re-running immediately fetches nothing (idempotent).

### AC-22-16 `[BE]` Reconcile + row-hash correctness
**Given** stored row hashes from prior runs
**When** a reconcile run executes
**Then** new source_refs stage as adds, hash-changed rows stage as updates, hash-equal rows stage
nothing, and source_refs absent from the extract produce delete intents
**And** changing a column that is NOT in compared columns does not stage an update ("on change of
which field" semantics)
**And** only hashes are stored long-term, not full row copies.

### AC-22-17 `[BE]` Run history observability
**Given** any run (manual, incremental, reconcile)
**When** it finishes (success, partial, failure, skipped)
**Then** run history records mode, rows scanned, added/updated/deleted/failed counts, duration,
and per-record failures are inspectable
**And** volume × frequency is visible enough to judge cost (rows scanned + duration per run).

## Group E - Activation gate + push `[BE]`/`[FE]`

### AC-22-18 `[BE]`/`[FE]` Activate-once gate
**Given** a newly configured task (status draft)
**When** the user activates it
**Then** activation requires a successful Sorento dry-run preview of the initial load, rendered
with the existing preview panel (summary + overwrite diff cards)
**And** Activate is disabled until that preview succeeds
**And** after activation, scheduled runs push automatically with no per-run approval.

### AC-22-19 `[BE]`/`[FE]` Pause/resume
**Given** an active task
**When** the user pauses it
**Then** the sweep stops dispatching it, in-flight runs finish, and resume re-enables without
re-activation
**And** repeated delivery failures surface on the task (status/last-error), never silently.

### AC-22-20 `[BE]` Push reuses hop 2 unchanged
**Given** staged adds/updates from a DB run
**When** they push
**Then** delivery goes through the existing `SorentoSink` batch path with per-record verdicts,
and `retryable` records are retried on subsequent runs, not lost.

## Group F - Deletes `[BE]`

### AC-22-21 `[BE]` Delete propagation
**Given** a delete intent from reconcile
**When** it pushes
**Then** the sink calls the Sorento deletion endpoint (Appendix A contract); the per-record
verdict (`deleted` | `deactivated` | `not_found` | `failed`) is recorded in run history
**And** local row-hash state for a confirmed-deleted ref is removed so a later re-appearance at
source stages as an add.

### AC-22-22 `[BE]` Delete safety
**Given** a reconcile extract that returns drastically fewer rows than the stored hash population
(e.g. a broken query or connection mid-extract)
**When** delete intents would exceed a configurable guard threshold (default 20% of known rows)
**Then** the run fails safe: no deletes are pushed, the run is marked failed with an explanatory
error, and the task surfaces the alert.

## Group G - Entity fan-out `[BE]`

### AC-22-23 `[BE]` Masters land end-to-end
**Given** DB tasks for suppliers, customers, products, warehouses, product_categories,
units_of_measure, sales agents
**When** each syncs against Sorento
**Then** each delivers with per-record verdicts (sales agents via the new Sorento spec, Appendix A)
**And** dependency order is respected: categories + UOM before products (products otherwise
`retryable`, and retryables resolve on the next run after the dependency lands).

### AC-22-24 `[BE]` SO/PO documents
**Given** DB tasks for sales orders and purchase orders
**When** they sync
**Then** header + lines are extracted (from-date respected), canonical documents mint
`{DatabaseName}:{DocKey}` refs and per-line refs, all statuses sync with status mapped,
and cancel-at-source arrives as a status update, never a delete
**And** a re-push of a changed document upserts lines (adds/updates/removes) per the Appendix A
contract.

## Group H - Cross-repo reliance `[XR]`

> Built in the standalone Sorento session against Appendix A of the plan. These ACs pin what THIS
> repo integrates against; the Sorento session owns their implementation tests.

### AC-22-25 `[XR]` Sales-agent ingest exists
`POST /api/v1/external/ingest/sales_agents` (+ read-back) accepting the canonical shape, keyed on
the agent code, honoring dry_run, with permission slug + grant migration.

### AC-22-26 `[XR]` Document ingest exists
SO and PO ingest endpoints accepting header+lines, upserting lines with per-line source_refs,
per-record verdicts, dry_run, resolving master references (`retryable` when absent).

### AC-22-27 `[XR]` Deletion endpoint exists
A batch deletion call per entity: attempts hard DELETE, falls back to deactivate (`is_active`;
`is_discontinued` for products) when dependents exist, and reports which per record.

### AC-22-28 `[XR]` Company-anchored ingest
Every ingest/read/delete call is company-anchored (anchor resolvable from the integration key or
explicit company code); adoption lookups are company-scoped; ingested rows carry a valid
`company_id`. The existing NULL-company / cross-company-adoption landmine is fixed.

## Group I - Security + permissions `[BE]`

### AC-22-29 `[BE]` Tenant isolation
All new tables/queries are tenant-scoped from the JWT; connection resolution is tenant+provider
scoped, never bare get-by-id; schema/preview/task routes require the autocount module permissions
and the connection referenced must belong to the tenant.

### AC-22-30 `[BE]` Credential hygiene
Source DB credentials are Fernet-encrypted at rest, never logged, never echoed in errors or
previews; preview/introspection errors are sanitized.

## Group J - E2E `[E2E]`

### AC-22-31 `[E2E]` Golden path, real clicks
From the sidebar (never deep URLs): create SQL connection (pointed at the local Postgres acting
as source) → test → build a customer task (schema tree → starter query → preview → pick key +
watermark + compared columns → mapping) → dry-run preview → Activate → Run now → run history
shows delivered counts. Timestamped names; dedicated tenant; 375px and 1280px.

### AC-22-32 `[E2E]` Change-detection path
Mutate a source row + delete a source row (test rig) → trigger incremental then reconcile →
run history shows 1 update then 1 delete intent with its verdict.

---

## Test tags

`[T]` unit/integration coverage is required for: SELECT-only guard (accept/reject matrix),
dialect URL building, preview wrapping per dialect, watermark advance, hash-diff add/update/
delete/no-change matrix, compared-columns exclusion, delete guard threshold, overlap skip,
source_ref parity, factory refactor regression (API path), scheduler due-selection.

## Decision Log (grill 2026-08-30)

| # | Decision |
|---|---|
| Q1 | Direct DB connection now (customer port-forwards); on-prem agent = backlog |
| Q2 | Read-only, structurally enforced; never write to source DB |
| Q3 | Inside autocount module via `EntitySource` seam; generic ETL engine = backlog |
| Q4 | Wide entity scope up front (masters + SO/PO together) |
| Q5 | Table-pick AND handwritten SQL, SQL-first with preview |
| Q6 | Watermark (ours, no client DBA) + full-extract hash-diff; both, per task |
| Q7 | Manual Run-now + scheduled |
| Q8 | Deletes propagate: hard delete where possible, deactivate fallback |
| Q9 | Activate-once gate (dry-run preview), then auto-push |
| Q10 | SO/PO read-only AutoCount→Sorento; write-back = future API feature |
| Q11 | Sorento-side work in scope, built in a standalone session against Appendix A |
| Q12 | Soft-deactivate baseline, hard delete attempted first |
| Q13 | Task config anchored on `ac_entity_config` (per company+entity), not free-form tasks |
| Q14 | Reuse `ac_field_mapping` + engine; editor binds to preview columns |
| Q15 | Interval scheduling down to 1 minute (cron = backlog) |
| Q16 | Minutely-safe design: two cadences, hash-store only, cost visible in run history |
| Q17 | Incremental (≥1m) + reconcile (≥1h, default daily); no-watermark forces ≥15m |
| Q18 | Stock balances OUT (API in ~2 weeks) |
| Q19 | Entity list confirmed; payment terms stays out |
| Q20 | SO/PO from-date per task (default today); all statuses, mapped; cancel = status update |
| Q21 | Hard-delete-try, deactivate-fallback, verdict reported |
| Q22 | 1 `ac_company` ↔ 1 Sorento company; ingest company-anchored (fixes landmine) |
| post | Source is multi-dialect: MSSQL + PostgreSQL + MySQL via SQLAlchemy dialects |
