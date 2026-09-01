# Sprint 3 · Plan 12 - Omnichannel Rich Message Types (respond.io parity)

**Status:** GRILLED (2026-07-07) - design locked, ready to slice + build.
**Branch:** `sprint-3/12-omnichannel-rich-message-types`
**Type:** Feature on the omnichannel Service (continues sprint-3/04-07). Touches 3 surfaces: **inbox UI**, **public gateway** (`/api/v1/omnichannel/*`), **consumer webhook**.
**UAC:** `12-omnichannel-rich-message-types-acceptance-criteria.md` (AC-12-01…28) - the contract. Build to it.

---

## Headline

Today omnichannel sends only TEXT + TEMPLATE. Inbound media/interactive is parsed + stored but rendered as a bare link. This plan brings **full WhatsApp message-type parity** (respond.io-class): send + receive image/video/audio/voice/document/sticker, interactive (reply-buttons/list/CTA-URL/location-request), location, contact cards, reactions, emoji picker, canned replies, and templates with media/button headers - across the inbox, the public gateway (EMS sends), and the consumer webhook (EMS receives).

**Deferred to backlog:** WhatsApp Flows, product/catalog/carousel/OTP-authentication templates (commerce verticals), on-device message recall (no Cloud API support).

---

## Locked decisions (grill 2026-07-07)

1. **All types in one scope** - do it right from the start.
2. **Transport = uniform upload-by-id** (D-Q2). One pipeline for every outbound media source (inbox file · gateway multipart · gateway url→fetch): bytes → sniff → StorageService → Meta `/{phone}/media` → `media_id` → send. Gateway `url` is fetched + re-uploaded, never a bare Meta `link`.
3. **Model** (D-Q3): `Message` gains `media_key`/`media_mime`/`media_filename`/`media_size` + `payload_json` (`JSON(none_as_null=True)`); `mediaUrl` = wire `@property` from the key (no stored URL - presigned expires). Wide `message_type` enum. Reactions = own table.
4. **Reactions** (D-Q4): `message_reactions` table (`UNIQUE(target_message_id, reactor)`), upsert/delete keyed to target wamid; aggregate-render as chips; new `message.reaction` event on WS + consumer webhook.
5. **Interactive** (D-Q5): reply-buttons/list/CTA-URL/location-request, text **or media** header + footer; inbound reply threaded via Meta `context.id`. Flows deferred.
6. **Composer** (D-Q6): attach menu, multi-file preview + per-file caption, **bundled** emoji picker (no CDN), voice record → **ffmpeg** transcode webm→ogg, canned replies.
7. **Rendering** (D-Q7): all inline (image lightbox, video/audio/voice players, doc card, sticker img, interactive visual, reply badge, location coords-card + Maps link, contact card with `tel:`/vCard, reaction chips).
8. **Media serving** (D-Q8): ONE endpoint `GET /omnichannel/media/{messageId}` - auth via session JWT (browser **blob-fetch**, forms BL-092 pattern) OR workspace API key (EMS). No signed URLs.
9. **Execution** (D-Q10): ALL outbound async via one Celery task (omni queue) - optimistic bubble, `QUEUED→SENT/FAILED`, WS status. ffmpeg added to the backend image.
10. **Gateway** (D-Q9): full symmetric send schema; media as JSON-url OR multipart; reaction targets **our durable id**; native location/contacts shapes.
11. **Caps** (D-Q12): per-**workspace** `omnichannel_settings` (configurable sizes, **clamped ≤ Meta ceiling**); mimes fixed to Meta's set; sniff-gate always.
12. **Templates** (D-Q11): media + button headers at send now; commerce/carousel/OTP/Flows → backlog.

---

## Architecture per surface

