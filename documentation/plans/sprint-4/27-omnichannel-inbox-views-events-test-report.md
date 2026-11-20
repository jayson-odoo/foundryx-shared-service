# Sprint 4 · Plan 27 - Omnichannel Inbox Views, Conversation Actions, Conversation Events · Test Execution Report

**Branch:** `sprint-4/27-inbox-views-events` (worktree `.claude/worktrees/s27`, HEAD `7239856`)
**Date:** 2026-09-06
**Environment:** backend `:8006` (DB `foundryx_service_s27`, Postgres, `ENVIRONMENT=development`,
`CELERY_TASK_ALWAYS_EAGER=true`), frontend `:3005` (prod build, `npx next start -p 3005`), Redis
`:6379`.
**Tester:** automated E2E via `agent-browser --session s27` (real clicks; Playwright is retired -
no specs written or run) + `python -m pytest -q` + `npx vitest run`.

## Result summary

| Gate | Result |
|---|---|
| Backend suite (`pytest -q`, full repo) | **2934 passed, 1 skipped, 18 deselected** (1632.77s) |
| `tests/test_omnichannel_conversation_events.py` | 20 test functions, all passing (part of the 2934) |
| `tests/test_omnichannel_inbox_views.py` | 39 test functions, all passing (part of the 2934) |
| `tests/test_omnichannel_shortcuts.py` | 10 test functions, all passing (part of the 2934) |
| `tests/test_workflow_shortcuts.py` | 18 test functions, all passing (part of the 2934) |
| `tests/test_omnichannel_deferred_actions.py` | 17 test functions, all passing (part of the 2934) |
| `tests/test_omnichannel_api_gateway.py` | 58 test functions, all passing, unchanged shapes (part of the 2934) |
| Frontend suite (`vitest run`) | **268 test files, 2036 tests passed** |
| `[E2E]` AC-IVE-49 (recorded run) | **PASS** - dedicated tenant, real clicks, screenshots `27-evidence/E2E/00`-`44` |
| `[E2E]` AC-IVE-50 (shortcut + isolation) | **PASS** - workflow built via real canvas clicks + a real handle drag, run twice, isolation probes uniform 404, no-module tenant hides Inbox |
| Responsive 375px + 1280px | **PASS** - every new/changed surface checked both widths, screenshots `22`-`24`, `42`-`44` at 375px |

**Environment note (infra, not product code):** none required this run - the lane's servers
(`:8006` backend, `:3005` frontend) were already up and correctly owned per the brief; no restart
needed.

## Tenants created (all timestamped, none reused from another lane)

| Tenant | Slug | Purpose |
|---|---|---|
| P27 Inbox Views 20260905224804 | `p27-20260905224804` | Primary E2E tenant - Admin `p27-admin-20260905224804@example.com` / `Passw0rd!2026` |
| P27 NoOmni 20260905224804 | `p27-noomni-20260905224804` | Isolation check - module never installed - Admin `p27-noomni-admin-20260905224804@example.com` / `Passw0rd!2026` |

`p25-noomni-*` (mentioned as a reuse candidate in the brief) does not exist on `foundryx_service_s27`
(each lane owns its own Postgres DB per the CLAUDE.md port/DB table), so a fresh
`p27-noomni-20260905224804` was created instead - confirmed via `psql ... where slug ilike
'%noomni%'` returning 0 rows before creation.

## Setup calls made outside real clicks (recorded per the brief's "record it as setup" rule)

1. **Mint API key** - done via real clicks (Workspaces > General > API Keys > Mint key), not an
   API call; key `fxw_live_DAwwfkn1...` (workspace `General`, tenant `p27-20260905224804`).
