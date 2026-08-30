# 22 - AutoCount direct-DB ETL (multi-dialect SQL source → Sorento)

> **Contract:** `22-autocount-db-etl-acceptance-criteria.md` (32 ACs). This plan fulfils it.
> **Branch:** `sprint-4/22-autocount-db-etl`.
> **Cross-repo:** Sorento-side work is specified in **Appendix A** and built in a standalone
> session in `/Users/tehjayson/Documents/foundryx/sorento_crm`. This repo integrates against
> Appendix A only; neither session edits the other's repo.

## 1. Why

The customer agreement moved DB integration ahead of API integration for AutoCount. The API path
(plans 13-16) stays intact and untouched; this plan adds a second source implementation behind the
existing `EntitySource` seam so the mapping engine, staging, watermark, preview and `SorentoSink`
are reused verbatim. Plan 13 ruled a direct SQL read "unnecessary" - that ruling is reversed by
the agreement, not by a technical finding.

FineDataLink is the UX reference: connection → schema browse → SQL + preview → mapping →
sync strategy (full / incremental / on-change-of-selected-fields) → scheduled task with run history.
We build the AutoCount-shaped subset of that, anchored on our canonical model (which FineDataLink
lacks - it is why we stay entity-anchored, decision Q13).

## 2. Architecture

```
ac_entity_config.source_impl
  'autocount_read'  → AutoCountReadSource (HTTP wrapper)   [existing, untouched]
  'sql_db'          → SqlDbSource (this plan)
                        └─ SqlSourceRuntime (dialect engine, guard, introspection, preview)
FetchResult → MappingEngine (ac_field_mapping, flat paths) → staging → SorentoSink
```

### 2.1 Seam refactor (prerequisite, AC-22-08)

`sync.py:250-333` today builds `AutoCountClient` unconditionally and passes it positionally to
every source factory. Refactor:

- Factory signature becomes `factory(ctx: SourceContext, **cfg)` where `SourceContext` carries
  `db`, `tenant_id`, `company`, `entity_config`, and a `company_service` handle. Each impl builds
  its own transport (`autocount_read` constructs the HTTP client internally, exactly as before).
- Observability: `EntitySource` gains optional `drain_activity()` (duck-typed like
  `write_batch`); `record_client_calls` consumes it when present. The DB source records one
  activity row per executed query (dialect, rows, duration, sanitized SQL head) into the same
  Developer Logs console (`SOURCE_AUTOCOUNT`).
- `client.close()` generalizes to `source.close()` in the `finally`.
- Regression pin: the full existing autocount pytest suite green before/after with zero test edits.

### 2.2 SqlSourceRuntime (new `modules/autocount/sql_source/`)

| File | Responsibility |
|---|---|
| `runtime.py` | engine cache per connection id (SQLAlchemy `create_engine`, pool_pre_ping, small pool), dialect URL builder, read-only session setup, statement timeout |
| `guard.py` | SELECT-only static guard: strip comments → exactly one statement → first token SELECT/WITH → reject `;`, INTO, FOR UPDATE. Deny-first, tested by accept/reject matrix |
| `introspect.py` | `sqlalchemy.inspect(engine)`: schemas → tables → columns(name, type). Cached (per connection, TTL + manual refresh) |
| `preview.py` | wrap query as `SELECT * FROM (<q>) AS _preview` + dialect limit (TOP/LIMIT), timeout, sanitized errors |
| `source.py` | `SqlDbSource(EntitySource)`: `fetch_changes(since)` two modes (§2.5) |
| `hashing.py` | canonical row-hash: compared columns sorted by name, values normalized (None, Decimal, datetime→UTC ISO, bytes→hex), sha256 |

**Dialects + drivers:** `mssql+pymssql` (wheels bundle FreeTDS - no ODBC system deps),
`postgresql+psycopg2` (already present), `mysql+pymysql` (pure Python). requirements.txt adds
`pymssql`, `pymysql`. Deploy image: pip-only, no base-image change (deliberately chose pymssql
over pyodbc to avoid unixODBC+msodbcsql provisioning on the Hostinger box).

**Read-only enforcement, layered (AC-22-03):** static guard (always) → session read-only where the
dialect has it (PG `SET TRANSACTION READ ONLY`, MySQL `SET SESSION TRANSACTION READ ONLY`; MSSQL
has none - guard + login) → per-query timeout (PG `statement_timeout`, MySQL `MAX_EXECUTION_TIME`,
pymssql `timeout`) → docs instruct a read-only login (`db_datareader` / `pg_read_all_data` /
`GRANT SELECT`).

