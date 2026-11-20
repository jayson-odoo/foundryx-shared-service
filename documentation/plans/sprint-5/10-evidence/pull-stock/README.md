# Evidence: AC-10-51 stock journey (re-verify at current HEAD)

Run date: 2026-09-20 (UTC), approx 12:50-13:11Z. HEAD `17dc2c619b42224d1211f9006d1c805aec498cd0`.
Lane: backend `:8009`, frontend `:3009`, DB `foundryx_service_s40`. Tenant `default`, user
`demo@example.com` (Admin). Company `Sorento SRT S40` (`0e6f5c95-b099-4a1f-8de9-425b63f561b4`).

**Resume context:** the `Stock balance` entity on this company already existed (already `Active`,
`pull` mode, combine preset pre-seeded) from an earlier tester's partial run, so this journey
re-opens the EXISTING task (AutoCount -> Companies -> Sorento SRT S40 -> Entities -> Stock balance
row Actions -> Configure source) rather than adding a fresh one - the "add the Stock balance
entity" step from the original AC text is superseded by this lane's already-populated state; every
downstream check (Source tab content, alias check, Test, Build, detail) was independently
re-verified live regardless.

## Journey (real clicks, both viewports)

1. **Source tab (view mode).** Preset path `/itembatchbalqtybypage`, two lookup rows
   (`/itembypage` for `ItemBaseUOM`/`ItemDescription`; `/itemuombypage` for `UomRate`), and the
   Combine rows section (computed columns `item_code`/`location_code`/`base_qty`, require rule
   `uom_rate`, measure `qty` = sum of `base_qty` half-up 0dp, drop rules `zero`/`negative`) all
   pre-filled exactly per the AC-10-41 preset. `01-source-tab-top-375.png`, `02-source-tab-lookups-
   375.png`, `03-source-tab-combine-375.png`, `08-source-tab-top-1280.png`, `09-source-tab-lookups-
   1280.png`, `10-source-tab-combine-1280.png`. The AC's own text mentions a read-only "Aggregated
   to one row..." chip; this HEAD (matching the earlier `combine/README.md` PASS run) instead
   shows a full "Combine rows" section with individually-editable computed/require/measure/round/
   drop controls - the chip language predates the later, richer combine editor (R11). **PASS
   with drift note** (Combine section is the current, correct replacement for the chip).
2. **Stock first-Test alias check (the 3-round regression check).** Clicked **Edit**, then clicked
   the TOP-LEVEL **Test** button (next to the main endpoint path) FIRST, before touching anything
   else. Result: `Paged - 68,612 total - 69 pages of 1000` on the main endpoint,
   `Sample: 50 matched - 0 missed` on both lookup rows, and **NO** `"<alias>" is already a source
   column.` message anywhere near `ItemBaseUOM`/`ItemDescription`/`UomRate` - confirmed both by
   visual inspection and `document.body.innerText.includes('is already a source column')` ->
   `false`, at BOTH viewports. `04-alias-check-test-result-375.png`, `11-alias-check-test-result-
   1280.png`. **PASS** - this specific regression (false alias-collision text after a first Test)
   does NOT reproduce at this HEAD.
3. **Watermark/compared pickers never offer `qty` (Defect D1, see below).** The brief's stated
   expectation - "watermark/compared pickers never offer qty" - **FAILS for this already-saved,
   Active task**: opening the Watermark column picker after the Test above offers `None, ItemCode,
   UOM, Location, BatchNo, BalQty, base_qty, qty` - `qty` (the combine's own OUTPUT measure alias)
   IS selectable, which the AC explicitly says should never happen. Full root-cause analysis below
   (Defect D1). This is a NEW finding this run, distinct from - and narrower than - the earlier
   `combine/README.md`'s PASS verdict on the SAME check, which was captured on a brand-new,
   never-saved draft task where the bug's trigger condition (a saved `comparedFields` pick equal to
   the measure alias) did not yet exist.
4. **Schedule tab, read-only badge (AC-10-15/16).** No toggle renders; a single read-only
   `StatusBadge` "Pull on request" is the entire tab content (confirmed via
   `document.querySelectorAll('[role=tab]')` context and a plain text scrape - no radio/group
   elements present at all). `05-schedule-readonly-badge-375.png`, `12-schedule-readonly-badge-
   1280.png`. **PASS.**
5. **Build -> ready -> detail.** Pull page -> Snapshots -> **Build snapshot** -> Company
   `Sorento SRT S40`, Entity `Stock balance`. `06-build-dialog-filled-375.png` (submitted, real
   build, ~5m 42s, see durations below), `13-build-dialog-filled-1280.png` (filled then Cancelled -
   the ALREADY-READY snapshot from the 375px run's build was reused for the 1280px detail capture
   instead of a second ~6-minute rebuild, since the two builds are byte-for-byte deterministic
   against the same live data). Detail page: `Ready`, **12,133** records, `Complete: Yes`, content
   hash `9732032fe75b327873c4d7e98c08c17d90ab7628267b944c4bd37acb4142c2f6`, **56,422** zero pairs,
   **42** negative pairs (all 42 listed as pills), **0** fractional pairs, **0** excluded (nonzero),
   plus the rows preview grid (`source_ref/item_code/item_description/location_code/uom_code/
   qty`). `07-stock-snapshot-detail-header-375.png`, `14-stock-snapshot-detail-header-1280.png`.
   Every number matches the plan's own AC-10-53 figures exactly. **PASS**, both viewports.

