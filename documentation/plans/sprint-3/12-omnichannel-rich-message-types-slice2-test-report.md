# Plan 12 — Omnichannel Rich Message Types · Slice 2 Test Execution Report

**Feature:** Interactive / location / contacts / structured messages
**Branch:** `sprint-3/12-omnichannel-rich-message-types`
**Date:** 2026-07-08
**Scope:** Slice 2 UAC ids — AC-12-13…18. (AC-12-19…24/28 are Slice 3 → out of scope; AC-12-28 live E2E is the consolidated Slice-3 journey per the plan → DEFERRED, not FAIL.)

---

## Summary

| Result | Count | AC ids |
|---|---|---|
| PASS | 6 | AC-12-13, 14, 15, 16, 17, 18 |
| DEFERRED | 1 | AC-12-28 (Slice 3 live E2E) |

**Suites green after Slice 2 + reviewer fixes:**
- Backend: `test_omnichannel_rich_messages.py` + `test_omnichannel_api_gateway.py` = **58 passed** (+2 reviewer regression tests). Full omnichannel module = **145 passed**.
- Frontend: `structured-messages.test.tsx` (8) + `conversation-drawer.test.tsx` (23) + `rich-messages.test.tsx` (9) = **40 passed**. eslint clean on touched files.

---

## Reviewer round (fixed before sign-off)

The reviewer returned no blockers, 2 should-fixes + nits — all applied:

| # | Finding | Fix |
|---|---|---|
| 1 (should-fix) | Gateway interactive with a bad media-header URL raised an unhandled `MediaRejected` → **500**, undercutting AC-12-18 "malformed → 422". | `public_gateway_service._send_structured` now catches `MediaRejected` → `ApiError(422)`; interactive definition is validated **before** the SSRF header fetch. Regression test `test_gateway_interactive_bad_media_header_is_422`. |
| 2 (should-fix) | Media-header interactive stored the header blob **before** the CSW window check → orphan blob on a closed window. | `message_service.send_interactive` checks `_window_open(contact)` before sniff+store. Regression test `test_interactive_media_header_closed_window_no_orphan_blob` (asserts `storage_for_tenant` never called). |
| 4 (nit) | Contacts phone `type` passed through unvalidated (Meta rejects non-enum). | `structured.validate_contacts` whitelists `CELL/HOME/WORK/MAIN/IPHONE` (uppercased), drops others. |
| — (a11y) | `DialogContent` missing `aria-describedby` (Radix console warning). | Added `DialogDescription` to all 3 structured-composer dialogs. |

Nit #3 (reorder validate-before-fetch) resolved as part of fix #1. Nit #5 (author-side media-header preview shows a label, not the media) is intentional preview behavior — no change.

---

## Per-AC results

### AC-12-13 — interactive builder + send `[FE][BE][T]` — **PASS**
- **BE:** `POST /omnichannel/contacts/{id}/interactive` builds `type:"button"|"list"|"cta_url"|"location_request"` via `structured.build_meta_interactive`, stores `message_type=INTERACTIVE` + `payload_json`. Free-form → 24h CSW enforced.
- **Tests:** `test_send_interactive_buttons` (stores payload, SENT), `test_send_interactive_too_many_buttons_422`, `test_send_interactive_list_over_10_rows_422`, `test_send_interactive_cta_bad_url_422`, `test_send_interactive_media_header_multipart`, `test_structured_blocked_when_window_closed`, `test_build_meta_interactive_shapes`.
- **FE:** `structured-composer.tsx` builder (buttons/list/cta/location-request, text **or media** header + footer). Tests: `builds + sends reply-buttons interactive`, `renders interactive buttons preview`.

### AC-12-14 — inbound interactive reply threaded `[BE][FE][T]` — **PASS**
- **BE:** adapter maps `button_reply`/`list_reply` → `INTERACTIVE_REPLY` + `payload_json{kind,id,title,description?}`, threaded via Meta `context.id` → tenant-scoped `get_message_by_external_id` → `reply_to` metadata.
- **Tests:** `test_inbound_interactive_reply_threaded`.
- **FE:** bubble badges "chose: <title>" under the quoted original. Test: `renders inbound reply badge`.

