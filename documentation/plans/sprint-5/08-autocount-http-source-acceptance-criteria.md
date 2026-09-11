# 08 - AutoCount open REST API source (multi-company, per-entity API / DB) - User Acceptance Criteria

Plan: `08-autocount-http-source.md`. Lane `sprint-5/08-autocount-http-source`
(worktree `.claude/worktrees/s37`, off `origin/main` 1028bda2, module 0.9.0, module Alembic
head 0019). Lane ports backend :8007 / frontend :3007, DB `foundryx_service_s37`.

Source: a second AutoCount API generation, an open (unauthenticated) REST wrapper at
`https://hapi.sorento.cc.cd/api/db1` (Sorento) and `.../api/db2` (Mocha). Probed 2026-09-11,
read-only: `GET /location`, `/ItemGroup`, `/ItemType`, `/ItemBrand`, `/ItemCategory`,
`/ItemClass` return a bare JSON array (no timestamps); `GET /itembypage?page=N&pageSize=1000`
and `/debtorbypage?...` return `{TotalCount, Page, PageSize, TotalPages, Data[]}` with
`LastModified` (ISO-8601, no zone) per row. `pageSize` above 1000 is silently CLAMPED (5000 ->
200); a page past `TotalPages` returns `Data: []`. No profile / company endpoint exists.
db1: 11,826 items, 4,224 debtors, ~60 item groups, 12 brands, `ItemCategory` empty.

Consumer: Sorento CRM contract 2.2 (deployed 2026-09-08). Facts from the Sorento owner session
2026-09-11: the xlsx import maps AutoCount Item Group -> `product_categories` and Item Brand ->
`brands`; `products` has no column for item type / class / category (ingest is `extra="forbid"`);
`brands` has NO ingest entity yet (`brand_code` <= 50, `brand_name` <= 150 on their DB);
ingest anchors a company by body `companyCode` unless the integration key is bound; ingest never
creates a `companies` row (MOCHA exists, hand-created); rate limit 600 requests / 60 s per key
(429 + `Retry-After`); batch max 1000.

Tags: `[BE]` backend pytest, `[FE]` frontend vitest, `[E2E]` recorded agent-browser run,
`[T]` tester-owned proof (mutation / live replay / docs).

## Definitions

- **source kind** - `api` (an `autocount` connection) or `db` (a `sql_database` connection).
  The operator's two words (plan review 2026-09-11); every picker uses them.
- **open connection** - an `api` connection with `config.auth == "none"`. Config = `baseUrl`
  only; the base URL INCLUDES the company segment (`https://hapi.sorento.cc.cd/api/db1`). No
  credentials.
- **basic connection** - an `api` connection with `config.auth == "basic"` (or absent = legacy
  rows): today's AppId / User ID / Password, login test, unchanged fetch grammar
  (`autocount_read`, GRN / supplier / customer only).
- **HTTP task** - an `ac_entity_config` row with `source_impl == "autocount_http"`. Its
  `source_config` = `{connectionId, path, keyFields[], watermarkField?, comparedFields[],
  distinctOf?[], incrementalMinutes, reconcileMode, reconcileHours?, reconcileAt?}`.
- **open company** - an `ac_company` whose primary `connection_id` is an open connection.
  `sourceKind == "http"`. Its `database_name` is the operator-typed **reference prefix**.
- **ref prefix** - `ac_company.database_name`; every pushed ref is `{prefix}:{key}` exactly as
  today (`mapping.company_qualified_identity`).
- **page walk** - for a `Data[]` envelope: request `page=1..N` with `pageSize=1000`, stop when
  `Page >= TotalPages` (as ECHOED by the server) or `Data` is empty; for a bare array: one request.
- **HTTP entity set** - `product`, `customer`, `warehouse`, `product_category`, `brand`,
  `unit_of_measure`.

## Group A - provider and connection (`[BE]` / `[FE]`)

- **AC-08-01 [BE]** `AutoCountProvider.fields()` gains a leading `auth` select (`basic` =
  "Basic auth (AppId + user + password)", `none` = "No auth"; default `basic`). The three
  credential fields carry `showWhen: {field: "auth", values: ["basic"]}`; `baseUrl` is always
  shown. Legacy rows without `auth` behave as `basic` everywhere (`auth_mode(config)` helper,
  one place).
