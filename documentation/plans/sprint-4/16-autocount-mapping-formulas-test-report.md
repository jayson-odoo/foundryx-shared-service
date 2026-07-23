# 16 — AutoCount mapping transform formulas + simulators — Test Execution Report

> **Contract:** `16-autocount-mapping-formulas-acceptance-criteria.md`
> **Branch:** `sprint-4/14-autocount-sorento-masters`
> **Date:** 2026-07-22
> **Stack under test:** Next :3001 → FastAPI :8001 → Postgres (live, seeded). Real-click E2E +
> backend/FE unit suites incl. a client↔server parity harness.

## Automated evidence (green)

| Suite | Result |
|-------|--------|
| Backend `test_autocount*` + `test_sorento_sink` | **295 passed** (`python -m pytest`) |
| Frontend vitest (full) | **1079 passed** — incl. `lib/autocount-formula.test.ts`, `lib/autocount-formula.parity.test.ts`, `autocount-formula-builder.test.tsx`, `date-format-tool.test.tsx`, `mapping-simulator.test.tsx` |
| **E2E** `e2e/autocount-mapping.spec.ts` | **2 passed** (real clicks vs live stack) |

## E2E journey — Formula builder + per-formula + whole-mapping simulation

- **User story:** As an operator I express a T/F transform as a formula, watch it evaluate live against
  a mock value, and simulate a whole AutoCount record → the whole Sorento record before a sync uses it.
- **Scenario:** `AC-15-40..44 / AC-16-10..31` in `e2e/autocount-mapping.spec.ts`.
- **Precondition:** A dedicated timestamped tenant with `autocount` installed; a real `erp` connection
  (scripted vendor for login/discovery only) + a connected company. The mapping surface reads NO vendor;
  the whole-mapping simulator runs the REAL MappingEngine over a hand-typed mock record and writes nothing.
- **Steps (real clicks):** sign in → connect + Test the AutoCount connection → Connect company →
  Entities ▸ Supplier ▸ Configure mapping → confirm the mapping table is **read-only** (AutoCount field
  / Transform / Sorento field; no comboboxes; Edit button present) → **Simulate mapping** (read mode):
  replace the mock JSON with a supplier record (`AccNo/CompanyName/EmailAddress/IsActive:"T"` +
  `Data[0].AutoKey/LastModified`) → **Run simulation** → read the Sorento record out → close → **Edit**
  → set row 1's Transform to **Boolean** → **Build formula** → read the pre-filled expression → Testing
  tab: type `T` then `F` → read the live output → **Apply** → **Save**.
- **Expected:** read-only-until-Edit; the whole-mapping sim returns the projected Sorento record with
  the `"T"` flag coerced to a real boolean and per-field results, writing nothing; the Boolean preset
  pre-fills `if(value == "T", true, false)`; the per-formula tester shows `T`→`true`, `F`→`false` live;
  Apply + Save persist through the form's single dirty-guarded save.
- **Actual:** PASS.
  - `sorento-output` contained `"code": "300-A001"`, `"name": "Acme Supplies"`, **`"is_active": true`**;
    `field-results` table shown; "This record maps cleanly." (AC-16-30/31).
  - Formula builder opened pre-filled with `if(value == "T", true, false)`; `formula-status` = "Valid
    formula" (AC-16-10/11).
  - `client-output` showed `true` for input `T` and `false` for input `F` — the formula genuinely
    evaluates (AC-16-20).
  - Save produced `Field mapping saved.` (AC-15-41).
- **Remarks:** Verified responsive at **375px and 1280px** on the mapping editor (no horizontal page
  scroll). The whole-mapping mock shape was validated against the real `MappingEngine.project_document`
  before authoring so the assertion reflects the true pipeline output.

## AC verdicts

