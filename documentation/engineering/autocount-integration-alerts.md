# AutoCount integration failure alerts (plan 33)

Spec: `documentation/plans/sprint-5/33-integration-run-failure-alert-acceptance-criteria.md`. Code:
`service_backend/modules/autocount/alerts.py`, table `app_autocount.ac_task_incident` (migration 0031).

## Contract

- **Where it runs.** `evaluate_integration_alerts(db, now=...)` runs once at the end of the 60 s ETL
  sweep (`scheduler.sweep_etl_tasks`), in its own try/except. A crash in it never changes the sweep's
  return value or its enqueueing. It checks every ACTIVE integration (`AcEntityConfig`) of every
  tenant that passes the sweep's own lifecycle predicate (`active_tenant_service_join`). One
  integration's error is logged and isolated.
- **Time-based, not a run-exit hook.** A run ends through about 20 exits (`_fail`, `_abort`, two
  success blocks, `bootstrap.on_job_orphaned`). Reading the run history each tick catches all of them,
  plus the integration that never runs at all.
- **Failed vs clean.** Failed = a scheduled (`incremental` / `reconcile`) run that ended `FAILED`, or
  ended `SUCCESS` with a real Sorento push error, which is what sets "Last run failed". A budget
  cut-short run is clean. Manual failures never count, but a clean manual run closes an incident.
  `skipped`, `snapshot` and `ABORTED` runs are ignored.
- **Rules.** Consecutive: N failed scheduled runs in a row (default 2). Stale: no clean run for
  `max(M x incrementalMinutes, 60 min)` (default M = 3). The clock starts at the later of the last clean
  run and `max(activated_at, resumed_at)`. `resumed_at` is set only by resume, so `activated_at`
  ("Activated <date>" on screen) is never rewritten.
- **One incident per integration.** A partial unique index allows one open row
  (`closed_at IS NULL`) per `entity_config_id`. Pause, deactivate, alerts off, a newer resume and a
  deleted integration all close it with no email.
- **Mail.** The opening alert, then a reminder every 4 h, then one "recovered" notice. Before any
  reminder or recovered notice is enqueued, a guarded UPDATE claims the incident, so overlapping
  sweeps never double-send. Per-integration budget: a new incident emails only when no notice went out
  for that integration in the last 4 h, and a silent incident never sends "recovered".
- **Recipients.** Active users of the SAME tenant holding `autocount.companies.manage`, plus the
  integration's "Also email" list (strict ASCII, at most 10), de-duplicated. Outbox only
  (`email_service.enqueue_raw`). Each recipient sees times in their own `users.timezone`, else UTC.
  The link base is `settings.frontend_url` (BL-SS-298 covers tenant-host links).
- **Email safety.** Control characters are collapsed out of subjects, because one unsendable message
  marks the shared SMTP connection ERROR (BL-SS-309). Tenant and remote text is HTML-escaped in the
  body.
- **Settings.** `source_config` keys `alertsEnabled`, `alertAfterFailedRuns` (1..20),
  `alertStaleMultiple` (2..48) and `alertEmails`. An absent key means the default, so no backfill is
  needed. An alert-only `PUT .../etl-task` needs no `sourceConfig`, never re-runs the preview and never
  clears the activation gate.
- **UI.** An incident banner sits in the new `banner` slot of `ResourceForm`, between the record card
  and the tabs. The company integration list shows a `Failing` badge in the Health column. The
  Schedule tab has a "Failure alerts" card whose number fields are clearable.

## Out of scope

DO/GRN doc feeds (`ac_doc_feed_run`) are not watched yet: BL-SS-308. An in-app bell inbox does not
exist (IN_APP is inert, BL-058). WhatsApp is off, because the `messaging.send` capability is a stub.
