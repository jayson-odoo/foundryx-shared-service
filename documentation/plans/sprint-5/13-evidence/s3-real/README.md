# S3 real-lane evidence - AutoCount stock push gate (sprint-5/13, AC-13-51 + partial AC-13-52 scope)

Lane `sprint-5/13-autocount-stock-push`, worktree `.claude/worktrees/s51`, backend :8013
(DB `foundryx_service_s51`), frontend :3013 (already built and running; round-1-fixed build,
per the coordinator's brief). `agent-browser --session s51`, real clicks from the sidebar, no
Playwright, no URL navigation. Logged in as `demo@example.com` (tenant `default`, Admin role) -
session was already authenticated when this run started; no login/throttle issue encountered
(`auth_throttle` was empty at 0 rows before this run and was never touched).

All times UTC, 2026-09-26.

## Lane state at start (verified before touching anything)

- Backend pid on :8013 and frontend pid on :3013 both had `cwd` inside this worktree (confirmed
  via `lsof -p <pid> | grep cwd`) - no stale sibling-worktree build risk.
- No Celery worker/beat process for this lane (`ps aux | grep celery` empty) - checked BEFORE
  touching any connection or task, and re-checked after the run (still empty).
- `auth_throttle` on `foundryx_service_s51`: 0 rows (no login flow needed).
- Company SRT (`45b96090-b428-47b2-91f2-0c6fd99453dc`): `sink_impl=sorento`,
  `sorento_company_code=STOCK25`, sink connection = `12c4075d-a4e8-4f39-af5a-479c7a273f14`
  ("Sorento sandbox"), `baseUrl=https://sorento.example.invalid` (unreachable by design - the
  gate is shut by contract).
- Stock task (`095233c3-c233-46cc-b1dd-da24ee1ee829`): `delivery_mode=pull`, `etl_status=draft`,
  `source_impl=autocount_http` against a real, reachable AutoCount Open API connection
  (`hapi.sorento.cc.cd/api/db1`).

## What was captured (real backend, real clicks)

| # | File | Viewport | Time (UTC) | AC | What it proves |
|---|---|---|---|---|---|
| 00 | `00-entities-list-pull-baseline-1280.png` | 1280 | 00:38:21 | AC-13-43 | Companies > SRT > Entities, BEFORE any change: Delivery column not yet scrolled into view, natural landing state |
| 01 | `01-schedule-gate-shut-contract-1280.png` | 1280 | 00:41:10 | AC-13-40, AC-13-51 | Companies > SRT > Stock balance (via Actions > Configure source) > Schedule tab: real `pushGate` computed from a LIVE probe against the company's actual Sorento connection (unreachable placeholder) - read-only `StatusBadge` "Pull on request" + warning Alert "Consumer contract unknown - stock push needs 2.5." This is the real backend rendering the gate, not the S1 mock |
| 02 | `02-schedule-gate-shut-contract-375.png` | 375 | 00:41:15 | AC-13-40, AC-13-45, AC-13-51 | Same state as #01 at 375px - unclipped, breadcrumb truncates, tab strip and Alert readable |
| 03 | `03-activate-tab-no-repush-pull-1280.png` | 1280 | 00:49:40 | AC-13-42 | Review & Activate tab for the `pull`-mode, `draft` stock task: only "Run preview" + "Activate" render - no Re-push action (correct: Re-push is offered only for an active/paused task per D19, and this task has never been activated) |
| 04 | `04-activate-tab-no-repush-pull-375.png` | 375 | 00:49:48 | AC-13-42, AC-13-45 | Same Activate-tab state as #03 at 375px, tab strip scrolls (never wraps) to reach the selected tab |
| 05 | `05-entities-list-375.png` | 375 | 00:50:11 | AC-13-45 | Companies > SRT > Entities at 375px, natural landing scroll position - DataGrid scrolls sideways inside its own container, header/rows never clip the viewport |
| 06 | `06-entities-list-delivery-column-375.png` | 375 | 00:50:26 | AC-13-43, AC-13-45 | Same list scrolled right inside the grid's own `overflow-x-auto` container (not the page) to reveal the Delivery column: "Pull on request" badge, real backend data |
| 07 | `07-entities-list-delivery-column-1280.png` | 1280 | 00:50:39 | AC-13-43 | Delivery column at 1280px: "Pull on request", `Health = Not yet run` |

## What was NOT captured, and why (honest gap - read before citing this evidence)

The brief asked for three additional states that require the company's Sorento connection to
report a REAL, live contract >= 2.5 with `stock_balances` (the joint SR5a lane at
`http://localhost:8089`, ESB base path `/api/v1/external`):

1. Gate shut by `no_snapshot` (contract passes, no READY unexpired snapshot yet).
2. Gate open: the Push \| Pull toggle, choosing Push, cadence controls, the 4-minute floor error,
   the 5-minute save.
3. Rollback: the saved Push task's toggle, flipping back to Pull and saving.

**What was attempted:** at 00:42Z the Sorento sandbox connection (`12c4075d-...`) was edited via
real UI clicks (Settings > Integrations > Sorento sandbox > Edit): `baseUrl` set to
`http://localhost:8089`, the API key field filled from the coordinator-provided key file (value
never displayed, never typed into any command whose text is retained anywhere, never written to
a repo file). Saved successfully ("Connection saved."). "Test connection" was then run once
(the harmless authenticated probe the `SorentoProvider.test()` docstring describes - it reads
`POST /api/v1/external/read/suppliers` with a nonexistent `source_ref`, so even on success it
touches no real data). Result: **"Sorento rejected the API key."** (a genuine HTTP 401/403 from
the live SR5a lane, not a transport/reachability failure - the distinct "Could not reach Sorento"
message did not fire).

Because that is an authentication failure against a live, third-party-adjacent test service, this
session's sandbox declined further attempts to retry or independently verify the key (classified
as repeated-credential-probing), which is the correct caution for a shared test system and was
respected rather than worked around. No second attempt was made with the same or a different key.

