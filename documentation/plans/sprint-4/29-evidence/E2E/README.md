# Plan 29 (Omnichannel Broadcasts v1) - formal E2E evidence run

Tester run for **AC-BRD-53 / 54 / 55**. Recorded with `agent-browser --session s29t`
(the ONLY browser tool; no Playwright), real clicks from `/`, foreground.

- **Commit under test:** `ae59090` (branch `sprint-4/29-broadcasts`, worktree `.claude/worktrees/s29`).
- **Lane:** frontend `http://localhost:3007` (prod build, pid 50418, cwd = this worktree's
  `service_frontend`), backend `http://localhost:8008` on Postgres `foundryx_service_s29`,
  `CELERY_TASK_ALWAYS_EAGER=true` (so a send completes inline; there is no beat process).
- **Logins:** `demo@example.com` / `demo1234` (default tenant Admin),
  `platform@example.com` / `platform1234` (`platform.localhost:3007`),
  plus two probe identities created during the run (below).
- **Timestamp used for every created name:** `20260906T085024Z`.
- **Viewports:** 1280x900 and 375x812.

## Lane change made during the run (recorded, not a product change)

The lane backend (pid 4971) had been started **without** `CORS_ORIGIN_REGEX`, so every
subdomain host (`platform.localhost:3007`, `<tenant>.localhost:3007`) failed CORS preflight
with `400` and the operator console could not POST `/platform/tenants`. Restarted the same
worktree's backend with the documented lane env:

```
DATABASE_URL=postgresql://foundryx:foundryx@localhost:5432/foundryx_service_s29 \
ENVIRONMENT=development CORS_ORIGINS=http://localhost:3007 \
CORS_ORIGIN_REGEX='^http://[a-z0-9-]+\.localhost:3007$' CELERY_TASK_ALWAYS_EAGER=true \
<venv>/bin/python -m uvicorn app.main:app --port 8008
```

No code or migration was touched.

## Setup calls used (all disclosed; the flow under test stayed real clicks)

1. **Push a scheduled instant into the past** so the beat-tick body has something due:
   ```sql
   UPDATE app_omnichannel.broadcasts
      SET scheduled_at = now() - interval '5 minutes'
    WHERE id = '1ef907af-76f0-4368-bcf5-f60b7c0a7672';
   ```
2. **Run the `omnichannel.broadcasts_due` tick inline** (no beat process in this lane). The
   module boot hook must be called first or the job type is unregistered in a bare process:
   ```bash
   cd <worktree>/service_backend
   DATABASE_URL=postgresql://foundryx:foundryx@localhost:5432/foundryx_service_s29 \
   ENVIRONMENT=development CELERY_TASK_ALWAYS_EAGER=true \
   <venv>/bin/python -c "
   from app.database import SessionLocal
   from modules.omnichannel.bootstrap import register_engine_entities
   from modules.omnichannel.services.broadcast_send_service import run_due_broadcasts
   register_engine_entities()
   db = SessionLocal()
   try: print(run_due_broadcasts(db))
   finally: db.close()"
   # -> {'started': 1, 'reconciled': 0, 'finalized': 0}
   ```
3. **Delivery receipts** - Meta-shaped status webhooks POSTed to the channel webhook (the
   dev adapter accepts unsigned bodies when `META_APP_SECRET` is unset):
   ```bash
   curl -s -X POST http://localhost:8008/omnichannel/webhooks/chn-demo \
     -H 'Content-Type: application/json' \
     -d '{"object":"whatsapp_business_account","entry":[{"id":"waba-demo","changes":[{"field":"messages",
          "value":{"messaging_product":"whatsapp","metadata":{"phone_number_id":"pn-demo"},
          "statuses":[{"id":"wamid.dev-ef7b629bfed5","status":"delivered","timestamp":"1789000000",
          "recipient_id":"60123456789"}]}}]}]}'
   # then the same with "status":"read", then a late "status":"sent" (forward-only probe)
   ```
4. **RBAC probe identity** - role `E2E No-Send Agent 20260906T085024Z` created over the API with
   `broadcasts.read/manage` + `contacts.read` + `workspaces.read` + `channels.read` +
   `wa_templates.read` (deliberately **no** `broadcasts.send`); user
   `e2e-nosend-20260906t0850@example.com` created over the API, then activated with a direct
   `UPDATE users SET password=<bcrypt>, status='ACTIVE'` (the API create lands `INVITED` and the
   invite mail path is out of scope here).
