# Plan 33 - Alert when a scheduled integration run keeps failing

Lane: SS-INTEGRATION-ALERT (crew), branch `crew/ss-integration-alert`, size M.
Status: BUILD (card answered and mockup v1 approved by the owner, 22 Oct 15:15).

## Why

Owner, 22 Oct 2026 14:06 (prod, integration "Stock balance", AutoCount Open API -> Sorento, Active):
many Incremental runs in a row ended Failed with `AutoCount answered HTTP 502 on page N.` and
nobody noticed until he opened the screen. He wants a watcher that alerts: "cannot wait until the
user raise this".

## Step 0 - what "AutoCount answered HTTP 502" means

Posted as a `crew-note` on PR #128 (issuecomment-6333265145). Summary:

- The text is raised at `http_source/source.py:384-394`. One page `GET {baseUrl}{path}?page=N&pageSize=S`
  answered 5xx three times (backoff 1 s then 4 s, `TRANSPORT_RETRY_BACKOFFS_SECONDS`, `:84`), so the
  run failed. Stock balance walks `/itembatchbalqtybypage` plus lookups `/itembypage`,
  `/itemuombypage` (`presets.py:1548,1557,1600`). No auth header.
- Cloudflare / a reverse proxy fronts the AutoCount REST wrapper (`sprint-5/10-*.md:658,701`). A
  502 means the front door answered but the origin (wrapper / IIS / tunnel connector) did not.
- No whole-run retry; the next tick is the retry (5 min for a no-watermark task). `_fail` holds the
  watermark and bumps `consecutive_failures` (`sync.py:2596-2605`). Nobody is told.

## Facts the design rests on (surveyed 22 Oct)

- Scheduled runs: beat `autocount-etl-sweep` every 60 s (`app/workflow_engine/worker.py:124`) ->
  `sweep_etl_tasks` (`scheduler.py:116`) claims due tasks and enqueues the same `autocount_sync` job
  as "Run now" with mode `incremental`/`reconcile`. Interval lives in
  `AcEntityConfig.source_config.incrementalMinutes` (default 15, floor 5 for no-watermark tasks,
  `etl_service.py:194-204`).
- One integration = one `AcEntityConfig` row (`models.py:190-204`); runs = `AcSyncRun`
  (`models.py:494-554`, outcome SUCCESS/FAILED/ABORTED, mode manual/incremental/reconcile/skipped/
  snapshot).
- A run reaches its terminal state through ~20 exits (`_fail` x18, `_abort`, two success blocks,
  `bootstrap.on_job_orphaned` for crashes), so the watcher is a time-based evaluator over the run
  history, run from the existing 60 s sweep. It also catches "no run at all" (wedged worker).
- A Sorento push failure ends the run SUCCESS but sets `run.error` and `config.last_run_error`
  (`sync.py:1056,1083-1084,2216`); the screen then says "Last run failed"
  (`task-editor-view.tsx:716-725`). Outcome FAILED and the badge are not the same signal.
- No in-app notification store exists: IN_APP is modelled but inert
  (`app/services/notification_dispatch.py:126-133`), the header bell sheet is demo data
  (`service_frontend/app/components/partials/topbar/notifications-sheet.tsx:28-43`), backlog BL-058.
- Email = outbox: `email_service.enqueue_raw(...)` (`app/services/email_service.py:152-191`); tests
  disable the dispatcher and SMTP (`tests/conftest.py:62,74`).
- WhatsApp capability `messaging.send@1` is a stub that sends nothing
  (`modules/omnichannel/bootstrap.py:28-37`).
- Dev DB has NO failed scheduled run (all 8 FAILED runs are `manual`); tests seed their own.

## Step 1 - behaviour card (BEFORE code)

Filed as one `crew report --ask` on 22 Oct.

### Rules (crew defaults, recommended answers folded in)

1. An incident opens on an ACTIVE integration when 2 scheduled runs in a row failed, OR no clean run
   finished for 3x the incremental interval (floor 60 min).
2. One alert when it opens. While it stays open, one reminder at most every 4 h. When a run ends
   clean, one "recovered" notice and the incident closes.
3. Pausing or deactivating the integration closes an open incident silently.
4. Channels: email to integration admins + an incident banner on the integration page and a marker
   on its row in the company's integration list. WhatsApp off (the capability is a stub today).
5. Times in the email use each recipient's own timezone (`users.timezone`, `app/models/user.py:47`),
   else UTC, labelled.

### Wording (draft)

- Subject: `Customer (V Soft Trading) has failed 2 runs in a row`
- Body: Integration: Customer. Company: V Soft Trading (AED_VSOFT). Failing since: 22 Oct 2026, 09:15
  (MYT). Failed runs: 2. Last error: AutoCount answered HTTP 502 on page 3. Button: Open runs ->
  `/autocount/companies/<id>/entities/customer?tab=runs`.
- Reminder subject: `Still failing: Customer (V Soft Trading), 14 failed runs since 09:15`
- Recovered subject: `Customer (V Soft Trading) is running again` - body: recovered at,
  failed runs during the incident, how long it lasted, link.