### 2.3 Connection provider

`SqlDatabaseProvider` in `modules/autocount/sql_provider.py`, registered in `bootstrap.py` beside
the two existing providers. `provider="sql_database"`, `type="erp"` (reuses the erp multiplicity
carve-out in `uq_connection_tenant_provider`). Fields: `dbType` (select mssql/postgresql/mysql),
`host`, `port` (default per dialect 1433/5432/3306), `database`, `username`; secret: `password`
(Fernet, write-only, blank=keep). `test()` = engine connect + `SELECT 1`, 10s cap, sanitized
failure. Extraction of the provider to platform core = backlog (BL below), the module keeps it for
now per Q3.

### 2.4 Task model (config, not new job machinery)

`ac_entity_config` gains columns (module Alembic `0007`):

- `source_config JSON(none_as_null=True)` - for `sql_db`:
  `{connectionId, query, lineQuery?, keyColumns[], watermarkColumn?, comparedColumns[], fromDate?,
  incrementalMinutes, reconcileMode: 'interval'|'dailyAt', reconcileHours?, reconcileAt?}`
  (`reconcileAt` = "HH:MM" in the tenant timezone, resolved to UTC at sweep time)
- `etl_status` (`draft|active|paused`, default `draft`), `activated_at`
- `next_incremental_at`, `next_reconcile_at` (UTCDateTime, indexed), `last_run_error`

Validation (AC-22-11) in `CompanyService`: key/watermark/compared columns validated against a
fresh preview's result columns; documents require `fromDate`; interval floors (1m / 60m; 15m when
no watermark). 422 `{fieldErrors}`.

New table `ac_row_hash` (tenant_id, company_id, entity_type, source_ref, row_hash, last_seen_at;
PK on tenant+company+entity+source_ref). Hash state only - never row copies (AC-22-16).

### 2.5 Fetch modes

`SqlDbSource.fetch_changes(since)` receives mode from job payload:

- **incremental** (watermark column set): `SELECT * FROM (<query>) t WHERE t.<wm> > :mark ORDER BY
  t.<wm>` (bound param, column name validated against preview columns at save time - never string-
  spliced from request input). Watermark advances to max seen (AC-22-15). No watermark column →
  this mode runs the reconcile diff instead (interval floor 15m).
- **reconcile**: full `<query>` extract, stream in server-side batches; per row mint source_ref
  from key columns (`{database}:{key1[|key2]}` - same scheme as API path for parity, AC-22-10),
  hash compared columns; diff vs `ac_row_hash` → adds/updates staged, absent refs → delete
  intents. Delete guard: intents > max(20%, 50 rows) of known refs → fail run, push nothing
  (AC-22-22).

Both modes emit `SourceRecord(raw=<flat row dict>)`. Mapping profile for `sql_db` uses flat paths;
`DEFAULT_MAPPINGS` are NOT seeded for DB tasks (columns are user-authored aliases - mapping starts
from the preview column list in the editor instead).

Delete intents ride staging as `op='delete'` rows (new column on `ac_staged_record`, default
`upsert`); push routes them to the sink's deletion call (§Appendix A), verdicts recorded, and a
confirmed delete removes the `ac_row_hash` row (AC-22-21).

### 2.6 Scheduler