5. **No-omnichannel tenant** - `p29-noomni-20260906t0850` provisioned with the operator API
   (`POST /platform/tenants`); nothing was installed on it.


## IMPORTANT - the worktree changed under this run

`git status` was **clean at `ae59090`** when this run started (09:48 local / 08:48 UTC). By the
time it finished, 20 tracked files were modified and 5 were added, with mtimes spread from
16:58 to 17:30 local - a concurrent agent was landing a review-fix round in the same worktree
while the tests ran. Consequences, stated exactly:

- **Backend suite** was collected within the first minute, so `3144 passed, 1 skipped` maps to
  `ae59090`.
- **Frontend suite** (`vitest run`, 2171 passed) finished before any FE file was touched, so it
  also maps to `ae59090`.
- **The served frontend build** (`:3007`, pid 50418, started 16:48 local) predates every FE edit -
  every UI observation in this run is `ae59090` behaviour.
- **The backend was restarted at 17:12:29 local** to add `CORS_ORIGIN_REGEX`. That process
  imported `ae59090` **plus** the then-uncommitted `models.py`, `0011_omni_broadcasts.py`,
  `message_service.py`, `deferred_actions.py` and `broadcast_bindings.py`. Everything before
  that (the whole send journey, test send, schedule, due tick, cancel, receipts) ran on the
  original `ae59090` backend process. The API probes after the restart (isolation, permission
  gates, 409 gates, workflow metadata, jobs, filter-audience) carry that caveat.
- Some of the in-flight work visibly closes gaps this report records (e.g. a gateway no-diff
  guard test now exists in the working tree but **not** at `ae59090`). This report is keyed to
  `ae59090` as briefed; re-run it once the round lands.

## Journey (1280px unless noted)

