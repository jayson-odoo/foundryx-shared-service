# Sprint 3 · Plan 12 — Acceptance Criteria: Omnichannel Rich Message Types

Full respond.io-parity WhatsApp message support across the inbox UI, the public gateway, and the consumer webhook. Grouped by slice; each AC tagged `[BE]`/`[FE]`/`[E2E]`/`[T]`. The Test Execution Report keys back to these ids.

Grill decisions: `12-omnichannel-rich-message-types.md` §"Locked decisions".

Legend — the three surfaces every type touches: **INBOX** (composer + bubble) · **GATEWAY** (`/api/v1/omnichannel/*`, EMS send) · **WEBHOOK** (consumer envelope, EMS receive).

---

## Slice 1 — Media core (send + receive)

### AC-12-01 — message model widened [BE][T]
- **Given** the `Message` model, **when** migrated, **then** it carries `media_key`, `media_mime`, `media_filename`, `media_size`, `payload_json` (`JSON(none_as_null=True)`), and `message_type` accepts the full enum (`TEXT,IMAGE,VIDEO,AUDIO,VOICE,DOCUMENT,STICKER,INTERACTIVE,INTERACTIVE_REPLY,LOCATION,CONTACTS,REACTION,TEMPLATE`); `mediaUrl` is a wire-only `@property` built from `media_key` (no stored URL column). Migration revision id ≤ 32 chars; backfill leaves existing rows valid.

### AC-12-02 — uniform upload-by-id pipeline [BE][T]
- **Given** any outbound media source (inbox file · gateway multipart · gateway url), **when** sent, **then** the pipeline is one path: get bytes → sniff mime → store in StorageService (`media_key`) → upload to Meta `/{phone_number_id}/media` → `media_id` → `adapter.send({type,<kind>:{id,caption}})`. A gateway `url` is fetched then re-uploaded (never passed to Meta as a bare `link`).

### AC-12-03 — async outbound execution [BE][T]
- **Given** any outbound send (all types), **when** the endpoint is called, **then** it stores/creates the `Message` row `status=QUEUED` and returns immediately (optimistic); a Celery task (omni queue) does transcode/upload/`adapter.send` → updates `status` (`SENT`/`FAILED`) + `external_message_id` + publishes a WS status event. Eager dev runs it inline.

### AC-12-04 — voice transcode [BE][T]
- **Given** a browser voice recording (webm/opus), **when** sent as VOICE, **then** the send task transcodes webm→ogg/opus via **ffmpeg** and uploads it as a true WhatsApp voice note; the backend image includes ffmpeg. A transcode failure fails the message `FAILED` (never a silent no-op).

### AC-12-05 — blob-fetch media endpoint [BE][T]
- **Given** `GET /omnichannel/media/{messageId}`, **when** called with **either** a session JWT (agent) **or** a workspace API key (EMS), **then** it authorizes tenant/workspace-scoped and streams the blob (local) or presigned-redirects (S3) with `Content-Security-Policy: sandbox` + nosniff; a caller with neither auth → 401; a cross-tenant/workspace message id → 404.

### AC-12-06 — composer attach + multi-file [FE][T]
- **Given** the inbox composer, **when** the agent clicks attach, **then** a menu offers Photo/Video/Audio/Document/Sticker; picking file(s) shows a preview tray (**multi-select** → each file its own message, per-file caption); Send dispatches each. The window-closed state still locks free-form to template-only.

### AC-12-07 — inline media rendering [FE][T]
- **Given** a message of each media type, **when** rendered in the thread, **then**: image → thumbnail (click → lightbox); video → `<video>`; audio → `<audio>`; voice → voice-note player (mic + duration); document → file card (icon·name·size·download); sticker → bare webp `<img>`. All fetch bytes via blob-fetch (no `<img src>` Bearer). Media loads lazily.

### AC-12-08 — emoji picker + canned replies [FE][T]
- **Given** the composer, **when** the agent opens the emoji picker, **then** a **bundled** (no-CDN) picker inserts into the textarea; **when** they trigger canned replies (`/` or button), **then** a `QuickReply` is picked and its body inserted (editable before send).

### AC-12-09 — inbound media parse + voice flag [BE][T]
- **Given** an inbound image/video/audio/document/sticker, **when** parsed, **then** the media is fetched + stored (`media_key`+mime+filename+size) and the bubble renders inline; an inbound audio with `voice==true` is stored as `VOICE` (not `AUDIO`).

### AC-12-10 — gateway media send [BE][T]
- **Given** `POST /api/v1/omnichannel/messages` with `type ∈ {image,video,audio,voice,document,sticker}`, **when** called with **JSON** (`media:{url,caption,filename}`) **or** **multipart** (`file` part + `payload` json), **then** it accepts either, runs the upload pipeline, returns `202 {id,status:queued}`; oversize/wrong-mime → typed error.

### AC-12-11 — webhook media fields [BE][T]
- **Given** a `message.inbound` delivery, **when** the message is media, **then** `data.message` carries `mediaUrl` (the API-key gateway endpoint), `mimeType`, `filename`, `size`, `voice` — additive, backward-compatible; EMS fetches bytes from `mediaUrl` with its API key.