- **AC-08-02 [BE]** `provider.test()` with `auth == "none"`: `GET {baseUrl}/location`
  with a 10 s timeout; a 2xx JSON array -> `ok=True` with message naming the row count; any
  network error, non-2xx, or non-array body -> `ok=False` naming the step ("reachability" /
  "not JSON" / "HTTP 404") and never the raw body. Credentials are NOT required and a login is
  NEVER attempted in this mode. `auth == "basic"` is byte-for-byte today's behaviour.
- **AC-08-03 [BE]** `base_url` validation for `none` is the same rule the provider applies
  today (scheme `http`/`https`, no trailing whitespace); a trailing `/` is stripped once at
  save so `{baseUrl}/location` never double-slashes.
- **AC-08-04 [FE]** The core connection form renders `select` fields and honours `showWhen`:
  switching `auth` to `none` hides AppId / User ID / Password and clears their required
  state; switching back restores them. Unit test on `connection-schema.ts` + the field
  component. No other provider changes behaviour (`showWhen` absent = always shown).
- **AC-08-05 [T]** `documentation/engineering/integrations-email.md` documents `showWhen`
  next to `defaultsFrom` as a `ProviderField` key.

## Group B - open company onboarding (`[BE]` / `[FE]`)

- **AC-08-06 [BE]** `CompanyService.create` dispatches on `auth_mode(conn.config)`: an open
  connection routes to `create_from_open_connection(tenant_id, conn, *, name, ref_prefix)`.
  Steps: `get_by_connection` -> 409 (one primary company per connection, unchanged); probe
  `GET {baseUrl}/location` -> connect failure / non-array -> 422 on `connectionId`;
  `database_name = ref_prefix`; `company_name = name`; activity `discover company` with
  `source: "autocount_http"`; NO `seed_company_defaults` (mirrors the DB branch, D13 of plan 01).
- **AC-08-07 [BE]** `ref_prefix` is required for an open connection (422 `refPrefix` when
  blank), trimmed, upper-cased, `^[A-Z0-9_]{2,32}$`, unique per tenant through the existing
  `uq_ac_company_tenant_db` (IntegrityError -> 409 naming the holder). It is ignored (422
  "not applicable") when the connection is `vendor` or `sql_database`.
- **AC-08-08 [BE]** `source_kind(connection)` returns `"http"` for an open connection;
  `CompanyItem.sourceKind` is `Literal['api','db','http']`; `client_for` on an open company
  raises `CompanyNotApiBacked` (409) exactly as for a DB company; `update_entity_config(
  sourceImpl='autocount_read')` and `goods_received_note` creation on an open company -> 422.
- **AC-08-09 [FE]** Connect form's Source toggle stays TWO segments, "API" | "Database". The
  API connection picker lists every `autocount` connection with no company bound, each option
  labelled with its auth ("Basic auth" / "No auth"). Picking a No-auth connection reveals a
  "Reference prefix" text field pre-filled from the label (upper-cased, non-alphanumerics ->
  `_`), editable, helper text "Prefixes every record reference sent to the consumer. Cannot be
  changed later."; a Basic-auth pick keeps today's discovery flow with no prefix field. Create
  is disabled until connection (+ prefix when shown) is valid; 422 `refPrefix` lands inline.
- **AC-08-10 [FE]** Company detail Integration row reads "API (no auth)" for `sourceKind ==
  "http"` and "API (basic auth)" for `api`; `edit-lookback` / `change-source` / GRN entity actions are hidden for it (same
  predicate that hides them for `db`).
- **AC-08-11 [E2E]** Settings -> Integrations -> add AutoCount connection, Auth "No auth", base URL `https://hapi.sorento.cc.cd/api/db2`, Test -> success naming the
  location count; AutoCount -> Companies -> Connect -> "API" -> that connection (badge "No auth") ->
  label `Mocha <ts>`, prefix auto `MOCHA_<TS>` -> Create -> detail shows Integration "API (no
  auth)" and the reference prefix. 375 + 1280, evidence dir `08-evidence/open-company/`.

