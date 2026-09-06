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

---

## Round 2 fixes (review round 2 - coder response)

Commit: `fix(omnichannel): plan 26 review round 2 - clickable deferred toasts over
modals, per-row segment delete controller, selected-segment fallback, dialog-close
safety`. Lane: worktree `s26`, backend :8005 (`foundryx_service_s26`), frontend :3004.

### Per-finding disposition

- **Blocker 1 (countdown toast's Cancel unclickable over the open dialog) - FIXED,
  globally.** `components/ui/sonner.tsx`'s `toastOptions.classNames.toast` gained
  `pointer-events-auto` (a Radix `Dialog`'s dismissable layer sets
  `document.body.style.pointerEvents = "none"` while open; sonner's toast portal
  inherits that unless it opts back in). New test
  `components/ui/sonner.pointer-events.test.tsx` renders the REAL `<Toaster>` + real
  `sonner` `toast.custom` (allowlisted in `lib/toast.inventory.test.ts` +
  `eslint.config.mjs`'s sonner-restriction override, mirroring the existing
  `branding.test.tsx` precedent) and uses `@testing-library/user-event`'s built-in
  pointer-events enforcement to prove the click reaches the button; verified red
  (reverting the class) then green. `vitest.setup.ts` gained
  `setPointerCapture`/`releasePointerCapture` jsdom stubs (sonner's own swipe
  handler calls them; jsdom has neither) - a second small, generic, reusable fix.
  **Live-verify surfaced a SECOND, previously-unreachable bug the moment Cancel
  became clickable**: clicking it also closed the whole "Manage segments" dialog,
  because sonner's toaster portal (a `document.body` sibling of the Dialog's own
  portal) was outside `components/common/floatingAncestry.ts`'s shared
  `FLOATING_SURFACE_SELECTOR` allowlist, so Radix's dismissable-layer read the click
  as "outside" the dialog. Fixed in that ONE shared selector (added
  `[data-sonner-toaster]`/`[data-sonner-toast]`) - the same seam
  `dialog.tsx`/`alert-dialog.tsx`/`sheet.tsx` already share for popovers/menus
  opened from within a dialog, so this benefits every Dialog+toast combination in
  the app, not just Contacts. 2 new cases in `floatingAncestry.test.ts`.

- **Blocker 2 (one shared `useDeferredAction` for every segment row - deleting A
  then B while A counted down orphaned A) - FIXED, CHANGED-APPROACH.** The literal
  ask was "extract a row component owning its own `useDeferredAction` (mirrors
  `action-menu.tsx`)". Implemented instead: the delete controller (ONE
  `useDeferredAction` instance, "one countdown at a time") is lifted OUT of the
  dialog entirely into a new `use-segment-delete-controller.ts` hook, owned by
  `page.tsx` (see should-fix 4 below for why lifting was necessary regardless);
  `manage-segments-dialog.tsx` was still refactored into a `SegmentRow`
  sub-component per the ask, but it is presentational (props-driven), not an
  independent hook owner. Rationale documented in the controller file's header:
  (a) the product rule is explicitly "one delete at a time" (every row's Delete
  disables while `deletingId` names a different segment), so two concurrent parks
  under one hook can never happen by construction - the exact race blocker 2
  reports is structurally impossible; (b) embedding a REAL per-row hook inside the
  dialog's `<DialogBody>{segments.map(...)}</DialogBody>` would put it inside
  content Radix's `AnimatePresence` unmounts after the close animation, which
  would have REINTRODUCED should-fix 4's bug for exactly this refactor - lifting
  to the page (which never unmounts on dialog close) avoids that regression
  entirely. `use-segment-delete-controller.test.ts` (4 new tests): delete A then
  attempt B while A is pending is a no-op (only ONE `park` call, B never starts);
  A's Cancel cancels A only and settles `deletingId` back to null; after A
  commits, B can start its own countdown; a plain "starts and parks" case.
  `manage-segments-dialog.test.tsx` covers the DIALOG's own contract: `onDelete`
  fires with the clicked row, and every row's Delete button disables while
  `deletingId` names ANY segment (2 new tests, replacing the round-1 test that
  asserted the dialog calling `pendingActionsService.park` directly - it no longer
  does; the controller test above covers that instead).

- **Should-fix 3 (deleting the selected segment stranded the list) - FIXED,
  generic shell fix.** `components/platform/resource-list/resource-list.tsx`
  gained an effect: when `list.segment` no longer names one of
  `config.segments`, it resets to `config.segments[0].id` (+ clears row
  selection, matching the existing segment-switch convention) - additive to the
  shell, so ANY N-way-segmented list gets the fallback for free, not just
  Contacts. `segmentOptions()` already always prepends the `all` sentinel as
  index 0, so the fallback always lands on "All contacts". New test
  `resource-list.segment-fallback.test.tsx` (2 cases): falls back when the
  selected segment disappears from `config.segments`; is a no-op when the
  selection still exists.

