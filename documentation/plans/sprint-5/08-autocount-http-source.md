# 08 - AutoCount open REST API source (multi-company, per-entity API / DB)

UAC: `08-autocount-http-source-acceptance-criteria.md` (the contract; this file is the design
that fulfils it). Lane `sprint-5/08-autocount-http-source`, worktree `.claude/worktrees/s37`
off `origin/main` 1028bda2 (module 0.9.0, module Alembic head 0019). Backend :8007, frontend
:3007, DB `foundryx_service_s37`.

## 1. Why

A second AutoCount API generation exists: an open REST wrapper (`https://hapi.sorento.cc.cd/api/
db1` for Sorento, `/api/db2` for Mocha) exposing items, debtors, locations and the item lookup
lists (group / type / brand / category / class). The owner wants (grill 2026-09-11):

- Sorento keeps its DB-fed SO / PO / SPO tasks AND takes masters from the REST API on the SAME
  company, every entity choosing API or DB on its own.
- Mocha, which has no database, onboards as an API-only company.
- No URL in code: base URLs live in connections; one `autocount` provider with an auth mode.
- Mapping edited in the frontend; endpoint path editable per entity.
- Run semantics follow the DB integration (reconcile hash-diff, optional watermark increment,
  same failure and delete rules).

The seam already exists: `ac_entity_config.source_impl` selects the fetch implementation PER
ENTITY (`sources.py` D6), the SQL source proved the hash / reconcile / schedule machinery is
source-agnostic, and BL-SS-081 ("attach a second connection to a company") predicted this
plan. What is new is the HTTP page-walking source, the open auth mode, the open-company
onboarding path, the `brand` entity, and the Endpoint tab.

## 2. Design

### 2.1 One provider, two auth modes (grill Q1, D1)

`AutoCountProvider.fields()` gains `authMode` (`select`: `vendor` | `none`, default `vendor`).
The three credential fields carry `showWhen: {field: "authMode", values: ["vendor"]}`. The
core connection form gains generic `showWhen` support next to `defaultsFrom`
(`connection-schema.ts` / `connection-form-fields.tsx`): hidden fields are dropped from the
required set and from the submitted config. `provider.py` exposes `auth_mode(config) -> str`
(absent = `vendor`) and `is_open_connection(conn)`; `test()` branches on it (AC-08-02).
`client_from_connection` is untouched (vendor only); a new `http_client.py` builds the open
transport.

Why not a second provider: the owner wants one AutoCount entry in the integrations picker. The
`erp` multiplicity carve-out already permits N `autocount` rows per tenant.

### 2.2 Base URL carries the company (grill Q4, D2)

Two connections: "Sorento REST" -> `https://hapi.sorento.cc.cd/api/db1`, "Mocha REST" ->
`.../api/db2`. No company-key field anywhere. Paths in tasks are RELATIVE (`/itembypage`).

### 2.3 Company model: no schema change (D3)

- `ac_company.connection_id` stays the single PRIMARY connection. `source_kind()` gains
  `"http"` (open connection). `CompanyItem.sourceKind: 'api'|'db'|'http'`.
- Open company creation = `create_from_open_connection` (AC-08-06/07): reachability probe,
  operator-typed **reference prefix** stored in `database_name` (the column every ref minter
  reads - `company_qualified_identity`), immutable through the existing "database_name never
  edited" rule. Mocha gets `MOCHA`; if Mocha ever gains a DB connection the operator types the
  same prefix on the SQL side (`config.database` must equal it, `etl_service` already checks).
- Sorento (a DB company, `AED_SORENTO`) needs NOTHING at company level: its HTTP tasks carry
  `source_config.connectionId` pointing at the "Sorento REST" open connection. The plan-01 lock
  "DB company reads only its own connection" (AC-01-09) is narrowed to `sql_db` tasks.

### 2.4 `HttpApiSource` (`http_source/`)

