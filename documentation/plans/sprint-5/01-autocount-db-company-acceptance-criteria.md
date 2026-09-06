# 01 - AutoCount DB-only company onboarding - User Acceptance Criteria

> **Status:** DRAFT - contract for `documentation/plans/sprint-5/01-autocount-db-company.md`
> **Builds on:** `sprint-4/13-autocount-esb.md` (company + connection model),
> `sprint-4/22-autocount-db-etl.md` (the `sql_db` source, task editor, `sql_database` provider).
> **Closes the gap:** a company can today ONLY be created from a vendor-API (`autocount`)
> connection (`CompanyService.create_from_connection` signs in to discover `DatabaseName`).
> A customer that grants direct SQL access but no API licence cannot onboard at all, so the
> `sql_db` entity tasks built in plan 22 are unreachable for them.
> **Source of decisions:** grill session 2026-09-04 (19 questions, §Decision Log below).
> **Companion:** `sprint-4/22-autocount-db-etl-autocount-sql.md` (the SO/PO/master SQL pack the
> DB company will run - presets are a follow-up, BL-SS-080).

## Scope

**In:** create an AutoCount company from a `sql_database` connection; company identity derived
from the connection (verified live); provider-aware connection resolution; `sourceKind`
exposed on the company wire; DB companies seed no API entities and offer every `sql_db` entity
(incl. customer/supplier); task `connectionId` locked to the company's connection (backend
enforced); API-only row actions hidden on DB companies; prerequisite-master warning for
document entities.

**Out:** attaching a second (API) connection to a DB company (schema-ready via one column later;
BL-SS-081). AutoCount SQL presets in the task editor (BL-SS-080). Any change to the API-path
company flow beyond the shared form. Stock / write-back (BL-SS-041/042).

## Definitions

- **API company** - `ac_company` whose `connection_id` is an `autocount` provider connection.
- **DB company** - `ac_company` whose `connection_id` is a `sql_database` provider connection.
- **sourceKind** - `'api' | 'db'`, DERIVED from the connection's provider at read time. Never
  stored, never client-supplied.
- **Company connection** - the one connection on `ac_company.connection_id`. For a DB company
  every `sql_db` task's `source_config.connectionId` MUST equal it.
