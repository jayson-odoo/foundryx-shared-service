# Sprint 4 · Plan 29 - Omnichannel Broadcasts v1 · Test Execution Report

**Branch:** `sprint-4/29-broadcasts` (worktree `.claude/worktrees/s29`)
**Commits under test:** round 1 = `ae59090`; **round 2 (final) = `c491d4a9`** (the review-round-1 fix commit)
**Date:** 2026-09-06 (round 1 08:48-09:31 UTC, round 2 14:00-14:25 UTC)
**Environment:** backend `:8008` (DB `foundryx_service_s29`, native Postgres,
`ENVIRONMENT=development`, `CELERY_TASK_ALWAYS_EAGER=true`, no beat process), frontend `:3007`
(prod build, `npx next start -p 3007`, pid 50418, cwd = this worktree).
**Tester:** automated E2E via `agent-browser --session s29t` (real clicks from `/`; Playwright is
retired - no spec written, run or referenced) + `python -m pytest -q` + `npx vitest run`.
**Contract:** `29-omnichannel-broadcasts-acceptance-criteria.md` (AC-BRD-01..55).
**Evidence:** `documentation/plans/sprint-4/29-evidence/E2E/` (round 1: 40 screenshots; round 2: 19
`r2-*` screenshots; one `README.md` run log covering both). Prior slice evidence: `29-evidence/S0/`, `29-evidence/merge-main/`,
`29-evidence/S4-smoke/`.

---

## Result summary

| Gate | Result |
|---|---|
| Backend suite (`pytest -q`, full repo) | **3144 passed, 1 skipped, 18 deselected** (2539.65s) |
| `tests/test_omnichannel_broadcasts.py` | 38 test functions, all passing (part of the 3144) |
| `tests/test_omnichannel_broadcasts_send.py` | 33 test functions, all passing (part of the 3144) |
| `tests/test_omnichannel_broadcasts_receipts.py` | 22 test functions, all passing (part of the 3144) |
| `tests/test_omnichannel_broadcasts_workflow_entity.py` | 5 test functions, all passing (part of the 3144) |
| `tests/test_omnichannel_api_gateway.py` | unchanged and green (part of the 3144) |
| Frontend suite (`npx vitest run`) | **290 test files, 2171 tests passed** (0 failed; the known `timezone-card.test.tsx` flake did not reproduce) |
| `app/(protected)/omnichannel/broadcasts/**` vitest | 7 files, **52 tests** passed |
| `[E2E]` AC-BRD-53 (send journey) | **PASS** |
| `[E2E]` AC-BRD-54 (cancel / isolation / RBAC) | **PASS** (round 2) - Cancel performed from the **list row action** on `c491d4a9`; isolation + no-send-permission clauses passed in round 1 |
| Responsive 375px + 1280px | **PASS** - list, builder, status page, recipients at both widths; `document.documentElement.scrollWidth === 375` throughout (re-checked in round 2 for the row-actions column + filter builder) |
| Round-2 targeted suites on `c491d4a9` | **138 passed** (5 broadcast pytest files) · **81 passed** (12 vitest files: broadcasts dir + the new hook/mock tests) |

**Per-AC tally (final, `c491d4a9`): 55 PASS · 0 FAIL · 0 DEFERRED.** Round 1 on `ae59090` scored
48 PASS / 7 FAIL (AC-BRD-05, 11, 18, 23, 51, 52, 54); every one of those seven was re-verified PASS in
round 2 - see "Round 2 verification" below. No AC is wholly deferred; two *sub-scope* items were
deferred by the plan itself (media-header templates, cross-broadcast rate capping) - see the DEFERRED
table.

---

## Round-1 caveat (RESOLVED in round 2) - the worktree changed under the first run

> **Resolved:** round 2 ran on `c491d4a9` with a clean tree at start and end, against servers the
> coordinator rebuilt on that exact commit (backend pid 29426, frontend pid 30927, both cwd = this
> worktree). Everything below in this section describes round 1 only and is kept for the record.

`git status` was **clean at `ae59090`** when this run started (08:48 UTC). By the time it
finished, 20 tracked files were modified and 5 added, mtimes spread across 07:58-09:31 UTC: a
concurrent agent was landing a review-fix round in the same worktree while these tests ran.
What that does and does not affect:

- **Backend suite** is collected in the first minute, so `3144 passed, 1 skipped` maps to `ae59090`.
- **Frontend suite** finished before any frontend file was touched, so `2171 passed` maps to `ae59090`.
- **The served frontend build** (started 08:48 UTC) predates every frontend edit, so every UI
  observation below is `ae59090` behaviour.
- **The backend was restarted at 09:12 UTC** (to add the missing `CORS_ORIGIN_REGEX`, see
  Environment note). That process imported `ae59090` **plus** the then-uncommitted `models.py`,
  `0011_omni_broadcasts.py`, `message_service.py`, `deferred_actions.py` and
  `broadcast_bindings.py`. Everything before the restart (the whole send journey, test send,
  schedule, due tick, cancel, receipts) ran on the original `ae59090` process; the API probes
  after it carry that caveat and are marked where it matters.
- Part of the in-flight work visibly closes gaps recorded here (e.g. a gateway no-diff guard
  test exists in the working tree but **not** at `ae59090`; `hooks/use-contact-filter-fields.ts`
  is being added, which looks aimed at defect D-3). **This report is keyed to `ae59090` as
  briefed. Re-run it once that round is committed.**

## Environment note (infra, not product code)

The lane backend (pid 4971) had been started **without** `CORS_ORIGIN_REGEX`, so every subdomain
host (`platform.localhost:3007`, `<tenant>.localhost:3007`) failed CORS preflight with `400` and
the operator console could not create a tenant. The same worktree's backend was restarted with
the lane env from the brief (`CORS_ORIGIN_REGEX='^http://[a-z0-9-]+\.localhost:3007$'`). No code,
migration or seed was touched.

## Tenants / identities created (all timestamped)

