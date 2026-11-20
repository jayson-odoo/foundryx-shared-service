# Plan 33 S6 - agent-browser evidence run (AC-MIG-56..61)

Lane: `.claude/worktrees/s33`, backend `:8012` (Postgres `foundryx_service_s33`), frontend
`:3010` (`npx next start -p 3010`, fresh `rm -rf .next && npm run build`), `agent-browser`
sessions `s33c2` (tenant A admin), `s33c3` (tenant A read-only probe user), `s33c4` (tenant B
admin). Real clicks from `/` (or the tenant's own subdomain login page, the one documented
exception below), never a typed URL to REACH a flow step, at 1280x900 and 375x812.

Two probe rows were hand-inserted directly into `foundryx_service_s33` Postgres (documented,
not committed anywhere) because this lane runs `CELERY_TASK_ALWAYS_EAGER=true`: a job handler
executes INLINE within the same HTTP request that created it, so a 3-row CSV job is `done`
before the response even returns - there is no naturally-observable in-flight window to click
Abort against, and no naturally-occurring failure row to exercise the failures-CSV download
against with clean input data. Both insert scripts are reproduced below; both rows were then
reached and acted on through REAL CLICKS from the Migration list, exactly like a genuinely
in-flight/failed job would be.

## Setup calls (all disclosed)

1. **Tenant A** provisioned via the operator API (`POST /platform/tenants`, logged in as
   `platform@example.com` at `platform.localhost:3010`... actually issued directly against
   `:8012` with `tenantSlug: "platform"` - the operator console itself was not used, only its
   API, to keep the browser sessions focused on the feature under test):
   slug `p33-mig-20260907t042326z`, admin `migration-admin-20260907t042326z@example.com` /
   `Password123!`.
2. **Tenant B** (isolation control), same route: slug `p33-migb-20260907t045000z`, admin
   `migration-admin-b-20260907t045000z@example.com` / `Password123!`.
