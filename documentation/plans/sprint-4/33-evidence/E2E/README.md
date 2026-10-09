# Plan 33 - Independent tester agent-browser evidence run (AC-MIG-01..61)

Independent verification, separate from the coder's own S0/S6 evidence runs. Branch
`sprint-4/33-respondio-migration`, worktree `.claude/worktrees/s33`, HEAD `d550b6f3`. Lane:
backend `:8012` (Postgres `foundryx_service_s33`, verified via `lsof -p <pid> | grep cwd` and a
live CORS probe against `Origin: http://localhost:3010` - process predates the HEAD commit by
timestamp but no source file is newer than the frontend's `.next/BUILD_ID`, so no restart/rebuild
was needed), frontend `:3010` (`next-server` owned by this worktree, confirmed via `lsof`).
`agent-browser` sessions: `s33t` (tenant A admin, real clicks from `/`), `s33t-ro` (tenant A
read-only RBAC probe), `s33t-b` (tenant B admin, isolation control). Real auth throughout, both
375x812 and 1280x900.

## Setup calls outside the UI (all disclosed, none committed)

1. **Tenant A + admin** - operator API, logged in as `platform@example.com` /
   `platform1234` at `tenantSlug: "platform"` against `:8012` directly (operator console itself
   not driven by clicks, only its API, per the brief's "operator-API setup OK"):
   `POST /platform/tenants {name, slug: "t33-mig-20260907t061224z", adminName, adminEmail:
   "tester-admin-20260907t061224z@example.com", adminPassword: "Password123!"}`.
2. **Tenant B + admin** (isolation control), same route: slug `t33-migb-20260907t061224z`, admin
   `tester-admin-b-20260907t061224z@example.com` / `Password123!`.
3. **RBAC probe role + user** (tenant A), via the tenant admin's own token:
   `POST /roles {name: "Migration Read Only", permissionKeys: ["omnichannel_migration.read"]}`
   then `POST /users {name, email: "migration-reader-20260907t061224z@example.com", roleIds}`
   (lands `INVITED`), then a direct ORM script setting `password = hash_password("Password123!")`
   and `status = "ACTIVE"` (the invite-email ceremony is out of scope; mirrors the S6 README's own
   documented shortcut and plan 29's precedent).
4. **Failures-table probe job** (tenant A) - this lane runs `CELERY_TASK_ALWAYS_EAGER=true`, so a
   real job finishes before the creating request returns; there is no naturally-occurring failure
   row to click through with clean input data. Hand-built via the app's own `SessionLocal` +
   `_write_failures_csv` helper (the SAME helper `tests/test_omnichannel_respondio_migration_s5.py
   ::test_failure_csv_round_trip_formula_guarded_and_empty_when_no_failures` calls, not a bespoke
   SQL insert): one failure row `{entity: "contacts", sourceId: "t33-probe-1", sourceLabel:
   "=SUM(A1:A10)", reason: "invalid lifecycle name: NoSuchStage", action: "skipped"}`, job
   `status=done, progressFailed=1`. **First attempt used a literal Python `None` for
   `payload_json.connectionId` and 500'd the list/detail routes - see Defect 1 below; the probe
   was corrected to `""` (empty string, matching what `create_job` actually persists) and re-used
   for the rest of the run.**
5. **Abort probe job** (tenant A) - same eager-mode reasoning; hand-built `BackgroundJob(status=
   running, progress_total=100, progress_done=40, cursor_json={"phase": "contacts"})` so Abort has
   a genuinely in-flight row to act on through a real click.
6. **>=2500-row CSV cap file** - generated locally (`t33-cap-20260907t061224z.csv`, 2500 data
   rows) and both curl-uploaded and UI-uploaded (`25-csv-row-cap-upload-1280.png`) to confirm the
   row count and the cap blocker; the resulting dry-run job was created via curl only (its
   counts/blockers already fully exercised through real UI clicks earlier in the run with the
   3-row file, so this second file's purpose was narrowly the cap blocker, not a duplicate full
   click-through).
7. **PNG-named-`.csv` upload** - curl multipart POST to `/omnichannel/migration/uploads` with a
   1x1 PNG's bytes saved as `fake-image.csv`, magic-byte sniffed and rejected 422.
8. **409 guard probes** - curl: (a) flipped the failures-probe job to `status=running` momentarily
   to prove `migration_in_progress` on a second `POST /jobs`, then reverted it; (b) `POST /jobs
   {mode:"run", ...a mapping that never had a matching dry run...}` to prove `dry_run_required`.
9. **Cross-tenant 404 probes** - curl from tenant B's own token against tenant A's job id,
   connection id (via preflight) and the failures.csv route.

None of steps 1-9 substituted for a real-click flow step; every flow step itself (module install,
connection create + Test, New migration, method switch, upload, mapping, dry run, Start, Abort,
Contacts list, RBAC-blocked page, tenant-B empty list) was driven by `agent-browser` clicks/types
against the live, real-auth stack.

## What was verified (real clicks unless marked curl/API)

1. **Module install via Services UI (App Store, real clicks)** - `00-omnichannel-installed-1280.png`.
2. **Migration menu gating negative case** - tenant B logged in BEFORE install: no Omnichannel/
   Migration entry anywhere in the sidebar (grep of the accessibility snapshot came back empty).
3. **Migration list, empty then populated (AC-MIG-02)** - `01-migration-list-empty-1280.png`,
   `13-migration-list-populated-1280.png` / `14-...-375.png` (exact column set: Source, Target
   workspace, Mode, Status, Progress, Contacts, Messages, Failures, Started, Finished).
4. **respond.io connection + live Test (AC-MIG-11/12/13)** - Settings > Integrations > Connect
   integration > provider `respond.io` (present in the registry) > filled `spaceLabel`/
   `timezone`/a dummy `apiToken` > Create > Actions > Test connection. The REAL
   `https://api.respond.io/v2/space/channel` call returned a genuine `401`, mapped to
   "respond.io rejected this access token." with no traceback/token fragment -
   `02-integration-form-filled-1280.png`, `03-integration-test-401-1280.png`.
5. **New migration, API mode preflight blocker (AC-MIG-03/07/14)** - picked the connection and
   target workspace; preflight ran against the real API, resolved `apiAvailable:false`, the
   inline "Blocked - respond.io rejected this access token." notice rendered on the Source card;
   `Start migration` stayed disabled - `04-new-migration-form-1280.png`,
   `05-api-mode-preflight-blocker-1280.png`.
6. **CSV mode (AC-MIG-46/03)** - Method switched to "CSV export" (SearchSelect, keyboard-typed +
   Enter - see the ref-instability note below); Channels/People/Lifecycle/Scope correctly absent;
   two dropzones appear - `06-csv-mode-1280.png`.
7. **CSV upload + header map (AC-MIG-47)** - uploaded a timestamped 3-row CSV
   (`t33-contacts-20260907t061224z.csv`: First Name, Last Name, Phone, Email, Lifecycle columns);
   "3 rows" recognized; explicitly mapped "First name" -> "First Name", left the rest "Not
   mapped" - `07-csv-upload-mapping-1280.png` / `08-...-375.png`.
8. **Dry run (AC-MIG-07/20/48)** - `Run dry run` -> real job -> Contacts `3 fetched / 3 would
   create`, every other entity 0, all THREE CSV-mode blockers stated up front (no message
   history, no channel identities, no media); `Start migration` flipped to enabled.
   **Screenshots `09`/`10` were mis-captured at the pre-scroll position (identical to `07`/`08`) -
   the report content itself was verified via `document.body.innerText` at the time (quoted in
   full in the session transcript) and is visually confirmed instead on the DETAIL page,
   `11-csv-run-detail-done-1280.png`, which shows the same Contacts `3/3/0/0/0` counts card.**
9. **Start migration -> Done -> Contacts list (AC-MIG-59)** - job detail reached `Done`, `3/3
   processed` - `11-csv-run-detail-done-1280.png` / `12-...-375.png`. Sidebar-clicked to
   Omnichannel > Contacts: Ada/Bob/Carl MigTester present with phone/email, confirmed via a
   tenant-scoped `GET /omnichannel/contacts?search=MigTester` read too (`total: 3`).
   **Defect 2 found here** - see below: all three landed on the "New Lead" INITIAL lifecycle
   stage regardless of their CSV `Lifecycle` value ("New Lead"/"Customer"/"New Lead").
10. **Re-run idempotency (AC-MIG-60)** - fresh "New migration" > CSV mode > re-uploaded the SAME
    file, left every header "Not mapped" (alias-fallback path) > dry run reports `3 fetched / 0
    would create / 3 would update` - `15-rerun-idempotent-1280.png`. Started the matching real
    run - `16-rerun-real-detail-1280.png`; `GET /omnichannel/contacts?search=MigTester` still
    `total: 3` afterward (API-verified against actual persisted state, not only the report).
11. **Failures table + authed CSV download (AC-MIG-08/53)** - opened the (corrected) failures
    probe job via a real row click: `Failures (1)` DataGrid (Entity/Source id/Source label/
    Reason/Action taken) - `17-failures-table-1280.png`; clicked "Download CSV" (a `<button>`,
    not a bare `<a href>`, confirmed via `eval`); curl-verified the SAME authed route returns
    `200`, `content-disposition: attachment`, `cache-control: private, no-store`,
    `content-security-policy: default-src 'none'; sandbox`, `x-content-type-options: nosniff`,
    and the formula-guarded body `'=SUM(A1:A10)` (leading apostrophe prevents spreadsheet
    execution on open).
12. **Abort (AC-MIG-28/57/60)** - opened the hand-inserted running probe via a real row click:
    `18-running-job-before-abort-1280.png` (`Running`, `40/100 processed`, Actions menu offers
    ONLY "Abort" - no Retry/Complete). Clicked Actions > Abort: page immediately showed `Aborted`,
    `40/100 processed` preserved - `19-aborted-job-1280.png`.
13. **RBAC read-only role (AC-MIG-50/60)** - second session `s33t-ro` logged in as the probe user
    (only `omnichannel_migration.read`): Migration list renders with no "New migration" button and
    no Actions column - `20-readonly-user-list-1280.png` / `22-...-375.png`. A direct open of
    `/omnichannel/settings/migration/new` (a guard check, not a flow step - same documented
    exception the S6 README used) renders the shell's "You don't have access to this page" block -
    `21-readonly-blocked-new-1280.png`. curl-independently confirmed: `GET .../jobs` -> `200`,
    `POST .../jobs` -> `403 {"detail":"Missing permission: omnichannel_migration.manage"}`.
14. **Tenant isolation (AC-MIG-51/52/60)** - third session `s33t-b`: fresh tenant B, installed
    Omnichannel via real clicks (App Store > Actions > Install), Migration list: "No data
    available" - `23-tenant-b-empty-list-1280.png` / `24-...-375.png`. curl-independently
    confirmed tenant B 404s on tenant A's job id, connection id (via preflight) and failures.csv
    route, with the SAME uniform "not found" shape a genuinely-missing id gets.
15. **409 guards (curl, AC-MIG-20/21)** - a second `POST /jobs` while one job was `running` for
    the same workspace -> `409 {"reason":"migration_in_progress"}`; a `run`-mode create whose
    mapping never had a matching dry run -> `409 {"reason":"dry_run_required"}`.
16. **PNG-named-.csv rejected (AC-MIG-47's sniff gate)** - curl multipart upload of PNG bytes named
    `fake-image.csv` -> `422 {"fieldErrors":{"file":"Unsupported file - upload a CSV (or xlsx/xls)."}}`.
17. **>=2500-row cap (AC-MIG-46's own limit, plan section 4 CSV-mode limits)** - a locally
    generated 2500-row CSV, uploaded both via curl and via a real UI upload
    (`25-csv-row-cap-upload-1280.png`, "2500 rows" recognized); the resulting dry run's blockers
    list led with "This contacts file has 2500 rows, at or over respond.io's own 2500-row
    Contacts-module export cap...".
18. **Dirty-guard AlertDialog** - clicking Cancel on a form with an uploaded file triggered the
    shell's "Discard changes?" dialog (not a bespoke confirm).
19. **Console** - `agent-browser console` / `errors` came back empty at every checkpoint across all
    three sessions.

## Defects found (both reproducible, repro steps + root cause below; also in the main report)

**Defect 1 (low severity, not reachable through normal UI/API use as shown)** - `GET
/omnichannel/migration/jobs` (list) and the job-detail read 500 with an unhandled
`pydantic_core.ValidationError` (`MigrationJobItem.connectionId` typed as `str`, not
`Optional[str]`) if a job row's `payload_json.connectionId` is JSON `null` rather than `""`.
`modules/omnichannel/services/migration_service.py:1435` reads it with
`payload.get("connectionId", "")`, whose default only applies when the KEY IS ABSENT, not when it
is present-and-`None`. Every REAL create path is safe because `create_job` (`:1233`) always
stores `payload.connectionId or ""`, so this is a defensive-coding gap (a stray `None` from any
future write path, a manual script, or an older pre-fix row would 500 the whole list), not a
customer-reachable bug via the described flows.

**Defect 2 (functional, reproducible, affects real migrated data) - CSV-mode `Lifecycle` CSV
column is silently ignored; every contact lands on the workspace's INITIAL lifecycle stage
regardless of its CSV value.** Root cause: `MigrationWriter.write_contact` (`migration_writer.py:
~628-636`) resolves lifecycle ONLY through `self.lifecycle_map`, which is built EXCLUSIVELY from
the operator-submitted `payload.lifecycleMap` (`migration_service.py:~1953-1961`) - the API-mode
Lifecycle-section mapping. CSV mode's setup form has NO Lifecycle mapping section (Channels/
People/Lifecycle are deliberately hidden for CSV mode per this slice's own S6 commit), so
`payload.lifecycleMap` is always `[]` for a CSV job and `self.lifecycle_map` is always `{}`. Every
CSV contact whose `Lifecycle` cell is non-empty therefore fails to map and falls through to
`contact.lifecycle_status_id = mapped or self.initial_lifecycle_status_id` - landing on the
INITIAL stage, not the CSV-specified one. This directly contradicts the plan's own contract
(section 5.6's CSV column table: "Lifecycle -> lifecycle -> resolver matches an existing stage by
key or label" - implying direct key/label resolution against the target workspace's stages, which
is not implemented for CSV mode at all) and the runbook's own claim (section 3, step 2: "a
lifecycle-mapping blocker... means those contacts land with no lifecycle stage" - they do not;
they silently land on the INITIAL stage with ZERO blocker or report signal, since the SAME
`lifecycle_unmapped` counter that the API-mode phase loop tracks is never incremented on the
separate CSV-mode contacts loop, `migration_service.py:~628-636`, which has no
`if outcome.lifecycle_unmapped: lifecycle_unmapped += 1` line at all).

Reproduced twice independently: this tester's own run (Ada/Bob/Carl all show "New Lead" despite
Bob's CSV row reading "Customer" - confirmed via `GET /omnichannel/contacts?search=Bob`'s
`lifecycle.key: "new_lead"`) AND the coder's own S6 evidence screenshot
(`33-evidence/S6/08-contacts-list-migrated-1280.png`) shows the identical symptom (all three
contacts "New Lead") despite the coder's own test-report prose claiming "New Lead/Customer
lifecycle" (differentiated) - the coder's screenshot contradicts their own report text.

## Ref-instability note (tooling, not a product bug - matches the S6 README's own finding)

`SearchSelect` option clicks via `agent-browser click @eN` intermittently no-op (the dropdown
stays open, the value never changes) once a page has re-rendered between snapshot and click,
even with a dispatched multi-event pointer sequence (`pointerdown`/`mousedown`/`pointerup`/
`mouseup`/`click`). The reliable fallback used throughout this run: click the combobox to open
it, `agent-browser keyboard type "<search text>"`, then `press Enter` - this dispatches real
keyboard events against the `SearchSelect`'s own filter+select-on-Enter behavior and never
depended on a stale ref.