- Banner (integration page): `Failing since 22 Oct, 09:15 - 14 failed runs. Last error: AutoCount
  answered HTTP 502 on page 3.` + "View runs". Row marker: `Failing` status badge.

### Questions (see the --ask)

Q1 in-app channel, Q2 recipients, Q3 what counts as failed, Q4 thresholds, Q5 scope (doc feeds).

Owner answers (22 Oct 15:15, via crew): all as recommended.
Q1 (a) banner + list badge + email, no bell inbox. Q2 (b) holders of `autocount.companies.manage` +
optional per-integration "also email" list. Q3 (a) scheduled runs that ended FAILED or with a Sorento
push error; manual runs never open, a clean manual run closes. Q4 (a) 2-in-a-row / 3x interval, 60 min
floor, editable per integration on the Schedule tab. Q5 (a) entity integrations now; DO/GRN doc feeds
= BL-SS-308. Mockup v1 (`documentation/mockups/SS-INTEGRATION-ALERT/index.html`) approved "Ok".

## Step 2 - build

UAC: `33-integration-run-failure-alert-acceptance-criteria.md` (AC-33-01..17).

### Phase 1 contract block (tester writes against this; coder implements it)

Backend (module `service_backend/modules/autocount/`):
- Model `AcTaskIncident`, table `app_autocount.ac_task_incident`: `id` (UUID string PK), `tenant_id`,
  `company_id`, `entity_config_id`, `entity_type`, `reason` (`consecutive` | `stale`), `opened_at`,
  `first_failure_at` (nullable for a stale incident with no failed run), `failed_runs` (int),
  `last_error` (Text), `last_notified_at`, `notices_sent` (int), `closed_at` (nullable),
  `close_reason` (`recovered` | `paused` | `disabled`, nullable). At most one row with
  `closed_at IS NULL` per `entity_config_id`. All datetimes `UTCDateTime`.
- Evaluator `modules/autocount/alerts.py`: `evaluate_integration_alerts(db, *, now=None) -> dict`
  returning counts `{"opened", "reminded", "recovered", "closed", "failed"}`. Called once at the end of
  `scheduler.sweep_etl_tasks` inside its own try/except (a crash there never changes the sweep's own
  return value). Same tenant/module-active filter as the sweep.
- Constants in `alerts.py`: `DEFAULT_ALERT_AFTER_FAILED_RUNS = 2`, `DEFAULT_ALERT_STALE_MULTIPLE = 3`,
  `STALE_FLOOR_MINUTES = 60`, `REMINDER_INTERVAL = timedelta(hours=4)`, `MAX_ALERT_EMAILS = 10`.
- Settings in `AcEntityConfig.source_config`: `alertsEnabled` (bool, default true),
  `alertAfterFailedRuns` (int 1..20, default 2), `alertStaleMultiple` (int 2..48, default 3),
  `alertEmails` (list of up to 10 emails, default []). Absent key = default.
- Wire: `EtlTaskUpdate` gains the same four optional fields (None = keep the stored value);
  `PUT .../etl-task` validates with the house per-field 422 (`{"field": ..., "message": ...}` shape the
  schedule fields already use). `EtlTaskResponse` returns the four resolved values plus
  `openIncident: {openedAt, firstFailureAt, failedRuns, lastError, reason} | null`. The company
  detail's integration rows (`EntityConfigItem`, `GET /autocount/companies/{id}`) gain the same
  `openIncident`.
- Email: `app.services.email_service.email_service.enqueue_raw(db, tenant_id, to_email, subject,
  html_body, text_body, template_key=..., commit=False)` per recipient. Subjects exactly as AC-33-09.
  The Runs link uses the tenant's own frontend host (the helper the auth emails already use).

Frontend (`service_frontend/app/(protected)/autocount/...`):
- Types/service: `openIncident` on the etl-task and entity-row types; the four alert fields on the
  etl-task type and its update payload (existing `services/` layer, no fetch in components).
- `task-editor-view.tsx`: incident banner under the header (`components/ui/alert.tsx`, destructive /
  light), text `Failing since <time> - <n> failed runs. Last error: <line>`, "View runs" switches to
  the Runs tab. Times via `useDatetime()`.
- `use-entities-list-config.tsx` Health column: `Failing` `StatusBadge` when `openIncident` is set.
- `schedule-tab.tsx`: "Failure alerts" card: Switch, two number inputs, "Also email" list; saved with
  the schedule; dirty-guarded.

### Slices

- S1 BE: model + module Alembic + crew SQL, settings validation, evaluator + email, sweep hook, API.
- S2 FE: types/service, banner, list badge, Schedule card.
- Tester writes S1 + S2 red tests first (`test(red):` commit), coder makes them green, kill test,
  reviewer + security-reviewer (recipient resolution is tenant + permission scoped) in parallel,
  agent-browser 1280 + 375, laneboard script, `crew report --handtest`.
