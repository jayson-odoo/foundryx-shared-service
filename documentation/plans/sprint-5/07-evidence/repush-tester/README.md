# AC-07-25 evidence - "Re-push all" as a server-parked deferred action

Lane `sprint-5/07-autocount-so-ref-repush`, worktree `.claude/worktrees/s36`, **HEAD `bcbad58a`**
(fixed commit after review round 2, D2/D10: typed-confirm dialog replaced by a
`DeferredActionButton` grace-window; activity recorded after commit with the parking actor;
in-flight guard re-checked before commit). Backend :8006, frontend :3006, DB
`foundryx_service_s36`.

**Note:** an earlier partial run against `4c8dbb80` (the old typed-confirm `AlertDialog` build)
was captured in this same directory and has been fully replaced - those screenshots are deleted.
This is the ONLY evidence run for AC-07-25 in this directory. (`../repush/` and `../repush-mock/`
are the coder's own earlier phase-1/phase-2 evidence for the same superseded typed-confirm build
and are banner-marked per the amended AC-07-25 wording; not touched by this tester run.)

## Stack (fresh build, own pids)

```
cd service_frontend && rm -rf .next && npm run build && npx next start -p 3006   # NEVER npm start
cd service_backend && .venv/bin/uvicorn app.main:app --port 8006
agent-browser --session s36-tester
```
Both ports (`3006`, `8006`) were confirmed free (`lsof -nP -iTCP:<port> -sTCP:LISTEN`) before
starting. Backend pid 5608, frontend pid 5639 - both killed by this session at the end (no bare
`pkill`). Only this session's `agent-browser --session s36-tester` browser was used; closed with
plain `close` (never `--all`).

## Navigation (real clicks from `/`, logged in `demo@example.com` / `demo1234`)

Sidebar `AutoCount` -> `Companies` -> row "ETL Demo Co" -> `Entities` tab -> `Customer` row's
kebab `Actions` (had to `scrollintoview` it - the entities table is wider than the 1280px
viewport, so the Actions column sits off-screen right at both viewports tested) ->
`Configure mapping` -> `Review & Activate` tab. (The entity row itself has no navigating
`onClick`/`href` - only the kebab menu opens the task editor; noted for the record, not an
AC-07-xx defect.)

## 1. Tab with the action (screenshots)

`01-tab-with-action-1280.png` / `01-tab-with-action-375.png` - Review & Activate tab, destructive
"Re-push all" button next to Re-run preview / Pause / Run now, at both viewports. Baseline DB:
`ac_row_hash` count for `(tenant=00000000-0000-0000-0000-000000000001, company=ETL Demo Co
53c93000-d878-4a65-9693-1135064f1285, entity_type=customer)` = 0 (coder's own prior runs had
already cleared it); `next_reconcile_at = 2026-09-10 16:47:27.969615+09`.

## 2. Countdown with Cancel (no dialog) - screenshots

Clicked "Re-push all": the button is replaced in place by a `DeferredCountdown` reading
"Re-pushing all in Ns" with a decaying progress bar and a `Cancel` button - **no dialog, no typed
input, matching AC-07-22 exactly**. `02-countdown-with-cancel-1280.png` /
`02-countdown-with-cancel-375.png` - Cancel is fully visible and NOT clipped at 375px.

## 3. Cancel run - proves nothing changed

Seeded 2 rows first so a no-op count would be a real proof, not a 0-to-0 coincidence:

```sql
insert into app_autocount.ac_row_hash (tenant_id, company_id, entity_type, source_ref, row_hash, last_seen_at)
values
  ('00000000-0000-0000-0000-000000000001', '53c93000-d878-4a65-9693-1135064f1285', 'customer', 'TESTER-S36-CANCEL-01', 'cafebabe0000000000000000000000000000c1', now()),
  ('00000000-0000-0000-0000-000000000001', '53c93000-d878-4a65-9693-1135064f1285', 'customer', 'TESTER-S36-CANCEL-02', 'cafebabe0000000000000000000000000000c2', now());
```

Clicked "Re-push all", then immediately clicked "Cancel" (before the ~10s destructive window
lapsed). Result: button reverted to "Re-push all" instantly, no toast (confirmed - no network
call to any repush/pending-actions POST after the cancel), and DB proof:

- `ac_row_hash` count for `(company, customer)`: **2 before, 2 after (unchanged)**.
- `pending_actions` row for this entity: latest is `status='cancelled'`, `ended_at
  2026-09-10 18:11:09.395` BEFORE its own `commit_at 18:11:11.980` (cancelled inside the window).
- `select count(*) from pending_actions where entity_id=... and status='pending'` = **0** (no
  pending action left).

(A first attempt at this Cancel proof, made with 0 rows seeded and while I was still taking two
viewport screenshots between click and Cancel, missed the ~10s window and the action committed
instead - `pending_actions` row `d5fab833-...` shows `status='committed'`. That is the correct
engine behaviour, not a bug: a Cancel that arrives after the window closes loses to the commit
(same rule the pytest suite pins for a late `cancel()` call). Recorded here for transparency; the
clean Cancel proof above is the one to read.)

## 4. Full run - window lapses, server commits

Re-seeded 3 rows for the "state exactly what you inserted" requirement:

```sql
insert into app_autocount.ac_row_hash (tenant_id, company_id, entity_type, source_ref, row_hash, last_seen_at)
values
  ('00000000-0000-0000-0000-000000000001', '53c93000-d878-4a65-9693-1135064f1285', 'customer', 'TESTER-S36-FULLRUN-01', 'f00dcafe000000000000000000000000000001', now()),
  ('00000000-0000-0000-0000-000000000001', '53c93000-d878-4a65-9693-1135064f1285', 'customer', 'TESTER-S36-FULLRUN-02', 'f00dcafe000000000000000000000000000002', now()),
  ('00000000-0000-0000-0000-000000000001', '53c93000-d878-4a65-9693-1135064f1285', 'customer', 'TESTER-S36-FULLRUN-03', 'f00dcafe000000000000000000000000000003', now());
```

Clicked "Re-push all", let the countdown run its full course (no click). ~10s later the button's
countdown resolved and the toast appeared (this run's `useDeferredAction` poll on
`GET /api/v1/pending-actions/current` is what drove the lazy commit locally - **no Celery beat/
worker process was running in this lane** (`CELERY_TASK_ALWAYS_EAGER=true`, no `celery -A ... beat`
started), so the frontend's own poll is what triggered `PendingActionService.current()`'s
`_commit_if_due`, exactly as `app/deferred_actions/service.py`'s module docstring describes:
"either the beat sweep (`commit_due`) or the frontend's lazy `GET current` poll"). One more
inserted row (`TESTER-S36-TOAST-01`) was added for a second, cleaner capture of the toast
screenshot (the first capture's toast had already auto-dismissed by the time the screenshot
command ran; the second chained `wait --text ... && screenshot` caught it mid-display).

`03-toast-1280.png` - toast text (read from the DOM, and visible in the screenshot):
> "Change tracking cleared. The full re-push starts on the next scheduler tick."

Exactly the AC-07-23 active-task copy. `04-reloaded-badge-375.png` - the "Next reconcile" badge
at 375px after the reload (`10 Sept 2026, 17:12`, advanced from the pre-click `16:47`/earlier
values across the two full runs - the `reloadTask()` callback in `activate-tab.tsx` fired).

### DB proof (taken AFTER the window lapsed, for the run captured in `03-toast-1280.png`)

```
ac_row_hash count for (company=53c93000-..., customer): 0
ac_entity_config.next_reconcile_at = 2026-09-10 18:12:56.643676+09
now() at check time                = 2026-09-10 18:13:09.210730+09   -> next_reconcile_at <= now(): true
```

`integration_activity` row:
```
id: 7fb53ca8-64a2-487f-9dd2-56cff2107a2d
source: autocount, operation: "repush task", status: success
response_summary_json: {"clearedCount": 1, "entityType": "customer",
                         "actorUserId": "a533e094-cbba-4d07-ad35-a8bb4969223e"}
```
`a533e094-cbba-4d07-ad35-a8bb4969223e` = `users.id` for `demo@example.com` (verified by a
direct query) - the parking actor is recorded exactly as AC-07-20b/AC-07-18 require. (Two earlier
successful full-run commits during this same session, `clearedCount: 3` and `clearedCount: 0`,
also each wrote their own activity row with the same `actorUserId` - all three are visible in
`integration_activity`, newest three shown, ordered by `created_at desc`, in the raw psql output
kept below for completeness.)

### Runs tab / scheduler sweep

Per the amended AC-07-25's own fallback clause: **the sweep was not running in this lane** (no
`celery -A app.workflow_engine.worker worker` / `... beat` process was started for this run -
`ps aux | grep celery` was empty throughout). The Runs tab therefore still shows the OLD run
history (no new "reconcile" run appears) because nothing has claimed the armed
`next_reconcile_at`. The DB row above (`next_reconcile_at <= now()`, i.e. armed and claimable) is
the substitute proof the AC allows for this case.

### Direct-route check (AC-07-23's "the tab never calls the repush route directly")

`agent-browser network requests` across the entire session: **zero** requests to
`.../etl-task/repush`. Every mutation went through `POST /api/v1/pending-actions` (202) and the
poll `GET /api/v1/pending-actions/current` (200) - confirmed by grepping the full request log.

## 5. Draft task - action absent

Navigated to the same company's `Sales order` entity (config id
`48e2b593-879b-4616-b924-cd1cce6e7edb`, `etl_status='draft'`) via its own kebab menu ->
`Configure mapping` -> `Review & Activate`. The tab shows only `Run preview` and a disabled
`Activate` button - **no "Re-push all" button and no countdown anywhere in the DOM.**
`05-draft-no-action-1280.png` / `05-draft-no-action-375.png`.

## 6. AC-07-20b negative checks

- **Unauthenticated caller -> 401** (verified live): `curl -X POST http://localhost:8006/api/v1/
  pending-actions` with a valid JSON body and NO `Authorization` header -> `401`.
- **`sync.run`-only user -> 403**: **not exercised live** - no such limited-permission user is
  seeded in this lane's DB (`foundryx_service_s36`) and creating a throwaway one felt like more
  lane-state risk than value for a behaviour already pinned. Covered instead by the passing
  pytest `tests/test_autocount_deferred_repush.py::test_park_by_a_sync_run_only_user_is_403`
  (re-run this session, green - see the test report). Not filed as DEFERRED-to-backlog since the
  behaviour IS tested, just not re-proven live; noting it here as the coordinator asked.
- **Another tenant's config id -> 404**: not exercised live for the same reason (would need a
  second tenant/company provisioned in this shared lane DB); covered by the passing
  `test_park_on_another_tenants_config_id_is_404`.

## Cleanup

All `TESTER-S36-*` seeded rows were consumed by the repush commits during this run;
`ac_row_hash` for `(company=53c93000-..., customer)` = 0 rows at the end (verified). No manual
delete was needed this time (unlike the superseded 4c8dbb80 partial run, which did leave one row
that was cleaned up then).
