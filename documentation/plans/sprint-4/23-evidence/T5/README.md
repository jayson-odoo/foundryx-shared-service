# T5 - Deferred actions (the grace-window engine) - evidence run

Branch `sprint-4/23-T5-deferred-actions` (worktree `.claude/worktrees/s23`, integration checkout
at `9d73de4`). Own stack: Postgres db `foundryx_service_s23`, backend on `:8003`
(`DATABASE_URL=postgresql://foundryx:foundryx@localhost:5432/foundryx_service_s23`,
`CELERY_TASK_ALWAYS_EAGER=true`), frontend prod build on `:3002`
(`NEXT_PUBLIC_BACKEND_API_URL=http://localhost:8003`). `agent-browser --session t5` (primary
tab) + `--session t5b` (second tab, journey 5). Logged in as `demo@example.com` / `demo1234`
(default tenant Admin). Every test user is timestamped (`T5 Test User 1788556536-<n>`) via real
sidebar navigation + clicks (User Management > Users > Add user), never a typed URL for
navigation (only used to reference an already-visited record id, matching the pattern the T4
evidence run used).

## Run log (real clicks, both widths)

1280px (primary run):
1. Created 5+ timestamped test users via `Add user` (User Management > Users).
2. Opened a record, gear > Trash - countdown replaced the primary area, no dialog
   (`01-record-delete-countdown-1280.png`). Left it to lapse - the page returned to the list
   with the record gone from Active (`03-record-delete-lapsed-back-to-list-1280.png`).
3. Opened a second record, gear > Trash > Cancel (well inside the window) - the Edit button
   was restored, same URL, no navigation (`04-record-delete-cancel-restored-1280.png`).
4. List row's own "…" > Trash - a sonner toast with the countdown + Cancel appeared, the row
   dimmed (`05-row-delete-toast-dimmed-1280.png`); Cancel restored it
   (`06-row-delete-cancel-restored-1280.png`).
5. Selected 3 rows > bulk Actions > Trash - ONE toast read "Trashing 3 users in Ns", all 3
   rows dimmed (`07-bulk-delete-3-rows-count-1280.png`). **Live bug found + fixed** (see
   below) - `08-bulk-delete-committed-fixed-1280.png` shows all 3 correctly removed after the
   fix; `09-trashed-view-1280.png` confirms all 3 (plus every other trashed test user) sit in
   the Trashed view, restorable.
6. Settings > General > Deferred actions: set "Delete countdown" to 3s, saved
   (`10-settings-window-change-1280.png`) - a fresh Trash showed "Trashing in 3s"
   (`11-settings-3s-countdown-1280.png`) and lapsed back to the list at ~3s
   (`12-settings-3s-lapsed-1280.png`).
7. Two tabs on the SAME record: tab A started Trash (`13-second-tab-A-started-1280.png`,
   "Trashing in 20s"); tab B (already on the record, different `agent-browser` session, same
   login) picked up the SAME countdown mid-flight ("Trashing in 9s" a few seconds later,
   `14-second-tab-B-parity-1280.png`) - the countdown bar shows the correctly-drained fraction,
   not a fresh 20s.
8. A record's Trash was started then the tab was closed (`agent-browser close`) before the
   window lapsed. After waiting past the window, a `GET /api/v1/pending-actions/current` call
   (the same lazy-commit path the frontend's own poll uses) showed the row `committed`
   (`15-tab-closed-during-window-current-committed.json`) - the action applied even though no
   UI was watching it (no beat process running in this dev setup; the plan explicitly allows
   this as the eager-dev equivalent of the beat sweep).

375px (mobile):
9. Record delete countdown replaces the primary area, no clipping (`16-record-delete-countdown-375.png`).
10. Row delete toast + dimmed row (`17-row-delete-toast-dimmed-375.png`).
11. Bulk delete of 3 rows naming the count, all 3 dimmed (`18-bulk-delete-3-rows-count-375.png`).
12. Settings > General deferred-actions card renders cleanly, no clipping (`19-settings-375.png`).

## Live bug found + fixed during this run (regression-pinned)

**Bulk commit only polled the FIRST entity in the batch.** `useDeferredAction`'s `pollOnce`
read `current()` for `parked.entities[0]` only, reasoning "every row shares the same
`commit_at`, one representative read is enough." Under eager dev there is **no beat
process** - `current()` is what lazily commits an overdue row, and it only touches the ONE
record it is asked about. So a 3-row bulk delete committed only the first row (via the poll
reading it) and left the other two parked forever server-side - screenshot
`08-bulk-delete-committed-1280.png` shows the bug live (only 1 of 3 rows actually removed,
`2 selected` left over in the toolbar). Fixed: `pollOnce` now checks **every** entity in the
batch (`Promise.all`), and the whole countdown only settles once every row has a non-pending
outcome. Re-verified live (`08-bulk-delete-committed-fixed-1280.png`, all 3 gone) and pinned
with a new test (`hooks/use-deferred-action.test.ts`, "bulk commit polls EVERY entity, not
just the first").

## AC verdicts

| AC | Verdict | Evidence |
|---|---|---|
| AC-DLA-37 (pending_actions table + tenant_settings columns) | PASS | migration `65458ac6203e`, `tests/test_deferred_actions.py` |
| AC-DLA-38 (registry + first-party actions) | PASS (16 registered, see report) | `app/deferred_actions/registry.py`, `handlers.py` |
| AC-DLA-39 (park/idempotent/409/400/403) | PASS | `tests/test_deferred_actions.py` (park tests) |
| AC-DLA-40 (cancel before/after, current lazy-commit, cross-tenant 404) | PASS | same file (cancel/current/cross-tenant tests) |
| AC-DLA-41 (beat sweep, isolated per-row transaction) | PASS | `worker.py pending_actions_commit_due_task`, sweep-isolation test; step 8 above (lazy-commit path) |
| AC-DLA-42 (windows from settings, Settings > General fields) | PASS | steps 6/9-12; `test_window_seconds_read_from_tenant_settings` |
| AC-DLA-43 (ResourceAction.deferred, hook state machine, carve-outs) | PASS (with disclosed deviations, see report) | `hooks/use-deferred-action.ts` + tests; `confirm-carve-outs.inventory.test.ts` |
| AC-DLA-44 (form-surface countdown replaces primary, no dialog, Escape no-op) | PASS | steps 2-3, `resource-form.deferred.test.tsx` |
| AC-DLA-45 (row toast + dim; bulk one action naming the count) | PASS | steps 4-5, 10-11; `data-grid-table.pending-dim.test.tsx` |
| AC-DLA-46 (tab-closed commits; second-tab parity) | PASS | steps 7-8 |
| AC-DLA-47 (confirm-action-dialog reserved to the two carve-outs) | PASS (3rd disclosed exception, see report) | `confirm-carve-outs.inventory.test.ts` |

No Playwright used anywhere in this run (D15).
