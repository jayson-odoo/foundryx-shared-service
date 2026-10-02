# 07 - AutoCount SO `Ref` on the Sorento feed + "Re-push all" task action - Test Execution Report

Keyed to `07-autocount-so-ref-repush-acceptance-criteria.md` (AC-07-01..28, including the amended
AC-07-20/20b/22/23/24/25 - D8/D10 review-round changes: "Re-push all" is a server-parked
`DeferredActionButton`, not a typed-confirm dialog). Executed 2026-09-10 on branch
`sprint-5/07-autocount-so-ref-repush`, worktree `.claude/worktrees/s36`, against **HEAD
`bcbad58a`** (the fixed commit after review round 2). Lane DB `foundryx_service_s36`, backend
`:8006`, frontend `:3006`.

## Environment

- Backend: `.venv/bin/uvicorn app.main:app --port 8006` from `service_backend/`, native Postgres
  `foundryx_service_s36` (`DATABASE_URL` set in the worktree's own `.env`).
- Frontend: fresh prod build each time evidence was captured - `rm -rf .next && npm run build`
  then `npx next start -p 3006` (never `npm start`, which pins 3001).
- Browser verification: `agent-browser --session s36-tester`, headless, real sidebar clicks from
  `/`, screenshots at ~375px and ~1280px. No Playwright anywhere in this pass.
- Unit/integration: `.venv/bin/python -m pytest -q` (in-memory SQLite, `create_all`); `npx vitest
  run` (jsdom, `vitest.config.mts`).
- An earlier partial evidence pass against the pre-review commit `4c8dbb80` (typed-confirm
  `AlertDialog`) was fully superseded mid-task when review rounds D8/D10 replaced the dialog with
  the deferred-action model; that partial run's screenshots were deleted and the directory
  (`07-evidence/repush-tester/`) rewritten against `bcbad58a`. The pytest/vitest suite runs cited
  below are the FINAL runs, all at `bcbad58a`.

## Suite totals (final, at `bcbad58a`)

- Backend, full `-k autocount`: **1319 passed, 3263 deselected, 0 failed** (503.81s).
- Backend, the three files this slice's ACs live in:
  `tests/test_autocount_deferred_repush.py tests/test_autocount_etl_task_routes.py
  tests/test_autocount_so_ref.py` = **101 passed, 0 failed** (84.39s).
- Frontend, `npx eslint` on every file changed vs `origin/main`
  (`git diff --name-only origin/main...HEAD -- service_frontend`): **0 findings.**
- Frontend, `npx vitest run "app/(protected)/autocount"`: **220 passed (24 test files), 0
  failed.** Broader scope `"app/(protected)/autocount" services/autocount hooks
  lib/autocount-etl.test.ts`: **574 passed (67 test files), 0 failed.**
- Both vitest runs surfaced the SAME 2 pre-existing "Unhandled Rejection" console errors from
  `task-editor-view.save-sequencing.test.tsx` / `task-editor-view.locked-connection.test.tsx`
  (a `URLSearchParams`/undici body-type quirk in an unrelated mock). Neither file is in this
  slice's diff and all their own tests still pass - not a regression from this plan, not filed as
  a new defect.

## Results by AC id

| ID | Tag | Status | Evidence |
|----|-----|--------|----------|
| AC-07-01 | BE | PASS | `test_so_header_query_selects_ref_after_note`, `test_so_preset_header_carries_a_ref_field_not_required`, `test_list_mapping_presets_headerquery_carries_ref_for_sales_order`, `test_po_spo_and_so_line_fingerprint_queries_are_byte_unchanged` |
| AC-07-02 | BE | PASS | `test_canonical_sales_order_declares_ref_optional_str_max_255`, `test_ref_is_in_fallback_fields_and_omit_when_empty_fields`, `test_v1_payload_never_carries_ref`, `test_v2_payload_carries_ref_when_set`, `test_v2_payload_omits_ref_when_empty` |
| AC-07-03 | BE | PASS | `test_purchase_order_and_shipping_order_have_no_ref_field`, `test_purchase_order_payload_never_carries_ref`, `test_shipping_order_payload_never_carries_ref` |
| AC-07-04 | BE | PASS | `test_mapping_catalog_accepts_ref_for_sales_order_only`, `test_put_mapping_ref_succeeds_on_sales_order_and_422s_on_purchase_order` |
| AC-07-05 | BE | PASS | `test_map_document_end_to_end_strips_ref_and_sink_carries_it_verbatim` |
| AC-07-06 | T | PASS | Live doc check: `documentation/plans/sprint-4/22-autocount-db-etl-autocount-sql.md` line 52 (`h.Ref AS Ref` in §1's query), line 118 (`\| Ref \| ref \| string \|`), lines 250-254 (§3 PO: "Do not map `internal_note`... Do not map `ref` on PO either"). `documentation/plans/sprint-5/02-autocount-document-mapping-sorento-addendum.md` lines 437 and 450 - two dated 2026-09-10 change-log lines (`ref` / RTF ownership) |
| AC-07-07 | BE | PASS | `test_backfill_is_a_no_op_on_a_schema_that_predates_its_tables`, `test_manifest_version_is_bumped_past_0_8_0`, `test_revision_0019_chains_onto_0018_and_calls_the_helper`, `test_update_tenant_runs_the_sales_order_ref_backfill` |
| AC-07-08 | BE | PASS | `test_backfill_replaces_a_byte_identical_old_preset_query_with_new_text_and_seeds_row` |
| AC-07-09 | BE | PASS | `test_backfill_leaves_a_customised_query_alone_and_disables_the_ref_row_without_it`, `test_backfill_enables_the_ref_row_on_a_customised_query_that_already_selects_ref` |
| AC-07-10 | BE | PASS | `test_backfill_leaves_an_existing_ref_row_alone_in_any_state`, `test_backfill_does_not_repeat_a_warning_on_a_second_pass`, `test_backfill_ignores_a_query_that_matches_another_companys_database` |
| AC-07-11 | BE | PASS | `test_backfill_resolves_the_company_with_the_configs_own_tenant_id`, `test_backfill_skips_a_config_whose_company_id_belongs_to_another_tenant` |
| AC-07-12 | T | PASS (amended) | `documentation/plans/sprint-5/07-evidence/backfill-replay/README.md`, re-verified LIVE this pass against `foundryx_service_s36`: `Sorento` config `a538e0cb-...` query md5 `2605221ed510ccf8a3520dd58b068e63` unchanged, disabled `Ref->ref` row (`is_enabled=false`, `sort_order=10`) present; `ac_sim` config `f5875900-...` query md5 `68f2a801415373cce92bca298cfc1dad` unchanged, disabled row present (the documented AC-07-12 amendment: `ac_sim` is a hand-translated Postgres query, never byte-identical to the MSSQL preset, so it takes the customised branch too - BL-SS-196); PO/SPO 53/53 configs, 0 with a `ref` mapping row. Idempotency re-proven TWICE independently: `run_module_migrations(engine, "autocount")` again (no warnings) and a direct call to `backfill_sales_order_ref(conn, schema="app_autocount")` (`changed: 0`, no warnings) |
| AC-07-13 | BE | PASS | `test_repush_requires_manage_and_404s_cross_tenant_and_401_unauthenticated`; live: unauthenticated `POST /api/v1/pending-actions` (the D10 park route this action now goes through) -> `401` |
| AC-07-14 | BE | PASS | `test_repush_happy_path_clears_only_this_companys_entity_hashes` |
| AC-07-15 | BE | PASS | `test_repush_on_an_active_task_arms_the_next_reconcile_now`, `test_repush_on_a_paused_task_leaves_next_reconcile_at_none` |
| AC-07-16 | BE | PASS | `test_repush_is_refused_on_a_draft_task`, `test_repush_is_refused_when_source_impl_is_not_sql_db`, `test_repush_is_refused_while_a_run_is_in_flight`, `test_repush_in_flight_with_no_run_row_yet_still_409s_without_a_runningRunId` |
| AC-07-17 | BE | PASS (amended) | `test_repush_failure_at_commit_rolls_back_the_deletion`, `test_repush_control_the_same_fixture_sees_a_committed_delete`, `test_repush_a_run_enqueued_between_the_guard_and_the_commit_rolls_back` (the amended re-check-before-commit clause) |
| AC-07-18 | BE | PASS (amended) | `test_repush_success_writes_one_activity_row_naming_the_cleared_count`, `test_repush_409_writes_no_activity_row`, `test_repush_an_activity_write_failure_never_undoes_the_committed_wipe`; live: `integration_activity` row `operation='repush task'`, `response_summary_json.actorUserId` = the `demo@example.com` user id, confirmed after the commit (see AC-07-25 evidence) |
| AC-07-19 | BE | PASS | `test_clear_all_then_reconcile_stages_every_row_as_an_add_and_repopulates_hashes` |
| AC-07-20 | FE | PASS (amended) | `services/autocount-service.test.ts` / `.mock.test.ts` (the API-path trio, kept for direct callers); `activate-tab.test.tsx` "no dialog" cases confirm the tab parks the deferred action instead of calling the route; live: `agent-browser network requests` showed ZERO calls to `.../etl-task/repush` across the whole E2E session - every mutation went through `POST /api/v1/pending-actions` + `GET .../current` |
| AC-07-20b | BE | PASS | `test_repush_action_is_registered`, `test_park_via_the_pending_actions_api_as_a_manage_user_returns_202`, `test_commit_clears_hashes_arms_the_reconcile_and_records_the_actor`, `test_park_by_a_sync_run_only_user_is_403`, `test_park_on_another_tenants_config_id_is_404`, `test_commit_while_a_run_is_in_flight_fails_with_the_409_message_hashes_intact`, `test_cancel_before_commit_clears_nothing` (`tests/test_autocount_deferred_repush.py`, all in the 101-passed run above). Live: unauthenticated 401 reproduced by curl; the `sync.run`-only-403 and cross-tenant-404 cases were NOT re-exercised live (no such limited user / second tenant provisioned in this shared lane DB) - not filed as a gap, the pytest coverage above is green and specific |
| AC-07-21 | FE | PASS | `activate-tab.test.tsx` "renders for an active database task...", "renders for a paused database task...", "hides for a draft task...", "hides for an active task without autocount.companies.manage", "hides for an active task whose source is the AutoCount API..." (all 5 permission x status cases); live: draft `Sales order` task's Review & Activate tab shows only `Run preview` / disabled `Activate`, no "Re-push all" anywhere in the DOM (`05-draft-no-action-1280.png` / `-375.png`) |
| AC-07-22 | FE | PASS (amended) | `activate-tab.test.tsx` "clicking the trigger parks the deferred action with the right key/entity - no dialog", "renders the countdown from the parked state"; live: clicking "Re-push all" replaces the button in place with a `DeferredCountdown` ("Re-pushing all in Ns" + decaying bar + `Cancel`) - NO dialog, NO typed input anywhere (`02-countdown-with-cancel-1280.png` / `-375.png`, Cancel fully visible and not clipped at 375px) |
| AC-07-23 | FE | PASS | `activate-tab.test.tsx` "onCommitted toasts success (active variant)...", "a paused task's onCommitted toast says nothing moves until resumed...", "onFailed... toasts the error with a link to the Runs tab", "Cancel calls cancel() and never toasts..."; live: toast text captured exactly `"Change tracking cleared. The full re-push starts on the next scheduler tick."` (`03-toast-1280.png`), the "Next reconcile" badge advanced after the reload (`04-reloaded-badge-375.png`), zero direct calls to the repush route (see AC-07-20) |
| AC-07-24 | FE | PASS (amended) | `activate-tab.test.tsx` full deferred-action describe block (permission x status renders/hides, park-with-no-dialog, countdown-from-parked-state, Cancel-never-toasts, onCommitted x2, onFailed, busy-disables-trigger, cancel-loses-the-race, disables-while-committing) - 14 tests in that block alone, all in the 220-passed vitest run |
| AC-07-25 | E2E | PASS | `documentation/plans/sprint-5/07-evidence/repush-tester/README.md` + screenshots `01-tab-with-action-{1280,375}.png`, `02-countdown-with-cancel-{1280,375}.png`, `03-toast-1280.png`, `04-reloaded-badge-375.png`, `05-draft-no-action-{1280,375}.png`. DB proof after the window lapsed: `ac_row_hash` count 0, `next_reconcile_at <= now()`, `integration_activity` row `repush task` with the demo user's `actorUserId`. A cancel-within-window run left the (non-zero, seeded) hash count unchanged and no `pending` row behind. A draft-task run proved the action absent. The scheduler sweep was NOT running in this lane (no celery beat/worker process) - the DB row is the substitute proof the amended AC explicitly allows for that case |
| AC-07-26 | T | PASS | Plan `07-autocount-so-ref-repush.md` §2.6 states the deploy order (Sorento #809 + project-label merged AND deployed first, confirmed by the `autocount-crm` ping; only then `workflow_dispatch` the Foundryx deploy; merge != deploy) |
| AC-07-27 | T | PASS | Plan §2.4: the 3-step Sorento operator sequence (add `h.Ref AS Ref,` under `h.Note AS Note,` on the Query tab; Test; Save; then enable the `Ref -> ref` row on the Mapping tab), restated here for the report per the AC: this is the production operator's manual step for the customised `Sorento` task - the backfill deliberately never splices an operator-owned query (D4) |
| AC-07-28 | T | PASS | This report |

## Findings from this tester pass

1. **Entity-list row click is a dead end (not an AC-07-xx defect, noted for the record).**
   Clicking the `Customer`/`Sales order` row (or its cells) on the company's Entities list does
   nothing - no navigation, no `href`, and even a direct DOM `.click()` on the `<tr>` produced no
   effect. The only way into the task editor is the row's kebab `Actions` menu ->
   `Configure mapping` / `Configure database query`. Worth a foolproof-UI look outside this plan's
   scope (a whole clickable-looking row that does nothing is a discoverability trap), but it
   predates this slice and none of AC-07-01..28 describe the Entities list's own row behaviour.
2. **The Entities list table is wider than the 1280px viewport**, so the `Actions` column (the
   kebab menu) sits off-screen right at both viewports tested; `agent-browser scrollintoview` was
   needed before every kebab click. Also pre-existing, also outside this plan's surface
   (`activate-tab.tsx` and the deferred-action pieces are the only files this plan touches).
3. **A late Cancel loses to the commit, by design.** My first attempt at the Cancel proof (before
   re-seeding rows for a stronger 2-to-2 proof) took two viewport screenshots between the click
   and the Cancel click, long enough for the ~10s destructive window to lapse; the action
   committed instead of cancelling. This is the CORRECT engine behaviour (pinned by
   `PendingActionService.cancel`'s own "a cancel that arrives after the window closed must lose to
   the commit" rule, mirrored in `test_park_by_a_sync_run_only_user_is_403`'s sibling tests for
   other deferred actions) - recorded in the evidence README as a process note, not a defect.
4. **No Celery beat/worker was running in this lane**, so the "Runs tab shows the claimed
   reconcile once the sweep ticks" half of AC-07-25 could not be demonstrated; the amended AC's
   own fallback clause (show the DB row instead) was used, and is the correct outcome for a local
   dev lane with `CELERY_TASK_ALWAYS_EAGER=true` and no `beat` process.
5. **The frontend's own poll is what committed the action locally**, not a server-side sweep -
   confirmed by reading `app/deferred_actions/service.py`'s own docstring ("either the beat sweep
   (`commit_due`) or the frontend's lazy `GET current` poll") and by watching
   `GET /api/v1/pending-actions/current` fire repeatedly on the network log until the commit
   landed. This is expected, documented behaviour of the shared deferred-actions engine, not
   something specific to this plan.

## Responsive verification (375px / 1280px)

Every screenshot in `07-evidence/repush-tester/` was taken at both viewports except `03-toast-
1280.png` (toast copy/position is not viewport-sensitive and was already covered structurally by
the countdown/tab screenshots at both sizes) and `04-reloaded-badge-375.png` (badge-only follow-up
at 375px; its 1280px sibling is `01-tab-with-action-1280.png`'s same badge row, already shown).
No horizontal overflow observed on the Review & Activate tab at 375px in any of the five states
captured (base tab, countdown, draft-task tab).

## DoD gate (PRINCIPLES.md)

1. Mock swapped to real, live-verified with real data: **yes** - the deferred-action park/cancel/
   commit path was exercised against the real `foundryx_service_s36` data (real `ac_row_hash`
   rows, real `ac_entity_config`, real `integration_activity`), not a mock.
2. Backfill for existing rows/tenants: **yes** - `backfill_sales_order_ref` (AC-07-07..12),
   re-verified live and idempotent twice this pass.
3. No hardcoded editable key: **yes** - `entity_type`/`action_key` are the module's own registered
   constants, not a tenant-editable label.
4. Permission grant sweep: **not needed** - `autocount.companies.manage` is an EXISTING key
   (D6), no new permission introduced by this plan.
5. Verified from the user's perspective, real clicks, 375px AND 1280px, fresh build,
   correctly-owned ports: **yes** - see AC-07-25 evidence; ports 3006/8006 confirmed free before
   starting, both pids (backend, frontend) killed by this session at the end, no `pkill` by name,
   `agent-browser` session closed with plain `close` (never `--all`).

## Deferred / backlog items

| Item | Reason | Backlog id |
|---|---|---|
| `repush_requested_at` stamp + reconcile-owned `clear_all` (closes the narrow concurrent-run window structurally, also removes the "Added = N, Updated = 0" reporting artefact) | Structural fix out of scope for this slice (D9) | BL-SS-197 |
| `refetch_entity` (API entities' "Refetch history") has no in-flight guard, unlike the new repush route | Sibling gap, not introduced by this plan | BL-SS-198 |
| Runs tab cannot distinguish re-baselined adds from genuine adds after a re-push | UX polish, backlog per plan §5 | BL-SS-199 |
| `ac_sim`'s hand-translated Postgres query takes the "customised" backfill branch instead of the UAC's originally-assumed auto-swap | Live-data discovery during AC-07-12 replay, not a code defect (mechanism proven correct by unit test) | BL-SS-196 |

No new defects were found this pass; all four backlog items above were already registered
(BL-SS-196 by an earlier tester pass, BL-SS-197/198/199 by the plan/review round) and are present
in `documentation/backlogs/backlog.md` with source-plan links.

## Evidence paths

- `documentation/plans/sprint-5/07-evidence/repush-tester/README.md` + PNGs (this pass, AC-07-25,
  against `bcbad58a`).
- `documentation/plans/sprint-5/07-evidence/repush/README.md`,
  `documentation/plans/sprint-5/07-evidence/repush-mock/README.md` (coder's own earlier phase
  evidence for the superseded typed-confirm build, banner-marked, kept for the audit trail).
- `documentation/plans/sprint-5/07-evidence/backfill-replay/README.md` (AC-07-12, re-verified live
  this pass).
- `documentation/backlogs/backlog.md` (BL-SS-196, BL-SS-197, BL-SS-198, BL-SS-199).