## Group C - HTTP task configuration (`[BE]` / `[FE]`)

- **AC-08-12 [BE]** `SOURCE_IMPL_AUTOCOUNT_HTTP = "autocount_http"` is registered
  (`register_http_source()` from `bootstrap`) and accepted by `update_entity_config`'s
  `sourceImpl` on: an open company (only choice), a DB company (beside `sql_db`), a vendor-API
  company (beside `autocount_read` / `sql_db`) - for entities in the HTTP entity set ONLY.
  `goods_received_note`, `supplier`, `sales_agent`, `sales_order`, `purchase_order`,
  `shipping_order` with `autocount_http` -> 422 naming the entity.
- **AC-08-13 [BE]** `validate_source_config` for `autocount_http`: `connectionId` must resolve
  tenant-scoped to an `autocount` connection with `auth == "none"` (a vendor or SQL id ->
  422 `connectionId`); `path` required, must start with `/`, no `..`, no query string (page
  params are ours), <= 200 chars; `keyFields` non-empty and each present in
  `result_columns` once a preview exists (else 422 "Test the endpoint first"); `watermarkField`
  optional, must be in `result_columns`; `comparedFields` default = every result column minus
  the key fields; `distinctOf` optional list of result columns - when set, `keyFields` must
  equal `["value"]` (see AC-08-22); schedule fields reuse the SQL validator verbatim
  (`incrementalMinutes >= 1` only when `watermarkField` set; reconcile `interval`/`dailyAt`).
  Plan 01's "DB company reads only its own connection" lock (AC-01-09) applies to `sql_db`
  tasks only - an HTTP task on a DB company may reference ANY open connection of the tenant.
- **AC-08-14 [BE]** `POST /autocount/http/preview {connectionId, path, distinctOf?}` (perm
  `autocount.manage`, same as `/autocount/sql/preview`): fetches page 1 with `pageSize=50`
  (or the bare array, capped to the first 50 rows), returns `{envelope: "paged"|"list",
  totalCount?, columns[{name, sample}], rows[<=50], durationMs}`. Errors map to 422 with the
  step named (`connectionId` for a bad connection, `path` for 404 / non-JSON / timeout). With
  `distinctOf`, rows are the distinct projection (`{value}`) and `columns == [value]`. Records
  `last_preview_at` / `result_columns` on the task exactly as the SQL preview does when
  `companyId` + `entityType` are passed.
- **AC-08-15 [BE]** `GET /autocount/http/connections` lists the tenant's `autocount`
  connections (`{id, name, baseUrl, auth: "basic"|"none"}`), tenant-scoped, `autocount.read`,
  so the Source tab can badge each option and derive the impl.
- **AC-08-16 [BE]** First clean save of an HTTP task with an empty mapping seeds the entity's
  **HTTP preset** (`presets.HTTP_PRESETS[entity_type]`: `path`, `keyFields`,
  `watermarkField`, `distinctOf`, mapping rows) through the same seed-if-absent contract as
  `seed_document_mapping`; `GET /autocount/presets/{entity_type}?companyId=` lists it for the
  Mapping tab's "Use preset" action. Presets (source field -> canonical):
  - `product` `/itembypage` key `ItemCode` wm `LastModified`: `ItemCode->code`,
    `Description->name`, `Desc2->description`, `ItemGroup->category_code`,
    `ItemBrand->brand_code`, `BaseUOM->uom_code`, `IsActive->is_active` (transform
    `t_f_bool`), `Discontinued->is_discontinued` (`t_f_bool`).
  - `customer` `/debtorbypage` key `AccNo` wm `LastModified`: `AccNo->code`,
    `CompanyName->name`, `Phone1->phone_number`, `IsActive->is_active` (`t_f_bool`). Only
    fields `CanonicalCustomer` already declares (code, name, email, phone_number, tax_id,
    is_active); no new customer fields in this plan.
  - `warehouse` `/location` key `Location`: `Location->code`, `Description->name`,
    `Address1->location`, `IsActive->is_active` (`t_f_bool`).
  - `product_category` `/ItemGroup` key `ItemGroup`: `ItemGroup->code`, `Description->name`
    (required), `Desc2->description`. No `is_active` row (the list carries none; the consumer's
    default applies).
  - `brand` `/ItemBrand` key `ItemBrand`: `ItemBrand->code`, `ItemBrand->name` (the vendor
    list's `Description` is blank on every probed row; name = code matches what Sorento's
    product path auto-creates today), `Description->description`. No `is_active` row.
  - `unit_of_measure` `/itembypage` `distinctOf ["BaseUOM","SalesUOM","PurchaseUOM"]` key
    `value`: `value->code`, `value->name`. `decimal_places` stays the canonical default 0.
  No preset row is a constant: the mapping engine has no constant transform and this plan
  does not add one.