- **Should-fix 4 (closing the dialog mid-countdown orphaned the toast, no
  refresh) - FIXED via the "lift the controller" option named in the brief.**
  `use-segment-delete-controller.ts` is owned by `page.tsx` (mounted
  unconditionally, independent of `manageSegmentsOpen`), so its
  `useDeferredAction` polling/toast/`onCommitted`->`refreshSegments()` all
  survive the dialog closing. Live-verified (see evidence run below): opened
  Manage segments, clicked Delete, immediately clicked the dialog's own Close
  (X) - the countdown toast stayed on screen with the dialog gone, and once the
  window lapsed the segment was deleted server-side AND the page's own "Manage
  segments" button disappeared (>0-segments gate), proving the refresh fired
  with the dialog unmounted the whole time.

- **Nit 5 (export-download docstring overclaimed "never a bearer-less signed
  URL") - FIXED.** `modules/omnichannel/routers/contacts.py`'s docstring and the
  plan's D-A2-6b row/§"Threats considered" bullet now say what is actually true:
  reaching the route always requires the bearer + `contacts.export`; for an
  S3/R2-backed storage connection the route may still 307-redirect to the
  storage layer's OWN time-limited presigned URL (Meta/AWS's capability link,
  not one we mint), matching the `documents.py` precedent - the D-A2-6b decision
  ("no OWN signed capability URL") still holds, the old wording just implied
  something stronger than the code does.

- **Nit 6 (import-time `assert` in `contact_export_service.py`) - FIXED.** Moved
  into `tests/test_omnichannel_contacts_import_export.py
  test_column_labels_cover_every_export_column_id` - a failure now reads as a
  named, re-runnable pytest failure instead of an opaque `ImportError` wherever
  the module happens to first get imported.

- **Nit 7 (`customFields.<key>` export header used the raw wire id) - FIXED.**
  New `_column_header()` in `contact_export_service.py` uses the registered
  field's LABEL (falls back to the raw id only if the field was since deleted).
  This ALSO closes the auto-map gap the finding named: `ImportService.preview`'s
  `by_norm` matches a file header against a column's LABEL or its `cf_<key>`
  key - never `customFields.<key>` - so the raw-id header could never auto-map on
  re-import; the label now does. New test
  `test_export_custom_field_header_uses_the_field_label`.

