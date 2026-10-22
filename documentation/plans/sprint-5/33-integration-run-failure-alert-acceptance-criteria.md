# 33 - Alert when a scheduled integration run keeps failing - acceptance criteria

Lane: SS-INTEGRATION-ALERT (crew), PR #128. Plan: `33-integration-run-failure-alert.md`.

Owner answered the behaviour card as recommended (Q1 a, Q2 b, Q3 a, Q4 a, Q5 a) and approved
mockup v1, 22 Oct 15:15. DO/GRN doc feeds are out of scope (BL-SS-308).

Terms:
- **Integration** = one `AcEntityConfig` row (`app_autocount.ac_entity_config`).
- **Failed run** = an `AcSyncRun` with mode `incremental` or `reconcile` that ended `FAILED`, or ended
  `SUCCESS` with a Sorento push error (exactly the runs that set the task's `last_run_error`, so the
  screen shows "Last run failed"). A crashed or orphaned run (`bootstrap.on_job_orphaned`) counts as
  failed. A run cut short by the run budget (`SUCCESS`, `error` = "Budget reached after page N;
  continues on the next tick.", `sync.py:1979-1980,2252-2257`) is NOT failed (crew audit 22 Oct).
- **Clean run** = any run (scheduled or manual) that ended `SUCCESS` with no push error, including a
  budget cut-short run.
- `skipped`, `snapshot` and `ABORTED` runs are neither failed nor clean. Manual failures do not count.
- **Incident** = one open alert state per integration, from the moment it trips until it closes.

## Detection

- **AC-33-01 [BE][T]** Consecutive rule. An ACTIVE integration whose last N terminal scheduled runs are
  all failed (N = the integration's "failed runs in a row", default 2) opens an incident. A clean run
  inside the window resets the count. Manual failures and skipped ticks neither count nor reset.
- **AC-33-02 [BE][T]** Stale rule. An ACTIVE integration with no clean run finished in the last
  `max(M x incrementalMinutes, 60 min)` opens an incident (M default 3). The clock starts at the later
  of the last clean run and the time the integration was last activated or resumed, so a freshly
  activated integration with no run yet does not trip at once. A resume is stamped in its own
  nullable `resumed_at` column; `activated_at` (shown as "Activated <date>") is never rewritten by a
  resume. NULL = not resumed since plan 33, no backfill needed. A wedged run that never finishes trips
  this rule.
- **AC-33-03 [BE][T]** The check runs from the existing 60 s ETL sweep (`scheduler.sweep_etl_tasks`),
  over every ACTIVE integration of every tenant where the AutoCount module is active. One integration's
  error never stops the check for the others nor the sweep's own enqueueing (logged, isolated).
- **AC-33-04 [BE][T]** Alerts off on an integration: no incident opens; an open one closes silently.

## Notices

- **AC-33-05 [BE][T]** Opening an incident sends ONE alert email per recipient. Running the check
  again while it stays open sends nothing until 4 h after the last notice, then ONE reminder, and so
  on every 4 h. Two overlapping checks never send the same reminder or recovered notice twice: the
  incident row is claimed with a guarded update before any email is enqueued.
- **AC-33-06 [BE][T]** The first clean run (scheduled or manual) after an incident opened closes it and
  sends ONE "recovered" email. A later check sends nothing more.
- **AC-33-07 [BE][T]** Pausing or deactivating the integration closes its open incident with no
  email. Re-activating starts fresh (a new incident needs the rules to trip again). A pause and resume
  that both land between two checks also close the open incident (the resume is newer than the
  incident) and the check starts fresh. Resuming never rewrites `activated_at`. An open incident whose
  integration no longer exists is closed.
- **AC-33-08 [BE][T]** Recipients: every ACTIVE user of the SAME tenant who holds
  `autocount.companies.manage` and has an email, plus the integration's "Also email" addresses,
  de-duplicated case-insensitively. Never a user of another tenant. No recipients: the incident still
  opens (banner), no email, no error.
- **AC-33-09 [BE][T]** Wording. Alert subject `<Integration> (<Company>) has failed <n> runs in a row`
  (stale rule: `<Integration> (<Company>) has had no successful run since <time>`); reminder
  `Still failing: <Integration> (<Company>), <n> failed runs since <time>`; recovered
  `<Integration> (<Company>) is running again`. The body names integration, company (name and
  database), failing-since time, failed-run count, the last error's first line, and a button to the
  integration's Runs tab (`.../autocount/companies/<id>/entities/<type>?tab=runs`) on
  `settings.frontend_url`, the same base every account email uses (`user_service.py:278`). A
  non-default tenant's link therefore lands on the bare host: BL-SS-298 (tenant-host links) covers it.
  Times use the recipient's `users.timezone`, else UTC, with the zone shown. No "Foundryx" in the text.
- **AC-33-10 [BE][T]** Emails go through the outbox (`email_service.enqueue_raw`) only. Tests never
  reach SMTP. No WhatsApp is sent.

## Settings

- **AC-33-11 [BE][T]** Per-integration settings live in `source_config` beside the schedule:
  `alertsEnabled` (default true), `alertAfterFailedRuns` (default 2, 1..20), `alertStaleMultiple`
  (default 3, 2..48), `alertEmails` (default empty, at most 10 valid addresses). An absent key means the
  default, so every existing integration is covered with no backfill. Out-of-range or invalid input is
  a 422 naming the field. Saved by the existing Schedule save (gated `autocount.companies.manage`).
  Saving ONLY alert settings never re-runs the source preview and never clears the activation gate, so
  an admin can turn alerts off while the source is down (crew audit 22 Oct). "Also email" accepts plain
  ASCII addresses only, validated by the house email validator.

## Surfaces

- **AC-33-12 [BE][T]** `GET .../entities/{type}/etl-task` and the company detail's integration rows
  carry the open incident (`openedAt`, `firstFailureAt`, `failedRuns`, `lastError`, `reason`
  consecutive|stale) or null. Tenant-scoped.
- **AC-33-13 [FE][T]** Integration page: while an incident is open, a banner under the header reads
  `Failing since <time> - <n> failed runs. Last error: <line>` with a "View runs" action to the Runs tab.
  No banner when there is no open incident.
- **AC-33-14 [FE][T]** Company detail integration list: the failing integration's row shows a
  `Failing` status badge.
- **AC-33-15 [FE][T]** Schedule tab: a "Failure alerts" section with the four settings, loaded from and
  saved with the schedule, dirty-guarded like the rest of the tab. The two number fields are clearable:
  a cleared field stays empty (never snaps to 0) and Save with an empty field shows that field's error
  instead of sending a value (owner rule "number fields clearable"). An alert-only change saves
  without running the source preview.

## Platform

- **AC-33-18 [BE][T]** Mail budget per integration (security review 22 Oct). A new incident's opening
  alert is emailed only when no alert, reminder or recovered notice went out for that integration in
  the last 4 h; otherwise it opens with the banner and badge only, and its first email follows the
  4 h cadence. A recovered notice goes out only for an incident that emailed at least once. Toggling
  alerts off and on, or a source that flaps between failing and clean, therefore sends at most one
  alert and one recovered notice per integration per 4 h.
- **AC-33-19 [BE][T]** Email safety. The subject has CR, LF and other control characters collapsed to
  single spaces (a tenant-typed company name can never break the outbox or the shared SMTP
  connection). Tenant-authored and remote text (integration and company names, the error line) is
  HTML-escaped in the body.
- **AC-33-20 [BE]** The per-integration check uses aggregate queries (count / min / latest one) on an
  index `(tenant_id, company_id, entity_type, finished_at)` of `ac_sync_run`, shipped in 0031 and the
  crew SQL; it never loads every failed run.
- **AC-33-16 [BE]** New module table `ac_task_incident` (UUID id, tenant-scoped, one open row per
  integration) via module Alembic, verified on live Postgres; matching idempotent SQL at
  `crew/state/migrations/SS-INTEGRATION-ALERT.sql`. (The two global guard tests the crew brief names,
  `test_schema_uuid_id_principle.py` and `test_list_pagination_limit.py`, do not exist in this repo:
  `git ls-files` finds neither. The new id is a UUID string; no list endpoint is added.)
- **AC-33-17 [E2E]** agent-browser run at 1280 and 375 on the crew test copy: banner, row badge,
  Schedule settings save, and the outbox row for the alert.