| AC | Verdict | Evidence |
|----|---------|----------|
| AC-16-01 Safe evaluator, client↔server parity | **PASS** | `lib/autocount-formula.parity.test.ts` + backend golden-matrix agreement (`test_autocount_pipeline.py` `:3892`); hand-written parser, no eval/Jinja. |
| AC-16-02 Grammar covers the need + quirks | **PASS** | `lib/autocount-formula.test.ts` + backend evaluator matrix; `if(value == "T", true, false)`→bool verified live in E2E. |
| AC-16-03 Fails CLOSED and named | **PASS** | `test_autocount_pipeline.py` AC-16-03 (`:3922`, `:3930`, `:4030`, `:4050`) — unknown name/fn/arity = 422 at save; `number('Acme')` fails that field named at eval. |
| AC-16-04 Output coerced to Sorento field type | **PASS** | `test_autocount_pipeline.py` AC-16-04 (`:3996`) — a boolean field fed a string is a per-field error, not a wrong value. |
| AC-16-10 Preset pre-fills the formula | **PASS** | E2E: Boolean preset → `if(value == "T", true, false)` in the builder; `autocount-formula-builder.test.tsx`; `applyPreset` in `autocount-meta.ts`. |
| AC-16-11 Builder discoverable + safe | **PASS** | E2E opens the builder (Build affordance), live parse validation shows "Valid formula"; `autocount-formula-builder.test.tsx`. |
| AC-16-12 Foolproof — searchable, read-only-until-Edit | **PASS** | E2E: builder only reachable under the form's Edit toggle; category/search are `SearchSelect`/inputs; per-function reference panel (not procedural copy). `autocount-formula-builder.test.tsx`. |
| AC-16-13 Functions grouped by type + searchable | **PASS** | `autocount-formula-builder.test.tsx` (category `SearchSelect` String/Number/Boolean/Date/Logical + search + insert-at-caret); backend `function_catalog`. |
| AC-16-14 Date-format tool (input + output tokens) | **PASS** | `date-format-tool.test.tsx` (fixed token vocabulary, live sample preview); backend date parity anchor case (`test_autocount_pipeline.py` `:3912`). **Not driven by the E2E** (shown only under the Date category; covered by unit + parity). |
| AC-16-15 Builder explains each function | **PASS** | `autocount-formula-builder.test.tsx` (reference panel: signature/args/description/example); `function-reference` testid in `autocount-formula-builder.tsx`. |
| AC-16-20 Per-formula live test with a mock value | **PASS** | E2E: `T`→`true`, `F`→`false` live in the Testing tab (`client-output`); `autocount-formula-builder.test.tsx`. |
| AC-16-21 Server confirms same result (parity) | **PASS** | Backend test-formula endpoint parity (`test_autocount_pipeline.py` `:4086`) + `lib/autocount-formula.parity.test.ts`. **E2E exercised the client preview only** (the "Check on server" click was not driven — server parity is robustly unit-covered). |
| AC-16-30 Whole-mapping sim → whole Sorento record | **PASS** | E2E: mock record → `sorento-output` with every mapped field + `field-results`; backend whole-mapping simulate (`test_autocount_pipeline.py` `:4104`, `:4130`), `mapping-simulator.test.tsx`. |
| AC-16-31 Legible record-in → record-out, writes nothing | **PASS** | E2E: AutoCount-in beside Sorento-out, "This record maps cleanly.", nothing written (pure preview); `mapping-simulator.test.tsx`. |
| AC-16-32 Simulator may seed a REAL sample | **DEFERRED** | Optional nice-to-have per the AC ("if it complicates the slice, a hand-entered/pasted mock record satisfies AC-16-30"). Not implemented — the simulator takes a hand-entered/pasted mock (the sanctioned fallback), which AC-16-30 confirms is sufficient. No "pull one real AutoCount record" button in `mapping-simulator.tsx`. |

## DoD gate

1. **Mock swapped to real** — `autocount-service.ts` binds `.real`; the whole-mapping simulator calls the real backend `…/mapping/simulate` (real `MappingEngine`), the formula tester calls the real `…/test-formula`. ✅
2. **Backfill** — `formula` column NULL-default (migration `0005`), behavior-preserving; a row with no formula runs its exact named transform. ✅
3. **No hardcoded tenant-editable key** — formulas operate on `value`; entity/field keys are code constants. ✅
4. **Permissions reach existing tenants** — `…/mapping/{functions,test-formula,simulate}` reuse `autocount.companies.manage`; no new permission introduced. ✅
5. **Responsive** — E2E asserts 375px + 1280px on the mapping editor. ✅

## Verdict

14 of 15 slice-16 ACs **PASS**; **AC-16-32 DEFERRED** (explicitly optional; the hand-entered mock the
AC accepts as sufficient is implemented). No FAIL. DoD gate holds.