- **Nit 8 (`sanitize_cell`'s `'` guard broke on re-import for names/first tag) -
  FIXED, house-wide.** `app/import_engine/coerce.py coerce_string()` now strips
  exactly one leading `'` when the character right after it is one of
  `sanitize_cell`'s own guarded prefixes (`= + - @` / tab / CR) - reversing our
  OWN export convention symmetrically for EVERY text-typed import column (not a
  contacts-only patch), since a CSV genuinely stores that `'` as a literal
  character (unlike a native XLSX text-format flag). A value that happens to
  start with a real apostrophe (`'Ohana Co`) is untouched (the check requires
  the SECOND character to be a guarded prefix too). Because tag coercion runs
  before the comma-split, a joined cell like `+VIP,Ops` (which sanitize_cell
  guards to `'+VIP,Ops` since the cell's first char is `+`) round-trips
  correctly with a SINGLE strip, not per-tag. Extended
  `test_export_sanitizes_formula_cells_and_round_trips_via_reimport`: seeded tag
  `+VIP` (was `VIP`) and added post-reimport assertions for
  `first_name`/`last_name` exact round-trip (previously untested - only
  phone/tag-set were asserted).

- **Nit 9 (`hooks/use-contact-segments.ts` dead `remove`) - FIXED.** Removed the
  hook's `remove` wrapper + its `UseContactSegmentsResult.remove` field
  (deferred delete never called it); `contactSegmentService.remove` (the
  service method) is left in place per the brief. Updated the two test files
  that mocked `remove: vi.fn()` for this hook.

- **Nit 10 (3 new tsc errors) - FIXED**, all three:
  `manage-segments-dialog.test.tsx:39` (a `vi.fn(() => 'toast-id-1')`-typed
  `toastCustom` mock had a ZERO-arg inferred signature, so
  `toastCustom(...a)` with `a: unknown[]` failed `TS2556` - the actual
  offending line was the SONNER `custom` mock, not the `pending-actions-service`
  one the line-number initially looked like it pointed at; fixed by giving the
  implementation a variadic signature: `vi.fn((..._args: unknown[]) =>
  'toast-id-1')`); `page.fetch-stability.test.tsx:126` (`listMock` was typed
  zero-arg from its own `vi.fn(async () => ...)` implementation, then called
  with 2 args via a spread - fixed with an explicit `vi.fn<(workspaceId, query)
  => ...>()` generic); `use-contact-actions.test.tsx:93` (`ResourceAction.run`
  is optional in the discriminated-union type - `.find(...)!.run(...)` needed a
  second `!` on `.run` itself). Two INCIDENTAL new tsc errors introduced by this
  round's own new test files were also fixed rather than left for a future
  round: a `filter: null` fixture (`ContactSegment.filter` is non-nullable) in
  two new test files, and a `ListResult` missing its required `page` field in
  the new `resource-list.segment-fallback.test.tsx` fixtures.

- **Nit 11 (add a cancel-within-window backend test) - FIXED.**
  `tests/test_omnichannel_deferred_actions.py
  test_contact_segments_cancel_within_the_window_leaves_the_row_intact` - parks
  `contact_segments.delete`, cancels via `PendingActionService.cancel` while the
  window is open, asserts `status == "cancelled"` and the segment row still
  exists.

- **Nit 12 (migration `0010`'s `sa.DateTime(timezone=True)` vs `UTCDateTime`) -
  DEFERRED to the merge step, as anticipated by the brief.** Confirmed
  equivalent, not a bug: `UTCDateTime.impl = DateTime(timezone=True)`
  (`app/models/utc_datetime.py`) - the migration's raw DDL produces the
  identical Postgres column type (`timestamptz`) either way; the
  `import app.models.utc_datetime` convention only matters for Alembic
  autogenerate diffing, not for hand-written DDL. The file's own
  "NOTE for the merging agent" already documents that `down_revision` needs
  rebasing onto sibling lane A3's `0009` at merge time - left as-is.

### Live verification (agent-browser, session `s26c`, backend :8005 / frontend :3004)

Full run log: `documentation/plans/sprint-4/26-evidence/round2/README.md`.
Screenshots: `documentation/plans/sprint-4/26-evidence/round2/*.png`.

- **Lane setup note (environment, not a plan-26 code defect):** the default
  tenant's Admin role on `foundryx_service_s26` had never been granted this
  plan's `contacts.*`/`segments.*` permissions, and the shared
  `service_backend/.env`'s `CORS_ORIGINS` only listed `:3001,:3002` - both hid
  the Omnichannel menu entirely. Fixed for this lane's DB only (permission
  sync + `tenant_admin_grant` re-run) and this process only (`DATABASE_URL`/
  `CORS_ORIGINS` exported inline when starting uvicorn, no shared `.env` file
  touched).
- Real clicks from the sidebar (Omnichannel -> Contacts) at 1280px: opened
  "Manage segments", clicked Delete on a real segment - the countdown toast
  rendered over the still-open dialog with the row's controls disabled
  (Blocker 1's exact repro). Clicked Cancel on the toast: the segment stayed
  (confirmed via `GET .../contact-segments`) AND the dialog itself stayed open
  (the `floatingAncestry.ts` follow-up fix) - both AC-CTM-06/AC-CTM-13
  behaviours hold.
  - Repeated the countdown-visible + Delete-commits path at 375px.
- Created a second segment and made it the ACTIVE "View segment" selection,
  then deleted it and let the window lapse: the segment view fell back to
  "All contacts" with no error (should-fix 3, AC-CTM-06).
- Created a third segment, clicked Delete, then immediately closed the dialog
  via its own Close (X) while the countdown was live: the toast persisted on
  the page with the dialog gone, and once it lapsed the delete committed
  server-side AND the page's "Manage segments" button disappeared (proving
  `refreshSegments()` fired) - should-fix 4.
- Console check across the whole run: only the pre-existing "Missing
  Description for DialogContent" a11y warning (present on every Dialog in this
  codebase already, unrelated to plan 26) - no errors.

### Suite counts (this round)

- Backend targeted (`test_omnichannel_contacts_import_export.py` +
  `test_omnichannel_deferred_actions.py`): **46 passed** (30 + 16).
- Backend full (`pytest -q`, whole repo): **2940 passed, 1 skipped, 18
  deselected** in 1603s (up from round 1's 2936 - net +4 from this round's new
  tests).
- Frontend (`npx vitest run`): **269 test files, 2033 tests passed** (up from
  round 1's 266/2022 - net +11 new tests: 4 controller, 2 dialog replacing 1,
  2 segment-fallback, 1 sonner pointer-events, 2 floatingAncestry).
- `npx eslint .`: **0 errors** (214 pre-existing warnings, none on touched
  lines).
- `npx tsc --noEmit`: the three named pre-existing errors are gone; no new
  errors from any file touched or added this round.

### ACs re-touched this round

AC-CTM-06 (segment delete via the grace-window engine, no confirm dialog) -
still holds, now with a genuinely clickable Cancel and a dialog that survives
both Cancel and an early Close. AC-CTM-13 (Manage segments dialog contract) -
extended with the one-countdown-at-a-time disable rule. AC-CTM-42 (export/
import round-trip) - extended to cover a tag name and a contact name that
themselves trigger the formula-injection guard.
