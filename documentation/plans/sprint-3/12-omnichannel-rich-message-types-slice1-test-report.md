# Test Execution Report - Plan 12 Slice 1 (Omnichannel Rich Message Types · Media core)

**Branch:** `sprint-3/12-omnichannel-rich-message-types`
**Date:** 2026-07-07
**Scope:** Slice 1 UAC ids - AC-12-01…12, AC-12-25, AC-12-26, AC-12-27. (AC-12-23 settings-page UI and AC-12-28 live E2E are Slice 3 → DEFERRED, not FAIL.)
**Suites run (clean):**
- Backend `python -m pytest -q` → **935 passed** (558.9s); rich-messages file alone → **18 passed** (14 pre-existing + 4 added).
- Frontend `npm test` (vitest) → **650 passed**; rich-messages file → **9 passed** (8 pre-existing + 1 added).
- `npx tsc --noEmit` → **0 errors** (after the defect fix below; was **2 errors** as committed).
- `npx eslint` on all changed files → **0 problems**.

---

## Summary

| Result | Count | AC ids |
|---|---|---|
| PASS | 15 | AC-12-01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 25, 26, 27 |
| FAIL | 0 | - |
| DEFERRED | 2 | AC-12-23 (Slice 3 settings UI), AC-12-28 (Slice 3 live E2E) |

**1 real defect found and fixed** (build-breaking type error in the committed test - see Defects).
**3 coverage gaps filled** (AC-12-26 WS publish, AC-12-11 webhook envelope, AC-12-08 canned replies) - all were claimed done but had **no test**.

---

## Defects

### D1 - Committed frontend test breaks `tsc` / `npm run build` (FIXED)
- **Severity:** Medium (build-red; unit suite is green because vitest/esbuild ignores types).
- **File:** `service_frontend/components/platform/conversation-drawer/rich-messages.test.tsx` (new on this branch).
- **Repro (as committed):** `cd service_frontend && npx tsc --noEmit` → exit 1:
  ```
  rich-messages.test.tsx(82,19): error TS2352: Conversion of type 'undefined' to type 'SendMediaInput' …
  rich-messages.test.tsx(82,45): error TS2493: Tuple type '[]' of length '0' has no element at index '0'.
  ```
  `next.config` sets no `typescript.ignoreBuildErrors`, and `tsconfig.json` `include` is `**/*.tsx` (tests are NOT excluded) → `npm run build` type-checks this file and fails. Lint/tsc is the documented prod-build gate (CLAUDE.md).
- **Root cause:** `onSendMedia.mock.calls[0][0]` - the mock `vi.fn(async () => true)` has no param type, so `mock.calls` is `[][]` (empty tuple) and indexing `[0][0]` is a compile error.
- **Fix (applied, test-only):** cast through `unknown`:
  `const call0 = (onSendMedia.mock.calls[0] as unknown as [SendMediaInput])[0];`
- **Kick-back note:** no application code changed; this is a test defect. Worth a reviewer note that the branch as originally committed would have failed CI `npm run build`.

---

## Coverage gaps filled (tests added by the tester)

| AC | Gap (before) | Test(s) added |
|---|---|---|
| AC-12-26 | No test asserted any `realtime.publish` on any mutation path. | `test_ws_publish_on_outbound_send` (created + status=SENT, workspace-scoped), `test_ws_publish_on_failed_send` (status=FAILED), `test_inbound_status_receipt_publishes_ws` (DELIVERED receipt) - `tests/test_omnichannel_rich_messages.py`. |
| AC-12-11 | No test asserted the consumer `message.inbound` envelope fields. | `test_inbound_publishes_ws_and_webhook_media_fields` - absolute `mediaUrl` (gateway URL, not inbox-relative), `mediaMime`, `mediaSize`, `voice`. |
| AC-12-08 | Emoji covered; canned/QuickReply insertion had no test. | `inserts a picked canned quick reply into the textarea (AC-12-08)` - `rich-messages.test.tsx`. |

All added tests pass (backend rich file 14→18; frontend rich file 8→9).

---

## Per-AC results

