# sprint-5/12 S3 (document entity) - agent-browser run log

Recorded 2026-09-22 by the lane tester at HEAD `e1857aac`. Tool: `agent-browser` CLI,
`--session s50t`, headless Chrome. NO Playwright. Widths 1280x900 and 375x812.
Target: **AC-12-27** (document entities are resettable, header scope only - ruling R7).

## Verdict: AC-12-27 FAILS on the UI path (the backend half is correct)

"Reset to preset" is **not offered anywhere an operator can click** on a document entity's
mapping editor. The backend answers `hasPreset: true` for the entity and the reset route
behaves exactly as AC-12-13/27 specify (header rows replaced, line rows byte-identical) - but
the surface that carries the action is unreachable for this class of task. Detail in
"The defect" below.

## Stack under test

| Piece | Value |
|---|---|
| Frontend | :3012, prod build of `e1857aac` (`lsof` cwd = `.claude/worktrees/s50/service_frontend`) |
| Backend | :8012, uvicorn without `--reload`, lane env, DB `foundryx_service_s50` |
| Auth | real login `demo@example.com` at `localhost:3012`, tenant `default` |
| Schema | no migration - this plan ships none (AC-12-32) |

## Precondition - how the DB-source document task was provisioned

The lane had **no** `sql_database` company, and one cannot be invented: `POST
/autocount/companies` runs a LIVE probe (`probe_current_database`, sprint-5/01 AC-01-02) and
422s on `connectionId` when the server is unreachable. Recorded blocker with a fake MSSQL host:

```
{"detail":{"fieldErrors":{"connectionId":"Could not connect to the database: (20009, ...
 Unable to connect: Adaptive Server is unavailable or does not exist (127.0.0.1) ..."}}}
HTTP 422
```

So the company was provisioned against a database that DOES exist and that the SQL provider
already supports: the lane's own Postgres, via the provider's `postgresql` dialect. Everything
below was created **through the product's own routes** - no hand-written `ac_*` row anywhere:

1. Integration `E2E SQL s50 20260922-044247` (provider `sql_database`, dbType `postgresql`,
   `localhost:5432/foundryx_service_s50`) - created by REAL CLICKS
   (sidebar AutoCount -> Companies -> Connect company -> "SQL database" -> "Add one in
   Integrations" -> provider picker -> fields -> Create integration), then re-pointed at
   Postgres with `PATCH /integrations/connections/{id}` (operator-API setup). Its own
   `POST .../test` answers `Connected to foundryx_service_s50 on localhost (PostgreSQL).`
2. Company `E2E Docs s50 20260922-044247` - `POST /autocount/companies` (operator-API setup),
   id `7eab8612-86af-439f-a3e3-c404b9f4de9a`, `sourceKind: db`.
3. `sales_order` task - `PUT .../entities/sales_order/etl-task` with a header query and a
   `:doc_key`-bound line query that SELECT AutoCount's own column names as quoted aliases off
   `app_autocount.ac_company`. The save ran the product's real preview validation and stored 12
   header + 15 line `resultColumns`.
4. **The mapping seeded itself**, by the product's own first-clean-save rule
   (`etl_service` -> `seed_document_mapping`): **11 header rows + 14 line rows**, no fixture.

Names are timestamped per the E2E rule. Residue left in the lane DB on purpose (it IS the
evidence): connection `fbf94a72-95d1-4216-a131-e045247914b7`, company
`7eab8612-86af-439f-a3e3-c404b9f4de9a`.

## Navigation - real clicks only

Sidebar `AutoCount` -> `Companies` -> row `E2E Docs s50 20260922-044247` -> tab `Entities` ->
the Sales order row's `Actions` menu -> `Configure mapping`.

## The defect

`Configure mapping` lands on **`/autocount/companies/{id}/entities/sales_order?tab=mapping`** -
the TASK editor's Mapping tab (`components/task-editor-view.tsx`), which embeds
`MappingEditorBody` and nothing else. The "Reset to preset" `ActionMenu` item and
`MappingResetDialog` live only on `mapping/components/mapping-editor-view.tsx`, the standalone
`/entities/{entityType}/mapping` page.

`company-detail-view.tsx` `onConfigureMapping` routes them apart:

```ts
if (entity.sourceImpl === 'sql_db') {
  router.push(acTaskHref(companyId, entity.entityType, 'mapping'));   // no reset action here
  return;
}
router.push(acMappingHref(companyId, entity.entityType));             // the reset action lives here
```

`acMappingHref` has exactly one other caller in the whole frontend - that same function - so a
`sql_db` task can never reach the standalone page by clicking.

And every document entity is a `sql_db` task in practice: `resolve_preset_rows` only answers
`DOCUMENT_PRESETS` on the non-HTTP branch, and `HTTP_PRESETS` carries no document entity
(product / customer / warehouse / product_category / brand / unit_of_measure / stock_balance).
So `hasPreset=true` + document == unreachable, every time.

Enumerated live on the landing page (both widths), the only controls present are:

```
Edit | Source | Mapping | Schedule | Review & Activate | Runs | Simulate mapping
```

No `Actions` button, no menu item, no dialog.

## Shots and artefacts

| File | What it proves | AC |
|---|---|---|
| `02-1280-entities-configure-mapping-menu.png` | The only click path to a document mapping: the row menu's `Configure mapping` (`Sync now` / `Configure mapping` / `Configure source`) | AC-12-27 |
| `03-1280-document-mapping-editor-no-reset-action.png` | Where that lands: `?tab=mapping`, Header fields (11) + Line fields (14) seeded and rendering, and NO `Actions` menu / `Reset to preset` | **AC-12-27 FAIL** |
| `04-375-document-mapping-editor-no-reset-action.png` | Same at 375: page does not overflow (`scrollWidth === innerWidth === 375`), same absent action | AC-12-27, AC-12-33 |
| `05-dry-run-header-only.json` | `POST .../mapping/reset-preset {"dryRun":true}` on this very entity: `label: "AutoCount SO"`, **11 rows, all header**, `removed: []`. No line canonical field (`unit_price`/`qty_ordered`/`source_ref`/`line_number`) appears | AC-12-12, AC-12-27 (backend half) |
| `06-line-rows-before.txt` / `07-line-rows-after.txt` | The 14 line rows immediately before and after a real `dryRun:false` apply - `diff` is EMPTY. The deliberate operator customisation `SubTotal -> unit_price` survives the reset verbatim | AC-12-13, AC-12-27 (backend half) |

Backend sequence actually run (curl, after bending one header row to `DocKey -> so_number` and
deleting the `customer_name` header row through the product's own mapping PUT):

```
dry run  -> 11 header rows, "CHANGED so_number <- DocNo", "ADDED customer_name <- DebtorName",
            removed: [], no line row in the diff
apply    -> HTTP 200; header rows back to the preset (DocNo -> so_number, DebtorName ->
            customer_name); line rows: 14 before, 14 after, diff empty
```

## Console

Zero errors across the run. Only the codebase-wide Radix
`Missing Description or aria-describedby for {DialogContent}` warnings (3), which pre-date this
plan.

## What a fix looks like (for the coder, not done here)

Either render the same `ActionMenu` item + `MappingResetDialog` on the task editor's Mapping
tab, or stop routing `sql_db` away from the standalone mapping page. The tester does not change
application code.
