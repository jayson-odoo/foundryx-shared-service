# S1 mock evidence - AutoCount stock push gate (sprint-5/13, AC-13-50)

Lane `sprint-5/13-autocount-stock-push`, worktree `.claude/worktrees/s51`, backend :8013
(DB `foundryx_service_s51`), frontend :3013 (`npx next start -p 3013` after
`rm -rf .next && npm run build`). `agent-browser --session s51`, real clicks from the
sidebar, no Playwright. Logged in as `demo@example.com` (tenant `default`, Admin role).

## What is mocked vs real

Per plan section 2.5 / AC-13-44, S1 opens ONE scoped PHASE 1 MOCK overlay
(`withPhase1PushGateMock`, `service_frontend/services/autocount-service.mock.ts`) bound by
`services/autocount-service.ts` for the duration of this slice: `getEtlTask` /
`updateEtlTask` / `activateEtlTask` / `pauseEtlTask` / `resumeEtlTask` gain a
client-computed `pushGate` on a `stock_balance` task (the backend has no `push_gate`
field yet - that is S3), and `setDeliveryMode` refuses the push flip while it is
shut. Every OTHER AutoCount surface in this run is the REAL, already-shipped backend
(company create, connections, Source-tab Test, Mapping preset, etc.) - the module was
already live before this plan, so a full mock-mode run was neither possible nor
representative; only the NEW pushGate behaviour needed a stand-in.

The mock's "gate open" state is reached by the SAME sentinel-company-code convention
`brandContractGateFor` already uses for `brand`/`BRANDS23` (`services/autocount-service.mock.ts`,
`stockPushGateState`): a company on the Sorento sink whose `sorentoCompanyCode` is
`STOCK25` reads as a consumer that advertises contract 2.5; anything else (or a
non-Sorento sink) reads as the shut, contract-too-low state. `setMockPushGate` is the
Vitest-only seam for the third (`no_snapshot`) state and is not used in this browser
run (see "Deferred" below).

## Lane data setup (not evidence; prerequisite setup only)

- `SRT` company created against a REAL `sql_database` connection pointed at the lane's
  own Postgres (`foundryx_service_s51`) - a genuine, reachable connection, not a fixture.
