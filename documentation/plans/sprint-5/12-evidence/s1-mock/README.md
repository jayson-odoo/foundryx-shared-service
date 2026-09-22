# sprint-5/12 S1 (frontend mock) - agent-browser run log

Recorded 2026-09-22 by the lane coder. Tool: `agent-browser` CLI, `--session s50`, headless
Chrome. NO Playwright. Widths: 1280x900 and 375x812 (`agent-browser set viewport`).

## Stack under test

| Piece | Value |
|---|---|
| Frontend | `npx next start -p 3012`, fresh `rm -rf .next && npm run build` |
| Backend | `uvicorn app.main:app --port 8012`, lane env (`DATABASE_URL=...foundryx_service_s50`, `REDIS_URL=redis://localhost:6379/12`, `CELERY_TASK_ALWAYS_EAGER=true`, `ENVIRONMENT=development`, `CORS_ORIGINS=...,http://localhost:3012`) |
| DB | `foundryx_service_s50` (autocount + omnichannel installed on the `default` tenant) |
| Login | `demo@example.com` / `demo1234`, tenant `default` |
| Service binding | `withPhase1MappingResetMock(realAutocountService)` - the S1 PHASE 1 MOCK overlay. `getMapping`/`updateMapping` are the REAL backend; only `hasPreset` and `resetMappingToPreset` are overlaid. |

`CORS_ORIGINS` had to be exported ad hoc for :3012 - the SHARED `service_backend/.env` (symlinked
into this worktree) only lists :3001/:3002, so every request from :3012 failed its OPTIONS
preflight with 400 and the AutoCount menu block stayed hidden. The shared `.env` was NOT edited.

## Navigation - real clicks only, no deep URLs

Sidebar `AutoCount` -> `Companies` -> row `Mocha s50` -> tab `Entities` -> row `Actions` menu ->
`Configure mapping` -> the standalone mapping page
(`/autocount/companies/{id}/entities/product/mapping`). That row action is the ONLY route to this
page for an API-sourced entity (`company-detail-view.tsx` `onConfigureMapping`), and it is the
surface the plan's section 7 runbook calls "the Mapping tab" for the prod `SRT` product task.

## Fixture setup (NOT feature verification)

Built through the UI with real clicks: the `autocount` integration (`Mocha REST (s50)`,
`https://hapi.sorento.cc.cd/api/db2`, no auth), the company `Mocha s50`, the `product` and
`customer` entity tasks, each Tested on the Source tab against the LIVE vendor API (product:
19 raw columns + the preset `uom` lookup alias `BaseUOMPrice` = 20 `acFields`; customer:
`/debtorbypage`).

The product mapping was then bent back to the production `SRT` baseline of UAC section 0 with
direct SQL (fixture data only - `ItemCode -> name`, plain `Description -> description`,
`uom_code` ENABLED, no `is_discontinued` row, plus a stray operator row `ItemType -> cost_price`).
The customer mapping's `phone_number` row was disabled by SQL so the "already matches" state has
a task to show it on. Every screenshot below is of the real UI reacting to those rows.

## Shots

| File | What it proves | AC |
|---|---|---|
| `01-1280-mapping-page.png` | The mapping page reached by clicks; `Actions` gear present | AC-12-21 |
| `02-1280-action-menu.png` | `Reset to preset` in the ActionMenu (manage permission + `hasPreset`) | AC-12-21 |
| `03-1280-reset-dialog-diff.png` | The preview Dialog: preset label badge, `StatusBadge` per row (Unchanged / Changed), `ClampedText` formula chip, internally scrolling row list | AC-12-22 |
| `04-1280-reset-dialog-scrolled-disabled-removed.png` | `Disabled - withheld by the preset` on `uom_code` (its column IS returned), `Added` on `is_discontinued`, the `Removed` section listing `ItemType -> Cost price` | AC-12-12, AC-12-22 |
| `05-375-reset-dialog.png`, `06-375-reset-dialog-removed.png` | Same dialog at 375: non-clipped, full-bleed, every row reachable by scrolling the list | AC-12-22, AC-12-33 |
| `07-1280-after-apply-toast.png` | `Reset mapping` applied: `lib/toast` "Mapping reset to preset.", dialog closed, table re-rendered from the returned view (Description -> Name, the Desc2 join on Description, BaseUOMPrice -> List price) | AC-12-23 |
| `08-1280-disabled-reason-missing-column.png` | The OTHER disabled cause, live on the customer task: `Disabled - column not returned by the source` for `Phone1 -> phone_number` (`/debtorbypage` does not return `Phone1`) | AC-12-12, AC-12-15 |
| `08-1280-reset-dialog-post-apply-residual-diff.png` | Known residual diff after a PHASE-1 apply - see "Findings" 1 and 2 | - |
| `09-1280-reset-dialog-empty-diff.png`, `10-375-reset-dialog-empty-diff.png` | "This mapping already matches the preset." with `Reset mapping` DISABLED, both widths | AC-12-22 |
| `11-1280-formula-builder-source-columns.png`, `12-375-formula-builder-source-columns.png` | The master entity's formula builder: ONE `Source columns` group (ItemCode, Description, `Desc2`, ...), the Desc2 join reading "Valid formula", and NO `Testing` tab | AC-12-01, AC-12-05, AC-12-33 |
| `13-375-action-menu.png` | The ActionMenu at 375 | AC-12-21, AC-12-33 |

Console during the run: ZERO errors. The only warnings are the pre-existing Radix
`Missing Description or aria-describedby for DialogContent` notices every dialog in this codebase
emits (`MappingSimulator` included) - not introduced here.

## Findings carried into S2 / the report

1. **BL-SS-260 confirmed here, CLOSED at S2.** `is_discontinued` was captured by
   `PRODUCT_HTTP_PRESET` but absent from `CanonicalProduct.SINK_FIELDS`, so `PUT .../mapping`
   422'd it and the S1 overlay (which has only the PUT) had to submit the accepted subset - which
   is why the applied mapping in shot 07 is missing that one row while the dry-run preview above
   still shows it. The owner's ruling of the same day DROPPED the preset row outright (Sorento
   derives "discontinued" from the `****` description prefix, plan 10 D22), so the S2 shots are
   the current truth and these S1 shots are a historical record of the mock phase.
2. **`is_required` drifted between a PUT and a seed** - raised from this run and RULED ON the
   same day: `plan_rows` now derives `is_required` from `mapping_catalog` (the single source of
   truth `replace_mapping` already used), so a seed, a Save and a reset agree and those rows no
   longer read `changed`. See `../s2-real/README.md` shot 08.
3. The mock's `computeMappingResetDiff` ignores a current row whose `sorentoField` is null (a
   non-deliverable/provenance row), so it reads `is_discontinued` as `added` even when the row
   exists. The S2 backend diffs on `canonical_field` over ALL header rows, so it does not have
   this blind spot - another reason the overlay retires at S2.