| Name | Slug / login | Purpose |
|---|---|---|
| P29 Isolation 20260906T085024Z | `p29-20260906t0850`, `p29admin@example.com` / `P29probe!2026` | AC-BRD-54 isolation tenant; omnichannel installed through the operator **Services** UI |
| P29 NoOmni 20260906T085024Z | `p29-noomni-20260906t0850`, `p29noomni@example.com` / `NoOmni!2026x` | AC-BRD-01 no-module tenant; nothing installed |
| E2E No-Send Agent 20260906T085024Z (role) + `e2e-nosend-20260906t0850@example.com` | default tenant | AC-BRD-12 / AC-BRD-25 RBAC probe: `broadcasts.read/manage` + `contacts/workspaces/channels/wa_templates.read`, **no** `broadcasts.send` |

## Setup calls made outside real clicks (recorded per the brief)

1. `UPDATE app_omnichannel.broadcasts SET scheduled_at = now() - interval '5 minutes' WHERE id = '1ef907af-…'` - to give the beat-tick body something due.
2. The `omnichannel.broadcasts_due` tick invoked inline (no beat process in this lane); the module boot hook must be called first or the job type is unregistered in a bare process. Exact command in `29-evidence/E2E/README.md`. Returned `{'started': 1, 'reconciled': 0, 'finalized': 0}`.
3. Two Meta-shaped status webhooks (`delivered`, then `read`, then a late `sent`) POSTed to `/omnichannel/webhooks/chn-demo` for `wamid.dev-ef7b629bfed5`. Payload in the evidence README.
4. The RBAC probe role and user created over the API; the user activated with a direct `UPDATE users SET password=<bcrypt>, status='ACTIVE'` (the API create lands `INVITED`).
5. The no-omnichannel tenant provisioned with `POST /platform/tenants` (operator API setup is permitted; the flows under test stayed real clicks).
6. `curl` isolation / permission / status-gate / filter-shape probes, all transcribed in the evidence README.

Everything else - segment creation, the whole broadcast builder, test send, send, duplicate,
schedule, cancel, the isolation tenant's creation and module install, the RBAC UI checks - was
real clicks from `/`.

## Harness notes (not product defects)

- Plan-23 motion-wrapped buttons below the fold no-op on a bare `agent-browser click @ref`; every
  such control needed `scrollintoview` first (Schedule-for radio, Schedule broadcast, Send now).
  Documented gotcha, worked every time once scrolled.
- `find role button click --name "Send test"` substring-matches the page's "Send test message"
  button and closed the dialog without firing the request. Using the dialog's own `@ref` worked.
  Tester error, not a product bug - but it cost one redo, so: prefer refs over `--name` when two
  buttons share a prefix.
- The native `<input type="datetime-local">` ignores `fill` and `keyboard type` in this harness;
  the React value-setter + `input`/`change` dispatch worked.
- `agent-browser console` carries one pre-existing Radix a11y warning
  (`Missing 'Description' or 'aria-describedby' for {DialogContent}`) from the test-send dialog.
  Same shell pattern already noted in the plan-27 report; not introduced here. `errors` was empty.

---

