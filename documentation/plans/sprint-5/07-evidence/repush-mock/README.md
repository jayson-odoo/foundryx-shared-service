# S2a "Re-push all" - Phase 1 FE evidence

Lane stack: backend `:8006` (`.venv/bin/uvicorn app.main:app --port 8006`, DB
`foundryx_service_s36`), frontend `:3006` (fresh `rm -rf .next && npm run build`
then `npx next start -p 3006`). `agent-browser --session s36`, real clicks,
logged in as `demo@example.com` / `demo1234`.

## Note on "mock" vs "real" for this run

`services/autocount-service.ts` binds the BARE `.real` service for the whole
AutoCount surface (it has been fully backend-backed since plan 22/sprint-5/02
and carries no runtime mock switch - see its own docstring). There is no env
flag to force `mockAutocountService` at runtime, so this run exercises the
real trio end to end against the real backend on :8006, which does NOT yet
have the `.../etl-task/repush` route (that lands in S2b). Per the brief's
fallback instruction, this run therefore proves: the action renders/hides
correctly, the typed-confirm dialog gates correctly, and the click reaches
the real backend with the right ids - the backend responds 404 (route not
found) and the tab's existing `lifecycle.error` Alert renders it, exactly
the "other errors: existing lifecycle.error surface" path from AC-07-23.
The 200/409-in-flight paths are covered by the Vitest suite
(`activate-tab.test.tsx`, `hooks/use-autocount-etl-lifecycle.test.ts`,
`services/autocount-service.mock.test.ts`) against `mockAutocountService`,
which resolves/throws exactly the AC-07-20 contract.

## Steps clicked

1. Sidebar -> AutoCount -> Companies.
2. Row click -> "ETL Demo Co" (a `sql_database`-sourced company, real seed
   data in the lane DB).
3. Entities tab -> row "..." menu (had to scroll the table's own
   `overflow-x-auto` container right to reach the Actions column at 1280px -
   the Actions column is the last one and is genuinely off-screen at this
   width until scrolled) -> "Configure database query" for `Sales order`
   (draft) and, separately, for `Customer` (active).
4. `Sales order` -> Review & Activate tab: task is `draft` - "Re-push all"
   correctly ABSENT (screenshots 01/02). This is the "second run against a
   draft task proves the action is absent" case from AC-07-25.
5. `Customer` -> Review & Activate tab: task is `active`, source `sql_db` -
   "Re-push all" renders (screenshots 03/04), destructive-styled, beside
   Re-run preview / Pause / Run now.
6. Click "Re-push all" -> the shell `AlertDialog` typed-confirm opens,
   Confirm disabled (screenshot 05).
7. Type "Customer" (the entity label, `entityLabel('customer')`) -> Confirm
   enables (screenshots 06/07).
8. Click Confirm -> dialog closes; the real `POST
   /autocount/companies/{id}/entities/customer/etl-task/repush` fires
   (confirmed in the backend log below) -> 404 (route not built yet, S2b) ->
   the tab's existing `lifecycle-error` Alert renders "Not Found" (screenshots
   08/09).

Backend log line (`/tmp/s36-backend.log`), confirming the exact ids on the
wire:

```
INFO: 127.0.0.1:51188 - "OPTIONS /autocount/companies/53c93000-d878-4a65-9693-1135064f1285/entities/customer/etl-task/repush HTTP/1.1" 200 OK
INFO: 127.0.0.1:51188 - "POST /autocount/companies/53c93000-d878-4a65-9693-1135064f1285/entities/customer/etl-task/repush HTTP/1.1" 404 Not Found
```

## Screenshots

| File | What it shows |
|---|---|
| `01-draft-task-1280.png` / `02-draft-task-375.png` | `sales_order` (draft, database task) - "Re-push all" absent, only Run preview / Activate |
| `03-active-task-repush-visible-1280.png` / `04-active-task-repush-visible-375.png` | `customer` (active, database task) - "Re-push all" renders (destructive) beside Pause / Run now |
| `05-dialog-open-disabled-1280.png` | Typed-confirm dialog just opened, Confirm disabled |
| `06-dialog-open-enabled-1280.png` / `07-dialog-open-enabled-375.png` | Typed "Customer" matches the entity label - Confirm enabled |
| `08-after-confirm-1280.png` / `09-after-confirm-404-375.png` | After Confirm: dialog closed, real 404 from the not-yet-built backend route rendered on the existing `lifecycle-error` Alert |

## What remains for S2b (mock -> real swap point)

There is no swap needed on the frontend - `autocountService.repushEtlTask`
already calls through `.real.ts` (`POST
/autocount/companies/{companyId}/entities/{entityType}/etl-task/repush`,
`service_frontend/services/autocount-service.real.ts`, the `repushEtlTask`
method added this slice). S2b's job is entirely backend: add the route
(`modules/autocount/routers/companies.py`), `EtlService.repush_task`, and
`EtlRepushResponse` per plan section 2.3 / AC-07-13..19, at which point this
exact frontend code starts working with no FE change at all.