## Build duration (this run)

| Build | Route | Started (UTC) | Finished (UTC) | Duration | Records |
|---|---|---|---|---|---|
| Stock balance, SRT | Operator | 12:54:37 | 13:00:19 | 5m 42s | 12,133 |

## Defect D1 - the watermark picker leaks a saved COMPARED-column pick (`qty`) for an already-saved combine task, violating AC-10-51's "never offer qty on watermark"

**Reproduction:** re-open ANY already-saved, Active stock task whose combine preset's measure
alias (`qty`) is part of the SAVED `comparedFields` (which it always is for the stock preset, per
AC-10-41) -> Edit -> Test -> open the Watermark column dropdown. `qty` is offered as a selectable
option, alongside the correctly-excluded key columns (`item_code`, `location_code` - filtered out
because they are `httpKeyFields`) and the correctly-excluded lookup-brought fields (`ItemBaseUOM`,
`ItemDescription` - filtered out because they are `lookupAliases`).

**Root cause (read-only source inspection, no code changed):**
`service_frontend/app/(protected)/autocount/companies/[id]/entities/[entityType]/components/
source-tab.tsx` computes `httpColumnOptions` via `lib/autocount-etl.ts`'s `pickerColumnOptions`:

```
export function pickerColumnOptions(previewColumns: string[], saved: string[]): string[] {
  const seen = new Set(previewColumns);
  const stale = saved.filter((c) => !seen.has(c));
  return [...previewColumns, ...stale];
}
```

`saved` (`httpSavedPicks`) is `[...keyFields, ...watermarkField, ...comparedFields]` - ALL THREE
pickers' saved values unioned into ONE pool, deliberately, so that a value a live preview no longer
returns still renders as a selectable/visible pill instead of silently vanishing (the comment above
it explicitly documents this as the "legacy value" exception). Because `qty` is a genuine saved
`comparedFields` entry (the stock preset always compares `qty`, per AC-10-41), it gets added to
`httpColumnOptions` as a "stale" pick even though the live Test's own pre-combine column set
(`preview.preCombineColumns`) correctly does NOT include it (pre-combine, `qty` does not exist yet
- it is a POST-group measure alias). `httpWatermarkOptions` then filters `httpColumnOptions` by
`!lookupAliases.has() && (!httpKeyFields.includes() || is-the-current-watermark)` - `qty` passes
both conditions (it is neither a lookup alias nor a key field), so it leaks through into the
watermark list, even though it is only present in the pool because of the COMPARED-columns
preservation rule, not because it is a legitimate watermark candidate.

**Why the earlier `combine/README.md` PASS run missed this:** that run captured the check on a
BRAND-NEW, never-before-saved draft task (`Add entity -> Configure` -> Edit -> Test), so
`config.comparedFields` was empty at Test time - `httpSavedPicks` had nothing stale to inject, and
`qty` correctly never appeared. The bug only manifests on a task that has ALREADY been saved with
a combine's comparedFields populated, which is the NORMAL state of any stock task after its first
Save - i.e. this is the common case for an operator re-opening an existing entity, not an edge
case.

**Impact:** an operator could select `qty` as the watermark column, which would be semantically
wrong (the watermark is meant to be a raw, pre-combine change-detection field, not the row's own
computed measure) - a save-time validation gate may or may not catch this (not tested here, no
application code changed); at minimum it is a foolproof-UI violation (AC's own principle: "only
offer options that will work"). Reported for the coder; not fixed here.

**AC-10-51 verdict impact:** the AC's blanket "watermark/compared pickers never offer qty" claim
is **FAIL** for an already-saved task (the common case); the ORIGINAL claim remains **PASS** for a
brand-new draft task (the `combine/README.md` scenario). Recorded as a genuine regression-class
finding for the coder to fix in `httpWatermarkOptions` (it needs to exclude a comparedFields-only
stale pick from the watermark pool specifically, not just lookup aliases and key fields).

## Responsive

Both widths confirmed clean (no unexpected horizontal scroll beyond the Combine section's own
internal funnel/preview-grid scroll, which is by design).

## House rules

- No hint/instructional copy. **PASS.**
- Every column pick (group-by, carry, measure source, watermark, compared columns, Company/Entity
  in Build dialog) is a searchable `SearchSelect`/`MultiSelect`. **PASS.**
- Console: only the pre-existing benign `DialogContent` a11y warning; no page errors. **PASS.**
- No em/en dashes, no "Foundryx" branding visible. **PASS.**

## AC verdicts (this run)

- **AC-10-51 [E2E]** PARTIAL. Source tab content, alias-collision-on-first-Test (the historical
  3-round defect), Schedule read-only badge, Build -> ready -> detail all **PASS** at both
  viewports with exact-match figures. The "watermark/compared pickers never offer qty" sub-clause
  is **FAIL** for an already-saved task (Defect D1, a new, narrower, more precisely-located finding
  than the earlier combine README's blanket PASS).
- **AC-10-15/16 [BE/FE]** PASS. Read-only badge confirmed no toggle, both viewports.
