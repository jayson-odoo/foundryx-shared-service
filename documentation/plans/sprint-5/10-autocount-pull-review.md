# 10 - AutoCount human-invoked pull (list price, stock balance, snapshot gateway)

UAC: `10-autocount-pull-review-acceptance-criteria.md` (the contract; this file is the design
that fulfils it). Lane `sprint-5/10-autocount-pull-review`, worktree `.claude/worktrees/s40`
off `origin/main` c1c5906a (module 0.10.0, module Alembic head `0019_autocount_so_ref`).
Backend :8009, frontend :3009, DB `foundryx_service_s40`.

## 0. Open items

None. The stock-scope question is closed by owner ruling R7 (D18) and the product-identity
question by owner ruling R8 (D19); both are recorded as locked rulings in the UAC.

## 1. Why

Item master and stock balance reach Sorento BY HAND today: a human exports from AutoCount and
uploads an Excel file. The owner will not hand that to an unattended push yet (grill
2026-09-19). The wanted flow is a human in the loop on the CONSUMER side:

1. A Sorento user presses a button.
2. Sorento calls Foundryx server-side and pulls the extract (sourced from the AutoCount hapi
   wrapper this module already reads).
3. Sorento shows a review page (plus an optional xlsx download in the manual template shape),
   the user compares it against what the manual upload produced, and presses Confirm.
4. After a few days of human-checked runs, each entity flips to auto-push - per company book,
   independently.

SO / PO / SPO stay on push exactly as they are. Both books are in scope from day one: `db1`
(Sorento, `AED_SORENTO`) and `db2` (Mocha). Three things are missing on this side and one is
wrong:

- **No route a consumer can call.** Everything this module does is outbound push
  (`sinks_sorento.SorentoSink`). Nothing outbound Sorento -> Foundryx exists.
- **No held extraction.** A pull that re-reads the ERP on Confirm would confirm a DIFFERENT set
  than the one reviewed.
- **No stock balance and no list price.** `CanonicalProduct.list_price` exists in `SINK_FIELDS`
  and has never had a source: `/itembypage` carries no price at all; the price lives on
  `/itemuombypage`, a SECOND endpoint, and no cross-endpoint join mechanism exists anywhere in
  this ETL.
- **Delivery is implicit.** An ACTIVE `sql_db` / `autocount_http` task auto-pushes by
  construction (`sync.py`, the `etl_status == ACTIVE` branch). There is no way to say "extract,
  but hold".

## 2. Design

### 2.1 Delivery mode: one column, one gate (D1, D2)

`ac_entity_config` gains `delivery_mode` (`push` | `pull`, NOT NULL, `server_default 'push'`).
The per (company, entity) task row IS the unit of choice, which is exactly the owner's "per
company book and per entity" requirement with no new entity and no new table.

Three places consume it, and only three:

1. `sync.py`'s auto-push branch (the plain path around line 798 and the paged path around
   line 1873) gains `and config.delivery_mode == DELIVERY_MODE_PUSH`. A pull task cannot push.
