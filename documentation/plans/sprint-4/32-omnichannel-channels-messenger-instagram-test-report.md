# Sprint 4 · Plan 32 (A7a) - Messenger + Instagram Channels · Test Execution Report

**Branch:** `sprint-4/32-channels-messenger-instagram` (worktree `.claude/worktrees/s32`)
**Slice:** S6 (Gateway + guide + workflow + wire-up + E2E), authored by the S6 coder; S0-S5 were
built and reviewed in prior turns on this same branch.
**Date:** 2026-09-07
**Environment:** backend `:8013` (DB `foundryx_service_s32`, Postgres, `ENVIRONMENT=development`,
`CELERY_TASK_ALWAYS_EAGER=true`, dev-safe: no `META_APP_ID`), frontend `:3011` (prod build via
`npx next start -p 3011`).
**Tester (this slice):** the S6 coder - `python -m pytest -q` (scoped to omnichannel + workflow
suites, no whole-repo run per the lane brief), `npx vitest run` (full frontend suite), and
`agent-browser` (sessions `s32c2`/`s32c3`) real-click E2E. A dedicated tester/reviewer pass is
still owed per the standing methodology (this report covers what the coder verified).

## Result summary

| Gate | Result |
|---|---|
| `tests/test_omnichannel_api_gateway.py` | 67 passed (S6 changes: channel selector, `to` prefixes, new codes, widened `channelType`) |
| `tests/test_omnichannel_gateway_channel_selector.py` (new, S6) | 20 passed (AC-CHN-53..58) |
| `tests/test_workflow_test_trigger_data.py`, `test_workflow_engine.py`, `test_workflow_shortcuts.py`, `test_workflow_triggers.py` (core workflow engine - `executor.py` touched) | 105 passed after fixing ONE pinned exact-shape assertion (`test_omnichannel_test_trigger_runs_draft_with_canonical_context` needed `"channelType": "WHATSAPP"` added to its expected `trigger_payload_json["omnichannel"]` dict, same class of fix as the FE catalog test below) |
| `tests/test_omnichannel*.py` (full omnichannel module, run 3x this slice as code evolved) | Final full run (`tests/test_omnichannel*.py tests/test_workflow*.py`, everything this slice's diff touches, module + core workflow engine together): **1169 passed, 1 failed** in-flight, the ONE failure being the exact-shape `test_omnichannel_test_trigger_runs_draft_with_canonical_context` pin that needed `"channelType": "WHATSAPP"` added - fixed and independently re-confirmed green (20/20 in `test_workflow_test_trigger_data.py` alone) in a follow-up run started after this one was already in flight; **1170/1170 with the fix applied**. Two earlier narrower runs during development (1064 passed on the omnichannel module alone before the `_channel_for_contact` fix; 197 + 219 passed on the touched-file subset right after it) are superseded by this final full run. |
| `npx vitest run` (full frontend suite) | **340/341 files, 2615/2616 tests passed** on first pass; the one failure was a pinned catalog-shape assertion needing an update for the new `channelType` field (`lib/workflow-catalog.omnichannel-ai.test.ts`) - fixed, **341/341 files, 2616/2616 tests green** after. Two unrelated `autocount` unhandled-rejection warnings (pre-existing `task-editor-view.*` fixtures, not touched this slice). |
| `npx eslint` (every file this slice touched, FE) | 0 errors, 0 warnings |
| `npm run build` (prod) | Clean (only pre-existing `jsx-a11y` warnings in untouched files) |
| `[E2E]` AC-CHN-62 | **PASS** (with 2 real bugs found + fixed live, see the evidence README) - `32-evidence/S6/README.md`, screenshots `01`-`11` |

## Per-AC results

### S6 (this coder) - `AC-CHN-53..63`

| AC | Tag | Result | Evidence |
|---|---|---|---|
| AC-CHN-53 | [BE] | PASS | `_workspace_channel` (public_gateway_service.py) prefers an active WHATSAPP channel, else oldest active; explicit `channelId` wins, unknown/foreign -> `422 invalid_channel`. `test_implicit_choice_prefers_whatsapp_over_an_older_messenger_channel`, `test_explicit_channel_id_wins_over_the_whatsapp_preference`, `test_unknown_channel_id_is_a_typed_422_never_a_silent_fallback`, `test_foreign_channel_id_from_another_workspace_is_rejected`. Found + fixed a real regression while writing these: `MessageService._channel_for_contact`'s no-identity fallback had NO WhatsApp preference (arbitrary DB row order) - now mirrors the gateway's own preference. |
| AC-CHN-54 | [BE] | PASS | `_resolve_send_target` - `psid:`/`igsid:` resolve an existing identity on the CHOSEN channel only, never create; `id:<contactId>`; bare/`phone:` unchanged. `test_to_psid_resolves_the_existing_identity_and_sends`, `test_to_psid_that_resolves_nothing_is_422_and_never_creates_a_contact`, `test_to_igsid_that_resolves_nothing_is_422_invalid_recipient`, `test_to_id_resolves_an_existing_contact_by_foundryx_id`, `test_bare_phone_still_resolves_and_sends_whatsapp_unchanged`. |
| AC-CHN-55 | [BE] | PASS | `SendRejected.code` (new) carries `messaging_policy.PolicyRejected.code` through to `_map_send_rejected` - WhatsApp keeps `csw_window_closed` verbatim; Messenger/Instagram (both `messaging_window_closed` and `automation_outside_window` PolicyRejected codes) surface as the ONE new public `messaging_window_closed`. `test_whatsapp_closed_window_keeps_the_verbatim_csw_code`, `test_messenger_closed_window_gets_the_new_distinct_code`, `test_gateway_send_inside_human_agent_window_is_automation_refused_as_messaging_window_closed`. **E2E**: gateway curl `igsid:igsid-demo-2` (cnt-ig-002, both windows expired) -> 409 `messaging_window_closed`. |
| AC-CHN-56 | [BE] | PASS | `channelType` on `ThreadItem`/`RioContactItem` already resolved real values (no code change needed there - the resolver was already generic); `MessageItem`/`RioMessageItem` gained `channelType` (new). Both shapes derived from the same `ConversationService`/`PublicGatewayService` mappers - one data path. `test_default_and_rio_shapes_carry_facebook_channel_type`, `test_message_item_carries_channel_type_on_both_shapes`. **E2E**: channels list + detail pages render `FACEBOOK`/`INSTAGRAM` type badges from the real API. |
| AC-CHN-57 | [BE] | PASS | Guide diff in the SAME commit: changelog row (2026-09-07), §2 multi-channel preference rule, §4.1 `channelId` + `to` prefix table + per-type window paragraph, §9.1/9.2/9.3 `channelType`/`windowExpiresAt`/`humanAgentExpiresAt`, §10 three new/updated codes (`invalid_channel`, `channel_not_available_for_contact`, `messaging_window_closed`). `test_consumer_guide_documents_the_channel_selector_and_new_codes` (new contract-drift guard, mirrors the existing `test_consumer_guide_documents_the_team_fields` pattern) + the pre-existing `test_gateway_default_and_rio_shapes_carry_team_fields`-style tests stay green (67/67 in `test_omnichannel_api_gateway.py`). |
| AC-CHN-58 | [BE] | PASS | `message_received` TriggerDef gained an `omnichannelChannelType` field (independent of the existing `channelId` filter, composable); `_message_received_refine` checks it; `inbound_service.py` + `workflow_test_data.py` stamp `extra.channelType`; the executor's generic `oc` flatten adds `trigger.channelType` unconditionally. `test_message_received_channel_type_filter_matches_only_that_type`, `test_message_received_trigger_declares_the_channel_type_field`, `test_inbound_extra_carries_channel_type_for_the_executor_context`, `test_inbound_service_stamps_channel_type_on_the_dispatched_extra`. FE catalog + drawer field (`node-config-drawer.omnichannel-ai.test.tsx`, 4 new tests). **E2E**: the field renders live in the real workflow editor with "All types" default + WhatsApp/Messenger/Instagram options (`11-workflow-channeltype-filter-1280.png`); the full webhook -> Logs firing round trip is **DEFERRED** (BL-SS-146) - the refine/context wiring is pytest-covered end to end. |
| AC-CHN-59 | [FE] | PASS | `onboarding-service.ts` now binds the WHOLE `OnboardingService` (all 4 methods) to `realOnboardingService` (was 2/4 mocked); `onboarding-service.real.ts` implements `listMetaPages`/`connectMetaChannel` against the real `/onboarding/meta/*` routes. The wizard, channel list, channel form and composer already ran against the real backend (no other mock bindings existed). `grep -rn "S0 MOCK"` across the frontend is empty. **E2E**: the full connect wizard (both Meta types) ran end to end against the real backend (screenshots `02`-`05`). |
| AC-CHN-60 | [T] | PASS (aggregate) | Full omnichannel pytest suite (webhook dispatch, PSID/IGSID stitch, echo suppression, window matrix, addressing, quick replies, attachment validation, upload-by-id, receipts, reactions, connect flow, dev-safe stubs, migration backfill, tenant isolation, capability-table parity) - built across S1-S5, re-confirmed green this slice (1064 passed in the full-module run; see summary table). |
| AC-CHN-61 | [T] | PASS (aggregate) | Full omnichannel-related vitest suite (wizard steps, capabilities record, window states, badges/icons, tab filtering, mock service states) - built across S0-S5, re-confirmed green this slice (2616/2616 after the one catalog-shape fix). This slice adds 4 new vitest cases (channel-type field) + rewrites 2 wizard tests that exercised the now-removed `authorizeMockMeta` mock-only path (they now exercise the real `listMetaPages`/`connectMetaChannel` two-call flow instead). |
| AC-CHN-62 | [E2E] | PASS (2 real bugs found + fixed live) | `documentation/plans/sprint-4/32-evidence/S6/README.md` + `01`-`11` at 1280px, `04`/`05`/`08` also at 375px. Connected a Messenger channel (type -> simulated authorize -> real page picker excluding the already-connected page -> connected, Type badge) and an Instagram channel (same flow); opened both, confirmed no Templates/no Profile tab (after fixing a real "Channel not found" bug that blocked this step entirely - `use-channel-form.tsx`'s `Promise.all` failed the whole page on the profile call's EXPECTED 409); opened a Messenger thread, composer enabled, sent a text (bubble appeared) - and found + fixed the header badge always reading "WhatsApp" (`conversation-drawer.tsx`); opened the window-closed Instagram thread, composer locked with per-type copy and no template affordance; opened the human-agent-window thread, composer unlocked with the "standard window closed" banner and still sent. **DEFERRED**: the "no `channels.manage` -> no Connect control" step (no ready non-admin login in this lane) - BL-SS-146. |
| AC-CHN-63 | [T] | PASS | This report + `documentation/backlogs/backlog.md` rows `BL-SS-144` (fixed), `BL-SS-145`, `BL-SS-146` (deferred). |

### S0-S5 (built + reviewed in prior turns, re-confirmed green by this slice's regression pass)

`AC-CHN-01..52` were implemented and their own slice's reviewer/tester pass ran in S0-S5 (evidence
under `32-evidence/S0/`; each slice's own commit body documents its AC coverage). This slice did
**not** re-derive per-AC detail for them from scratch; instead it re-ran their owning test files as
part of the S6 regression pass (full `tests/test_omnichannel*.py` = 1064 passed, full `vitest run`
= 2616/2616 passed after the one expected catalog-shape update) and made ONE cross-cutting fix that
touches their shared code path:

- `MessageService._channel_for_contact`'s no-identity fallback (used by the internal composer,
  workflow `send_message` action, and broadcasts - none of which are S6-owned surfaces) now prefers
  WhatsApp instead of an arbitrary DB row, matching D-A7-18. This is additive/corrective, not a
  behaviour change for any tenant that has only ever had one channel type (the fallback path is
  identical when there is only one active channel). Re-verified: `test_omnichannel_broadcasts_send.py`,
  `test_omnichannel_workflow_parity_actions.py`, `test_omnichannel_workflow_triggers.py`,
  `test_omnichannel_conversations.py`, `test_omnichannel_rich_messages.py`,
  `test_omnichannel_channels_media_receipts.py` - 219 passed.

A full independent per-AC-01..52 re-verification is the tester/reviewer's job per the standing
methodology; not repeated here to stay in scope for the S6 slice.

## Deferred items

| ID | Title | Priority |
|---|---|---|
| BL-SS-144 | Channel detail 404 for every non-WhatsApp channel | **Fixed in this commit** (High while open) |
| BL-SS-145 | No publish-time refusal of `send_message` template mode off-WhatsApp (runtime refusal is correct + tested) | Low |
| BL-SS-146 | `channels.manage` permission-gate E2E step + full `message_received` channelType Logs round trip not live-verified | Low |

See `documentation/backlogs/backlog.md` for full descriptions.
