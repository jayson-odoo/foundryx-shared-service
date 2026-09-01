# 15 - AutoCount review UI + field-mapping editor - Test Execution Report

> **Contract:** `15-autocount-review-ui-and-mapping-acceptance-criteria.md`
> **Branch:** `sprint-4/14-autocount-sorento-masters`
> **Date:** 2026-07-22
> **Stack under test:** Next :3001 → FastAPI :8001 → Postgres (live, seeded). Real-click E2E +
> backend/FE unit suites.

## Automated evidence (green)

| Suite | Result |
|-------|--------|
| Backend `test_autocount*` + `test_sorento_sink` | **295 passed** (`python -m pytest`) |
| Frontend vitest (full) | **1079 passed** (128 files) - incl. `use-jobs-list-config.test.tsx`, `use-staged-list-config.test.tsx`, `staged-records-list.test.tsx`, `review-view.test.tsx`, `sink-target-section.test.tsx`, `mapping-table.test.tsx`, `entities-list-config.test.tsx` |
| **E2E** `e2e/autocount-mapping.spec.ts` | **2 passed** (real clicks vs live stack) |

## E2E journey - Review via the sidebar + push-target read-only-until-Edit

- **User story:** As an operator I open the Review list from the AutoCount menu, see my sync batches,
  and open one; and my company's push target is read-only until I choose to edit it.
- **Scenario:** `AC-15-01..03 / AC-15-20` in `e2e/autocount-mapping.spec.ts`.
- **Precondition:** A dedicated, timestamped tenant provisioned via the operator API with the
  `autocount` module installed; a scripted AutoCount vendor on loopback (GRN only) so a real Sync now
  can manufacture a reviewable batch. Sorento is NOT involved.
- **Steps (every navigation a real click):** sign in → Settings ▸ Integrations → Connect integration
  (AutoCount) → Test connection → AutoCount ▸ Companies → Connect company → on the company Overview
  inspect the Delivery target → click Edit → set Delivery to Sorento → observe the missing-connection
  warning → Cancel → Entities tab → Goods received note row ▸ Actions ▸ Sync now → (eager job stages,
  app navigates to the review form) → click Back → AutoCount ▸ Review (sidebar) → open the batch row.
- **Expected:** Delivery read-only (no bare dropdown) until Edit; Sorento with no connection warns and
  is not silently saved; the Review sidebar entry opens a Resource list of batches with the review-state
  segments; a batch row opens the review form (Needs review + approve control).
- **Actual:** PASS. Delivery renders as plain label/value in read mode (`Push delivery target`
  combobox absent); under Edit the picker appears and selecting Sorento surfaces
  `sink-connection-warning`; the Review list shows the `Goods received note` batch under the
  `Needs review` segment; the row opens the review form (`approve-batch` visible).
- **Remarks:** Verified responsive at **375px and 1280px** (no horizontal page scroll, anchor in view).

## E2E journey - Mapping editor, formula builder + simulators

- **User story:** As an operator I configure an entity's AutoCount→Sorento field mapping, express a
  transform as a formula, test it, and simulate a whole record before trusting it.
- **Scenario:** `AC-15-40..44 / AC-16-10..31` in `e2e/autocount-mapping.spec.ts` (detailed in the
  slice-16 report; the slice-15 mapping-editor ACs are covered by its opening steps).
- **Steps:** …Companies → company → Entities → Supplier row ▸ Actions ▸ Configure mapping → confirm the
  AutoCount field / Transform / Sorento field table renders **read-only** (no comboboxes, Edit button
  present) → Simulate mapping (read mode) → Edit → change a row transform → save.
- **Actual:** PASS - read-only-until-Edit honoured; the mapping saves through the form's single
  dirty-guarded Save (`Field mapping saved.`).

## AC verdicts