2. `scheduler.sweep_etl_tasks`'s due query gains `AcEntityConfig.delivery_mode ==
   DELIVERY_MODE_PUSH`; `EtlService.activate_task` arms no `next_*_at` for a pull task and
   clears both when a task is switched to pull.
3. The pull gateway reads it to decide `PULL_NOT_ENABLED` vs `PUSH_ACTIVE`.

**Pull tasks do NOT run on the schedule (D2).** Recommended and taken, for three reasons: the
snapshot TTL is 24 h and Sorento's Confirm must re-read the SAME `snapshot_id`, so pre-built
snapshots nobody reads are pure churn (12k-70k rows every cadence); the owner's flow is
explicitly a button press; and a scheduled pull keeps reading a customer's ERP with no consumer
on the other end and nobody watching. The consequence is a clean one-switch flip: `pull -> push`
re-arms from the SAVED `source_config` through the existing `next_run_times` with no re-mapping,
no re-Test and no status change (AC-10-14).

`stock_balance` is pull-only (AC-10-15): Sorento has no stock ingest entity, so `push` is a
configuration that is guaranteed to fail - the foolproof-UI line this module already applies to
`sorentoCompanyCode`.

### 2.2 Lookups: a general, operator-configurable cross-endpoint join (D3, owner ruling R9)

The owner's question was the right one: "how can this be more general and applicable for future
possible similar use cases". So this is NOT a hidden block that only knows about list price. Any
API task may carry an ORDERED list of `lookups`, authored by the operator on the Source tab:

```
lookups: [ { path, as, on: [{local, remote, match?}], fields: [{remote, as}] } ]
```

One lookup reads one more endpoint on the SAME connection, joins it to the task's rows on one or
more column pairs, and brings named remote columns in under operator-chosen aliases. Rules, all
fixed and documented rather than offered as choices:

- **Order is evaluation order.** Lookup 2 may join on an alias produced by lookup 1, which is how
  the stock path chains balance row -> item `BaseUOM` -> ItemUOM `Rate` without a second
  mechanism. A `local` column that no earlier step produces is a save-time 422, so a forward
  reference or a cycle cannot be expressed at all.
- **A miss leaves the alias ABSENT** (never `None`), so `sink_payload()`'s omit-None rule does the
  right thing and a missing price is a missing key, not a cleared field.
- **Path safety is the main path's**, reusing `validate_http_path`
  (`http_source/preview.py:30-46`) - the editor cannot reach an endpoint the task path could not.
- **Aliases are ordinary columns.** They land in `result_columns`, in the Mapping tab's picker,
  in the key / watermark / compared pickers and in the row hash. Nothing downstream knows a
  lookup happened.
- Capped at `MAX_LOOKUPS` (5) per task; each lookup endpoint is walked ONCE per run.

**One naming note, deliberately not churned:** "lookup" is the operator's word and the config key;
"enrich" survives as the internal/wire word in two already-agreed places - the snapshot header's
`enrichMissCount` and the gateway's `ENRICH_FAILED` status code, both already in the Sorento
peer's hands (Appendix A). Renaming a contract field to match an internal vocabulary change would
be churn for its own sake.

New module `http_source/lookups.py` owns `validate_lookups(specs, source_columns)`,
`build_index(rows, on)` and `apply(rows, index, fields)`; `HttpApiSource.fetch_changes` calls them
in order between `_walk()` and `_dedupe()`. The lookup endpoints are walked with the SAME `_walk`
machinery, so the echoed-page trust, the non-advancing-page guard, the row cap and the
fail-before-state rule are inherited, not re-implemented.

**The editor** extends the Source tab's API branch built in plan 08 rather than adding a surface:
`source-tab.tsx` already imports `SearchSelect`, `ColumnPickers`, `ColumnChips`, `SqlPreviewGrid`
and `DeferredActionButton`, and a lookup row is those same pieces - path input + Test, two
`SearchSelect`s per join pair (local options = previewed source columns plus earlier aliases;
remote options = the lookup endpoint's own probed columns, from a small
`POST /autocount/http/preview-columns`), a match-mode `SearchSelect`, and remote-column -> alias
field rows. Nothing is free text except the path and the alias. The product preset ships
PRE-FILLED with the ItemUOM lookup, so the owner's case needs zero configuration, but it is an
ordinary row that can be edited or deleted.

Why aliases are merged onto the ROW, rather than a special `list_price` code path:

- **The operator sees where the value comes from.** `BaseUOMPrice` is an ordinary source column
  in `result_columns`, so it appears in the Mapping tab's source picker and in the key /
  watermark / compared pickers with no special casing. The Source tab adds a read-only
  "Enriched fields" section naming the endpoint and the join keys (AC-10-09).
- **Change detection is free.** The default `comparedFields` is every result column minus the
  keys (`compared_columns_for`), so `BaseUOMPrice` joins the row hash automatically and a
  price-only change is a genuine `updated` (AC-10-06). This is the single most important
  property: a bolt-on price lookup that did not enter the hash would never re-push.
- **A miss is absence, not null.** An unmatched row does not gain the alias key, so
  `CanonicalMaster.sink_payload()`'s "omit None, keep falsy" rule omits `list_price` entirely
  rather than sending `null` (which under Sorento contract 2.1 means "clear this field").

Live shape (probed): `/itemuombypage` has 11,852 rows for 11,840 items, every item has a row
whose `UOM` equals its `BaseUOM`, every `Rate` is 1.0, and there are zero duplicate
`(ItemCode, UOM)` pairs - so the index is exact and the `casefold_trim` matcher covers the
`'unit'` vs `'UNIT'` dirt. Junk rows with `UOM: ""` simply never match.

**R2 (owner, locked): list price 0.0 ships as a real `0`.** No omit-on-zero, matching AutoCount
and matching what the manual Excel upload does. 5,008 of 11,840 db1 items are 0.0, and the
Sorento review page states that count. `sink_payload()` already keeps falsy non-`None` values;
AC-10-07 pins it so a future "tidy up empty values" change cannot silently break parity.

**R5 (owner, locked): a negative list price is clamped to 0, visibly.** The plan review found 121
ACTIVE db1 items whose base-UOM `ItemUOM` `Price` is `-1.0` - a vendor sentinel, not a price - and
`CanonicalProduct.list_price` is `ge=0`, so without a rule every db1 product extract would reject
121 records. The owner's rule is the manual upload's: negative becomes 0. It is expressed as the
preset mapping row's FORMULA, `if(number(value) < 0, 0, number(value))` - every token already
exists in the formula engine (`if`, `number` and `<` are in `formula.FUNCTION_CATALOG` /
`OPERATOR_CATALOG`) - so it is an ordinary editable row in the Mapping tab with its formula
builder and simulator, not a coercion buried in the canonical model. `ge=0` stays as the backstop.
Because push and pull share ONE mapper, the clamp applies on the PUSH path the moment S1 ships,
which is the honest outcome: the same 121 items would otherwise have been silently rejected there
too. The snapshot header reports `negativeListPriceCount` beside `zeroListPriceCount`, and
AC-10-63 fixes their semantics so they cannot be double-read: `zeroListPriceCount` counts rows
whose DELIVERED price is 0 (post-clamp, so it includes the clamped negatives), while
`negativeListPriceCount` counts only the clamped ones. On db1 that is roughly 5,129 and 121.

**One trim rule, one place (D17).** 20 live db1 `ItemCode`s carry leading or trailing whitespace,
and one location code is `'MBS '`. The HTTP source writes a trimmed view (`str(value).strip()`) of
every KEY field and every enrich JOIN field back onto the raw row immediately after the walk, once
- so the enrich index, the canonical `code`, the stock reducer's grouping, the de-duplication and
the row hash all read the SAME value with no second copy to drift. The one carve-out:
`flat_source_ref` identity for an entity that ALREADY pushes (product) keeps using the RAW key
value, because changing a ref retroactively orphans the row Sorento already holds under the old
one and would land as 20 creates plus 20 deletes. `stock_balance` has never pushed, so it mints
its ref from the trimmed values. Normalising the existing product refs cross-repo is backlogged
(BL-SS-216), not smuggled into this plan.

### 2.3 Stock balance: a canonical entity with a NAMED reducer (D4, D5)

`ENTITY_STOCK_BALANCE` + `CanonicalStockBalance` land in `canonical/masters.py` beside their
siblings (same no-import-cycle reason the file's own comment gives), registered in
`ENTITY_PROFILES`, `ETL_ENTITY_TYPES`, `HTTP_PRESETS` and `mapping_catalog.SORENTO_FIELDS`. It
gets NO `sinks_sorento._ENTITY_PATH` entry: there is no Sorento ingest path, and inventing one
would be a lie the sink would discover at push time. The pull-only rule keeps the sink
unreachable for it.

**Everything here is operator-configurable (owner ruling R11).** The JOINS are ordinary lookups
(R9): the item's `BaseUOM` and `Description` from one lookup on `/itembypage`, the UOM `Rate` from
a second on `/itemuombypage` that joins on the first one's alias. The COLLAPSE is a second general
step - **Combine rows** - available on ANY API task, running after Lookups and before mapping,
with the stock preset shipping it PRE-FILLED so the owner configures nothing:

```
combine: {
  computed: [ {alias, formula} ],          # ordered, may name earlier aliases
  require:  [ {name, formula, reason} ],   # falsy -> row EXCLUDED with that reason
  measure:  "<pre-group column>",          # the designated quantity, for generic counters
  groupBy:  ["..."],                       # picked columns, never typed
  measures: [ {source, op, alias} ],       # sum | min | max | count | first | last
  carry:    ["..."],                       # first value in the group
  round:    [ {measure, mode, dp} ],       # none | half_up
  drop:     [ {name, formula, listRows} ]  # ordered, counted per name
}
```

Six properties keep it honest rather than a rules engine:

1. **One step per task, no joins, no nested grouping**, and caps on every list (10 computed,
   10 require, 5 group-by, 10 measures, 10 drop rules). Joins belong to Lookups; combining
   combined rows is not expressible.
2. **Every expression is the existing hand-written formula engine** (`parse_formula` /
   `evaluate_formula`, `FUNCTION_CATALOG` + `OPERATOR_CATALOG`) - never `eval`, never a template
   language. This is the house anti-SSTI line applied to one more surface, not a new one.
3. **Ordered evaluation, no forward references** - a computed column may name earlier aliases
   only, which is a save-time 422 rather than a runtime surprise.
4. **A designated `measure`** is what makes the generic counters work: an excluded row keeps its
   group-by values and that column's raw value, so `excludedNonzeroCount` is computable without
   the engine ever knowing the word `BalQty`.
5. **The group-by columns BECOME the task's key fields.** De-dup, `source_ref` and `row_hash` all
   run on the combined rows, so a push task combines exactly as a pull task does. Editing the
   combine config therefore changes identity and hash, which sends the task back to `draft` under
   the existing config-change rule - no phantom deletes, one wave of updates.
6. **Generic metadata, unchanged wire.** The step emits
   `{excludedRows, excludedCount, dropped: {<rule>: {count, rows?}}, roundedCount}`; the agreed
   Sorento stock names (`zeroPairs`, `negativePairs`, `negativePairList`, `fractionalPairs`,
   `excludedNonzeroCount`) are produced from it by ONE declarative map on the entity profile
   (AC-10-81). Renaming a drop rule cannot silently change the consumer's contract - the map is
   what fails at save time instead.

What the operator sees is a funnel, not a chip: Test reports rows in -> excluded -> groups ->
dropped per rule -> rows out, with the combined rows in the preview grid. The stock preset's own
configuration is in AC-10-41, and it is editable like any other.

The stock preset's combine configuration, grounded in the probe:

| Step | Rule | Live evidence |
|---|---|---|
| Trim | Inherited from the ONE trim rule (section 2.2 / AC-10-60); the warehouse master's `Location` is trimmed the same way | `'MBS '` with a trailing space; Sorento matches case-insensitively but does NOT trim |
| Base UOM | Row whose `UOM` casefold-trim == enriched `ItemBaseUOM` contributes `BalQty` | every item has a base-UOM row |
| Convert | Any other row contributes `BalQty * UomRate` from `/itemuombypage` | 27 non-base rows, 4 nonzero |
| Exclude | Missing / non-numeric / `<= 0` rate -> `excludedRows` entry, contributes nothing | 5 rows, all zero qty, casing dirt |
| Sum | Group by `(item_code, location_code)` over every `BatchNo` | `BatchNo` empty on all 68,612 rows |
| Round | Half-up to int; any pre-rounding difference counted in `fractionalPairs` | 0 fractional pairs live |
| Drop | `== 0` -> `zeroPairs`; `< 0` -> `negativePairs` + full `negativePairList` | 56,433 zero, 42 negative pairs |

`item_description` rides the SAME enrich mechanism (`/itembypage` is already needed for
`BaseUOM`), so Sorento can build its Stock List xlsx (Item Code, Item Description, Location,
On Hand Qty) with no second lookup.

**Faithful source, consumer-side filter (R7).** The reducer cuts on QUANTITY only. It holds no
location allow-list, reads no `IsActive`, and applies no item filter - the delivered `SRT` set is
roughly 12,133 pairs over 75 locations. The manual macro workbook's 6,591 rows were proven to be
the same data after a LOCATION filter (`Master` filtered by an `Active Loc` sheet of 60 locations
and `On Hand Qty > 0`), and Sorento's `warehouses.is_active` already mirrors that sheet almost row
for row. So the filter lives where the flag lives: Sorento applies only rows whose warehouse is
active there and lists the rest as "not applied" with counts. Putting a copy of that list in
Foundryx would be a second source of truth that silently drifts the first time a warehouse is
activated. Of the 75 stock-bearing locations: 43 active in Sorento, 25 present but inactive
(5,476 pairs, led by `CON` 1,596 / `BRW-DFCT` 982 / `JB SHOWR` 571), 7 missing entirely
(155 pairs, led by `BRW-VAR` 142). AC-10-68 pins the absence of a filter here.

`complete` stays TRUE with exclusions - an exclusion is a data problem, a truncated walk is not.
The FULL company set always ships: Sorento's stock import zeroes every (product, active
warehouse) pair absent from the file, so a truncated set is destructive, which is why any page
failure fails the whole snapshot (the plan-08 rule, inherited).

### 2.4 Snapshot store (D6, D7)

Two tables in `app_autocount`, module Alembic `0020_autocount_pull_snapshot` (down
`0019_autocount_so_ref`; 28 chars, no collision):

- `ac_pull_snapshot` - `id, tenant_id, company_id, entity_type, company_code, status
  (building|ready|failed), job_id, record_count, complete, content_hash, metadata_json, error,
  error_code, requested_via, requested_by, created_at, extracted_at, expires_at`.
- `ac_pull_snapshot_row` - PK `(tenant_id, snapshot_id, row_index)` + `company_id, source_ref,
  payload_json`.

`company_code` is COPIED onto the snapshot at build time so a later edit of
`ac_company.sorento_company_code` cannot retarget an extraction that is already out for review.

**Immutability is structural, not a convention.** The repository exposes insert-row and
stamp-terminal methods only; there is no update-row or delete-row method at all, and
`SnapshotService` raises on any write against a snapshot whose status is not `building`
(AC-10-19). Expiry is DERIVED from `expires_at` - never a stored fourth status that a clock skew
could disagree with.

Size and pruning: a product snapshot is ~11.8k rows (~2 MB of JSON), a stock snapshot ~12.2k
rows; the raw stock walk is 69 pages but the stored set is the REDUCED one. `expires_at =
extracted_at + 24 h` (setting `autocount_pull_snapshot_ttl_hours`), where `extracted_at` is the
moment the snapshot became READY - the BUILD END, never its start. A 25-minute Mocha build
therefore still leaves a full 24 hours of review time, which is the point of anchoring it there. A new beat task
`autocount.prune_pull_snapshots` (hourly, registered beside `autocount.etl_sweep` in
`app/workflow_engine/worker.py`) deletes expired snapshots and keeps at most the newest 3
`ready` snapshots per (tenant, company, entity).

The build is a background job `autocount_pull_snapshot` (`register_job_handler`, imported in the
Celery worker path exactly like `autocount_sync`, or jobs sit Pending forever). It reuses the
SOURCE registry factory, `mapping.map_document` and the existing activity trail; it writes NO
`ac_staged_record`, NO `ac_row_hash` and NO watermark (`persist_hashes=False`, `mode=reconcile`)
- a pull is a full snapshot every time, and for stock the drop-zero rule would otherwise churn
the hash table and trip the delete guard on every run. It records ONE `ac_sync_run` with
`mode='snapshot'` so the Runs tab shows a pull build like any other run.

**Set-level failure vs per-record exclusion (R6, AC-10-22 / AC-10-62).** A fault that makes the
SET untrustworthy - a source page failure, an enrich endpoint failure, a row-cap breach, an empty
extract against a previously non-empty one - fails the whole snapshot with its own `error_code`
and serves zero rows: a partial set compared against a manual upload is worse than no set. A
per-record mapping or validation failure is NOT such a fault. The record is EXCLUDED (listed in
`excludedRows` with a reason, counted in `excludedCount`) and the snapshot still reaches `ready`.
The live case that forced this: 10 ACTIVE db1 items have an empty `Description`, which maps to the
required `name`; under the draft rule those 10 records would have blocked the other 11,830 from
ever reaching a review page. `record_count` counts DELIVERED rows only; `excludedRows` is capped
at 500 entries with `excludedCount` carrying the true total. The consumer's reaction differs by
entity and only by entity: products are a non-destructive upsert, so exclusions never block
Confirm (Sorento lists them on the review page); stock zeroes absent pairs, so Sorento refuses
Confirm while any excluded row has `qty != 0`.

`content_hash` = sha256 over `json.dumps(row, sort_keys=True, separators=(",",":")) + "\n"` per
row in `row_index` order, computed over EXACTLY the stored `payload_json` that is later served
(AC-10-23). One fact that makes this reproducible and that the contract must state honestly:
`sink_payload()` runs `model_dump(mode="json")`, and pydantic v2 renders a `Decimal` as a JSON
**string** - verified against pydantic 2.13.4 in this repo (`Decimal("0") -> "0"`,
`0.0 -> "0.0"`, `Decimal("12.50") -> "12.50"`). So `list_price` / `cost_price` cross the wire as
strings, exactly as every other Decimal this module already sends, and by the time a value is
stored there is no `Decimal` left to serialize ambiguously - a consumer re-dump of the assembled
pages reproduces the bytes. The hash is a best-effort integrity check; the hard guards are
`recordCount`, `complete` and the `companyCode` echo.

### 2.5 The pull gateway (D8, D9, D10)

Routes mount as a module router with prefix `/api/v1/autocount` - the manifest `routers`
mechanism the omnichannel Service already uses for `/api/v1/omnichannel` (`manifest.json:125`),
so nothing new is invented at the loader level.

```
POST /api/v1/autocount/snapshots            {companyCode, entity}         -> 202 {snapshotId,...}
GET  /api/v1/autocount/snapshots/{id}                                     -> the header
GET  /api/v1/autocount/snapshots/{id}/rows?page=1&pageSize=1000           -> one page
```

**Auth.** `X-API-Key` (the header this module already uses toward Sorento, so both directions
match). The key pattern is the omnichannel one - scheme prefix, 8-char indexed lookup prefix,
sha256 hash, `hmac.compare_digest`, plaintext returned once, `last_used_at` stamped - but it is
REIMPLEMENTED module-locally in `ac_pull_api_key` + `services/pull_key_service.py`, not imported:
`WorkspaceApiKey` lives in the omnichannel schema and a cross-module table read is exactly what
the module-governance rule forbids (`PRINCIPLES.md`: cross-module refs are capability soft-refs,
never a join). That the pattern now exists twice is real duplication and is backlogged
(BL-SS-210) as a promotion to core rather than hidden.

**Tenancy is derived, never accepted.** Tenant id and the allowed company id set come from the
key row. `companyCode` is matched case-insensitively and trimmed against
`ac_company.sorento_company_code` WITHIN that tenant. Nothing in the request can name a tenant,
a tenant slug or a company id. A key of tenant A naming tenant B's company code gets the uniform
404 (AC-10-30).

**The error ladder** is AC-10-31 verbatim and is repeated in Appendix A for the consumer. It
exists because the consumer needs to say different things to its user: "bad key", "this book is
not enabled for pull", "this book is now automatic", "that extract expired", "extraction
failed".

**Audit.** Every call writes one `ac_pull_audit` row (key id, company, entity, snapshot, action,
page, record count, status code, timestamp). No payload, no debtor / customer field - the
module's own activity rule (`activity.py`) plus the owner's standing "no PII in logs" line.

**Throttle.** A new core throttle scope `pull` in `app/services/throttle.py` (mirroring the
`embed` / `webchat` scopes that modules already added there) records a failure per client IP on
every 401. Volume is bounded structurally instead: one `building` snapshot per (company, entity)
at a time, a 60 s build cooldown (429 + `Retry-After`), and page reads that are plain indexed
Postgres reads.

### 2.6 Operator surfaces (D11)

Everything is the Resource shell; nothing is hand-rolled.

- **Task editor, Schedule tab** - a two-segment `ToggleGroup` "Push" | "Pull on request" at the
  top. Pull HIDES the cadence controls (they do not apply) while keeping their saved values, so
  the flip back is lossless. A pull-only entity renders a read-only `StatusBadge` instead of a
  toggle (only offer valid options).
- **Task editor, Review & Activate tab** - the banner states what Activate means in the selected
  mode. The entities list gains a Delivery column (`StatusBadge`).
- **`/autocount/pull`** - a new page in the AutoCount sidebar section (menu entry tagged
  `module: 'autocount'` + `permission: 'autocount.pull.read'` in ALL THREE menu arrays of
  `config/menu.config.tsx`, lines ~415 / ~586 / ~743, so `filterMenu` hides it correctly).
  One `ResourceList` with an N-way segment `Keys | Snapshots` (rendered as `SearchSelect` per
  the shell rule; row selection clears on view switch). Issue key = a `ResourceForm` dialog
  (name + company `MultiSelect`); the plaintext key shows once with a copy control; Revoke =
  the CORE deferred-action grace window registered in `deferred_actions.py` beside
  `autocount_etl_task.repush` (never a hand-rolled confirm).
- **Snapshot detail** - header facts + the metadata blocks + the first page of rows in the
  EXISTING preview grid (`components/platform/autocount/{preview-panel,sql-preview-grid}.tsx`)
  reused with a prop, never a second grid.

Frontend layering is the house one: `types/autocount.ts` -> `services/autocount-service.
{ts,mock,real}.ts` -> `hooks/use-autocount-pull.ts` -> UI. The mock lands first and carries
every state (AC-10-48). Responsive at 375 and 1280 on every new surface.

### 2.7 Company identity: verified, and the one contradiction to fix

The brief assumed the pull `companyCode` is the operator-typed reference prefix in
`ac_company.database_name`. **That is not what this module sends.** `SorentoSink._body`
(`sinks_sorento.py:507-514`) sets `body["companyCode"] = self.company_code`, and the factory
(`sinks_sorento.py:1291-1316`, `services/company_service.py:796/848`) passes
`ac_company.sorento_company_code`. `database_name` is the REFERENCE PREFIX that qualifies
`source_ref` (`AED_SORENTO:SRT-01`) - a different string with a different job.

So the gateway resolves on `sorento_company_code`, and both directions agree by construction.
One wrinkle, and the one planner default worth the owner's attention:
`CompanyService.set_sink_target` CLEARS `sorento_company_code` when a company is switched to the
`logging` sink (deliberately - "a code left behind would silently anchor a later switch back at
a company nobody re-chose"). A pull-only company on the logging sink would therefore have no
identity. Taken: `sorento_company_code` is promoted to "the consumer company code", editable on
its own, REQUIRED to enable pull (AC-10-11), and cleared by `set_sink_target(logging)` only when
no entity on the company is pull-enabled. One conditional, one field, no new column.

### 2.8 Product identity: code wins (R8)

The 9,067 live `AED_SORENTO:<numeric>` product refs were never minted by a product master push -
the `SRT` Product task has never run. They came from SO/PO LINE ingest, where Sorento's document
resolver links a line's `product_ref` once the `product_code` rung hits. Their
`integration_references` is UNIQUE on `(entity_type, entity_id)`, so a second alias ref for the
same product is impossible, and today `MasterIngestService` raises `ReferenceConflict` (record
FAILED) when a ref misses but the code matches an already-linked product. An ItemCode-keyed `SRT`
pull against contract 2.3 would therefore fail roughly 9,067 records.

The owner's ruling is the simple one: **code wins.** Foundryx keeps `PRODUCT_HTTP_PRESET` exactly
as it is (`key_fields = ("ItemCode",)`) on BOTH books - no DB-source product variant, no `AutoKey`
scheme, nothing conditional per book. Sorento changes `MasterIngestService` for `products` only:
a ref miss whose code matches a product already linked under the same source system and company
UPDATES that product, keeps the existing ref, does not link the new one, and attaches a
`ref_mismatch` warning. That is the rule their document-line resolver already applies, so it is a
consistency fix on their side rather than a new concept.

Three consequences land here:

1. **A contract gate**, built by generalising the existing brand gate rather than cloning it
   (`services/company_service.py:820-872` + `sinks_sorento.BRAND_REQUIRED_CONTRACT_VERSION`):
   `PRODUCT_CODE_WINS_CONTRACT_VERSION = 2.4`, one generic `contractGate` field on the task view,
   one banner component. Activating a product task in PUSH mode against a `< 2.4` Sorento sink is
   REFUSED (not a logging-sink fallback like brand: the rows already exist on the consumer);
   PULL mode gets the banner only; a pull-only company on the logging sink gets the banner with
   `version: null`, because the gateway genuinely cannot see the consumer's contract. AC-10-69.
2. **The push parser needs no change.** `_result_for` keys on `outcome` alone and
   `_OUTCOME_DELIVERED = {"created", "updated"}`, and `warnings` is not read anywhere today - so
   `updated` + `warnings: ["ref_mismatch"]` already counts as delivered. AC-10-70 pins that and
   adds the one honest improvement: count the warning codes onto the run's activity so an operator
   can see them.
3. **Deletions carry the code.** Nothing on the delete path stores it (`_stage_deletes` writes a
   ref and no payload), but under R8 the ref IS `{prefix}:{ItemCode}`, so `codes[ref]` is
   recovered by splitting the ref once - no column, no migration. Guarded to single-key ItemCode
   tasks and contract `>= 2.4`. This ships in S3, the slice that owns the push flip, because a
   flip without it would send deletes the consumer cannot resolve for those 9,067 products.
   AC-10-72.

### 2.9 The push-flip checklist

Everything this plan deliberately withholds during the human-checked period, in one list, so the
flip to automatic is a checklist and not an archaeology exercise:

| # | Item | Why it is withheld now |
|---|---|---|
| 1 | Sorento contract `>= 2.4` live (products code-wins) | R8; AC-10-69 refuses push activation below it |
| 2 | `codes` on product deletions shipping | R8 item 3; a flip without it sends deletes the consumer cannot resolve for ~9,067 products |
| 3 | Sorento SR0 deployed | The 2.4 change itself, ahead of their SR1-SR4 |
| 4 | Enable the `uom_code` mapping row | R10: the manual template has no UOM column, so sending it during the check period would make every pulled product differ from a manual upload (AC-10-74) |
| 5 | Decide on `cost_price` | Never sent by either path today; there is no AutoCount source for it (BL-SS-213) |
| 6 | Stock only: Sorento contract `>= 2.5` (`stock_balances`) | D4/AC-10-15; that flip is slice S7 |

### 2.10 Security notes

The gateway is the second public surface this platform exposes and the first one carrying a
customer's ERP master data. The invariants, restated because they are the review gate:
tenancy from the key only; uniform 404 across tenants; keys hashed, shown once, never logged;
a suspended tenant or a deactivated module stops the gateway (`Status.blocks_access` /
`is_archived` + `ModuleRepository.is_active`, the same predicate `scheduler.sweep_etl_tasks`
already uses); no stored id resolved without its tenant scope (the recurring polymorphic-id
leak class); audit rows carry no payload. Snapshot ids are uuid4 and are additionally scoped to
the key's tenant and company set on every read - possession of an id is not authorisation.

S6 security round (AC-10-58), the five rulings that needed one:

- **Failed-header prose is fixed per code.** A gateway `failed` header's `error.message` is the
  ONE operator-safe sentence mapped from its `error_code`
  (`pull_gateway_service.GATEWAY_FAILED_MESSAGES`, generic fallback for an unmapped code), never
  the stored `snapshot.error` - that text names this deployment's own source host, port and
  endpoint path, and the gateway's reader is a third party. `error.code` is unchanged and stays
  the thing a consumer branches on (Appendix A6); the operator header and `integration_activity`
  keep the verbatim text.
- **Outbound egress guard on `baseUrl`.** An `autocount` connection's base URL is a stored,
  operator-supplied outbound target, so it runs through the house SSRF guard
  (`app/services/url_guard.assert_deliverable`, https-only, blocks private/loopback/link-local/
  reserved/multicast targets given as a literal OR resolved from a hostname) at SAVE
  (`AutoCountProvider.validate_config`, a 422 naming `baseUrl`) and again immediately before
  every request, at the two outbound chokepoints: `http_source.client.HttpApiClient.get` (the
  paged walk, every lookup and the preview sample all route through it) and
  `http_client.probe_open_connection` (the Test button and open-company onboarding). Re-checking
  at request time is the point - DNS can be re-pointed after a URL is accepted. ONE carve-out,
  the BL-SS-166 precedent shape (a `settings.environment == "development"` flag, never a
  request-controlled input): a LOOPBACK host (`localhost`, `127.0.0.0/8`) is allowed `http://` in
  development so a local wrapper still works for live-verify. The carve-out does not extend to
  any other private range, and a metadata address (`169.254.169.254`) stays refused even in
  development. **Review round confirm-3 (2026-09-20) - owner ruling:** stays HTTPS-ONLY outside
  that one carve-out (an earlier draft of this round briefly allowed `http://` on a genuinely
  public host, then reverted - see the decision log). `provider.py`'s two operator-facing
  messages ("The base URL must start with...") now say `https://` only, never advertising
  `http://` as an accepted scheme the wizard would then 422 anyway. Ops note: `ENVIRONMENT`
  defaults to `development`, so the loopback carve-out above is LIVE by default unless a
  deployment's `.env` sets `ENVIRONMENT=production` (same posture as BL-SS-166). See BL-SS-241
  (High): an existing `http://` AutoCount connection outside the dev carve-out fails EVERY walk
  after this change with a named error - count them in prod before deploying this branch.