3. **RBAC probe role + user** (tenant A), via the tenant admin's own token:
   `POST /roles {name, permissionKeys:["omnichannel_migration.read"]}` then
   `POST /users {name, email, roleIds:[<role>]}` (lands `INVITED`), then one direct
   `UPDATE`-via-ORM script setting `password = hash_password("Password123!")` and
   `status = "ACTIVE"` (the invite-email ceremony is out of scope here - the same shortcut
   plan 29's own E2E evidence run used for its no-send probe identity).
4. **Failures-table probe row** (tenant A, hand-inserted `BackgroundJob`, `status=done`,
   `progress_failed=1`, one failure row `{entity:"contacts", reason:"invalid phone - could
   not derive digits", ...}`) - mirrors the exact shape `tests/test_omnichannel_respondio_
   migration_jobs.py::test_failures_csv_download_authed_private_no_store` already pins.
5. **Abort probe row** (tenant A, hand-inserted `BackgroundJob`, `status=running`,
   `progress_done=40/100`) - mirrors `test_cancel_job_aborts_running_and_409_when_terminal`'s
   own hand-built-running-job convention.

Neither probe row nor the RBAC role/user were committed to the repo; all four live only in the
`foundryx_service_s33` Postgres database for this lane.

## What was verified (real clicks, both viewports)

1. **Integrations Test (AC-MIG-13, live vendor call).** Settings > Integrations > Connect
   integration > provider `respond.io` > filled `spaceLabel`/`timezone`/a dummy `apiToken` >
   Create > Actions > Test connection. The REAL `https://api.respond.io/v2/space/channel` call
   (this machine has network access, no valid token) returned a genuine `401`, mapped exactly
   per AC-MIG-13: **"respond.io rejected this access token."** - `01-integration-test-401-1280.png`.
2. **Migration list (AC-MIG-02), empty then populated** - `02-list-empty-1280.png`,
   `17-list-375.png` (non-clipped, columns scroll horizontally at 375px). Server-side search,
   sort and the Filter popover were EXTENDED this slice (`MigrationService.list_jobs`,
   `_LIST_SORT_FIELDS`/`_filter_rule_matches`) - S2 had shipped pagination + the status
   segment only; a search box/sortable columns/Filter popover that silently no-op against the
   real backend would have been a foolproof-UI violation this slice's own live run would have
   caught. Covered by `tests/test_omnichannel_respondio_migration_jobs.py::
   test_list_jobs_search_sort_and_filter` (pytest, not separately re-clicked live here since
   AC-MIG-59/60's own script did not call for it).
3. **New migration, API mode (AC-MIG-03/04/05/06/07).** Picked the just-created connection;
   preflight ran against the REAL respond.io API with the same dummy token, resolved
   `apiAvailable:false`, and the Source card now renders the **Blocked** notice inline
   ("respond.io rejected this access token.") - a genuine S6 gap-fix: S0-S1 never wired
   `preflight.warnings` to any surface at all; this run's own API-mode pass is what surfaced
   it. `Start migration` stayed disabled (no dry run ever ran against a rejected token);
   `Run dry run` was NOT clicked in this mode (a dry run against an invalid token is a
   pytest-covered path, `test_omnichannel_respondio_migration.py`, not a live click here since
   AC-MIG-59 only asks for the blocker + Start-disabled state in API mode) -
   `03-api-mode-preflight-blocker-1280.png`.
4. **Switch to CSV mode (AC-MIG-46/47).** The connection picker and Channels/People/Lifecycle/
   Scope sections all correctly disappear; two upload dropzones appear (Contacts CSV,
   required; Quick replies CSV, optional). Uploaded a timestamped 3-row CSV
   (`s33-contacts-20260907t042326z.csv`, columns First/Last Name, Phone, Email, Lifecycle) via
   the REAL `POST /omnichannel/migration/uploads` route - `201`, 3 rows, headers echoed back
   into the header-map section (mapped "First name" explicitly; left the rest to the
   backend's own case-insensitive alias guess) - `04-csv-mode-upload-mapping-1280.png` /
   `05-csv-mode-upload-mapping-375.png` (non-clipped, single-column stack).
5. **Dry run (AC-MIG-07/20/48).** `Run dry run` -> real `POST /omnichannel/migration/jobs`
   (`mode:dry_run, source:csv`) -> Counts report: Contacts `3 fetched / 3 would create`, every
   other entity genuinely zero, all THREE CSV-mode blockers stated up front (no message
   history, no channel identities, no media) - `Start migration` flips from disabled to
   enabled the instant the dry run settles `done` -
   `06-csv-dryrun-report-1280.png`.
6. **Real run + Contacts list (AC-MIG-59).** `Start migration` -> real
   `POST /omnichannel/migration/jobs` (`mode:run`) -> job detail polls to `Done`,
   `3/3 processed`, Counts report shows `3 would create` -
   `07-csv-run-detail-done-1280.png`. Navigated to Omnichannel > Contacts (sidebar, real
   click): Ada/Bob/Carl `MigE2E-20260907t042326z` all present with their phone/email and
   `New Lead`/`Customer` lifecycle - `08-contacts-list-migrated-1280.png`. Confirmed via the
   tenant-scoped `GET /omnichannel/contacts?search=MigE2E` API read too: `total: 3`.
   **CORRECTION (review round 1 fix commit):** this line's "New Lead/Customer" claim was WRONG
   as originally written - the screenshot itself shows all three contacts landed on "New Lead"
   regardless of their CSV `Lifecycle` cell, because CSV mode never resolved that column at all
   (filed as the test report's Defect 2). Fixed in the review-round-1 commit: CSV mode's
   Lifecycle value now resolves via `lifecycleMap` when present, else an exact key/label match
   against the target workspace's own stages (`find_stage_by_key_or_label`, map-only, never
   create); an unmapped value still lands the contact on the initial stage but is now reported
   as a `lifecycleUnmappedByValue` report row + blocker line. See
   `tests/test_omnichannel_respondio_migration_review1.py`
   (`test_csv_mode_lifecycle_resolves_by_stage_key_and_reports_the_unmapped_value`) and the test
   report's Defect 2 section (now FIXED) for the corrected behavior.
7. **Re-run idempotency (AC-MIG-60).** New migration > CSV mode > re-uploaded the SAME file
   (a fresh upload, new storage key - the mapping hash still matches since `contactsCsvKey`
   content is irrelevant to the hash, only the ROW DATA re-resolves identically) > left every
   header "Not mapped" this time (exercises the alias-fallback path, `_HEADER_ALIASES`, the
   mirror of run 1's explicit mapping) > dry run reports `3 fetched / 0 would create / 3 would
   update` - `09-rerun-idempotent-zero-creates-1280.png`. Started the matching real run too;
   `GET /omnichannel/contacts?search=MigE2E` still reports `total: 3` afterward - zero
   duplicates, confirmed against actual persisted state, not only the report.
8. **Failures table + authed CSV download (AC-MIG-08/53).** Opened the hand-inserted
   failures-probe job via a real row click from the Migration list: `Failures (1)` table
   renders (Entity/Source id/Source label/Reason/Action) -
   `10-failures-table-1280.png`. Clicked **Download CSV**: real
   `GET /omnichannel/migration/jobs/{id}/failures.csv` fired (`200`), the SAME authed-fetch-
   then-Blob-download pattern the codebase's other exports use (never a bare `<a href>`) -
   `11-failures-download-clicked-1280.png`.
9. **Abort (AC-MIG-28/57/60).** Opened the hand-inserted running-probe job via a real row
   click: `12-running-job-before-abort-1280.png` (`Running`, `40/100 processed`, Actions menu
   offers ONLY "Abort" - no Retry/Complete, the S6 decision below). Clicked Actions > Abort:
   real `POST /omnichannel/migration/jobs/{id}/cancel` (`200`, the DEDICATED route, never the
   generic `/jobs/{id}/abort`) - the page immediately shows `Aborted`, `40/100 processed`
   preserved (partial counts intact) - `13-aborted-job-1280.png`.
10. **RBAC - read-only role (AC-MIG-60).** A second browser session (`s33c3`) logged in as a
    user holding ONLY `omnichannel_migration.read`: the Migration list renders (read works)
    with no "New migration" button and no "Actions" column at all -
    `14-readonly-user-list-1280.png`. A direct open of `/omnichannel/settings/migration/new`
    (a guard check, not a flow step) renders the shell's own "You don't have access to this
    page" block - `15-readonly-user-blocked-new-1280.png`. The API itself independently
    confirmed: `GET .../jobs` -> `200`, `POST .../jobs` -> `403`.
11. **Tenant isolation (AC-MIG-51/52/60).** A third session (`s33c4`) provisioned tenant B
    fresh, installed Omnichannel via real clicks (App Store > Omnichannel > Actions >
    Install), navigated to Migration: `No data available` - tenant B never sees any of tenant
    A's jobs - `16-tenant-b-empty-list-1280.png`.
12. **White-label fix, verified live.** The S0 setup-form subtitle read "Map a respond.io
    space onto a **Foundryx** workspace" - a live hard-fail this run's own screenshot caught
    (`04-csv-mode-upload-mapping-1280.png`, pre-fix). Fixed in `migration-form-view.tsx`
    (`'Map a respond.io space onto a workspace'`), rebuilt, re-verified: `document.body.
    innerText.includes('Foundryx')` -> `false` on the same page -
    `19-whitelabel-fix-verified-1280.png`.
13. **Detail report at 375px** - `18-detail-report-375.png` (Progress/Details/Counts report
    cards stack, DataGrid scrolls horizontally, blockers stay `ClampedText`-recoverable, no
    clipping).
14. **Milestone log, a genuine AC-MIG-08 gap this run's own AC re-check caught (not
    previously flagged).** AC-MIG-08 requires the detail page to render "the milestone log";
    `JobService.log()` had been writing `background_jobs.logs_json` since S2 (page
    checkpoints, rate-limit backoff, abort detection), but neither `MigrationJobItem` nor the
    detail page ever surfaced it - a straight omission, not something S0's mock ever modelled
    either. Fixed this slice: `MigrationJobLogEntry` schema + `MigrationJobItem.logs` (detail
    read only - `include_logs=True`; the list read always sends `[]`, pinned by a new pytest),
    and a `Logs` card on the detail page (verbatim clone of `jobs/[id]/page.tsx`'s own Logs
    card - timestamp/level/message, "No log entries yet." when empty). Rebuilt, re-verified
    live: `20-logs-card-1280.png`. This lane's own jobs never triggered a real milestone line
    (a 3-row CSV completes in one page, no backoff, no server-side abort mid-run), so the
    CARD's presence is confirmed live but a populated LINE is pytest-only
    (`test_get_job_surfaces_milestone_log_list_does_not`).

## Console

No console errors observed across any of the four sessions during the run (a pre-existing
generic Radix `DialogContent` a11y warning, same as S0's own note, is the only recurring
console line and is unrelated to this slice).

## Deliberately not re-verified live here (pytest-covered, stated in the S6 brief)

- **API-mode message-history migration into a live Inbox thread** (AC-MIG-59's own
  "confirm a migrated thread shows its history in original order... no unread badge" clause) -
  this machine has no valid respond.io token, so no API-mode run can ever reach the
  identities/messages/media/events phases live. Covered by `tests/test_omnichannel_
  respondio_migration_s3.py`/`_s4.py` (timestamp resolution, delivery-status mapping,
  `agent_last_read_at` set to `last_message_at`, the no-publish/no-entity-event assertions).
- **Cursor resume after a genuine crash-mid-flight abort** (AC-MIG-60's "a later re-run
  resumes" clause) - `CELERY_TASK_ALWAYS_EAGER=true` runs a job's whole handler inline before
  the creating request even returns, so there is no way to interrupt a REAL run mid-page from
  a browser click; the abort demonstrated above (10) is a hand-built `running` row, which
  proves the cancel route + UI state transition but not the cursor-resume mechanics
  themselves. Covered by `tests/test_omnichannel_respondio_migration_jobs.py::
  test_cooperative_abort_stops_before_next_page_and_resume_continues`.

## Ref-stability note (tooling gotcha, not a product bug)

`agent-browser snapshot`'s `@eN` refs occasionally pointed at a DIFFERENT element than the one
named in the immediately-preceding isolated snapshot once the page had multiple overlapping
regions (e.g. a full-page snapshot vs. an open-combobox-only snapshot reusing the same ref
numbers for different nodes) - clicking a ref that LOOKED right sometimes silently hit
"Cancel" instead of the intended option, or did nothing at all off-screen (a DataGrid's
"Actions" column scrolled out of the 1280px viewport). The reliable fallback used throughout
this run: `agent-browser eval --stdin` with a `document.querySelectorAll(...).find(...)` text
match, or `type` + `press Enter` for `SearchSelect` comboboxes - both dispatch REAL DOM
events (`element.click()`, a real `keydown`), not a synthetic ref-indexed click. Filed as a
process note (`docs/reference/process-lessons.md` is the home for this class of finding, not
touched by this coder - flagged for whoever next owns that file).