| AC | Verdict | Evidence |
|----|---------|----------|
| AC-15-01 Review sidebar entry | **PASS** | E2E: `AutoCount ▸ Review` reached by click → `/autocount/review`. Menu tagged `autocount.sync.read` in all 4 menu arrays (`config/menu.config.tsx`). |
| AC-15-02 Review is a paginated Resource list | **PASS** | E2E renders the list with `Needs review \| Done \| All` segments; `use-jobs-list-config.test.tsx`; backend `GET /autocount/jobs` tenant-scoped + status filter (`test_autocount_pipeline.py` `:3477`, `:3494`, `:3816`). |
| AC-15-03 Batch row opens the review form | **PASS** | E2E: clicking the batch row navigates to `/autocount/review/{jobId}` (review form; approve control visible). |
| AC-15-10 Staged list paginates/filters/searches | **PASS** | `use-staged-list-config.test.tsx`, `staged-records-list.test.tsx`; backend staged pagination (`test_autocount_pipeline.py` `:3477`, `hasChanges` per row `:3604`). |
| AC-15-11 No-change records collapsed | **PASS** | `test_autocount_pipeline.py` AC-15-11 (`:3595` - delta re-fetch with no mapped-field change collapses into a count); `staged-records-list.test.tsx`. |
| AC-15-20 Push target read-only until Edit | **PASS** | E2E (above): Delivery plain in read mode, picker only under Edit, saved via the form's single save; `sink-target-section.test.tsx`. |
| AC-15-21 Push target matches form design | **PASS** | E2E: `SearchSelect` pickers, Sorento-with-no-connection warning; `sink-target-section.test.tsx`. |
| AC-15-30 First-run window not a dead control | **PASS** | `entities-list-config.test.tsx` (Edit-window offered only pre-watermark, Re-fetch history once superseded); backend re-fetch (`test_autocount_pipeline.py` AC-15-30 `:3764`). |
| AC-15-31 Un-synced entity edits the window normally | **PASS** | `entity-lookback-dialog.test.tsx`; `entities-list-config.test.tsx` - Days editable when no watermark. |
| AC-15-40 Field mappings viewable | **PASS** | E2E: the AutoCount field → Transform → Sorento field table renders; `mapping-table.test.tsx`; backend `GET …/mapping` (`test_autocount_pipeline.py` `:3651`). |
| AC-15-41 Remap the source per Sorento field | **PASS** | E2E saves an edited mapping; backend PUT AC-15-41 seed-safe (`test_autocount_pipeline.py` `:3743`). |
| AC-15-42 Target picker = only accepted fields | **PASS** | Backend PUT guard 422 on non-accepted target (`test_autocount_pipeline.py` AC-15-42 `:3709`); FE picker offers only the accepted set (`mapping-table.tsx` + `mapping-table.test.tsx`). |
| AC-15-43 Source picker discoverable, free path allowed | **PASS** | `mapping-table.test.tsx` (SearchSelect `allowCustom` dotted path); backend source catalog + shape validation. |
| AC-15-44 Mapping editor read-only until Edit + foolproof | **PASS** | E2E: read-only-until-Edit + no comboboxes in read mode; `unmapped-required-warning` for an unmapped required Sorento field (`mapping-editor-view.tsx`, `mapping-table.test.tsx`). |

## DoD gate

1. **Mock swapped to real** - `services/autocount-service.ts` binds `realAutocountService` (`.real`). ✅
2. **Backfill** - `formula` column added NULL-default (migration `0005_autocount_mapping_formula.py`), behavior-preserving; mapping seed-if-absent only on a brand-new company (never reverts operator edits). ✅
3. **No hardcoded tenant-editable key** - entity keys are CODE constants (`entityLabel` humanizes them), never a lookup of a renameable key. ✅
4. **Permissions reach existing tenants** - mapping/formula/simulate endpoints reuse `autocount.companies.manage`; Review reuses `autocount.sync.read`. No new permission → no grant sweep needed. ✅
5. **Responsive** - E2E asserts 375px + 1280px on the review list and the mapping editor. ✅

## Verdict

All 14 slice-15 ACs **PASS**. No FAIL, no DEFERRED. DoD gate holds.
