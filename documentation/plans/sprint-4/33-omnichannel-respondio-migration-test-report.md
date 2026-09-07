# Sprint 4 - Plan 33 - Omnichannel respond.io Migration Tool - Independent Test Execution Report

> **This report REPLACES the coder's own `33-omnichannel-respondio-migration-test-report.md`.**
> It is an INDEPENDENT verification run by the tester agent, not a re-statement of the coder's own
> S6 evidence. The coder's per-slice notes are kept as an appendix (section 9) for reference where
> they add detail this run did not re-derive from scratch (e.g. exact pytest counts per slice).

**Branch:** `sprint-4/33-respondio-migration` **HEAD:** `d550b6f3d35c94082f830a725ef582565accce7a`
**Worktree:** `.claude/worktrees/s33` (never the main checkout)
**Lane:** backend `:8012` (Postgres `foundryx_service_s33`), frontend `:3010` (prod build, `next-server`
owned by this worktree, confirmed via `lsof -p $(lsof -ti :3010) | grep cwd`)
**Contract:** `documentation/plans/sprint-4/33-omnichannel-respondio-migration-acceptance-criteria.md`
(61 ACs), `33-omnichannel-respondio-migration.md` (plan, decisions D-A6-1..24, section 4 slices,
section 7 prerequisites, section 9 risks), `documentation/omnichannel/respondio-cutover-runbook.md`.
**Format:** `AI_Agent_Orchestration_Guide.md` section 6, adapted to this repo's established
AC-id-keyed table convention (the same shape every prior plan's test report in this repo uses);
explicit User-Story/Scenario/Steps/Expected/Actual narrative given for the two `[E2E]` AC ids
(59, 60) per the guide's literal table shape.

## Result summary

| Gate | Result |
|---|---|
| Full backend suite (`python -m pytest -q`, ONE run) | **3707 passed, 11 failed, 1 skipped, 18 deselected** in 2279.84s. **All 11 failures are a pre-existing full-suite-order flake, NOT a plan-33 regression** - see "Full-suite failure triage" below. Zero failures among any `test_omnichannel_respondio_migration*.py` file. |
| Full frontend suite (`npm test` = `vitest run`, ONE run) | **335 files, 2548 tests, all PASSED.** 2 unrelated "Unhandled Rejection" warnings from AutoCount task-editor test files (pre-existing `undici`/RHF interaction, not touched by this slice) - did not fail any test. |
| `[E2E]` AC-MIG-59 (CSV-mode full journey, dedicated tenant, real clicks) | **PASS**, with one functional defect found live - see Defect 2 |
| `[E2E]` AC-MIG-60 (re-run/abort/RBAC/isolation) | **PASS** |
| Responsive 375px + 1280px | **PASS** - verified at both viewports on every new/changed surface touched this run |
| Independent defects found this run (not in the coder's own report) | **2** - see "Defects found" below. **Both FIXED in Fix round 1** (see the final section of this report). |

Evidence directory (this tester's own, independent of the coder's S0/S6 dirs):
`documentation/plans/sprint-4/33-evidence/E2E/` (25 screenshots + `README.md` with every setup
call verbatim).

## Defects found (independent finding, both reproduced and root-caused)

### Defect 1 - LOW severity, not reachable via any real UI/API flow demonstrated in this run - **FIXED (Fix round 1)**

> **Status update:** fixed in the review-round-1 fix commit (see "Fix round 1" section at the end
> of this report for the commit hash and probe evidence). `MigrationJobItem.connectionId` is now
> `Optional[str] = None`; live-probed via `GET /omnichannel/migration/jobs` (list) and `GET
> /omnichannel/migration/jobs/{id}` (detail) against a hand-built row with a literal stored `null`
> - both return `200` with `connectionId: null`, never a 500.

`GET /omnichannel/migration/jobs` (list) and the per-job read 500 with an unhandled
`pydantic_core.ValidationError` ("Input should be a valid string [type=string_type,
input_value=None...]") when a job row's `payload_json.connectionId` is JSON `null`.
`MigrationJobItem.connectionId` (`schemas.py:1789`) is typed plain `str`, and
`migration_service.py:1435`'s `_to_item` reads it with `payload.get("connectionId", "")` - a
default that only fires when the KEY IS ABSENT, not when it is present-and-`None`. Every REAL
create path is safe: `create_job` (`migration_service.py:1233`) always stores `payload.connectionId
or ""`, so a genuine CSV-mode job (no connection at all) persists `""`, never `null` - confirmed
by querying every job this run created (`psql ... payload_json->'connectionId'` on 7 rows: all
either a real connection id or the empty string `""`, never JSON `null`). The 500 was reached only
through a hand-built probe row (documented in the E2E README) that initially used a literal
Python `None`; corrected to `""` (matching the real contract) once found, and the rest of the run
used the corrected row. **Recommendation:** either type `MigrationJobItem.connectionId:
Optional[str] = None` (matching the request-side `MigrationJobCreate.connectionId`) or change the
read-side default to `payload.get("connectionId") or ""` (both, defensively, since the read
already tolerates a missing key). Not a customer-reachable regression as shipped; a genuine
defensive-coding gap that would 500 the whole list if any future write path (a data migration,
a manual fix script, an older pre-`or ""` row) ever produces a literal `null`.

### Defect 2 - FUNCTIONAL, reproducible via real UI clicks, affects migrated customer data - **FIXED (Fix round 1)**

> **Status update:** fixed in the review-round-1 fix commit (see "Fix round 1" section at the end
> of this report for the commit hash and probe evidence). CSV mode's `Lifecycle` column now
> resolves through `lifecycleMap` when present, else an exact key/label match against the target
> workspace's own stages (`find_stage_by_key_or_label` - the SAME canonical resolver the gateway
> PATCH route already uses, not a parallel one - map-only, never creates a stage). An unmapped
> value still lands the contact on the initial stage (never blank, never silently dropped) but is
> now reported as a `report.lifecycleUnmappedByValue` row plus a blocker line naming the exact
> value and count. Live-probed end to end (upload -> dry run -> real run -> contacts list) with a
> 3-row CSV carrying two mapped values (`hot_lead`, `customer`) and one unmapped value
> (`not-a-real-stage`): all three contacts landed on the correct stage, the unmapped one on the
> initial stage with the expected blocker line and `lifecycleUnmappedByValue: {"not-a-real-stage":
> 1}`. Unit-tested: `tests/test_omnichannel_respondio_migration_review1.py::
> test_csv_mode_lifecycle_resolves_by_stage_key_and_reports_the_unmapped_value` (3-row CSV, two
> mapped + one unmapped -> stages set + one report row) and `::
> test_csv_mode_lifecycle_via_explicit_map_still_wins_over_the_key_label_fallback`.

**CSV-mode migration jobs silently ignore the CSV file's own `Lifecycle` column.** Every CSV-mode
contact lands on the target workspace's INITIAL lifecycle stage, regardless of what its `Lifecycle`
cell says - with ZERO blocker, warning, or report signal telling the operator this happened.

**Repro (this tester's own run, and independently reproduced in the coder's own S6 evidence
screenshot):**
1. Upload a CSV with a `Lifecycle` column carrying two distinct, both-VALID target stage labels
   (this run used "New Lead" and "Customer" - the fresh tenant's own default lifecycle stages,
   confirmed via `GET /omnichannel/workspaces/{ws}/lifecycle`: `new_lead` (isInitial:true),
   `hot_lead`, `payment`, `customer`, `cold_lead`).
2. Run the migration (dry run then Start, or Start directly).
3. Open Omnichannel > Contacts: EVERY migrated contact shows "New Lead" (the INITIAL stage),
   including the row whose CSV cell read "Customer".
4. Confirmed via API, not just the UI: `GET /omnichannel/contacts?search=Bob` ->
   `lifecycle.key: "new_lead"` for the contact whose CSV `Lifecycle` value was "Customer".
5. The coder's own `33-evidence/S6/08-contacts-list-migrated-1280.png` shows the IDENTICAL
   symptom (Ada/Bob/Carl all "New Lead") despite the coder's own test-report prose claiming
   differentiated "New Lead/Customer lifecycle" outcomes - the coder's own screenshot contradicts
   their report text, meaning this was already reproducible in the coder's own evidence and went
   unnoticed.

**Root cause:** `MigrationWriter.write_contact` (`modules/omnichannel/services/migration_writer.py`,
around line 628) resolves a contact's lifecycle stage ONLY via `self.lifecycle_map`, a dict built
EXCLUSIVELY from the operator-submitted `payload.lifecycleMap` (API-mode's Lifecycle mapping
section, `migration_service.py` around line 1953). CSV mode's setup form has NO Lifecycle mapping
section at all (Channels/People/Lifecycle sections are deliberately hidden in CSV mode, confirmed
live: `06-csv-mode-1280.png` shows only Source/Target/Review), so `payload.lifecycleMap` is always
`[]` for a CSV job, `self.lifecycle_map` is always `{}`, and EVERY CSV contact with a non-empty
`Lifecycle` cell fails the map lookup and falls through to
`contact.lifecycle_status_id = mapped or self.initial_lifecycle_status_id` - the INITIAL stage.
Separately, the phase-loop counter that WOULD have surfaced this as the existing
"N contact(s) have no lifecycle mapping and will land with no lifecycle stage" blocker
(`migration_service.py` around line 726, driven by a `lifecycle_unmapped` counter) is only
incremented in the API-mode phase loop (around line 2265: `if outcome.lifecycle_unmapped:
lifecycle_unmapped += 1`); the SEPARATE CSV-mode contacts loop (around line 555-625) never checks
`outcome.lifecycle_unmapped` at all, so the blocker never fires for CSV jobs either.

This contradicts two written contracts:
- The plan's own section 5.6 CSV column table: `"Lifecycle -> lifecycle -> resolver matches an
  existing stage by key or label"` - describing direct key/label resolution against the target
  workspace's OWN stages, which is simply not implemented for CSV mode.
- The runbook's own section 3 step 2: `"A lifecycle-mapping blocker (\"N contacts have no
  lifecycle mapping\") means those contacts land with no lifecycle stage - map the label or accept
  the gap."` - CSV-mode contacts do NOT land with "no lifecycle stage" (they land on the INITIAL
  stage), and the blocker never appears for CSV jobs regardless of how many contacts' labels fail
  to resolve.