2. **3 contacts + inbound messages** - the consumer guide has **no** `POST
   /api/v1/omnichannel/contacts` endpoint (contacts are created by inbound stitch or an outbound
   send to a new number, per `documentation/omnichannel/consumer-integration-guide.md` §9/§4 -
   confirmed by grep, the brief's literal endpoint name does not exist on this codebase). Used the
   dev-safe webhook route directly (`POST /omnichannel/webhooks/{channel_id}`, unsigned - dev mode
   since `META_APP_SECRET` is unset locally) with a Meta-shaped inbound payload (same shape as
   `tests/test_omnichannel_webhooks.py::_wa_payload`) for 3 new phone numbers, each producing one
   `opened` conversation event - verified via `psql`. The WhatsApp channel itself (Foundryx Events
   Co., sandbox) was connected via real clicks (Channels > Connect channel > Connect (sandbox) >
   Authorize).
3. **One outbound reply to contact 3** (`POST /api/v1/omnichannel/messages`, gateway) - setup to
   produce a "replied" thread so the Unreplied toggle/sort had a real off-vs-on effect to assert
   against (all 3 fresh contacts would otherwise be identically unreplied).
4. **Isolation probes** - `curl` with the default tenant's JWT (from `POST /auth/login`) against
   every new route with tenant-A ids, and a `GET /omnichannel/workspaces` probe with the no-module
   tenant's JWT. Recorded verbatim in the isolation section below.

Everything else (tenant creation, module install, close reasons, saved views, thread actions,
close/reopen, the shortcut workflow build + publish + run) was real sidebar/canvas clicks from `/`
per the brief.

## Harness notes (not product defects, confirms prior evidence)

- Plan-23 motion-wrapped dialog/dropdown/tab triggers frequently no-op'd on `agent-browser click
  @ref` / CDP; the documented workaround (`pointerdown -> mousedown -> pointerup -> mouseup ->
  click` dispatched via `eval` on the real element, `[role=dialog]`-scoped when a trigger button
  shares text with a dialog's submit button) was used throughout and worked every time.
- `Escape` inside a nested Radix Select-inside-Dialog closed the OUTER dialog too (not just the
  select popover) once - cost one redo of the close-dialog flow. Selecting an option normally
  (native pointer sequence, no Escape) closed only the popover as expected on every other
  occasion.
- The deferred-delete countdown (close reasons) is short (~9-10s) - the first delete+cancel
  attempt committed before the cancel click landed (several `eval` calls elapsed first); redone
  immediately-chained and captured correctly the second time (see AC-IVE-22 evidence).
- React Flow handle-to-handle wiring (Shortcut trigger -> Update-a-record action) needed a real
  `mouse move -> down -> move -> up` sequence at the handle dot coordinates (found via
  `getBoundingClientRect` off the fitted-view screenshot) - a bare `drag` command was not
  attempted given this documented gotcha; the manual sequence worked on the first try.
- At 375px the conversation-drawer header action row (assignee/priority/status chips, Snooze,
  Close, Shortcuts) overflows its own container horizontally (`scrollWidth` 721 vs `clientWidth`
  341) while the PAGE itself never scrolls horizontally (`document.documentElement.scrollWidth ===
  375` throughout). Shortcuts is reachable by scrolling that one row (verified, screenshot `43b`).
  This is a legitimate scoped-overflow toolbar pattern (not a page-level violation of the no-
  horizontal-scroll mandate) but is dense; noted as a UX candidate, not a FAIL - see Defects/
  Deferred below.
- Three blank entries came back from `agent-browser errors` at the end of the run with no message
  text; `agent-browser console` for the same session showed only benign Radix `Missing Description
  for DialogContent` a11y warnings (pre-existing shell pattern, not introduced by this plan) and no
  JS exceptions. Could not attribute the blank entries to a specific action; flagged under "could
  not fully verify" rather than claimed as a defect.

## Per-AC results (`27-omnichannel-inbox-views-events-acceptance-criteria.md`)

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-IVE-01 | [BE] | PASS | `test_conversation_events_table_shape` |
| AC-IVE-02 | [BE] | PASS | `test_event_write_rolls_back_with_its_mutation` |
| AC-IVE-03 | [BE] | PASS | `test_opened_event_new_thread_inbound`, `test_opened_event_gateway_create`; **E2E** 3 webhook-created contacts each carry exactly one `opened` event (`psql` verified) |
| AC-IVE-04 | [BE] | PASS | `test_auto_reopen_and_unsnooze_events_on_inbound` |
| AC-IVE-05 | [BE] | PASS | `test_manual_status_change_events`; **E2E** close (`19-closed-feed-1280.png`) and reopen (`21-reopened-feed-1280.png`) each wrote exactly one event, visible in the feed |
| AC-IVE-06 | [BE] | PASS | `test_assign_unassign_events`; **E2E** `15-assigned-to-self-1280.png` + feed line "P27 Admin assigned to P27 Admin" |
| AC-IVE-07 | [BE] | PASS | `test_first_agent_reply_once_per_open_cycle`; **E2E** the setup reply to contact 3 produced one `first_agent_reply` event with `payload_json.responseSeconds: 264` (`psql` verified) |
| AC-IVE-08 | [BE] | PASS (forward-looking per the amendment) | `test_lifecycle_changed_event` - no live UI path exists for this plan (no workflow action moves lifecycle yet, per the amendment text), confirmed by reading the current AC wording |
| AC-IVE-09 | [BE] | PASS | `test_comment_added_event_native`, `test_comment_added_event_gateway`; **E2E** internal note added, `comment_added` backing event confirmed via `psql` while the feed showed the note bubble without a duplicate line (AC-IVE-34 behavior) |
| AC-IVE-10 | [BE] | PASS | `test_actor_tenant_scoped_save_and_read`; **E2E** actor names ("P27 Admin") render correctly, never another tenant's name |
| AC-IVE-11 | [BE] | PASS | `test_last_agent_message_at_maintained_by_sends_not_notes` |
| AC-IVE-12 | [BE] | PASS | `test_backfill_tenant_function`, `test_seed_demo_conversations_backfills_events`, `test_backfill_tenant_is_batched_not_n_plus_one`, `test_install_tenant_self_heals_events` |
| AC-IVE-13 | [BE] | PASS | `test_list_events_route_shape_pagination_and_tenant_isolation`; **E2E** `GET .../events` cross-tenant probe returned 404 (isolation section) |
| AC-IVE-14 | [BE] | PASS | `test_uninstall_tenant_deletes_conversation_events` |
| AC-IVE-15 | [BE] | PASS | `test_thread_list_channel_and_tag_filters`, `test_thread_list_lifecycle_filter`, `test_thread_list_unreplied_filter` |
| AC-IVE-16 | [BE] | PASS | `test_thread_list_sorts`, `test_thread_list_sort_stable_pagination`; **E2E** `08-show-sort-unreplied-1280.png` shows Longest-waiting ordering matching `last_incoming_message_at ASC` |
| AC-IVE-17 | [BE] | PASS | `test_view_id_expansion_and_override`; **E2E** `12`/`13` - saved view with `unreplied:true` active, then explicit `unreplied=false` override reveals contact 3 while the view stays selected (the exact regression this AC's wording protects against) |
| AC-IVE-18 | [BE] | PASS | `test_inbox_view_create_read_own`, `test_inbox_view_unknown_filter_key_422`, `test_inbox_view_id_validated_against_workspace`, `test_inbox_view_name_unique_case_insensitive`, `test_inbox_view_cap_50_per_workspace` |
| AC-IVE-19 | [BE] | PASS | `test_inbox_view_own_vs_shared_permission_split`, `test_inbox_view_own_view_needs_only_conversations_read`, `test_inbox_view_someone_elses_view_needs_manage`, `test_inbox_view_shared_view_needs_manage_to_edit` |
| AC-IVE-20 | [FE] | PASS | `inbox-view-rail.test.tsx` (8 tests); **E2E** `06-inbox-1280.png` (All/Mine/Unassigned + Lifecycle + Views), `11-reload-restores-view-1280.png` (reload restores `?view=` from the URL) |
| AC-IVE-21 | [FE] | PASS | `inbox-filter-bar.test.tsx` (4 tests); **E2E** `08-show-sort-unreplied-1280.png` - Show/Sort are `SearchSelect` comboboxes, Unreplied a switch |
| AC-IVE-22 | [FE] | PASS | `inbox-view-dialog.test.tsx` (5 tests, incl. "hides the Shared switch entirely without inbox_views.manage"); **E2E** `09` (save dialog, Shared toggle), `10` (saved + selected), `41-rename-view-dialog-1280.png` (Rename dialog carries Name + Shared switch), `26`-`28` (deferred-delete undo toast for close reasons, same pattern per the amendment - see close-reason delete below; the saved-view row's own Delete menuitem follows the identical `useDeferredAction` pattern per `inbox-view-rail.tsx`, confirmed by code review of the same commit, not separately re-clicked to avoid destroying the working "Waiting" view mid-run) |
| AC-IVE-23 | [FE] | PASS | **E2E** `19-closed-feed-1280.png` -> `20-show-closed-1280.png`: contact 1's row left the Open list live with no manual refresh, then reopening it live-vacated the Closed list too |
| AC-IVE-24 | [FE] | PASS | **E2E** `23-list-375.png` (rail collapses to a `View` SearchSelect, single pane, `scrollWidth===375`), `22-thread-375.png` (conversation pane with a "Back to conversations" control) |
| AC-IVE-25 | [BE] | PASS | `test_close_reason_crud`, `test_close_reason_permission_gates` |
| AC-IVE-26 | [BE] | PASS | `test_close_reason_delete_in_use_409_deactivate_ok`; **E2E** `29-in-use-no-delete-1280.png` - "Refund" (1 use) offers only Edit/Deactivate, no Delete |
| AC-IVE-27 | [BE] | PASS | `test_close_reasons_seeded_on_default_workspace`, `test_close_reasons_seeded_on_new_workspace_create`, `test_close_reason_backfill_tenant_idempotent`; **E2E** `02-close-reasons-seeded-1280.png` - fresh tenant's fresh workspace already has the 4 seeded reasons (General Inquiry, Sales Inquiry, Payment Issue, Others) via `install_tenant`, proven by installing via the real Services UI |
| AC-IVE-28 | [BE] | PASS | `test_close_route_happy_path`, `test_close_route_publishes_contact_updated_once`; **E2E** `18`-`19` - closed with reason + note, one `closed` event with `close_reason_id` + `note` persisted (`psql` verified) |
| AC-IVE-29 | [BE] | PASS | `test_close_route_rejects_missing_reason`, `test_close_route_rejects_inactive_reason`, `test_close_route_rejects_foreign_workspace_reason` |
| AC-IVE-30 | [FE] | PASS | `close-thread-dialog.test.tsx` (6 tests); **E2E** `18-close-dialog-filled-1280.png` (Close disabled until a reason is chosen, confirmed by the dialog snapshot sequence: `Close conversation` `[disabled]` before reason pick, enabled after) |
| AC-IVE-31 | [FE] | PASS | `use-close-reason-list.test.tsx` (5 tests, incl. "hides the create action entirely when canManage is false"); **E2E** `02-close-reasons-seeded-1280.png` (Close reasons tab after Tags, embedded ResourceList with Name/Sort order/Active/Uses/Date added), `25`/`26`-`28` (Deactivate then deferred Delete with cancel-once-then-commit), `29` (Delete hidden for an in-use reason) |
| AC-IVE-32 | [FE] | PASS | `activity-feed.test.tsx` (5 tests); **E2E** `17-activities-feed-1280.png` - merged chronological feed: "Conversation opened" / "assigned to" (compact system lines) + the internal note (authored bubble) |
| AC-IVE-33 | [BE] | PASS | Verified by the existing (pre-plan) suite staying green - `conversations.reply` gate and `message.created` publish are unchanged; the amendment text matches shipped gateway behavior (`senderType: "SYSTEM"` on note reads), confirmed in `tests/test_omnichannel_api_gateway.py` (58/58 passing, no diff needed) |
| AC-IVE-34 | [FE] | PASS | `activity-feed.test.tsx` covers note-vs-event dedup; **E2E** `17-activities-feed-1280.png` shows the note bubble with no adjacent duplicate `comment_added` line |
| AC-IVE-35 | [BE] | PASS | `test_entity_shortcut_trigger_registered`, `test_workflow_entity_supports_shortcut_flag`, `test_metadata_advertises_supports_shortcut`; **E2E** the workflow builder's Entity picker for the Shortcut trigger listed only "Contact" (the one `supports_shortcut` entity), confirmed live |
| AC-IVE-36 | [BE] | PASS | `test_list_shortcuts_returns_published_workflow`, `test_list_shortcuts_unknown_contact_is_404`, `test_shortcut_routes_require_conversations_shortcut_permission`; **E2E** the Shortcuts control listed "P27 Shortcut 20260905224804" once published+active |
| AC-IVE-37 | [BE] | PASS | `test_run_shortcut_happy_path_validates_and_publishes_webhook`, `test_create_run_for_event_returns_the_run`; **E2E** `38`/`39-workflow-run-action-detail-1280.png` - run detail shows `triggeredBy: "event"`, resolved `recordId` = the exact contact id, output `countryCode: "MY"` written |
| AC-IVE-38 | [BE] | PASS | `test_run_shortcut_rejects_workflow_of_another_entity`, `test_run_shortcut_rejects_unpublished`, `test_run_shortcut_rejects_code_node_without_authorization` (+ `test_workflow_shortcuts.py`'s `test_run_shortcut_rejects_wrong_entity/_unpublished/_inactive/_archived/_foreign_tenant/_non_shortcut_trigger/_unauthorized_code_node`) |
| AC-IVE-39 | [FE] | PASS | `shortcut-menu.test.tsx` (6 tests); **E2E** `35-shortcuts-control-1280.png` (control appears once a shortcut exists), `37-shortcut-run-toast-contact3-1280.png` (toast "Shortcut started." + "View run" link) |
| AC-IVE-40 | [BE] | PASS | `test_require_native_refuses_any_embed_principal_regardless_of_caps` |
| AC-IVE-41 | [BE] | PASS | `test_permission_csv_new_keys_present`, `test_admin_grant_includes_new_keys_after_module_update` |
| AC-IVE-42 | [BE] | PASS | `test_tenant_isolation_on_new_routes`, `test_shortcut_routes_tenant_isolation`; **E2E** live isolation probe (see below) - every new route returned a uniform 404 for tenant-A ids under the default tenant's JWT |
| AC-IVE-43 | [FE] | PASS | `inbox-view-dialog.test.tsx` ("hides Shared switch without `inbox_views.manage`"), `inbox-view-rail.test.tsx` ("hides/shows Manage for another user's view"), `shortcut-menu.test.tsx` ("renders nothing without `conversations.shortcut`"), `use-close-reason-list.test.tsx` ("hides create without canManage") - all four permission-gated controls confirmed hidden client-side; the API-level 403 half is covered by `test_close_reason_permission_gates` / `test_shortcut_routes_require_conversations_shortcut_permission` (backend is the real gate regardless of the UI) |
| AC-IVE-44 | [BE] | PASS | Confirmed by reading `documentation/omnichannel/consumer-integration-guide.md` (no new `/api/v1/` route or field added by this plan) and `tests/test_omnichannel_api_gateway.py` (58/58 unchanged) |
| AC-IVE-45 | [BE][T] | PASS | `git show --stat` on every plan-27 commit (`d86f5cb`, `58b410a`, `181526d`, `081c15c`, `4df6774`, `aebb70d`, `7239856`, `15a59c1`) confirms NONE touches `documentation/omnichannel/consumer-integration-guide.md`; `tests/test_omnichannel_api_gateway.py` 58/58 passing |
| AC-IVE-46 | [FE] | PASS (one UX observation, not a FAIL - see Defects) | **E2E** every listed surface checked at both widths: view rail/list header (`06`-`08` @1280, `23` @375), save-view dialog (`09` @1280, `42` @375), close dialog (`18` @1280, `44` @375), close-reasons tab (`02` @1280, `24` @375), activities feed (`17` @1280, `22` @375), shortcuts control (`35`-`37` @1280, `43`/`43b` @375 - reachable via a scoped horizontal scroll, page itself never scrolls) |
| AC-IVE-47 | [T] | PASS | Backend suite 2934 passed / 1 skipped / 18 deselected; the five plan-27 test files total 104 test functions, all green (counts above) |
| AC-IVE-48 | [T] | PASS | Frontend suite 268 files / 2036 tests passed; the plan-27 FE files cited across AC-IVE-20/21/22/30/31/32/34/39/43 above are all part of that total |
| AC-IVE-49 | [E2E] | PASS | Full recorded run, `27-evidence/E2E/00`-`44` + this report; every step of the brief's script executed via real clicks (tenant create -> install -> close-reasons seeded -> add "Refund" -> inbox rail -> lifecycle filter -> Show/Sort/Unreplied -> save shared view -> reload restores it -> open thread -> assign -> note -> Activities -> Close w/ reason+note -> live-leaves-Open-view -> Show=Closed -> Reopen -> feed keeps both) |
| AC-IVE-50 | [E2E] | PASS | Workflow built via real canvas clicks + a real React-Flow handle drag (Shortcut trigger -> Update-a-record action, entity `omnichannel_contact`, field `countryCode`), published + activated via real clicks; Shortcuts control listed it, ran twice (contacts 2 and 3), both toasts + run details confirmed `trigger.record.id` resolution; isolation probes (below) all uniform 404/empty; the no-module tenant showed no Omnichannel/Inbox menu entry and a direct API probe returned 403 "Module not installed" |

## Isolation probe (AC-IVE-42 / AC-IVE-50, live run)

Default tenant's JWT (`demo@example.com`, tenant `default`) against tenant A's
(`p27-20260905224804`) ids:

| Route | Result |
|---|---|
| `GET /omnichannel/contacts?viewId=<A-view>` | **404** |
| `GET /omnichannel/workspaces/{A-ws}/close-reasons` | **404** |
| `GET /omnichannel/workspaces/{A-ws}/inbox-views` | **404** |
| `POST /omnichannel/contacts/{A-id}/close` | **404** |
| `GET /omnichannel/contacts/{A-id}/events` | **404** |
| `GET /omnichannel/contacts/{A-id}/shortcuts` | **404** |
| `POST /omnichannel/contacts/{A-id}/shortcuts/{A-workflow}` | **404** |
| `GET /omnichannel/workspaces/{B-ws}/inbox-views` (B = default's own workspace) | 200, lists only the DEFAULT tenant's own 4 pre-existing views - none of tenant A's `Waiting 20260905224804` views appear |

No-module tenant (`p27-noomni-20260905224804`) probe:

| Check | Result |
|---|---|
| Sidebar after login as the tenant's own Admin | No "Omnichannel" section, no "Inbox" entry (`grep -i omnichannel/inbox` on the snapshot returns nothing) |
| `GET /omnichannel/workspaces` with that tenant's own JWT | **403** "Module not installed" |

## Defects found

None. Every AC passed against real backend data with no product-code changes required.

## Deferred / follow-up candidates (not blocking, plan 27's own backlog ids renumbered from BL-SS-075 upward per the brief - not written to `backlog.md`)

- **BL-SS-075 (candidate)** - The conversation-drawer header action row (assignee/priority/status
  chips, Snooze, Close, Shortcuts) overflows its own container at 375px (scoped horizontal scroll,
  not a page-level violation - `document.documentElement.scrollWidth` stays 375 throughout) but is
  dense enough that Shortcuts is off-screen without scrolling that one row. A future pass could
  collapse the header into an overflow ("...") menu below ~400px, matching the pattern used
  elsewhere in the design language for icon-only overflow. Priority: Low.
- **BL-SS-076 (candidate)** - Three blank entries surfaced from `agent-browser errors` during this
  run with no attributable message or stack; `agent-browser console` for the same window showed
  only pre-existing benign Radix `DialogContent` description warnings and no JS exceptions. Could
  not reproduce deterministically or attribute to a specific plan-27 surface in the time available;
  worth a follow-up pass with `agent-browser --enable react-devtools` / a DevTools trace if it
  recurs. Priority: Low, informational only - not claimed as a regression.

## Could not fully verify

- The saved-view row's own **Delete** action (as opposed to Rename, which was exercised live) was
  not separately clicked-through in this run to avoid destroying the "Waiting 20260905224804"
  shared view mid-script (it was still needed for later steps). Its deferred-delete path is
  code-identical to the close-reason deferred-delete flow exercised live in this run
  (`inbox-view-rail.tsx`'s delete action registers through the same `useDeferredAction` seam per
  `tests/test_omnichannel_deferred_actions.py::test_inbox_views_delete_own_view_needs_only_conversations_read`
  / `test_inbox_views_delete_shared_view_requires_manage`, both green) - treated as covered by
  backend+FE-unit evidence rather than re-clicked live.
- The exact source of the three blank `agent-browser errors` entries (see Deferred above).

## Suite counts (verbatim)

```
2934 passed, 1 skipped, 18 deselected, 254 warnings in 1632.77s (0:27:12)
```

```
Test Files  268 passed (268)
     Tests  2036 passed (2036)
  Duration  54.60s
```

## Review round 2 fixes (addendum, 2026-09-06)

Opus code-review round 2 (post-`31988b4`) returned four should-fix findings, addressed in one
follow-up commit on top of this branch. No plan/UAC amendment needed - these are bug fixes against
the existing AC-IVE-16/17/21/22 contract, not new scope.

1. **AC-IVE-16/21 (server-side status/priority filtering + saved views)** - `threadQueryString`
   (`services/conversation-service.real.ts`) only sent an explicit `unreplied` override alongside an
   active `viewId`; `status`/`priority` were omitted whenever the bar read "All", so the backend
   (`routers/conversations.py` - absent param = "use the view's stored value", explicit `ALL` =
   "clear it") silently kept applying the view's stored `statuses`/`priority` instead of the
   picked "All". Fixed to always send `status`/`priority` explicitly while `viewId` is set;
   covered by 4 new cases in `conversation-service.real.test.ts`. Live-verified in this addendum:
   selected the tenant's saved view (`Show` auto-expanded to `Open`), set `Show` back to `All`
   without deselecting the view, and confirmed the thread list widened to include a
   previously-hidden thread with no console errors.
2. **AC-IVE-22 (saved view delete)** - deleting the CURRENTLY-SELECTED view left
   `filters.viewId` pointing at the deleted row, 404ing the next thread-list fetch. Fixed:
   `inbox-view-rail.tsx`'s deferred-delete `onCommitted` now falls back to the All rail entry
   (same patch + `?view=` URL key as clicking All) when the committed view was selected. Live-
   verified: selected the tenant's own saved view, deleted it via the deferred (no-confirm-dialog)
   flow, waited past the 10s window, and confirmed the URL fell back to `?view=all` with no error
   toast and no console errors - closing this report's own "Could not fully verify" gap on the
   saved-view Delete action.
3. **AC-IVE-22 (saved view delete, concurrency)** - a single `useDeferredAction` instance backs
   every row in the rail; starting a second delete before the first settled silently overwrote the
   hook's tracked park, so the FIRST toast's Undo would cancel the SECOND view. Fixed: `deleteView`
   now settles (dismisses) any already-active delete toast before starting the next one. Covered by
   a new vitest case driving the real park/settle/cancel sequence via `userEvent` against the mock
   pending-actions service (`inbox-view-rail.test.tsx`). Not independently re-verified live in this
   addendum (CLI round-trip latency between two agent-browser commands exceeded the production 10s
   window on the attempt made, which only proves the single-countdown fallback path again rather
   than the concurrency path) - the vitest case is the authoritative coverage for this finding.
4. **Confirm-to-deferred swap pinned with tests** - `use-close-reason-list.test.tsx` now asserts
   the close-reason delete action carries `deferred: { actionKey: 'close_reasons.delete' }` with no
   `confirm`; `inbox-view-rail.test.tsx` gained a `describe` block (4 cases) driving the saved-view
   delete end to end (parks via the pending-actions service, renders no `alertdialog`, falls back
   to All only when the deleted view was selected, leaves an unrelated selection untouched).

Nits also closed: dead `remove()` removed from `use-inbox-views.ts`/`use-close-reasons.ts` (no
caller used it); `close-thread-dialog.tsx`'s Reason `<Label>` no longer carries a `htmlFor`
pointing at nothing. Backend nit: `deferred_actions.py`'s `_inbox_views_delete` gained a comment
documenting a latent cross-tenant-impersonation edge case (`requested_by_id` is the real actor, not
the effective/impersonated user) - documented per the review's "resolve if the engine passes it,
else document" guidance, since widening the shared `DeferredActionDef.execute` contract for one
consumer was out of scope for this fix.

**Commit:** `87dd467` - `fix(omnichannel): plan 27 review round 2 - view overrides for
status/priority, selected-view delete fallback, single deferred countdown, swap tests` (frontend +
one backend comment-only file; the branch tip immediately following `31988b4` above).

**Suite counts after the fix (verbatim):**

```
Frontend: Test Files  268 passed (268)
          Tests  2045 passed (2045)
```

```
Backend (tests/test_omnichannel_deferred_actions.py only - full suite unaffected, comment-only
change): 17 passed
```

## Addendum - round 3 (codex triage)

Cross-model (Codex) review of the branch after two Opus review rounds passed it, surfacing 32
CANDIDATE findings (B1-B20 backend, F1-F12 frontend). Triaged test-first; verdicts below. Lane:
worktree `.claude/worktrees/s27`, backend `:8006` (PID 52635 after restart), frontend `:3005`
(PID 53658 after a clean rebuild), DB `foundryx_service_s27`.

**Commit:** one commit on top of `432e947` - `fix(omnichannel): plan 27 round 3 - codex triage:
impersonation semantics, assignee guards, scoped resolution, shortcut entity check, view override
tracking, drawer races` (see the branch tip for the hash).

### Verdicts

**Backend**

- **B1 - REAL (fixed in `service_backend/app/services/workflow_service.py`).** `WorkflowService.
  run_shortcut` now resolves the `WorkflowEntity` and requires `supports_shortcut` before anything
  else, then reloads the record tenant-scoped via `entities.load_record` rather than trusting the
  caller's object - defense-in-depth for the generic function (the one real caller, omnichannel's
  `ConversationService.run_shortcut`, already loaded tenant-scoped, but the shared function must
  hold that line on its own). Tests: `test_run_shortcut_rejects_entity_without_supports_shortcut`,
  `test_run_shortcut_rejects_unregistered_entity_type`,
  `test_run_shortcut_reloads_record_tenant_scoped` (`tests/test_workflow_shortcuts.py`).
- **B2 - REAL (fixed, same file).** An unresolved `execution.mode="serialized"` correlation key
  raised a bare `RuntimeError` straight through `run_shortcut` (the manual `run()` path already
  catches this and maps to a `WorkflowError` 409). Added `ShortcutSerializationConflict` and a
  matching `except RuntimeError` in `run_shortcut`, mapped to 409 in
  `modules/omnichannel/routers/conversations.py`. Test:
  `test_run_shortcut_serialized_execution_unresolved_key_is_conflict`.
- **B3 - FALSE POSITIVE (evidence: `app/workflow_engine/entity_events.py` `create_run_for_event`).**
  The published-version lookup filters `WorkflowVersion.id == wf.current_version_id` only, but
  `WorkflowVersion.id` is a UUID surrogate key never shared across workflows, and `wf` (from
  `run_shortcut`'s own tenant-scoped query, or `_match_and_enqueue`'s candidate query) is read in
  the SAME session/transaction with no interleaving commit before this lookup runs - SQLAlchemy's
  `expire_on_commit` default would force a fresh reload of `wf` on the very next attribute access
  after any commit anyway. Joining on `workflow_id` cannot change which row resolves.
- **B4 - REAL (fixed in `app/workflow_engine/entity_events.py`).** In the non-eager path,
  `dispatch_persisted_run` ran AFTER the run row was already committed durable-Pending; an
  unhandled dispatch error (e.g. a broker-down `.delay()`) propagated straight through
  `create_run_for_event` - the CRUD bus survives it via `_dispatch`'s own broad `except Exception`,
  but `run_shortcut` has no such wrapper and would 500 while leaving the committed run stranded (a
  client retry then double-parks). Wrapped the dispatch call in its own try/except - logs, leaves
  the run Pending, returns it unchanged. Test:
  `test_run_shortcut_survives_a_dispatch_failure` (mocks `serialization.dispatch_persisted_run` to
  raise).
- **B5 - FALSE POSITIVE (evidence: `modules/omnichannel/services/event_service.py list_for_contact`).**
  Filters by `tenant_id` + the caller-supplied `contact_id` only, but `contact_id` is a UUID PK
  already tenant-validated by the router (`ConversationService.assert_contact_exists`, added for
  B13 below) before this function ever runs - adding `workspace_id` would be pure redundancy
  (the same row set, since one `contact_id` selects exactly one contact) with zero functional
  effect.
- **B6 - REAL (fixed in `modules/omnichannel/alembic/versions/0009a_omni_inbox_views.py`).**
  `install()`'s `create_schema_and_tables` runs `OmniBase.metadata.create_all` on EVERY boot,
  BEFORE the per-module Alembic stamp-vs-upgrade detection (`_bootstrap_one_module`). On a
  deployment mid-upgrade (an `alembic_version_omnichannel` row already at 0008, `conversation_
  events` not created yet), that `create_all` call fresh-creates `conversation_events` complete
  with the model's embedded `ForeignKey("close_reasons.id")` under a Postgres AUTO-GENERATED
  constraint name, not this migration's literal `fk_conv_events_close_reason` - a name-only check
  missed it, adding a second redundant FK on upgrade, and `downgrade()` could only ever drop its
  own literal name. Detection is now by (columns, referred table) on both `upgrade()`/`downgrade()`,
  name-agnostic. Verified against the live s27 DB (`\d app_omnichannel.conversation_events`) -
  this lane's DB went through the real incremental migration path (no duplicate FK present); the
  fix is defense-in-depth for the `create_all`-races-Alembic deployment shape.
- **B7 - REAL (fixed in `modules/omnichannel/bootstrap.py create_schema_and_tables`).** Verified
  the ordering IS the established module pattern (`install()` -> `create_all` -> per-module
  Alembic stamp-or-upgrade, matching 0004/0008's own precedent, per-tenant data backfill still
  handled correctly by `install_tenant`/`update_tenant`'s Python-level idempotent calls regardless
  of which DDL path ran) - so per the brief's own conditional, the fix is to the MIRROR, not the
  ordering. `create_schema_and_tables` did not mirror 0009a's two functional `lower(name)` unique
  indexes (`uq_close_reasons_workspace_name`, `uq_inbox_views_workspace_name`) - neither model
  declares them as a SQLAlchemy `Index`, so `create_all` never emits them, and on a fresh DB the
  stamp-path means 0009a's migration SQL never runs either. Added matching idempotent
  `CREATE UNIQUE INDEX IF NOT EXISTS` statements to `create_schema_and_tables`, mirroring the
  existing `uq_channels_phone_number_id` precedent in the same function. Verified live: both
  indexes already present on this lane's DB (`\d app_omnichannel.close_reasons` / `.inbox_views`).
- **B8 - REAL (fixed narrowly, in `modules/omnichannel/bootstrap.py seed_demo_conversations`).**
  The idempotency check `Contact.id == "cnt-001"` was unscoped by `tenant_id` - scoped it. Verified
  the two actual call sites (`scripts/bootstrap_db.py`, `scripts/init_db.py`) both always pass
  `DEFAULT_TENANT_ID`, so this is defense-in-depth today, not an active bug; the function ALSO
  hardcodes literal ids (`cnt-001..005`, `tpl-001..003`, `chn-demo`) that would collide (a PK clash,
  or worse a cross-tenant channel reuse for `chn-demo` specifically) if ever called for a second
  tenant - that deeper design gap is out of scope for a dev-only seed script fix and is logged as
  **BL-SS-077** below (backlog section only, not backlog.md).
- **B9 - REAL (fixed in `app/deferred_actions/service.py PendingActionService.park` +
  `modules/omnichannel/deferred_actions.py _inbox_views_delete`).** The round-2 comment on this
  exact line already documented the gap: `_inbox_views_delete` authorized against
  `requested_by_id` (the REAL actor, correct for audit) instead of the EFFECTIVE user, so a
  cross-tenant impersonator's own view-ownership check 404'd/403'd for an action the impersonated
  target was always allowed. `park()` now stamps `payload["_effectiveUserId"] = actor.id`
  SERVER-SIDE (after copying whatever client payload was sent, so it can never be spoofed) -
  generic to EVERY deferred action, not just this one; `_inbox_views_delete` reads it with a
  fallback to `actor_user_id` for callers that never split the two identities.  Tests:
  `test_inbox_views_delete_own_view_authorizes_as_effective_user_under_impersonation`,
  `test_inbox_views_delete_shared_view_still_requires_manage_under_impersonation`
  (`tests/test_omnichannel_deferred_actions.py`) - both exercise `PendingActionService.park`/
  `commit_one` directly with a real impersonation-style actor/requested_by split.
- **B10 - REAL (fixed in `modules/omnichannel/repositories/contact_repository.py list_threads` +
  `services/conversation_service.py` + `routers/conversations.py`).** `assignee == "user"` with an
  empty/omitted `assignee_user_ids` fell through to NO predicate (every thread, any assignee) - the
  SAME bug shape for `assignee == "me"` with neither identity resolved. Both branches now apply a
  false predicate (`sa.false()`) instead of skipping the filter; the router additionally 422s
  `assignee=user` with no ids on the MERGED effective pair (assignee/assigneeUserIds may
  independently come from a saved view, AC-IVE-17). Tests:
  `test_thread_list_assignee_user_without_ids_is_422` (`tests/test_omnichannel_inbox_views.py`).
- **B11 - REAL (fixed, same files).** Tag/channel `EXISTS` subqueries gained an explicit
  `tenant_id` predicate on the link row itself (defense-in-depth alongside the already-tenant-
  scoped correlation - never rely solely on the correlation for tenant safety). A foreign tag/
  channel id now 422s via `ConversationService.assert_explicit_filters_valid`, called on EXPLICIT
  query params ONLY (never a saved view's already-validated, possibly-since-stale expansion - a
  hard-deleted tag must keep degrading a view gracefully, not 422 it forever). The status-key join
  (`Status.id == Contact.status_id`) is intentionally left as an exact-id join with no added
  `tenant_id` filter - adding one would be redundant (same reasoning as B3/B5) and would actively
  BREAK platform-tier (`tenant_id IS NULL`) status rows. Tests:
  `test_thread_list_foreign_tag_id_is_422`, `test_thread_list_foreign_channel_id_is_422`,
  `test_thread_list_view_with_since_deleted_tag_degrades_not_422` (the graceful-degradation
  regression guard) in `tests/test_omnichannel_inbox_views.py`.
- **B12 - REAL (fixed in `modules/omnichannel/routers/conversations.py list_threads`).** Saved-view
  visibility (`InboxViewService.get_visible`'s ownership check) and `assignee=me` both used
  `principal.actor_user_id` (the REAL admin under impersonation, per `ConversationPrincipal`'s own
  docstring) where the house rule calls for the EFFECTIVE user (ownership/"me" is authorization,
  not attribution - matches `resolve_effective_actor`'s existing split for the lifecycle move).
  Both switched to `principal.effective_user_id`. Test:
  `test_view_and_assignee_me_resolve_as_effective_user_under_impersonation` - real impersonation
  session via `/impersonation/start`, mutation-verified (reverting the fix makes the view 404
  under impersonation).
- **B13 - REAL (fixed in `modules/omnichannel/services/conversation_service.py` +
  `routers/conversations.py list_events`).** The router reached `ConversationService(db).repo.
  get_by_id(...)` directly - added `ConversationService.assert_contact_exists` (a thin
  tenant-scoped existence check, mirrors the pattern already used by `list_messages`) and the
  router now calls that instead of touching `.repo`.
- **B14 - REAL (fixed in `modules/omnichannel/services/close_reason_service.py delete`).** A
  conversation could close with a reason BETWEEN the pre-check `in_use` query and the delete
  commit; the FK violation surfaced as an unhandled `IntegrityError` -> 500. Wrapped the commit in
  try/except, translating to the same `CloseReasonInUse` the pre-check raises. Test:
  `test_close_reason_delete_race_is_409_not_500` (monkeypatches `db.commit` to raise once, same
  pattern as the existing A1 tag-race tests).
- **B15 - FALSE POSITIVE (evidence: `event_service.list_for_contact`, same reasoning as B5).**
  Duplicate framing of the same pagination function - `contact_id` already pins the row set to one
  tenant-validated contact; no `workspace_id` predicate is needed for correctness.
- **B16 - REAL (fixed in `modules/omnichannel/services/event_service.py _label_map` + `to_items`).**
  The lifecycle-status branch resolved `CoreStatus` by bare `tenant_id` + `id` with no `entity_
  type`/`scope_id` (workspace) constraint - the lifecycle machine is a SCOPED status entity
  (`ConversationService._lifecycle_map`'s own precedent/comment: "a status id that happens to exist
  for another workspace of the same tenant must NOT resolve"). Close-reason labels had the
  matching gap (bare `tenant_id` + `id`, no `workspace_id`). Both now constrain by workspace
  (derived from the batch's own events, since `to_items` always renders ONE contact's events = one
  workspace). Existing `test_lifecycle_changed_event`/assignment-label tests in
  `tests/test_omnichannel_conversation_events.py` continue to pass unmodified (confirms no
  regression to the happy path).
- **B17 - REAL (fixed in `modules/omnichannel/services/inbox_view_service.py create`/`update`).**
  Same check-then-insert/rename race class as A1's tag service - wrapped both commits in
  try/except `IntegrityError`, translating to `InboxViewValidationError` (the A1 tags precedent).
  Test: `test_inbox_view_create_race_is_422_not_500`.
- **B18 - REAL (fixed in `inbox_view_service.py _validate_filter_ids` + `expand()` +
  `routers/conversations.py`).** `InboxViewFilter.segmentId` was accepted at save time and
  silently discarded on expansion. Save now rejects any non-null `segmentId` with the SAME message
  the query-param path uses ("Contact segments are not available yet."); `expand()` re-checks it
  as defense-in-depth for a pre-guard-era or planted row, raising the same error, mapped to 422 by
  the router. Tests: `test_inbox_view_segment_id_rejected_at_create`,
  `test_inbox_view_segment_id_rejected_at_expansion`.
- **B19 - REAL (fixed in `modules/omnichannel/services/lifecycle_service.py move` +
  `ConversationService.move_lifecycle` + the router).** The `lifecycle_changed` event's actor was
  the EFFECTIVE user (needed for `status_machine.transition`'s own authorization, B5's prior fix)
  instead of the REAL admin for attribution. `move()` gained an `attributed_actor_id` param
  (defaults to `actor.id` when omitted, so `patch_thread`'s lifecycle branch - where `actor` is
  ALREADY the real actor - is unaffected); the router's `move_lifecycle` route now passes
  `principal.actor_user_id` explicitly. Test:
  `test_move_lifecycle_impersonation_attributes_event_to_real_admin`
  (`tests/test_omnichannel_contact_data_model.py`), mutation-verified.
- **B20 - REAL (fixed in `modules/omnichannel/services/message_service.py _mark_agent_message`).**
  The `is_first_reply_pending` SELECT then `event_service.record(..., "first_agent_reply", ...)`
  INSERT is a check-then-write race under concurrent sends for the same contact. Added a
  Postgres-only `SELECT ... FOR UPDATE` row lock on the contact before the check (dialect-guarded,
  no-op on the SQLite test engine - the same pattern `serialization.touch_run_heartbeat` already
  uses). **Not independently pytest-verified**: the test suite runs on SQLite (single connection,
  no real row-locking, no threads), so the guard's SQL branch is untested by `pytest`; the existing
  sequential `test_first_agent_reply_once_per_open_cycle` still passes unmodified (no regression
  to normal, non-concurrent behavior). Live-probed at the dialect-check level, not with genuine
  concurrent traffic (out of scope for a `curl` probe) - flagged as unverified below.

**Frontend**

- **F1 - REAL (fixed in `inbox-rail-entries.ts railSelectionPatch`).** Leaving a saved view for
  All/Mine/Unassigned/a lifecycle stage cleared `lifecycleStageIds` but not `tagIds`/`channelIds` -
  both are VIEW-ONLY dimensions (no filter-bar control for either), so a stale narrowing kept
  silently applying with no UI left to show or clear it. Both cases now clear all three. Tests in
  `inbox-rail-entries.test.ts`.
- **F2 - REAL (fixed, interacting with round 2's fix as flagged).** Added `ConversationFilters.
  statusExplicit` (true ONLY on a genuine filter-bar pick); `expandViewFilter` always sets it
  `false` (a multi-status view's `ALL` collapse is never mistaken for a user override);
  `threadQueryString` sends `status` while a view is active ONLY when `statusExplicit` is true,
  otherwise omits it so the server applies the view's real (possibly multi-status) filter.
  Round-2's single-status/explicit-All cases still pass (updated to set `statusExplicit: true`,
  matching a genuine bar pick); new case covers the multi-status-collapse-not-explicit path.
- **F3 - REAL (fixed in `inbox-view-rail.tsx deleteView` - the SAFEST of the brief's two options).**
  `useDeferredAction`'s `parkedRef` is one-per-hook-instance; `start()` overwrites it wholesale, so
  round 2's settle-then-overwrite silently stopped polling/refreshing/toasting for the FIRST
  delete once a second one started (server-side it still resolved, but the UI never learned it
  did). Chose "refuse a second start while one is parked" over "track parks per row" - zero change
  to the shared engine hook's contract. A second delete on a DIFFERENT view now shows "Finish
  deleting "X" first." and does not touch the first; a double-click on the SAME view is a no-op.
  Test (replaces the round-2 "settles the first toast" test, which asserted the now-superseded
  behavior): `refuses a second delete while the first is still counting down`.
- **F4 - REAL (fixed in `use-inbox-rail-selection.ts`).** `restoredRef` was "done" for the hook's
  whole lifetime - a workspace switch (same mounted rail, new stages/views) never re-attempted
  `?view=` restoration. Added a `restoredForWorkspaceRef` tracking which workspace was last
  restored FOR, resetting the guard on change. An unknown/stale rail key (lifecycle or view) now
  normalizes to All in BOTH the URL and the filter state, instead of a silent no-op that strands
  the address bar on a dead key. New dedicated `use-inbox-rail-selection.test.ts` (4 cases,
  mutation-verified for the workspace-switch case).
- **F5 - REAL (fixed in `inbox/page.tsx`).** The mobile "Back to conversations" control PUSHED a
  fresh no-thread history entry (the same code path as opening a thread): `[list] -> [thread] ->
  [list, via this button]` left the device's native Back one tap short of leaving the inbox (it
  would land back on `[thread]`, reopening the very conversation just backed out of). An
  `openedViaClickRef` now tracks whether the open thread was reached by an in-app click (a real
  poppable entry exists) - Back calls `history.back()` for that case, `replaceState` for a
  deep-linked thread (no prior list entry to pop to). Two new tests in `page.test.tsx`, both
  asserting on `history.back`/`pushState`/`replaceState` spies (not jsdom navigation state, which
  doesn't model this distinction well).
- **F6 - REAL (fixed in `workspace-close-reasons-tab.tsx onSetActive`).** `void update(...)`
  discarded a Deactivate/Activate rejection - `update()` re-throws (no internal catch) and the
  Resource shell's `ActionMenu` awaits a non-deferred action's `run` with no catch of its own
  either (every OTHER action self-handles its errors). Wrapped in try/catch + `toast.error`. New
  `workspace-close-reasons-tab.test.tsx` (2 cases, mutation-verified).
- **F7 - REAL (fixed in `activity-feed.tsx`).** `.sort((a,b) => a.createdAt.localeCompare(...))` is
  a lexicographic string sort - Python's `isoformat()` drops the fractional part entirely at
  exactly-zero microseconds, so `"...:00Z"` vs `"...:00.500000Z"` compares '.' (0x2E) against 'Z'
  (0x5A) and sorts the LATER (.5s) timestamp FIRST. Switched to numeric epoch via `lib/datetime.ts
  parseUtc(...).getTime()` (unparsable sorts last, never throws). New regression case + mutation-
  verified.
- **F8 - REAL (fixed in `conversation-drawer.tsx`).** `void setStatus('OPEN').then(reloadEvents)`
  discarded a Reopen rejection (`setStatus` has no internal catch, matching `CloseThreadDialog`'s
  own `onClose` which IS awaited inside a try/catch by the dialog - Reopen has no dialog wrapping
  it). Extracted a `reopenThread` callback with try/catch + `toast.error`. New test in
  `conversation-drawer.test.tsx`, mutation-verified (also fixed one pre-existing new-test-only tsc
  error: `toast.error`'s mock needs a truthy return, not `void`).
- **F9 - REAL (fixed in `shortcut-menu.tsx`).** `useShortcuts(contactId)` fetched unconditionally
  BEFORE the `can('conversations.shortcut')` gate below it - every agent without the permission
  fired a guaranteed-403 request on every conversation opened. `useShortcuts` already treats a
  null contact as "nothing to fetch" - now called with `hasPermission ? contactId : null`. Updated
  the existing "renders nothing without the permission" test to assert `listShortcuts` is NEVER
  called (previously asserted the opposite - the old buggy behavior).
- **F10 - REAL (fixed in `hooks/use-conversations.ts`).** Every view-rail filter dimension
  (`lifecycleStageIds`/`tagIds`/`channelIds`/`viewId`) is scoped to the PREVIOUS workspace; a
  switch never reset them, so the new workspace's request carried the old one's ids - a stale
  `viewId` 404s outright (the router's cross-workspace guard) and a stale tag/channel id now 422s
  under B11's new validation. Reset happens DURING RENDER (the sanctioned "derived state from a
  changed prop" pattern) so `load()`'s effect never fires with the stale combination even
  transiently; `rawThreads` is cleared the same way so a slow/broken new fetch never leaves the
  OLD workspace's rows looking current. New `hooks/use-conversations.test.ts` (2 cases, both
  mutation-verified).
- **F11 - REAL (fixed in `hooks/use-messages.ts`).** `addNote`/`send`/`sendTemplate`/`sendMedia`/
  `runStructured` (interactive/location/contacts)/`react` all called `setMessages(...)`
  unconditionally after their `await` - a note/message/reaction started for contact A that
  resolves after the user switched to contact B could append into B's (already reloaded) message
  list. Added `guardMessagesUpdate` (the SAME `activeContactIdRef` staleness check
  `commitThreadIfActive` already uses for thread-level fields) and applied it to every one of
  those six functions' post-await `setMessages` calls. Test:
  `F11: a slow addNote for the PREVIOUS contact does not land in the newly selected contact's
  messages`, mutation-verified.
- **F12 - REAL (fixed, same file, the initial-load effect).** The `Promise.all([getThread,
  listMessages])` `.then()` did `setMessages(msgs)` - a blind overwrite. A WS `message.created` for
  the SAME (new) contact can land while this fetch is still in flight, because the socket
  subscription is keyed on `thread?.workspaceId`, which stays live across a same-workspace contact
  switch (the OLD contact's thread object persists until the NEW one's `Promise.all` resolves) -
  `onEvent` is already re-scoped to the new `contactId` by then and appends the live message, which
  the blind overwrite then silently dropped. Two changes made this safe: (1) `setMessages([])` now
  runs SYNCHRONOUSLY when `contactId` changes (previously only on a falsy id), so `messages` is
  scoped to ONLY the new contactId for the whole duration of its own fetch; (2) the `.then()` now
  merges the REST snapshot with any ids not already in it (`prev` filtered against `msgs`'s id set)
  instead of overwriting. Test: `F12: a WS message landing during the initial fetch is merged, not
  dropped` - required a REAL wait for the mock's ~150ms `getThread` delay (an initial `waitFor` on
  `thread?.id` was a false signal, since `onEvent`'s OWN `message.created` handler also calls
  `setThread`, independent of the fetch's own `.then()`); mutation-verified.

### Suite counts

```
Backend targeted (before round 3): 161 passed (test_omnichannel_inbox_views/conversation_events/
deferred_actions/shortcuts, test_workflow_shortcuts, test_workflow_triggers, test_module_platform)
Backend targeted (after round 3):  277 passed (adds the new B1/B2/B4/B9/B10/B11/B14/B17/B18/B19
cases across test_workflow_shortcuts.py, test_omnichannel_deferred_actions.py,
test_omnichannel_inbox_views.py, test_omnichannel_contact_data_model.py)
Backend full suite (before round 3, per round-2's own report): 2934 passed, 1 skipped, 18 deselected
Backend full suite (after round 3): 2951 passed, 1 skipped, 18 deselected (1603.70s) - zero failures,
zero regressions

Frontend (before round 3): 268 files, 2045 passed
Frontend (after round 3):  271 files, 2063 passed - zero failures, zero regressions
```

`npx eslint` on every file touched this round: 0 errors. `npx tsc --noEmit`: one NEW error
introduced by this round's own test file (`conversation-drawer.test.tsx` - a `toast.error` mock
needed a non-`void` return type), fixed; every other `tsc --noEmit` error in the repo is
pre-existing and untouched by this round's diff (verified by `git status` - none of those files
appear in this round's changeset). `grep` for em/en dashes across every changed file: clean.

### Live probes (backend `:8006`, real `curl` against `demo@example.com`)

- `GET /omnichannel/contacts?assignee=user` (no `assigneeUserIds`) -> **422**
  `{"detail":"assigneeUserIds is required when assignee=user."}`.
- `GET /omnichannel/contacts?tagIds=not-a-real-tag` -> **422**
  `{"detail":"tagIds contains an unknown id."}`.
- `POST /omnichannel/workspaces/{id}/inbox-views` with `filter.segmentId` set -> **422**
  `{"detail":{"fieldErrors":{"filter":"Contact segments are not available yet."}}}`.
- `POST /omnichannel/contacts/{id}/shortcuts/{unknown-workflow-id}` -> **404**
  `{"detail":"Shortcut not found"}` (the uniform-404 contract holds end to end; the specific
  "entity without `supports_shortcut`" branch inside `run_shortcut` has no separate public route to
  probe live - the SAME endpoint is hardcoded to `omnichannel_contact`, which DOES opt in - so B1's
  registry-level guard is covered by its own pytest unit tests against `WorkflowService.
  run_shortcut` directly, not this live probe).
- Impersonated `assignee=me`: **not independently live-probed** - creating a fresh target user via
  the live API left it in `INVITED` status (a `PATCH .../status=ACTIVE` did not flip it, and
  `ImpersonationService.start` refuses an inactive target), so the HTTP round-trip could not be
  completed in this session; B12/B19 are instead verified by `pytest` tests that construct a real
  `ImpersonationSession` row (`/impersonation/start`) end to end through the SAME
  `get_conversation_principal`/`resolve_effective_actor` code path the live route uses, both
  mutation-verified (reverting either fix makes its test fail). Probe artifacts (`Probe B12 Agent
  <ts>` role, two `probe-b12*@example.com` users) were soft-trashed after the session; the
  temporary assignment on `cnt-001` was reverted.

### Anything unverified

- **B20** (message-service row lock) has no pytest coverage of the actual concurrent-write path
  (SQLite test engine, single connection) and was not live-probed with genuine concurrent traffic
  (would need two simultaneous real sends against the same contact, out of scope for a `curl`
  session) - the dialect-guard code path itself is exercised (falls through as a no-op on SQLite,
  confirmed by the unmodified sequential test still passing) but the actual lock's race-prevention
  is unverified end-to-end.
- **Impersonated `assignee=me` live HTTP round-trip** - see the live-probes note above; covered by
  pytest instead.

### Backlog (source: this plan, round 3 - not written to `documentation/backlogs/backlog.md`)

- **BL-SS-077** - `modules/omnichannel/bootstrap.py seed_demo_conversations` hardcodes global
  literal ids (`cnt-001..005`, `tpl-001..003`, `chn-demo`) that collide (a PK clash for contacts/
  templates, a cross-tenant CHANNEL reuse for `chn-demo` specifically) if the function is ever
  called for a second tenant. Today both call sites (`scripts/bootstrap_db.py`,
  `scripts/init_db.py`) always pass `DEFAULT_TENANT_ID`, so this is dormant - low priority, dev-only
  seed tooling, not customer-facing. Fix = per-tenant-unique ids (or a tenant-suffixed id scheme)
  the day this seed is ever wired to a second demo tenant.