### AC-12-15 — location send/receive/render `[BE][FE][T]` — **PASS**
- **BE:** send + inbound store `payload_json{lat,lng,name,address}`; `validate_location` range-checks; gateway `type:"location"` symmetric.
- **Tests:** `test_send_location`, `test_send_location_out_of_range_422`, `test_inbound_location_and_contacts`, `test_gateway_location`.
- **FE:** card with name/address + coords + "Open in Maps". Tests: `builds + sends a location`, `renders a location card with a maps link`.

### AC-12-16 — contact card send/receive/render `[BE][FE][T]` — **PASS**
- **BE:** `validate_contacts` normalizes friendly → WhatsApp-native `{contacts:[{name,phones}]}`; requires name + ≥1 phone; phone-type whitelisted.
- **Tests:** `test_send_contacts`, `test_send_contacts_no_phone_422`, `test_inbound_location_and_contacts`.
- **FE:** card with name · phones · `tel:` click-to-call · vCard download. Tests: `builds + sends a contact card`, `renders a contact card with tel + vCard`.

### AC-12-17 — unknown-type placeholder `[BE][T]` — **PASS**
- **BE:** adapter maps any unsupported inbound `type` → `UNSUPPORTED` (+ `original_type` logged); inbound stores a placeholder bubble, never dropped.
- **Tests:** `test_inbound_unknown_type_placeholder` (inbound `order` → `UNSUPPORTED`, 1 message stored).
- **FE:** `renders an unsupported placeholder`.

### AC-12-18 — gateway interactive/location/contacts `[BE][T]` — **PASS**
- **BE:** public gateway accepts `type ∈ {interactive,location,contacts}`, validates (buttons≤3, list≤10 rows, title/URL limits) → 202; malformed → typed 422; bad media-header bytes → 422 (reviewer fix); closed window → 409.
- **Tests:** `test_gateway_interactive_and_malformed` (202 + empty-buttons 422), `test_gateway_interactive_bad_media_header_is_422`, `test_gateway_location`, `test_unsupported_type` (reaction still `unsupported_type` — Slice 3).

### AC-12-28 — E2E rich-message journeys `[E2E]` — **DEFERRED** (Slice 3)
- Live dev-cred-channel Playwright journeys are the consolidated Slice-3 deliverable per the plan. Not run here.

---

## Hard-fail / DoD gate

- **No DB/SQL in routers** — routers delegate to `MessageService` / `PublicGatewayService`. ✅
- **No component fetch/axios** — UI → `useMessages` → `conversationService`. ✅
- **No `any`** — explicit interfaces; only narrow casts on the `payload` union. ✅
- **No raw CSS/`<style>`.** ✅
- **Module stays in `app_omnichannel`** — `payload_json` is a Slice-1 nullable column (`ADD COLUMN IF NOT EXISTS`); no core `public` mutation, no backfill gap. ✅
- **Mock swapped to real** — `conversation-service.real.ts` implements all three structured sends. ✅
- **No new permission** — reuses `conversations.reply` / `channels.manage`; no grant sweep needed. ✅
- **Security** — CTA URL handed to Meta, never server-fetched; gateway media-header fetch is SSRF-guarded (`validate_callback_url`, https-only, redirects off, capped); every repo query tenant/workspace-scoped; CSW 24h enforced on every structured send. ✅

---

## Files changed (Slice 2)

**Backend:** `services/structured.py` (new), `adapters/whatsapp_cloud.py`, `routers/conversations.py`, `schemas.py`, `services/{conversation,inbound,message,public_gateway,send_runner}_service.py`, `tests/{test_omnichannel_rich_messages,test_omnichannel_api_gateway}.py`.
**Frontend:** `conversation-drawer/{composer,conversation-drawer,message-bubble}.tsx`, `message-structured.tsx` (new), `structured-composer.tsx` (new), `structured-messages.test.tsx` (new); `hooks/use-messages.ts`; `services/conversation-service.{ts,mock,real}.ts`; `types/omnichannel.ts`.

**Verdict:** Slice 2 AC ids AC-12-13…18 **PASS**; reviewer approved after 2 should-fixes applied. Ready to merge and proceed to Slice 3 (reactions + rich templates + polish + consolidated E2E).
