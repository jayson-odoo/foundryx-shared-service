# 10 - AutoCount human-invoked pull (list price, stock balance, snapshot gateway) - User Acceptance Criteria

Plan: `10-autocount-pull-review.md`. Lane `sprint-5/10-autocount-pull-review`
(worktree `.claude/worktrees/s40`, off `origin/main` c1c5906a, module 0.10.0, module Alembic
head `0019_autocount_so_ref`). Lane ports backend :8009 / frontend :3009, DB
`foundryx_service_s40`.

Owner intent (grill 2026-09-19): item master and stock balance are uploaded into Sorento BY
HAND today (Excel). The owner does not want auto-push for them yet. Wanted flow: a Sorento
user presses a button, Sorento pulls from Foundryx (sourced from the AutoCount hapi wrapper),
reviews the result against the manual upload (with an optional xlsx download), and Confirms.
After a few days of human-checked runs each entity flips to auto-push independently. SO / PO /
SPO stay on push, unchanged. Both company books are in scope from day one: `db1` (Sorento) and
`db2` (Mocha), activated per company.

## Owner rulings (locked)

- **R1** - product review and apply in Sorento go through the INGEST path (`dry_run` diff, then
  the same ingest service on Confirm), not the Excel bulk-import path. Sorento offers an xlsx
  download in the manual template shape.
- **R2** - `list_price` 0.0 is sent as a REAL `0` (AutoCount parity, matching the manual Excel
  behaviour). No omit-on-zero.
- **R3** - Stock Confirm in Sorento generates an xlsx from the pulled rows and archives it as the
  "Stock List" attachment (Sorento-side work; recorded here for the contract only).
