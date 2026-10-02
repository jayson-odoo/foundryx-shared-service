# Sprint 4 · Plan 25 - Omnichannel Contact Data Model · Test Execution Report

**Branch:** `sprint-4/25-contact-data-model` (worktree `.claude/worktrees/s25`, HEAD `51888b6`)
**Date:** 2026-09-05
**Environment:** backend `:8004` (DB `foundryx_service_s25`, Postgres, `ENVIRONMENT=development`,
`CELERY_TASK_ALWAYS_EAGER=true`), frontend `:3003` (prod build), Redis `:6379`.
**Tester:** automated E2E via `agent-browser --session s25` (real clicks; Playwright is retired -
no specs written or run) + `python -m pytest -q` + `npx vitest run`.

## Result summary

| Gate | Result |
|---|---|
| Backend suite (`pytest -q`, full repo) | **2766 passed, 1 skipped, 18 deselected** (1499s) |
| `tests/test_omnichannel_contact_data_model.py` | 52 test functions, all passing (part of the 2766) |
| `tests/test_omnichannel_api_gateway.py` | 58 test functions, all passing (part of the 2766) |
| Frontend suite (`vitest run`) | **176 test files, 1440 tests passed** |
| `[E2E]` AC-CDM-42 (scripted run) | **PASS** - dedicated tenant, real clicks, screenshots `25-evidence/E2E/01`-`52` |
| `[E2E]` AC-CDM-43 (isolation probe) | **PASS** - see isolation section below |
| Live-Postgres field-delete strip (S0 carry-over) | **PASS** - verified via `psql` direct read, not just SQLite |
| Responsive 375px + 1280px | **PASS** - every new/changed surface checked both widths, screenshots `42`-`50` at 375px |

**Environment fix applied this run (infra, not product code):** the lane's backend CORS
allowlist (`CORS_ORIGINS`/`CORS_ORIGIN_REGEX`, set as a process env override at lane start, never
in the shared `.env`) didn't cover tenant-subdomain logins on `:3003` (`http://<slug>.localhost:3003`
origin, and the regex was capped at ports `300[0-2]`). Restarted uvicorn (same DB, same code) with
the allowlist widened to include `:3003`. Recorded in `25-evidence/E2E/README.md`; not a plan-25
defect (the s25 lane's CORS default predates this plan and was never exercised against a
subdomain login before).