### AC-12-01 - message model widened `[BE][T]` - **PASS**
- **Scenario:** media columns + `mediaUrl` wire property + wide enum + safe migration.
- **Steps/Expected:** send an image → row carries `media_key` (not `media_url`), `media_mime`, `media_size`; `mediaUrl` == `/omnichannel/media/{id}`. Migration `0004_omni_rich_media` (id 20 chars ≤ 32), idempotent add-column, legacy rows keep `media_url`.
- **Actual:** `test_media_send_stores_key_and_sends` green; migration + bootstrap `ADD COLUMN IF NOT EXISTS` verified in source.
- **Remarks:** `omnichannel_settings` new-deploy path = `create_all`; existing-deploy = migration 0004 - both idempotent.

### AC-12-02 - uniform upload-by-id pipeline `[BE][T]` - **PASS**
- One path: bytes → sniff → StorageService key → `adapter.upload_media` → `media_id` → `adapter.send({type,<kind>:{id,caption}})`. Gateway `url` → `_fetch_url` → `_send_media` (re-upload); the adapter has **no `link` path** at all.
- **Actual:** exercised via `test_media_send_stores_key_and_sends`, `test_gateway_media_by_url`, `send_runner.run_send`.
- **Remarks:** the gateway URL fetch itself is monkeypatched in tests (structural coverage of the fetch→reupload wiring); the re-upload is real.

### AC-12-03 - async outbound execution `[BE][T]` - **PASS**
- QUEUED row returned optimistically; eager inline task runs pipeline→SENT/FAILED + `external_message_id` + WS `message.status`.
- **Actual:** SENT via `test_media_send_stores_key_and_sends`; FAILED via `test_voice_transcode_failure_marks_failed`; WS status now asserted by the added AC-12-26 tests.

### AC-12-04 - voice transcode `[BE][T]` - **PASS**
- webm→ogg/opus via ffmpeg in the send task; failure → `FAILED` (never silent). Backend `Dockerfile` adds ffmpeg (diff confirmed).
- **Actual:** `test_voice_transcode_invoked` (transcode called once), `test_voice_transcode_failure_marks_failed`.

### AC-12-05 - blob-fetch media endpoint `[BE][T]` - **PASS**
- `GET /omnichannel/media/{id}` dual-auth (session JWT **or** `fxw_` API key), tenant/workspace-scoped, CSP `sandbox` + nosniff; no auth → 401; unknown/cross id → 404.
- **Actual:** `test_media_endpoint_session_and_apikey` (200 both paths, headers, 401, 404) + `test_media_endpoint_cross_workspace_apikey_404`.
- **Remarks:** router is `"public": true` in the manifest (auth enforced inside `_resolve_principal`); message is resolved via tenant-scoped `get_message` (never unscoped) - see AC-12-27. Minor observation: `public` bypasses `require_module`, so a tenant that later deactivated omnichannel could still fetch its own already-scoped media; low risk, not a Slice-1 blocker.

### AC-12-06 - composer attach + multi-file `[FE][T]` - **PASS**
- Attach menu (photo/video/audio/document/sticker), multi-file tray with per-file caption, each file → its own send.
- **Actual:** `shows the attach menu with all media kinds`, `previews chosen files in a multi-file tray and sends each` (2 sends, first caption applied).

### AC-12-07 - inline media rendering `[FE][T]` - **PASS**
- image→thumbnail+lightbox, voice→player, document→file card (name+size), sticker→bare img; bytes via `apiFetchBlob`→object URL (no Bearer in `<img src>`); lazy.
- **Actual:** 4 bubble tests green (image/document/voice/sticker); `useMediaBlob` fetches blob & revokes on unmount.
- **Remarks:** VIDEO/AUDIO branches render (`<video>`/`<audio>`) but aren't separately asserted - same code path as the asserted media types. Non-blocking.

### AC-12-08 - emoji picker + canned replies `[FE][T]` - **PASS** (gap filled)
- Bundled emoji picker (no CDN) inserts into textarea; QuickReply pick inserts body (editable).
- **Actual:** `inserts a bundled emoji…` + **added** canned-reply test.

### AC-12-09 - inbound media parse + voice flag `[BE][T]` - **PASS**
- Inbound image → fetched + stored (key+mime+size); `audio` with `voice==true` → stored as `VOICE`.
- **Actual:** `test_inbound_image_stored_and_voice_flag`.

