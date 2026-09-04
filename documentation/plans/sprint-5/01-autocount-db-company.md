# 01 - AutoCount DB-only company onboarding

> **Status:** DRAFT - fulfils `01-autocount-db-company-acceptance-criteria.md` (AC-01-01 … 24).
> **Branch:** `sprint-5/autocount-db-company`.
> **Builds on:** `sprint-4/13-autocount-esb.md` (company model, `CompanyService`),
> `sprint-4/22-autocount-db-etl.md` (`sql_database` provider, `SqlSourceRuntime`, task editor).
> **Follow-ups logged:** BL-SS-045 (AutoCount SQL presets), BL-SS-046 (second connection on a company).

## 1. Problem

`ac_company` is born only through `CompanyService.create_from_connection`, which resolves the
connection provider-pinned to `autocount` (`company_service.py:488-497`) and signs in to the
vendor API to discover `DatabaseName`/`CompanyName` (`:688-788`). A customer with direct SQL
access and no API licence hits "No AutoCount integration is connected yet." and can never reach
the `sql_db` tasks plan 22 built. `database_name` is load-bearing: it qualifies every
`source_ref` (`{DatabaseName}:{key}`) pushed to Sorento, and `etl_service.py:754-762` refuses any
task whose connection `config.database` differs from it.

## 2. Design

### 2.1 No schema change (D3)
`ac_company.connection_id` stays the single source connection. Kind is derived:
`source_kind(company, connection) = 'db' if connection.provider == SQL_DATABASE_PROVIDER_KEY else 'api'`.
`uq_ac_company_tenant_db` already enforces one company per database across both kinds (D14).

### 2.2 Backend - `CompanyService`

| Change | Where | Notes |
|---|---|---|
| `_source_connection(tenant_id, connection_id) -> Connection` | replaces `_connection` callers that only need the row | Tenant-scoped, provider ∈ {`autocount`, `sql_database`}; else `ConnectionNotFound` (uniform 404). `ConnectionRepository.get_for_providers(tenant_id, id, providers)` (new, one query). |
| `_connection` (API-pinned) | keep for `client_for` | `client_for` first checks kind; DB → `CompanyNotApiBacked` (409, AC-01-08). |
| `create(tenant_id, connection_id, *, name, transport=None)` | new dispatcher behind `POST ""` | Resolves the connection once, branches: `autocount` → existing `create_from_connection`; `sql_database` → `create_from_sql_connection`. Router changes one call. |
| `create_from_sql_connection(tenant_id, conn, *, name)` | new | 1. `get_by_connection` → 409 (D6). 2. `database_name = config["database"].strip()`. 3. `probe_current_database(conn)` → mismatch 422 / connect failure 422 (AC-01-02). 4. `company_name = read_profile_name(conn)` best-effort (AC-01-03). 5. `companies.add(...)` - existing `uq_ac_company_tenant_db` IntegrityError → 409 naming the holder (AC-01-04). 6. Activity `discover company`. 7. **No** `seed_company_defaults` (D13). |
| `seed_company_defaults` | unchanged | Called only on the API branch. |
| `update_entity_config(sourceImpl='autocount_read')` | guard | DB company → 422 "not available on a database company". Same guard rejects `goods_received_note` task creation on a DB company (AC-01-10). |
| `document_prerequisites(company)` | new, pure | `DOCUMENT_PREREQUISITES = {sales_order: (customer, product), purchase_order: (supplier, product)}`; reads the company's entity configs once; returns `[{entityType, missing, inactive}]` (AC-01-11). |

### 2.3 Backend - SQL probe helpers (`sql_source/runtime.py` + `sql_source/probe.py`)

- `CURRENT_DATABASE_SQL = {"mssql": "SELECT DB_NAME()", "postgresql": "SELECT current_database()", "mysql": "SELECT DATABASE()"}` next to `DIALECTS`.
- `probe_current_database(conn: Connection, *, credentials) -> str` - `RUNTIME.readonly_connection(conn.id, config, creds, timeout_s=CONNECT_TIMEOUT_SECONDS)` + `exec_driver_sql(...).scalar()`; errors → `sanitize_error` → `SqlProbeFailed(message)` (mapped to 422 on `connectionId`).
- `read_profile_name(conn, *, credentials) -> str` - mssql only (`SELECT TOP 1 CompanyName FROM dbo.Profile`), wrapped `try/except Exception → ""` (AC-01-03). Other dialects return `""` (AutoCount is MSSQL-only; the helper exists for symmetry, not speculation).
- Both are read-only, use the same runtime/engine cache as the task path (engine evicted on connection delete already, `bootstrap._evict_deleted_connection`).

### 2.4 Backend - `EtlService` lock (AC-01-09)
In `validate_source_config` (before the existing `connectionId` resolution at `:754`):
```
if source_kind == 'db':
    if not connection_id: connection_id = company.connection_id
    elif connection_id != company.connection_id:
        errors["connectionId"] = "A database company reads only from its own connection."
```
API company: unchanged. The existing `config.database == company.database_name` check then
holds by construction for DB companies.