- A `stock_balance` task added via the real "Add entity" picker (real click), Source tab
  connection = a REAL `autocount` (no-auth) connection at `https://hapi.sorento.cc.cd/api/db1`
  (the same open REST API this repo's other AutoCount evidence runs use) - Test on the
  main endpoint and both lookups genuinely succeeded (68,830 rows, 69 pages) before Save
  unlocked (AC-08-20's existing save gate, unaffected by this plan).
- A `sorento`-provider connection ("Sorento sandbox") with a placeholder API key - used
  only to flip the company's sink target between `logging` (shut) and `sorento` +
  `STOCK25` (open); never actually pushed to (the module has no `stock_balance` sink
  path until S2, so Activate/Run stay legitimately blocked today - see "Deferred").

## Screenshots (numbered = run order)

| # | File | AC | What it shows |
|---|---|---|---|
| 01 | `01-schedule-gate-shut-1280.png` | AC-13-40 | Company on `logging` sink (contract absent): read-only `StatusBadge` "Pull on request" (the CURRENT mode, not hardcoded) + warning Alert "Consumer contract 2.4 - stock push needs 2.5." |
| 02 | `02-schedule-gate-open-toggle-1280.png` | AC-13-40 | Company flipped to Sorento + `STOCK25` (real click: Overview > Edit > Push delivery target > Sorento sandbox > code `STOCK25` > Save): the Push \| Pull-on-request `ToggleGroup` renders instead of the badge, no warning line. `AC_PULL_ONLY_ENTITY_TYPES` is gone - this is driven by `task.pushGate` alone. |
| 03 | `03-schedule-push-reveals-cadence-1280.png` | AC-13-41 | Clicking the Push segment (real click, Edit mode) reveals the Incremental / Reconcile / Delete guard cards with their saved values. |
| 04 | `04-schedule-floor-4-error-1280.png` | AC-13-20/41 | Typing `4` into Incremental "Every" shows "At least 5 minutes without a watermark column." live, no save required. |
| 05 | `05-schedule-floor-5-ok-1280.png` | AC-13-20/41 | Typing `5` clears the error (the FE mirror floor is 5, D11). |
| 06 | `06-entities-delivery-column-1280.png` | AC-13-43 | Companies > SRT > Entities: the existing Delivery column renders "Pull on request" for the stock task (no code change; the DataGrid column already reads `deliveryMode`). |
| 07 | `07-schedule-gate-shut-375.png` | AC-13-45 | Same shut state as #01 at 375px - unclipped, breadcrumb truncates, tab strip and content readable. |
| 08 | `08-schedule-gate-open-375.png` | AC-13-45 | Same open-gate toggle as #02 at 375px. |
| 09 | `09-schedule-push-cadence-375.png` | AC-13-45 | Cadence cards stack in a single column at 375px (no side-by-side overflow). |
| 10 | `10-schedule-floor-4-error-375.png` | AC-13-45 | Floor error at 375px, unclipped. |
| 11 | `11-activate-tab-375.png` | AC-13-45 | Review & Activate tab at 375px - the tab strip scrolls (never wraps) to reach it. |
| 12 | `12-entities-list-375.png` | AC-13-45 | Entities list `DataGrid` scrolls sideways inside its own container at 375px, header/rows never clip the viewport. |

## AC ids covered live in this run

AC-13-40, AC-13-41, AC-13-43, AC-13-45 (all at both 1280 and 375), plus the
foolproof-UI/no-hardcoded-entity-list intent behind AC-13-42/D18 (confirmed by #02:
the toggle appears the moment the BACKEND company state changes, no frontend code
touched between #01 and #02).

## Deferred / not captured live (honest gaps)

- **AC-13-42 "preview unavailable" neutral empty state** (`pullOnlyPreviewUnavailable`,
  `preview-pull-only-empty-state` test id): only reachable live when `task.pushGate` is
  shut AND a dry-run has been attempted. With the gate OPEN (as set up for #02-#06) the
  Activate tab's Run preview correctly shows the RAW backend reason instead ("No
  consumer is configured for this company... Point the company at Sorento first") -
  which is itself the correct AC-13-42 "keys off pushGate, not entity type" behaviour,
  but is a DIFFERENT branch than the neutral empty state. Reverting to the shut state
  and running Preview would show the neutral state, but was not captured as a separate
  screenshot in this pass (budget). Covered by
  `activate-tab.test.tsx`'s existing + new (D18) unit tests instead.
- **AC-13-42 Re-push for an ACTIVE `autocount_http` task**: activating the stock task
  needs a passing "Run preview", which needs the module's Sorento sink path for
  `stock_balance` - genuinely absent until S2 (`sinks_sorento._ENTITY_PATH` has no
  entry yet, per the plan's own "Verified baseline"). Run preview correctly shows
  "Nothing to preview... Point the company at Sorento first" for this reason even with
  the push gate open, so Activate stays disabled today BY DESIGN. Re-push's
  `autocount_http` eligibility (D19) is proven by `activate-tab.test.tsx`'s new test
  ("renders for an active OPEN REST API (autocount_http) task too") using a
  synthetic active task instead of a live one.
- **`setMockPushGate`'s `no_snapshot` state**: exercised only in Vitest
  (`services/autocount-service.mock.push-gate.test.ts`), not in this browser run - the
  sentinel-code convention only reaches "open" or "contract-shut" live; forcing
  `no_snapshot` live would need either the seam wired to a reachable UI control (not
  built - it is a Vitest-only seam per the plan) or a real pull-snapshot flow, out of
  this slice's scope.
- The company/task SETUP steps above used a few direct API calls (creating the two
  connections, and two of the sink-target flips between #06 and #07) rather than pure
  clicks, purely to keep the run inside a reasonable time budget - every SCREENSHOT
  itself was reached by a genuine, freshly-loaded page after a real state change, and
  the sink-target flip WAS also demonstrated by real clicks once (Overview tab, Edit >
  combobox > combobox > text > Save, between #01 and #02).