- **AC-08-17 [BE]** A parity test pins `HTTP_PRESETS.keys() == HTTP_ENTITY_TYPES ==
  autocount-meta.ts AC_HTTP_ENTITY_TYPES` and that every preset canonical field exists on the
  entity's canonical class (`SINK_FIELDS` or declared field).
- **AC-08-18 [FE]** `AutocountSourceImpl` gains `'autocount_http'`; `AC_HTTP_ENTITY_TYPES`
  (six) is exported; `entitiesForSourceKind('http') == AC_HTTP_ENTITY_TYPES`. The source
  choice moves to the task's Source tab (AC-08-19): the `change-source` action and
  `entity-source-dialog.tsx` are REMOVED (one place). "Add entity" creates the task with the
  company's default (`db` company -> Database, `http` company -> API, `api` company -> API)
  and opens the Source tab. `AC_SOURCE_IMPL_OPTIONS` is deleted with the dialog; the impl is
  derived: Database -> `sql_db`; API + no-auth connection -> `autocount_http`; API +
  basic-auth connection -> `autocount_read` (offered only for `AC_API_CAPABLE_ENTITY_TYPES`,
  other entities show the picker option disabled with the reason "Basic-auth API supports
  GRN, supplier and customer only").
- **AC-08-19 [FE]** The task editor's first tab is renamed **Source** (`AcTaskTab` value
  `query` kept for the route; label changes). It opens with a two-segment "API" | "Database"
  toggle (the shell's `ToggleGroup`). **Database** renders today's SQL query editor unchanged
  (connection locked on a DB company). **API** renders: connection `SearchSelect` listing the
  tenant's `autocount` connections with an auth badge per option (from AC-08-15, which now
  returns both auths; on an `http`/`api` company locked to the company's own connection via
  `lockedConnection`), `path` text input (preset-filled, editable, monospace; read-only vendor
  path for a basic-auth connection), a read-only "Derived from distinct values of" chip list
  when `distinctOf` is set, a **Test** `DeferredActionButton` -> preview grid (reuse
  `SqlPreviewGrid`) with the envelope badge ("Paged · 11,826 total · 12 pages of 1000 - a run
  walks every page" / "List · 60 rows · one request"), then the key / watermark / compared
  pickers fed by the preview columns (the SQL tab's pickers extracted into one shared
  component, dropdowns never free text). Toggling API <-> Database on a saved task shows the
  dirty guard and, on save, AC-08-28 applies (status back to draft). Mapping, Schedule,
  Review & Activate and Runs tabs are the existing components untouched.
- **AC-08-20 [FE]** States: no API connection ("Add an AutoCount API connection in
  Settings -> Integrations" with link), preview loading (skeleton), preview error (422 message
  inline on `path`), preview success, unsaved-changes dirty guard (shell AlertDialog). Save is
  disabled until a preview succeeded after the last `path`/`connectionId` change (same rule as
  the SQL tab's "Test a query first").
- **AC-08-21 [E2E]** On the Mocha company from AC-08-11: Add entity "Product" -> Source tab
  opens on API with the company's connection locked, `/itembypage` preset -> Test -> "Paged ·
  N total · 12 pages of 1000", key `ItemCode`, watermark `LastModified` pre-picked -> Save -> Mapping tab shows the seeded preset rows -> Schedule
  tab -> Review & Activate. Repeat for "Brand" (`/ItemBrand`, list envelope) and "Unit of
  measure" (derived chip). 375 + 1280, evidence `08-evidence/http-task/`.

## Group D - extraction, hashing, run modes (`[BE]`)

- **AC-08-22 [BE]** `HttpApiSource(ctx, *, entity_type, mode, ...)` implements `EntitySource`
  (`fetch_changes`, `drain_activity`, `close`). Page walk per the definition; `pageSize=1000`
  requested, the ECHOED `PageSize`/`TotalPages` trusted; rows de-duplicated on `keyFields`
  across pages (first occurrence wins, duplicates counted into a WARNING activity naming the
  count - page drift while walking). `distinctOf` projects each row's listed fields into one
  record per distinct non-blank trimmed value `{"value": v}` and reports `rows_scanned` as
  the rows read, not the values emitted. `reported_total = TotalCount` when paged.
- **AC-08-23 [BE]** Every request carries a 30 s timeout and `Accept: application/json`; a
  non-2xx, a timeout, a connection error, a non-JSON body or a page whose shape differs from
  page 1 (paged vs list) FAILS the run (`HttpSourceError` with page number and status, body
  never logged beyond 200 chars): nothing is staged, no hash row is touched, no delete intent
  is computed, the watermark cursor is not advanced. Mutation test: a stub that 500s on page 3
  of 5 leaves `ac_row_hash` and `ac_watermark` byte-identical.
- **AC-08-24 [BE]** `MAX_EXTRACT_ROWS` (200,000) is shared with the SQL source; exceeding it
  fails loudly with the same error code. `drain_activity()` yields one `CallRecord` per page
  (method, path with page params, status, duration, row count) so the Runs tab shows the
  request count.
- **AC-08-25 [BE]** Run modes mirror `sql_db` exactly: `manual` (activate-once dry-run gate
  via `preview_task`, then `run_task_now`), `incremental` (only when `watermarkField` set:
  full walk, rows kept where `str(row[watermarkField]) > stored mark`, mark compared as the
  raw ISO string, new mark = max seen, advanced only after the whole run succeeds),
  `reconcile` (full walk, `ac_row_hash` diff via `hashing.row_hash(row, comparedFields)`,
  adds / updates / delete intents, the existing 20 % + 50-row delete guard, `STAGED_OP_DELETE`
  staging, `sync._stage_deletes` untouched). A task without `watermarkField` has no
  incremental cadence (the Schedule tab hides it, as it does for SQL tasks without a watermark).
- **AC-08-26 [BE]** `IsActive == "F"` (and any `t_f_bool` false) stages an UPSERT with
  `is_active=false`; it is never a delete intent. A ref missing from a reconcile walk is the
  ONLY delete intent source.
- **AC-08-27 [BE]** Refs: `company_qualified_identity(raw[keyFields...], company.database_name)`
  -> `{prefix}:{key}` (multi-key joined with `|`, as SQL). Test: a product `ItemCode "SRT-01"`
  on the Sorento company mints `AED_SORENTO:SRT-01` whether the task's `source_impl` is
  `sql_db` or `autocount_http`.
- **AC-08-28 [BE]** Changing an active task's `sourceImpl` (either direction) or its
  `connectionId` / `path` sets `etl_status` back to `draft` (must Test + re-activate) and
  keeps `ac_row_hash` rows (so the first reconcile after a switch reports updates for changed
  hashes and NO phantom deletes when the key is unchanged). Documented on the Review & Activate
  tab banner.
- **AC-08-29 [BE]** The beat sweep (`scheduler.py`) selects due `autocount_http` tasks with
  the same query as `sql_db` (status `active`, `next_*_at` due); overlap guard and `skipped`
  rows behave identically. Test: one sweep with one due SQL task and one due HTTP task enqueues
  two jobs.
- **AC-08-30 [BE]** Router / schema: `EtlTaskView.sourceImpl` and `source_config` round-trip
  the HTTP shape; `update_task` for an HTTP task never calls the SQL runtime (no engine is
  created; asserted with a spy). `repush_task` (sprint-5/07) works unchanged for HTTP tasks.

## Group E - brand entity and Sorento push (`[BE]`)

- **AC-08-31 [BE]** `ENTITY_BRAND = "brand"`, `CanonicalBrand(CanonicalMaster)` with
  `description: Optional[str]` (<= 255), `SINK_FIELDS = (source_ref, source_doc_no, code,
  name, description, is_active)`; validation `code <= 50` and `name <= 150` (Sorento's DB
  limits, 422 at mapping time naming the field and the limit). Registered in `ENTITY_PROFILES`,
  `HTTP_ENTITY_TYPES`, `AC_SQL_DB_ENTITY_TYPES` (a DB task can feed it too:
  `SELECT ItemBrand, Description ... FROM ItemBrand`), terminology label "Brand".
- **AC-08-32 [BE]** `sinks_sorento._ENTITY_PATH["brand"] = "brands"`; push ordering /
  `_DEPENDENT_ENTITIES` treat `product.brand_code` as a dependency like `category_code`
  (`retryable` on a product for an unknown brand is expected, not a defect). The logging sink
  handles `brand` with no change.
- **AC-08-33 [BE]** `sorento_supports_entity("brand")` is gated on the consumer contract
  version (`>= 2.3`, read from `GET /api/v1/external/contract` as sprint-5/06 reads 2.2): on
  a 2.2 consumer a brand task stages and logs (logging-sink fallback) with the Review & Activate
  banner "Consumer contract 2.2 - brands land when 2.3 is deployed"; never a 422 from Sorento.
- **AC-08-34 [T]** Appendix A of the plan (Sorento contract 2.3: `brands` ingest entity,
  read-back, deletions, permission grant check) is delivered to the Sorento owner session and
  acknowledged; the acknowledgement (session name + date) is recorded in the test report.
- **AC-08-35 [BE]** Sorento rate limit: `SorentoSink` already honours 429 + `Retry-After`;
  test that a 429 mid-batch on `brands` sleeps `Retry-After` (capped 60 s) once and retries
  the same batch, and that the run reports the pause in activity.

## Group F - end to end, live, docs (`[E2E]` / `[T]`)

- **AC-08-36 [E2E]** Sorento company (DB company, existing SQL SO/PO/SPO tasks untouched):
  Add entity "Product category" -> Source tab opens on Database -> toggle API -> connection
  picker lists the Sorento no-auth connection (`.../api/db1`, badge "No auth") -> Test ->
  Save -> Activate -> Run now -> Runs tab shows requests = 1, rows ~60, added N. Then Add
  entity "Product" the same way -> Test shows "12 pages of 1000" -> Run now -> Runs tab shows
  requests = 12, rows scanned 11,826 -> Review shows staged records with refs `AED_SORENTO:<ItemGroup>`. Then the
  SQL PO task's Runs tab still shows its own last run unchanged. 375 + 1280, evidence
  `08-evidence/sorento-mixed/`.
- **AC-08-37 [T]** Live replay on the lane DB against `https://hapi.sorento.cc.cd/api/db2`
  (Mocha): product (paged, all pages), customer (paged), warehouse, product_category, brand,
  unit_of_measure - each task Test -> Activate -> Run now with the LOGGING sink (no Sorento
  push from the lane): run rows record request counts, rows scanned = `TotalCount`, zero
  duplicates, and a second identical run reports 0 added / 0 updated / 0 deleted. Then flip
  one item's compared field in a recorded stub and prove 1 updated. Report cites job ids.
- **AC-08-38 [T]** Failure replay: a stub returning 500 on page 3 -> run failed, `ac_row_hash`
  count unchanged, watermark unchanged, Runs tab shows the error code and page number.
- **AC-08-39 [T]** Ref-parity proof: on a DB company whose product task ran via `sql_db`
  (lane fixture, 20 rows), switch the same task to `autocount_http` against a recorded stub of
  the same 20 items -> reconcile reports 0 added, 0 deleted, N updated (hash change only).
- **AC-08-40 [T]** Test Execution Report keyed AC-08-01..40; pytest autocount + module suites
  green on Postgres; vitest green; lint + prod build clean; `documentation/engineering/
  process-lessons.md` (AutoCount section) gains the `autocount_http` row (source impl table, preset table,
  run-mode table, the `pageSize` clamp gotcha); backlog rows for the deferrals in plan §6.