- **Prerequisite masters** - for `sales_order`: `customer` + `product`; for `purchase_order`:
  `supplier` + `product` (the refs Sorento cannot NULL or that carry the document's identity).

---

## Group A - Create a DB company `[BE]`

### AC-01-01 `[BE]` Create branches on the connection's provider
**Given** `POST /autocount/companies {connectionId, name?}`
**When** `connectionId` resolves (tenant-scoped) to a `sql_database` connection
**Then** a DB company is created without any vendor-API call
**And** when it resolves to an `autocount` connection the existing API flow runs unchanged
**And** any other provider, or a connection of another tenant, is 404 "That connection was not
found." (uniform - never reveals the other tenant's row).

### AC-01-02 `[BE]` Identity = the connection's database, verified live
**Given** a `sql_database` connection with `config.database = "AED_SORENTO"`
**When** a DB company is created from it
**Then** `database_name = "AED_SORENTO"` (trimmed, byte-identical to `config.database`)
**And** create opens the connection read-only and runs the dialect's current-database probe
(`SELECT DB_NAME()` mssql / `current_database()` postgresql / `DATABASE()` mysql)
**And** a probe result ≠ `config.database` is 422 on `connectionId`: "This login lands on
'<probe>', but the connection names '<config>'." - nothing is created
**And** connect/auth failure is 422 with the sanitized runtime message (never credentials).

### AC-01-03 `[BE]` Company name discovered best-effort
**Given** create of a DB company
**When** the AutoCount profile table is readable (`SELECT TOP 1 CompanyName FROM dbo.Profile`)
**Then** `company_name` is that value
**And** when the table is absent / unreadable / empty, `company_name = ""` and create still
succeeds (no error surfaced; the operator's `name` label is untouched).

### AC-01-04 `[BE]` One company per database, across both kinds
**Given** a company already exists for `database_name = X` (API or DB kind)
**When** a DB company is created from a `sql_database` connection whose `config.database = X`
**Then** 409 naming the existing company ("'X' is already connected as company '<label>'.")
**And** a `sql_database` connection already bound to a company yields the same 409
(`get_by_connection` guard applies to both providers).

### AC-01-05 `[BE]` No API-shaped seeds for a DB company
**Given** a DB company is created
**Then** NO `ac_entity_config` rows and NO `ac_field_mapping` rows are seeded
**And** an API company still seeds exactly `SEEDED_ENTITIES` as before (regression pin).

### AC-01-06 `[BE]` Activity log
**Given** a DB company is created
**Then** an activity row `discover company` is recorded with the probe outcome (database,
company name or blank) - same channel the API path uses.

## Group B - Provider-aware company wiring `[BE]`

### AC-01-07 `[BE]` `sourceKind` on the wire
**Given** `GET /autocount/companies` and `GET /autocount/companies/{id}`
**Then** each `CompanyItem` carries `sourceKind: 'api' | 'db'` derived from its connection's
provider (list endpoint resolves connections in ONE batched tenant-scoped query, never per row)
**And** a company whose connection was deleted reports `sourceKind` from the last-known provider
or `'api'` and is otherwise unchanged (no 500).

### AC-01-08 `[BE]` Vendor-API paths refuse a DB company cleanly
**Given** a DB company
**When** any path that needs the vendor client runs (`client_for`, an `autocount_read` sync,
`update_entity_config(sourceImpl='autocount_read')`)
**Then** it fails 409/422 with "This company is connected by database; the AutoCount API is not
available." - never `ConnectionNotFound`, never a 500.

### AC-01-09 `[BE]` Task connection locked to the company connection
**Given** a DB company and `PUT /companies/{id}/etl-task/{entity}` (or preview)
**When** `source_config.connectionId` is omitted
**Then** the server fills it with `company.connection_id`
**And when** it is present and ≠ `company.connection_id`
**Then** 422 on `connectionId`: "A database company reads only from its own connection."
**And** an API company keeps today's free picker behaviour (regression pin).

### AC-01-10 `[BE]` All `sql_db` entities addable on a DB company
**Given** a DB company
**When** a task is first saved for `customer` or `supplier` (today API-seeded entities)
**Then** the row is born with `source_impl = 'sql_db'` exactly like the other seven
**And** `goods_received_note` is 422 "not available on a database company" (no Sorento path,
API-only envelope).

### AC-01-11 `[BE]` Prerequisite-master status endpoint
**Given** `GET /autocount/companies/{id}` for any company
**Then** the response carries `documentPrerequisites: [{entityType, missing: [...],
inactive: [...]}]` for each configured document entity (`sales_order`, `purchase_order`),
computed from the company's entity configs (`missing` = no config row; `inactive` = row exists
but `etl_status != 'active'` / `is_enabled = false`)
**And** the list is empty when no document entity is configured.

## Group C - Connect-company form `[FE]`

### AC-01-12 `[FE]` Source toggle
**Given** `/autocount/companies/new`
**Then** a "Source" segmented control offers **AutoCount API** | **SQL database**, defaulting to
whichever has an unbound connection available (API first when both do)
**And** the connection picker below is a `SearchSelect` filtered to the chosen source's
provider, excluding connections already bound to a company
**And** switching source clears the picked connection.

### AC-01-13 `[FE]` Per-source empty states
**Given** the SQL database source is selected and no unbound `sql_database` connection exists
**Then** the banner reads "No SQL database connection yet." with a link to
`/settings/integrations/new` (or "Every SQL database connection is already registered as a
company." when all are bound)
**And** the API source keeps today's two banners
**And** Create is disabled until a connection is picked.

### AC-01-14 `[FE]` Create + errors
**Given** a `sql_database` connection is picked
**When** Create is clicked
**Then** `createCompany({connectionId, name})` is called (same call as API), success routes to
the new company's Overview
**And** a 422 on `connectionId` renders inline under the picker (probe mismatch / auth failure),
a 409 renders inline naming the existing company.

### AC-01-15 `[FE]` Responsive
**Given** the form at 375px and 1280px
**Then** toggle, picker, label and banner stack without horizontal scroll or clipping.

## Group D - Company detail on a DB company `[FE]`

### AC-01-16 `[FE]` Overview shows the kind
**Given** a DB company's Overview
**Then** the Integration row reads "SQL database" and links to the connection; an API company
reads "AutoCount API" (label only; the link exists today).

### AC-01-17 `[FE]` Add-entity offers every `sql_db` entity
**Given** a DB company's Entities tab
**When** Add entity is opened
**Then** the list is all nine `sql_db` entities (`customer`, `supplier`, `product_category`,
`unit_of_measure`, `warehouse`, `product`, `sales_agent`, `sales_order`, `purchase_order`) minus
those already configured; `goods_received_note` is absent
**And** an API company keeps today's seven (regression pin).

### AC-01-18 `[FE]` API-only actions hidden
**Given** a DB company's entity rows
**Then** `edit-lookback` and `change-source` are not rendered (row menu and bulk)
**And** `configure-task`, `sync-now`, `configure-mapping`, `refetch-history` remain
**And** an API company's rows are unchanged.

### AC-01-19 `[FE]` Task editor: connection locked
**Given** the task editor (Query tab) for an entity on a DB company
**Then** the Connection `SearchSelect` is replaced by a read-only row showing the company
connection (`name · database`) and `config.connectionId` is pre-set to it
**And** the "No SQL database connection yet." warning never renders for a DB company
**And** an API company keeps the picker.

### AC-01-20 `[FE]` Prerequisite warning
**Given** a DB or API company with a configured `sales_order` / `purchase_order` task
**When** any prerequisite master is missing or inactive
**Then** a warning card renders above the Entities list, one line per document entity:
"Sales orders will stay retryable until **Customers** and **Products** are active." (naming
only the missing/inactive ones, using terminology labels), with an "Add entity" affordance for
missing ones
**And** the card is absent when all prerequisites are active or no document entity exists.

### AC-01-21 `[FE]` Responsive
**Given** Overview, Entities tab (with warning card), and the task editor Query tab at 375px and
1280px
**Then** no horizontal scroll, no clipped controls; the warning card wraps.

## Group E - Tests `[T]` / `[E2E]`

### AC-01-22 `[T]` Backend
- create from `sql_database`: identity from config, probe match, probe mismatch 422, auth
  failure 422, profile name best-effort (present / absent table), 409 same database via API
  company, 409 bound connection, no seeds, activity row.
- `sourceKind` on list + detail; batched connection load (query-count assertion).
- vendor-API paths refuse a DB company (`client_for`, `sourceImpl='autocount_read'`).
- task lock: fill when omitted, 422 when different, API company unaffected.
- `customer`/`supplier` born `sql_db` on a DB company; GRN 422.
- `documentPrerequisites` matrix (none configured / missing / inactive / all active).
- Regression: full existing `test_autocount*` suite green.

### AC-01-23 `[T]` Frontend
- connect-company: toggle default, filtered picker, per-source banners, disabled Create,
  inline 422/409.
- company-detail: kind label, add-entity list per kind, hidden actions per kind, warning card
  matrix.
- query-tab: locked connection row on DB company, picker on API company.
- `autocount-service.mock` drives every state (no backend).

### AC-01-24 `[E2E]` Real-click journey
**Given** a fresh tenant with a `sql_database` connection pointing at the E2E Postgres source
(plan 22's `etl_demo_customers` rig)
**When** the operator clicks Apps → AutoCount → Companies → Connect company → SQL database →
picks the connection → Create → Entities → Add entity → Customer → saves a query → Preview
**Then** the company appears with Integration "SQL database", the Add-entity list includes
Customer, the Query tab shows the locked connection, preview returns rows
**And** the spec provisions its own tenant + timestamped names (parallel-safe).

## Group F - Definition of Done `[T]`

- No frontend mock left behind (`autocount-service.real` wired, live-verified).
- No new columns → no backfill; `sourceKind` derivation verified against existing API companies
  on the live DB (all report `'api'`).
- No new permission (existing `autocount.companies.manage` gates create).
- Verified from the user's perspective on a fresh build at 375px + 1280px, ports 3001/8001.

---

## Decision Log (grill 2026-09-04)

| # | Decision |
|---|---|
| Q1 | Identity = connection `config.database` (verified by live probe), never operator-typed. |
| Q2 | `company_name` best-effort from `dbo.Profile`, blank on failure. |
| Q3 | ONE `connection_id`, no schema change; `sourceKind` derived from the connection provider. |
| Q4 | A company holds one connection in this slice (attach-later = BL-SS-081). |
| Q5 | Form: Source toggle first, then provider-filtered picker. |
| Q6 | One company per SQL connection (app-level `get_by_connection` guard, both providers). |
| Q7 | Task `connectionId` locked to the company connection. |
| Q8 | Add-entity on a DB company lists only `sql_db`-capable entities, default `sql_db`. |
| Q9 | AutoCount SQL presets = separate follow-up slice (BL-SS-080). |
| Q10 | Prerequisite-master warning card, read-only, no block. |
| Q11/Q18 | `sprint-5/01-autocount-db-company`. |
| Q12 | Probe `DB_NAME()` at create; mismatch = 422. |
| Q13 | DB company seeds nothing; add-entity offers all nine `sql_db` entities. |
| Q14 | Same DB twice (API + SQL) = 409, one company per database. |
| Q15 | Lock enforced in the backend (fill + 422), UI hides the picker. |
| Q16 | Hide `edit-lookback` + `change-source` on DB companies. |
| Q17 | Prerequisites = `customer`/`supplier` + `product` only; card on Entities tab. |
| Q19 | Profile-name failure is silent. |