- **In-tenant `COMPANY_NOT_ALLOWED` vs `UNKNOWN_COMPANY` is by design.** A key presented for a
  code that exists in its own tenant but is outside the key's company set answers 403
  `COMPANY_NOT_ALLOWED`, while a code that exists in no company of that tenant answers 404
  `UNKNOWN_COMPANY` - so a key holder can distinguish the two WITHIN the tenant it already
  authenticates to. Deliberate: the caller is a known consumer of that tenant's own books, the
  distinction is what makes a misconfigured key diagnosable rather than a support ticket, and
  the leak is bounded by the tenant it already holds a credential for. Across tenants there is
  no distinction at all (uniform 404), which is the boundary that matters.
- **XFF posture.** `settings.trust_proxy_headers` is FALSE by default, so `client_ip` reads the
  socket peer and every gateway caller behind the production reverse proxy shares ONE per-IP
  throttle bucket (the per-KEY budget, which is unaffected, is what actually bounds an
  individual consumer). Turning it on is safe only if Caddy OVERWRITES `X-Forwarded-For` rather
  than appending to a client-supplied value - otherwise a caller spoofs its way into a fresh
  bucket per request. Owner decision, not taken in this slice.
- **Pruning.** The retention sweep never deletes a `building` snapshot (a stale `expires_at` on a
  re-attached row must not tear down a live build), and `PullSnapshotRepository.delete` takes the
  owning `tenant_id` - the cross-tenant sweep still visits every tenant, one tenant-scoped delete
  at a time. The gateway's audit write on an error path is best-effort (an exception raised
  inside an `except` block escapes the whole `try`, which would turn a clean flat 403/404/429
  into an unhandled error); `last_used_at` is stamped only once the service gate passes, so a
  suspended tenant's key never records a call it was not served.

## 3. Files

Backend (`service_backend/modules/autocount/`):
`models.py` (`DELIVERY_MODE_PUSH/PULL`, `delivery_mode`, `AcPullSnapshot`, `AcPullSnapshotRow`,
`AcPullApiKey`, `AcPullAudit`, snapshot status constants, `RUN_MODE_SNAPSHOT`),
`http_source/lookups.py` (new: validate, ordered apply, multi-hop), `http_source/combine.py`
(new: validate, computed, require, group, round, drop, generic metadata), `http_source/source.py` (ordered lookup + reduce hooks in `fetch_changes`, no other
behaviour change), `http_source/preview.py` (`preview-columns` probe), `routers/http.py`
(`/preview-columns`), `http_source/client.py`
(`User-Agent`), `canonical/masters.py` (`ENTITY_STOCK_BALANCE`, `CanonicalStockBalance`),
`mapping.py` (`STOCK_BALANCE_PROFILE`, `ENTITY_PROFILES`), `mapping_catalog.py`
(`SORENTO_FIELDS` entry), `presets.py` (product `enrich` + the `BaseUOMPrice -> list_price` row carrying the R5 clamp
formula, `STOCK_BALANCE_HTTP_PRESET`), `services/etl_service.py` (`_validate_http_config` enrich/reduce
branches, `ETL_ENTITY_TYPES`, `set_delivery_mode`, activate/arm rules, preview enrich),
`services/pull_service.py` (new: build, header, page, the entity-name map, the error ladder),
`services/pull_key_service.py` (new), `repositories/autocount_repository.py`
(`PullSnapshotRepository`, `PullKeyRepository`, `PullAuditRepository`), `routers/pull.py` (new,
authed operator routes), `routers/pull_v1.py` (new, the public gateway), `pull_auth.py` (new,
the `X-API-Key` dependency), `sync.py` (delivery-mode gate on both auto-push branches,
`_run_pull_snapshot`, `register_pull_snapshot_handler`), `scheduler.py` (due-query filter),
`bootstrap.py` (register the new job handler + router + the tenant Admin grant sweep in
`update_tenant`), `backfill.py` (`backfill_delivery_mode_defaults`), `deferred_actions.py`
(key revoke), `activity.py` (one new operation constant), `manifest.json` (0.11.0, two router
entries), `permissions/permissions.csv` (two rows), `alembic/versions/
{0020_autocount_pull_snapshot,0021_autocount_pull_gateway}.py`.
Core: `app/services/throttle.py` + `app/config.py` (the `pull` scope and its two settings),
`app/workflow_engine/worker.py` (the prune beat entry + the job handler import).
Tests: `tests/test_autocount_lookups.py`, `..._combine.py`, `..._stock_balance.py`, `..._delivery_mode.py`,
`..._pull_snapshot.py`, `..._pull_gateway.py`, `..._pull_keys.py`, plus extensions to the
entity-parity and permission suites.

Frontend (`service_frontend/`): `types/autocount.ts`,
`services/autocount-service.{ts,mock,real}.ts`, `hooks/use-autocount-pull.ts`,
`app/(protected)/autocount/components/autocount-meta.ts` (permission keys, routes, delivery
labels, `AC_PULL_CAPABLE_ENTITY_TYPES`), `app/(protected)/autocount/companies/[id]/entities/
[entityType]/components/{schedule-tab,activate-tab,source-tab}.tsx` plus a
`lookups-editor.tsx` beside them (shell primitives only - `SearchSelect`, `ColumnChips`,
`DeferredActionButton`, `SqlPreviewGrid`),
`app/(protected)/autocount/companies/components/use-entities-list-config.tsx` (Delivery column),
`app/(protected)/autocount/pull/{page.tsx,loading.tsx,components/*}`,
`app/(protected)/autocount/pull/snapshots/[id]/{page.tsx,loading.tsx,components/*}`,
`config/menu.config.tsx` (three arrays), tests beside each.

Docs: this pair, `documentation/engineering/process-lessons.md` (AutoCount section: delivery
mode, enrich, reduce, snapshot, the two new Alembic ids), `documentation/engineering/
module-platform-and-app-store.md` (second public API-key gateway cross-reference), backlog rows.

## 4. Slices and order