### Backend (`modules/omnichannel/`)
- **Model** (`models.py`): new columns + `payload_json` + `message_reactions` table. Per-module Alembic migration (revision id ≤ 32 chars; backfill safe).
- **Adapter** (`adapters/whatsapp_cloud.py`): `upload_media(creds, phone_id, bytes, mime)→media_id`; extend `send()` for `image/video/audio/voice/document/sticker/interactive/location/contacts/reaction` + template media/button components; extend `parse_inbound` for location/contacts/reaction/voice-flag + unknown placeholder (image/video/audio/document/sticker/interactive already parsed).
- **Media pipeline** (new `services/media_pipeline.py`): the one upload-by-id path + ffmpeg voice transcode + sniff-gate (`app/uploads.detect_upload_mime`) + per-workspace cap check.
- **Send** (`services/message_service.py` + `worker.py`): send endpoints create `QUEUED` row → enqueue `omnichannel.send_message` task → task runs pipeline + `adapter.send` → status + WS. Reactions/interactive/location/contacts handled by type.
- **Media serve** (`routers/media.py`): `GET /omnichannel/media/{messageId}` dual-auth (session or API key), tenant/workspace-scoped, StorageService resolve, CSP-sandbox + nosniff.
- **Gateway** (`routers/api_v1.py` + `services/public_gateway_service.py`): accept all types (JSON + multipart); the `/media/{id}` endpoint under API-key auth; per-workspace caps.
- **Webhook** (`services/webhook_delivery.py` + `inbound_service.py`): envelope media/payload fields additive; new `message.reaction` event; `message.status` unchanged.
- **Settings**: `omnichannel_settings` (workspace PK) + `GET/PUT` gated by the manage perm.

### Frontend (`components/platform/conversation-drawer/` + inbox)
- **Composer** (`composer.tsx`): attach menu, file preview tray (multi-file + caption), emoji picker (bundled), voice recorder (MediaRecorder), canned-reply picker, interactive builder dialog, location + contact dialogs. Optimistic bubbles.
- **Bubble** (`message-bubble.tsx`): per-type inline render + reaction chips + reply/quote + interactive visual.
- **Media**: `apiFetchBlob` → object URL (lazy). Service trio extended for the new send shapes.
- **Settings page**: workspace caps editor.

### Consumer webhook contract (EMS)
- `message.inbound.data.message` += `mediaUrl` (API-key gateway URL) · `mimeType` · `filename` · `size` · `voice` · `payload` (interactive/location/contacts). New `message.reaction`. All additive/back-compat. Update the EMS ticket (`dreamz_ems …/sprint-4/10-…`).

---

## Slices

**Slice 1 - Media core.** AC-12-01…12 + 25/26/27. Model + migration, upload-by-id pipeline, async send task, ffmpeg voice, blob-fetch media endpoint, composer attach/multi-file/emoji/canned/voice, inline media render, inbound media parse (voice flag), gateway media (url+multipart), webhook media fields, per-workspace caps.

**Slice 2 - Interactive + structured.** AC-12-13…18. Interactive builder + send + inbound-reply threading + render, location + contacts send/receive/render, parse location/contacts + unknown placeholder, gateway + webhook for these.

**Slice 3 - Reactions + rich templates + polish.** AC-12-19…24 + 28. Reactions (table, send/receive, chips, WS + webhook), template media/button headers, settings page, webhook/docs finalized, E2E journeys, EMS-ticket update.

Each slice: frontend-first (mock) → backend → swap → TDD (Vitest + pytest) → Playwright E2E → reviewer approval. Validate against its UAC ids before the next slice.

---

## Security invariants
- Every query tenant+workspace-scoped from auth (JWT or API key), never client input. Stored media/target ids resolved scoped (never unscoped `get_by_id`).
- Sniff-gate all uploads (magic bytes; declared content-type ignored); capped reads (never buffer unbounded bodies); caps clamped ≤ Meta ceilings.
- Media endpoint CSP-sandbox + nosniff. No raw SQL in routers; no fetch/axios in components; no `any`.
- Credentials Fernet; API keys hashed; HMAC constant-time.

## Testing
- Backend `tests/test_omnichannel_rich_messages.py` (pipeline, upload-by-id, async task, transcode-mock, caps clamp, parse extensions, reactions upsert/delete, interactive threading, gateway all-types, media-endpoint dual-auth, isolation).
- Frontend composer + bubble Vitest (attach, multi-file, emoji, render each type, blob-fetch mock).
- E2E `e2e/omnichannel-rich-messages.spec.ts` (AC-12-28) against the dev-cred channel.
- Conftest: SQLite `schema_translate_map`; ffmpeg mocked in tests.

## Backlog (deferred here)
- BL-SS-0xx: WhatsApp Flows · product/catalog/multi-product messages · carousel templates · OTP/authentication templates · on-device recall (Cloud API gap) · location map-tile embed.

---

*This plan fulfils `12-omnichannel-rich-message-types-acceptance-criteria.md`. Build slice by slice; a slice is done only when its UAC ids pass + the DoD gate + reviewer approval.*