### 2.5 Backend - schemas / router
- `CompanyItem` += `sourceKind: Literal['api','db']`, `documentPrerequisites: list[DocumentPrerequisite]` (detail only; list returns `[]`).
- List endpoint: `ConnectionRepository.get_many_for_tenant(tenant_id, ids)` - one `IN` query, dict by id (AC-01-07). Missing connection → `'api'` (never 500).
- `CompanyCreate` docstring updated: identity is discovered from the vendor login (API) or the connection's `database` (DB) - still never operator-typed.
- New error classes → `raise_autocount_http`: `CompanyNotApiBacked` 409, `SqlProbeFailed` 422 (`connectionId`), `SqlProbeMismatch` 422 (`connectionId`).

### 2.6 Frontend

**Connect form** (`companies/components/connect-company-view.tsx`)
- New `SegmentedControl`/`ToggleGroup` "Source": `api` | `db` (reuse the shell's segmented control used for Active|Trashed; no new primitive).
- Hook `useAutocountSourceConnections(kind)`: `api` → existing `useAutocountConnections()`; `db` → `useAutocountSqlConnections()` (server-scoped `GET /autocount/sql/connections`) minus companies' `connectionId`s. Both return `{options, hasAny, allBound, loading}` so the view has one code path.
- Default source: `api` if it has an unbound connection, else `db` if it has one, else `api` (AC-01-12).
- Banners per source (AC-01-13). Create disabled until picked. Inline `fieldErrors.connectionId` + 409 message (AC-01-14).

**Types / service**: `AutocountCompany.sourceKind`, `documentPrerequisites`; mock service gains a `sql_database` connection + a `db` company + prerequisite fixtures for every state.

**Company detail** (`company-detail-view.tsx`, `use-entities-list-config.tsx`, `add-entity-control.tsx`, `entity-source-dialog.tsx`, `autocount-meta.ts`)
- Integration row label from `sourceKind` (AC-01-16).
- `AC_SQL_DB_ENTITY_TYPES` (nine) in `autocount-meta.ts`; `AddEntityControl` picks `sourceKind === 'db' ? AC_SQL_DB_ENTITY_TYPES : AC_NEW_MASTER_ENTITY_TYPES` (AC-01-17). Parity test extends `test_autocount_entity_parity.py` to pin the nine against `ENTITY_PROFILES` minus GRN.
- Actions `edit-lookback`, `change-source`: `isVisible` gains `company.sourceKind !== 'db'` (AC-01-18).
- `DocumentPrerequisiteCard` above the list (AC-01-20): terminology labels via `useTerminology`, "Add entity" routes to `acTaskHref(companyId, entityType)`.

**Task editor** (`[entityType]/components/query-tab.tsx`)
- Prop `lockedConnection?: {id, label}`; when set, render a read-only `DetailRow` instead of the `SearchSelect`, pre-seed `config.connectionId`, suppress the `no-sql-connection` warning (AC-01-19). Parent passes it when `company.sourceKind === 'db'`.

### 2.7 Component-library discipline
Segmented control, `SearchSelect`, `DetailRow`, warning card (`Alert` variant already used for the inactive-company warning), `FormRow`. Nothing new.

## 3. Slices

1. **S1 FE mock** - form toggle + banners + create; detail kind label, add-entity list, hidden actions, prerequisite card; query-tab lock. All states via `autocount-service.mock`. Browser-verify 375/1280.
2. **S2 BE TDD** - probe helpers, `create` dispatcher + `create_from_sql_connection`, `sourceKind`/`documentPrerequisites` on the wire, API-path guards, task lock, entity-birth changes. Swap mock → real.
3. **S3 E2E + report** - `e2e/autocount-db-company.spec.ts` (AC-01-24), test report keyed to AC ids.

## 4. Tests (TDD, backend first-red)
`tests/test_autocount_db_company.py`: fixture = `_connection(db, "sql_database", {...database: DB_NAME}, {password})` from `test_autocount_etl_task_routes.py:120`; probe via `RUNTIME.put_engine(conn.id, sqlite_engine)` where the sqlite engine's `exec_driver_sql` is monkeypatched per case (match / mismatch / raise). Cases per AC-01-22. Frontend per AC-01-23 (Vitest + RTL). Regression: full `test_autocount*`.

## 5. Risks / notes
- **Probe on sqlite tests**: `CURRENT_DATABASE_SQL` has no sqlite entry → helper raises `SqlProbeFailed("unsupported dialect")`; tests inject the engine + patch the statement map. Live MSSQL verified manually against the ZeroTier relay (see memory `sorento-sql-zerotier-relay`) and recorded in the test report.
- **`dbo.Profile` shape** unverified from the customer's dump - best-effort by design.
- **Existing API companies** are untouched: derived kind = `'api'`, seeds unchanged, picker unchanged. Regression pins in every FE/BE test group.
- **Deleted connection**: `sourceKind` falls back to `'api'`; the existing "Open connection" link 404s as it does today.

## 6. Backlog additions
- **BL-SS-045** AutoCount SQL presets in the task editor (SO/PO/masters from `22-autocount-db-etl-autocount-sql.md`, pre-filled key/watermark/docDate/line-column config; validate on live MSSQL first).
- **BL-SS-046** Attach a second (API) connection to a DB company - prerequisite for BL-SS-041 (stock via API) and BL-SS-042 (write-back) when the customer onboarded DB-first. Adds `api_connection_id` then; `sourceKind` becomes `'db' | 'api' | 'both'`.