### AC-12-12 — per-workspace caps [BE][FE][T]
- **Given** an `omnichannel_settings` row keyed by `workspace_id` (nullable = default), **when** an admin sets per-type max sizes, **then** send validation enforces `min(configured, Meta ceiling)` (never above Meta's hard cap — clamp + warn); mimes are fixed to Meta's accepted set (not editable); sniff-gate always on; oversize/bad-mime rejected on **both** inbox + gateway.

---

## Slice 2 — Interactive + structured types

### AC-12-13 — interactive builder + send [FE][BE][T]
- **Given** the composer interactive builder, **when** the agent builds reply-buttons (≤3, title≤20), a list (button + sections[rows{id,title,description}], ≤10 rows), a CTA-URL button, or a location-request, **then** it sends via `adapter.send({type:"interactive",…})` with an optional text **or media header** + footer; the sent message stores `message_type=INTERACTIVE` + `payload_json` (the definition) and renders showing what the recipient sees. Interactive is free-form → **24h window only**.

### AC-12-14 — inbound interactive reply threaded [BE][FE][T]
- **Given** a recipient taps a button/row, **when** parsed, **then** the reply is stored `message_type=INTERACTIVE_REPLY` + `payload_json={kind,id,title,description?}`, **threaded** to the interactive via Meta `context.id`→`reply_to`, and the bubble badges "chose: <title>" under the original.

### AC-12-15 — location send/receive/render [BE][FE][T]
- **Given** location, **when** sent (coords + optional name/address; "use my location" via `navigator.geolocation`) **or** received, **then** it stores `payload_json{lat,lng,name,address}` and renders as a card (name/address + coords + "Open in Maps" link — no embedded tiles). Gateway `type:"location"` + webhook payload symmetric.

### AC-12-16 — contact card send/receive/render [BE][FE][T]
- **Given** a contact card, **when** sent (manual name + phones) **or** received, **then** it stores `payload_json` (WhatsApp-native contacts shape) and renders a card with name · phones · click-to-call (`tel:`) · vCard download. Gateway `type:"contacts"` + webhook payload symmetric.

### AC-12-17 — unknown-type placeholder [BE][T]
- **Given** an inbound message of an unsupported type (order/system/ephemeral/…), **when** parsed, **then** a placeholder bubble ("Unsupported message type") is stored + logged — never silently dropped.

### AC-12-18 — gateway interactive/location/contacts [BE][T]
- **Given** the gateway, **when** `type ∈ {interactive,location,contacts}` is sent, **then** the documented schema is accepted, validated (buttons≤3, list≤10 rows, titles within limits), and returns `202`; malformed → typed 422.

---

## Slice 3 — Reactions + rich templates + polish

### AC-12-19 — reactions send/receive [BE][T]
- **Given** a `message_reactions` table (`UNIQUE(target_message_id, reactor)`), **when** an inbound reaction arrives, **then** it upserts (emoji) or deletes (empty emoji) keyed to the target wamid→our message (unknown target → drop+log), never a bubble; **when** an agent reacts, **then** the adapter sends the reaction + upserts our row.

### AC-12-20 — reaction propagation [BE][FE][T]
- **Given** a reaction change, **then** a `message.reaction` event publishes on **WS** (open inboxes update the chip live) and on the **consumer webhook** (`data{targetMessageId,reactorType,emoji,removed}`, opt-in subscription); the target bubble renders emoji chips.

### AC-12-21 — reaction targets our durable id [BE][T]
- **Given** the gateway `type:"reaction"` (`{messageId:<our durable id>, emoji}`), **when** called, **then** it resolves our id → target message → sends the reaction; EMS never handles raw wamids.

### AC-12-22 — template media/button headers at send [BE][FE][T]
- **Given** a template with an image/video/document header and/or buttons, **when** sent with header media + header/body/CTA-URL variables, **then** the header media runs through the upload pipeline and the template sends with the correct components; a variable-count mismatch → typed 422 (existing rule extended to header/button params).

### AC-12-23 — settings page [FE][T]
- **Given** a workspace admin, **when** they open the omnichannel settings page, **then** they can edit per-type size caps (clamped ≤ Meta, mimes shown read-only) gated by the existing manage permission; changes take effect on the next send.

### AC-12-24 — consumer webhook + docs finalized [BE][FE]
- **Given** all new events/fields, **when** documented, **then** the consumer-webhook contract lists `message.inbound` (media + payload fields), `message.status`, `contact.updated`, `message.reaction`; the EMS integration ticket (`dreamz_ems …/sprint-4/10-…`) is updated with the rich-type envelope; backlog carries the deferred set.

---

## Cross-cutting

### AC-12-25 — CSW window across types [BE][T]
- **Given** the 24h customer-service window is closed, **when** any free-form type (text/media/voice/sticker/interactive/location/contacts/reaction) is sent, **then** it returns `csw_window_closed`; only an approved template sends. Reactions to keep-alive… (reactions still require an open window — Meta rule).

### AC-12-26 — WS realtime for every mutation [BE][T]
- **Given** any new message / status / reaction / contact change, **when** it commits, **then** a WS event publishes to the workspace room — no mutation path leaves other agents' inboxes stale (house rule).

### AC-12-27 — tenant/workspace isolation [BE][T]
- **Given** any send/receive/media-fetch, **when** processed, **then** every query is tenant+workspace-scoped from the auth context (JWT or API key), never client input; a stored media/target id is resolved scoped (defense-in-depth), never an unscoped `get_by_id`.

### AC-12-28 — E2E rich-message journeys [E2E]
- **Given** a dev-cred channel, **when** the suite runs, **then** it real-clicks: send an image (optimistic bubble → SENT), receive an inbound image (inline render), build+send reply-buttons, receive a button reply (threaded badge), react to a message (chip). Deferred/live-number cases recorded in the report.