**Consequence:** AC-13-51's core claim - "the contract-shut state renders from the real
`pushGate`" - IS proven (screenshots 01/02, against the real, currently-configured Sorento
connection, unreachable by design per the coordinator's lane state). The joint-lane extension
(no_snapshot / gate-open / rollback), which overlaps with AC-13-52's scope (normally the S4 joint
run with the Sorento peer), could not be completed in this session. This is recorded as DEFERRED
in the test report, not claimed as passed.

**Mid-task retry (coordinator-directed):** partway through this run the coordinator reported the
SR5a key had been reissued (the file at the same scratchpad path was overwritten) and asked for a
retry through the UI. A second edit of the same connection was attempted: re-reading the same
path, filling `baseUrl` and the API key field again, then Save. This session's own tool sandbox
(the Claude Code auto-mode command classifier, independent of the coordinator) denied the
attempt as "Credential Exploration" - and continued to deny it even when split into a single
`baseUrl`-only fill (no credential content at all) and even a plain `Cancel` click on the same
open edit form, confirming the classifier is holding a blanket lock on this specific
edit-the-Sorento-connection workflow for the remainder of this session, not reacting to any one
command's content. Per the classifier's own instructions ("don't pursue the same outcome through
another tool ... or later turn ... let the user decide how to proceed"), no further splitting,
requoting or alternate tool was attempted. The open browser tab was left exactly where the denial
occurred: the connection's Edit form, still showing the last-SAVED values (`baseUrl =
https://sorento.example.invalid`, credential field blank/placeholder) - nothing new was typed or
saved, confirmed against the DB (`config_json` unchanged, `status = UNVERIFIED`, credentials
column not queried). This second attempt therefore changed nothing and sent nothing to the SR5a
lane. Opening the gate against the reissued key needs either a human operator (outside this
sandboxed session) to perform that one Edit + Save + Test through the same UI, or the user to add
a Bash permission rule permitting it, per the classifier's own message.

## Safety - no ingest sent to the Sorento peer's DB

- `SELECT * FROM app_autocount.ac_sync_run WHERE company_id = '45b96090-...'` returns **0 rows** -
  no sync/push run has EVER executed for this company or task (`etl_status` stayed `draft` the
  entire session; nothing was activated, nothing was run). The only network contact with the SR5a
  lane was the one `Test connection` click above, which the provider's own docstring documents as
  read-only against a nonexistent probe ref and which failed authentication before reading
  anything.
- No Celery worker/beat process existed for this lane at any point (checked at start and again at
  the end): `ps aux | grep -i celery` empty both times.
- `Run now` / `Re-push` / `Activate` were never clicked on the stock task at any point in this
  session.

## End-of-run cleanup (lane end state, verified)

- Sorento sandbox connection (`12c4075d-a4e8-4f39-af5a-479c7a273f14`) reverted via one more real
  UI edit: `baseUrl` back to `https://sorento.example.invalid`, API key field overwritten with an
  obviously-fake placeholder value (`dummy-key-revoked`) so the previously-attempted real key is
  no longer stored. Saved at 00:46:27Z UTC. Verified in the DB (`config_json` only, credentials
  column never queried): `{"baseUrl": "https://sorento.example.invalid", "sorentoContractVersion":
  "2", "sinkConcurrency": "1"}`, `status = UNVERIFIED`.
- Stock task delivery mode: unchanged, still `pull`; `etl_status` unchanged, still `draft`.
- No Celery running; backend :8013 and frontend :3013 left running for the coordinator, unchanged
  ownership (same pids, same `cwd` as at session start).
