# AC-07-25 - "Re-push all" live evidence (S2b)

Lane stack: backend `:8006` (`.venv/bin/uvicorn app.main:app --port 8006`, DB
`foundryx_service_s36`), frontend `:3006` (fresh `rm -rf .next && npm run build`
then `npx next start -p 3006`). `agent-browser --session s36`, real clicks,
logged in as `demo@example.com` / `demo1234`. This run is against the REAL
backend route built in S2b (`.real.ts` was already wired from S2a; no frontend
change this slice).

**Task used**: company `ETL Demo Co` (id `53c93000-d878-4a65-9693-1135064f1285`),
entity `Customer` - an `active`, `sql_db`-sourced task with 9 real
`ac_row_hash` rows going in. (The tester's independent re-run may land on a
different active database task in this same lane DB - anything satisfying
`status in (active, paused)` and `sourceImpl = sql_db` reproduces the same
result shape; the exact `clearedCount` will differ with whatever row-hash
population that task holds at the time.)

## Steps clicked

1. Sidebar -> AutoCount -> Companies -> row "ETL Demo Co".
2. Entities tab -> scrolled the table's own horizontal `overflow-x-auto`
   container right to reach the Actions column -> "..." on the `Customer`
   row -> "Configure database query".
3. Review & Activate tab: "Re-push all" renders (destructive-styled, beside
   Re-run preview / Pause / Run now) - screenshots 01/02.
4. Click "Re-push all" -> typed-confirm dialog opens, Confirm disabled -
   screenshot 03.
5. Type "Customer" (`entityLabel('customer')`) -> Confirm enables -
   screenshots 04/05.
6. Click Confirm -> dialog closes -> success toast: **"Change tracking
   cleared for 9 documents. The full re-push starts on the next scheduler
   tick."** - screenshots 06/07.
7. Second run, same company's `sales_order` entity (still `draft`, never
   activated) -> Review & Activate tab shows ONLY "Run preview"/"Activate" -
   "Re-push all" is absent, proving the action never appears for a task that
   cannot use it - screenshots 08/09.

## SQL proof (`foundryx_service_s36`, before -> after the click)

Before (captured immediately prior to step 6):

```
select count(*) from app_autocount.ac_row_hash
where company_id='53c93000-d878-4a65-9693-1135064f1285' and entity_type='customer';
 row_hash_count
----------------
              9
```

After:

```
select count(*) from app_autocount.ac_row_hash
where company_id='53c93000-d878-4a65-9693-1135064f1285' and entity_type='customer';
 row_hash_count
----------------
              0

select next_reconcile_at, next_reconcile_at <= now() as is_due, now() as db_now
from app_autocount.ac_entity_config
where company_id='53c93000-d878-4a65-9693-1135064f1285' and entity_type='customer';
       next_reconcile_at       | is_due |            db_now
-------------------------------+--------+-------------------------------
 2026-09-10 16:18:03.215432+09 | t      | 2026-09-10 16:18:43.063818+09
```

Activity row (AC-07-18):

```
select operation, status, response_summary_json, created_at from integration_activity
where source='autocount' and operation ilike '%repush%' order by created_at desc limit 3;
  operation  | status  |             response_summary_json             |          created_at
-------------+---------+-------------------------------------------------+-------------------------------
 repush task | success | {"clearedCount": 9, "entityType": "customer"}  | 2026-09-10 16:18:03.201032+09
```

`clearedCount: 9` matches the toast, the before-count, and the DB row's own
`response_summary_json`. `ac_doc_fingerprint`/`ac_watermark` were not queried
here (already pinned by the pytest suite, `test_repush_happy_path_clears_
only_this_companys_entity_hashes`) - not re-verified live in this pass.

## Note on the tab's own badges (not a defect, documented in S2a)

The "Next reconcile" badge on the Review & Activate tab still read the OLD
value in the post-click screenshot (06) - `repushEtlTask`'s wire response is
narrow (`clearedCount`/`nextReconcileAt`/`status` only, no full task), so the
hook does not feed it back into the page's own `task` object (S2a's own
design, see `hooks/use-autocount-etl.ts`'s `repush()`). The toast and the DB
are the source of truth for this action; a manual reload (or the Runs tab,
which DOES refetch via `onRan()`) shows the current state. Not part of any
AC-07-2x wording, not changed this slice.

## Screenshots

| File | What it shows |
|---|---|
| `01-review-activate-tab-1280.png` / `02-review-activate-tab-375.png` | Active `customer` task - "Re-push all" renders |
| `03-dialog-open-1280.png` | Typed-confirm dialog just opened, Confirm disabled |
| `04-dialog-confirm-enabled-1280.png` / `05-dialog-confirm-enabled-375.png` | Typed "Customer" - Confirm enabled |
| `06-success-toast-1280.png` | Real success toast: "Change tracking cleared for 9 documents..." |
| `07-success-toast-375.png` | Post-click tab state at 375px (toast already auto-dismissed by capture time, 4s duration) |
| `08-draft-task-no-repush-1280.png` / `09-draft-task-no-repush-375.png` | Draft `sales_order` task on the SAME company - "Re-push all" absent |

Servers started for this run (uvicorn pid 45475, next start pid 46198) were
killed by pid after the run; ports 3006/8006 confirmed free.
