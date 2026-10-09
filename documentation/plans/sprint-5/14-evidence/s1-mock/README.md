# sprint-5/14 S1 - Document feeds tab (mock) - agent-browser evidence

Run log for AC-14-90..95 and AC-14-E1, against the lane stack (`.claude/worktrees/s60`,
backend :8014, frontend :3014, `foundryx_service_s60`), real clicks via the `agent-browser`
CLI (`--session s60`), never navigation by URL except the two initial page opens. The
backend has NO `doc-feeds` router yet (S2..S4) - every doc-feed call in this run goes
through the `withPhase1DocFeedMock` overlay (`autocount-service.mock.ts`), which now reads
the REAL company (`sinkImpl`/`sorentoCompanyCode`) and the REAL `autocount` connections
(`listApiConnections()`) for the contract gate and the eligible-connections picker - only
the doc-feed rows/runs/issues/backfills themselves are in-memory mock state.

## Setup (once)

1. Logged in as `demo@example.com` (tenant Admin) on `localhost:3014`.
2. App Store > AutoCount ESB > Actions > Install (module was not installed on this lane's
   fresh DB).
3. Settings > Integrations > Connect integration > provider `AutoCount`, name
   "AutoCount open API", auth "No auth", base URL `https://hapi.sorento.cc.cd/api/db1`
   (the live vendor wrapper, per plan section 1) - Create.
4. Settings > Integrations > Connect integration > provider `Sorento`, name "Sorento CRM",
   base URL `http://localhost:8107` (not actually reachable in this mock run - the S1
   overlay never calls it), a placeholder API key - Create.
5. AutoCount > Companies > Connect company > Source "AutoCount API", connection
   "AutoCount open API", label "Sorento Sdn Bhd" - Create company.
6. Company > Overview > Edit > Push delivery target "Sorento", Sorento consumer connection
   "Sorento CRM", Sorento company code `SRT` (plan section 0, V9: `SRT` is the sentinel the
   S1 mock overlay reads as an OPEN 2.7 gate; any other code, or no Sorento sink at all,
   reads shut) - Save company.

## Steps and evidence

| # | Screenshot | What it shows | AC |
|---|---|---|---|
| 1 | `01-unconfigured-1280.png` | Document feeds tab, all three feeds `Off`, "Never run", Waiting/Failed 0, Backfill `-` | AC-14-90 |
| 2 | `02-configure-dialog-1280.png` | Configure dialog, no connection chosen yet - Mode offers ONLY `Off` (foolproof-UI: Dry run/Push are ABSENT, not disabled) | AC-14-91 |
| 3 | `03-configure-gate-shut-1280.png` | Connection chosen on a company with NO Sorento push target - warning Alert "This company has no ready Sorento push target yet.", Mode still only `Off` | AC-14-91 |
| 4 | `04-configure-gate-open-1280.png` | Same dialog after the company's push target is set to Sorento + code `SRT` - gate open, Mode now offers Off / Dry run / Push | AC-14-91 |
| 5 | `05-dry-run-with-runs-1280.png` | Saved Dry run + Run now - feed row shows outcome Success, "Runs"/"Waiting and failed documents" lists still empty (dry run never writes runs/issues in this mock, matching D9's "dry run never advances" intent extended to the demo state) | AC-14-90, 94 |
| 6 | `06-push-with-cursor-issues-1280.png` | Reconfigured to Push, Run now - Covered through `2026-09-29`, Waiting 1 / Failed 1, a Poll row in Runs (window, fetched, counters, outcome), two rows in Waiting and failed documents with real `field: message` errors (`itemCode`/`docDate`) | AC-14-90, 92, 94 |
| 7 | `07-push-with-cursor-issues-375.png` | Same state at 375px - the three embedded lists stack full-width, tab bar and cards are not clipped, DataGrid's own horizontal scroller carries the extra columns | AC-14-95 |
| 8 | `08-backfill-dialog-default-1280.png` | Backfill dialog, no open backfill - Dry run switch ON by default, From/To defaulting to `2023-01-01` / today | AC-14-93 |
| 9 | `09-backfill-running-1280.png` | Started (dry run) - `JobProgress` in DAYS ("day 456 of 1368"), Stop control | AC-14-93 |
| 10 | `10-backfill-done-1280.png` | Same backfill, later poll - feed row's Backfill cell reads `Done` (the mock's demo ticker advances a chunk per view read and flips to done at the total) | AC-14-90 |
| 11 | `11-backfill-stopped-1280.png` | A second backfill, started then Stopped immediately - feed row's Backfill cell reads `Stopped` | AC-14-90, 93 |
| 12 | `12-actions-menu-stopped-backfill-1280.png` | Row `ActionMenu` open on the stopped-backfill row - Configure / Run now / Run sweep now / Backfill… / Resume backfill / Discard backfill, each present because its OWN state allows it (never shown-but-disabled) | AC-14-92 |
| 13 | `13-configure-dialog-375.png` | Configure dialog at 375px - not clipped, Mode `ToggleGroup` wraps cleanly | AC-14-95 |
| 14 | `14-backfill-dialog-stopped-375.png` | Backfill dialog at 375px (backfill `stopped`, so it's back to the start-a-new-one form) - not clipped | AC-14-95 |

Row-actions convention note (E1): `ActionMenu` is a closed-until-clicked Radix dropdown
(the SAME shape `use-entities-list-config.tsx`'s row menu already uses) - every click
sequence above opens the row's "Actions" ("…") trigger before selecting a menu item, real
clicks throughout (`agent-browser click`), never a direct URL to a sub-state.

Console: `agent-browser console` showed no errors other than the harmless
`next-auth CLIENT_FETCH_ERROR`-shaped noise absent entirely on this lane (checked clean at
steps 6 and after the final rebuild).

## Known S1 mock simplifications (disclosed, not backend behaviour)

- The contract gate and the connection eligibility ARE read from the real company/real
  `autocount` connections; the gate's PASS/FAIL rule itself (sentinel code `SRT` = open,
  everything else shut) is a client-side stand-in for the real `GET .../external/contract`
  probe S2's `doc_feed_gate_error` will make.
- `updateDocFeed` does not re-enforce the gate server-side in the mock (the Configure
  dialog's own ToggleGroup already only offers Dry run/Push when the gate is open, so the
  save path is never reachable with a shut gate through the real UI); S2 adds the real
  422 at save time and at run time (`CONTRACT_GATE`).
- Runs/issues counters and the two seeded issue rows (`DO-900001` retryable, `DO-900002`
  failed) are fixed, deterministic demo data, not a real vendor/CRM round-trip - S5's
  evidence run replaces this with the live vendor (`db1`) and a real CRM copy on `:8107`.
- The backfill's day-by-day progress is a per-view-read ticker (advances a fixed chunk
  every time the tab polls), not a real Celery job walking 2023-01-01 forward one day at a
  time - S2/S4 land the real `autocount_doc_feed_backfill` job.
