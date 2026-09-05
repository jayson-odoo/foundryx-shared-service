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