- **R4** - both books (`db1` Sorento, `db2` Mocha) are in scope, activated per company.
- **R5 (2026-09-19, from live data)** - a NEGATIVE list price is CLAMPED TO 0, parity with the
  manual Excel upload. It is an explicit, operator-visible step (the mapping row's formula), never
  a silent coercion inside the canonical model, and it applies on the PUSH path too the moment S1
  ships, because push and pull share one mapper.
- **R6 (2026-09-19, from live data)** - a per-record mapping / validation failure does NOT fail a
  snapshot. The record is EXCLUDED (listed in `excludedRows`, counted in `excludedCount`) and the
  snapshot still reaches `ready`. Snapshot-level failure remains for source page failure, enrich
  endpoint failure, row cap and empty extract ONLY. Products: exclusions never block Confirm (the
  upsert is non-destructive) and Sorento lists them on the review page. Stock: unchanged strict
  rule - Sorento refuses Confirm while any excluded row has `qty != 0`.

- **R7 (2026-09-19, from the peer's macro-workbook measurement)** - **Foundryx delivers EVERY
  positive (item, location) pair; there is NO location allow-list on this side.** The manual
  macro workbook was proven to be `Master` (11,205 raw rows) filtered by an `Active Loc` sheet
  (60 locations) AND `On Hand Qty > 0`, giving exactly its 6,591 `Template` rows - a LOCATION
  filter, never an item filter. Sorento's `warehouses.is_active` already mirrors `Active Loc`
  almost row for row (6,502 live positive pairs in Sorento-active warehouses vs 6,476 in prod),
  so the filter belongs on the consumer side where the active flag actually lives. AutoCount's own
  `IsActive` is a DIFFERENT list and cannot stand in for it. Sorento therefore applies only rows
  whose warehouse is ACTIVE in Sorento and lists inactive / unknown-location rows on its review
  page as "not applied" with counts. No contract change; the stock slice is not gated.

- **R8 (2026-09-19, locked): CODE WINS for product identity.** Foundryx keys EVERY product
  `<refPrefix>:<ItemCode>` on BOTH books, from the HTTP source, using `PRODUCT_HTTP_PRESET` as it
  stands - no DB-source variant, no `AutoKey`/`DocKey` scheme. The 9,067 live
  `AED_SORENTO:<numeric>` product refs were minted by SO/PO LINE ingest (the document resolver
  links a line's `product_ref` when the `product_code` rung hits), never by a product master push
  - the Foundryx `SRT` Product task has never run. Sorento's `integration_references` is UNIQUE on
  `(entity_type, entity_id)`, so alias refs are impossible; instead Sorento changes
  `MasterIngestService` for `products` ONLY: a ref miss whose `code` matches a product already
  linked under the SAME source system and company UPDATES that product, KEEPS the existing ref
  untouched, does not link the new one, and attaches a `ref_mismatch` warning (`dry_run` reports
  `updated` + diff + warning). `ReferenceConflict` stays for every other entity and source system.
  This is the rule their document-line resolver already applies. **Sorento contract 2.4** carries
  it (plus optional `codes` on product deletions); the future `stock_balances` ingest entity moves
  to **2.5**.

- **R9 (2026-09-19, locked): lookups are a GENERAL, operator-configurable feature of any API
  task**, not a preset-only block for one field. An operator adds N lookups on the task's Source
  tab; the product preset merely ships PRE-FILLED with the ItemUOM one, as an ordinary editable
  row. BL-SS-208 is pulled into scope by this ruling.

- **R10 (2026-09-20, locked): manual-upload parity is a GATE, not a claim.** A pulled product
  must land in Sorento byte-identical to what the manual Excel upload would have produced for the
  same AutoCount row. R1 (apply through the ingest path) STANDS - the peer's code-level matrix
  shows both paths already share `is_discontinued` (explicit flag wins, else
  `description.lstrip().startswith("****")`) and `parse_dimensions` (L/W/H parsed out of the
  DESCRIPTION text), so parity is won by sending the right `description`, not by a second code
  path. What changes on this side: the description join (AC-10-73), `uom_code` withheld during
  the check period (AC-10-74), and a joint parity test plus a fixture that carries the awkward
  rows (AC-10-67, plan Appendix A10).

- **R11 (2026-09-20, locked): row combining is GENERAL and operator-configurable**, not a named
  code-side reducer. Any API task may carry ONE bounded "Combine rows" step that runs after
  Lookups and before mapping: computed columns, require rules, group-by with measures and carried
  columns, per-measure rounding, and ordered drop rules. The stock preset ships PRE-FILLED with
  the whole configuration, so the owner configures nothing, but every part is an ordinary editable
  row. BL-SS-209 is pulled into scope. The Sorento wire contract does NOT change: the agreed stock
  header names are serialised FROM the generic metadata by the entity profile (AC-10-81).

Consumer: Sorento CRM contract 2.3. Facts from the Sorento peer session 2026-09-19: Sorento has
NO stock-balance ingest entity (stock applies through their existing `bulk_import_stock` during
the check period; a `stock_balances` ingest entity is contract 2.4 and is NOT built here); their
stock import ZEROES every (product, active warehouse) pair absent from the file, clamps `<= 0`
to 0 and applies `int()`; product review/apply goes through the INGEST path (`dry_run` diff,
then the same `MasterIngestService` on Confirm), never their Excel bulk-import path; their
product matching is case-insensitive but does NOT trim.

Live wrapper facts (probed 2026-09-19, `https://hapi.sorento.cc.cd/api/db1`, read-only):
`/itemuombypage` rows `{ItemCode, UOM, Rate, Price}`, 11,852 rows for 11,840 items, every item
has a row whose `UOM` equals its `BaseUOM`, 11 multi-UOM items, some junk rows with `UOM: ""`,
every `Rate` is 1.0, zero duplicate `(ItemCode, UOM)`, no timestamps. `/itembatchbalqtybypage`
rows `{ItemCode, UOM, Location, BatchNo, BalQty}`, 68,612 rows over 69 pages, 56,433 zero /
44 negative / 12,135 positive, `BatchNo` empty on every row, 27 non-base-UOM rows (4 of them
nonzero), 5 rows whose `(ItemCode, UOM)` has no `ItemUOM` rate (casing dirt, all zero qty), one
item whose `BaseUOM` is `''`. Aggregated to (item, location): 68,597 pairs, 12,175 nonzero,
42 negative, 0 fractional. 147 distinct balance locations, all present in `/location` (154 rows,
carrying `IsActive` T/F). Live dirt to handle: a location code `'MBS '` with a trailing space,
and a UOM `'unit'` where the item's `BaseUOM` is `'UNIT'`. 5,008 of 11,840 db1 items carry
`Price` 0.0.

Live findings from the plan review (2026-09-19, db1), which R5 and R6 answer: **121 ACTIVE items
carry a base-UOM `ItemUOM` `Price` of `-1.0`** (a vendor sentinel, not a price) and
`CanonicalProduct.list_price` is `ge=0`, so without R5 every db1 product extract would reject 121
records; **10 ACTIVE items have an empty `Description`**, which maps to the required `name`;
**20 `ItemCode`s carry leading or trailing whitespace**; **1 item has `BaseUOM` `''`**.

Measured wrapper performance (2026-09-19/20 night, the night's ops finding): on **db2 (Mocha)**
`/itembypage` at `pageSize=1000` returned a Cloudflare **524 after about 125 s on 9 of 9 attempts**
for pages 1-3, while page 4 (445 rows) answered 200 in 66 s; `pageSize=100` took 22 s and
`pageSize=300` took 65 s. That is roughly **0.2 s PER ROW on db2**, with Cloudflare cutting any
request past about 100 s - so the largest safe db2 page is about **400 rows**. db1 the same night
answered `pageSize=1000` in 21 s. Plan 08's live db2 smoke on 2026-09-12 walked 3,438 products in
4 pages of 1000, so this is either new or intermittent - unknown. Against today's client (ONE
30 s attempt per page, no retry) every db2 page over roughly 130 rows would have failed.

Tags: `[BE]` backend pytest, `[FE]` frontend vitest, `[E2E]` recorded agent-browser run,
`[T]` tester-owned proof (mutation / live replay / docs).

## Definitions

- **delivery mode** - a per (company, entity) choice on `ac_entity_config.delivery_mode`:
  `push` (today's behaviour: an activated task delivers to the company's sink on its schedule)
  or `pull` (the task never pushes and never runs on the sweep; a consumer request builds a
  snapshot on demand). Every existing task is `push`.
- **snapshot** - one immutable extraction of ONE (company, entity) at one instant, held under a
  `snapshot_id`, TTL 24 hours, served by page. Never mutated after it reaches `ready`.
- **excluded row** - a record the extraction READ but could not deliver, reported in the
  snapshot header's `excludedRows` with a `reason` and counted in `excludedCount`. It never fails
  the snapshot (R6). Shape is per entity: a product exclusion is
  `{source_ref, code, reason, message}`, a stock exclusion is
  `{item_code, location_code, uom, qty, reason}`.
- **clamp** - the explicit `list_price` floor at 0 (R5), expressed as the preset mapping row's
  FORMULA so it is visible and editable in the Mapping tab, never a model-level coercion.
- **trimmed key view** - `str(value).strip()` (+ casefold for a `casefold_trim` join pair) applied
  by the HTTP source to every lookup join key, used ONLY for the enrich index and its lookups and
  for the stock reducer's group key. NEVER written back onto the row - identity (`flat_source_ref`,
  `code`) is already trimmed via `t_string`, so `row_hash` stays byte-identical and this plan causes
  no one-time re-push wave (AC-10-60).
- **complete** - `true` only when the extraction walked the FULL company set: for a paged
  endpoint, raw scanned rows == the wrapper's echoed `TotalCount`; for a bare-array endpoint,
  always true (one request). It says nothing about data quality.
- **lookup** (config key `lookups`, R9) - an operator-authored cross-endpoint join on an API
  task: one extra endpoint walked once per run, indexed by named join keys, projecting named
  remote fields onto every source row under an operator-chosen alias, BEFORE de-duplication,
  hashing and mapping. Lookups are ORDERED and a later one may join on an earlier one's alias.
  "Enrich" is the same thing in the internal/wire vocabulary and survives in two already-agreed
  contract names (`enrichMissCount`, `ENRICH_FAILED`).
- **combine** (config key `combine`, R11) - one bounded, operator-configurable step on an API
  task that turns many source rows into fewer: computed columns, require rules (a falsy one
  EXCLUDES the row), group-by with measures and carried columns, per-measure rounding, and ordered
  drop rules. Runs after every lookup and before mapping; its group-by columns become the task's
  key fields.
- **pull-only entity** - an entity with no consumer ingest path at all (`stock_balance` today).
  Its delivery mode is `pull`, immutably.
- **pull gateway** - the public API-key routes under `/api/v1/autocount/*` that a consumer calls
  server-side. Tenancy is derived from the key, never from the request.
- **company code** - `ac_company.sorento_company_code`, the SAME string this module already
  sends as the top-level `companyCode` on every Sorento ingest / read / delete call
  (`sinks_sorento.SorentoSink._body`). It is NOT `ac_company.database_name` (that is the
  reference prefix that qualifies `source_ref`).
- **wire casing** - the pull gateway uses camelCase ENVELOPE / metadata keys (matching the
  existing `companyCode` body key this module already sends) and snake_case ROW keys (matching
  `CanonicalProduct.sink_payload()` byte for byte). Stated once here and once in plan Appendix A.

## Group A - list price by enrichment (`[BE]` / `[FE]`)

- **AC-10-01 [BE]** An HTTP task's `source_config` accepts an optional ORDERED `lookups` list
  (R9), operator-authored, any number of entries. Each entry is
  `{path, as, on: [{local, remote, match?}], fields: [{remote, as}]}` on the task's OWN
  connection. `path` passes the SAME `validate_http_path` rule (`http_source/preview.py:30-46`:
  must start with `/`, no `..`, no query string, <= 200 chars) the task path and the preview route
  already use - the lookup editor can never reach an endpoint the main path could not. `as` and
  every `fields[].as` match `^[A-Za-z][A-Za-z0-9_]{0,40}$`; `match` is `exact` (default) or
  `casefold_trim`. 422 naming `lookups[i].<field>` for: a duplicate alias, an alias colliding with
  a source column or with an earlier lookup's alias, an empty `on`, an empty `fields`, a `local`
  column that is neither a source column nor an alias produced by an EARLIER lookup, or more than
  `MAX_LOOKUPS` (5) entries.
- **AC-10-02 [BE]** `HttpApiSource` walks each lookup endpoint ONCE per run with the same page
  walker (echoed `Page`/`TotalPages` trusted, non-advancing page guarded, row cap shared),
  builds an in-memory index on the join keys, and merges the projected fields onto every source
  row under their aliases BEFORE `_dedupe`, `row_hash` and mapping. A row with no match simply
  does not gain the alias keys (they are ABSENT, never `None`) - the miss behaviour is FIXED and
  documented, never an operator choice. **Multi-hop by ordered evaluation:** lookups are applied
  in list order and each may join on any column the row carries by then, including an alias from
  an earlier lookup - which is exactly how stock chains balance row -> item `BaseUOM` -> ItemUOM
  `Rate`. Forward references are the 422 in AC-10-01, so the order in the editor IS the
  evaluation order and no cycle is representable.
- **AC-10-03 [BE]** An enrich MISS is counted, never fatal: the run records ONE warning activity
  and one `record_note` naming the entity, the enrich alias and the miss count; the run
  succeeds. An enrich endpoint transport / status / shape / cap failure FAILS the run through
  the same `HttpSourceError` path as a source page failure - nothing staged, no hash written, no
  watermark advanced, no delete intent computed.
- **AC-10-04 [BE]** The product HTTP preset ships PRE-FILLED with one ordinary, fully editable
  lookup (R9 - zero configuration for the owner's case, no special casing in the engine). It gains
  `enrich: [{path: "/itemuombypage", as: "uom", on: [{local: "ItemCode", remote: "ItemCode"},
  {local: "BaseUOM", remote: "UOM", match: "casefold_trim"}], fields: [{remote: "Price", as:
  "BaseUOMPrice"}]}]` and a mapping row `BaseUOMPrice -> list_price` carrying the CLAMP formula
  (AC-10-59), not required. A first clean save of a product HTTP task seeds both, through the
  existing seed-if-absent contract.
- **AC-10-05 [BE]** `POST /autocount/http/preview` accepts the task's `lookups`, applies them in
  order over the sampled page, and returns the alias columns alongside the source columns plus a
  per-lookup `{alias, matched, missed}` count - so the task's `resultColumns` AS SERVED (stored
  raw columns plus the configured lookups' own aliases, review round 1b) contain `BaseUOMPrice`
  and any operator alias for the Mapping tab's source picker, the key / watermark / compared
  pickers and the default `comparedFields`. The STORED `result_columns` itself holds the RAW
  main-endpoint columns only (never a merged alias) - so AC-10-01's save-time collision check
  (an alias colliding with a source column) is always exact, with no carve-out. A companion
  `POST /autocount/http/preview-columns {connectionId, path}` returns just the first page's
  column names, so the lookup editor offers REAL remote columns to pick from rather than free
  text. A preview whose lookup endpoint fails is a 422 naming `lookups[i].path` with the endpoint,
  never a silent drop of the alias columns.
- **AC-10-06 [BE]** An enriched value participates in change detection: with `comparedFields`
  left at its default (every result column minus the key fields), a run in which ONLY
  `/itemuombypage` `Price` changed for one item reports `updated_count == 1` and stages that one
  product. Pinned by a stubbed two-run test.
- **AC-10-07 [BE]** `list_price` 0.0 is delivered as a REAL `0` (AutoCount parity, owner ruling
  R2): `CanonicalProduct.sink_payload()` keeps falsy non-`None` values, so a product whose
  `BaseUOMPrice` is `0`, `0.0` or `"0"` delivers a zero rather than omitting the key. **Verified
  wire form:** `sink_payload()` is `model_dump(mode="json")`, which renders a `Decimal` as a JSON
  STRING (pydantic 2.13.4 in this repo: `Decimal("0") -> "0"`, `0.0 -> "0.0"`,
  `Decimal("12.50") -> "12.50"`), so the key crosses the wire as `"list_price": "0"` / `"0.0"` on
  BOTH the push path and in a pull snapshot row - unchanged from how every other Decimal this
  module sends already behaves. A product with NO enrich match omits the key entirely. All pinned.
  A NEGATIVE source price is a separate rule (R5, AC-10-59) and also lands as a zero.
- **AC-10-08 [BE]** `http_source/client.py` sends an explicit, honest `User-Agent`
  (`Foundryx-AutoCount-ESB/<module version>`) on every request alongside `Accept: application/
  json`. Pinned by a transport test asserting the header (Cloudflare 403s the default
  python-urllib UA; the default httpx UA is not something to depend on).
- **AC-10-09 [FE]** The Source tab's API branch gains a **Lookups** section (R9) below the path
  input and above the key / watermark / compared pickers, built from the shell primitives already
  in that file (`source-tab.tsx` imports `SearchSelect`, `ColumnPickers`, `ColumnChips`,
  `SqlPreviewGrid` and `DeferredActionButton` today - no new primitive). Each lookup row: endpoint
  path input (same validation message as the main path), a Test that probes its first page, join
  pairs as TWO `SearchSelect`s (local = the main path's previewed columns plus every earlier
  lookup's aliases; remote = the lookup's own probed columns) with a match-mode `SearchSelect`
  (`Exact` | `Ignore case and spaces`), and field rows (remote column `SearchSelect` -> alias
  input). Add / remove / reorder; order is evaluation order and the UI says so by numbering the
  rows, not by hint copy. Every dropdown is searchable, nothing is free text except the path and
  the alias, and an alias that collides shows the inline 422. The combined Test shows per-lookup
  matched / missed counts and the aliased columns in the preview grid. The Mapping tab needs no
  change: an alias is an ordinary source column in its picker.
- **AC-10-09b [E2E]** Operator adds a lookup by real clicks at 375 AND 1280, evidence
  `10-evidence/lookups/`: AutoCount -> Companies -> the `db1` company -> Product entity -> Source
  tab -> the pre-filled ItemUOM lookup is visible -> Add lookup -> path `/itemuombypage` -> Test
  -> pick join `ItemCode` <-> `ItemCode` and `BaseUOM` <-> `UOM` (Ignore case and spaces) -> bring
  in `Rate` as `BaseUOMRate` -> Test shows matched / missed -> Save -> the Mapping tab's source
  picker offers `BaseUOMRate`.

- **AC-10-59 [BE]** **Negative list price is clamped to 0 (R5), visibly.** The product preset's
  `BaseUOMPrice -> list_price` row carries the FORMULA
  `if(number(value) <= 0, 0, number(value))` (every token exists in the formula engine today:
  `if`, `number` and `<=` are in `FUNCTION_CATALOG` / `OPERATOR_CATALOG`), so the clamp is an
  ordinary, editable, testable mapping row in the Mapping tab and its formula builder - never a
  coercion hidden in `CanonicalProduct`. `list_price` keeps its `ge=0` bound as the backstop.
  `<= 0` rather than `< 0` deliberately: `-0.0` passes `ge=0` and would otherwise be delivered as
  the string `"-0.0"` (verified). Because push and pull share ONE mapper, the clamp applies on the
  PUSH path from S1 onward. Pinned on the DELIVERED wire value: source `-1.0` -> `"0.0"`; source
  `-0.0` -> `"0.0"`; source `0.0` -> `"0.0"`; source `12.5` -> `"12.5"`; absent -> key omitted.
- **AC-10-60 [BE]** **One trim rule, and it is smaller than it looked.** Verified in code:
  `mapping.flat_source_ref` builds every key part through `t_string` (`str(value).strip()`), and
  every `string`-transform mapping row does the same - so `source_ref` AND the canonical `code`
  are ALREADY trimmed today, for the 20 whitespace `ItemCode`s as much as for any other. Nothing
  about identity changes in this plan. What is NOT trimmed today is the raw dict lookup, so the
  rule is scoped to exactly that: the HTTP source computes a trimmed LOOKUP KEY (never written
  back onto the row) for the enrich index and its lookups, and the stock reducer groups on trimmed
  `(ItemCode, Location)`. Not writing back is deliberate - it keeps `row_hash` byte-identical, so
  this plan causes no one-time re-push wave. Tests: (a) an item `"SRT-01 "` gains its enrich
  price; (b) its `source_ref` is `AED_SORENTO:...` identically before and after; (c) its
  `row_hash` is unchanged; (d) the reducer folds `'MBS '` and `'MBS'` into one pair.
- **AC-10-61 [FE]** The Mapping tab shows the clamp as what it is: the `list_price` row's preset
  reads `Custom` with the formula visible in the existing formula builder, and the mapping
  simulator evaluates it (`-1` -> `0`). No banner, no explanatory copy - the row IS the
  explanation.

## Group B - delivery mode (`[BE]` / `[FE]`)

- **AC-10-10 [BE]** `ac_entity_config.delivery_mode` is `String NOT NULL default 'push'` with a
  `server_default` of `'push'`. Module Alembic `0020_autocount_pull_snapshot` adds it; a
  `create_all`-first host is covered by a `backfill_delivery_mode_defaults` sweep called from
  `update_tenant` (idempotent, mirrors `backfill_sink_impl_defaults`). Every task that existed
  before this plan reads `push` and behaves exactly as it does today.
- **AC-10-11 [BE]** `PUT /autocount/companies/{id}/entities/{entityType}/delivery-mode
  {deliveryMode}` (perm `autocount.companies.manage`, tenant- and company-scoped) sets the mode.
  `pull` requires the company to carry a `sorento_company_code` (422 `deliveryMode` naming the
  missing company code) and requires the entity to be in the pull-capable set
  (`product`, `stock_balance` in this plan; 422 naming the entity otherwise). The switch does
  NOT touch `source_config`, mapping rows, `result_columns` or `ac_row_hash`.
- **AC-10-12 [BE]** A `pull` task never auto-pushes: the auto-push branch in `sync.py` (both the
  plain and the paged path) is additionally gated on `delivery_mode == 'push'`. Mutation test:
  an ACTIVE `autocount_http` product task in `pull` mode, run with a stub source, calls
  `SyncService.auto_push` ZERO times (spy) and leaves `ac_staged_record` empty.
- **AC-10-13 [BE]** A `pull` task never runs on the 60 s sweep: `scheduler.sweep_etl_tasks`'s due
  query filters `delivery_mode == 'push'`; `activate_task` on a `pull` task arms NO schedule
  (`next_incremental_at` and `next_reconcile_at` both NULL) and switching an active task to
  `pull` clears both immediately. Test: one due `push` task and one `pull` task whose due times
  are in the past -> the sweep fires exactly one job.
- **AC-10-14 [BE]** Flipping `pull -> push` on an ACTIVE task re-arms the schedule from the
  SAVED `source_config` through the existing `next_run_times`, with no re-mapping, no re-Test
  and no status change; the next sweep tick picks it up. Flipping `push -> pull` disarms it.
  Round-trip test proves the mapping rows and `result_columns` are byte-identical afterwards.
- **AC-10-15 [BE]** `stock_balance` is pull-only **for now, by the same contract gate as
  products - not by a hardcoded forever rule**: `set_delivery_mode(entity='stock_balance',
  deliveryMode='push')` is refused while the consumer's contract is below
  `STOCK_BALANCES_CONTRACT_VERSION = 2.5` or `stock_balances` is absent from its `entities` list
  (the SAME `fetch_contract_detail` -> `sorento_supports_entity` probe AC-10-69 generalises), with
  a 422 naming the entity and the version. Its tasks are created in `pull` mode. The Push segment
  is HIDDEN, not disabled, while the gate is shut (only offer valid options) and appears with no
  code change once Sorento serves 2.5 - that flip is the planned S7 follow-up (BL-SS-207), out of
  THIS plan's Definition of Done.
- **AC-10-16 [FE]** The task editor's Schedule tab opens with a two-segment `ToggleGroup`
  "Push" | "Pull on request". Choosing Pull HIDES the incremental / reconcile cadence controls
  entirely (they do not apply) while keeping their saved values; choosing Push restores them
  unchanged. While an entity's push gate is shut (AC-10-15) no toggle renders at all - a read-only
  `StatusBadge` "Pull on request" does, and the toggle appears on its own once the consumer
  supports the entity. Dirty guard is the shell's AlertDialog.
- **AC-10-17 [FE]** The Review & Activate tab's banner states what Activate means for the
  selected mode: in Push mode today's copy, in Pull mode "Activating lets the consumer request
  this extract." The entities list gains a Delivery column (`StatusBadge`: Push / Pull on
  request). No hint or how-to copy anywhere.

## Group C - snapshot store and build job (`[BE]`)

- **AC-10-18 [BE]** Module Alembic `0020_autocount_pull_snapshot` (down `0019_autocount_so_ref`,
  id <= 32 chars, no collision with any existing id) creates `ac_pull_snapshot` and
  `ac_pull_snapshot_row` in `app_autocount`, both carrying `tenant_id` AND `company_id`, all
  datetimes `UTCDateTime`, all JSON columns `JSON(none_as_null=True)`. `ac_pull_snapshot`:
  `id, tenant_id, company_id, entity_type, company_code, status, job_id, record_count, complete,
  content_hash, metadata_json, error, error_code, requested_via, requested_by, created_at,
  extracted_at, expires_at`. `ac_pull_snapshot_row`: `(tenant_id, snapshot_id, row_index)` primary
  key plus `company_id, source_ref, payload_json`.
- **AC-10-19 [BE]** `status` is `building | ready | failed`. Expiry is DERIVED from `expires_at`,
  never a stored status. A snapshot that reaches `ready` is immutable: the repository exposes no
  row update or delete-row method at all, and `SnapshotService` refuses (raises) any write
  against a snapshot whose status is not `building`. Mutation test: attempting a second row
  insert on a `ready` snapshot raises and writes nothing.
- **AC-10-20 [BE]** A build is a background job (`autocount_pull_snapshot`, registered through
  `register_job_handler` like `autocount_sync`, handler imported in the Celery worker path too).
  It: creates the `building` row, builds the source through the SAME registry factory with
  `mode=reconcile`, `persist_hashes=False`, applies enrich and (when the preset names one) the
  reduce step, maps each record through the SAME `mapping.map_document` the push path uses,
  inserts rows in a deterministic order, then stamps `record_count`, `complete`, `content_hash`,
  `extracted_at`, `expires_at` and `status='ready'` in ONE commit.
- **AC-10-21 [BE]** A pull run writes NO `ac_staged_record` rows, advances NO watermark and
  writes NO `ac_row_hash` rows; it records ONE `ac_sync_run` row with `mode='snapshot'` carrying
  `rows_scanned`, `added_count = record_count`, the request count and the outcome, so the Runs
  tab shows a pull build exactly as it shows a push run.
- **AC-10-22 [BE]** Snapshot-level failure is reserved for faults that make the SET untrustworthy
  (R6): a source page failure, an enrich endpoint failure, a row-cap breach, or an empty extract
  against a previously non-empty one. Each leaves the snapshot `failed` with its `error_code`
  (`SOURCE_PAGE_FAILED` / `ENRICH_FAILED` / `ROW_LIMIT` / `EMPTY_EXTRACT`), ZERO readable rows and
  no partial page served. A per-record mapping or validation failure is NOT one of them - it is an
  excluded row (AC-10-62). Test: a stub that 500s on page 3 of 5 produces `status='failed'` with
  zero rows readable through the gateway, while a stub whose page 2 carries one unmappable record
  produces `status='ready'` with that record in `excludedRows`.
- **AC-10-23 [BE]** `content_hash` is `sha256` over the concatenation, in `row_index` order, of
  `json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"` for EXACTLY the stored
  `payload_json` that is later served - never a re-projection. Because `sink_payload()` has
  already run `model_dump(mode="json")`, every stored value is a JSON primitive (string, int,
  bool, null) with no `Decimal` left to serialize ambiguously, so a consumer re-dump of the
  assembled pages reproduces the bytes. Pinned by a fixed-fixture test. It is a best-effort
  integrity check, not an authorization or completeness guard - `recordCount`, `complete` and the
  `companyCode` echo are those (Appendix A5).
- **AC-10-24 [BE]** `complete` is computed per the definition above (raw scanned rows ==
  echoed `TotalCount` for a paged endpoint, `true` for a bare array). A stubbed walk that returns
  999 rows against `TotalCount: 1000` yields a `ready` snapshot with `complete = false` and the
  real counts - never a failed run and never a silent `true`.
- **AC-10-25 [BE]** TTL and retention: `expires_at = extracted_at + autocount_pull_snapshot_ttl_
  hours` (setting, default 24). A new Celery beat task `autocount.prune_pull_snapshots` (hourly,
  registered beside `autocount.etl_sweep` in `app/workflow_engine/worker.py`) deletes expired
  snapshots and their rows in bounded batches, and also drops all but the newest 3 `ready`
  snapshots per (tenant, company, entity). Test: an expired snapshot and a 4th-newest ready
  snapshot are both removed with their rows; a `building` snapshot younger than the orphan
  window is untouched.
- **AC-10-26 [BE]** At most ONE `building` snapshot exists per (tenant, company, entity): a
  second build request returns the EXISTING building snapshot's id rather than starting a second
  extraction. That re-attach has NO time limit while the build is ALIVE: a consumer that
  stopped polling at 60 minutes and clicks again re-attaches to the same `snapshotId` and never
  starts a second extraction (AC-10-88). A build request less than 60 s after the previous build
  for the same triple is refused with 429 and `Retry-After`. A `building` snapshot whose job has NOT HEART-BEATEN for
  `background_job_orphan_after_minutes` (config default 15, floor 5) is failed by the module's
  existing `on_job_orphaned` hook (extended to this job type) so it never blocks forever. The
  sweep is liveness-based, not age-based, so a legitimately long build (AC-10-86: a Mocha product
  snapshot is roughly 25 minutes) is safe PROVIDED the handler beats per page - it registers with
  `heartbeats=True` exactly as `autocount_sync` does, and the per-request timeout cap of 100 s
  (AC-10-85) sits far inside the orphan window by construction.

- **AC-10-62 [BE]** **Per-record exclusion (R6).** A record that fails mapping or canonical
  validation is written to the snapshot's `metadata_json.excludedRows` as
  `{source_ref, code, reason, message}` with `reason = "mapping_failed"` (or the specific
  validation reason), is counted in `excludedCount`, and is NOT written as a snapshot row. The
  snapshot still reaches `ready`, `complete` is unaffected, and `record_count` counts the
  DELIVERED rows only. `excludedRows` is UNCAPPED today; if a cap is ever introduced the header
  sets `truncated: true` and the COUNTS stay authoritative (AC-10-66). Test with the live-shaped
  case: a product whose `Description` is empty (required
  `name`) is excluded, the other 19 of 20 fixture records are served, and the snapshot is `ready`.
- **AC-10-63 [BE]** Product header counters, defined so they can never be double-read:
  `zeroListPriceCount` counts rows whose DELIVERED `list_price` is `0` (post-clamp, so it
  INCLUDES every clamped negative); `negativeListPriceCount` counts rows whose SOURCE price was
  below 0 and were clamped; `enrichMissCount` counts rows that got no enrich match at all (their
  `list_price` key is absent). `negativeListPriceCount <= zeroListPriceCount` always. Pinned by a
  fixture of 5 rows covering zero, negative, positive, absent and non-numeric.

## Group D - pull gateway, API keys, permissions (`[BE]` / `[FE]`)

- **AC-10-27 [BE]** Module Alembic `0021_autocount_pull_gateway` (down `0020_...`) creates
  `ac_pull_api_key` (`id, tenant_id, name, key_prefix (indexed), key_hash, company_ids (JSON),
  created_by, created_at, last_used_at, revoked_at`) and `ac_pull_audit` (`id, tenant_id,
  company_id, entity_type, key_id, snapshot_id, action, page, record_count, status_code,
  created_at`). No payload, no debtor / customer / PII field is ever written to either table.
- **AC-10-28 [BE]** Key issuance mirrors the omnichannel pattern without importing it (module
  isolation): scheme `fxa_live_`, `secrets.token_urlsafe(32)`, stored as an 8-char indexed
  prefix plus a `sha256` hash, compared with `hmac.compare_digest`, plaintext returned EXACTLY
  once and never persisted or logged. `last_used_at` is stamped on every successful resolve.
- **AC-10-29 [BE]** Gateway routes are mounted as a module router with prefix
  `/api/v1/autocount` (manifest `routers` entry, mirroring omnichannel's `/api/v1/omnichannel`):
  `POST /snapshots {companyCode, entity}` -> 202 `{snapshotId, status, entity, companyCode}`;
  `GET /snapshots/{snapshotId}` -> the header; `GET /snapshots/{snapshotId}/rows?page=&pageSize=`
  -> the page. `entity` on the wire is `products` or `stock_balances`, translated by ONE map to
  the internal `product` / `stock_balance`; an unknown entity is a 422 naming the accepted set.
- **AC-10-30 [BE]** Auth and tenancy: the key is presented in `X-API-Key` (the header this
  module already uses toward Sorento). Tenant, and the allowed company id set, come from the KEY
  ROW - never from the request. `companyCode` is resolved case-insensitively and trimmed against
  `ac_company.sorento_company_code` WITHIN the key's tenant only; the resolved company id must be
  in the key's `company_ids`. No route accepts a tenant, tenant slug or company id from the
  client. Cross-tenant test: a key of tenant A naming tenant B's company code gets a uniform 404.
- **AC-10-31 [BE]** The error ladder is exact, stable-coded and distinguishable, body
  `{"code": "...", "message": "...", "companyCode": "...", "entity": "..."}`:
  - 401 `INVALID_API_KEY` - missing, malformed, unknown or revoked key (uniform, no enumeration).
  - 403 `SERVICE_NOT_ENABLED` - the `autocount` module is not active for the key's tenant, or the
    tenant is suspended / archived (same `Status.blocks_access` / `is_archived` predicate the
    sweep uses).
  - 403 `COMPANY_NOT_ALLOWED` - the company resolves in the key's tenant but is not in the key's
    company set.
  - 404 `UNKNOWN_COMPANY` - no company with that code in the key's tenant (uniform; never reveals
    another tenant's company).
  - 409 `PULL_NOT_ENABLED` - no task for that (company, entity), or its delivery mode is not
    `pull`, or its `etl_status` is not `active`.
  - 409 `PUSH_ACTIVE` - the task is ACTIVE with delivery mode `push` (the book has flipped to
    automatic).
  - 410 `SNAPSHOT_EXPIRED` - `expires_at` has passed.
  - 404 `UNKNOWN_SNAPSHOT` - unknown id, or an id belonging to another tenant / company / key
    scope (uniform).
  - 429 `TOO_MANY_BUILDS` - within the build cooldown; carries `Retry-After`.
  Each code has its own test.
- **AC-10-32 [BE]** A snapshot header answers
  `{snapshotId, entity, companyCode, status, extractedAt, expiresAt, recordCount, complete,
  contentHash, sourcePageSize}` when `ready` (`sourcePageSize` is the page size the walk actually
  used, AC-10-86 - informational, for diagnosing a slow book); `{snapshotId, entity, companyCode, status: "building", progress?}` while
  building, with no counts (AC-10-87); `{..., status: "failed", error: {code, message}}` when failed. A stock
  header additionally carries `zeroPairs, negativePairs, negativePairList[], fractionalPairs`
  and `excludedNonzeroCount` (AC-10-66); a product header additionally carries
  `zeroListPriceCount, negativeListPriceCount, enrichMissCount`. BOTH entities carry
  `excludedCount` and `excludedRows[]` (R6, AC-10-62).
  The header is the ONLY place these appear - a page repeats only
  `{snapshotId, page, pageSize, totalPages, recordCount, rows[]}`.
- **AC-10-33 [BE]** Paging is `page` (1-based) + `pageSize` (default 1000, max 1000, above max is
  clamped, not an error), ordered by `row_index`, stable across calls. A page past `totalPages`
  returns an empty `rows` array with the same header echo, never a 404. Rows are served exactly
  as stored (`payload_json`), with no re-projection at read time.
- **AC-10-34 [BE]** Every gateway call writes ONE `ac_pull_audit` row (who = key id, when,
  company, entity, snapshot, action, page, record count, status code) including the failures in
  AC-10-31, and no payload. A 401 with no resolvable key writes an audit row with a NULL key id
  and NULL tenant - or none at all if tenancy cannot be attributed; state which, once, and test
  it.
- **AC-10-35 [BE]** Throttle: a new core throttle scope `pull` (`app/services/throttle.py` +
  settings, mirroring the `embed` / `webchat` scopes) records a failure per client IP on every
  401 and enforces before key resolution; over-limit answers 429 with `Retry-After` and the
  uniform body. Successful calls never consume the bucket.
- **AC-10-36 [BE]** New permissions in `modules/autocount/permissions/permissions.csv`:
  `autocount.pull.read` and `autocount.pull.manage` (resource `autocount.pull`). Verified against
  core `app/permissions/permissions.csv` for key collisions before naming. Because existing
  tenants already have the module installed, `update_tenant` re-runs the tenant Admin grant so
  the new keys reach them (the DoD "new permission -> grant sweep" gate); a test proves an
  already-provisioned tenant's Admin holds both keys after an update.
- **AC-10-37 [BE]** Operator (authed) routes for the same data, under the existing
  `/autocount` prefix, Router -> Service -> Repository with no DB access in the router:
  `GET/POST /autocount/pull/keys`, `POST /autocount/pull/keys/{id}/revoke`
  (`autocount.pull.manage`), `GET /autocount/pull/snapshots`,
  `GET /autocount/pull/snapshots/{id}`, `GET /autocount/pull/snapshots/{id}/rows`
  (`autocount.pull.read`), and `POST /autocount/pull/snapshots` to build one as the operator
  (`autocount.pull.manage`, `requested_via='operator'`, the SAME service the gateway calls).
  Every query is tenant-scoped from the JWT.
- **AC-10-38 [FE]** `/autocount/pull` is a new page reached from the sidebar AutoCount section
  (menu entry tagged `module: 'autocount'` + `permission: 'autocount.pull.read'` in ALL THREE
  menu arrays, so `filterMenu` hides it correctly), rendered as a `ResourceList` with an N-way
  segment `Keys | Snapshots` (segment rendered as `SearchSelect` per the shell rule; selection
  clears on view switch). Keys: name, companies (`OverflowPills`), created, last used, status.
  Snapshots: entity, company, status, records, complete, built, expires, requested via. Issue
  key is a `ResourceForm` dialog (name + company `MultiSelect`); the plaintext key is shown once
  with a copy control; Revoke is the CORE deferred-action grace window registered in
  `deferred_actions.py` beside `autocount_etl_task.repush`, never a hand-rolled confirm dialog.

- **AC-10-64 [BE]** The gateway's failed-status code set is exactly `SOURCE_PAGE_FAILED`,
  `ENRICH_FAILED`, `ROW_LIMIT`, `EMPTY_EXTRACT` (R6). `MAPPING_FAILED` is NOT a snapshot status
  code and never appears in a `status: "failed"` body; `mapping_failed` exists only as an
  `excludedRows[].reason` on a `ready` snapshot. Pinned by a test asserting the code set, so the
  consumer's error switch cannot be broken by a later addition without a contract change.

## Group E - stock balance entity (`[BE]`)

- **AC-10-39 [BE]** `ENTITY_STOCK_BALANCE = "stock_balance"` and `CanonicalStockBalance` are
  declared in `canonical/masters.py` beside their siblings, registered in `ENTITY_PROFILES`,
  `ETL_ENTITY_TYPES`, `HTTP_PRESETS` / `HTTP_ENTITY_TYPES`, `mapping_catalog.SORENTO_FIELDS`
  and terminology ("Stock balance"). It has NO `sinks_sorento._ENTITY_PATH` entry, and
  constructing a `SorentoSink` for it raises the existing "no ingest path" error - the pull-only
  rule (AC-10-15) is what keeps that unreachable. Fields:
  `item_code`, `item_description`, `location_code`, `uom_code`, `qty` (int, `ge=0`).
- **AC-10-40 [BE]** The stock HTTP preset: path `/itembatchbalqtybypage`, no watermark (the
  endpoint carries no timestamp), TWO lookups - `/itembypage` on `ItemCode` projecting
  `{BaseUOM -> ItemBaseUOM, Description -> ItemDescription}`, then `/itemuombypage` on
  `(ItemCode, UOM casefold_trim)` projecting `{Rate -> UomRate}` - and a PRE-FILLED `combine`
  block (AC-10-41). Key fields are DERIVED from the combine step's group-by
  (`["ItemCode", "Location"]`, AC-10-80), not typed separately.
- **AC-10-41 [BE]** The stock preset's `combine` block is an ORDINARY, editable configuration
  (R11) that expresses exactly what the old named reducer did:
  - `computed`: `base_qty = if(lower(trim(UOM)) == lower(trim(ItemBaseUOM)), number(BalQty),
    number(BalQty) * number(UomRate))`;
  - `require`: `{name: "uom_rate", formula: "lower(trim(UOM)) == lower(trim(ItemBaseUOM)) or
    number(default(UomRate, 0)) > 0", reason: "uom_rate_unresolved"}`;
  - `measure`: `base_qty` (the designated quantity column, AC-10-77);
  - `groupBy`: `[trim(ItemCode), trim(Location)]` via computed `item_code` / `location_code`
    columns, so the trim is visible rather than implied (`'MBS '` -> `'MBS'`);
  - `measures`: `{source: base_qty, op: sum, alias: qty}`; `carry`:
    `[ItemDescription, ItemBaseUOM]`;
  - `round`: `{measure: qty, mode: half_up, dp: 0}`;
  - `drop`: `[{name: "zero", formula: "qty == 0"}, {name: "negative", formula: "qty < 0",
    listRows: true}]`.
  Every formula parses through the EXISTING hand-written engine (`parse_formula` /
  `evaluate_formula`) - never `eval`, the house anti-SSTI line. UOM comparison stays casefold +
  trim (`'unit'` matches `'UNIT'`), and the warehouse master's `Location` is trimmed by the same
  one trim rule (AC-10-60).
- **AC-10-42 [BE]** Only NONZERO POSITIVE pairs survive, and they do so through the two DROP
  RULES above, not a hardcoded rule: the `zero` rule's count surfaces as `zeroPairs`, the
  `negative` rule's count as `negativePairs` and its listed rows as `negativePairList`
  (`{item_code, location_code, qty}`) through the entity-profile map of AC-10-81; neither is
  emitted as a row. The
  positive-only cut is the ONLY cut this side makes (R7): there is no location allow-list and no
  item filter here, so the delivered set is roughly 12,133 db1 pairs over 75 locations, NOT the
  manual macro workbook's 6,591 - that number is the same data after the CONSUMER's
  active-warehouse filter (AC-10-68). Pinned by a fixture covering all three cases.
- **AC-10-43 [BE]** Quantities are INTEGER by the preset's `round` entry (`half_up`, 0 dp); any
  group whose pre-rounding value differed increments the generic `roundedCount`, which the entity
  profile serialises as `fractionalPairs` (AC-10-81), and is listed (capped at 50) in the
  metadata. The probed live set has 0 fractional pairs, so this is a visible
  guard, not a silent conversion.
- **AC-10-44 [BE]** `complete` stays TRUE when `excludedRows` is non-empty (an exclusion is a
  data problem, not a truncated walk) and so does `status = 'ready'` (R6). The STOCK-ONLY consumer
  refusal rule (Confirm blocked while any excluded row has `qty != 0`) is theirs; this side only
  reports honestly. Pinned.
- **AC-10-45 [BE]** A stock snapshot row is
  `{source_ref, item_code, item_description, location_code, uom_code, qty}` with `qty` a positive
  integer, and it always covers the FULL company set (the consumer zeroes absent pairs, so a
  truncated set is destructive). A build whose walk did not reach `TotalCount` yields
  `complete=false`, which the consumer treats as "do not Confirm". Which of those rows are
  APPLIED is the consumer's decision (R7), never a cut made here.
- **AC-10-46 [BE]** Zero-row guard: a stock or product build that produces 0 rows while the most
  recent `ready` snapshot for the same (company, entity) had a non-zero `record_count` FAILS with
  `error_code = "EMPTY_EXTRACT"` and writes no rows. A genuinely first build with 0 rows is
  allowed (nothing to contradict it).
- **AC-10-47 [BE]** Every row of every stock query, snapshot read and audit write is scoped by
  `tenant_id` AND `company_id`; no stored id (`snapshot_id`, `key_id`, `company_id`,
  `connectionId`) is ever resolved with an unscoped `get_by_id`. Pinned by a repository test per
  method and by a cross-tenant read test per gateway route.

- **AC-10-65 [BE]** Exclusion semantics differ by entity and the header says so: a PRODUCT
  snapshot's exclusions never block the consumer's Confirm (its upsert is non-destructive - the
  excluded products simply keep whatever Sorento already holds), while a STOCK snapshot's
  exclusions do (their import zeroes absent pairs, so an unresolvable row with `qty != 0` would
  silently zero real inventory). The consumer's stock guard reads ONE number,
  `excludedNonzeroCount` (AC-10-66), never a scan of the list. Both entities are reported
  identically; only the consumer's rule differs, and plan Appendix A5 states it as stock-only.
  Pinned by a test asserting a product snapshot with exclusions is `ready`, `complete: true`, and
  carries no blocking flag.

- **AC-10-66 [BE]** A STOCK header carries `excludedNonzeroCount` - the number of `excludedRows`
  entries whose DESIGNATED MEASURE (the combine step's `measure` column, AC-10-77 - never a
  hardcoded `BalQty`) is non-zero - so the consumer's Confirm guard is one integer comparison and never a
  client-side scan of a list that could be truncated. Rule, pinned for both `excludedRows` and
  `negativePairList`: they are uncapped today; should a cap ever be introduced, the header sets
  `truncated: true` and every COUNT (`excludedCount`, `excludedNonzeroCount`, `negativePairs`)
  remains the authoritative full total. Test: 3 excluded rows of which 2 carry `qty != 0` yields
  `excludedCount: 3`, `excludedNonzeroCount: 2`, `truncated` absent.

- **AC-10-68 [BE]** **No location allow-list, no active filter, no item filter in Foundryx
  (R7).** The stock preset's combine step cuts on quantity only (its two drop rules). A fixture whose locations include ones that
  are inactive in AutoCount (`PRJ-ACT`, `LOC1`, `PRJ-JW`, `BEYOND`, `SAMPLE` are the live
  stock-bearing examples) and ones absent from the consumer entirely (`BRW-VAR`) delivers every
  one of their positive pairs, and the header's `recordCount` / `zeroPairs` / `negativePairs`
  describe the FULL set. A test asserts the reducer never reads `IsActive` and holds no location
  list at all - if a filter is ever wanted it belongs on the consumer side, where the active flag
  lives.

- **AC-10-69 [BE]/[FE]** **Product contract gate (R8), built by generalising the brand gate, not
  beside it.** `CompanyService`'s existing memoised `fetch_contract_detail` ->
  `sorento_supports_entity` probe (`services/company_service.py:820-872`,
  `sinks_sorento.BRAND_REQUIRED_CONTRACT_VERSION`) becomes entity-parameterised with
  `PRODUCT_CODE_WINS_CONTRACT_VERSION = 2.4`, and the task view exposes one generic
  `contractGate {entity, version, requiredVersion}` (the existing `brandContractGate` field and
  `brandContractBanner` are folded into it, never duplicated). The rule, per company:
  - the company HAS a Sorento sink connection and the live contract is `< 2.4`: **activating a
    product task in PUSH mode is refused** (422 / Activate disabled with the banner). Pushing
    ItemCode refs at a 2.3 consumer would fail roughly 9,067 records - the foolproof-UI line, and
    unlike the brand gate there is no safe logging-sink fallback for an entity that already has
    rows on the consumer.
  - same company, PULL mode: banner only, no block. Nothing lands on the consumer until its own
    Confirm, and its review page shows the conflicts.
  - the company has NO Sorento sink connection (logging sink, pull-only): the gateway genuinely
    cannot see the consumer's contract, so the banner renders with `version: null` (the shape the
    brand gate already uses for "could not be reached") and nothing is blocked. No guessing.
  Pinned per branch, including the unreachable-consumer case.
- **AC-10-70 [BE]** **`updated` + `warnings: ["ref_mismatch"]` is SUCCESS, and needs no parser
  change.** Verified in code: `SorentoSink._result_for` (`sinks_sorento.py:1066-1128`) keys only
  on `outcome` (`_OUTCOME_DELIVERED = {"created", "updated"}`), `entity_id` and `errors`; the
  `warnings` key is not read anywhere in `sinks_sorento.py` / `sinks.py` / `sync_service.py`
  today, so an unknown extra key is already tolerated and the record already counts as delivered.
  This AC (a) pins that with a fixture record
  `{"source_ref": "AED_SORENTO:SRT-01", "outcome": "updated", "entity_id": "...",
  "diff": {"list_price": {"current": "63.00", "incoming": "0"}}, "warnings": ["ref_mismatch"]}`
  so a future parser change cannot silently turn it into a failure, and (b) adds the ONE honest
  improvement: `warnings` (a list of stable string codes, omitted when empty, already reaching us
  on `sales_orders` / `purchase_orders` records) is counted per code onto the run's activity, so
  an operator can see how many records carried `ref_mismatch`. An unknown code is informational
  and never downgrades an outcome.
- **AC-10-71 [BE]** Product refs are `<refPrefix>:<ItemCode>` on BOTH books (R8): the parity test
  pins `PRODUCT_HTTP_PRESET.key_fields == ("ItemCode",)`, that no product preset or seeded task
  keys on `AutoKey`/`DocKey`, and that a `SRT` and an `MCH` product task mint
  `AED_SORENTO:BRACD7455C` / `MCH:BRACD7455C` for the same ItemCode. No DB-source product variant
  is added by this plan.
- **AC-10-72 [BE]** **Product delete intents carry `codes` (contract 2.4).** `SorentoSink.
  delete_batch` sends `{"companyCode", "source_refs": [...], "codes": {"<ref>": "<ItemCode>"}}`
  for `products` only; `codes` is optional and omitted for every other entity. Verified: nothing
  on the delete path stores the code today (`sync._stage_deletes` writes an `AcStagedRecord` with
  `op='delete'`, a `source_ref` and no payload; `ac_row_hash` holds ref + hash), but under R8 the
  ref IS `{prefix}:{ItemCode}`, so the code is recovered from the ref by splitting once on `:` -
  no column, no migration, no backfill. Guarded: the entry is emitted ONLY when the task's
  `keyFields` is exactly `["ItemCode"]` and the suffix contains no `|` (a multi-key ref has no
  single code), and only when the contract gate reports `>= 2.4`. Outcomes are unchanged
  (`deleted` / `deactivated` / `not_found`) plus `warnings: ["ref_mismatch"]` when the code rung
  matched. Product read-back stays ref-only. Pinned by a body-shape test plus a multi-key
  negative.

- **AC-10-73 [BE]** **Description parity with the manual Excel path (R10), as a visible mapping
  formula.** Sorento's Excel path writes `description = Description + " " + Desc2` when `Desc2` is
  non-empty (a RAW f-string join, `.strip()` on the ENDS only), else `Description`; the ingest
  path writes `payload.description` when non-blank. So the product preset changes: the current
  `Desc2 -> description` row is REPLACED by a `Description -> description` row carrying
  `trim(if(default(Desc2, "") != "", concat(Description, " ", Desc2), Description))` - every token
  verified present (`trim`, `if`, `default`, `concat`, `!=` are in `FUNCTION_CATALOG` /
  `OPERATOR_CATALOG`; `concat` is `"".join(_stringify(x))` and does NOT trim its arguments).
  Verified expressible with NO engine change: `map_document` always passes
  `facts=self._header_facts(raw, lines)` for the header scope and `_header_facts` returns
  `dict(raw)` for a non-document entity, so a master formula may name `Desc2`; the save gate's
  `known_vars = frozenset(config.result_columns or []) | LINE_AGGREGATE_NAMES`
  (`services/company_service.py:1617`) accepts it once the task has previewed. **Inner whitespace
  is never collapsed** - 2,786 live `SRT` descriptions hold a double space precisely because the
  Excel path joins raw, and normalising would flip those rows back and forth between a manual
  upload and a pull. Verified nothing on this side normalises inner whitespace: `t_string` is
  `.strip()` (ends only), the canonical models set no `str_strip_whitespace`, and a formula row's
  result is returned unmodified. `name` stays `Description -> name` (the contract requires it;
  Sorento ignores it once `description` is present). `remark` and `cost_price` are never sent -
  already true, `CanonicalProduct` declares no `remark` and nothing derives a cost on either side.
  Pinned with five fixtures: an item with no `Desc2`; one with `Desc2` (177 live); one whose raw
  join yields a double space; one whose description starts `****` (2,882 live) proving
  `is_discontinued` is derived by Sorento from the text we send; and one carrying dimensions in
  the description proving L/W/H parse identically.
- **AC-10-74 [BE]/[FE]** **`uom_code` is withheld during the check period (R10).** The manual
  template has no UOM column, and the peer's correction (2026-09-20) is that X FORCES the configured
  default UOM onto every row it touches, while omitting `uom_code` on the ingest path leaves the
  unit untouched on update and takes the default on create. That is NEAR-parity, not identity:
  the measured residue is 26 `SRT` products still on `L` against 11,850 on `EA` (MCH all `EA`) -
  a next manual upload resets those 26 to `EA` while a pull leaves them on `L`, and it never
  appears as a `dry_run` diff row because the key is absent. Sending `uom_code` would instead make
  a pull diverge from a manual upload on every product, so it stays withheld. The preset therefore seeds the `BaseUOM -> uom_code` row **present but DISABLED**
  (`PresetField` gains an `enabled: bool = True` flag that `_seed_rows` passes into the
  `is_enabled` it already computes) rather than omitting it: the operator can SEE the field exists
  and turn it on deliberately, which an absent row cannot express. Enabling it is an item on the
  plan's push-flip checklist. A test pins that a freshly seeded product task sends no `uom_code`
  and that enabling the row sends it.
- **AC-10-75 [BE]** **Bounded retry per page before declaring failure (ops finding 2026-09-19:
  the `db2` wrapper timed out repeatedly at `pageSize=1000` while `db1` was fine).** Today
  `http_source/client.py` makes ONE attempt per page with a 30 s timeout and no retry
  (AC-08-23), so a single slow Mocha page fails a whole build. Each page request (main path AND
  lookups) now retries at most twice on a TIMEOUT, connect error or 5xx, with a bounded backoff
  (1 s then 4 s), and a Cloudflare **524** is treated as a timeout, not as a 5xx to give up on.
  **On a SECOND timeout of the SAME page the walk HALVES the page size for the rest of the run
  (floor 50) and RESTARTS from page 1**, because page boundaries shift the moment the size
  changes; the echoed-`TotalPages` rule (AC-08-22) still governs termination at the new size, and
  a full-set walk is idempotent so restarting costs time, never correctness. At most two halvings
  per run, then the existing `HttpSourceError` / `SOURCE_PAGE_FAILED` rule applies unchanged - a
  4xx, a non-JSON body or a shape change still fails immediately with no retry. Attempts, the
  restart and the effective page size are recorded in the run's `CallRecord` activity so an
  operator sees a flaky endpoint.
  The fail-before-state rule (AC-10-22) is untouched: retries happen inside the walk, before any
  hash, watermark or snapshot row is written.

- **AC-10-76 [BE]** **Combine config and its save gate (R11).** `source_config.combine` is
  optional, at most ONE per task, and shaped
  `{computed[], require[], measure, groupBy[], measures[], carry[], round[], drop[]}`. Caps:
  10 computed, 10 require, 5 group-by, 10 measures, 10 drop rules, 20 carried columns. 422 naming
  `combine.<part>[i]` for: an unknown column or alias; a forward reference (a computed formula
  naming a LATER computed alias, or `groupBy`/`measures`/`carry` naming an undefined one); an
  alias clashing with a source column, a lookup alias or another computed / measure alias; an
  empty `groupBy`; a `measure` that does not name a known PRE-GROUP column (a raw source column,
  a lookup alias or an earlier computed alias - never a `measures[].alias`, which does not exist
  until AFTER grouping); a numeric op
  (`sum`/`min`/`max`) over a column whose previewed sample values are non-numeric with no
  computed cast (a SAMPLE-based check, so a runtime non-numeric still raises the normal named
  `TransformError` - stated, not pretended away); and a `require` or `drop` formula whose inferred
  type is not boolean. Every formula is parsed at save time by the EXISTING `parse_formula` with
  `known_variables` = source columns + lookup aliases + earlier computed aliases. No joins live
  here (that is Lookups), no nested grouping, no second combine step.
- **AC-10-77 [BE]** **Stage order, computed columns and require rules.** Combine runs after every
  lookup and before mapping, in this order: (1) `computed` in list order, each formula able to
  name any row column, any lookup alias and any EARLIER computed alias; (2) `require` in list
  order - the first rule that evaluates falsy EXCLUDES the row with that rule's `reason`, and the
  excluded entry carries the row's `groupBy` values plus the raw value of the DESIGNATED
  `measure` column, so `excludedNonzeroCount` is computable for any entity without the engine
  knowing what `BalQty` is. A require formula that raises is itself an exclusion with reason
  `require_error`, never a run failure.
- **AC-10-78 [BE]** **Group, measure, carry.** Rows are grouped on the `groupBy` columns (exact
  values after computed columns have run, so trimming is explicit in a computed column, never
  implicit). Each `measures` entry applies `sum | min | max | count | first | last` to a source
  column or computed alias and publishes it under its alias; `carry` columns take the FIRST value
  seen in the group (`item_description` is the live case). Group ordering is first-appearance, so
  the emitted set is deterministic for a fixed input.
- **AC-10-79 [BE]** **Rounding and drop rules.** `round` entries apply `none | half_up` at N
  decimal places to a named measure after grouping, and the number of groups whose value CHANGED
  is the generic `roundedCount`. `drop` rules then run in list order over the grouped rows; the
  first matching rule drops the group and increments a counter under that rule's `name`, and when
  `listRows` is true the dropped rows are listed (capped at 50, with the cap flagged per
  AC-10-66's `truncated` rule). A drop formula that raises is a named task error, not a silent
  keep.
- **AC-10-80 [BE]** **Output key and the push path.** When a task carries a combine step its KEY
  FIELDS are the `groupBy` columns - derived, never separately typed, and the Source tab's key
  picker becomes read-only chips showing them. De-duplication, `source_ref` minting and
  `row_hash` all run on the COMBINED rows, so a push task combines exactly as a pull task does
  and the reconcile diff is over combined rows. Consequence, pinned: editing the combine config
  changes both the identity and the hash of every row, so it sets `etl_status` back to `draft`
  under the EXISTING rule for a config change (AC-10-28) and the first reconcile afterwards
  reports updates rather than phantom deletes.
- **AC-10-81 [BE]** **Generic metadata, unchanged wire (R11).** The step produces
  `{excludedRows, excludedCount, dropped: {<rule>: {count, rows?}}, roundedCount}` for ANY entity.
  The agreed Sorento stock header names are produced FROM that by ONE declarative map on the
  entity profile - `zeroPairs <- dropped["zero"].count`,
  `negativePairs <- dropped["negative"].count`, `negativePairList <- dropped["negative"].rows`,
  `fractionalPairs <- roundedCount`, `excludedNonzeroCount <- excludedRows where measure != 0`,
  `excludedRows` / `excludedCount` passing through unchanged. A test pins the serialised stock
  header against Appendix A3's agreed example byte for byte, so renaming a drop rule cannot
  silently change the consumer's contract (the map is what would 422 at save time instead).
- **AC-10-82 [FE]** The Source tab gains a **Combine rows** section below Lookups, shell
  primitives only: computed columns (alias input + the EXISTING
  `components/platform/autocount/formula-builder` component), require rules (name + formula +
  reason code), group-by `MultiSelect` over previewed columns and aliases, measure rows (source
  `SearchSelect` + op `SearchSelect` + alias input), carry `MultiSelect`, per-measure rounding
  (`SearchSelect` `None` | `Half up` + dp), and ordered drop rules (name + formula + a
  "list dropped rows" switch). Test shows the FUNNEL - rows in, excluded, groups, dropped per
  rule name, rows out - plus the combined rows in the existing preview grid. Nothing is free text
  except aliases, rule names and formulas; every column pick is searchable; no hint copy.
- **AC-10-83 [E2E]** Operator edits a drop rule by real clicks at 375 AND 1280, evidence
  `10-evidence/combine/`: AutoCount -> Companies -> `db1` -> Stock balance entity -> Source tab ->
  Combine rows -> the pre-filled rules are visible -> open the `negative` rule -> turn "list
  dropped rows" off -> Test -> the funnel shows the dropped count with no listed rows -> undo ->
  Save.
- **AC-10-84 [T]** The stock preset reproduces the live numbers end to end on `db1` with no
  operator configuration: 68,612 rows in -> 12,133 rows out, the `zero` rule dropping roughly
  56,400, the `negative` rule dropping 42 and listing them, `roundedCount` 0, and the excluded set
  matching the 5 known rate-unresolved rows. Report cites the snapshot id and the funnel counts.

- **AC-10-85 [BE]/[FE]** **Page size and request timeout are per-CONNECTION settings**, because
  they are a property of the book's host, not of a task: `AutoCountProvider.fields()` gains
  `pageSize` (number, default 1000, 50..1000) and `requestTimeoutSeconds` (number, default 90,
  max 100 - deliberately under Cloudflare's roughly 100 s cut), both carrying the EXISTING
  `showWhen: {field: "auth", values: ["none"]}` mechanism so they appear only for an open
  connection. Verified today: `HttpApiSource` builds `HttpApiClient(base_url, transport=...)`
  without passing a timeout, so the client's `DEFAULT_TIMEOUT_SECONDS = 30.0` is fixed, and
  `DEFAULT_PAGE_SIZE = 1000` is a module constant in `http_source/source.py` - both now read from
  the connection config with those values as the fallback, in ONE place each. The connection Test
  reports the MEASURED latency of its probe ("Reached in 21 s, 154 locations") so an operator
  sizes the settings from evidence rather than guesswork. Lookup endpoints obey the same page
  size, timeout and retry as the main path.
- **AC-10-86 [BE]** **Long builds are supported, not papered over.** The snapshot build job has no
  short global timeout: it is an ordinary `background_jobs` row that beats per page, and the only
  ceiling is the liveness sweep of AC-10-26. The effective page size actually used by a run
  (after any halving) is recorded in the run activity AND on the snapshot header as
  `sourcePageSize`, so a slow book is diagnosable after the fact. Expected durations, from the
  measured 0.2 s per row on db2: a Mocha product snapshot is about 3,438 items plus about 3,438
  ItemUOM lookup rows, roughly **25 minutes**; Mocha stock is UNKNOWN (its balance row count has
  not been measured). The 60 s build cooldown (AC-10-26) is unchanged - it bounds request volume,
  not build duration. Pinned by a test that a build exceeding the default request timeout per page
  still completes and stamps `sourcePageSize`.

- **AC-10-87 [BE]** A `building` header may carry an OPTIONAL `progress` hint
  `{pagesDone, pagesTotal, stage}` where `stage` is `"source"`, `"lookup:<alias>"`, `"combine"` or
  `"mapping"`. It is cheap because the walk already trusts the wrapper's ECHOED `TotalPages`, and
  it is OMITTED whenever it is not known (before page 1 answers, for a bare-array endpoint, or
  during a stage with no page count) - never guessed, never a percentage. The consumer treats an
  absent `progress` as "still building", exactly as before. Written on the snapshot row as the
  build advances, so it costs one small update per page and nothing on the read path.
- **AC-10-88 [BE]** **Re-attach while alive; reclaim only when dead.** A build request for a
  (tenant, company, entity) whose snapshot is `building` returns THAT `snapshotId` for as long as
  its job is alive, with no time limit - a consumer that gave up polling at 60 minutes re-attaches
  rather than starting a second extraction. A DEAD build is reclaimed by the machinery that
  already exists, not by a new timer: the build job registers with `heartbeats=True` and beats per
  page (like `autocount_sync`), core's `JobService.fail_orphaned_running_jobs` fails a RUNNING job
  whose last beat is older than `background_job_orphan_after_minutes` (default 15, floor 5 -
  liveness, never age), and the module's existing `on_job_orphaned` hook, extended to this job
  type, marks the snapshot `failed` with `error_code = "BUILD_ABANDONED"`. Only once the snapshot
  is `failed` may a new build start. Pinned both ways: a beating 30-minute build is never
  reclaimed and keeps returning its id; a job whose beat stopped 16 minutes ago is failed
  `BUILD_ABANDONED` and the next request starts a fresh snapshot.

## Group F - operator UI, end to end, live, docs (`[FE]` / `[E2E]` / `[T]`)

- **AC-10-48 [FE]** Frontend layering holds: new types in `types/autocount.ts`, the service trio
  `autocount-service.{ts,mock,real}.ts` gains `setDeliveryMode`, `listPullKeys`, `issuePullKey`,
  `revokePullKey`, `listPullSnapshots`, `getPullSnapshot`, `getPullSnapshotRows`,
  `buildPullSnapshot`; one hook module `hooks/use-autocount-pull.ts`; no component calls
  `fetch`/`api-client` directly; no `any`. Mock fixtures cover every state: no keys, one active
  and one revoked key, a `building` / `ready` / `failed` / `expired` snapshot, a stock snapshot
  with exclusions and negative pairs, and a 409 `PUSH_ACTIVE`.
- **AC-10-49 [FE]** The snapshot detail surface shows the header facts (entity, company, status,
  records, complete, built, expires, content hash) plus the metadata blocks - for a product
  snapshot the zero-list-price count, the negative-list-price (clamped) count and the enrich-miss
  count; for a stock snapshot the zero / negative / fractional counts and the negative pair
  list; and for BOTH the excluded-row list with its reasons - and the first page
  of rows in the existing preview grid primitive (reused with a prop, never a second grid).
  Truncated text uses `ClampedText` / `OverflowPills`, never a bare `truncate`.
- **AC-10-50 [E2E]** Operator journey, 375 AND 1280, real clicks from the sidebar, evidence
  `10-evidence/pull-setup/`: AutoCount -> Companies -> the `db1` company -> Product entity ->
  Schedule tab -> switch Delivery to "Pull on request" (cadence controls disappear) -> Review &
  Activate -> Activate -> back to Entities (Delivery column reads "Pull on request") -> sidebar
  AutoCount -> Pull -> Keys -> Issue key (name + both companies) -> plaintext shown once ->
  Snapshots segment -> Build snapshot for Product -> the row goes building -> ready with the
  record count -> open it -> header + first page of rows render.
- **AC-10-51 [E2E]** Stock journey, 375 AND 1280, evidence `10-evidence/pull-stock/`: add the
  "Stock balance" entity on the `db1` company -> the Source tab shows the preset path, the two
  enrich rows and the read-only "Aggregated to one row per item and location, base UOM, whole
  units" chip -> Test -> Save -> Activate (Delivery reads "Pull on request", no toggle) -> Pull
  page -> Build -> the snapshot detail shows the zero / negative / excluded counts and the rows.
- **AC-10-52 [E2E]** Flip-to-automatic journey, 375 AND 1280, evidence `10-evidence/flip-push/`:
  on the same Product task switch Delivery back to Push -> the cadence controls return with
  their saved values -> Save -> the Runs tab shows the schedule armed -> the consumer's pull now
  answers 409 `PUSH_ACTIVE` (proved by the curl transcript in the evidence README).
- **AC-10-53 [T]** Live replay, lane DB, LOGGING sink, BOTH books: against
  `https://hapi.sorento.cc.cd/api/db1` and `/api/db2` - build a product snapshot and a stock
  snapshot per book, record `record_count`, `complete`, `content_hash`, the build duration and
  the request count; prove the db1 product snapshot is `ready` and reports roughly 11,830 rows with
  `zeroListPriceCount` about 5,129 (5,008 already zero plus 121 clamped), `negativeListPriceCount`
  121 and `excludedCount` about 10 (the empty-`Description` items), and that the `SRT` stock
  snapshot delivers roughly 12,133 rows over 75 locations with 42 negative pairs excluded and the
  expected excluded-row set - of which Sorento applies roughly 6,500 after its own
  active-warehouse filter (R7), the rest listed by Sorento as "not applied". Report cites job ids
  and snapshot ids, and records both numbers side by side.
- **AC-10-54 [T]** Enrich mutation replay on the PUSH path: a recorded stub of 20 items whose
  `/itemuombypage` `Price` changes for exactly one item produces 0 added, 0 deleted, 1 updated
  and one pushed product whose `list_price` is the new value; a second identical run reports
  0/0/0.
- **AC-10-55 [T]** Failure replays: (a) a stub that 500s on page 3 of the balance walk leaves the
  snapshot `failed` with zero readable rows and no `ac_row_hash` / `ac_watermark` change;
  (b) a stub whose enrich endpoint 500s fails the run with the enrich endpoint named; (c) an
  expired snapshot answers 410 on both header and rows while its `ready` sibling still serves.
- **AC-10-56 [T]** Cross-repo: plan Appendix A (the Sorento contract brief for the pull client,
  review page, xlsx download, products Confirm through `MasterIngestService`, stock Confirm
  through `process_stock_import` plus the Stock List xlsx archive, the manual-upload parity gate
  of A10, and the later `stock_balances` ingest entity for 2.5) is delivered to the Sorento owner
  session and acknowledged; the acknowledgement (session name + date) is recorded in the test
  report. **Precondition:** Sorento's contract-2.4 code-wins change (their SR0) is DEPLOYED before
  joint run 1 on `SRT`; `MCH` (zero existing refs) works without it, so an `MCH`-first run is the
  fallback if SR0 slips. TWO joint live runs against the lane backend from the Sorento lane are
  recorded with their snapshot ids:
  - **joint run 1** products, `SRT` then `MCH` (their SR3). **Exit criterion (R10):** Sorento's
    `dry_run` over the pulled `SRT` set shows NO `description`, `is_discontinued` or L/W/H change
    for any product whose AutoCount data has not changed since the last manual upload - every
    remaining diff row explainable, row by row.
  - **joint run 2** stock, `SRT` then `MCH` (their SR4), recording BOTH numbers: rows delivered by
    Foundryx and rows applied by Sorento after its active-warehouse filter (R7).
- **AC-10-67 [T]** S0 ships recorded sample fixtures for the Sorento mock build under
  `documentation/plans/sprint-5/10-fixtures/`: per entity (`products`, `stock_balances`) a
  snapshot header JSON and one 10-row page JSON, plus one 409 body and one `status: "failed"`
  body. The PRODUCT page fixture must carry the awkward rows Sorento's parity test needs
  (R10): an item whose description starts `****`, an item with dimensions in its description, an
  item WITH `Desc2` (and one whose raw join yields a double space), a `-1.0` source price item, a
  `0` price item, an edge-whitespace `ItemCode` item, and one MOCHA-SHAPED row (no `brand_code` at
  all, with a joined `Desc2` description): Mocha carries NO brands - 3,442 of 3,442 NULL in
  Sorento, 445 of 445 blank in our sample - and does have `Desc2` items, so a fixture that only
  looks like `SRT` would not exercise the absent-key path. They are recorded from the lane (or hand-written to the Appendix A shapes before the lane
  exists) and are re-verified against the real gateway in S6; any drift found there is fixed in
  the fixtures in the same commit.
- **AC-10-57 [T]** Test Execution Report keyed AC-10-01..88 (plus AC-10-09b); pytest autocount + module suites
  green on Postgres; vitest green; `npm run lint` and a fresh `rm -rf .next && npm run build`
  clean; `documentation/engineering/process-lessons.md` (AutoCount section) gains the delivery
  mode, enrich, reduce and snapshot rows; `documentation/engineering/module-platform-and-app-
  store.md` gains the second public API-key gateway as a cross-reference; backlog rows for every
  deferral in plan section 6.
- **AC-10-58 [T]** Security pass (reviewer + security-reviewer, Opus): no unscoped `get_by_id`
  on any stored id; no tenant / company id accepted from a gateway client; keys never logged and
  never returned twice; the audit table holds no PII; a suspended tenant and a deactivated module
  both stop the gateway; the build cooldown and the throttle both proven; the operator routes
  carry the new permission keys and the existing tenants' grant sweep is proven.