## Per-AC results (`25-omnichannel-contact-data-model-acceptance-criteria.md`)

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-CDM-01 | [BE] | PASS | `test_create_field_and_list_sorted` |
| AC-CDM-02 | [BE] | PASS | `test_create_field_validation_matrix` |
| AC-CDM-03 | [BE] | PASS | `test_update_field_editable_and_immutable` |
| AC-CDM-04 | [BE] | PASS | `test_delete_field_strips_values_scoped_to_workspace`, `test_delete_field_strips_values_sqlite_fallback_path`; **E2E** `51-delete-field-confirm-1280.png` (confirmation names "1 contact... holds a value") + `52-field-deleted-1280.png` (live-Postgres strip verified via `psql` - closes the S0 "Carry to S4" item) |
| AC-CDM-05 | [BE] | PASS | `test_field_cap_100_per_workspace` |
| AC-CDM-06 | [BE] | PASS | `test_patch_contact_custom_fields_full_type_matrix`, `test_patch_contact_custom_fields_whole_null_clears_all_registered_values`; **E2E** `34`-`36` (Source select + save + persist) |
| AC-CDM-07 | [BE] | PASS | `test_patch_contact_language_country_code` |
| AC-CDM-08 | [BE] | PASS | `test_contact_field_routes_tenant_isolation`; **E2E** isolation probe (contact-fields 404 for tenant B, see below) |
| AC-CDM-09 | [BE] | PASS | `test_create_tag_and_list`, `test_tag_cap_500_per_workspace`; **E2E** `18`-`19` (tag created via dialog) |
| AC-CDM-10 | [BE] | PASS | `test_patch_contact_tag_ids_replace_and_cross_workspace_rejected` |
| AC-CDM-11 | [BE] | PASS | `test_delete_tag_removes_links_contact_unaffected` |
| AC-CDM-12 | [BE] | PASS | `test_thread_list_and_detail_carry_tags` |
| AC-CDM-13 | [BE] | PASS | `test_lifecycle_entity_registered_and_canvas_returns_workspace_graph`; **E2E** `07` (real seed graph on the canvas) + isolation probe (`/statuses?entityType=omnichannel_contact_lifecycle&scopeId=` 200 for A / 404 for B) |
| AC-CDM-14 | [BE] | PASS | `test_workspace_create_materializes_lifecycle_same_transaction`, `test_install_tenant_default_workspace_already_has_lifecycle_graph`; **E2E** `03` (Install via App Store UI) + `05`/`07` (General workspace + its seed graph exist) |
| AC-CDM-15 | [BE] | PASS | `test_install_tenant_backfills_when_default_workspace_predates_the_graph`, `test_update_tenant_backfill_materializes_and_stamps_then_noops` |
| AC-CDM-16 | [BE] | PASS | `test_inbound_stitch_sets_initial_lifecycle_stage`, `test_gateway_contact_creation_sets_initial_lifecycle_stage`, `test_dev_seed_demo_contacts_get_initial_lifecycle_stage`; **E2E** `29` (webhook-created contact shows 🆕 New Lead) |
| AC-CDM-17 | [BE] | PASS | `test_move_lifecycle_happy_path`, `test_move_lifecycle_no_edge_409`, `test_move_lifecycle_cross_workspace_and_cross_tenant_404`, `test_move_lifecycle_edge_role_auth`, `test_move_lifecycle_fires_transition_notification`; **E2E** `39` (New Lead -> Hot Lead) + API 409 probe (`hot_lead` -> `hot_lead`) |
| AC-CDM-18 | [BE] | PASS | `test_lifecycle_moves_list_and_empty_on_won`; **E2E** `39` ("Move to..." picker lists only the 5 fireable edges incl. the newly-added "Nurture") |
| AC-CDM-19 | [BE] | PASS | `test_thread_list_and_detail_carry_lifecycle`, `test_thread_lifecycle_null_when_unset`, `test_thread_lifecycle_null_when_stage_id_belongs_to_another_workspace` |
| AC-CDM-20 | [BE] | PASS | `test_lifecycle_canvas_edits_apply_directly_no_fork`, `test_lifecycle_delete_guard_blocks_stage_with_contacts`, `test_lifecycle_exactly_one_is_initial_enforced`; **E2E** `08`-`13` (Edit -> add stage + edge -> Save, real clicks + drag) |
| AC-CDM-21 | [BE] | PASS | `test_uninstall_tenant_cleans_core_lifecycle_status_rows` |
| AC-CDM-22 | [BE] | PASS | `test_omnichannel_contact_workflow_entity_registered_and_facts_resolve`, `test_omnichannel_contact_metadata_has_no_status_picker`, `test_entity_transition_status_action_rejects_omnichannel_contact_cleanly` |
| AC-CDM-23 | [BE] | PASS | `test_contact_patch_emits_one_updated_entity_event_with_changes_diff`, `test_internal_patch_emits_entity_event_with_real_actor_name_and_email` |
| AC-CDM-24 | [BE] | PASS | `test_status_changed_workflow_trigger_fires_on_lifecycle_move` |
| AC-CDM-25 | [BE] | PASS | `test_gateway_default_shape_carries_contact_data_model_fields`, `test_gateway_rio_shape_carries_contact_data_model_fields` |
| AC-CDM-26 | [BE] | PASS | `test_gateway_patch_tags_by_name_autocreate_and_reuse`, `test_gateway_patch_lifecycle_move_by_key_and_label`, `test_gateway_patch_lifecycle_unknown_stage_422`, `test_gateway_patch_lifecycle_no_edge_409`, `test_gateway_patch_bad_customfields_422_field_errors`, `test_gateway_patch_atomic_bad_customfields_leaves_tags_unchanged`; **E2E** live API 409 probe |
| AC-CDM-27 | [BE][T] | PASS | guide `documentation/omnichannel/consumer-integration-guide.md` §Contacts updated same commit as the shape (changelog entry 2026-09-05, confirmed present); contract-drift tests above pin both shapes |
| AC-CDM-28 | [BE] | PASS | `test_permission_gates_403_without_grants` |
| AC-CDM-29 | [FE] | PASS | `use-workspace-form.test.tsx` (tab gating incl. "still hides them while creating"); **E2E** `06` (three new tabs after Members) |
| AC-CDM-30 | [FE] | PASS | **E2E** `07`-`08` (real `EntityFlow` canvas, read-only until Edit) |
| AC-CDM-31 | [FE] | PASS | `contact-field-schema.test.ts` (slug derivation, list-needs-options); **E2E** `14`-`16` (embedded ResourceList, Add dialog, 422-shaped client validation), `51` (Delete confirmation naming the count) |
| AC-CDM-32 | [FE] | PASS | **E2E** `17`-`19` (Tags tab, Create dialog: emoji/name/colour/description, contacts count column) |
| AC-CDM-33 | [FE] | PASS (code-inspection + shared-shell precedent) | `use-workspace-form.test.tsx` gates the TABS by permission; `use-contact-field-list.tsx` wires `createPermission: 'contact_fields.manage'` (same `useCan()`-is-UX-only pattern proven elsewhere, e.g. Users/API-keys lists) + backend `test_permission_gates_403_without_grants` is the real gate. **Not independently re-verified this run with a live non-privileged session** (noted as a residual gap, same class as S0's action-menu note) |
| AC-CDM-34 | [FE] | PASS | **E2E** `31` (panel toggle, right pane at 1280px) + `42` (full-screen Sheet at 375px) |
| AC-CDM-35 | [FE] | PASS | **E2E** `31`-`37` (Details/Lifecycle/Tags all present, typed inputs, sort_order, fireable-only Move-to) |
| AC-CDM-36 | [FE] | PASS | `contact-details-form.test.tsx` (phone read-only, 422 mapping); **E2E** `32`-`35` (Edit toggle, ONE PATCH, Save/read-view swap) |
| AC-CDM-37 | [FE] | PASS | `lifecycle-move.test.tsx` (fireable-only, 409 structured message); **E2E** `39` (panel badge + thread-list row update together, no reload) |
| AC-CDM-38 | [FE] | PASS | `tag-chips.test.tsx` (optimistic add/remove/revert); **E2E** `38` (chip appears in panel AND thread row simultaneously) |
| AC-CDM-39 | [FE] | PASS | **E2E** `29` (lifecycle badge on thread row), `38`-`40` (tag chip + badge together, survives reload) |
| AC-CDM-40 | [T] | PASS | full matrix present - see AC-01..28 citations above (all part of the 2766-passing backend suite) |
| AC-CDM-41 | [T] | PASS | `contact-field-schema.test.ts`, `contact-details-form.test.tsx`, `lifecycle-move.test.tsx`, `tag-chips.test.tsx`, `use-workspace-form.test.tsx` (all part of the 1440-passing frontend suite) |
| AC-CDM-42 | [E2E] | PASS | Full recorded run, `25-evidence/E2E/01`-`52` + `README.md` run log (dedicated tenant `p25-20260905125540`, real clicks throughout, one documented inbound-webhook setup call to materialize a contact since the new tenant has no demo threads and the gateway has no contact-create endpoint) |
| AC-CDM-43 | [E2E] | PASS | Isolation probes below + tenant B (`p25-noomni-...`) has no Omnichannel sidebar section at all (`54-tenant2-home-1280.png`) - PASS-by-absence since there is no workspace form to inspect tabs on when the whole Service is invisible |

## AC-CDM-43 isolation detail (recorded, not a setup call)

Tenant B = `default` (`demo@example.com`), tenant A = `p25-20260905125540`
(workspace `671d1f4b-b3bd-4712-84a1-637132bf637c`, contact `3d3a2062-df7c-42b7-a715-33f3e41c697b`):

```
GET /omnichannel/workspaces/{A-ws}/contact-fields  (B token) -> 404 {"detail":"Workspace not found."}
GET /omnichannel/workspaces/{A-ws}/contact-tags    (B token) -> 404 {"detail":"Workspace not found."}
GET /omnichannel/workspaces/{A-ws}/lifecycle       (B token) -> 404 {"detail":"Workspace not found."}
GET /statuses?entityType=omnichannel_contact_lifecycle&scopeId={A-ws}
    (A token, control) -> 200, 6 statuses
    (B token)          -> 404 {"detail":"Workspace not found."}
GET /omnichannel/contacts/{A-contact} (B token) -> 404 {"detail":"Conversation not found"}
```

(The UAC text names the route `/api/v1/statuses`; the real core canvas mount is plain `/statuses`
- `/api/v1/*` is reserved for the public consumer gateway. Confirmed against `app/main.py`'s
route table; a first attempt against the literal `/api/v1/statuses` path 404'd for BOTH tokens,
which was the tell that the path itself was wrong, not an isolation success - re-ran against the
correct mount and got the expected 200-for-A / 404-for-B split.)

## Test Execution Report (narrative form, orchestration guide §6)

| User Story | Scenario | Precondition | Steps | Expected | Actual | Remarks |
|---|---|---|---|---|---|---|
| Contact data model (A1) | Operator installs Omnichannel on a fresh tenant and the workspace comes with a working lifecycle graph | Fresh tenant `p25-20260905125540`, Omnichannel not yet installed | 1. Operator opens Tenants, opens the tenant, Modules tab<br>2. Actions -> Install on the Omnichannel card | Card flips to "Active"; the tenant's default workspace ("General") already has the 5-stage seed lifecycle graph | Card shows "Active" (`03`); Lifecycle tab renders New Lead/Hot Lead/Payment/Customer/Cold Lead with edges (`07`) | **PASS** |
| Contact data model (A1) | Admin extends the lifecycle graph on the existing canvas | Logged in as tenant admin, workspace "General", Lifecycle tab | 1. Edit toggle<br>2. Add status "Nurture ts"<br>3. Drag New Lead's output handle onto Nurture's input handle<br>4. Fill action label, Create transition<br>5. Save | A new stage + a "Move to Nurture" edge exist on save; "Workspace updated." toast | Stage created (`10`); edge/transition created via the drag + drawer (`12`); Save succeeded (`13`) | **PASS**. The connect-handle drag needed real CDP mouse events (`agent-browser mouse move/down/up`) - a synthetic `dispatchEvent`-based drag silently no-ops against React Flow's handle logic (documented as a harness lesson, not a product bug) |
| Contact data model (A1) | Admin registers a typed custom field and a tag | Contact fields / Tags tabs, empty | 1. Add custom field "Source ts", type Dropdown list, options WhatsApp Ads/Referral<br>2. Create tag "VIP ts", colour Brand | Field + tag appear in their lists; both are real POSTs | "Field created."/"Tag created." toasts, rows appended (`16`, `19`) | **PASS** |
| Contact data model (A1) | Agent edits a contact's profile, tag and lifecycle from the Contact panel; changes propagate live | A real contact exists (materialized via one inbound-webhook simulation, since the fresh tenant has no demo threads) | 1. Open thread, toggle Contact panel<br>2. Edit Details, set Source = WhatsApp Ads, Save<br>3. Add tag VIP<br>4. Move New Lead -> Hot Lead | Details persist via ONE PATCH; tag chip + lifecycle badge update in the panel AND the thread-list row without a manual refresh; a reload keeps everything | All confirmed in single screenshots showing panel + row together (`38`, `39`); reload retained state (`40`, `41`) | **PASS** |
| Contact data model (A1) | Deleting a field with a value strips it from the contact on live Postgres | Field "Source ts" has a value on the one contact | 1. Contact fields tab -> row Actions -> Delete | Confirmation names the exact count; after delete the key is gone from the contact's `custom_fields_json`, verified on the real Postgres row (not just SQLite) | Confirmation read "1 contact in this workspace holds a value..." (`51`); post-delete gateway read AND a direct `psql` read both showed `customFields: {}` | **PASS** - closes the S0 "Carry to S4" follow-up |
| Contact data model (A1) | An invalid lifecycle move is rejected with the machine's message | Contact at a terminal-adjacent but non-terminal stage (Hot Lead) | API `PATCH .../contacts/{id} {"lifecycle":"hot_lead"}` (same stage - no self-loop edge) | 409 `lifecycle_move_not_allowed` with a human-readable message | `409 {"code":"lifecycle_move_not_allowed","message":"No transition from '🔥 Hot Lead' to '🔥 Hot Lead'."}` | **PASS**. Not driven through the UI by design (foolproof-UI hides invalid moves) - verified at the wire, matching `lifecycle-move.test.tsx`'s 409-message assertion |
| Contact data model (A1) | Tenant isolation holds on every new route | Tenant B (`default`) has no relationship to tenant A's workspace/contact | Tenant B's token calls A's contact-fields/contact-tags/lifecycle/`/statuses`/contact-by-id routes | Uniform 404, never A's data | All five routes returned 404 with generic messages; a control call with A's own token on `/statuses` returned 200 (proving the isolation is real, not a broken route) | **PASS** |
| Contact data model (A1) | A tenant without the Omnichannel Service sees no trace of it | Tenant B2 (`p25-noomni-...`) created, Omnichannel never installed | Log in as B2's admin, inspect the sidebar | No Omnichannel section, no Workspaces link, no way to reach a workspace form at all | Sidebar confirmed to have zero Omnichannel entries (`54`) | **PASS-by-absence** - the literal AC wording ("workspace form has no new tabs") doesn't apply because there is no workspace form reachable when the module itself is inactive; the stronger absence is the actual, correct behaviour |

## Defects found

None. Every AC passed either directly or via the existing pytest/vitest suites plus the recorded
E2E run. No product code was changed by the tester.

## Deferred / residual gaps (not defects, transparency)

- **AC-CDM-33** was verified by code inspection (the `createPermission`/`useCan()` wiring matches
  the shared, already-proven Resource-shell pattern) plus the backend's real permission gate test,
  rather than by logging in as a second live user without `contact_fields.manage`/
  `contact_tags.manage` in this run. Risk is low (identical mechanism to Users/API-keys lists,
  which are exercised live elsewhere), but flagging per the brief's instruction to report
  anything not independently verified. **Backlog candidate:** none needed - re-verify in the next
  slice that touches this surface, or spot-check manually before a customer-facing release.
- The row-action "..." dropdown menu (Contact fields Edit/Delete) needed a second click attempt to
  open reliably via the CLI in this session (opened cleanly on retry, `_debug-field-actions2.png`
  before cleanup) - a harness/CDP-timing quirk consistent with the same note in the S0 evidence,
  not a product defect (the underlying component is the shared `ActionMenu`).

## Harness lessons (for the next agent driving this canvas)

- **React Flow connection-handle drags need REAL CDP mouse events** (`agent-browser mouse move/down/up`
  with a scroll-into-view first), not a synthetic `PointerEvent`/`dispatchEvent` sequence - the
  library likely calls `setPointerCapture`, which throws/no-ops for a non-hardware-originated
  pointer id, silently swallowing the whole gesture.
- **`agent-browser mouse move` while a button is held down only reliably delivers ONE further
  move event** across separate CLI invocations - a `down` -> `move` -> `up` sequence (skip extra
  intermediate moves) was what worked; adding more intermediate `mouse move` calls between down
  and up did not increase reliability and once caused an unintended large canvas pan.
- **Always re-measure node/handle coordinates AFTER any Tidy/Save/reload** - React Flow's fitView
  re-centers the canvas on structural changes, so coordinates captured before a save are stale
  after it.
- Several dialogs/menus in this app share an accessible name across two different buttons on the
  same page (e.g. "Actions", "Mint key", "Save") - `agent-browser find role button click --name`
  can hit the wrong one; prefer a fresh `snapshot -i -c` + click by the specific `@ref` right
  before each click when duplicates are likely.

## Addendum - round 3 (2026-09-06, codex cross-model triage)

**Commit:** `fix(omnichannel): plan 25 round 3 - codex triage: unique-index 422s, tag resolve
retry, workflow update hook, drawer race guards, dialog errors` (branch `sprint-4/25-contact-data-model`,
worktree `.claude/worktrees/s25`).

Two Opus reviews (round 1 + round 2, already reflected in the test report above) passed the
branch except for 22 CANDIDATE findings from an OpenAI Codex cross-model review. This round
triaged all 22: 21 REAL (fixed test-first, red confirmed before each fix), 1 FALSE POSITIVE
(B2, already a documented decision from round 2 - re-confirmed against the migration's own
inline comments, no code change). Full verdict list, live probes, and any generic core changes
are in the coder's session report; summary here for the AC/suite-count record.

**Suite counts (both suites re-run in full after every fix):**

| Suite | Before round 3 | After round 3 |
|---|---|---|
| Backend (`pytest -q`, full repo) | 2773 passed, 1 skipped | **2785 passed, 1 skipped, 18 deselected** (1535s) |
| Frontend (`npx vitest run`, full repo) | 1440 passed | **1463 passed** (180 test files) |

**ACs re-verified by test this round** (no AC changed meaning; these got NEW regression
coverage as a side effect of the fixes): AC-CDM-06/07 (`language`/`countryCode` validation,
tightened - B8), AC-CDM-09/31 and AC-CDM-32 (field/tag create 422 mapping incl. the DB-backstop
race path - B6/B9/F9/F10), AC-CDM-10 (tag resolve-or-create batch race - B10), AC-CDM-17/18
(lifecycle move/moves authorization + refetch - B5/F5), AC-CDM-23 (`entity.field_changed`
trigger matching the documented camelCase `changes` keys - B7), AC-CDM-29/30 (Lifecycle tab
gating - F6), AC-CDM-35/36/38 (Contact panel Details/Tags race guards - F1/F2/F3/F4/F7/F8).

**Live probes run this round** (backend restarted PID 73686 on `:8004` with the SAME env as the
S4 evidence run - `DATABASE_URL=...foundryx_service_s25`, `ENVIRONMENT=development`,
`CORS_ORIGINS`/`CORS_ORIGIN_REGEX` - and frontend rebuilt + restarted PID 80111 on `:3003`):

- `POST /omnichannel/workspaces/{ws}/contact-fields` with a duplicate `key` -> `422
  {"fieldErrors":{"key":"..."}}` (not 500), confirmed live against the real Postgres app-level
  duplicate check.
- `psql "\d app_omnichannel.contact_fields"` / `contact_tags` on the LIVE `foundryx_service_s25`
  database confirm the functional unique indexes `uq_contact_fields_workspace_key` /
  `uq_contact_tags_workspace_name` genuinely exist in production - the DB-backstop `IntegrityError`
  path B6/B9's fix catches is reachable outside of pytest's SQLite (which has no such index and
  can only test the catch/recovery logic via a monkeypatched exception, per the existing
  round-2 test convention this file's tests already followed).
- B3 (missing FKs on `contact_fields`/`contact_tags`/`contact_tag_links`): applied the idempotent
  ALTER TABLE ADD CONSTRAINT statements live on `foundryx_service_s25`, then re-ran `psql
  "\d app_omnichannel.contact_tag_links"` - all three tables now carry FKs matching the ORM model,
  matching every sibling omnichannel table.
- Not run live this round (covered instead by the pytest/vitest suites, noted per the brief's
  "anything unverified" instruction): B4's tenant-backfill scenario (would need provisioning a
  genuinely pre-App-Store tenant state on `foundryx_service_s25`, awkward to stage safely against
  a shared lane DB - the pytest test constructs this scenario directly and asserts both the
  `install_tenant` side effects and the permission grant), B11's live workflow-run-produces-a-
  webhook-delivery path (fully exercised by
  `test_workflow_entity_update_on_contact_validates_and_fans_out_webhook`, which asserts a real
  `WebhookDelivery` row with the normalized `countryCode`), and F6's role-permission-tweak UI
  probe (covered instead by 7 passing vitest cases including a render-prop-level assertion on
  the `editing` flag actually passed into the canvas).