Package mirrors `sql_source/`: `source.py` (the `EntitySource`), `client.py` (httpx transport
with timeouts, `CallRecord` emission, masked / bounded like `client._record_call`),
`envelope.py` (paged vs list detection, page walk), `errors.py` (`HttpSourceError(code,
page, status)`), `preview.py`.

Fetch algorithm (`fetch_changes(since)`), same skeleton as `SqlDbSource.fetch_changes`:

1. `full_extract = mode == reconcile or not watermark_field`.
2. Walk: `GET {baseUrl}{path}?page=1&pageSize=1000`. Body dict with `Data` list ->
   paged: loop while `Page < TotalPages` (echoed) and `Data` non-empty, `MAX_EXTRACT_ROWS`
   guard; body list -> single page. One `CallRecord` per request.
3. `distinctOf` -> project to `{"value": v}` rows (trimmed, non-blank, first-seen order).
4. De-duplicate on `keyFields` (drift guard, WARNING activity with the count).
5. Incremental: keep rows whose `str(row[watermarkField]) > stored mark` (ISO strings sort
   lexically; AutoCount stamps carry no zone and are never converted); new mark = max seen,
   stored in `AcWatermark.cursor_json` under `CURSOR_MARK` / `CURSOR_COLUMN` exactly as SQL.
6. Reconcile / full: `hashing.row_hash(row, comparedFields)` vs `RowHashRepository`; classify
   added / updated / unchanged; missing refs -> `deleted_refs` (delete intents); the 20 % /
   50-row guard and `STAGED_OP_DELETE` staging are the EXISTING code in `sync.py`.
7. Any transport / shape / cap error raises before step 6 touches state (AC-08-23).

Reused, not copied: `hashing.row_hash`, `RowHashRepository`, `MAX_EXTRACT_ROWS`, the run-mode
constants, `SourceRecord`/`FetchResult`, `company_qualified_identity`, `sync.py` staging and
delete paths, `scheduler.py` sweep (its due-task query keys on `etl_status` + `next_*_at`,
not on `source_impl` - verify and add `autocount_http` to any impl filter it has).

### 2.5 Task configuration (`etl_service.py`, `routers/http.py`)

`validate_source_config` grows a per-impl branch: `_validate_http_config` (AC-08-13) beside the
SQL branch; schedule validation is shared. New router `routers/http.py` (prefix
`/autocount/http`, mounted like `/autocount/sql`): `GET /connections` (open connections),
`POST /preview` (page-1 sample, `distinctOf` projection, records `result_columns` when a task
is named). `EtlService.preview_task`/`_extract_and_map`/`activate_task`/`run_task_now`
dispatch on `source_impl` at the one place they build the source (`SourceContext` factory) -
no SQL runtime is ever touched for an HTTP task (AC-08-30).

### 2.6 Presets (`presets.py`)