| # | Screenshot | What it shows |
|---|---|---|
| 1 | `01-segment-created-1280.png` | Sidebar Omnichannel > Contacts > Filters > `Name contains "r"` > Apply (list narrows to `1 - 3 of 3`: Sarah Chen, Marcus Wong, Priya Raj) > **Save as segment** > `E2E Segment R 20260906T085024Z`. Toast "Segment saved." |
| 2 | `02-broadcasts-list-1280.png` | Sidebar Omnichannel > **Broadcasts** (entry sits after Contacts). Resource-shell list with every AC-BRD-02 column: Name, Labels, Channel, Audience, Recipients, Status, Scheduled / Sent at, Sent / Delivered / Read / Failed, Created by, Created. |
| 3 | `03-status-segments-1280.png` | The status views render as a `SearchSelect`: All, Draft, Scheduled, Sending, Sent, Cancelled, Failed (AC-BRD-03). |
| 4 | `04-audience-segment-count3-1280.png` | **New broadcast** > name `E2E broadcast 20260906T085024Z` > Audience source `Segment` > the segment just created > live count **"3 recipient(s) resolved"** (a real `POST .../audience-preview` 200). |
| 5 | `05-template-picker-approved-only-1280.png` | Channel `Demo WhatsApp (sandbox)` chosen; the Template picker offers only `booking_update (en)` and `payment_reminder (en)` - the seeded `promo_blast` is `PENDING` and is **not** offered (AC-BRD-06). |
| 6 | `06-bindings-preview-1280.png` | The variables editor renders exactly the template's two body slots. Slot 1 = Contact field / First name, fallback `there`; slot 2 = Static text `6 Sept 3pm`. The reused `WaBubblePreview` renders "Hi Alex, there is an update on your booking: 6 Sept 3pm..." live (AC-BRD-07). |
| 7 | `07-review-section-1280.png` | Review = read-only summary (Audience 3 recipient(s) / Channel / Template / Schedule Send now) + Test send + primary Send now (AC-BRD-09). |
| 8 | `08-test-send-1280.png`, `09-after-test-send-1280.png` | **Send test message** > contact picker > Sarah Chen > Send test. Real `POST .../{id}/test-send` **200**. DB check: exactly one new `conversation_messages` row for `cnt-001`, **zero** `broadcast_recipients` rows, broadcast still `DRAFT` with all counts `0` (AC-BRD-41). |
| 9 | `10-status-sent-counts-1280.png` | **Send now** > auto-saved the draft, called `send()`, navigated to the status page. Eager Celery finished the send inline: Status **Sent**, Total 3 / Sent 3 / rest 0, Started + Finished stamped. |
| 10 | `11-recipients-sent-1280.png` | Recipients tab (embedded Resource list; Contact, Phone, State, Error, Attempted at): all 3 segment members `Sent`. DB: each row carries a real `message_id`. |
| 11 | `12-inbox-thread-template-1280.png` | Sidebar > Inbox > Sarah Chen thread shows the delivered template body. |
| 12 | `13-list-no-row-actions-column-1280.png` | **Defect evidence (D-1).** The broadcasts list has NO actions column - headers are `<select>, Name, Labels, Channel, Audience, Recipients, Status, Scheduled / Sent at, Sent / Delivered / Read / Failed, Created by, Created`. Selecting a row shows only "1 selected" + Clear (no bulk action menu for that row's status). |
| 13 | `14-form-actions-duplicate-1280.png` | The FORM surface's Actions menu works: Duplicate on a Sent broadcast. Result: new `DRAFT` "... (copy)", counts 0, no schedule, **0 recipients copied** (AC-BRD-22). |
| 14 | `15-schedule-set-1280.png`, `16-scheduled-detail-1280.png`, `17-list-scheduled-row-1280.png` | Schedule the duplicate: `Schedule for` + `06 Sept 2026, 17:03` in the user's zone (the field's own caption reads `Timezone: Asia/Kuala_Lumpur`). **Schedule broadcast** > status `SCHEDULED`, stored as `2026-09-06 09:03 UTC` (correct tz conversion, AC-BRD-08/26). List row reads `Scheduled  06 Sept 2026, 17:03`. |
| 15 | `18-list-after-due-tick-1280.png` | Setup step 1 + 2 (push `scheduled_at` into the past, run the tick inline) -> tick returned `started: 1`; after a reload the row is **Sent** with `3 / 0 / 0 / 0` (AC-BRD-42). |
| 16 | `19-sent-no-cancel-action-1280.png` | Third broadcast `E2E cancel probe 20260906T085024Z`, audience = **Selected contacts > Select all** (5 demo contacts, "5 recipient(s) resolved") > Send now. Eager mode completed it inline, so the status is already `Sent` and the Actions menu correctly offers **only Duplicate** (no Cancel). A live `POST .../cancel` on it returns `409 {"reason":"broadcast_not_cancellable"}`. |
| 17 | `20-scheduled-actions-cancel-1280.png`, `21-cancelled-zero-sends-1280.png` | So Cancel was exercised on a SCHEDULED one: duplicate the third broadcast, schedule it for 18:30 local, reload, Actions > **Cancel** (no confirm dialog - the documented S0 decision). Status `Cancelled`, `finished_at` stamped, `total/sent = 0`, **0 recipient rows** (AC-BRD-40). |
| 18 | `22-receipt-delivered-1280.png`, `23-receipt-read-1280.png`, `24-overview-counts-after-receipts-1280.png` | With the Recipients tab open, setup step 3 posted `delivered` then `read` for `wamid.dev-ef7b629bfed5` (Sarah Chen's broadcast message). The row flipped **Sent -> Delivered -> Read live, with no reload** (the `broadcast.updated` realtime publish). Overview then reads Total 3 / Sent 2 / Delivered 0 / Read 1. A late `sent` posted afterwards left the row at `read` - receipts move forward only (AC-BRD-37). |
| 19 | `39-jobs-drawer-broadcast-send-1280.png` | Sidebar > Jobs: every send appears as `Omnichannel.broadcast Send`, status Done, progress `3/3` and `5/5`. `GET /jobs/{id}` returns `progressTotal: 3`, `progressDone: 3`, `result {total,sent,failed,skipped,cancelled}` (AC-BRD-50). |

### 375px pass

`25-status-page-375.png` (status card + counts grid reflows to 3 columns),
`26-recipients-375.png`, `27-list-375.png`, `28-builder-375.png`.
`document.documentElement.scrollWidth === window.innerWidth === 375` on every one - no
horizontal page scroll, nothing clipped, every control reachable.

### Isolation + RBAC (AC-BRD-54)

| # | Screenshot | What it shows |
|---|---|---|
| 20 | `29-isolation-tenant-created-1280.png` | Operator at `platform.localhost:3007` > Tenant Management > Tenants > **Add tenant** > `P29 Isolation 20260906T085024Z` / slug `p29-20260906t0850` / admin `p29admin@example.com`. Created. |
| 21 | `30-isolation-omnichannel-installed-1280.png` | The tenant's **Modules** (Services) tab > Omnichannel card > Actions > **Install** > ACTIVE `0.5.0`. DB check: `install_tenant` seeded the `BROADCAST` status scope with 6 keys and the tenant's Admin role received all three `broadcasts.*` keys (AC-BRD-16/47). |
| 22 | `31-isolation-empty-list-1280.png` | Logged in as that tenant's admin at `p29-20260906t0850.localhost:3007`: **Broadcasts** appears in the sidebar after Contacts, and the list is empty - tenant A's 7 broadcasts are invisible. |
| 23 | `32-isolation-no-channel-options-1280.png`, `33-isolation-no-template-options-1280.png` | New broadcast on the fresh tenant: the Channel and Template `SearchSelect`s offer **zero** options (foolproof - nothing to pick, no error). |
| 24 | `34-nosend-list-1280.png`, `35-nosend-actions-no-send-cancel-1280.png`, `36/37-nosend-*-1280.png` | Logged in as `e2e-nosend-...` (no `broadcasts.send`): the list and detail render, the detail Actions menu offers **only Duplicate** (no Send now, no Cancel), and the builder's Review section renders **no** "Send test message" and **no** primary Send/Schedule button (AC-BRD-12). |
| 25 | `38-noomni-no-broadcasts-menu-1280.png` | Tenant `p29-noomni-20260906t0850` (omnichannel never installed): no Omnichannel section and no Broadcasts entry in the sidebar **or** the Apps mega menu (AC-BRD-01). |

### API isolation probes (curl, both directions)

Tenant A = `default` (ws `d4843946-...`), tenant B = `p29-20260906t0850` (ws `88e26189-...`).

```
A token -> B ws  GET  /omnichannel/workspaces/{B}/broadcasts                    404 Workspace not found.
A token -> B ws  POST /omnichannel/workspaces/{B}/broadcasts/audience-preview   404 Workspace not found.
B token -> A ws  GET  /omnichannel/workspaces/{A}/broadcasts                    404
B token -> A ws  POST .../audience-preview                                      404
B token -> A broadcast id, via A's ws path:
  GET /{id}  404 | GET /{id}/recipients  404 | PATCH /{id}  404 | DELETE /{id}  404
  POST /{id}/send  404 | /cancel  404 | /test-send  404 | /duplicate  404
B token -> B(own) ws, A's segment id      404 Segment not found.
B token -> B(own) ws, A's contact ids     200 {"count": 0}   (no leak; see report remark)
```

Status-gate + validation probes on tenant A:

```
POST .../{sent-id}/cancel      409 {"reason":"broadcast_not_cancellable"}
PATCH .../{sent-id}            409 {"reason":"broadcast_not_editable"}
DELETE .../{sent-id}           409 {"reason":"broadcast_not_editable"}
POST .../audience-preview  {segmentId: unknown}   404 Segment not found.
```

Permission gate for the no-send user (`broadcasts.read` + `manage` only):

```
GET  .../broadcasts            200
POST .../{id}/send             403 Missing permission: broadcasts.send
POST .../{id}/test-send        403 Missing permission: broadcasts.send
POST .../{id}/cancel           403 Missing permission: broadcasts.send
```


### Audience "Filter" source (added after the main journey)

`40-audience-filter-branch-1280.png` - New broadcast > Audience source **Filter** > Build filter >
`Status is any of Open` > Apply. The chip reads "1 condition(s)" but the count stays
`-  recipient(s) resolved`; the HAR shows the preview call returning **422**:

```
POST .../broadcasts/audience-preview
{"audience":{"kind":"filter","filter":{"kind":"group","combinator":"and",
 "rules":[{"kind":"condition","field":"status","operator":"in","value":""}]}}}
-> 422 {"detail":"field not filterable: status"}
```

`status` and the enum-shaped `assignee` are not columns in the backend's
`CONTACT_FILTER_COLUMNS`; the builder's `AUDIENCE_FILTER_FIELDS` in `audience-section.tsx` is a
hardcoded four-entry stub, not the contact filter map (defect D-3).

While isolating that, a second, more serious one surfaced (defect D-4): with `rules` spelled
correctly the filter works (`firstName contains zzz` -> 0, `contains Sarah` -> 1), but an
**empty or unrecognised rule set silently resolves to the whole workspace**:

```
{"filter":{"kind":"group","combinator":"and","rules":[]}}          -> 200 {"count": 5}
{"filter":{"kind":"group","combinator":"and","conditions":[...]}}  -> 200 {"count": 5}
{"filter":{"kind":"group","combinator":"and","zzz":[...]}}         -> 200 {"count": 5}
```

and the same body is accepted at **create** - `E2E malformed-filter probe 20260906T085024Z`
(`4f71f799-c59a-4f58-bb22-bdb575f76ca4`) was created 201 with a stored audience of
`{"kind":"filter","filter":{"kind":"group","combinator":"and","rules":[]}}`, i.e. every contact
in the workspace. It was left as a DRAFT and deliberately **not** sent.

## Console / errors

`agent-browser --session s29t errors` reported nothing across the whole run.
`console` carried one pre-existing Radix a11y warning
(`Missing 'Description' or 'aria-describedby' for {DialogContent}`) raised by the test-send
dialog - not a plan-29 regression pattern, logged in the report as an observation.

## Findings recorded during this run

1. **D-1 (FAIL, AC-BRD-11 / AC-BRD-54)** - the broadcasts list has **no row-actions column**.
   `useBroadcastActions` declares `surfaces: {row: true}` on all five actions, but
   `use-broadcasts-list-config.tsx` never adds the `id: 'actions'` column that the Users
   reference list uses to render `<ActionMenu surface="row">`. Consequence: Cancel /
   Duplicate / Send / Edit / Delete are unreachable from a list row, and AC-BRD-54's
   "cancelled from the list row action" cannot be performed. Evidence
   `13-list-no-row-actions-column-1280.png`. Cancel was verified from the FORM surface instead.
2. **Observation** - a broadcast is not sendable/viewable by a role holding only
   `broadcasts.read`: the list resolves its workspace through `GET /omnichannel/workspaces`,
   which is gated `workspaces.read`, so a broadcasts-only role sees an empty list
   (`403` on the workspaces call). The probe role needed `workspaces.read` added.
3. **D-3 (FAIL, AC-BRD-05)** - the Audience "Filter" source is non-functional: the builder
   offers `Status` / `Priority` / `Assignee` / `Last message`, but `status` and the enum
   `assignee` are not in `CONTACT_FILTER_COLUMNS`, so Apply returns
   `422 field not filterable: status` and the count never resolves.
4. **D-4 (FAIL, AC-BRD-18 / AC-BRD-23)** - an empty or unrecognised inline filter rule set is
   accepted (200 / 201) and resolves to **every contact in the workspace**, not a 422 and not 0.
   Server-side there is no mirror of the client zod rule "rejects a filter audience with zero
   conditions".
5. **Observation** - the first (failed) tick invocation ran in a process that had not called
   the module boot hook, so `JobService.create` raised `UnknownJobType` **after**
   `start_scheduled_broadcast` had already committed the `SCHEDULED -> SENDING` claim. The
   pre-existing residue broadcast `Live Probe Broadcast Renamed` is consequently parked in
   `SENDING` with `job_id NULL` and 0 recipients; the 15-minute stuck-SENDING reconciler in
   `run_due_broadcasts` is the designed repair for exactly this. Caused by the tester's setup,
   not by product code, but it shows the claim and the job creation are not atomic.

## Residue left on `foundryx_service_s29`

Tenants `p29-20260906t0850` and `p29-noomni-20260906t0850`; role
`E2E No-Send Agent 20260906T085024Z`; user `e2e-nosend-20260906t0850@example.com`;
segment `E2E Segment R 20260906T085024Z`; broadcasts named `E2E broadcast 20260906T085024Z*`,
`E2E cancel probe 20260906T085024Z*`, `E2E rbac scheduled 20260906T085024Z`,
`E2E malformed-filter probe 20260906T085024Z` (D-4 repro, left DRAFT, never sent). All names are
timestamped, so a re-run does not collide. Local DB only - no code, migration or seed changed.
