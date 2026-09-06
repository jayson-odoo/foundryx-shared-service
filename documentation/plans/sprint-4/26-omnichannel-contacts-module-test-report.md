# Sprint 4 · Plan 26 - Omnichannel Contacts module (list, segments, form, bulk, import/export) · Test Execution Report

**Branch:** `sprint-4/26-contacts-module` (worktree `.claude/worktrees/s26`, HEAD `1b2ae72`)
**Date:** 2026-09-05/06
**Environment:** backend `:8005` (DB `foundryx_service_s26`, Postgres, `ENVIRONMENT=development`,
`CELERY_TASK_ALWAYS_EAGER=true`), frontend `:3004` (prod build), Redis `:6379`.
**Tester:** automated E2E via `agent-browser` (sessions `s26`, `s26viewer`, `s26noomni`; real clicks;
Playwright is retired - no specs written or run) + `python -m pytest -q` + `npx vitest run`.

## Result summary

| Gate | Result |
|---|---|
| Backend suite (`pytest -q`, full repo) | **2926 passed, 1 skipped, 18 deselected** (1667s / ~28 min) |
| `tests/test_omnichannel_contacts_module.py` | 30 test functions, all passing (part of the 2926) |
| `tests/test_omnichannel_contacts_admin.py` | 25 test functions, all passing (part of the 2926) |
| `tests/test_omnichannel_contacts_import_export.py` | 26 test functions, all passing (part of the 2926) |
| `tests/test_omnichannel_api_gateway.py` | all passing, zero diff to `api_v1.py`/`Rio*` (AC-CTM-45) |
| Frontend suite (`vitest run`) | **264 test files, 2018 tests passed** |
| `[E2E]` AC-CTM-48/49 (scripted create/segment/bulk/import/export run) | **PASS** - dedicated tenant, evidence `26-evidence/E2E/01`-`26` + `README.md` |
| `[E2E]` AC-CTM-50 (permission gating + module-absence + isolation) | **PARTIAL - 2 defects found**, evidence `26-evidence/E2E/27`-`33` |
| Responsive 375px + 1280px | **PASS** - every new/changed surface checked both widths |

**Two defects found this run** (both detailed under "Defects found" below, both reproduced live and
via source-code confirmation, neither is a tester-setup mistake):