| Slice | Scope | UAC |
|---|---|---|
| S0 | Lane + docs commit; Appendix A delivered to the Sorento peer session; recorded sample fixtures for their mock build under `10-fixtures/` (header + 10-row page per entity, one 409 body, one failed body) | AC-10-56 (send), 67 |
| S1 | **General lookups + list price on the existing PUSH path** - `http_source/lookups.py` (validate, ordered apply, multi-hop), the `preview-columns` probe, the ONE trim rule, the pre-filled product preset + the clamp and description-parity formula rows + the disabled `uom_code` row, `User-Agent`, bounded per-page retry. Independently shippable and logging-sink verifiable | AC-10-01..08, 54, 59..61, 71, 73..75 |
| S2 FE mock | Types, mock service, hooks, **the Source tab's Lookups editor** (add / remove / reorder, join pairs, aliases, per-lookup Test with matched / missed) **and its Combine rows editor** (computed, require, group-by, measures, carry, rounding, drop rules, funnel preview), delivery toggle on Schedule + Activate banner + Delivery column, `/autocount/pull` (Keys + Snapshots + detail), every state; agent-browser 375/1280 against the mock | AC-10-09, 09b, 16, 17, 38, 48, 49 |
| S3 BE | Delivery mode column + backfill + the three gates; the product contract gate (generalised from the brand gate) and `codes` on product deletions - both owned by the push flip; snapshot tables (`0020`), build job, set-failure vs per-record exclusion, header counters, content hash, TTL + prune beat, operator routes | AC-10-10..15, 18..26, 37, 46, 62, 63, 69, 70, 72 |
| S4 BE | Pull gateway (`0021`): keys, `X-API-Key` dependency, the error ladder (pinned failed-code set), paging, audit, throttle, cooldown, permissions + existing-tenant grant sweep. Curl-verifiable end to end | AC-10-27..36, 47, 64 |
| S5a BE | **The combine ENGINE, entity-agnostic**: config shape + save gate, computed / require / group / measure / carry / round / drop, generic metadata, key-fields-from-group-by and its draft-on-change rule | AC-10-76..81 |
| S5b BE | `stock_balance` itself: canonical, profile, the pre-filled preset (two lookups + combine), the entity-profile metadata map, pull-only rules, the stock-only Confirm rule, the live-numbers proof | AC-10-39..45, 65, 66, 84 |
| S6 | (S5a/S5b precede this.) **Precondition: Sorento's SR0 (contract 2.4, code-wins) is deployed before joint run 1 on `SRT`; `MCH` works without it.** Swap mock for real, prod build, recorded agent-browser runs, live replay on BOTH books with the logging sink (expect the `SRT` stock snapshot to DELIVER ~12,133 rows of which Sorento APPLIES ~6,500), failure replays, **joint run 1 (products, `SRT` then `MCH`, their SR3)** and **joint run 2 (stock, `SRT` then `MCH`, their SR4)** with the Sorento lane, fixture re-verification, test report, docs, backlog | AC-10-50..53, 55..58, 67, 68 |