## Per-AC results

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-BRD-01 | [FE] | PASS | `config/menu.config.tsx` carries a Broadcasts entry in all three arrays (lines 331 / 472 / 611), each `permission: 'broadcasts.read'`, each inside a block tagged `module: 'omnichannel'` (lines 315 / 457 / 598). **E2E** `02-broadcasts-list-1280.png` (sidebar, after Contacts); `38-noomni-no-broadcasts-menu-1280.png` (tenant without the module: no Omnichannel section in the sidebar **and** none in the Apps mega menu) |
| AC-BRD-02 | [FE] | PASS | **E2E** `02-broadcasts-list-1280.png` - Resource shell with exactly the specified columns; server-side paging/sort/search through `useResourceList` (`GET .../broadcasts?page=0&pageSize=25&sortBy=createdAt&sortDir=desc`); per-user prefs confirmed by the live `GET /me/preferences/omnichannel.broadcasts.list` call |
| AC-BRD-03 | [FE] | PASS | **E2E** `03-status-segments-1280.png` - `SearchSelect` with All / Draft / Scheduled / Sending / Sent / Cancelled / Failed; `broadcast-status.test.tsx` "the list segments mirror the registry keys plus the 'all' sentinel". *Remark: clear-selection-on-segment-switch is the shell's own behaviour (pinned by the shell's tests); not separately re-clicked.* |
| AC-BRD-04 | [FE] | PASS | **E2E** `04`, `06`, `07`, `28-builder-375.png` - one Overview tab with Details / Audience / Channel / Message / Schedule / Review as ordered cards; Edit toggle + Cancel/Save on the detail; no instructional copy (only the identity subtitle "Configure a WhatsApp broadcast campaign") |
| AC-BRD-05 | [FE] | PASS (round 2) | **Round 2 on `c491d4a9`:** the Filter source now offers the contact filter columns (Name, Phone, Email, Language, Country, Priority, Assignee, Channel, Lifecycle, Tags, Last message, Created - `r2-03`), `Name contains a` > Apply resolved **6 recipient(s)** through a live `POST .../audience-preview 200` (`r2-04`); `hooks/use-contact-filter-fields.test.ts` (4) pins the field set. *Round-1 finding, kept for the record:* Segment and Selected-contacts branches PASS (`04-audience-segment-count3-1280.png` "3 recipient(s) resolved"; broadcast 3 used Selected contacts > Select all -> "5 recipient(s) resolved"; the count refreshes on every change). The **Filter** branch does not work: `40-audience-filter-branch-1280.png` - the builder's `AUDIENCE_FILTER_FIELDS` is a hardcoded stub (`status`, `priority`, `assignee`, `lastMessageAt`) that is not the contact filter map, so Apply returns `422 field not filterable: status` and the count never resolves. **Defect D-3** |
| AC-BRD-06 | [FE] | PASS | **E2E** `05-template-picker-approved-only-1280.png` - only the two APPROVED templates offered; the seeded `promo_blast` (PENDING) is absent. Only the one active channel is offered (`Demo WhatsApp (sandbox)`). Media-header exclusion is in the same filter (`broadcast-form-sections.tsx:193`) and pinned server-side by `test_create_media_header_template_rejected`. *Remark: "changing the channel clears the template" was not separately re-clicked; it is implemented in the same handler and has no dedicated test* |
| AC-BRD-07 | [FE] | PASS | **E2E** `06-bindings-preview-1280.png` - exactly the template's two body slots, per-slot source `SearchSelect`, contact-field row exposes a required Fallback, live `WaBubblePreview` renders "Hi Alex, there is an update on your booking: 6 Sept 3pm…". `binding-editor.test.tsx` (4), `broadcast-schema.test.ts` "rejects a contactField binding with an empty fallback" |
| AC-BRD-08 | [FE] | PASS | **E2E** `15-schedule-set-1280.png` - Send now / Schedule for; the field's caption reads `Timezone: Asia/Kuala_Lumpur` (`useDatetime()`), `06 Sept 2026, 17:03` local stored as `2026-09-06 09:03 UTC`. Past-instant rejection: `broadcast-schema.test.ts` "rejects a scheduledAt in the past" + server `test_create_scheduled_at_in_past_422` (live `POST .../send` with a past instant returns 422) |
| AC-BRD-09 | [FE] | PASS | **E2E** `07-review-section-1280.png` - read-only Audience / Channel / Template / Schedule summary + Test send + primary Send now; the primary stayed `[disabled]` until every piece was set (observed through the snapshot sequence 04 -> 06). Per-section error text is rendered via `ClampedText text-destructive` (`broadcast-form-sections.tsx`), no hint copy |
| AC-BRD-10 | [FE] | PASS | **E2E** `10-status-sent-counts-1280.png` (Overview + StatusSummary) and `11-recipients-sent-1280.png` (Recipients tab: embedded `ResourceList` with Contact / Phone / State / Error / Attempted at, `StatusBadge` per state, filterable). A Sent broadcast exposes no Edit toggle. Errors render through `ClampedText` (`use-recipients-list-config.tsx`) |
| AC-BRD-11 | [FE] | PASS (round 2) | **Round 2 on `c491d4a9`:** the list carries a trailing actions column with one `Actions` button per row (`r2-02`, 6 of 6 at 1280 and at 375 once the table scroller is moved - `r2-16b`); row menus render per status - Draft `Edit | Send now | Duplicate | Delete`, Sent `Duplicate`, Scheduled `Send now | Duplicate | Cancel` (`r2-13` + snapshot text); Duplicate, Cancel and Delete were each fired from the ROW; `use-broadcasts-list-config.test.tsx` (3) pins the column. *Round-1 finding, kept for the record:* The **form** surface works (`14-form-actions-duplicate-1280.png`, `19`, `20-scheduled-actions-cancel-1280.png`) and status gating is correct (Sent -> only Duplicate; Scheduled -> Send now / Duplicate / Cancel; Cancel has no confirm dialog, the documented S0 decision). But the **list has no actions column at all** - `13-list-no-row-actions-column-1280.png`, headers are `<select>, Name, Labels, Channel, Audience, Recipients, Status, Scheduled / Sent at, Sent / Delivered / Read / Failed, Created by, Created`. `useBroadcastActions` declares `surfaces: {row: true}` on all five, but `use-broadcasts-list-config.tsx` never adds the `id: 'actions'` column the Users reference uses. Row surface unreachable. **Defect D-1** |
| AC-BRD-12 | [FE] | PASS | **E2E** `35-nosend-actions-no-send-cancel-1280.png` (Scheduled broadcast, no-send user: Actions offers only Duplicate), `37-nosend-review-section-1280.png` (builder Review renders no Send test message and no primary Send/Schedule). `use-broadcast-actions.test.tsx` "Send/Cancel are gated broadcasts.send; Edit/Duplicate/Delete are gated broadcasts.manage". Backend is the real gate - live 403s under AC-BRD-25 |
| AC-BRD-13 | [FE] | PASS | Verified at S0 - `29-evidence/S0/README.md` walks loading / empty / Draft / Scheduled / Sending-with-advancing-counts / Sent-with-failures / Cancelled off `broadcast-service.mock.ts` with no backend. *Remark: since S4 bound `broadcastService` to the real implementation, `broadcast-service.mock.ts` is no longer imported anywhere (dead file). Cleanup candidate, not a functional gap* |
| AC-BRD-14 | [FE] | PASS | **E2E** `25-status-page-375.png`, `26-recipients-375.png`, `27-list-375.png`, `28-builder-375.png` + the 1280px set. `document.documentElement.scrollWidth === window.innerWidth === 375` on every 375px surface; sections stack, the counts grid reflows to 3 columns, every control reachable. `document.body.innerText` matched neither forbidden brand string; grep over the broadcasts source -> none |
| AC-BRD-15 | [BE] | PASS | Live Postgres: `app_omnichannel.broadcasts` + `broadcast_recipients` exist, `uq_broadcast_recipient UNIQUE (broadcast_id, contact_id)`, `ix_app_omnichannel_broadcast_recipients_message_id`, `channels.broadcast_rate_per_second integer`, every datetime column `timestamp with time zone`. Migration `0011_omni_broadcasts` (revision id 20 chars), inspector-guarded (`sa.inspect(bind)`, `get_table_names`, `get_columns`); `bootstrap.create_schema_and_tables` mirrors the channel column with `ADD COLUMN IF NOT EXISTS` (`bootstrap.py:419-427`). `test_migration_revision_sanity`. *Remark: shipped as `0011`, not the plan's `0012` - the real head was re-checked at branch time (plan F1)* |
| AC-BRD-16 | [BE] | PASS | `test_broadcast_status_scope_seeded_on_install`, `test_ensure_statuses_idempotent_rerun`, `test_grant_sweep_on_update`. **E2E** installing omnichannel on the brand-new `p29-20260906t0850` through the operator Services UI seeded exactly 6 `BROADCAST` statuses (`30-isolation-omnichannel-installed-1280.png` + `psql`) |
| AC-BRD-17 | [BE] | PASS | `test_create_happy_path_draft_zero_counts_no_recipients`; live create returned DRAFT with all six counts 0, `createdByName` = the acting admin |
| AC-BRD-18 | [BE] | PASS (round 2) | **Round 2 on `c491d4a9`:** an empty inline filter group is rejected at create with `422 {"fieldErrors":{"audience.filter":"Add at least one condition."}}`, an unknown rule key with Pydantic's `extra_forbidden` 422, and the valid control still creates `201` (curl transcript in the evidence README); `test_create_empty_filter_group_422_not_whole_workspace`, `test_create_nested_empty_filter_group_422`, `test_create_filter_unknown_key_422`, `test_create_valid_filter_still_creates`, plus the new S3 guard `test_create_empty_static_binding_rejected_422` (live: `422 {"fieldErrors":{"bindings.body.0.text":"Static text is required."}}`). *Round-1 finding, kept for the record:* Every enumerated branch is covered and green: `test_create_name_required_and_length`, `_channel_not_active_or_foreign`, `_audience_not_exactly_one_source`, `_segment_from_another_workspace_422`, `_invalid_filter_tree_422`, `_contact_id_not_in_workspace_422`, `_template_not_approved_422`, `_media_header_template_rejected`, `_binding_count_mismatch_422`, `_binding_unknown_field_and_missing_fallback_422`, `_binding_unregistered_custom_field_422_then_registered_ok`, `_static_binding_rejects_token_syntax_422`, `_scheduled_at_in_past_422`; live 422s carry the house `{fieldErrors:{path:message}}` shape. **But** an inline filter with an empty (or unrecognised-key) rule set is accepted `201` and stored as `{"kind":"group","combinator":"and","rules":[]}`, i.e. an audience of every contact in the workspace - the server has no mirror of the client rule "rejects a filter audience with zero conditions". **Defect D-4** |
| AC-BRD-19 | [BE] | PASS | `test_create_happy_path_draft_zero_counts_no_recipients`; live - after Save + a Test send the DRAFT still had **0** `broadcast_recipients` rows and 0 counts |
| AC-BRD-20 | [BE] | PASS | `test_list_search_and_filter_whitelist`, `test_list_status_segment`; live list is tenant+workspace scoped (isolation probes below), paginated, each row carries the denormalized counts (`3 / 0 / 0 / 0`) |
| AC-BRD-21 | [BE] | PASS | `test_update_draft_editable_non_draft_409`, `test_update_scheduled_at_allowed_while_scheduled`, `test_delete_draft_only`; live on a SENT broadcast: `PATCH -> 409 {"reason":"broadcast_not_editable"}`, `DELETE -> 409 {"reason":"broadcast_not_editable"}` |
| AC-BRD-22 | [BE] | PASS | `test_duplicate_creates_distinct_draft_with_no_recipients`; **E2E** `14-form-actions-duplicate-1280.png` -> new `DRAFT` "… (copy)", same audience/channel/template/bindings, counts 0, `scheduled_at NULL`, **0** recipients copied (`psql` verified) |
| AC-BRD-23 | [BE] | PASS (round 2) | **Round 2 on `c491d4a9`:** preview with an empty group -> `422 fieldErrors.audience.filter`; unknown key -> `422 extra_forbidden`; `firstName contains Sarah` -> `200 {"count":1}`; no shape resolves to the workspace any more. `test_audience_preview_empty_filter_group_422_not_whole_workspace`, `_nested_empty_group_422`, `_unknown_key_on_condition_422`, `_valid_filter_still_resolves_count`. *Round-1 finding, kept for the record:* Unknown segment -> `404 Segment not found.` (live + `test_audience_preview_unknown_segment_404_and_invalid_filter_422`); counts are SQL-computed by the A2 query builder and match the snapshot (`test_preview_count_matches_snapshot_total`); live segment preview returned 3 of 5. **But** an invalid / empty filter returns `200 {"count": 5}` (the whole workspace), not 404/422 - the exact "silent" outcome this AC forbids, and worse than the silent 0 it names. **Defect D-4.** *Two further remarks: the shipped route is `POST .../audience-preview` with a body, not the AC's `GET ...?segmentId=|filter=` (deviation already recorded in the S1 report); and a preview carrying another workspace's contact ids returns `{"count": 0}` rather than 404/422 - benign, create-time validation is the gate* |
| AC-BRD-24 | [BE] | PASS | `test_tenant_isolation_uniform_404`, `test_send_and_cancel_tenant_isolation_404`, `test_test_send_tenant_isolation_404`. **Live, both directions, 13 route/method combinations** (list, audience-preview, GET, PATCH, DELETE, duplicate, send, cancel, test-send, recipients) - every one `404`, never 403, never data. A foreign segment id inside the caller's own workspace -> `404 Segment not found.` Transcript in the evidence README |
| AC-BRD-25 | [BE] | PASS | `test_permission_gates_per_route`, `test_send_and_cancel_require_broadcasts_send_permission`, `test_test_send_requires_broadcasts_send_permission`. Live with the no-send role: `GET .../broadcasts 200`, `send 403`, `test-send 403`, `cancel 403`, each `Missing permission: broadcasts.send` |
| AC-BRD-26 | [BE] | PASS | `test_send_now_full_happy_path_sent_with_counts_and_message`, `test_send_with_future_scheduled_at_becomes_scheduled_no_job`, `test_send_already_sent_returns_409`, `test_send_race_second_atomic_claim_loses_no_second_job`, `test_send_past_scheduled_at_422`. **E2E** Send now -> SENDING -> SENT with one `background_jobs` row stamped on the broadcast (`10`, `39`); Schedule for -> SCHEDULED, instant stored in UTC, `job_id` still NULL (`16`, `psql`) |
| AC-BRD-27 | [BE] | PASS | `test_snapshot_queued_and_no_identity`, `test_snapshot_join_after_snapshot_not_sent_to`, `test_snapshot_counts_match_live_aggregate_invariant`; live - the segment resolved 3 at send time and `total_count` became 3 with exactly 3 recipient rows |
| AC-BRD-28 | [BE] | PASS | `test_snapshot_queued_and_no_identity`, `test_snapshot_idempotent_rerun_marks_duplicate_no_new_rows`, `test_send_no_identity_contact_skipped_others_sent`, `test_snapshot_channel_inactive_skips_everyone` |
| AC-BRD-29 | [BE] | PASS | `test_preflight_channel_inactive_fails_broadcast_zero_recipients`, `test_preflight_template_not_approved_fails_broadcast` |
| AC-BRD-30 | [BE] | PASS | `test_worker_broadcast_chunk_reschedules_then_finalizes`, `test_worker_broadcast_chunk_missing_broadcast_fails_job`, `test_run_one_chunk_called_twice_on_same_chunk_no_double_send`; the eager inline path is what the whole E2E exercised |
| AC-BRD-31 | [BE] | PASS | `test_claim_recipient_atomic_second_call_loses`, `test_job_retry_resumed_run_no_double_send`, `test_run_one_chunk_called_twice_on_same_chunk_no_double_send` (asserts exactly one `conversation_messages` row per recipient after a double chunk execution) |
| AC-BRD-32 | [BE] | PASS | `test_actor_resolution_deleted_user_resolves_to_none`; live - each recipient's message is `message_type = TEMPLATE` on `chn-demo` with the broadcast's channel override, `sent` state, real `message_id` |
| AC-BRD-33 | [BE] | PASS | `test_send_csw_exempt_expired_window_still_sends` |
| AC-BRD-34 | [BE] | PASS | `test_resolve_bindings_direct_skip_missing_variable`, `test_sanitize_param_strips_control_chars_and_long_runs`, `test_send_missing_variable_skip_others_sent`; live - the contactField binding resolved each contact's real first name ("Hi Sarah…", "Hi Marcus…", "Hi Priya…") and the static slot emitted verbatim |
| AC-BRD-35 | [BE] | PASS | `test_compute_chunk_pacing_pure_function` (measures the computed delay, does not sleep), `test_rate_for_channel_prefers_channel_override` |
| AC-BRD-36 | [BE] | PASS | `test_broadcast_recipient_permanent_send_failure_marks_failed`, `test_broadcast_recipient_transient_send_failure_stays_queued_not_failed` |
| AC-BRD-37 | [BE] | PASS | `test_send_runner_sent_stamps_recipient_sent_and_message_id`, `test_inbound_delivered_then_read_advance_recipient_and_counts`, `test_inbound_failed_after_sent_marks_recipient_failed_with_error`, `test_receipt_hook_raising_never_breaks_the_send`, `test_receipt_hook_raising_never_breaks_inbound_webhook`. **E2E** `22`/`23` - a `delivered` then a `read` webhook advanced the row and the counts live; a late `sent` posted afterwards left it at `read` (forward-only) |
| AC-BRD-38 | [BE] | PASS | `test_reconcile_adopts_matching_outbound_message`, `test_reconcile_no_matching_message_marks_send_result_unknown`, `test_reconcile_idempotent_second_call_no_op`, `test_finalize_broadcast_calls_reconcile_before_terminal` |
| AC-BRD-39 | [BE] | PASS | `test_snapshot_counts_match_live_aggregate_invariant`, `test_finalize_broadcast_calls_reconcile_before_terminal`; live - `SENT` with `finished_at` stamped, job `done` with `result {"total":3,"sent":3,"failed":0,"skipped":0,"cancelled":false}`, and after the receipts the counts (Sent 2 / Read 1 / Total 3) still equal a live aggregate over `broadcast_recipients` |
| AC-BRD-40 | [BE] | PASS | `test_cancel_scheduled_zero_sends`, `test_cancel_terminal_states_409`, `test_cancel_mid_sending_remaining_skipped_already_sent_keeps_state`. **E2E** `20`/`21` - Cancel on a SCHEDULED broadcast -> `CANCELLED`, `finished_at` stamped, 0 recipients, 0 sends; live `POST .../cancel` on a SENT one -> `409 {"reason":"broadcast_not_cancellable"}` |
| AC-BRD-41 | [BE] | PASS | `test_test_send_sends_one_message_no_recipient_no_status_change`, `_never_creates_a_receipt_recipient_link`, `_unresolvable_binding_422`, `_contact_outside_workspace_404`, `_works_regardless_of_broadcast_status`, `_requires_broadcasts_send_permission`, `_tenant_isolation_404`. **E2E** `08`/`09` - one new `conversation_messages` row for `cnt-001`, **zero** recipient rows, status still DRAFT, counts unchanged |
| AC-BRD-42 | [BE] | PASS | `test_run_due_broadcasts_starts_overdue_scheduled_broadcast`, `_is_a_no_op_when_nothing_due`, `test_start_scheduled_broadcast_claim_race_only_one_wins`, `_reconciles_and_finalizes_stuck_sending`, `_leaves_genuinely_queued_broadcast_alone`; the task is registered on the workflow beat (`worker.py` `beat_schedule` `broadcasts-due`, 60s) inside `try/except ImportError` and a catch-all. **E2E** the tick was run inline against an overdue SCHEDULED broadcast -> `{'started': 1}`, row flipped to Sent with 3/0/0/0 (`18-list-after-due-tick-1280.png`) |
| AC-BRD-43 | [BE] | PASS | `test_entity_event_completed_emitted_on_sent`, `test_no_conversation_events_written_for_a_broadcast` |
| AC-BRD-44 | [BE] | PASS | `test_workflow_entity_registered`, `test_record_facts_resolve_for_a_real_broadcast`, `test_record_status_fact_tracks_a_terminal_state`, `test_entity_update_rejected_broadcast_is_read_only`. **Live** `GET /workflows/metadata` lists `omnichannel_broadcast` with `writableFields: []` |
| AC-BRD-45 | [BE] | PASS | `test_realtime_publish_on_send_and_cancel`, `test_record_delivery_realtime_publish`. **E2E** with the Recipients tab open and no reload, the row flipped Sent -> Delivered -> Read as each webhook landed (`22`, `23`) |
| AC-BRD-46 | [BE] | PASS | `git diff d52abdb..ae59090 -- modules/omnichannel/routers/api_v1.py documentation/omnichannel/consumer-integration-guide.md` is **empty**; `schemas.py` gained 173 lines with no `Rio*` line changed; `tests/test_omnichannel_api_gateway.py` green inside the 3144. *Remark: the guard test the plan promised does not exist at `ae59090` - see AC-BRD-51* |
| AC-BRD-47 | [BE] | PASS | `modules/omnichannel/permissions/permissions.csv` lines 25-27 declare `broadcasts.read/manage/send`; live `permissions` rows carry `module = omnichannel` with no core collision; both the pre-existing `default` tenant's Admin and the brand-new `p29-…` tenant's Admin hold all three. Implied-read: granting only `broadcasts.manage` normalized `broadcasts.read` alongside it (observed on the probe role). *Remark / minor deviation (**D-2**): the manifest was **not** bumped to `0.6.0` as plan §2.1/F1 states - it is still `0.5.0`, and the local tenant sits at `installed_version 0.5.0`, so the App-Store "Update" action is never offered. Existing tenants get the keys through `seed.sweep_tenant_admin_grants` at `bootstrap_db`/seed instead. `test_grant_sweep_on_update` artificially downgrades `installed_version` to `0.4.0` to exercise the update path. Outcome (grants reach existing tenants) verified live; mechanism differs from the AC's wording. **Round 2:** the manifest **stays `0.5.0` by decision** - plan §8 F9 records A4 merging before A8, so the bump is deliberately not taken here; the grant path remains the bootstrap sweep* |
| AC-BRD-48 | [BE] | PASS | `test_uninstall_tenant_deletes_broadcasts_and_recipients` (asserts another tenant's rows survive). Not re-run live - uninstalling on `p29-…` would have destroyed the isolation evidence |
| AC-BRD-49 | [BE] | PASS | Live wire inspection: every field camelCase, every datetime Z-suffixed (`"createdAt":"2026-09-06T08:54:45.039970Z"`), 409s typed `{"reason": "broadcast_not_editable" \| "broadcast_not_cancellable"}`, and four live 422 probes all returned the house shape - `{"fieldErrors":{"name":"Name is required."}}`, `{"fieldErrors":{"bindings.body.0.text":"Static text cannot contain {{ }} merge syntax."}}`, `{"fieldErrors":{"audience.contactIds":"One or more contacts are not in this workspace."}}`, `{"fieldErrors":{"templateId":"Select an approved template of this channel."}}` |
| AC-BRD-50 | [BE] | PASS | `test_job_visible_in_jobs_endpoint_with_progress`; live `GET /jobs/{id}` -> `type: "omnichannel.broadcast_send"`, `progressTotal: 3` (= audience size), `progressDone: 3`, `progressFailed: 0`, registered through `register_job_handler` (`broadcast_send_service.py:615`, no bespoke table). **E2E** `39-jobs-drawer-broadcast-send-1280.png` - every send listed with its progress bar |
| AC-BRD-51 | [T] | PASS (round 2) | **Round 2 on `c491d4a9`:** the gateway guard now exists and is green - `test_gateway_router_carries_no_broadcast_surface`, `test_gateway_rio_schemas_carry_no_broadcast_field`, `test_consumer_integration_guide_carries_no_broadcast_mention` (`tests/test_omnichannel_broadcasts_workflow_entity.py`); the five broadcast pytest files total **138 passed**. *Round-1 finding, kept for the record:* 98 broadcast pytest functions cover every listed area **except one**: there is **no guard test that no gateway file changed** at `ae59090` (`grep` over `tests/test_omnichannel_broadcasts*.py` for `api_v1` / `consumer-integration-guide` -> nothing at HEAD). The AC's other named items are all present and green - the 422 matrix (13), status-gated edits (3), duplicate, audience preview (3), snapshot incl. join-after-snapshot, all five skip reasons, preflight (2), chunk-executed-twice idempotency (3), CSW exemption, actor resolution, binding resolution + sanitization (3), rate pacing (2), transient vs permanent (2), receipts from both seams (3), reconciler adopt + give-up (3), count invariant, cancel from scheduled and mid-sending (3), scheduled beat claim (5), test-send creating no recipients (7), entity-event shape (2), realtime publish (2), per-route permission gates (3), per-route tenant isolation (3), uninstall cleanup. *The missing guard test is being added in the concurrent uncommitted round; it is absent from the commit under test* |
| AC-BRD-52 | [T] | PASS (round 2) | **Round 2 on `c491d4a9`:** `broadcast-form-sections.test.tsx` covers the template picker ("excludes a non-approved (PENDING) template", "excludes an APPROVED template with a media header (IMAGE/VIDEO/DOCUMENT)", "returns no templates and makes no call while no channel is selected", "resolves to an empty list ... when the service call rejects") and `services/broadcast-service.mock.test.ts` (10) exercises every seeded status view plus the 404/409/422 paths and duplicate; the broadcasts vitest set totals **81 passed** across 12 files. *Round-1 finding, kept for the record:* 52 broadcast vitest tests cover the builder schema (audience exactly-one, binding count from the template shape, required fallback, past-schedule rejection, static text rejecting token syntax), the status-badge registry mapping, the recipient state filter, `useCan` gating of Send/Cancel and the audience-preview hook. **Two named items are not covered**: (a) no test asserts the **template picker excludes non-approved and media-header templates** (the filter lives untested at `broadcast-form-sections.tsx:193`); (b) no test exercises **the mock service states** - `broadcast-service.mock.ts` has no test file and is no longer imported by anything |
| AC-BRD-53 | [E2E] | PASS | Recorded `agent-browser --session s29t` run, real clicks from `/`, evidence at 375px and 1280px under `29-evidence/E2E/` with a README run log. Journey: sidebar -> Omnichannel -> Broadcasts -> Create -> name `E2E broadcast 20260906T085024Z` -> audience -> channel `Demo WhatsApp (sandbox)` -> template `booking_update` -> slot 1 Contact field First name (fallback `there`), slot 2 static text -> Review -> Test send to Sarah Chen -> Send now -> Sending/Sent -> Recipients tab lists every recipient with its state -> counts match -> the Inbox thread shows the template message (`01`-`12`). *Deviation from the AC's literal script, deliberate and briefed: the audience was a saved 3-contact segment rather than the 5 demo contacts, so the segment path (roadmap D6) was exercised too; a separate broadcast used all 5 via Selected contacts* |
| AC-BRD-54 | [E2E] | PASS (round 2) | **Round 2 on `c491d4a9`:** clause (a) performed from the ROW - the Scheduled copy's row `Actions` > Cancel -> `POST .../cancel 200`, row `Cancelled`, toast "Broadcast cancelled.", `psql` CANCELLED / 0 sends (`r2-11`, `r2-12`). Clauses (b) and (c) stand from round 1. *Round-1 finding, kept for the record:* Two of the three clauses PASS: (b) the freshly provisioned `p29-20260906t0850` cannot see tenant A's broadcasts - empty list in the UI (`31`) and uniform `404` on 13 API route/method combinations in both directions; (c) a user without `broadcasts.send` sees no Send / Test send / Cancel control (`35`, `37`) while the API still refuses with `403` on all three routes. Clause (a) **cannot be performed**: there is no list **row action** menu at all (defect D-1), so "cancelled from the list row action" is unreachable. Cancel-from-SCHEDULED itself works from the form surface and lands `Cancelled` with zero sends (`20`, `21`) |
| AC-BRD-55 | [T] | PASS | This report, `AI_Agent_Orchestration_Guide.md` §6 format, PASS/FAIL/DEFERRED per AC id, citing `29-evidence/E2E/` for every `[E2E]` id. *Deferred items are listed below with backlog candidates; `documentation/backlogs/backlog.md` was deliberately **not** edited (main's numbering is authoritative at merge, per the brief)* |

---

## Defects found

| # | Severity | AC | Description | Repro |
|---|---|---|---|---|
| **D-1** FIXED `c491d4a9` (verified round 2) | High (contract) | AC-BRD-11, AC-BRD-54 | The broadcasts list renders **no row-actions column**, so Send / Schedule / Cancel / Duplicate / Edit / Delete are unreachable from a list row. `useBroadcastActions` declares `surfaces: {row: true}` on all five actions but `use-broadcasts-list-config.tsx` never adds the `id: 'actions'` column that `use-users-list-config.tsx:162` uses to render `<ActionMenu … surface="row">`. Bulk actions are also effectively invisible for most statuses because the only row-level entry point is missing | Sidebar > Omnichannel > Broadcasts. `Array.from(document.querySelectorAll('table thead th')).map(t => t.innerText)` -> no Actions column. Screenshot `13-list-no-row-actions-column-1280.png` |
| **D-2** CLOSED by decision (plan §8 F9: manifest stays `0.5.0`) | Low (deviation) | AC-BRD-47 | `modules/omnichannel/manifest.json` was **not** bumped to `0.6.0` (still `0.5.0`), contrary to plan §2.1 / flag F1. A tenant already installed at `0.5.0` is therefore never offered an App-Store **Update**, so the AC's stated grant mechanism ("manifest version bump plus `update_tenant`") does not fire; the keys reach existing tenants only via `sweep_tenant_admin_grants` on the next `bootstrap_db`/seed. The outcome is safe, the documented mechanism is not what ships | `grep '"version"' modules/omnichannel/manifest.json` -> `0.5.0`; `select installed_version from tenant_modules` -> `0.5.0` for the pre-existing `default` tenant |
| **D-3** FIXED `c491d4a9` (verified round 2) | High | AC-BRD-05 | The Audience **Filter** source is non-functional. `audience-section.tsx` `AUDIENCE_FILTER_FIELDS` is a hardcoded four-entry stub (`status`, `priority`, `assignee` as an enum with a single "unassigned" option, `lastMessageAt`) instead of the contact filter map; `status` and that `assignee` shape are not in `CONTACT_FILTER_COLUMNS`, so the preview 422s and the count never resolves. This is also a foolproof-UI violation (a picker offering choices that cannot work) | New broadcast > Audience source **Filter** > Build filter > `Status is any of Open` > Apply. Preview `POST .../audience-preview` -> `422 {"detail":"field not filterable: status"}`; the section shows `-  recipient(s) resolved`. Screenshot `40-audience-filter-branch-1280.png` |
| **D-4** FIXED `c491d4a9` (verified round 2) | High (blast radius) | AC-BRD-18, AC-BRD-23 | An inline filter whose rule list is **empty**, or whose rules key the server does not recognise, is silently accepted and resolves to **every contact in the workspace** - `200 {"count": 5}` on preview and `201` on create, stored as `{"kind":"group","combinator":"and","rules":[]}`. The client zod schema rejects a zero-condition filter, but the server has no mirror, so an API caller holding `broadcasts.manage` can persist a broadcast whose send-time snapshot fans out to the entire contact base. AC-BRD-23 explicitly requires an invalid filter to 404/422 "rather than a silent 0"; this is a silent *all* | `POST .../broadcasts/audience-preview` with `{"audience":{"kind":"filter","filter":{"kind":"group","combinator":"and","rules":[]}}}` -> `200 {"count":5}`. Same body on `POST .../broadcasts` -> `201`; row `E2E malformed-filter probe 20260906T085024Z` (`4f71f799-c59a-4f58-bb22-bdb575f76ca4`) left as a DRAFT on `foundryx_service_s29`, deliberately not sent. Control: `"rules":[{"kind":"condition","field":"firstName","operator":"contains","value":"zzz"}]` -> `{"count":0}`, `…"value":"Sarah"` -> `{"count":1}` (so the correct shape does work) |
| **D-5** FIXED `c491d4a9` (verified round 2) | Low | AC-BRD-51 | No guard test asserts that no gateway file changed (`api_v1.py`, `Rio*`, `consumer-integration-guide.md`) at `ae59090`, although the substance holds (verified by `git diff`). Being added in the concurrent uncommitted round | `grep -l "api_v1\|consumer-integration-guide" tests/test_omnichannel_broadcasts*.py` at `ae59090` -> nothing |
| **D-6** FIXED `c491d4a9` (verified round 2) | Low | AC-BRD-52 | No vitest asserts the template picker excludes non-approved / media-header templates, and no vitest exercises the mock service states; `broadcast-service.mock.ts` has no test file and no importer | `grep -rn "APPROVED" app/(protected)/omnichannel/broadcasts/` -> one production line (`broadcast-form-sections.tsx:193`) and one fixture, no assertion |

### Non-defect observations

1. **A `broadcasts.read`-only role cannot use the surface.** The list resolves its workspace via `GET /omnichannel/workspaces`, gated `workspaces.read`; without it the call 403s and the list renders empty with no explanation. The RBAC probe role had to be granted `workspaces.read` (plus `channels.read` / `wa_templates.read` for the builder). Worth a documented "Broadcasts needs these companion keys" note, or a friendlier empty state.
2. **The `SCHEDULED -> SENDING` claim and the job creation are not atomic.** `start_scheduled_broadcast` commits the status claim, then calls `JobService.create`. During setup I invoked the tick from a process that had not run the module boot hook; `JobService.create` raised `UnknownJobType` after the claim had committed, leaving the pre-existing residue broadcast `Live Probe Broadcast Renamed` parked in `SENDING` with `job_id NULL` and no recipients. The 15-minute stuck-SENDING reconciler inside `run_due_broadcasts` is the designed repair, and the failure mode is only reachable from a misbooted process - recorded as an observation, not a defect.
3. **Ops note for the real deployment:** any Celery process that runs `omnichannel.broadcasts_due` (or the broadcast_send job) must import `modules.omnichannel.bootstrap.register_engine_entities`, exactly as the code comment at `bootstrap.py:100-115` warns. Worth one line in the deploy runbook.

## Round 2 verification (commit `c491d4a9`, 2026-09-06 14:00-14:25 UTC)

**Scope:** re-record, with real clicks in `agent-browser --session s29t2`, exactly the surfaces the
review-round-1 fix commit changed, and re-run the targeted suites once. Tree clean at start and end;
servers already rebuilt on `c491d4a9` by the coordinator (not restarted here); no product code touched.
Full run log + curl transcripts: `29-evidence/E2E/README.md` ("Round 2").

| Fix | AC | Result | Evidence |
|---|---|---|---|
| D-1 row actions | 11, 54 | **PASS** | Actions column present (`r2-02`); Scheduled row > Cancel from the ROW -> `Cancelled`, 0 sends (`r2-11`, `r2-12`); Draft row > Delete -> deferred toast "Deleting in 9s / Cancel" (`r2-14`), left to lapse -> row gone, `pending_actions` **committed**; a second draft's toast Cancel -> `POST .../pending-actions/{id}/cancel 200`, row survives (`r2-15`), `pending_actions` **cancelled** |
| D-3 / B3 filter audience | 05 | **PASS** | Field picker = contact filter columns (`r2-03`); `Name contains a` > Apply -> 6 recipient(s) (`r2-04`) |
| D-4 server-side filter validation | 18, 23 | **PASS** | Empty group -> `422 {"fieldErrors":{"audience.filter":"Add at least one condition."}}` on preview AND create; unknown key -> `422 extra_forbidden` on both; valid control -> `200 {"count":1}` / `201` |
| S2 server-searched pickers | 07 (builder), 41 (test send) | **PASS** | Test-send picker and audience contacts picker both fire `GET .../contacts?...&search=Ais` and narrow to Aisha (`r2-06`, `r2-07`); tenant has 6 contacts (< 50), so the narrowing is the evidence |
| S3 empty static binding | 18 | **PASS with observation O-4** | Client guard blocks the save (no `POST`, page stays on `/new` - `r2-05`) and the server rejects the same body with `422 fieldErrors.bindings.body.0.text`; **but the client renders no field error and no toast** (`r2-05b`) - see O-4 |
| B2 unreplied stays unreplied | 43 (adjacent) | **PASS** | Inbox > Unreplied before (`r2-01`) and after a 6-recipient send (`r2-09`): `Phase2Probe Unreplied` still listed, `last_agent_message_at IS NULL` in `psql`; `test_broadcast_send_leaves_an_unreplied_contact_unreplied` |
| D-5 / D-6 tests | 51, 52 | **PASS** | Named in the AC rows above; 138 pytest + 81 vitest green |
| 375px | 14 | **PASS** | `r2-16`, `r2-16b`, `r2-17`; `scrollWidth === 375`, all 6 row-action buttons reachable inside the table scroller |

**O-4 (new, minor UX, not a guard failure):** the "Static text is required." zod rule blocks the
save silently - `BindingEditor` takes no `error` prop and `form.handleSubmit` has no `onInvalid`, so
the error sits in `formState.errors.bindings.body[n].text` unrendered. Backlog candidate alongside
BL-SS-119/120.

## DEFERRED

| Item | AC touched | Reason | Backlog candidate |
|---|---|---|---|
| Media-header template support in a broadcast | AC-BRD-06 (out-of-scope half) | Plan decision D-A4-6: a media-header template needs per-send header bytes uploaded by id; that is its own design. The picker and the server both exclude them, and the exclusion is tested server-side | plan 29's **BL-SS-083** |
| Per-channel rate cap across concurrent broadcasts | AC-BRD-35 (documented limit) | Plan decision D-A4-12 accepts that two concurrent broadcasts on the same channel can exceed the tier in v1; a Redis token bucket is out of scope | plan 29's **BL-SS-084** |

*(Both were deferred by the plan itself, not by this test pass. The plan also reserves
**BL-SS-085** for opted-out / blocked-contact skips, per D-A4-20 - not an AC, so not tallied.
`documentation/backlogs/backlog.md` was deliberately not edited: main's numbering is
authoritative at merge.)*

## Could not verify

- **AC-BRD-48 live** - `uninstall_tenant` cleanup was not re-run against the live DB because it
  would have destroyed the isolation tenant that AC-BRD-54's evidence depends on. Covered by
  `test_uninstall_tenant_deletes_broadcasts_and_recipients`.
- **AC-BRD-06 "changing the channel clears the template and its bindings"** - not separately
  re-clicked (the run only ever picked one channel) and it has no dedicated test either side.
- **AC-BRD-03 "switching a segment clears row selection"** - relied on the shell's own behaviour
  and its own tests; not re-clicked on this surface.
- **Post-restart API behaviour (round 1)** - resolved: round 2 re-ran every changed surface on a
  clean `c491d4a9` with servers built on that commit.