- Celery beat entry (workflow worker's beat, existing pattern): `autocount_etl_sweep` every
  minute. Sweep = one indexed query for due active tasks → for each, enqueue `background_jobs`
  `autocount_sync` with `{mode}` → bump `next_*_at`. No extraction in the sweep (AC-22-13).
- Overlap (AC-22-14): skip if an unfinished `autocount_sync` job exists for (tenant, company,
  entity); record a `skipped` run-history row. Claim via the existing atomic job-status claim.
- Eager/dev: `Run now` buttons enqueue the same job inline; beat not required locally.
- Activated tasks auto-push: job pipeline for `etl_status=active` runs fetch→map→stage→push in one
  job, no `needs_review` stop. `retryable` verdicts stay staged and re-push next run (AC-22-20).
  Manual API-path flow keeps its review gate untouched.

### 2.7 Run history

`ac_sync_run` gains `mode` (`manual|incremental|reconcile|skipped`), `rows_scanned`,
`deleted_count`, `duration_ms`. Task page renders history with cost columns (AC-22-17).

### 2.8 SO/PO canonicals

`canonical/documents.py`: `CanonicalSalesOrder` / `CanonicalPurchaseOrder` extending
`CanonicalRecord`, with `lines: list[CanonicalDocumentLine]`. Header task query returns header
rows; lines fetched per changed header by a second configured query (`lineQuery` in
`source_config`, `:doc_key` bound param) - avoids joining megarows and keeps line diffing local.
Refs: header `{database}:{DocKey}`, line `{database}:{DocKey}:{DtlKey}`. Status passes through
mapped (`status` canonical field + mapping formula); cancel = status update (AC-22-24).
`SorentoSink._ENTITY_PATH` gains `sales_orders`, `purchase_orders`, `sales_agents` + deletion
paths per Appendix A.

## 3. Frontend

Surfaces (all Resource-shell / existing autocount components; lavish mockup accompanies this plan):

1. **Connections**: registry-driven form renders the new provider automatically; verify only.
2. **Company → entity page (Database mode) = ONE task surface with five tabs** (mockup review
   2026-08-30): **Query · Mapping · Schedule · Review & Activate · Runs**.
   - Query tab: left schema tree (searchable, tables only, Expand all; clicking a table opens a
     **columns side panel**, lazy-introspected); center **CodeMirror SQL editor in v1** (SQL
     highlight, autocomplete fed by the introspected schema, bracket match); Test Query → preview
     grid (100 rows, column types, row count); below: key/watermark/compared column pickers fed by
     preview columns (`SearchSelect`/`MultiSelect`), from-date (documents). Document entities show
     a second **line query** field (`:doc_key` bound) - one task, two queries, never a separate
     lines task (header+lines ship as one canonical record).
   - Mapping tab: existing mapping editor; source path input becomes a dropdown of preview columns
     when source_impl=sql_db.
   - Schedule tab: incremental interval; reconcile mode = **"Daily at HH:MM" (tenant timezone) OR
     every-N-hours**, both day one.
   - Review & Activate tab: existing preview panel (dry-run summary + overwrite cards) → Activate
     gated on success; status chip (draft/active/paused), pause/resume.
   - Runs tab: run list + mode badge, scanned/added/updated/deleted counts, duration, skipped
     rows, last error on task.

Service trio: extend `autocount-service.{ts,mock,real}` (schema, preview, task CRUD, activate,
pause, run-now, history). Mock drives all editor states (loading/empty/error/success) in Phase 1.

## 4. Slices (vertical, in order)

| # | Slice | Proves | UAC |
|---|---|---|---|
| S1 | Connection provider + test + schema browse + query preview (FE mock → BE) | dialect runtime + guard | A, B |
| S2 | `sql_db` source for **customers** end-to-end: seam refactor, task config, mapping, manual Run now, dry-run activate, push | the spine | C, E, I |
| S3 | Scheduler: beat sweep, two cadences, overlap, watermark incremental, reconcile hash-diff, delete intents + guard (sink logs deletes until Sorento endpoint lands) | change detection | D, F |
| S4 | Master fan-out: suppliers, products, warehouses, categories, UOM, sales agents (sales agents deliver once Appendix A lands) | breadth | G(23) |
| S5 | SO/PO documents (canonicals, line queries, from-date) against Appendix A ingest | documents | G(24) |
| S6 | E2E + test report + DoD | | J |

Sorento standalone session runs Appendix A in parallel; S3 delete-push and S4 sales-agents and S5
integrate as its endpoints land (logging-sink fallback in the meantime, existing pattern).

## 5. Testing

- **Unit/integration (pytest, Postgres):** guard matrix, URL builder, preview wrap per dialect,
  hash normalization matrix, watermark advance, reconcile add/update/delete/no-change,
  compared-column exclusion, delete guard, sweep due-selection, overlap skip, source_ref parity,
  seam regression (existing suite untouched).
- **Dialect coverage:** local Postgres is the CI "source DB" (real engine, real introspection).
  MySQL/MSSQL: URL/limit/timeout branches unit-tested; live smoke against throwaway Docker
  `mysql:8` and `mcr.microsoft.com/mssql/server:2022` once, recorded in the test report (not CI).
- **Live verify:** real AutoCount = ask vsoft to port-forward 1433 on the demo wrapper box
  (fallback: AutoCount trial + "Mobile Phone Trading Sdn Bhd" sample book on a Windows VM).
  Deferred to the tail of S4; not a gate for S1-S3.
- **E2E (Playwright):** AC-22-31/32, source DB = the local Postgres itself with a seeded
  `etl_demo_customers` table (dev seed), dedicated tenant, real clicks, 375+1280.

## 6. Security notes

- Query text is tenant data - never rendered into errors/logs beyond a sanitized head; credentials
  never leave the backend; preview errors scrubbed of DSN.
- Watermark/limit wrapping never string-splices user input into SQL outside the validated column
  names + bound params.
- All new routes behind existing autocount permission keys (`require_permission`), connection
  lookups tenant-scoped (AC-22-29/30). Stored `connectionId` in `source_config` re-validated
  against tenant on every use (polymorphic-stored-id rule).

## 7. Backlog (register in `documentation/backlogs/backlog.md` on merge)

- BL: on-prem connector agent for unreachable customer DBs (Q1)
- BL: cron-expression scheduling (Q15)
- BL: extract SQL source + provider into a platform-core data-integration engine (Q3)
- BL: stock balances via AutoCount API (~2 weeks, Q18)
- BL: SO/PO write-back to AutoCount via API (Q10)

---

## Appendix A - Sorento cross-repo contract (standalone session brief)

Repo `/Users/tehjayson/Documents/foundryx/sorento_crm`. Everything below is Sorento-side work;
the shared-service repo consumes these shapes verbatim. Existing conventions apply: per-record
SAVEPOINT verdicts, always-200 batches, `?dry_run=true` real-run-rollback, X-API-Key +
`require_external_permission_for_path`, `IntegrationReferenceService` correlation.

### A1. Company-anchored ingest (fixes existing landmine)

- Every external ingest/read/deletion call resolves a company anchor: from the integration
  principal (integration → company binding) or an explicit `companyCode` field; missing/ambiguous
  → 422.
- `MasterIngestService` stamps `company_id` on INSERT (raw-INSERT path currently bypasses
  `CompanyScopedMixin` auto-stamp → NULL violation under migration 305) and scopes
  `_lookup_id` adoption by company (today it can adopt another company's row).
- `integration_reference` resolution keyed within company where the entity is company-scoped.

### A2. Sales-agent ingest

- `EntitySpec` for `sales_agents` (table exists, `app/models/sales_agent.py:42`, docstring already
  designates it the AutoCount mirror). Code column `sales_agent`; columns: description,
  is_active, person_label; annotations (`internal_note`, `follow_up`) untouched by re-sync.
- Add to `ENTITY_SPECS`, `_READ_COLUMNS`, `SUPPORTED_ENTITY_TYPES`, `INGEST_PERMISSIONS`/
  `READ_PERMISSIONS` + grant migration.

### A3. Document ingest (SO + PO)

- `POST /api/v1/external/ingest/sales_orders` and `/purchase_orders`: header + `lines[]` in one
  record. Targets are `public.sales_orders`/`public.purchase_orders` (NOT the `projects.*`
  same-named tables).
- Header keyed by `source_ref` (ladder: ref → adopt by `so_number`/`po_number` → create). Lines
  carry per-line `source_ref`; re-push upserts lines and removes lines absent from the payload.
- Master references (customer/supplier/product/agent/warehouse) resolved via integration refs;
  missing → `retryable` for the record (not the batch).
- Status arrives as a canonical string; Sorento maps to its own status enum; cancelled = update.
- dry_run + read-back (`POST /api/v1/external/read/{entity}`) for both.

### A4. Deletion endpoint

- `POST /api/v1/external/ingest/{entity}/deletions` body `{"source_refs": [...]}` (batch ≤1000).
- Per ref: resolve → try hard DELETE → FK/dependent failure → deactivate fallback (`is_active=false`;
  products: `is_discontinued=true`, `is_active` untouched per product.py:177 comment) → verdict
  `deleted | deactivated | not_found | failed` (+`errors`). Unlink the integration reference on
  hard delete only.
- dry_run supported (reports which verdict each ref WOULD get).

### A6. AS-AGREED SHAPES (Sorento session reply 2026-08-30 - these WIN over A1-A4 where they differ)

Sorento branch `feat/autocount-cross-repo-contract`, plan
`sorento_crm/.claude/worktrees/autocount-contract/documentation/plans/autocount/PLAN-autocount-cross-repo-contract.md`.

Endpoints (all X-API-Key, always-200 batches, per-record SAVEPOINT, `?dry_run=true`, batch <= 1000
else 413), entity in `product_categories | units_of_measure | warehouses | suppliers | customers |
products | sales_agents | sales_orders | purchase_orders`:
- `POST /api/v1/external/ingest/{entity}` body `{"companyCode": "SRT", "records": [...]}`
- `POST /api/v1/external/read/{entity}` body `{"companyCode": "SRT", "source_refs": [...]}`
- `POST /api/v1/external/ingest/{entity}/deletions` body `{"companyCode": "SRT", "source_refs": [...]}`

Deviations from A1-A4 and what they mean for THIS repo:
1. **`companyCode` is a top-level body field** on all three calls (matched case-insensitively on
   `companies.code`, then `companies.autocount_ref`; fallback = the integration's
   `config_json.company_code`). 422 codes: `COMPANY_ANCHOR_REQUIRED`, `UNKNOWN_COMPANY`,
   `COMPANY_ANCHOR_AMBIGUOUS` (body `{"code","message"}`, exact JSON confirmed when A1 lands).
   → `ac_company.sorento_company_code` (new column, required when `sink_impl='sorento'`);
   `SorentoSink` sends it on every call; a 422 anchor error = run failed with that code surfaced
   on the task (never per-record).
2. **Document status vocabulary is fixed**: SO/PO canonical `status` in
   `open | partial | fulfilled | closed | cancelled` (unknown = per-record failed `errors.status`).
   Sorento maps to its own enums. → the SO/PO mapping profile ships a required `status` canonical
   field; default mapping rows use a formula over AutoCount `Cancelled`/fulfilment columns; the
   editor's simulator must show the resulting value.
3. **Document lines reference masters by INTEGRATION REF, not code**: `customer_ref`,
   `sales_agent_ref`, `supplier_ref`, line `product_ref` (required) / `warehouse_ref` = the
   `source_ref` we pushed that master under. Unknown ref = whole record `retryable`, nothing
   written; absent optional ref = FK NULL. → line mapping mints refs with the SAME scheme as the
   master tasks (`{DatabaseName}:{key}`), which forces the master-task key column to be the same
   column the document line carries (e.g. `ItemCode`). Save-time validation: a document task's ref
   columns must be declared, and the run history surfaces `retryable` counts so a missing master
   sync is visible.
4. **Documents with dependents deactivate as `status='cancelled'`** (no `is_active` on documents).
5. Dependents are found by a pg_catalog FK probe before DELETE (customers → sales_orders is ON
   DELETE SET NULL, a bare DELETE would orphan). Verdict semantics unchanged for us.
6. **`sales_agents` rows are SHARED (company_id NULL)**: two companies pushing the same agent code
   under different source_refs = second is `failed`. → **decision: sales-agent source_ref is NOT
   company-qualified** - it is `agent:{CODE}` (upper/trim), so every company's task resolves to
   the one shared row (later pushes = `updated`). Documents' `sales_agent_ref` uses the same
   scheme. The only entity with an unqualified ref; documented in the task editor's key hint.

Record shapes (extra="forbid" everywhere; SorentoSink projects exactly these):
- sales_agents: `{source_ref, source_doc_no?, code(1..100), description?, is_active=true, person_label?}`
- sales_orders: `{source_ref=DocKey, so_number=DocNo (required, adopt key), customer_ref?,
  sales_agent_ref?, doc_date?, requested_delivery_date?, status, internal_note?, lines:[{source_ref=DtlKey,
  product_ref (required), warehouse_ref?, qty_ordered, qty_delivered?, unit_price?, discount?, line_total?,
  uom?, required_date?}]}`
- purchase_orders: same with `po_number`, `supplier_ref?`, `issue_date?`, `expected_date?`,
  `currency?`; lines `{source_ref, product_ref, warehouse_ref?, qty_ordered, qty_received?, unit_cost?,
  discount?, line_total?, uom?, currency?, expected_date?}`
- deletions response: `{dry_run, summary:{total,deleted,deactivated,not_found,failed},
  records:[{source_ref, outcome: deleted|deactivated|not_found|failed, entity_id, errors?}]}`
- permission slugs: `master_data.sales_agents.{edit,view,delete}`, `scm.sales_orders.*`,
  `scm.purchase_orders.*`; deletions need the entity's `.delete` on top of `.edit` (Sorento
  migration 445 sweeps `.delete` onto `integration_foundryx_esb`).

### A5. Acceptance (Sorento session's own tests)

Per-entity spec tests (ingest, read-back, dry-run, permission 401/403), company-anchor tests
(NULL-company regression, cross-company adoption blocked), document line-upsert/removal tests,
deletion fallback matrix. Existing `tests/test_external_company_anchor_scope.py` extended, not
bypassed.