Rules: S2 before any of the S3/S4 UI-facing backend (frontend-mock-first); S1's own frontend
piece is mock-first within the slice; S3..S5 are TDD red-green (tester's failing tests first);
every coder / tester brief embeds `PRINCIPLES.md` design mandates + the DoD gate + the hard-fail
list; reviewer (Opus) on S3+S4 combined and again at the merge gate; security-reviewer (Opus)
on S4 specifically - it is a new public surface over customer ERP data.

Deviation from the brief's suggested slicing, stated: the brief's "S2 snapshot store + pull
gateway" is split into S3 (store) and S4 (gateway) because the gateway carries the entire auth
surface and deserves its own security review gate, and an explicit FE-mock slice is inserted
ahead of both because PRINCIPLES mandates it.

## 5. Risks and answers

- **The consumer confirms a different set than it reviewed.** Impossible by construction: the
  snapshot is immutable, keyed, hashed and TTL'd; Confirm re-reads the SAME `snapshot_id` and
  refuses on expiry, count mismatch or `complete=false`.
- **A truncated stock set silently zeroes real inventory** (their import zeroes absent pairs).
  Any page failure fails the whole snapshot; `complete` is computed against the wrapper's echoed
  `TotalCount`, not trusted; a 0-row build against a previously non-zero snapshot is
  `EMPTY_EXTRACT`.
- **Enrich doubles the request count.** Products: 12 source pages + 12 enrich pages. Stock:
  69 + 12 + 12. The enrich endpoint is walked ONCE per run and indexed in memory (11.8k rows is
  nothing); the run's request count is visible on the Runs tab.
- **A price-only change never re-pushes.** Closed by putting the alias in the row hash
  (AC-10-06); this was the whole reason enrich merges onto the row instead of being applied at
  mapping time.
- **The 20 %/50-row delete guard fights the stock drop-zero rule.** Closed by not hashing at all
  in pull mode (`persist_hashes=False`): a pull is a full snapshot, never a diff.
- **Snapshot bloat.** 24 h TTL + newest-3 retention + an hourly bounded prune. Revisit object
  storage past ~100k rows per snapshot (BL-SS-212).
- **A `building` snapshot wedged forever** by a crashed worker: the module's existing
  `on_job_orphaned` hook is extended to the new job type, so the core orphan sweep closes it and
  the next build is not blocked.
- **`pageSize` clamp / page drift** (plan 08's lessons): the walk trusts the ECHOED values and
  guards a non-advancing page; both are inherited, not re-derived.
- **A vendor sentinel read as a price.** 121 active db1 items carry `Price -1.0`. Clamped to 0
  (R5) as an explicit mapping formula, counted in `negativeListPriceCount`, and raised with the
  API owner (BL-SS-215) - never silently dropped and never a rejected record.
- **10 items with an empty `Description`** (the required `name`). Excluded per record (R6), the
  snapshot still serves; the operator sees them on the snapshot detail and Sorento on its review
  page. Fixing them is ERP data entry, not a code change.
- **One item with `BaseUOM` `''`.** `uom_code` is `Optional` on `CanonicalProduct`, so the key is
  simply omitted by `sink_payload()` - not an exclusion and not a failure. The enrich join for
  that item finds no base-UOM row, so it also lands in `enrichMissCount` with no `list_price`.
- **Trimming a key changes identity.** It does not, on either side. Verified here:
  `flat_source_ref` builds every key part through `t_string` (`.strip()`), and so does every
  `string`-transform mapping row, so refs and codes are ALREADY trimmed today. Verified by the
  peer: Sorento strips every canonical string on ingest (`str_strip_whitespace`) including
  `source_ref`, prod holds zero untrimmed product or warehouse codes, and their stock matcher
  strips, then matches exact, then case-insensitively. The trim rule is therefore scoped to the
  raw dict lookups only (enrich index, reducer grouping) and is NOT written back onto the row, so
  `row_hash` is untouched and no re-push wave occurs. AC-10-60.
- **Product identity risks, owner-accepted (R8), recorded verbatim:** an `ItemCode` rename in
  AutoCount creates a NEW product in Sorento and leaves the old one behind (the same behaviour as
  the manual Excel flow); code REUSE updates the old product; the roughly 9,067 already-linked
  products carry `ref_mismatch` forever; and a later document line carrying an `AutoKey`
  `product_ref` for a code-linked product resolves by code with `ref_mismatch` (today's
  behaviour).
- **Ref case vs code case (peer note, 2026-09-19).** Sorento's `source_ref` uniqueness is
  exact-case while its `product_code` match is case / whitespace-insensitive. An `ItemCode`
  CASING edit in AutoCount (`abc-1` -> `ABC-1`) changes our ref, misses on their side, hits the
  code rung and updates the same product with `ref_mismatch`, keeping the old ref. Harmless, but
  that product then lives on the code rung permanently. **Never casefold the ref on this side to
  "fix" it** - refs already stored would then miss.
- **New AutoCount items during the check period.** Documents stay on auto-push while products are
  human-pulled, and Sorento's document resolver has no back-create for products: a SO/PO line for
  an item Sorento does not hold yet is DROPPED (the document still lands, `lines.dropped` counted)
  until someone Confirms a product pull; the next push of that document lands the line by code.
  This is the same exposure as today (new items arrive only when the item Excel is uploaded), so
  parity - but the product pull is what unblocks those lines, which is one more reason the
  products flip to push should not wait long after the check days.
- **Stock scope and warehouse coverage.** Closed by R7: Foundryx ships every positive pair, the
  consumer filters on its own active flag. S5 is not gated.
- **The `db2` (Mocha) wrapper is roughly 0.2 s PER ROW and Cloudflare cuts at about 100 s.**
  Measured 2026-09-19/20: `pageSize=1000` -> 524 after about 125 s on 9 of 9 attempts (pages 1-3),
  page 4 (445 rows) -> 200 in 66 s, `pageSize=100` -> 22 s, `pageSize=300` -> 65 s; db1 the same
  night served `pageSize=1000` in 21 s. Largest safe db2 page is about 400 rows. Plan 08's db2
  smoke on 2026-09-12 walked 4 pages of 1000 cleanly, so this is new or intermittent - unknown.
  Against today's client (ONE 30 s attempt, no retry) every db2 page over about 130 rows would
  fail. Three answers, none of them a guess: the page size and request timeout become
  per-CONNECTION settings (AC-10-85, default 90 s to stay under the cut); a page that times out
  twice HALVES the page size for the rest of the run and restarts the walk (AC-10-75); and the
  build job is allowed to take as long as it takes, bounded only by the heartbeat liveness sweep
  (AC-10-86). The vendor-side cause is not ours to fix - BL-SS-219 carries the measurements for
  the owner to raise with the wrapper vendor.
- **Lookups re-walk their endpoint on every run**, which roughly doubles the request cost on a
  slow book (a Mocha product run is about 3,438 item rows plus about 3,438 ItemUOM rows, roughly
  25 minutes at the measured rate). Lookup endpoints obey the same page size, timeout and retry
  settings as the main path, so a connection tuned for a slow book tunes both halves at once. A
  per-run lookup cache across tasks is NOT built here (it would need an invalidation story for
  one saved request).
- **Manual-upload parity is the thing that can silently rot.** Both sides derive
  `is_discontinued` and L/W/H from the DESCRIPTION TEXT, so a well-meant "tidy the description"
  change on either side (collapsing the double space that 2,786 live rows carry, trimming inside
  the join) silently flips product flags and dimensions. R10 makes it a gate: the description
  join is a visible formula here (AC-10-73), Sorento runs a parity pytest feeding the same items
  through both paths, and joint run 1 has an explainable-diff exit criterion.
- **A configurable combine step is a foot-gun aimed at real inventory.** A wrong group-by or a
  deleted drop rule changes what the consumer zeroes. Mitigations, all already in the design: the
  step is bounded (one per task, no joins, no nested grouping, capped lists); every expression
  goes through the save-time parse gate; the group-by IS the key, so a change sends the task back
  to `draft` and forces a re-Test before it can run; the Test funnel shows rows in / excluded /
  dropped / out before anything is saved; and for stock the consumer still refuses a Confirm on
  `excludedNonzeroCount > 0` or `complete: false`.
- **Stock push is a planned follow-up, not a dead end.** `stock_balance` is pull-only for now
  because Sorento has no ingest entity for it; the SAME contract gate that opens products at 2.4
  opens stock at 2.5 (S7, BL-SS-207). Nothing about the reducer, the preset or the lookups has to
  change for that flip.
- **`BalQty` appears to be GROSS of consignment.** The macro's "On Hand" is `Balance + CSGN`, and
  `CSGN` is nonzero only in `CON`, `HQ` and `DISPLAY` - none of which is active in Sorento today,
  so the difference is invisible for now. **Re-open this before any of those three warehouses is
  activated**, or the pulled quantity for them will disagree with the manual workbook.
- **7 stock-bearing locations are missing from Sorento entirely** (155 pairs, `BRW-VAR` 142 of
  them). Those rows ship and are listed by Sorento as unknown-location "not applied". Whether the
  warehouse master push should have created them is a separate completeness question
  (BL-SS-217).
- **Cloudflare UA blocking**: the wrapper 403s the default python-urllib UA. An explicit honest
  `User-Agent` is now pinned (AC-10-08) instead of depending on httpx's default.
- **Key sprawl.** Keys are scoped to company IDs (immutable) not codes (mutable), revocable with
  a grace window, hashed, audited, and rate-limited.
- **Two API-key implementations in one repo.** Acknowledged, backlogged (BL-SS-210); the module
  isolation rule forbids the shortcut of reading omnichannel's table.

## 6. Backlog

- **BL-SS-241 (High)** - **An existing `http://` AutoCount connection fails EVERY walk after
  this change, outside the development loopback carve-out.** Review round confirm-3's owner
  ruling (section 2.10, D34) keeps the egress guard https-only; `provider.py`'s messages now say
  so plainly, but a connection SAVED before this branch with a plain `http://` `baseUrl` (the
  save-time scheme check predates the guard's own https requirement and never fully enforced it)
  will 422 with a named `baseUrl` error on its next preview/walk. Count existing `autocount`
  connections with an `http://` `baseUrl` in production before deploying this branch; migrate
  each to `https://` (a reverse proxy / tunnel in front of the AutoCount wrapper) or accept the
  entity goes dark until migrated.
- **BL-SS-240** - **An existing `autocount` connection is re-validated by the egress guard at
  REQUEST time, not only at save** (pre-existing behaviour, unchanged by this round -
  `assert_autocount_base_url_deliverable` re-runs the SAME https-only + target check before
  every request, not only at save). `ENVIRONMENT` defaults to `development` (the loopback
  carve-out is live unless a deployment's `.env` explicitly sets `ENVIRONMENT=production`, same
  posture as BL-SS-166), so an operator whose wrapper's `baseUrl` resolves to a private range (or,
  per BL-SS-241 above, is plain `http://`) outside development fails with a NAMED error
  (`baseUrl: ...`) on the next request, not a silent skip - an ops note, not a defect, but worth
  surfacing so a deploy that forgets to set `ENVIRONMENT=production` does not mistake a passing
  loopback connection for a validated one. Review round confirm-3 (2026-09-20).
- **BL-SS-222** - **Preview matched/missed counts are a 50-row SAMPLE.**
  `POST /autocount/http/preview`'s per-lookup `{alias, matched, missed}` (AC-10-05) is computed
  over `PREVIEW_PAGE_SIZE` (50) rows of the main endpoint and the SAME cap on the lookup endpoint
  (review round 1 should-fix 8) - never the full population. The S2 editor must label these as
  sample counts, not "the" matched/missed totals, or an operator will misread a 2/50 miss rate as
  the whole task's enrich-miss rate. The preview lookup PROBE itself (unlike a real run's
  `_walk_endpoint`) walks PAGE 1 only, capped, never the whole lookup endpoint - so a match that
  sits on the lookup's page 2 (or beyond) reads as a miss at preview time even though the SAME row
  would match at run time, when the full page walk runs. Sample matched counts under-report for
  this reason too, not only the 50-row main-page sample size.
- **BL-SS-221** - **An operator formula naming a lookup alias fails to parse (not just "returns
  null") on a row that MISSED the lookup**, because the miss leaves the alias key ABSENT
  (AC-10-02) and `evaluate_formula`'s own `known_variables` gate is derived from the CURRENT row's
  raw dict keys (`_header_facts` = `dict(raw)`) - a formula referencing an absent name cannot even
  parse, which fails that ONE record (visible as `STAGED_FAILED` / an excluded row, review round 1
  finding while diagnosing a `test_autocount_http_lifecycle.py` regression whose OWN cause was
  unrelated - a missing raw `Desc2` key, not a lookup miss - but the SAME mechanism). No shipped
  preset does this today (the clamp formula's own source, `BaseUOMPrice`, sits on the SAME row the
  lookup wrote it onto, never referenced from a DIFFERENT row's formula). Consider an
  alias-aware `known_variables` (treat a configured lookup alias as always-known, defaulting to
  absent/None when missed) before an operator-authored formula ever names one.
- **BL-SS-220** - **AC-10-75's halving budget is PER ENDPOINT WALK, not shared per run.** Each of
  the main path and every lookup gets its OWN independent "at most two halvings" budget
  (`http_source/source.py`'s `_walk_endpoint`), so a task with the maximum 5 lookups plus the main
  path could in the worst case halve 6 times across one run (2 halvings x 6 endpoints) before the
  existing failure rule applies to any ONE of them. The plan's own text left "per run" ambiguous
  between "one `fetch_changes` call" and "one endpoint walk"; taken as per-endpoint-walk since no
  AC-10-75 test forced a shared reading and a shared counter would let a slow lookup exhaust the
  main path's own retry budget. Revisit if a slow book's worst-case build time needs a tighter
  cross-endpoint bound.
- **BL-SS-219** - **Vendor-side db2 (Mocha) wrapper performance.** Measured 2026-09-19/20:
  roughly 0.2 s per row against about 0.02 s on db1, with Cloudflare 524-ing any request past
  about 100 s (`pageSize=1000` failed 9 of 9 attempts at about 125 s; 100 rows took 22 s, 300 rows
  65 s, a 445-row page 66 s). Owner to raise these numbers with the wrapper vendor. Until then
  this plan works around it (AC-10-75/85/86) at the cost of a roughly 25-minute Mocha product
  build. Mocha stock has not been measured and could be far worse.
- **BL-SS-218** - Optional one-time rekey of the roughly 9,067 `AED_SORENTO:<AutoKey>` product
  refs to `<prefix>:<ItemCode>`, which would clear the permanent `ref_mismatch` warning on those
  rows. Owner-accepted as-is for now (R8 risk list); revisit only if the warning noise becomes a
  problem on Sorento's review pages.
- **BL-SS-207** - **PLANNED follow-up slice S7**, after the human-checked period and gated on
  Sorento's SR5: the `stock_balances` ingest entity (contract **2.5**, moved from 2.4 when 2.4 was
  taken by R8's products code-wins change) and the Foundryx flip of stock from pull to auto-push.
  Deliberately OUT of this plan's Definition of Done - the gate (AC-10-15) is what opens it, and
  no reducer, preset or lookup has to change. Links BL-SS-041, BL-SS-203.
- **BL-SS-208** - **Pulled into scope by owner ruling R9** (operator-authored lookups). Kept as a
  row only so the id is not reused; the work is in slices S1 and S2 of this plan.
- **BL-SS-209** - **Pulled into scope by owner ruling R11** (the general "Combine rows" step).
  Kept as a row only so the id is not reused; the work is in slices S2 (editor) and S5a (engine).
- **BL-SS-210** - Promote the API-key issue / resolve pattern to core. It now exists twice
  (`omnichannel.WorkspaceApiKey`, `autocount.AcPullApiKey`) with the same security invariants
  and two copies of the hashing / compare code.
- **BL-SS-211** - The remaining new wrapper endpoints (`/creditorbypage`, `/salesagent`,
  `/taxcode`, `/terms`, `ItemType` / `ItemCategory` / `ItemClass`) are OUT of this plan.
  Extends BL-SS-203.
- **BL-SS-212** - Snapshot rows in Postgres vs object storage. Fine at 12k-70k rows; revisit if
  a customer's set grows past ~100k rows per snapshot.
- **BL-SS-213** - `CanonicalProduct.cost_price` still has no wrapper source (the wrapper exposes
  `Price` only). It is declared, never populated. Ask the API owner or drop the field.
- **BL-SS-217** - Warehouse push completeness: 7 stock-bearing AutoCount locations have no
  Sorento warehouse at all (155 pairs; `BRW-VAR` alone is 142). Decide whether the warehouse
  master task should be creating them (and whether `Location.IsActive` should drive
  `warehouses.is_active` on push) or whether their absence is deliberate. Blocks nothing today -
  R7 means those rows ship and Sorento lists them as not applied.
- **BL-SS-215** - Ask the wrapper's API owner about the `-1.0` `ItemUOM.Price` sentinel on 121
  active db1 items: is it "no price" or a real value? Until answered, R5's clamp to 0 is the
  agreed parity behaviour and the count is reported on every snapshot.
- **BL-SS-216** - **CLOSED before it opened** (peer + code verification 2026-09-19): no
  cross-repo `source_ref` normalisation is needed for the 20 whitespace `ItemCode`s.
  `flat_source_ref` already strips on this side and Sorento strips every canonical string on
  ingest, so the refs already agree. Kept as a row only so the question is not re-asked.
- **BL-SS-214** - Server-side filtering on `/itembatchbalqtybypage` (the walk reads 68,612 rows
  to emit ~12k). Extends BL-SS-204 (the same ask for `LastModified`).
- **BL-SS-041 / BL-SS-203** (existing) - update the rows to note that stock balance now has a
  Foundryx-side canonical entity and a pull path, and that only the Sorento ingest half remains.

**S6 docs pass (2026-09-20) - new deferrals found while writing the Test Execution Report /
Appendix A6 verification, minted BL-SS-223..239 so this register and `backlog.md` agree:**

- **BL-SS-223** - pre-existing vitest failure, `services/autocount-service.test.ts` (S2's
  `normalizeEtlTask` overlay, `d83a0d1e`, throws on a stub task with no `sourceConfig`).
- **BL-SS-224** - pre-existing vitest failure, `components/ui/pressed-class.inventory.test.ts`
  (two un-allowlisted webchat-panel buttons, unrelated to autocount).
- **BL-SS-225** - combine `excludedRows` carries only `{<groupBy cols>, measure, reason,
  message?}` - no per-entity extra column (e.g. stock's own `uom`).
- **BL-SS-226** - sample-type checks (boolean require/drop, numeric measure ops) run only inside
  `preview_http`; Test clean -> edit formula -> Save never re-checks.
- **BL-SS-227** - `ac_pull_api_key.last_used_at` commits on every successful gateway call,
  uncoalesced.
- **BL-SS-228** - the operator pull routes' header shape (`id`/`entityType`/`companyId`) differs
  from the gateway's Appendix A3 shape (`snapshotId`/`entity`/`companyCode`) by design - worth a
  doc note so it does not read as drift.
- **BL-SS-229** - the Pull page's N-way segment reads `query.segment` as a fetcher-side channel
  rather than a dedicated shell callback - the first list config to do this; generalise or
  document before a second config copies it.
- **BL-SS-230** - a pull snapshot build has no incremental "row ready" signal, only a per-page
  liveness heartbeat - the whole snapshot must finish before any row is servable.
- **BL-SS-231** - snapshot TTL (24 h) and audit retention (90 days) are module constants, not
  `app/config.py` settings.
- **BL-SS-232** - the `autocount_pull_snapshot` background job has no cooperative-cancellation
  checkpoints.
- **BL-SS-233** - `mockAutocountService.previewHttp` (PHASE 1 MOCK) applies no lookups at all.
- **BL-SS-234** - the frontend `HTTP_PRESETS` table has no VALUE drift guard against the
  backend's `presets.py::HTTP_PRESETS` (only the entity-type key set is parity-pinned).
- **BL-SS-235** - the Companies > Entities list's row click only selects (`rowHref: () => '#'`);
  Configure is reached only via the Actions menu - confirm as deliberate or wire `rowHref`.
- **BL-SS-236** - the operator `PullSnapshotOut` schema carries no `progress` hint; AC-10-87
  landed on the public gateway header only.
- **BL-SS-237** - the core 10 s destructive deferred-action grace window keeps a "revoked" pull
  API key live (still resolves/authenticates) for up to 10 more seconds after Revoke is clicked -
  the core pattern working as designed (AC-10-38), flagged because a live credential during the
  window is a different risk class than a soft-deleted list row.
- **BL-SS-238** - pre-existing push-path re-staging defect (NOT plan-10 code): an HTTP product
  task with `watermarkField: null` re-stages every record on every run (`ac_staged_record` grows
  roughly 5,000/run, capped by BL-SS-092); found live during this plan's db1 replay, verified by
  the Opus reviewer against `c1c5906a`, recorded per the PR #70 comment.
- **BL-SS-239** - HIGH, pre-existing, separate from plan 10: `EtlSourceConfigIn` declares no
  `fingerprintQuery` field, so `validate_source_config` always reads it as absent and (unlike
  `combine`'s explicit `model_fields_set` guard) has no keep-if-absent branch - ANY operator save
  of a document task silently wipes `fingerprintQuery` and disables the line-fingerprint sweep.
  File as a GitHub issue.

## 7. Decision log

| # | Decision | Why |
|---|---|---|
| D1 | Delivery mode is a `delivery_mode` column on the existing `ac_entity_config` task row (`push` default) | Owner: activate per company book AND per entity; the task row already IS that pair. No new table, every existing task keeps today's behaviour |
| D2 (owner approved 2026-09-19) | A `pull` task does NOT run on the 60 s sweep; a consumer request (or an operator) builds a snapshot on demand | 24 h TTL + Confirm-re-reads-the-same-id makes pre-built snapshots churn; the owner's flow is a button; a scheduled pull reads a customer ERP with no consumer |
| D3 | **Owner ruling R9 (changed from the draft).** Lookups are a GENERAL, operator-configurable, ordered list on ANY API task - N endpoints, N join pairs, operator-named aliases, multi-hop by evaluation order - and the product preset merely ships one pre-filled. Values MERGE onto the source row before de-dup / hash / mapping | Owner: "how can this be more general and applicable for future possible similar use case". A preset-only block would have to be re-opened for the next field and the next endpoint. Aliases stay ordinary columns, so the operator sees where `list_price` comes from and a price-only change is still detectable (row hash). BL-SS-208 pulled into scope |
| D4 | **Reworded on owner markup.** `stock_balance` is pull-only **for now**: the Push option is HIDDEN behind the same contract gate as products (`stock_balances` at contract 2.5), not forbidden forever, and opens with no code change once Sorento serves it (planned S7, BL-SS-207) | Owner: "it will have push mechanism also once pull is stabilized". Today `push` would be a configuration guaranteed to fail, which is a gate, not a law |
| D5 | **Owner ruling R11 (changed from the draft).** The collapse is NOT a named reducer: "Combine rows" is a general, operator-configurable step on ANY API task - computed columns, require rules, group-by with measures and carried columns, per-measure rounding, ordered drop rules - bounded (one per task, no joins, no nested grouping, capped lists) and expressed entirely in the EXISTING formula engine. The stock preset ships pre-filled; the generic metadata is mapped to the agreed stock wire names by the entity profile | Owner: "I prefer it to be more configurable and general for future use case". The danger of a wrong group-by is answered by bounds, the save-time parse gate, key-change-forces-draft, the Test funnel and the consumer's own Confirm guard - not by hiding the knob. BL-SS-209 pulled into scope |
| D6 (owner approved 2026-09-19) | A pull run writes a SNAPSHOT only - no staging, no row hashes, no watermark, no delete intents | A pull is a full set every time; diffing fights the drop-zero rule and would trip the delete guard every run |
| D7 | Set-level failure ONLY for source page / enrich / row cap / empty extract; a per-record mapping or validation failure is an EXCLUDED ROW on a `ready` snapshot (R6, revised 2026-09-19) | A partial set is worse than no set, but 10 items with a blank `Description` must not block 11,830 good ones from reaching a review page. Products upsert non-destructively, so exclusions cannot harm; stock's own strict rule stays on the consumer side |
| D15 | Negative `list_price` is clamped to 0 by the preset mapping row's FORMULA `if(number(value) < 0, 0, number(value))`, not by the canonical model (R5) | 121 active db1 items carry the `-1.0` sentinel and `list_price` is `ge=0`. The operator must be able to SEE and edit the rule; the Mapping tab, its formula builder and its simulator already exist. One mapper means the push path gets it too |
| D16 (owner approved 2026-09-19) | Snapshot header carries `excludedCount` + `excludedRows[]` for BOTH entities and `negativeListPriceCount` for products; `zeroListPriceCount` is POST-clamp | The consumer needs to show its user exactly what did not come through, and two counters that could be read as overlapping must have one stated definition |
| D22 | Manual-upload parity is enforced as a GATE (visible description formula here + a two-path parity pytest on Sorento + an explainable-diff exit criterion on joint run 1), and `uom_code` is withheld until the push flip (R10) | Owner: pull must behave exactly like the manual Excel upload. Both paths derive `is_discontinued` and L/W/H from the description text, so parity is won by sending the right description - not by a second code path (R1 stands). Inner whitespace is never collapsed: 2,786 live rows carry a double space because the Excel path joins raw |
| D19 | Products are keyed `<prefix>:<ItemCode>` on both books; Sorento makes CODE WIN for `products` (contract 2.4) rather than Foundryx adopting the AutoKey refs (R8) | The 9,067 numeric refs came from LINE ingest, not a master push, and their `integration_references` cannot hold an alias. Keying on AutoKey would need a DB-source product variant per book and would still leave MCH (zero refs) different. One key, one preset, one rule |
| D20 (owner approved 2026-09-19) | The product contract gate REFUSES push activation below 2.4 (unlike the brand gate's logging-sink fallback), warns in pull mode, and warns with `version: null` when there is no Sorento connection to probe | Brand had no rows on the consumer to damage; products have roughly 9,067. Never let the UI be configured into a certain runtime error, and never guess a contract we cannot see |
| D21 (owner approved 2026-09-19) | `codes` on product deletions is DERIVED from the ref (`{prefix}:{ItemCode}`), single-key-guarded, shipped in S3 | R8 makes the ref code-bearing, so no column, no migration and no backfill are needed - and the push flip is unsafe without it |
| D18 | Stock: Foundryx is a FAITHFUL source (quantity cut only); the active-location filter lives on the consumer, which lists "not applied" rows (R7) | The macro workbook's filter is a LOCATION list that Sorento's `warehouses.is_active` already mirrors. A copy of it here would be a second source of truth that drifts the first time a warehouse is activated - and AutoCount's own `IsActive` is a different list that cannot stand in for it |
| D17 | The trim rule is scoped to the raw dict LOOKUPS (enrich index, stock grouping) and is never written back onto the row; identity and `code` need no change (revised 2026-09-19) | Verified: `flat_source_ref` and every `string` transform already `.strip()`, and Sorento strips canonical strings on ingest - so there is no ref hazard and no carve-out to make. Not writing back keeps `row_hash` stable, so no one-time re-push wave |
| D8 (owner approved 2026-09-19) | Public gateway at `/api/v1/autocount/*`, `X-API-Key`, key-derived tenancy, uniform 404 across tenants | Mirrors the omnichannel gateway precedent at the loader level and the module's own outbound header choice |
| D9 (owner approved 2026-09-19) | The API-key pattern is re-implemented module-locally, not imported from omnichannel | Cross-module table reads are forbidden (capability soft-refs only). Duplication is acknowledged in BL-SS-210 |
| D10 | Wire casing: camelCase envelope / metadata keys, snake_case ROW keys | `companyCode` is already what this module sends; product rows are `sink_payload()` byte for byte (locked: "EXACTLY as pushed today"). Stated in Appendix A so the Sorento session corrects in one place |
| D11 (owner approved 2026-09-19) | Operator surfaces are the Resource shell: delivery toggle on the Schedule tab, one `/autocount/pull` page with a Keys / Snapshots segment, existing preview grid reused for rows | No hand-rolled tables or forms; extend with a prop, never a parallel component |
| D12 | The gateway's company identity is `ac_company.sorento_company_code` (VERIFIED in `sinks_sorento.py`), NOT `database_name` | Both directions must agree; `database_name` is the ref prefix for `source_ref`, a different string |
| D13 (owner approved 2026-09-19) | `sorento_company_code` is required to enable pull and is no longer cleared by a switch to the logging sink while any entity is pull-enabled | A pull-only company on the logging sink would otherwise lose its identity |
| D14 (owner approved 2026-09-19) | Lane s40, :8009/:3009, DB `foundryx_service_s40` | s37-s39 held by earlier sprint-5 lanes |
| D23 (review round 1b) | Raw-only `result_columns`, aliases derived at read - closes review-1 blocker 2 without a carve-out | An HTTP task's stored `result_columns` holds the RAW main-endpoint columns ONLY; every consumer that needs an operator alias too (the wire `resultColumns`, the compared-column baseline, mapping-row formula validation, key/watermark validation) derives it through one helper (`effective_result_columns` = stored raw + the configured lookups' `fields[].as`, in order). The save-time collision check then compares an alias against a set that can NEVER legitimately contain it, so no carve-out (previously-saved lookups, registered presets) is needed at all - closing the false-422 a carve-out reopened for a brand-new, first-time-saved lookup (R9's whole point). An alias may never be a KEY or WATERMARK field (a miss leaves it absent) |
| D24 (S6 docs pass, verified in code) | The preview/Source pickers offer TWO distinct column sets, never one flat list: `resultColumns` (stored raw + lookup aliases, `EtlSourceConfigIn`/`effective_result_columns`) for key/watermark/mapping picks vs `combineOutputColumns`/`preCombineColumns` (`schemas.py:863/907`) for the COMBINE output schema once a task has one | A combine-carrying task's mapping tab must see the POST-group shape (group-by + carry + measure aliases), while key/watermark pickers must still see the PRE-group raw/lookup names - collapsing the two into one set would offer either the wrong picks or the wrong mapping targets |
| D25 (owner ruling R11, verified `formula.py:1229-1246`) | A `require`/`drop` combine formula that does not evaluate to a real boolean is a fail-closed `FormulaRuntimeError`, via the SAME `to_bool_strict` `not`/`and`/`or`/`if` already use - never a second, more permissive boolean dialect | Review round 3 finding: a non-empty-string result previously coerced to `True` unconditionally; foolproof-UI requires the SAME strict rule everywhere a formula is asked for true/false, not a locally-invented one for combine |
| D26 (review round 4, SF-3) | `BUILD_ABANDONED` and `COMBINE_RULE_FAILED` are kept as ADDITIVE members of the ONE pinned failed-status code set (`sync.py::PULL_SNAPSHOT_FAILED_CODES`), never folded onto `SOURCE_PAGE_FAILED` | An orphan-reclaimed build and a runtime-raising drop rule are diagnostically distinct failures a consumer's error switch should be able to tell apart, even though both are terminal |
| D27 (verified `http_source/combine.py:407/690/974`) | `combine.measure` is OPTIONAL (`combine.get("measure")`, never a required key) | Not every combine-carrying task needs a measure column (e.g. a pure dedup/require reduction with no numeric aggregate); requiring one would force a dummy column on tasks that have nothing to sum |
| D28 (S5b review round 5, coordinator ruling) | ONE `excludedRows` entry shape per combine-carrying task, regardless of which STAGE excluded the row - a mapping-stage exclusion is normalised to the SAME `{<groupBy cols>, measure, reason: "mapping_failed", message}` shape a combine-stage exclusion already carries, rather than the generic per-record `{source_ref, code, reason, message}` shape a non-combine task keeps | So a consumer's `excludedNonzeroCount` guard (A5) reads every exclusion uniformly without branching on which stage produced it |
| D29 (router `companies.py:632-642`, R9/R11) | An explicit `"combine": null` on the wire CLEARS the stored combine block; an OMITTED `combine` key KEEPS whatever is stored. A cleared combine is never automatically re-seeded from the entity's preset on a later save | `model_dump()` cannot distinguish "sent null" from "never sent" once flattened to a plain dict - the router drops the key from `raw` entirely unless `model_fields_set` shows the client actually sent it, so the service layer's `"combine" in raw` check can tell the two apart. Re-seeding on every save would silently resurrect a combine block an operator deliberately turned off (S5b confirm B-2, `0c6df8a9`) |
| D30 (verified `presets.py:860-886`) | The stock preset SHIPS a pre-filled `combine` block (`STOCK_BALANCE_HTTP_PRESET`), and the entity's `keyFields` are DERIVED from `combine.groupBy` at save time rather than hand-configured | A stock row's real identity is the post-group (item, location) pair, not any pre-group raw column - deriving it keeps one source of truth instead of an operator having to keep two settings in sync |
| D31 (`tests/test_s10_s5b_live_numbers.py:16-81`) | Live-probe captures for the S5b test suite are stored OUTSIDE git, resolved via `AUTOCOUNT_PROBE_DIR` with a stable fallback copy, never committed raw vendor data | The captures carry real db1/db2 field values; keeping them out of the repo (env override for a fresh capture, a checked-in "stable" summary only) avoids committing a customer's live ERP data under a test fixture |
| D32 (verified `combine-editor.tsx:115-155`) | Each combine formula stage gets its OWN variable scope from the `AutocountFormulaBuilder`, never one flat list for every stage: `computed[i]` sees raw/lookup columns + EARLIER computed aliases only (a forward reference is the save-time 422); `require[i]` sees raw/lookup + ALL computed aliases (require runs after every computed step); `drop[i]` runs AFTER grouping and sees ONLY `groupBy` + `carry` + `measures[].alias` | S5b-FE defect 1: a formula that could reference a not-yet-computed alias, or a pre-group raw column after grouping, would parse in the editor and then 422 (or silently read `null`) at save/run time - scoping the picker per stage closes both classes at author time |
| D33 (verified `canonical/masters.py:339-354`) | `CanonicalStockBalance` extends `CanonicalRecord` directly, deliberately NOT `CanonicalMaster` | It carries none of `CanonicalMaster`'s push-oriented shape (`code`/`name`/`is_active`/`last_modified`/`extras`) and is pull-only (AC-10-15, no `sinks_sorento._ENTITY_PATH` entry); subclassing `CanonicalMaster` would also silently enrol it in the contract-2.1 master-parity suite, which is keyed off `CanonicalMaster` subclasses |
| D34 (owner ruling, review round confirm-3, 2026-09-20, OVERRIDES this round's own first draft) | The AutoCount `baseUrl` egress guard stays HTTPS-ONLY outside the one development loopback carve-out - a draft of this same round briefly widened `assert_autocount_base_url_deliverable` to accept `http://` on any resolvable public host (matching `provider.py`'s pre-existing, contradictory "http:// or https://" copy) and was reverted before merge. `provider.py`'s two operator-facing messages were corrected the OTHER way instead - both now say "must start with https://" | Owner: keep the tighter posture; an operator's genuinely plain-http wrapper is a migrate-to-https-or-tunnel problem, not a guard-widening one. BL-SS-241 (High) tracks the ops consequence for any existing `http://` connection |

## Appendix A - the cross-repo contract (for the Sorento `autocount` peer session)

Self-contained. Correct anything that disagrees with Sorento's own code and reply with the
corrections; this side has not written code yet.

### A1. Wire conventions (AGREED with the Sorento peer, 2026-09-19)

The earlier draft of this contract used snake_case header keys (`snapshot_id`, `record_count`,
`content_hash`, ...). **Final ruling: envelope and metadata keys are camelCase; ROW object keys
are snake_case.** Reasons: Foundryx already sends `companyCode` as the top-level key on every
ingest / read / delete call to Sorento, and the product row must be `CanonicalProduct.
sink_payload()` byte for byte (locked: zero contract change for products), which is snake_case.
Mapping from the earlier draft: `snapshot_id -> snapshotId`, `record_count -> recordCount`,
`content_hash -> contentHash`, `extracted_at -> extractedAt`, `expires_at -> expiresAt`,
`zero_pairs -> zeroPairs`, `negative_pairs -> negativePairs`,
`negative_pair_list -> negativePairList`, `excluded_rows -> excludedRows`,
`page_size -> pageSize`, `total_pages -> totalPages`. `complete` and `entity` are unchanged.
Objects INSIDE `negativePairList` / `excludedRows` are row-shaped and therefore snake_case.

### A2. Auth and company identity

- Header `X-API-Key: fxa_live_...`, issued by the Foundryx operator per tenant, bound to an
  explicit set of companies. Store it as a secret on your side; it is shown once.
- `companyCode` is the SAME string Foundryx already sends as the top-level `companyCode` on
  push. Verified in Foundryx code: it is `ac_company.sorento_company_code`
  (`sinks_sorento.py:507-514` sets `body["companyCode"]`; `company_service.py:796/848` passes
  it). It is NOT the reference prefix that qualifies `source_ref` (`AED_SORENTO:...`).
  Confirmed by the peer: Sorento sends `companies.code` ONLY (`autocount_ref` is empty in prod
  for both books), and their `foundryx-esb` integration row carries NO company binding, so every
  push is anchored by the body `companyCode`. The two book codes are **`SRT`** (Sorento) and
  **`MCH`** (Mocha - NOT `MOCHA`). The gateway matches the code trimmed and case-insensitively
  within the key's tenant.
- **Pre-flight (owner action, prod, before the first live pull):** verify
  `ac_company.sorento_company_code` is exactly `SRT` and `MCH` on the two Foundryx companies. A
  mismatch is a 404 `UNKNOWN_COMPANY` on pull and a `COMPANY_ANCHOR` fault on push - the same one
  string governs both directions.
- `entity` on the wire is `products` or `stock_balances`.

### A3. Routes

**Build.** `POST /api/v1/autocount/snapshots`
```json
{ "companyCode": "SRT", "entity": "products" }
```
(the Mocha book is `{ "companyCode": "MCH", "entity": "products" }` - same routes, same shapes)
-> `202` `{ "snapshotId": "8f1e...", "status": "building", "entity": "products",
"companyCode": "SRT" }`. A build already in flight for the same pair returns THAT id (no second
extraction). Within 60 s of the previous build: `429` + `Retry-After`.

**Status / header.** `GET /api/v1/autocount/snapshots/{snapshotId}`
```json
{
  "snapshotId": "8f1e...", "entity": "products", "companyCode": "SRT",
  "status": "ready", "extractedAt": "2026-09-19T08:14:02Z",
  "expiresAt": "2026-09-20T08:14:02Z", "recordCount": 11830,
  "complete": true, "contentHash": "3b0c...", "sourcePageSize": 1000,
  "zeroListPriceCount": 5129, "negativeListPriceCount": 121, "enrichMissCount": 1,
  "excludedCount": 10,
  "excludedRows": [
    {"source_ref": "AED_SORENTO:SRT-77", "code": "SRT-77",
     "reason": "mapping_failed", "message": "name: this field is required"}
  ]
}
```
While building: `{"snapshotId": "...", "entity": "...", "companyCode": "...",
"status": "building"}` with no counts, optionally carrying a progress hint:
```json
{ "snapshotId": "8f1e...", "entity": "products", "companyCode": "MCH", "status": "building",
  "progress": { "pagesDone": 3, "pagesTotal": 4, "stage": "lookup:uom" } }
```
`progress` is ABSENT whenever it is not known (before page 1 answers, on a bare-array endpoint,
during a stage with no page count). `stage` is one of `source`, `lookup:<alias>`, `combine`,
`mapping`. Treat an absent hint as "still building" - it is a courtesy for your progress bar, not
a contract you can depend on. On failure: `{"...", "status": "failed",
"error": {"code": "SOURCE_PAGE_FAILED", "message": "..."}}`.

A STOCK header carries instead:
```json
{
  "snapshotId": "c22a...", "entity": "stock_balances", "companyCode": "SRT",
  "status": "ready", "extractedAt": "...", "expiresAt": "...",
  "recordCount": 12175, "complete": true, "contentHash": "9ab1...",
  "sourcePageSize": 1000,
  "zeroPairs": 56422, "negativePairs": 42, "fractionalPairs": 0,
  "excludedCount": 5, "excludedNonzeroCount": 0,
  "negativePairList": [ {"item_code": "SRT-01", "location_code": "MBS", "qty": -3} ],
  "excludedRows": [
    {"item_code": "SRT-99", "location_code": "HQ",
     "measure": 0, "reason": "uom_rate_unresolved"}
  ]
}
```
**Amended (S5b, coordinator ruling 2026-09-20):** an `excludedRows` entry's shape is
`{<groupBy columns>, measure, reason}` exactly, straight off the entity-agnostic combine engine
(`http_source/combine.py`'s `apply_combine`, S5a) - it carries the row's group-by columns (here
`item_code`/`location_code`) plus the raw value of the combine step's DESIGNATED `measure` column
(never a fixed `qty`/`uom` pair; those are two more of stock's OWN pre-group source columns the
engine has no way to single out generically) plus the exclusion's `reason`. The example above
originally showed a `"uom": "ctn"` key with no mechanism to produce it and `"qty"` instead of
`"measure"` - corrected here rather than extending the engine to carry a third, entity-specific
column for one consumer's worked example.

**Amended (S5b review round 5, coordinator ruling 2026-09-20):** `sourcePageSize` added to the
example above - it is on the real header for every entity (review round 2, AC-10-32/A7) and was
missing here by omission only, never a stock-specific difference. Also: a STOCK snapshot's
`excludedRows` today mixes two distinct shapes depending on which STAGE produced the exclusion -
a COMBINE-stage exclusion (the `uom_rate_unresolved` example above, `apply_combine`'s own
require-stage output) carries `{<groupBy cols>, measure, reason}` with no `message`; a
MAPPING-stage exclusion (a row that survived combine intact but then failed a canonical field
constraint, e.g. stock's `qty >= 0`) is normalised to the SAME `{<groupBy cols>, measure, reason:
"mapping_failed", message}` shape rather than the generic per-record `{source_ref, code, reason,
message}` shape a task with NO combine step keeps - ONE shape per combine-carrying task,
regardless of which stage excluded the row, so the consumer's `excludedNonzeroCount` reads every
exclusion uniformly. A task with no `combine` step (every non-stock HTTP entity today) is
byte-identical to before this amendment.

**Pages.** `GET /api/v1/autocount/snapshots/{snapshotId}/rows?page=1&pageSize=1000`
```json
{ "snapshotId": "8f1e...", "page": 1, "pageSize": 1000, "totalPages": 12,
  "recordCount": 11840, "rows": [ ... ] }
```
`pageSize` default 1000, max 1000 (above max is clamped, not an error). Ordering is stable
across calls. A page past `totalPages` returns an empty `rows` array, not a 404. The header
facts are NOT repeated on a page - fetch the header once.

### A4. Row shapes

**products** - `CanonicalProduct.sink_payload()` EXACTLY as pushed today, same mapper, zero
contract change:
```json
{ "source_ref": "AED_SORENTO:BRACD7455C", "code": "BRACD7455C", "name": "Widget 12mm",
  "description": "...", "category_code": "ACC", "uom_code": "UNIT",
  "brand_code": "SORENTO", "list_price": "0.0", "cost_price": "12.50", "is_active": true }
```
`source_ref` is `{refPrefix}:{ItemCode}` on BOTH books (owner ruling R8 - see A9); it is the
SAME scheme the push path will mint when products flip to automatic. `list_price` / `cost_price` are JSON STRINGS, not numbers:
`sink_payload()` is `model_dump(mode="json")` and pydantic v2 renders `Decimal` as a string
(verified, pydantic 2.13.4). That is unchanged from every other Decimal this module already sends
you; confirm your `CanonicalProduct.list_price` coerces `"0.0"` cleanly, since the field has never
carried a value before.
Notes: a `None` field is OMITTED (never `null`), so absent keys are normal - treat absent as
"unchanged". `list_price: 0` is a REAL zero (AutoCount parity, owner ruling R2; 5,008 of 11,840
db1 items are 0.0) - do NOT treat it as missing. A NEGATIVE source price is CLAMPED to 0 before it
reaches you (owner ruling R5; 121 active db1 items carry a `-1.0` sentinel), so you will never see
a negative `list_price`; `negativeListPriceCount` in the header tells you how many were clamped,
and `zeroListPriceCount` is the POST-clamp total (it includes them). `source_doc_no` is normally absent.
`is_discontinued` is NOT sent; you derive it from a description starting with `****`, the same
rule as your manual Excel path.

**stock_balances** - one row per (item, location), base UOM, whole units, nonzero positive only:
```json
{ "source_ref": "AED_SORENTO:BRACD7455C|MBS", "item_code": "BRACD7455C",
  "item_description": "Widget 12mm", "location_code": "MBS",
  "uom_code": "UNIT", "qty": 37 }
```
`item_description` is included so your Stock List xlsx (Item Code, Item Description, Location,
On Hand Qty) needs no second lookup. `location_code` equals the warehouse master code Foundryx
pushes, TRIMMED on both sides (live dirt: `'MBS '` with a trailing space; your matching is
case-insensitive but does not trim). Zero and negative pairs are NOT rows - they are counted in
the header. `source_ref` is present and ignorable. **Foundryx applies no location filter at all
(owner ruling R7):** every positive pair ships, roughly 12,133 for `SRT` over 75 locations. Your
side decides what to apply.

### A5. Immutability, completeness, TTL

- A snapshot is immutable once `ready`. Confirm MUST re-read the SAME `snapshotId`.
- `complete: true` means ONLY "the extraction walked the full company set" (raw scanned rows ==
  the wrapper's echoed `TotalCount`). It says nothing about data quality.
- Refuse to Confirm when: the snapshot is expired (`410 SNAPSHOT_EXPIRED`), `complete` is
  `false`, or your re-read `recordCount` disagrees with the row count you assembled.
- **Exclusions (`excludedCount` / `excludedRows`) are NOT a failure and NOT a reason to block a
  PRODUCT Confirm** (owner ruling R6): the record was read but could not be delivered (e.g. an
  item with an empty `Description`, which is 10 live db1 items). Your product upsert is
  non-destructive, so the excluded products simply keep what you already hold - list them on the
  review page and let the user Confirm. **For STOCK the rule is the opposite and unchanged:**
  refuse to Confirm while `excludedNonzeroCount > 0`, because your import zeroes absent pairs and
  an unresolvable nonzero row would silently zero real inventory. A snapshot
  carrying exclusions is still `status: "ready"` with `complete: true`.
- `contentHash` = sha256 over the concatenation, in page-then-row order, of
  `json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"` for each row. Recompute it
  after assembling pages if you want a belt-and-braces check.
- TTL is 24 h from `extractedAt`, and `extractedAt` is the BUILD END (the moment the snapshot
  became `ready`), not its start - so a 25-minute Mocha build still leaves you a full 24 hours.
  Do not cache a snapshot id beyond that; build a fresh one.
- **Re-clicking Pull while a build is still running re-attaches to the SAME `snapshotId`**, for as
  long as that build is alive, with no time limit. So stopping your poll at 60 minutes is safe: a
  later click returns the same id and the same extraction, never a second one. If the build's
  worker died, Foundryx marks that snapshot `failed` with `BUILD_ABANDONED` (liveness-based, once
  its heartbeat has been silent past the orphan window) and only then does a new request start a
  fresh build.
- Foundryx keeps only the newest 3 ready snapshots per (company, entity), so **a snapshot MAY
  vanish before its `expiresAt`** if three newer ones were built. Treat `404 UNKNOWN_SNAPSHOT`
  and `410 SNAPSHOT_EXPIRED` identically: pull again.
- `contentHash` is a BEST-EFFORT integrity check. It is sha256 over
  `json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"` for each row in page-then-row
  order, over exactly the bytes served. Every value is already a JSON primitive (decimals are
  strings, see A4), so a Python re-dump reproduces it. Your HARD guards are `recordCount`,
  `complete` and the `companyCode` echo - not the hash.
- For STOCK, read `excludedNonzeroCount` (one integer) for your Confirm guard rather than
  scanning `excludedRows`. `excludedRows` and `negativePairList` are uncapped today; if a cap is
  ever added the header sets `truncated: true` and the COUNTS remain the full authoritative
  totals.

### A6. Error ladder (stable codes, body
`{"code","message","companyCode","entity"}`)

A failed snapshot's `error.message` is a FIXED, non-diagnostic sentence per `error.code` (S6,
AC-10-58 M1) - branch on `code`, never parse `message`; the exact prose is not part of this
contract and may change without notice.

| Status | code | Meaning / what to tell your user |
|---|---|---|
| 401 | `INVALID_API_KEY` | Missing, malformed, unknown or revoked key. Uniform, no enumeration |
| 403 | `SERVICE_NOT_ENABLED` | The AutoCount service is off, or the tenant is suspended |
| 403 | `COMPANY_NOT_ALLOWED` | Real company in this tenant, but not in this key's scope |
| 404 | `UNKNOWN_COMPANY` | No company with that code for this key. Uniform across tenants |
| 409 | `PULL_NOT_ENABLED` | This book/entity was never enabled for pull, or is not active |
| 409 | `PUSH_ACTIVE` | This book/entity has flipped to automatic - say "this book is now automatic" |
| 410 | `SNAPSHOT_EXPIRED` | Build a fresh snapshot |
| 404 | `UNKNOWN_SNAPSHOT` | Unknown id, or not yours. Uniform |
| 429 | `TOO_MANY_BUILDS` | Within the 60 s build cooldown; honour `Retry-After` |
| 429 | `TOO_MANY_REQUESTS` (added S4 security round 1, additive) | Either the per-IP throttle (before your key even resolves - the SAME bucket a bad key trips) or a per-KEY request budget counted on every authenticated call, success or business error alike; honour `Retry-After` on both |
| 409 | `AMBIGUOUS_COMPANY` (added S4 security round 1, additive) | More than one company in this tenant shares that `companyCode` (`set_sink_target` does not yet prevent it) - the gateway refuses rather than guessing which one you meant |
| 422 | `INVALID_REQUEST` (added S4 security round 1, additive) | A malformed request: `companyCode`/`entity` missing on `POST /snapshots`, or `page` outside `1..1000000` on the rows route (rejected outright, never clamped - `pageSize` is the only field that clamps) |
| 422 | `UNKNOWN_ENTITY` (added S4 security round 1, additive) | `entity` is not `products` or `stock_balances` |
| 413 | `PAYLOAD_TOO_LARGE` (added S4 security round 1, additive) | Request body over 16 KB, checked on the raw bytes before any JSON parse |
| 500 | `INTERNAL` (added S4 security round 1, additive) | Last-resort net for an unanticipated exception; the body never carries the exception text, class name or a stack frame (logged server-side only) |
| 5xx / `status: "failed"` | `SOURCE_PAGE_FAILED`, `ENRICH_FAILED`, `EMPTY_EXTRACT`, `ROW_LIMIT`, `BUILD_ABANDONED`, `COMBINE_RULE_FAILED` | Extraction failed; nothing partial is ever served. This list is exhaustive and pinned by a test - switch on it safely |

`MAPPING_FAILED` is deliberately NOT in that list (owner ruling R6): a record that cannot be
mapped is an EXCLUDED ROW on a `ready` snapshot, never a snapshot failure. `mapping_failed` appears
only as an `excludedRows[].reason`, alongside `uom_rate_unresolved` (stock).

**Amended (S6 docs pass, verified against `pull_v1.py`/`pull_auth.py`/`pull_gateway_service.py`
2026-09-20):** the six rows above marked "added S4 security round 1" were introduced by that
review round (commit `2596cb46`, "internal errors, key validation, reflection, per-key throttle,
no-store, ambiguous company") and were never folded into this table - closing that gap. Two
further facts belong beside this ladder, also verified in code and previously undocumented here:
every gateway response, success or error, carries `Cache-Control: no-store`
(`pull_v1.py`'s `_json_response` / `PullGatewayError.to_response`) - never cache this surface, it
serves a customer's ERP master data behind a bearer-style key; and `GET /snapshots/{id}/rows`'s
`page` query param is REJECTED (422 `INVALID_REQUEST`), not clamped, once it exceeds `1000000`
(`pull_v1.py`'s `MAX_PAGE`) - `pageSize` remains the only field that clamps instead of erroring.

**Confirm-3 review round (2026-09-20) - a failed-snapshot message is fixed prose, not a log
line.** Restating the note at the top of this table because it is easy to miss: a `5xx` /
`status: "failed"` row's `error.message` (`pull_gateway_service.GATEWAY_FAILED_MESSAGES`, one
sentence per `error_code`, generic fallback for an unmapped code) is operator-safe by
construction - it never echoes the stored `snapshot.error`, which names this deployment's own
source host/port/endpoint path. Treat `message` as display-only human copy that may be reworded
without a contract bump; only `error.code` is the stable, switchable value.

### A7. Sizing (for your RQ timeouts)

**Row counts.** db1, probed 2026-09-19: products about 11,840 rows / 12 pages of 1000; stock about
12,175 delivered rows (reduced from 68,612 raw balance rows over 69 wrapper pages). Build cost is
dominated by the upstream wrapper: products = 12 source + 12 lookup requests; stock = 69 + 12 + 12.

**Build DURATION varies enormously by book, and this is the part to size for.** Measured
2026-09-19/20 against the AutoCount wrapper itself (not our gateway): db1 serves 1,000 rows in
about 21 s, while db2 (Mocha) runs at roughly 0.2 s PER ROW and Cloudflare cuts any upstream
request past about 100 s. So:

| Book / entity | Expect |
|---|---|
| `SRT` products | minutes |
| `SRT` stock | minutes |
| `MCH` products | up to about 30 minutes (about 3,438 items plus as many lookup rows) |
| `MCH` stock | UNKNOWN - not yet measured, plan for longer |

**What this means for your client:** poll `GET /snapshots/{id}` every 5 s and use a LONG ceiling -
60 minutes is the suggestion - showing "still building" rather than failing. A `status: "building"`
response is a healthy answer, not a stall; there is no short server-side timeout on our build job.
Page the READY snapshot with `pageSize=1000` as before (our paging is a database read and is
fast - it is the upstream wrapper that is slow, never the gateway). The header's `sourcePageSize`
tells you what page size the extraction actually used, which is the first thing to look at if a
build was unusually slow. The owner is raising the db2 performance with the wrapper vendor.

### A8. Your side (the slice list this contract implies)

- **SR0 - contract 2.4 (its own small lane / PR, ahead of SR1-SR4, with a security-reviewer
  pass).** Products code-wins in `MasterIngestService` + optional `codes` on product deletions.
  See A9. Must be deployed before joint run 1 on `SRT`; `MCH` (zero existing refs) does not need
  it.
- **SR1 - BE client + products preview job.** A server-side client for the three routes above
  (key in settings), driven from an RQ job: build -> poll -> page -> assemble -> hold for review.
- **SR2 - FE Pull button + review page.** The **Pull button lives on the Products list and on the
  Stock Balance grid, where Import sits today**; the **import-job detail page IS the review page**
  (rows, header facts, xlsx download in the MANUAL template shape, Confirm). Show `complete`,
  `recordCount`, `excludedCount` with the excluded rows listed (they do NOT block a product
  Confirm), and for products the count of rows whose `list_price` went to 0 - either from the
  header (`zeroListPriceCount` / `negativeListPriceCount`) or from your own `dry_run` diff.
- **SR3 - products Confirm via `MasterIngestService`** (owner ruling R1): `dry_run` for the diff,
  then the SAME ingest service on Confirm. Not the Excel bulk-import path. **Joint run 1:
  products, `SRT` then `MCH`** (mirrored in Foundryx slice S6).
- **SR4 - stock preview / pull / guard / Confirm + Stock List xlsx.** Apply the
  **active-warehouse filter BEFORE `process_stock_import`** (owner ruling R7): only rows whose
  warehouse is ACTIVE in Sorento are fed in; inactive-warehouse and unknown-location rows are
  listed on the review page as "not applied" with counts, never silently dropped. Expect roughly
  12,133 delivered and roughly 6,500 fed for `SRT`. Confirm via `process_stock_import` during the
  check period, and archive the generated xlsx as the "Stock List" attachment (owner ruling R3):
  **the xlsx contains the FED rows** - every pulled row whose warehouse is active in Sorento,
  INCLUDING rows the import then skips as `PRODUCT_NOT_FOUND` (the manual Template is archived raw
  and carries those too) - and EXCLUDES the inactive / unknown-location "not applied" rows.
  Guard on `excludedNonzeroCount > 0`. Known quirks on your
  side: the import clamps `<= 0` to 0 and applies `int()`; the zero-out skips inactive
  warehouses; stock is keyed by product + warehouse only (no batch, no UOM). Foundryx sends only
  nonzero positive integer pairs in base UOM, so the clamp should never fire. **Joint run 2:
  stock, `SRT` then `MCH`** - no longer gated (owner ruling R7).
- **SR5 - later (contract 2.5, NOT now)**: a real `stock_balances` ingest entity so stock can
  flip to auto-push like products will. Foundryx tracks it as BL-SS-207; the row shape in A4 is
  the proposed starting point.
- **Ordering guard (recorded, no contract impact).** Sorento WARNS, and does not block, on
  `would_skip` `PRODUCT_NOT_FOUND` / `WAREHOUSE_NOT_FOUND` rows, showing the qty total. Relevant
  because Sorento holds 83 `SRT` warehouses against 154 AutoCount locations.
- **Permissions** (your default, recorded here only): one slug per entity covering Pull +
  Confirm - `master_data.products.autocount_pull`, `inventory.stock.autocount_pull`.
- **Fixtures.** Foundryx ships recorded samples for your mock build at
  `documentation/plans/sprint-5/10-fixtures/`: per entity a header JSON and one 10-row page JSON,
  plus one 409 body and one `status: "failed"` body.

### A10. Manual-upload parity (owner ruling R10)

The pulled product set must land exactly as the manual Excel upload would have left it. Your
code-level matrix (2026-09-20) is the basis; recorded here so neither side drifts.

| Field | Excel path (X) | Ingest path (I) | Consequence for Foundryx |
|---|---|---|---|
| `is_discontinued` | explicit flag wins, else `description.lstrip().startswith("****")` | SAME function | Nothing to send - it follows from the description text we send. 2,882 live `SRT` descriptions start `****` |
| L/W/H | `parse_dimensions` over the description | SAME function | Same - follows from the description text |
| `description` | `Description + " " + Desc2` when `Desc2` non-empty, RAW join, `.strip()` ENDS only; else `Description` | `payload.description` when non-blank, else `payload.name` | Foundryx now sends the JOINED value, built by a visible mapping formula (AC-10-73). Inner whitespace NEVER collapsed - 2,786 live rows hold a double space because X joins raw |
| `product_name` | Item Code | `payload.code`, ALWAYS (peer correction 2026-09-20 - `name` is only a fallback for `description` when that is blank) | Both paths store the Item Code as `product_name`. We send `name = Description` only because the contract requires the field |
| `unit` / `uom_code` | no column in the template - X FORCES the configured default UOM onto every row it touches (peer correction 2026-09-20) | with `uom_code` omitted: untouched on update, default on create | NEAR-parity, not identity. Measured delta: `SRT` 11,850 on `EA` + 26 still on `L`, `MCH` all `EA` - so 26 residual `SRT` products that a next manual upload resets to `EA` and a pull leaves on `L`. Never a `dry_run` diff row (the key is absent). Foundryx still withholds `uom_code` for the check period (AC-10-74); enabling it is on the push-flip checklist |
| `cost_price` | derived by nothing | derived by nothing | Never sent (the ~60 percent values in prod came from outside this pipeline) |
| `remark` | X never writes it | - | Declared on `CanonicalProduct` (`Optional`, max 500) but never sent by either side |
| `description` edge whitespace | X keeps it | ingest strips string ENDS on everything it receives | The "edge whitespace trimmed by ingest" diff class, about 45 rows - detailed below the table |
| brand blank | X clears brand to NULL | I ignores a blank | Measured delta, 16 live blank `ItemBrand` rows. Recorded, NOT patched - it only bites if a brand is blanked later |
| stock | `bulk_import_stock` | SR4 feeds the SAME `process_stock_import` | Parity by construction. Note that on UPDATE it resets `reserved` / `damaged` to 0 and `reorder_point` / `zone` to NULL when those columns are absent - identical to the manual 4-column file |

**The gate.** Sorento adds a parity pytest that feeds the SAME items through X (template rows)
and I (our canonical rows) into two scratch companies and asserts identical `products` columns:
name, description, category, brand, `list_price`, `is_active`, `is_discontinued`, L/W/H and
default supplier. Foundryx's S0 product fixture carries the awkward rows it needs: a `****` item,
an item with dimensions in the description, an item WITH `Desc2` (including one whose raw join
yields a double space), a `-1.0` price item, a `0` price item and an edge-whitespace-code item.
**Joint run 1 exit criterion:** your `dry_run` over the pulled `SRT` set shows NO description,
discontinued or dimension change for products whose AutoCount data has not changed since the last
manual upload - every remaining diff row explainable, with **"edge whitespace trimmed by ingest"**
(about 45 rows, detailed below) as a named and expected class.

**Your patches recorded here** (no contract impact): `created_by` / `updated_by` stamped with the
confirming user on a pull Confirm; per-record outcomes written to `import_job_rows`.

CONFIRMED by the peer from X's code (`product_service.py:1647-1650`, 2026-09-20): X tests `Desc2`
by RAW truthiness (`if desc2:`), joins both parts RAW in an f-string, and `.strip()`s the joined
result only. Our formula is byte-equal to X in the join branch. In the no-`Desc2` branch X does
NOT strip while we trim - moot, because Sorento's ingest schema strips string ENDS on everything
it receives.

Explainable-diff class for joint run 1 - **"edge whitespace trimmed by ingest"**: descriptions
stored today WITH edge whitespace (X kept it) = SRT 41 (42 counting tabs / newlines) of 11,876,
MCH 4 of 3,442. On the first pull those rows show a whitespace-only description diff, and a manual
upload running in parallel puts the edge space back each time. Cosmetic: no rule depends on it
(`****` uses `lstrip`, dimensions are a regex search). Nobody patches it; the reviewer should
expect roughly 45 such rows.

### A9. Product identity: code wins (contract 2.4)

Owner ruling R8, 2026-09-19, locked. Foundryx keys every product `<refPrefix>:<ItemCode>` on BOTH
books (e.g. `AED_SORENTO:BRACD7455C`, `MCH:BRACD7455C`) - no AutoKey scheme, no per-book variant.
Sorento carries the reconciliation, for entity `products` ONLY:

1. **Ingest.** A `source_ref` miss whose `code` matches a product already linked under the SAME
   source system and the SAME anchored company UPDATES that product, KEEPS the existing
   (AutoKey) reference untouched, does NOT link the new reference, and attaches a `ref_mismatch`
   warning. `dry_run` reports `updated` + the diff + the warning. `ReferenceConflict` stays for
   every other entity and every other source system. This mirrors the rule your document-line
   resolver already applies.
2. **Warnings.** No new shape: record results carry `"warnings": ["<code>", ...]`, stable string
   codes, omitted when empty. `ref_mismatch` already exists and already reaches Foundryx on
   `sales_orders` / `purchase_orders` records. Example product record:
   ```json
   { "source_ref": "AED_SORENTO:SRT-01", "outcome": "updated", "entity_id": "...",
     "diff": { "list_price": { "current": "63.00", "incoming": "0" } },
     "warnings": ["ref_mismatch"] }
   ```
   Foundryx side, verified: `SorentoSink._result_for` keys on `outcome` alone
   (`_OUTCOME_DELIVERED = {"created", "updated"}`) and never reads `warnings`, so this already
   parses as SUCCESS with no change; we are adding only a per-code count on the run's activity.
   An unknown code is informational and never downgrades an outcome.
3. **Deletions.** `POST /external/ingest/products/deletions`
   ```json
   { "companyCode": "SRT", "source_refs": ["AED_SORENTO:BRACD7455C"],
     "codes": { "AED_SORENTO:BRACD7455C": "BRACD7455C" } }
   ```
   `codes` is an optional object keyed by `source_ref`, honoured for `products` only. On a ref
   MISS with `codes[ref]` present, Sorento matches `product_code` in the anchored company and
   proceeds only if that product is unlinked or linked under the same source system; otherwise
   `not_found`. Outcomes unchanged (`deleted` / `deactivated` / `not_found`) plus
   `warnings: ["ref_mismatch"]` when the code rung matched. Foundryx derives `codes` from the ref
   itself (it IS `{prefix}:{ItemCode}`), emits it only for single-key ItemCode tasks, and only
   once the contract gate reports `>= 2.4`.
4. **Read-back** for products stays ref-only; Foundryx does not rely on it.
5. **Versioning.** Contract **2.4** = products code-wins + optional `codes` on product deletions.
   The `stock_balances` ingest entity moves to **2.5**. Foundryx gates product PUSH activation on
   `>= 2.4` and shows a banner in pull mode.

Nothing is open. The stock scope question is closed by owner ruling R7 (Foundryx ships every
positive pair; you filter on your own active flag) and product identity by R8 (code wins,
contract 2.4 - A9). The only sequencing constraint left is SR0 before joint run 1 on `SRT`.