**No existing AC explicitly names this exact scenario** (AC-MIG-06's "lands with no lifecycle,
reported as a blocker" language is scoped to the API-mode Lifecycle SearchSelect section; AC-MIG-
46/47/48 require CSV mode to hand off contacts to the writer with the same idempotency and to
state the media/identity/history blockers up front, which it does), so this is reported as an
independent finding rather than a hard FAIL against a specific numbered AC - but it is a genuine,
reproducible defect that will silently mis-stage every CSV-migrated contact whose source label
differs from the target's initial stage, with no operator-visible signal. **Recommended fix
options:** (a) give CSV mode a Lifecycle SearchSelect mapping section too (mirroring API mode,
built from the distinct `Lifecycle` values observed in the uploaded file - the same "observed
labels" pattern preflight already uses for API mode), or (b) implement the plan's own stated
"resolver matches an existing stage by key or label" direct match for CSV mode and wire the
existing `lifecycle_unmapped` counter into the CSV-mode contacts loop so an unresolvable label is
at minimum reported as a blocker even without an operator mapping step.

## Full-suite failure triage (backend)

The full run reported 11 failures, all outside `omnichannel_respondio_migration*`:
`test_omnichannel_media_backfill.py::test_media_sample_key_registered_and_drift_clean`,
`test_storage_migration.py` (8 tests), `test_storage_migration_registry.py::
test_no_unregistered_storage_key_columns`, `test_worker_module_boot.py::
test_boot_module_hooks_registers_module_workflow_nodes`.

**Classified as a pre-existing full-suite-order flake, not a plan-33 regression:**
- All 3 non-`test_storage_migration.py` failures pass cleanly in isolation
  (`pytest tests/test_storage_migration_registry.py::test_no_unregistered_storage_key_columns
  tests/test_omnichannel_media_backfill.py::test_media_sample_key_registered_and_drift_clean
  tests/test_worker_module_boot.py::test_boot_module_hooks_registers_module_workflow_nodes` ->
  3 passed).
- `test_storage_migration.py`'s full 25 tests pass cleanly in isolation (25 passed, 16.98s).
- Re-running the EXACT alphabetical neighborhood these files sit in during the full suite
  (`test_omnichannel_reports_builders.py` through `test_storage_migration_registry.py`, 28 files
  including all 5 `test_omnichannel_respondio_migration*.py` files) together in one pytest
  invocation reproduced **615 passed, 0 failed** - the failure does not reproduce even with the
  plan-33 files present, which rules out a plan-33-introduced pollution source specifically.
  The failure is therefore something upstream in the FULL 3700+-test run's execution order/shared
  state (a pre-existing class already tracked for a different pair of files as **BL-SS-126**,
  "Full-suite timer flakes... pass in isolation and fail 1-2 times per full vitest run under CPU
  load" - the backend analogue of the same phenomenon). No `test_omnichannel_respondio_migration*`
  test failed in the full run, in isolation, or in the 28-file reproduction.

## Per-AC results

### Slice S0 - Frontend on the mock service (re-spot-checked against the REAL backend, S6 wiring)

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-MIG-01 | [FE] | **PASS** | Menu entry present in all 3 arrays (`config/menu.config.tsx` greps at lines 383/551/715, tagged `module:'omnichannel'` + `permission:'omnichannel_migration.read'`). Live-confirmed: present for tenant A admin AND the read-only RBAC probe (`20-readonly-user-list-1280.png`); **absent entirely for tenant B before module install** (grepped the accessibility snapshot - zero hits for "Omnichannel"/"Migration"); present after install (`23-tenant-b-empty-list-1280.png`'s own sidebar). |
| AC-MIG-02 | [FE] | **PASS** | Resource shell clone of Users; exact column set Source/Target workspace/Mode/Status/Progress/Contacts/Messages/Failures/Started/Finished - `01-migration-list-empty-1280.png`, `13-migration-list-populated-1280.png` / `14-...-375.png` (non-clipped, columns scroll horizontally at 375px). |
| AC-MIG-03 | [FE] | **PASS** | `ResourceForm`, ordered Source/Target/(Channels/People/Lifecycle when API mode has data)/Scope/Review; shell Edit toggle + dirty-guard AlertDialog confirmed live (Cancel on a form with an uploaded file triggered "Discard changes?", not a bespoke confirm). `04-new-migration-form-1280.png` through `07`. |
| AC-MIG-04 | [FE] | **DEFERRED (stated)** | Live API-mode preflight against the (necessarily invalid, no real token available on this machine) connection resolved `apiAvailable:false` with ZERO source channels, so there was nothing to map live and the "forced Skip when no compatible target" rule could not be re-clicked. Covered by `services/respondio-migration-service.mock.test.ts` ("preflight() surfaces at least one source channel with no compatible target") and `channel-map-row.tsx`'s own options-list construction (reviewed: built only from compatible targets + an explicit Skip option, no free-text path exists). |
| AC-MIG-05 | [FE] | **DEFERRED (stated)**, same reason as AC-MIG-04 | `user-map-row.tsx` reviewed: options are `SearchSelect` over the tenant's real users only, prefilled by email match; no free-text id entry exists in the component. |
| AC-MIG-06 | [FE] | **PASS (component-level), FUNCTIONAL GAP found downstream - see Defect 2** | `lifecycle-map-row.tsx` reviewed: options built only from `preflight.targetStages`, no create affordance. The FRONTEND component itself satisfies the AC; the BACKEND's actual unmapped-label handling (in the CSV path specifically, which this AC does not directly govern) has the bug described in Defect 2. |
| AC-MIG-07 | [FE] | **PASS** | Live-verified repeatedly: `Start migration` stayed disabled through the API-mode blocked-preflight state (`05`), flipped disabled->enabled the instant a fresh CSV dry run settled `done` (`07`->`09`/`11`), and re-locked on a changed mapping (curl-verified: a `run` with an unmatched mapping hash -> `409 dry_run_required`). |
| AC-MIG-08 | [FE] | **PASS** | Progress bar + Details + Counts-report `DataGrid` + Failures `DataGrid` + Download CSV + Actions-menu-gated Abort, all live: `11`, `17`, `18`, `19`. Logs card present (`"No log entries yet."` shown on every job this run, since none produced a real milestone line under eager-mode single-page CSV runs - matches the coder's own documented gap of the same shape). |
| AC-MIG-09 | [FE] | **PASS (frontend fixture only, per AC-MIG-56)** | Mock survives only as `*.mock.test.ts` (vitest run confirms `respondio-migration-service.mock.test.ts` still passes, 13 tests); no page imports it (`grep -rn "S0 MOCK"` across `service_frontend/` returned nothing live-relevant). |
| AC-MIG-10 | [FE] | **PASS** | 375px non-clipped verified on every new/changed surface this run touched (`08`, `10` [mis-captured scroll position, see README], `12`, `14`, `22`, `24`); every dropdown is a `SearchSelect`/keyboard-typed combobox; no instructional copy observed; `document.body.innerText.includes('Foundryx')` checked manually on the setup form subtitle - reads "Map a respond.io space onto a workspace" (the coder's own white-label fix, confirmed still in place). |

### Slice S1 - Connection provider and preflight

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-MIG-11 | [BE] | **PASS** | `respond.io` provider present and selectable in the live Integrations "Connect integration" provider combobox (`02-integration-form-filled-1280.png`); fields `spaceLabel`/`timezone`/`requestsPerSecond` + secret `apiToken` rendered exactly as declared. |
| AC-MIG-12 | [BE] | **PASS (pytest, not independently re-derived this run)** | `apiToken` never echoed on any read (spot-checked: the connection detail page never rendered the token value after Create). Blank-keeps-value and partial-merge behavior taken on trust from `tests/test_omnichannel_respondio_migration.py`'s own coverage (unchanged this slice, full-suite green). |
| AC-MIG-13 | [BE] | **PASS** | Live `Test connection` against the REAL `https://api.respond.io/v2/space/channel` with a dummy token: genuine `401` mapped to "respond.io rejected this access token." - no vendor traceback/DSN/token fragment anywhere in the toast or (checked) the console - `03-integration-test-401-1280.png`. |
| AC-MIG-14 | [BE] | **PASS** | Preflight resolved `apiAvailable:false` + a `warnings` array surfaced inline on the setup form's Source card (S6's own fix, live-reconfirmed); zero writes (no contact/job/connection row appeared from the preflight call alone, confirmed via the job list staying empty before the first `New migration` submit). |
| AC-MIG-15 | [BE] | **PASS (pytest only)** | Not independently re-derivable live without a real respond.io token generating real rate-limit headers; taken on trust from the unchanged, full-suite-green `test_omnichannel_respondio_migration.py` throttle/backoff tests. |
| AC-MIG-16 | [BE] | **PASS** | The live 401 mapped to a clean job/connection-test failure, never an unhandled 500 (confirmed via `agent-browser errors` returning empty and the toast showing the mapped message, not a stack trace). |
| AC-MIG-17 | [T] | **PASS** | `test_omnichannel_respondio_migration.py`, unchanged, ran clean in the full suite this run. |

### Slice S2 - Migration job, contacts phase, dry run

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-MIG-18 | [BE] | **PASS** | `app_omnichannel.migration_refs` present and functioning (re-run correctly resolved `0 would create / 3 would update` via a ref hit, not a fresh phone/email match - confirmed by `contacts.migrated_from`/re-run idempotency both working). Alembic revision is currently `0016_omni_migration_refs` with a GAP at 0013-0015 (0012 exists, 0016 next) - **the plan's own "Merge-renumber rule" (section 3) explicitly reserves this renumbering for whoever merges to `main`; not a defect in this slice, but a flagged pre-merge TODO** confirmed still outstanding. |
| AC-MIG-19 | [BE] | **PASS** | Every job created this run went through `POST /omnichannel/migration/jobs` -> a real `background_jobs` row of type `omnichannel.respondio_migration` (confirmed via `psql`: 7 rows this run, all that type). |
| AC-MIG-20 | [BE] | **PASS** | curl-verified directly: a `run`-mode create against a mapping with no matching prior dry run -> `409 {"reason":"dry_run_required"}`. Frontend Start-disabled state matched exactly (never enabled until the SAME mapping's dry run settled `done`). |
| AC-MIG-21 | [BE] | **PASS** | curl-verified directly: flipped an existing job to `status=running` for the workspace, then a second `POST /jobs` -> `409 {"reason":"migration_in_progress"}`; reverted. |
| AC-MIG-22..26 | [BE] | **PASS (pytest for the API-mode-specific mechanics; live-reconfirmed for the CSV-mode contacts phase)** | Contact creation, phone/email match ladder, custom fields (N/A in CSV mode - not exercised), tags (N/A in CSV mode), assignee (N/A in CSV mode - no assignee column in this migration tool's CSV path) all exercised live via the 3-row and re-run CSV jobs; cursor-walk/crash-resume specifically is API-mode-only (`GET /contact/list` pagination) and not reachable without a real token - pytest-only, unchanged, full-suite green. |
| AC-MIG-27 | [BE] | **PASS (pytest, not independently re-derived)** | Dry-run write-absence taken on trust from the unchanged `test_omnichannel_respondio_migration_jobs.py` savepoint-fixture tests (full-suite green); indirectly corroborated live by the dry run NEVER changing the Contacts list count before Start was clicked. |
| AC-MIG-28 | [BE] | **PASS (live for the cancel-route + UI transition; cursor-resume-after-abort is pytest-only, eager-mode makes it unobservable live)** | Abort on the hand-inserted `running` probe left it `Aborted` with `40/100 processed` intact - `19-aborted-job-1280.png`. Genuine crash-mid-flight resume-from-cursor: `CELERY_TASK_ALWAYS_EAGER=true` runs a job's whole handler inline before the creating request returns, so there is no way to interrupt a REAL run mid-page from a browser click (same documented limitation as the coder's own S6 run) - covered by `test_cooperative_abort_stops_before_next_page_and_resume_continues` (unchanged, full-suite green). |
| AC-MIG-29 | [T] | **PASS** | `tests/test_omnichannel_respondio_migration_jobs.py`, ran clean in the full suite. |

### Slice S3 - Channel identities and message history (API mode only - not reachable live, no valid token)

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-MIG-30..37 | [BE] | **DEFERRED (stated) - pytest only** | This machine has no valid respond.io Developer API token, so no API-mode job ever reaches the identities/messages phases (CSV mode explicitly never touches this code path either, AC-MIG-48's own point). Covered by `tests/test_omnichannel_respondio_migration_s3.py` (17 tests, unchanged, ran clean in the full suite this run): `test_identity_deriver_whatsapp_prefers_meta_then_contact_phone_then_none`, `test_identity_written_for_mapped_whatsapp_channel`, `test_underivable_identity_never_fabricates_and_message_channel_less_report` (identity derivation + skip rule); `test_timestamp_explicit_branch_uses_min_of_status_timestamps`, `test_timestamp_interpolated_branch_between_bracketing_anchors`, `test_timestamp_fallback_branch_when_no_bracket_exists`, `test_timestamp_one_sided_anchor_is_not_a_bracket_falls_back` (timestamp inference); `test_sender_mapping_user_mapped_and_every_other_source_records_sender_source`, `test_sender_user_source_unmapped_user_id_records_sender_source_too` (sender mapping, all six `sender.source` values); `test_message_type_map_every_branch_and_unmapped` (every message-type branch); `test_delivery_status_map_last_element_and_no_status_is_null` (delivery status); `test_per_contact_recompute_after_message_phase` (the per-contact recompute maths); `test_no_realtime_publish_or_entity_event_during_identities_or_messages`, `test_message_never_writes_external_message_id_and_channel_less_when_unmapped` (the no-publish/no-event/no-webhook invariant). |
| AC-MIG-38 | [T] | **PASS** | Same file, ran clean in the full suite. |

### Slice S4 - Media, derived events, quick replies (API mode only - not reachable live)

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-MIG-39..44 | [BE] | **DEFERRED (stated) - pytest only**, same reason as S3 | `tests/test_omnichannel_respondio_migration_s4.py` (15 tests, unchanged, ran clean): `test_media_fetched_sniffed_capped_and_stored_media_key_convention`, `test_media_oversize_skip_and_report_message_kept`, `test_media_sniff_mismatch_rejected`, `test_media_404_skip_and_report_never_aborts_job` (media cap/sniff/skip-report); `test_events_derivation_matrix`, `test_events_no_fan_out_no_workflow_trigger`, `test_a9_report_service_reads_migrated_events_on_original_dates` (derived events, original-date reporting - AC-MIG-43); `test_quick_replies_created_from_csv_and_idempotent_rerun`, `test_quick_reply_matches_existing_live_row_case_insensitive_never_duplicates` (quick-reply de-dup); `test_messages_since_floor_skips_older_messages_and_counts_them` (`messagesSince` date floor). |
| AC-MIG-45 | [T] | **PASS** | Same file, ran clean in the full suite. |

### Slice S5 - CSV fallback + failure export

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-MIG-46 | [BE] | **PASS** | Live: CSV mode's Source card offers the two upload dropzones (Contacts CSV required, Quick replies CSV optional) - `06-csv-mode-1280.png`; the contacts CSV path is handled by this tool's own writer per D-A6-18, NOT re-implementing the contacts importer's parsing (confirmed by code review: `read_rows` + this module's own header-map/alias logic, not a call into `ImporterDef("omnichannel_contacts")`). |
| AC-MIG-47 | [BE] | **PASS for contacts-CSV mechanics (header map, sniffing, `migration_refs` idempotency); FUNCTIONAL GAP for the Lifecycle column specifically - Defect 2** | `read_rows`-backed upload (curl-verified 201 + row count + headers), operator header map honoured live (`07`), alias-fallback confirmed live on re-run (`15`), `migration_refs` idempotency confirmed live (0 creates on re-run, contact count stayed 3 via API). The Lifecycle column specifically does not resolve correctly - see Defect 2. |
| AC-MIG-48 | [BE] | **PASS** | All THREE CSV-mode blockers (no message history, no channel identities, no media) stated up front on EVERY CSV dry run and real run this created, confirmed via `document.body.innerText` on `09`(text)/`11`/`15`/`16` and the raw `result_json.report.blockers` via `psql`. |
| AC-MIG-49 | [T] | **PASS** | `tests/test_omnichannel_respondio_migration_s5.py` (19 tests, unchanged, ran clean in the full suite, including `test_failure_csv_round_trip_formula_guarded_and_empty_when_no_failures` - the exact `=SUM(...)` guard this run independently re-verified live via curl on a real download). |

### Cross-cutting - security, tenancy, permissions

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-MIG-50 | [BE] | **PASS** | `omnichannel_migration.read`/`.manage` CSV rows present (`modules/omnichannel/permissions/permissions.csv:28-29`); reads/.read, writes/.manage confirmed live via the RBAC probe: `GET /jobs` -> 200 as read-only, `POST /jobs` -> `403 {"detail":"Missing permission: omnichannel_migration.manage"}`. Manifest version genuinely bumped this slice (`0.6.0 -> 0.7.0`, confirmed via `git log -p` on `manifest.json`), delivering the grant sweep to already-provisioned tenants via `update_tenant` (taken on trust from the unchanged, full-suite-green module-install test suite - not independently re-derived by installing onto a PRE-EXISTING tenant with an older stamp, since both this run's tenants were provisioned fresh with the module already at 0.7.0). |
| AC-MIG-51 | [BE] | **PASS** | Every route this run exercised resolved tenant from the JWT; re-validated an unrelated tenant's connection id at USE time (`GET .../preflight?connectionId=<tenant-A's id>` from tenant B's own token -> `404 "Connection not found."`, WITH a valid `workspaceId` supplied so this genuinely reached the tenant-scope check rather than tripping the required-param validator first, which was this run's own first attempt and is documented as a correction in the E2E README). |
| AC-MIG-52 | [BE] | **PASS** | Tenant B: cannot read tenant A's connection (via preflight, 404), cannot reference it (never offered in tenant B's own connection picker, which is itself tenant-scoped by the existing Integrations list), cannot observe its existence (uniform 404 shape confirmed identical to a genuinely-missing id: `{"detail":"Connection not found."}` both times). |
| AC-MIG-53 | [BE] | **PASS** | curl-verified directly on the probe job's failures.csv: `200`, `content-disposition: attachment`, `cache-control: private, no-store`, `content-security-policy: default-src 'none'; sandbox`, `x-content-type-options: nosniff`; gated by `omnichannel_migration.read` (the RBAC read-only probe user's own session could reach the job detail page, confirming the SAME permission gate the route itself requires); never a bearer-less link (the Download CSV control is a `<button>` dispatching an authed `fetch`, confirmed via `eval`, not a bare `<a href>`). |
| AC-MIG-54 | [BE] | **PASS (pytest, not independently re-derived)** | Not exercised live this run (no module uninstall performed on either test tenant); taken on trust from the unchanged, full-suite-green module `uninstall_tenant` test suite. |
| AC-MIG-55 | [BE]/[T] | **PASS** | `git diff main...HEAD` for this branch (spot-checked via `git log --stat` across all 8 slice commits) touches neither `modules/omnichannel/routers/api_v1.py` nor any `Rio*` schema nor `documentation/omnichannel/consumer-integration-guide.md`; the coder's own guard test `test_gateway_contract_files_carry_no_migration_trace` ran clean in the full suite this run. |

### Slice S6 - Wire, evidence, runbook, report

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-MIG-56 | [FE] | **PASS** | Every surface this run touched rendered REAL data from the live backend (connections, jobs, contacts, RBAC state) - no mock-service artifact observed anywhere (no stubbed/static content, every count/status matched independently-queried API state). |
| AC-MIG-57 | [FE] | **PASS** | The Done job's detail page showed final state immediately (eager-mode jobs finish before the creating request returns, so "polling while in flight" itself is not independently observable live this run beyond the coder's own S6 polling-code review); Abort took effect within the same interaction (`18`->`19`, no intermediate poll needed since the cancel route is a synchronous commit). |
| AC-MIG-58 | [T] | **PASS** | Full `npm test` this run: 335 files / 2548 tests, all green, including every migration-specific file the coder's S6 report names (`migration-schema.test.ts`, `use-migration-form.test.tsx`, `migration-status.test.ts`, `migration-failures-table.test.tsx`, `use-migration-actions.test.tsx`, `respondio-migration-service.mock.test.ts`, `csv-upload-field.test.tsx`, `csv-header-map-section.test.tsx`, `respondio-migration-service.real.test.ts`, `migration-report-card.test.tsx`). |
| AC-MIG-59 | [E2E] | **PASS** - see the dedicated User Story table below | `33-evidence/E2E/01` through `19`, `25`; README with every setup call verbatim |
| AC-MIG-60 | [E2E] | **PASS** - see the dedicated User Story table below | Same evidence dir |
| AC-MIG-61 | [T] | **PASS** | This report (replacing the coder's own); `documentation/omnichannel/respondio-cutover-runbook.md` verified present and complete (prerequisites, WABA number move ceremony, dry-run-then-run procedure, CSV-mode limits, rollback notes, out-of-scope statement); this run's own new findings (Defect 1, Defect 2, the alembic renumber-gap flag) registered below rather than silently dropped. |

## `[E2E]` AC-MIG-59 / AC-MIG-60 - explicit User Story format

| User Story | Scenario | Precondition | Steps | Expected Result | Actual Result | Remarks |
|---|---|---|---|---|---|---|
| **AC-MIG-59** | Operator runs a first-time CSV-mode migration end to end | Fresh tenant `t33-mig-20260907t061224z`, Omnichannel installed via real clicks, a respond.io connection created with a dummy token | 1. Sidebar: Omnichannel > Settings > Migration<br>2. New migration<br>3. Pick connection, Test (real 401)<br>4. Switch Method to CSV export<br>5. Upload a timestamped 3-row CSV<br>6. Map "First name" explicitly, leave rest "Not mapped"<br>7. Run dry run<br>8. Start migration<br>9. Sidebar: Omnichannel > Contacts | Dry run reports `3 fetched / 3 would create`, 3 CSV blockers stated; Start enabled only after dry run; real run reaches Done `3/3`; Contacts list shows all 3 migrated rows | Exactly as expected for counts/blockers/gating/Done state and Contacts presence. **Deviation found:** all 3 contacts' Lifecycle stage is WRONG (all "New Lead" instead of their CSV-specified values) - Defect 2 | **PASS** on every literal AC-MIG-59 clause (the AC does not itself assert lifecycle correctness); Defect 2 filed separately since it is a real gap a customer migration would hit |
| **AC-MIG-60** | Re-run idempotency, abort, RBAC, tenant isolation all hold on the same migrated data | Same tenant, job from AC-MIG-59 already Done | 1. New migration > CSV mode > re-upload the SAME file, leave headers unmapped (alias fallback)<br>2. Dry run<br>3. Start<br>4. Confirm contact count via API<br>5. Open a hand-built `running` probe job, Actions > Abort<br>6. Log in as a `.read`-only user, attempt New migration + a raw POST<br>7. Provision tenant B, install Omnichannel, open Migration | Re-run reports `0 would create / 3 would update`; contact count stays 3; Abort leaves the job `Aborted` with partial counts intact; read-only user sees no Start control and the API 403s; tenant B sees zero of tenant A's jobs | Exactly as expected on every point; additionally curl-verified the two 409 guards (`dry_run_required`, `migration_in_progress`) and the uniform cross-tenant 404 shape (job id, connection id via preflight, failures.csv) | **PASS** |

## Setup calls outside the UI (verbatim, also in `33-evidence/E2E/README.md`)

See `documentation/plans/sprint-4/33-evidence/E2E/README.md` section "Setup calls outside the UI"
for the full verbatim list (tenant provisioning via the operator API, the RBAC probe role/user,
the two hand-inserted probe `background_jobs` rows and why eager-mode execution makes them
necessary, the 2500-row CSV cap file, the PNG-named-.csv file, and the three curl-only guard
checks). Not repeated here to avoid drift between the two documents; that file is the source of
truth for exact request bodies.

## What could not be verified (deferred, stated, not silently missing)

- **API-mode message-history migration into a live Inbox thread** (the identities/messages/media/
  events phases) - this machine holds no valid respond.io Developer API token, so no API-mode job
  can ever progress past the (correctly-blocked) preflight step. Covered entirely by
  `tests/test_omnichannel_respondio_migration_s3.py` / `_s4.py` (cited by test name above), which
  ran clean in the full suite this run.
- **Genuine crash-mid-flight cursor resume** - `CELERY_TASK_ALWAYS_EAGER=true` runs a job's whole
  handler inline before the creating request returns; there is no way to interrupt a REAL run
  mid-page from a browser click in this lane. Covered by
  `test_cooperative_abort_stops_before_next_page_and_resume_continues` (ran clean).
- **AC-MIG-04/05's live "forced Skip" / "email-prefill" re-click** - the (necessarily invalid)
  connection's preflight returns zero source channels/users, so there is nothing to click through
  live; covered by the mock test suite and direct component review.
- **AC-MIG-15's rate-limit header handling, AC-MIG-27's savepoint-rollback write-absence,
  AC-MIG-54's uninstall sweep** - taken on trust from the unchanged, full-suite-green pytest
  coverage rather than independently re-derived by this run (no real rate-limited API call, no
  module uninstall performed on either test tenant this run).
- **AC-MIG-50's manifest-version grant sweep for an ALREADY-provisioned tenant** - both this run's
  tenants were provisioned fresh with the module already at its current version; the "existing
  tenant silently gets the new permission via `update_tenant`" path itself was not independently
  re-derived (taken on trust from the unchanged module-install test suite).

## Independent findings beyond the AC checklist

1. **Defect 1** and **Defect 2** above (full root-cause + repro in their own sections).
2. **Alembic revision gap** (`0012` then `0016`, missing `0013`-`0015`) - explicitly a pre-merge
   TODO per the plan's own "Merge-renumber rule" (section 3), not a defect in this slice; flagged
   here so it is not lost before merge.
3. Screenshots `09`/`10` in the evidence dir were captured at the pre-scroll viewport position
   (identical to `07`/`08`) rather than the scrolled-down report section - the report CONTENT was
   independently confirmed correct via `document.body.innerText` at the time and is visually
   confirmed via `11` (the detail page's own Counts report card, same numbers) instead. Disclosed
   rather than silently re-labeled.

## Backlog registration

Both defects were new findings from this independent run, not previously registered. **Both are
now FIXED (Fix round 1, see the final section of this report) - no backlog registration needed;**
the paragraphs below are kept as a record of the ORIGINAL recommendation at the time this report
was first filed.

- **CSV-mode migration jobs silently ignore the CSV `Lifecycle` column** (Defect 2 above) - every
  CSV-migrated contact lands on the target workspace's INITIAL lifecycle stage regardless of its
  CSV value, with no blocker/report signal. Priority: **Medium-High** (silently wrong customer
  data on every CSV-mode migration that specifies a non-initial lifecycle stage). Source: this
  report. **FIXED, see "Fix round 1" below.**
- **`MigrationJobItem.connectionId` is typed non-Optional `str` while the read path's
  `payload.get("connectionId", "")` does not coerce a stored `None`** (Defect 1 above) - a latent
  500 landmine for any future write path that stores a literal JSON `null`. Priority: **Low**
  (not reachable via any current real write path). Source: this report. **FIXED, see "Fix round 1"
  below.**

## 9. Appendix - the coder's own S6 per-slice notes (kept for reference)

The coder's own `33-omnichannel-respondio-migration-test-report.md` (now replaced by this file)
recorded targeted-suite counts per slice (S1: 19, S2+S6: 25, S3: 17, S4: 15, S5: 19 - matching
this run's full-suite file-by-file breakdown exactly), the two gaps they found and fixed in S6
itself (the white-label subtitle leak, the missing milestone-log wiring), and the decisions taken
where the plan/UAC were silent (Abort as a plain immediate `run` rather than a `DeferredAction`,
in-Python list search/sort/filter rather than a SQL clause, CSV mode's alias-fallback convention).
None of that detail is repeated here; see the coder's original evidence at
`documentation/plans/sprint-4/33-evidence/S0/README.md` and `.../S6/README.md` for the narrative
of how each slice was built. This report's own defects (1 and 2) were not present in, or were
mis-characterized by, that original report - see the "Defects found" section above for exactly
how each diverges from what the coder's own document claimed.

## 10. Fix round 1 (review round 1 + this report's Defect 1/Defect 2)

**Commit under test:** `8b5c878e` (short form as of the last amend that touched this line) on
`sprint-4/33-respondio-migration`, on top of `ae609a47` (= `d550b6f3` + this report's own
evidence/report commit). Note the inherent self-reference: a commit cannot contain its own final
hash, so this value was captured one amend behind the commit it now lives in - cross-check `git
log -1 --format=%H` on this branch if precision matters more than the approximate pointer.

### What landed

**Review round 1 blockers/should-fixes (phase 1 + phase 2 coder):**
- **B1** - `migration_media.py` media-URL redirects: `follow_redirects=False` + a manual, guarded
  hop loop (`assert_deliverable` re-checked on every `Location`, `MAX_REDIRECT_HOPS` ceiling).
- **B2** - `contactsCsvKey`/`snippetsCsvKey` free-string fields RETIRED (`extra="forbid"`);
  replaced by opaque `contactsUploadId`/`snippetsUploadId` resolved tenant-scoped through a new
  `migration_uploads` table (migration `0017_omni_migration_uploads`) + a core `LocalDiskStorage`
  traversal guard on the READ path (`_safe_read_path`), belt-and-suspenders.
- **B3** - `respondio/client.py` pagination: same-cursor-twice guard, empty-page-with-cursor guard,
  `MAX_PAGES` ceiling.
- **S1** - a dry run writes zero storage blobs (`fileKey: None`, inline sample only).
- **S2** - `epoch_to_dt` clamps ms-magnitude/garbage/future/overflow values to `[2009, now+24h]`;
  `resolve_message_timestamps` wrapped in the per-contact failure handler.
- **S4** - `userMap`/`teamMap` tenant-scoped validation at create (422) + a reported blocker when a
  mapping drops at use time.
- **S5** - `teamMap` writes `Contact.assigned_team_id` from the contact's assignee's mapped team.
- **S6** - a running `progressTotal`, refined every checkpoint (not just at `finish_done`).
- **S9** - bare `truncate` replaced with `ClampedText` on every vendor-supplied string.
- **S10** - `_has_fresh_dry_run` pushes `finished_at`/`mode`/`workspace` into the SQL filter.
- **S12** - the failure-CSV/report reason string strips the vendor media URL's query string.
- **S13** - the 2499-vs-2500 CSV row-cap boundary test monkeypatches the cap instead of writing
  2500 real contacts twice.
- **S11 (this round)** - a new module constant `MAX_MESSAGES_PER_CONTACT = 20000`
  (`migration_service.py`). `_process_contact_messages` now checks the buffer size INSIDE the
  vendor page loop; once exceeded, paging for that contact stops immediately (no further network
  calls), the contact's whole message set is skipped (never partially written), a failure row is
  recorded, and the run-level `report.messagesSkippedOverCap` count + a blocker line surface it.
  The contact ROW itself still migrates - only its messages are skipped. Tested with the cap
  monkeypatched to 2 (`test_message_cap_skips_only_the_capped_contact_reports_blocker_never_aborts`,
  proving an UNRELATED contact's own messages are unaffected) and to 1 with a 2-page vendor
  response (`test_message_cap_stops_paging_immediately_never_fetches_further_pages`, proving the
  second page is never requested once the cap trips).

**This report's Defect 2 (CSV Lifecycle column silently ignored):** `MigrationWriter.write_contact`
(and `write_derived_events`, for the `lifecycle_changed` derived-event parity) now falls back to
`find_stage_by_key_or_label` (`lifecycle_service.py` - the SAME canonical resolver the gateway PATCH
route already uses for its own `lifecycle: <key or label>` field, not a parallel one) when
`self.lifecycle_map` has no explicit entry for the source label. This is the plan's own stated
contract (section 5.6: "Lifecycle -> lifecycle -> resolver matches an existing stage by key or
label") and is map-only - it never creates a stage. `_process_csv_contacts` now also tallies
`outcome.lifecycle_unmapped` per RAW CSV value into a new `csv_lifecycle_unmapped: Dict[str, int]`
(persisted through `checkpoint()` for crash-resume, exactly like `csv_blockers`), surfaced in the
report as `lifecycleUnmappedByValue` plus a blocker line per distinct unmapped value (`'N
contact(s) had a CSV Lifecycle value of "<value>" that does not match a mapped value or an
existing stage in this workspace - landed on the initial stage instead.'`). An unmapped value still
writes the contact on the initial stage (never blank, never silently dropped) - the fix is that
this is now REPORTED, not that the fallback stage changed.

**This report's Defect 1 (`connectionId` null 500):** `MigrationJobItem.connectionId` is now
`Optional[str] = None` (`schemas.py`), matching the request-side `MigrationJobCreate.connectionId`;
the FE `MigrationJob.connectionId` type is now `string | null` to match. No read-side default
change was needed (`payload.get("connectionId", "")` already tolerates a present-and-`None` value
once the schema itself accepts `None`).

### Migration transcript (lane DB `foundryx_service_s33`)

1. Before: `alembic_version_omnichannel = 0016_omni_migration_refs`; `migration_uploads` table
   absent.
2. `run_module_migrations(engine, "omnichannel")` -> `alembic_version_omnichannel =
   0017_omni_migration_uploads`; `migration_uploads` table present with the expected 9 columns
   (`id`, `tenant_id`, `workspace_id`, `kind`, `storage_key`, `row_count`, `headers_json`,
   `created_by`, `created_at`).
3. Down/up cycle via raw `alembic.command`: `downgrade("0016_omni_migration_refs")` (drops
   `migration_uploads` + its two indexes) -> `upgrade("head")` (recreates it) - both steps clean,
   final state confirmed at `0017_omni_migration_uploads` with `migration_uploads` present again.

### Live probes (curl against `:8012`, real Postgres, no mocks)

| Probe | Result |
|---|---|
| Upload a 3-row CSV with `Lifecycle` values (`hot_lead`, `customer`, `not-a-real-stage`) | `201 {id, rowCount: 3, headers: [...]}` - opaque receipt id, never a raw storage key |
| `POST .../jobs` with the RETIRED `contactsCsvKey` field | `422 {"detail":[{"type":"extra_forbidden","loc":["body","contactsCsvKey"],...}]}` |
| `POST .../jobs` with an unknown `contactsUploadId` | `404 {"detail":"Uploaded file not found."}` |
| `POST .../jobs` with tenant A's `contactsUploadId` from tenant B's own token | `404 {"detail":"Uploaded file not found."}` (uniform, same shape as unknown) |
| Dry run (`mode: dry_run`) on the 3-row CSV | `status: done`; `report.lifecycleUnmappedByValue: {"not-a-real-stage": 1}`; blocker line names the value; `failureCount: 0` (no blob written) |
| Real run (`mode: run`) on the SAME CSV | `status: done`; same `lifecycleUnmappedByValue` + blocker |
| `GET /omnichannel/contacts?search=<phone>` per migrated contact | Ada (`hot_lead` CSV value) -> `lifecycle.key: hot_lead`; Bob (`customer`) -> `lifecycle.key: customer`; Carl (`not-a-real-stage`, unmapped) -> `lifecycle.key: new_lead` (the workspace's own initial stage) |
| `GET /omnichannel/migration/jobs` and `GET .../jobs/{id}` against a hand-built row with `payload_json.connectionId = null` | Both `200`, `connectionId: null` in the response body - never a 500 |

A media URL redirecting to a private IP is covered by the pytest-only stub transport tests (B1) -
no live vendor call was made for this (no real respond.io token on this machine, unchanged from
the original test report's own limitation).

### Suite results (this fix round)

- Backend, targeted (`test_omnichannel_respondio_migration_review1.py` + the 5 adjacent migration
  suites + `test_storage_resolution.py`): **143 passed**, 0 failed.
- Backend, full suite (`python -m pytest -q`, ONE run, lane `foundryx_service_s33`): **3753
  passed, 1 skipped, 18 deselected** in 2353.46s (39m13s) - **zero failures.** The original
  report's 11 pre-existing full-suite-order flakes (already diagnosed there as unrelated to
  plan 33, reproducing in neither isolation nor a 28-file targeted run) did not reproduce at all
  in this run, consistent with that diagnosis (an intermittent, order/load-dependent flake class,
  tracked as `BL-SS-126`'s backend analogue - not a regression from this fix round).
- Frontend, full suite (`npx vitest run`, ONE run): **335 files, 2548 tests, all PASSED** (same 2
  pre-existing unrelated `Unhandled Rejection` warnings from AutoCount task-editor tests noted in
  the original report above - did not fail any test).
- `npx eslint` on every changed FE file: **0 errors**, 3 pre-existing a11y warnings on
  `csv-upload-field.tsx` (unchanged from the original report, same dropzone pattern).
- `npx tsc --noEmit`: no NEW errors from this fix round. The whole-repo run surfaces a large set of
  pre-existing errors in UNRELATED files (AutoCount/ideation/platform test files, none touching
  `migration`/`respondio`) - the only migration-adjacent hit is the SAME pre-existing
  `services/storage-migration-service.mock.test.ts` `Job.logs` error the original report already
  flagged as predating this branch.
- `rm -rf .next && npm run build`: clean, no errors. Frontend restarted via `npx next start -p
  3010` (cwd-verified before kill: `lsof -p $(lsof -ti :3010) | grep cwd`). Backend restarted via
  `uvicorn app.main:app --port 8012` with `CORS_ORIGINS`/`CORS_ORIGIN_REGEX` overrides for :3010 +
  its tenant-subdomain regex (cwd-verified before kill: `lsof -p $(lsof -ti :8012) | grep cwd`).

### Still open

- The alembic revision-id renumber (`0016`/`0017` collide with whatever `main` has moved to since)
  is unchanged from the original report's own flagged pre-merge TODO - still the merger's job per
  the plan's own "Merge-renumber rule", not addressed in this fix round.
- The manifest version bump (`0.7.0` -> the merge-time-correct next number) and the three
  version-pin test updates are likewise left for the merge checklist, unchanged from the original
  review.
- A live vendor-token B1 redirect-SSRF probe was not run (no real respond.io Developer API token
  on this machine) - covered by the pytest stub-transport tests only, same limitation as every
  other API-mode-only AC in the original test report.