1. **AC-CTM-22 FAIL** - the single-contact detail route (`GET /omnichannel/contacts/{id}`, the A1
   route the Contacts module's detail page reuses per D-A2-2a) is gated by `conversations.read`, a
   DIFFERENT permission key than `contacts.read`. A role holding exactly `contacts.read` (the
   contract AC-CTM-13/22 both promise is sufficient for "list + detail reads") gets a misleading
   "Contact not found." on every contact it opens from its OWN list.
2. **Cosmetic/UX gap (not a numbered AC, logged as a candidate follow-up)** - the Contacts list page
   has no visible error state when its workspace-resolution call 403s (a `contacts.read`-only role
   with no `workspaces.read` sees a totally blank page below the breadcrumb, not even the toolbar) -
   see "Defects found" #2.

## Per-AC results (`26-omnichannel-contacts-module-acceptance-criteria.md`)

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-CTM-01 | [FE] | PASS | Menu tagged in all 3 arrays (`config/menu.config.tsx` lines 323-324, 458, 591 - `module:'omnichannel'`, `permission:'contacts.read'`); **E2E** live: tenant A sidebar shows Contacts directly after Inbox (`04-list-3-contacts-1280.png` sidebar), tenant A mega-menu shows it (`33-tenantA-megamenu-has-contacts-1280.png`), tenant B (`p26-noomni-...`, module inactive) shows it on NO surface - sidebar (`30`), mega menu (`31`), mobile mega menu (`32`) |
| AC-CTM-02 | [FE] | PASS | **E2E** `01-contacts-list-empty-1280.png`/`04-list-3-contacts-1280.png` - full-width Resource-shell list, columns Name/Phone/Email/Lifecycle/Tags(+Assignee/Channel/Last message/Created via Columns), leading select column, trailing row "..." menu; no hand-rolled markup (code: `app/(protected)/omnichannel/contacts/page.tsx` uses `<ResourceList config>`) |
| AC-CTM-03 | [FE] | PASS | **E2E**: search/sort/filter/segment/page each issue one server request (network log shows exactly one `GET .../contacts` per action throughout the run); Columns persisted (Email hidden step 8, still hidden after a hard reload - server `view_key=omnichannel.contacts.list` preference, confirmed in `README.md` step 17) |
| AC-CTM-04 | [FE] | PASS | **E2E** `07-filter-lifecycle-1280.png` field picker lists Name/Phone/Email/Language/Country/Priority/Assignee/Channel/Lifecycle/Tags/Last message/Created/**Lead Source** (the registered custom field) - matches the server whitelist exactly (`AC-CTM-16`'s column map) |
| AC-CTM-05 | [FE] | PASS | **E2E** `08-segment-switched-1280.png` - "All contacts" + "P26 New Leads ..." SearchSelect, switching re-queries to the segment's 3 rows; `use-contacts-list-config.test.tsx` |
| AC-CTM-06 | [FE] | PASS | **E2E** `09-segment-edit-filter-roundtrip-1280.png` - the stored filter round-trips into the SAME filter-builder shape (Lifecycle/is any of/New Lead); `manage-segments-dialog.test.tsx` |
| AC-CTM-07 | [FE] | PASS (list->detail navigation; Edit/Conversation tabs render) | **E2E** `02-contact1-created-1280.png` (Details tab, read + "Move to..." picker), `19-conversation-tab-1280.png`/`-375.png` (Conversation tab mounts `<ConversationDrawer>`); record-nav `‹ N / M ›` visible on the detail header (`debug-carys-detail.png` shows "3 / 3"); dirty-guard confirmed via the "Discard changes?" dialog on Cancel (create-form flow). **See AC-CTM-22 FAIL**: the detail page itself 403's for a `contacts.read`-only role because the underlying route needs `conversations.read` |
| AC-CTM-08 | [FE] | PASS | **E2E** `03-create-contact3-filled-1280.png`/`-375.png` - First/Last/Phone*(required)/Email/Language/Country/Lifecycle(defaulted "New Lead")/Tags/Lead Source all render typed; Phone read-only on an existing contact (`17-detail-edit-mode-1280.png`); `contact-schema.test.ts` |
| AC-CTM-09 | [FE] | PASS | **E2E** `11`-`16` (Assign/Add tags/Move lifecycle dialogs, all SearchSelect/MultiSelect pickers), `12-bulk-assign-result-1280.png` "2 contacts assigned.", `16-bulk-lifecycle-partial-failure-1280.png` "1 moved, 1 failed. `<id>`: No transition from..." (never a bare "something went wrong"); `use-contact-actions.test.tsx` ("gates every action on contacts.manage") |
| AC-CTM-10 | [FE] | PASS | **E2E** Import wizard (`20`-`24`) + Export dialog (`25-export-dialog-1280.png`) both present in the toolbar; export downloads a CSV directly when it finishes inside the wait window (`services/contact-service.real.test.ts` covers the "polls until done" AND "ExportPendingError - never a silent failure" + "raises the job error" paths not exercised live since Celery is eager locally) |
| AC-CTM-11 | [FE] | PASS | **E2E** every new surface checked at 375px AND 1280px: list (`01`), create form (`03`), bulk dialogs (`16-...-375.png`), import test results (`22-...-375.png`), conversation tab (`19-...-375.png`) - no horizontal scroll, no clipped controls, dialogs usable at both widths |
| AC-CTM-12 | [FE] | PASS | **E2E**: assignee picker offered only "Unassigned" until a real member was added, then only real members (`11-bulk-assign-dialog-1280.png`); tags picker offered only the workspace's own tag; lifecycle picker offered only the 4 real outgoing edges from New Lead; no instructional copy observed on any dialog/list/form in this run |
| AC-CTM-13 | [FE] | **PARTIAL - see Defects** | List gating PASS (`28-viewer-read-only-list-1280.png`: Add contact/Import/bulk "Actions"/"Save as segment"/"Manage segments" all absent for a `contacts.read`+`workspaces.read` role; "the list itself still reads with contacts.read" - **actually required `workspaces.read` too, see Defect #2**). Detail-form Edit-toggle absence **could not be verified** because the detail page never loads for this role at all (**Defect #1**, AC-CTM-22) |
| AC-CTM-14 | [BE] | PASS | `test_list_default_shape_and_sort`, `test_list_page_size_cap_422` |
| AC-CTM-15 | [BE] | PASS | `test_search_matches_name_phone_digits_email_never_message_body`; **E2E** `06-search-phone-digits-1280.png` (bare-digits phone search on a live contact) |
| AC-CTM-16 | [BE] | PASS | `test_filter_system_fields`, `test_filter_unknown_field_422`, `test_filter_depth_422` |
| AC-CTM-17 | [BE] | PASS | `test_filter_custom_field_registered_key`, `test_filter_custom_field_boolean_portable`, `test_filter_custom_field_unregistered_key_422`, `test_filter_custom_field_deleted_key_422` |
| AC-CTM-18 | [BE] | PASS | `test_sort_every_whitelisted_key_accepted[...]`, `test_sort_name_and_phone_order`, `test_sort_unknown_key_422`, `test_sort_dir_invalid_422` |
| AC-CTM-19 | [BE] | PASS | `test_channels_resolved_from_identities_never_fabricated` |
| AC-CTM-20 | [BE] | PASS | `test_segment_crud_and_uniqueness`, `test_segment_save_time_validation_rejects_unknown_field`, `test_segment_cap_100_per_workspace` |
| AC-CTM-21 | [BE] | PASS | `test_segment_apply_ands_with_ad_hoc_filter`, `test_segment_belonging_to_another_workspace_is_404` |
| AC-CTM-22 | [BE] | **PASS (round 1 fix)** | Originally **FAIL** (see "Defect 1" below, kept for history) - `GET /omnichannel/contacts/{id}` / `.../messages` required `conversations.read`, not `contacts.read`. Fixed via `ConversationPrincipal.require_read_or_contacts()` (`embed_auth.py`); new test `test_omnichannel_contacts_module.py::test_contact_detail_read_accepts_contacts_read_alone` (a `contacts.read`-only role gets 200 on detail+messages, 403 on the bare Inbox list). `test_permission_gates_403` / `test_tenant_isolation_uniform_404` still cover the list+segment routes. Tenant-isolation half of this AC (uniform 404 cross-tenant) confirmed PASS via the curl probes below |
| AC-CTM-23 | [BE] | PASS | `test_list_resolution_is_batched_not_per_row` |
| AC-CTM-24 | [BE] | PASS | `test_create_happy_path`, `test_create_sets_explicit_lifecycle_stage`; **E2E** `02`/`04` (3 real creates, initial stage + OPEN/MEDIUM implied by thread defaults) |
| AC-CTM-25 | [BE] | PASS | `test_create_phone_required_422`, `test_create_phone_no_digits_422`, `test_create_duplicate_phone_422_nothing_written`; **E2E** `05-duplicate-phone-422-1280.png` |
| AC-CTM-26 | [BE] | PASS | `test_create_then_inbound_stitches_onto_same_contact` |
| AC-CTM-27 | [BE] | PASS | `test_create_stamps_phone_digits`, `test_phone_digits_backfill_is_idempotent`, `test_find_by_phone_digits_matches_the_old_scan_including_empty_no_match` |
| AC-CTM-28 | [BE] | PASS | `test_patch_thread_phone_still_rejected`; **E2E** confirmed the Contacts UI never renders a phone input in Edit mode (`17-detail-edit-mode-1280.png` shows Phone as static text, not a textbox) |
| AC-CTM-29 | [BE] | PASS | `test_bulk_assign_unassign_with_null`, `test_bulk_assign_unknown_assignee_fails_every_id`, `test_bulk_assign_cross_tenant_and_cross_workspace_ids_are_not_found`; **E2E** `11`/`12` |
| AC-CTM-30 | [BE] | PASS | `test_bulk_tags_add_and_remove_math`, `test_bulk_tags_foreign_tag_id_422_writes_nothing`, `test_bulk_tags_partial_failure_isolated`; **E2E** `13`/`14` |
| AC-CTM-31 | [BE] | PASS | `test_bulk_lifecycle_move_and_no_edge_failure`, `test_bulk_lifecycle_unknown_target_stage_fails_every_record`; **E2E** `16-bulk-lifecycle-partial-failure-1280.png` (live "No transition from Customer to Cold Lead" on 1 of 2 selected) |
| AC-CTM-32 | [BE] | PASS | `test_bulk_ids_cap_422`, `test_bulk_assign_permission_403_and_tenant_404`, `test_bulk_lifecycle_permission_403_and_response_shape` |
| AC-CTM-33 | [BE] | PASS | `test_create_and_bulk_publish_contact_updated` |
| AC-CTM-34 | [BE] | PASS | `test_importer_registered_with_module_perm_context`, `test_importer_hidden_for_tenant_without_module` |
| AC-CTM-35 | [BE] | PASS | `test_import_columns_match_documented_set`, `test_dynamic_cf_columns_derive_type_from_the_field_registry`; **E2E** `20-import-map-columns-1280.png` (auto-mapped firstName/lastName/phone/email/lifecycle) |
| AC-CTM-36 | [BE] | PASS | `test_validate_missing_required_phone_on_create`, `test_validate_id_rules_per_mode`, `test_validate_duplicate_phone_in_file_and_table`, `test_validate_duplicate_phone_against_unstamped_legacy_row`, `test_validate_unknown_lifecycle_stage`, `test_validate_custom_field_type_error`; **E2E** `22-import-test-one-error-1280.png` (live "Unknown lifecycle stage for this workspace." on the one genuinely-bad row) |
| AC-CTM-37 | [BE] | PASS | `test_commit_creates_contacts_with_defaults_tags_and_custom_fields`, `test_commit_explicit_lifecycle_stage`, `test_commit_all_or_nothing_on_mid_file_failure`, `test_commit_update_id_match_never_touches_phone`, `test_trigger_automations_gate`; **E2E** `24-import-committed-list-1280.png` (3 rows land with their exact keyed lifecycle stage) |
| AC-CTM-38 | [BE][T] | PASS | `test_drift_guard_columns_subset_of_writable_plus_documented_exceptions` |
| AC-CTM-39 | [BE] | PASS | `test_export_creates_job_writes_csv_and_downloads`, `test_export_row_cap_422`; **E2E** `25-export-dialog-1280.png` + network trace (`POST .../export` 201 -> `GET .../file` 200) |
| AC-CTM-40 | [BE] | PASS | `test_export_cooperative_cancel_stops_before_file` |
| AC-CTM-41 | [BE] | PASS | `test_export_download_uniform_404_before_done_and_wrong_tenant`; **E2E** curl probe: tenant B token against tenant A's job id -> 404 (isolation section below) |
| AC-CTM-42 | [BE] | PASS | `test_export_honours_ids_selection_over_filter`, `test_export_sanitizes_formula_cells_and_round_trips_via_reimport`; **E2E** downloaded `contacts (2).csv` verified `ID` first, all 6 rows' data matching the live list exactly (dump below) |
| AC-CTM-43 | [BE] | PASS | manifest bumped to `0.3.0` and `update_tenant` wired (module CSV; `permissionCount`/`permissionKeys` API confirms `segments.manage`/`contacts.import`/`contacts.export` are real, distinct keys - verified live via `GET /roles/{id}` during the AC-CTM-50 role setup, no collision) |
| AC-CTM-44 | [FE] | PASS | `services/contact-service.real.ts` is the wired service (confirmed via the live network trace throughout this entire run - every list/create/bulk/export/segment call hit `localhost:8005`, never a mock); no `PHASE 1 MOCK` string reachable from the shipped route (S0's mock is a separate, superseded file per the plan's slice history) |
| AC-CTM-45 | [BE][T] | PASS | `git diff d302ea7..HEAD -- .../api_v1.py .../schemas.py` (recorded in `26-evidence/S4-smoke/README.md`, re-confirmed): `api_v1.py` zero diff, `schemas.py` additions are all NEW plan-26 classes, no `Rio*` touched; `tests/test_omnichannel_api_gateway.py` green (part of the 2926) |
| AC-CTM-46 | [T] | PASS | Full matrix present across `test_omnichannel_contacts_module.py` (30), `test_omnichannel_contacts_admin.py` (25), `test_omnichannel_contacts_import_export.py` (26) - list/search/sort/filter incl. 422s and depth, segment CRUD+apply+cross-tenant 404, batched-query count, create+phone+stitch+backfill, all 3 bulk routes incl. partial-failure/cap/uniform-not-found/403/isolation, importer Test/Import matrix+drift guard, export job incl. cancellation/tenant-scoped download/storage key, 403-per-new-permission |
| AC-CTM-47 | [T] | PASS | `use-contacts-list-config.test.tsx` (columns/viewKey/segments/importer/gating), `manage-segments-dialog.test.tsx`, `contact-schema.test.ts`, `use-contact-actions.test.tsx` (bulk gating/failure), `services/contact-service.real.test.ts` (export wait-then-Jobs-fallback: "throws ExportPendingError (never a silent failure) when the wait window elapses") |
| AC-CTM-48 | [E2E] | PASS | Full run `26-evidence/E2E/01`-`19`, `26` + `README.md` - sidebar Contacts -> list -> create (phone/name/email/custom field/tag/lifecycle) -> appears with correct badge+chip -> filter by tag/lifecycle -> save as segment -> switch to it -> bulk select 2 -> Move lifecycle -> rows update -> open contact -> Conversation tab shows thread -> Back to contacts keeps the segment |
| AC-CTM-49 | [E2E] | PASS | `26-evidence/E2E/20`-`25` + `README.md` - 3-row CSV import (one genuinely-bad row after correcting for the workspace's real label text) -> Test shows the one real error -> fixed CSV -> Test shows 0 errors -> Import commits -> rows appear in the list; Export the current query -> downloaded CSV verified `ID` first, all rows present |
| AC-CTM-50 | [E2E] | **PARTIAL - 1 defect (AC-CTM-22)** | Tenant isolation curl probes below: ALL uniform 404 as required (contacts/segments/export/export-file/bulk-not_found). Module-absence menu check: PASS on all 3 surfaces (`30`/`31`/`32` vs control `33`). `contacts.manage`-less user sees the list with no Add/bulk/Edit/Import controls: **PASS for the LIST** (`28`), **BLOCKED for the detail-form Edit-toggle check** by the AC-CTM-22 defect (the detail page 403's before any Edit-toggle-absence check is even possible) |

## AC-CTM-50 isolation probes (recorded curl commands, `[BE]`)

Tenant A = `p26-20260905222948` (workspace `bfffc460-851d-40f7-b2fa-1f2183784352`, contact
`49dcaa56-90e7-48d3-a2c3-2c2b252dfbe8`, export job `2ebcbe8e-f4fe-4409-ae1c-8abed6f710fd`).
Tenant B = `default` (`demo@example.com`, workspace `ade92e65-946c-42d3-8b33-c796eb750092`).

```
GET  /omnichannel/workspaces/{A-ws}/contacts                              (B token) -> 404
GET  /omnichannel/workspaces/{A-ws}/contact-segments                      (B token) -> 404
POST /omnichannel/workspaces/{A-ws}/contacts/export                       (B token) -> 404
GET  /omnichannel/workspaces/{A-ws}/contacts/export/{A-job}/file          (B token) -> 404
POST /omnichannel/workspaces/{B-ws}/contacts/bulk/assign {ids:[A-contact]} (B token)
     -> 200 {"ok":[],"failed":[{"id":"49dcaa56-...","error":"not_found"}]}
GET  /omnichannel/workspaces/{B-ws}/contacts                              (A token, control) -> 404
```

Every cross-tenant read/write is a uniform 404 (or a uniform `not_found` inside a 200 bulk-result
envelope, per the module's own contract) - never 403, never a data leak, never an existence oracle.

## Export CSV round-trip verification (AC-CTM-42, downloaded during the E2E run)

`~/Downloads/contacts (2).csv` (6 rows, `ID` first, exactly matching the live list at time of export):

```
ID,Name,Phone,Email,Lifecycle,Tags,Assignee,Channel,Last message,Created
331bd37e-...,ImportGood Three ...,+6011192229483,importgood3....@example.com,Cold Lead,,,,,2026-09-05T22:55:53Z
48b443c8-...,Beno Larsen ...,+601112229482,beno....@example.com,Cold Lead,P26 VIP,P26 Admin,,,2026-09-05T22:36:05Z
49dcaa56-...,Amara Okafor ...,+601112229481,amara....@example.com,New Lead,P26 VIP,P26 Admin,,,2026-09-05T22:35:29Z
7aec20c7-...,ImportGood One ...,+6011192229481,importgood1....@example.com,New Lead,,,,,2026-09-05T22:55:53Z
ab873812-...,ImportGood Two ...,+6011192229482,importgood2....@example.com,Hot Lead,,,,,2026-09-05T22:55:53Z
cc7dc1c9-...,Carys Mendes ...,+601112229483,carys....@example.com,Customer,P26 VIP,,,,2026-09-05T22:38:26Z
```

## Defects found

### Defect 1 - AC-CTM-22 FAIL: contact detail page requires `conversations.read`, not `contacts.read`

**Severity:** Medium (breaks a stated UAC contract; workable in practice because every seeded/real
role bundles both keys, but a role built literally to the AC's own wording - "list + detail reads
require `contacts.read`" - is broken).

**Repro:**
1. Create a role with ONLY `contacts.read` (+ `workspaces.read`, needed per Defect 2 below, just to
   reach the list at all).
2. Assign a user, log in, open the Contacts list (renders fine), click any contact row.
3. Frontend shows "Contact not found." Network trace: `GET /omnichannel/contacts/{id}` -> **403**
   `{"detail":"Missing permission: conversations.read"}`.

**Root cause** (`service_backend/modules/omnichannel/routers/conversations.py:105` +
`service_backend/modules/omnichannel/embed_auth.py:105 ConversationPrincipal.require_read`): the
single-contact detail route the Contacts module's detail page reuses (per plan decision D-A2-2a,
"the Conversation tab mounts the existing `<ConversationDrawer>`") is the pre-existing A1/Inbox
`conversations` router, gated by `conversations.read` - a permission resource never mentioned by
plan 26's own permission list (D-A2-7: "reuse `contacts.read`/`contacts.manage`; add
`segments.manage`, `contacts.import`, `contacts.export`"). No test in
`tests/test_omnichannel_contacts_module.py`/`test_omnichannel_contacts_admin.py` exercises "a
`contacts.read`-only caller opens a single contact" - `test_permission_gates_403` only covers the
NEW list/segment routes.

**Impact:** any tenant that provisions a role matching the literal, documented contract of
`contacts.read` (list+detail, no manage) gets a working list but a broken detail page, with a
misleading "not found" message instead of a permission error.

**Fix owner:** coder (not fixed by the tester per the house rule - reported here for the coder to
address, e.g. either (a) the detail route additionally accepts `contacts.read`, or (b) the module's
`contacts.read` grant is documented/enforced to imply `conversations.read` too, or (c) the frontend
surfaces a proper "You don't have permission" state instead of "Contact not found" on a 403).

**Evidence:** `26-evidence/E2E/29-viewer-detail-no-edit-1280.png`, network trace in `README.md`
step 22, source citations above.

### Defect 2 - UX gap (not a numbered AC, logged as a backlog candidate): blank Contacts list on a 403 from workspace resolution

**Severity:** Low/cosmetic, but directly caused the AC-CTM-13 verification to need an extra
permission grant this run.

**Repro:** a role holding `contacts.read` but NOT `workspaces.read` opens `/omnichannel/contacts` -
the page renders the breadcrumb/title only; the entire toolbar+table is missing, with no error
message, no toast, no retry affordance. Root cause: the page resolves the active workspace via
`GET /omnichannel/workspaces` (gated `workspaces.read`, per D-A2-10 "mirrors the Inbox" - this is
pre-existing A1 behaviour the Contacts page inherited, not new to this slice), and the frontend has
no fallback UI for that specific 403.

**Evidence:** `26-evidence/E2E/27-viewer-contacts-list-1280.png` (blank), network trace in
`README.md` step 19.

**Recommendation:** log as a backlog item (candidate: "Contacts/Inbox workspace-resolution 403 shows
a proper permission-denied state") rather than blocking this slice - the underlying `workspaces.read`
requirement is an A1/Inbox-wide decision (D-A2-10), not something plan 26 introduced, and once the
correct permission set is granted (which is what any real Admin-derived role will have) the list
works exactly as specified.

## Suite counts

- Backend: `python -m pytest -q` -> **2926 passed, 1 skipped, 18 deselected** in 1667.08s.
- Frontend: `npx vitest run` -> **264 test files, 2018 tests passed** in 60.01s.

## Tenants created (all timestamped, dedicated - see `26-evidence/E2E/README.md` for full detail)

- `p26-20260905222948` (Omnichannel installed, used for the full AC-CTM-48/49/50 script).
- `p26-noomni-20260905222948` (Omnichannel never installed, used for the module-absence menu check).

## Setup API calls (documented in `26-evidence/E2E/README.md`, not part of the scripted flows)

1. `POST /auth/set-password` with a token read from `invite_tokens` via `psql` - activated the
   "P26 Contacts Viewer" test user without needing the maildir smtpd rig for a permission probe.
2. `PATCH /roles/{roleId}` `{"permissionKeys":[...]}` - the in-app Roles permission picker (a cmdk
   `Command`-based `MultiSelect`, not the app's standard `SearchSelect`) could not be reliably driven
   by `agent-browser click` or a synthetic pointer-event sequence this session; this call has the
   identical effect a successful UI save would produce and was used only to unblock the AC-CTM-13/50
   permission-gating verification (see `README.md` "Harness gotchas").
3. Read-only `psql` queries against `invite_tokens` for (1).
4. `POST /auth/login` for the various tokens used in the isolation curl probes.

## Anything not independently verified

- **Manage segments -> Rename / Delete** were not exercised this run (only "Edit filter" was, to
  prove the `initialValue` round-trip); covered by `manage-segments-dialog.test.tsx` in the vitest
  suite.
- **Export wait-then-Jobs-fallback UI path** was not observed live (Celery is eager locally, so every
  export in this run finished before the first poll) - covered by
  `services/contact-service.real.test.ts` ("throws ExportPendingError ... when the wait window
  elapses").
- **`test_export_permission_gate_403` / `test_import_permission_gate_403`**: relied on for the
  `contacts.export`/`contacts.import` 403 cases rather than a live click-through (creating a THIRD
  bespoke role for each would have added little beyond what the two already-verified roles +
  passing backend tests demonstrate).

## Deferred items

None deferred outright - both findings above are reported as defects (one FAIL, one backlog
candidate) rather than skipped verifications.

## Round 1 fixes (review round 1, 2026-09-06)

Opus returned REQUEST CHANGES on `d302ea7..1b2ae72` (2 blockers, findings 4-14, 8 nits). All fixed
and re-verified in the same worktree/lane (`:8005`/`:3004`, DB `foundryx_service_s26`), plus two
additional items the tester's own AC-CTM-22/backlog findings above surfaced. Fixed in the commit
immediately following `3d4504a` (this evidence commit) on `sprint-4/26-contacts-module` - see
`git log` for the exact SHA (`fix(omnichannel): plan 26 review round 1 - ...`).

**AC-CTM-22 is now PASS.** `ConversationPrincipal.require_read_or_contacts()` (new,
`modules/omnichannel/embed_auth.py`) accepts `contacts.read` as an alternative to
`conversations.read` for the two per-record reads the Contacts detail page reuses -
`GET /omnichannel/contacts/{id}` (`get_thread`) and `GET /omnichannel/contacts/{id}/messages`
(`list_messages`), both in `modules/omnichannel/routers/conversations.py`. The shared Inbox LIST
(`GET /omnichannel/contacts` bare, `list_threads`) deliberately stays `conversations.read`-only -
`contacts.read` must not silently grant Inbox visibility. New test:
`tests/test_omnichannel_contacts_module.py::test_contact_detail_read_accepts_contacts_read_alone`
(a role holding ONLY `contacts.read` gets 200 on the detail + messages routes, 403 on the bare
Inbox list). Live-reprod fixed: `AC-CTM-13`'s detail-form Edit-toggle-absence check, previously
blocked by the AC-CTM-22 defect, is unblocked now too (not re-run live this round; covered by the
new unit test + the unchanged frontend permission gating already verified in the original run).

Backlog: **BL-SS-075** added for the tester's second finding ("Contacts list renders blank when
workspace resolution 403s for a role lacking `workspaces.read`", D-A2-10 inherited-from-A1 gap) -
not fixed this round, logged per the coordinator's instruction.

**Blockers fixed:**
- CSV formula-injection sanitize (`contact_export_service.py _csv_value` now calls the import
  engine's `sanitize_cell`, applied to every cell AND the header row; `phone`'s leading `+` is
  itself a guarded prefix, `_normalize_phone` strips it cleanly on re-import).
- Segment delete migrated to the deferred grace-window engine (`contact_segments.delete`,
  `deferred_actions.py`) - `manage-segments-dialog.tsx` rewritten to use
  `useDeferredAction`/`deferredToast` instead of a hand-rolled `AlertDialog`. AC-CTM-06 amended;
  new decisions D-A2-17/D-A2-18 in the plan file.
- Export download route rebuilt on the `documents.py`/`forms.py` `RedirectResponse`/`FileResponse`
  precedent (no more raw `urlopen`/whole-file `read()`).

**Findings 4-14 + tags delimiter + nits 15-22:** all addressed - scoped lifecycle-label lookups
(finding 4), tenant-scoped `workspaceId` validation in the importer (finding 5, live-reproduced
below), the legacy `phone_digits IS NULL` fallback mirrored in the importer's uniqueness check
(finding 6), stable `useContactActions` callbacks fixing an unbounded per-render list refetch
(finding 7), `ClampedText` in the segments dialog (finding 8), `ExportRowCapExceeded` translated in
the router instead of raised from the service (finding 9), bulk-failure reasons now name the
record (finding 10), `cf_*` import columns now derive `enum`/`boolean`/`decimal` types from the
field registry (finding 12), backlog row `BL-SS-074` (finding 13), `ContactExportRequest.columns`
capped + validated against a whitelist incl. registered `customFields.<key>` (finding 14), the
tags export/import delimiter aligned on `,` both sides. Nits: unresolved-update-row now logs a
warning (15), dead `except InvalidPatch` removed (16), the `0.3.0` docstring typo fixed (17), `neq`
now includes NULL rows (19), the export BOM uses `codecs.BOM_UTF8` (20), "View Jobs" navigates via
the Next router (21), a multi-batch bulk-failure test + a non-tautological drift-guard assertion
added (22). See the coder's Phase 1 report for the full per-finding FIXED/CHANGED-APPROACH list;
one item (a genuinely interleaved mid-run bulk-cancellation test) was not added - the export job's
own cooperative-cancel test already covers the pattern this engine uses.

**Live probes (this round, via `agent-browser` session `s26b` + direct API calls against the
rebuilt `:8005`/`:3004`):**
- Deferred segment delete: clicked Delete on a real segment - a "Deleting in 9s…Cancel" toast
  appeared immediately (no confirm dialog), the row dimmed/disabled, and it committed to
  "Segment deleted." with the row removed from the list. Checked at 1280px and 375px (both clean,
  no overflow).
- Export: created a contact with `firstName="=2+5(evil)"`, `lastName="+SUM(A1:A9)"`,
  `phone="+60 24-777 0099"`; exported `id,firstName,lastName,phone` - the downloaded CSV (200,
  `Content-Security-Policy: sandbox`, `nosniff`, `no-store`) shows every cell prefixed `'`
  (`'=2+5(evil)`, `'+SUM(A1:A9)`, `'+60 24-777 0099`).
- Tag round-trip: tagged the same contact with 2 tags, exported `id,firstName,tags` (cell =
  `"CleanProbeTag,Follow up"`, comma-delimited), removed both tags, re-imported the EXACT
  downloaded file (`update_only`, `id`-matched) - both tags restored exactly.
- Foreign `workspaceId` import context: uploaded a valid file with
  `context={"workspaceId":"not-a-real-workspace-id"}` - Test phase returned the aggregate
  `{"row": null, "column": "workspaceId", "message": "Workspace not found."}`, zero rows validated.
- UI export button click (Contacts list, real click) - job created, dialog closed cleanly, no
  console errors (backend contract already proven via the API probes above).

**Suite counts (this round):**
- Backend targeted (`test_omnichannel_contacts_module.py` + `_contacts_admin.py` +
  `_contacts_import_export.py` + `_import_engine.py` + `_api_gateway.py` + `_deferred_actions.py`):
  **191 passed**.
- Backend full (`pytest -q`, whole repo): **2936 passed, 1 skipped, 18 deselected** in 1576s
  (up from the original run's 2926 passed - the new/updated tests this round net +10).
- Frontend (`npx vitest run`): **266 test files, 2022 tests passed** (up from 264/2018).
- `npx eslint` on every touched file: 0 errors (6 pre-existing warnings, unrelated lines).

**Residue note:** the live-probe contact (`firstName="'=2+5(evil)"`, searchable by `evil`) could not
be cleaned up - the Contacts module ships no delete/merge/block action in this slice (D-A2-15), so
it remains in the shared `default` tenant like the tester's own `CleanProbe`/`S4Smoke*` residue rows
already did.