`HttpPreset(label, path, key_fields, watermark_field, distinct_of, rows)` and
`HTTP_PRESETS: Dict[entity_type, HttpPreset]` for the six entities (rows per AC-08-16). Seeded
on first clean save through the existing seed-if-absent path, listed by
`list_mapping_presets` (the Mapping tab's "Use preset" already consumes that endpoint). Parity
test pins `HTTP_PRESETS.keys()` == backend `HTTP_ENTITY_TYPES` == frontend
`AC_HTTP_ENTITY_TYPES` and every canonical field named in a row exists on the entity class.

### 2.7 `brand` entity (grill round 3, D10)

`canonical/masters.py`: `ENTITY_BRAND`, `CanonicalBrand` (code <= 50, name <= 150 - Sorento's
DB widths; the canonical siblings allow 100 / 255 and would pass validation only to fail on
their DB). `ENTITY_PROFILES`, terminology, `ETL_ENTITY_TYPES`, `AC_SQL_DB_ENTITY_TYPES` (a DB
task may feed it too), `sinks_sorento._ENTITY_PATH["brand"] = "brands"`, `_DEPENDENT_ENTITIES`
unchanged (product already tolerates `retryable`; the brand row itself has no dependency).
`sorento_supports_entity("brand")` is contract-gated (>= 2.3, AC-08-33) so a brand task on a
2.2 consumer stages and logs instead of 422-ing.

### 2.8 Frontend

- `types/autocount.ts`: `AutocountSourceImpl` += `'autocount_http'`, `AutocountSourceKind`
  += `'http'`, `AutocountHttpSourceConfig`, `HttpPreview` types; service trio gains
  `listHttpConnections`, `previewHttp`; mock fixtures: an open connection, an open company
  (`MOCHA`), a paged preview (11,826 total) and a list preview, a 422 path error.
- `autocount-meta.ts`: `AC_SOURCE_IMPL_OPTIONS` += Open REST API; `AC_HTTP_ENTITY_TYPES`;
  `entitiesForSourceKind('http')`; `sourceKindLabel('http')`.
- `connect-company-view.tsx`: third `ToggleGroupItem` "Open REST API" (existing primitive);
  `useAutocountSourceConnections('http')` filters `provider === 'autocount' && config.authMode
  === 'none'` minus bound ids; "Reference prefix" field (plain `Input` from the form shell)
  with the derived default + helper text.
- `entity-source-dialog.tsx` / `add-entity-control.tsx`: options by entity set; locked single
  option on an open company.
- `[entityType]/components/endpoint-tab.tsx` (new, in the `query` tab slot when `sourceImpl
  === 'autocount_http'`): open-connection `SearchSelect` (or `lockedConnection`), `path`
  input, derived chips, Test as `DeferredActionButton`, `SqlPreviewGrid` reuse with an
  envelope `StatusBadge`, then the SAME key / watermark / compared pickers component the SQL
  tab uses (extract `ColumnPickers` from `query-tab.tsx` if it is not already a component; no
  second copy). `task-editor-view.tsx` picks the tab by `sourceImpl`.
- No new primitives, no motion beyond the shell's; `design-language.md` roster applies.

### 2.9 Sorento contract 2.3 (deploy order) - Appendix A

Cross-repo work for the Sorento owner session (`autocount` peer): a `brands` ingest entity.
The ESB merges only after 2.3 serves (same gate as plan 06 / 2.2); until then brand tasks fall
back to the logging sink by the contract check.

### 2.10 Security notes

The wrapper is public and unauthenticated (4,224 debtors with phones and credit limits). Owner
ruling: the API owner will add auth later. Our side: `authMode` select makes adding an API-key
header a field change (`headerName` / `headerValue` secret) not a schema change; `showWhen`
already hides it. Base-URL validation is the provider's existing rule; the ESB only ever GETs.

## 3. Files

Backend (`service_backend/modules/autocount/`):
`provider.py` (authMode, `auth_mode`, open test), `http_client.py`, `http_source/{__init__,
source,client,envelope,errors,preview}.py`, `models.py` (`SOURCE_IMPL_AUTOCOUNT_HTTP`),
`canonical/masters.py` (brand), `mapping.py` (`ENTITY_PROFILES` brand), `presets.py`
(`HTTP_PRESETS`), `services/company_service.py` (`source_kind` http, `create_from_open_
connection`, guards), `services/etl_service.py` (`_validate_http_config`, dispatch),
`routers/http.py`, `routers/companies.py` (`refPrefix`), `schemas.py`, `sinks_sorento.py`
(brands path, contract gate), `bootstrap.py` (register source + router), `scheduler.py`
(impl filter if any), `manifest.json` (0.10.0, router entry), `permissions/` (none new -
`autocount.manage` / `autocount.read` reused). Core: `app/integrations/base.py` docstring for
`showWhen`. Tests: `tests/test_autocount_http_source.py`, `..._http_preview.py`,
`..._open_company.py`, `..._brand.py`, parity test extension, provider test.

Frontend (`service_frontend/`): `types/autocount.ts`, `services/autocount-service.{ts,mock,
real}.ts`, `app/(protected)/autocount/components/autocount-meta.ts`,
`companies/components/{connect-company-view,entity-source-dialog,add-entity-control}.tsx` +
hooks, `companies/[id]/entities/[entityType]/components/{endpoint-tab,task-editor-view}.tsx`,
`settings/integrations/components/{connection-schema.ts,connection-form-fields.tsx}`, tests
beside each.

Docs: this pair, `documentation/engineering/process-lessons.md` AutoCount section (source impl
table, preset table, `pageSize` clamp gotcha), `integrations-email.md` (`showWhen`), backlog rows.

## 4. Slices and order

| Slice | Scope | UAC |
|---|---|---|
| S0 | Lane + docs commit; Appendix A sent to the Sorento peer | AC-08-34 (send) |
| S1 FE mock | Types, mock service, meta, connect form (http segment + prefix), source dialog, Endpoint tab, every state; agent-browser 375/1280 against the mock | AC-08-09/10/18/19/20 (mock) |
| S2 BE provider + company | authMode + showWhen (core form), open test, `create_from_open_connection`, `source_kind` http, guards, router `refPrefix` | AC-08-01..08 |
| S3 BE source + task | `http_source/`, validate, preview router, presets, dispatch, scheduler | AC-08-12..17, 22..30 |
| S4 BE brand | canonical, profile, sink path, contract gate, 429 test | AC-08-31..33, 35 |
| S5 wire + E2E | swap mock for real, prod build, recorded runs, live replay on db2 with the logging sink, failure + parity replays, report, docs | AC-08-11, 21, 36..40 |

Rule: S1 before any backend code (frontend-mock-first); S2..S4 TDD red-green; every coder /
tester brief embeds PRINCIPLES.md design mandates + DoD gate + hard-fails; reviewer (Opus) on
S2..S4 combined and again at merge gate; codex second opinion on the source package.

## 5. Risks and answers

- **Page drift** (rows inserted while walking): de-dup on key + WARNING; the reconcile hash
  diff self-heals next run. Never a silent truncation: a page error fails the run.
- **`pageSize` clamp**: never assume the requested size; loop on the ECHOED `TotalPages`.
- **Phantom deletes** from a partial walk: impossible by construction (AC-08-23) plus the
  existing 20 % guard as the second net.
- **Watermark as string**: `LastModified` is zone-less ISO; comparing strings is exact for
  this format and avoids inventing a zone. Documented in the source module docstring.
- **Ref parity on impl switch** (Sorento product DB -> HTTP): key must be `ItemCode` on both;
  the preset pins it; AC-08-39 proves 0 phantom deletes.
- **Sorento duplicate brands** (case / space variants vs product auto-create): brand tasks
  push BEFORE product tasks (operator order; the Review banner names it); Sorento's own
  normalisation is their side (Appendix A item 5).
- **Rate limit 600/min**: the first Mocha product load is ~12 batches; the sink's 429 handling
  covers bursts; AC-08-35 pins it.
- **Open API on the internet**: owner-accepted; §2.10.

## 6. Backlog

- BL-SS-201 - ItemType / ItemClass / ItemCategory lookups: no Sorento home (owner: not
  stored); revisit if Sorento adds product attributes.
- BL-SS-202 - API-key header on the open mode (`headerName`/`headerValue`) once the API owner
  adds auth.
- BL-SS-203 - Supplier / creditor and stock-balance endpoints on the open API (batch 2);
  links BL-SS-041.
- BL-SS-204 - Server-side `LastModified` filter on the wrapper would make incremental runs
  O(changes) instead of a full walk; ask the API owner.
- BL-SS-081 (existing) - closed by this plan for the "second source on a company" half; the
  `api_connection_id` column idea is superseded by task-level `connectionId`.

## 7. Decision log

| # | Decision | Why |
|---|---|---|
| D1 | One `autocount` provider, `authMode` select (`vendor` / `none`) | Owner: one provider; open API needs no login |
| D2 | Base URL includes the company segment; no company-key field | Owner: "usually people put v1/v2 there", two connections |
| D3 | No company schema change; `connection_id` = primary; HTTP tasks carry their own `connectionId` | Per-entity choice (owner), plan-22 seam already task-level |
| D4 | Open company `database_name` = operator-typed reference prefix | Mocha has no DB; every ref needs a prefix (Sorento BL-056) |
| D5 | `ItemGroup` -> category, `ItemBrand` -> brand; ItemType/Class/Category dropped | Matches Sorento live data + xlsx import; owner re-confirmed |
| D6 | UOM derived from distinct item UOM codes (`distinctOf`) | No UOM endpoint; products need UOM rows first |
| D7 | Reconcile default; incremental only with a watermark field, string-compared | API has no server filter; ISO strings sort |
| D8 | Any page failure fails the run before state changes | Partial list = phantom mass delete |
| D9 | Presets per entity, path editable | Owner: mapping from the frontend, path editable |
| D10 | `brand` canonical + Sorento `brands` ingest (contract 2.3), contract-gated | Owner: Sorento needs brand ingestion |
| D11 | `showWhen` added to the core connection form | Conditional credentials; generic, tiny, mirrors `NodeField.show_when` |
| D12 | Lane s37 :8007/:3007 | s36 held by plan 07 |

## Appendix A - Sorento contract 2.3 brief (for the `autocount` peer session)

Facts from your reply 2026-09-11 (origin/main 3bc23aeb0) drive this; do not re-derive.

1. **Entity `brands`** in `SUPPORTED_ENTITIES` (`app/api/v1/external/ingest.py:183`).
   Canonical `CanonicalBrand` beside `CanonicalProductCategory`
   (`app/schemas/canonical_masters.py:56-66`): `source_ref` (required), `source_doc_no?`,
   `code` (<= 50), `name` (<= 150), `description?`, `is_active?`; `extra="forbid"`, `""` = null.
2. **EntitySpec** (`master_ingest_service.py:596-599` sibling): table `brands`, code column
   `brand_code`, `_brand_columns` -> `brand_code = code`, `brand_name = name`, `description`,
   `is_active`; NOT NULL defaults per `:306-314`; company-scoped (`CompanyScopedMixin`,
   unique `(company_id, brand_code)`); `manufacturer` / `website` / `logo_url` /
   `access_levels` untouched (default).
3. **Permission maps** INGEST / READ / DELETE (`ingest.py:76-119`) -> `master_data.brands.
   {add,edit,view,delete}` (slugs exist). Confirm the `integration_foundryx_esb` role holds
   `master_data.brands.*` on prod (third query in your reply) or grant it in a migration.
4. **Allowlist** `IntegrationReferenceService.SUPPORTED_ENTITY_TYPES`
   (`integration_reference_service.py:57-76`) += `brands`; read-back `_READ_COLUMNS`
   (`master_read_service.py:39-95`); deletions `ENTITY_MODELS` + deactivation map
   (`deletion_service.py:117, :134-140`, a brand with products -> deactivate).
5. **Adoption of auto-created brands**: the product path creates `brands` with code = name =
   raw value; a later `brands` push must ADOPT that row by normalised code (trim, case-fold)
   rather than create a second one - please make the master adoption lookup for brands use
   `normalized_code=True` (`master_ingest_service.py:442-479`).
6. **Contract**: `contract.py:65-85` lists `brands`; version string `ingest.py:196` -> `2.3`.
   Products keep `brand_code` resolution unchanged.
7. **Company anchor**: nothing to change; the ESB sends `companyCode` per body (`SRT` /
   `MOCHA`). Owner to run the prod binding query from your reply before the first Mocha push.
8. Tests: route happy + 413 + permission denial; adoption of a pre-existing auto-created
   brand; deletion deactivation with dependents. Reply with the PR number when open; the ESB
   merge gate waits for 2.3 on prod.
