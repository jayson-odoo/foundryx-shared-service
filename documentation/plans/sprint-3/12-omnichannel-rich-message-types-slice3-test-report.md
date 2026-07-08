# Plan 12 — Omnichannel Rich Message Types · Slice 3 Test Execution Report

**Feature:** Reactions + rich templates + media-caps settings + docs
**Branch:** `sprint-3/12-omnichannel-rich-message-types`
**Date:** 2026-07-08
**Scope:** Slice 3 UAC ids — AC-12-19…24 + AC-12-28.

---

## Summary

| Result | Count | AC ids |
|---|---|---|
| PASS | 6 | AC-12-19, 20, 21, 22, 23, 24 |
| PARTIAL | 1 | AC-12-28 (E2E spec written; live-stack run pending) |

**Suites green after Slice 3 + reviewer fixes:**
- Backend: full omnichannel module **164 passed** (`test_omnichannel_rich_messages` incl. reactions + templates + regression, `test_omnichannel_api_gateway`, `test_omnichannel_consumer_webhooks`, …).
- Frontend: `conversation-drawer/` **46 passed** (incl. `reactions.test.tsx` ×4, template-dialog AC-12-22 ×2); media-settings **20 passed** (`media-size`, service, hook, page). eslint clean on all touched files.

---

## Reviewer round (APPROVE — fixes applied)

No blockers / no hard-fail violations. One correctness should-fix + nits, all applied:

| # | Finding | Fix |
|---|---|---|
| 1 (should-fix) | Multi-agent reaction mirror divergence — keying AGENT reactions by `actor_user_id` kept two rows when two agents reacted, but Meta stores ONE reaction per direction (agent B overwrites agent A). Live WS collapsed to one; reload showed two → disagreement. | `message_service.react` now keys AGENT reactions by a single business identity (`AGENT_REACTOR`), so agent B replaces agent A's row — mirror matches Meta. Regression test `test_agent_react_single_business_identity`. |
| 3 (nit) | React endpoint ignored the `contact_id` path segment. | `react(expected_contact_id=…)` → 404 if the message isn't on that thread (defence in depth). |
| 4 (nit) | No emoji length cap. | `MAX_EMOJI_LEN=32` guard on the agent path; inbound clamps to 32 chars. |

Nit #2 (FE `reactor` field holds the reactor type) is cosmetic — chips don't render `reactor`; left as-is.

---

## Per-AC results

### AC-12-19 — reactions send/receive `[BE][T]` — **PASS**
- `message_reactions` table (`UNIQUE(target_message_id, reactor)`) + migration `0005_omni_reactions`. Inbound reaction upserts (emoji) / deletes (empty), keyed target-wamid → our message; unknown target dropped + logged; **never a message bubble** (adapter `parse_inbound` reroutes the `reaction` type before the bubble path). Agent react sends via the adapter + upserts.
- **Tests:** `test_inbound_reaction_upserts_never_a_bubble`, `test_inbound_reaction_unknown_target_dropped`, `test_agent_react_endpoint_and_wire`, `test_agent_react_single_business_identity`, `test_agent_react_closed_window_409_via_422`.

### AC-12-20 — reaction propagation `[BE][FE][T]` — **PASS**
- `message.reaction` published on WS + fanned to the consumer webhook (`data{targetMessageId,reactorType,emoji,removed}`; added to `webhook_service.EVENT_TYPES` + the FE subscription dialog `WEBHOOK_EVENT_OPTIONS`). Target bubble renders emoji chips (aggregated + counted); quick-react palette + remove control in the bubble context menu; WS handler live-updates chips.
- **Tests:** `test_reaction_ws_publish`, `test_reaction_forwards_to_consumer`; FE `reactions.test.tsx` (chips render/count, no-chips, fires onReact, remove control).

### AC-12-21 — reaction targets our durable id `[BE][T]` — **PASS**
- Gateway `type:"reaction"` (`{messageId:<our durable id>, emoji}`) resolves our id → target → sends; workspace-scoped (a key can't react on — or probe — another workspace's message). EMS never handles raw wamids.
- **Tests:** `test_gateway_reaction_durable_id`, `test_gateway_reaction_cross_workspace_404`.

### AC-12-22 — template media/button headers at send `[BE][FE][T]` — **PASS**
- New `POST /{contact_id}/template` (JSON or multipart). `template_send.py` (`analyze_template`/`validate_template_params`/`build_send_components`/`inject_header_media_id`) fills header (TEXT var or image/video/document media), body, and dynamic URL-button variables. Header media rides the upload-by-id pipeline (sniff-gated, `send_runner` injects the id). Header/body/button count mismatch → typed 422. `TemplateItem` exposes `headerFormat`/`headerVariableCount`/`buttonVariableCount`; the composer dialog renders only the inputs a template needs.
- **Tests:** analyze matrix, build/inject unit, list metadata, TEXT-header+body+button components, media-header storage, missing-file 422, 3-way count-mismatch 422, back-compat via `/messages`; FE 2 dialog tests.

### AC-12-23 — settings page `[FE][T]` — **PASS**
- `/omnichannel/settings/media` over the existing `GET/PUT /omnichannel/settings` (gated `channels.manage`). One card per media type (MB input, ceiling hint, read-only accepted mimes); blank = Meta default; client clamp + backend clamp. Menu entry added to both omnichannel menu arrays. Wired to the REAL service.
- **Tests:** 20 (byte↔MB helpers, service, hook, page form).

### AC-12-24 — consumer webhook + docs finalized `[BE][FE]` — **PASS**
- Standalone contract doc `12-omnichannel-consumer-webhook-contract.md` lists `message.inbound` (media+payload), `message.status`, `contact.updated`, `message.reaction`. Backlog carries the deferred set (BL-SS-010..013) + a cross-repo EMS-ticket handoff (BL-SS-015 — `dreamz_ems` can't be edited from this repo).

### AC-12-28 — E2E rich-message journeys `[E2E]` — **PARTIAL**
- Spec written: `e2e/omnichannel-rich.spec.ts` (real-click reaction add/remove chips + media-caps settings page), driving the seeded demo inbox. Inbound-simulation journeys (receive image / button reply / contact reaction) require POSTing a Meta webhook to the receiver and are documented for a follow-up API-driven run. **Live-stack run pending** (backend :8001 + built frontend :3001 + `seed_demo_conversations`); recorded here per the plan's E2E-consolidation note.

---

## Hard-fail / DoD gate
- No DB/SQL in routers; no component fetch/axios (settings → hook → service; reactions/templates → `useMessages`). ✅
- No `any`; explicit interfaces (`MessageReaction`, `SendTemplateInput`, `OmnichannelSettings`, `ReactionResult`). ✅
- No raw CSS/`<style>`; module stays in `app_omnichannel`. ✅
- **New table `message_reactions`** has migration `0005` (id ≤32 chars) + `create_all` for tests; a new table needs no row backfill. ✅
- Mock swapped to real (settings page + `sendTemplate`/`react` on `.real`). ✅
- No new permission — reactions/templates reuse `conversations.reply`, settings reuse `channels.manage`; no grant sweep. ✅
- Security: every reaction/template query tenant-scoped; gateway reaction workspace-scoped (404 cross-workspace); template header media sniff-gated; reactions gate on the 24h CSW window; parity FE↔BE (`message.reaction` event, `reactions` field). ✅

**Verdict:** Slice 3 AC-12-19…24 **PASS**; AC-12-28 spec written (live run pending). Reviewer APPROVED after the multi-agent-reaction fix. Plan 12 is feature-complete across all 3 slices.