### AC-12-10 - gateway media send `[BE][T]` - **PASS**
- JSON (`media:{url,…}`) and multipart (`file` + `payload`); `202 {id,status:queued}`; oversize → typed error.
- **Actual:** `test_gateway_media_multipart`, `test_gateway_media_by_url`, `test_gateway_media_oversize_typed_error` (`error.code == "oversize"`).

### AC-12-11 - webhook media fields `[BE][T]` - **PASS** (gap filled)
- `message.inbound.data.message` carries absolute API-key gateway `mediaUrl` + media metadata + `voice`, additive/back-compat.
- **Actual:** **added** `test_inbound_publishes_ws_and_webhook_media_fields`.
- **Remarks:** implementation exposes the additive fields with the **frontend camelCase contract** - `mediaMime` / `mediaFilename` / `mediaSize` (not the AC prose `mimeType` / `filename` / `size`). Data is present and back-compatible; note the field-name nuance for the EMS-ticket contract doc (AC-12-24, Slice 3).

### AC-12-12 - per-workspace caps `[BE][FE][T]` - **PASS**
- `omnichannel_settings` (workspace nullable=default); enforce `min(configured, Meta ceiling)`; mimes fixed; sniff-gate always; oversize/bad-mime rejected on inbox + gateway.
- **Actual:** `test_oversize_rejected`, `test_bad_mime_rejected`, `test_caps_clamped_to_meta_ceiling` (999,999,999 → clamped to 5 MiB IMAGE ceiling), `test_gateway_media_oversize_typed_error`.
- **Remarks:** settings endpoints gated by the existing `channels.manage` (already granted to tenant Admin) - no new-permission grant sweep needed. AC-12-23 dedicated UI is Slice 3.

### AC-12-25 - CSW window across types `[BE][T]` - **PASS**
- Window closed → media send `422` (csw closed); template-only re-engage.
- **Actual:** `test_media_blocked_when_window_closed`; gateway maps `CSW_CLOSED_MESSAGE` → `409 csw_window_closed`.
- **Remarks:** Slice-1 free-form types are text + media; interactive/location/contacts/reaction land in Slices 2/3.

### AC-12-26 - WS realtime for every mutation `[BE][T]` - **PASS** (gap filled)
- Every new message / status commit publishes to the workspace room.
- **Actual:** **added** 3 backend tests (outbound created+SENT status, FAILED status, inbound created + status receipt DELIVERED). All publishes target the contact's workspace room.

### AC-12-27 - tenant/workspace isolation `[BE][T]` - **PASS**
- Every query scoped from auth context; stored media/target id resolved scoped (never unscoped `get_by_id`).
- **Actual:** media endpoint uses tenant-scoped `get_message` + additional workspace check for API-key callers; `test_media_endpoint_cross_workspace_apikey_404` proves a foreign workspace key → 404.

### AC-12-23 - settings page `[FE][T]` - **DEFERRED** (Slice 3)
- Backend `GET/PUT /omnichannel/settings` exists and is exercised by Slice-1 tests; the workspace-admin **settings UI page** is Slice-3 scope.

### AC-12-28 - E2E rich-message journeys `[E2E]` - **DEFERRED** (Slice 3)
- Not run: live dev-cred-channel E2E is Slice 3. No live Meta/WhatsApp connection was used per brief.

---

## Notes / observations (non-blocking)
1. Media serve router `"public": true` bypasses `require_module`; message resolution is still tenant/workspace-scoped, so isolation holds - flagged only as a defense-in-depth observation.
2. AC-12-11 field naming (`mediaMime`/`mediaSize` vs AC prose) should be reflected when the EMS consumer-webhook contract doc is finalized (AC-12-24, Slice 3).
3. Gateway media-by-URL: the outbound fetch is mocked in tests; the re-upload path is real. A live fetch is only exercisable in E2E (Slice 3).

## Files changed by the tester
- `service_backend/tests/test_omnichannel_rich_messages.py` (+4 tests: AC-12-26 ×3, AC-12-11 ×1)
- `service_frontend/components/platform/conversation-drawer/rich-messages.test.tsx` (+1 canned-reply test; fixed D1 build-breaking type error)
