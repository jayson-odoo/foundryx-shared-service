# Omnichannel Consumer-Webhook Contract (finalized - plan 12 Slice 3, AC-12-24)

The canonical event contract a consumer (e.g. the EMS module in `dreamz_ems`) subscribes to. Endpoints are registered per channel with an opt-in `events[]` list; each delivery is HMAC-signed (`X-Fx-Signature`) and carries a stable `event_id` for dedup across our retries.

**Subscribable event types** (`webhook_service.EVENT_TYPES`): `message.inbound`, `message.status`, `contact.updated`, `message.reaction`.

Every envelope: `{ type, channelId, eventId, timestamp, data }`. All fields below are additive/back-compat - a consumer built before Slice 1/2/3 keeps working.

---

## `message.inbound`
An inbound message from a contact (text / media / interactive-reply / location / contacts / unsupported).

`data.message` fields:
- `id` - OUR durable message id (never a raw wamid; EMS references this).
- `contactId`, `channelId`, `senderType` (`CONTACT`), `messageType`, `body`, `createdAt`.
- **Media (Slice 1)**: `mediaUrl` - an ABSOLUTE, API-key-authed gateway URL (`{public_base_url}/omnichannel/media/{id}`, not the inbox-relative path); `mimeType`; `filename`; `size`; `voice` (bool - an inbound voice note).
- **Structured payload (Slice 2)**: `payload` - the friendly definition for `INTERACTIVE_REPLY` (`{kind,id,title,description?}`), `LOCATION` (`{lat,lng,name,address}`), `CONTACTS` (WhatsApp-native `{contacts:[…]}`). `UNSUPPORTED` inbound types are delivered with a placeholder body, never dropped.
- `replyTo` - quoted-message ref when the inbound threads a reply (Meta `context.id` → our message).

`data.contact` - the thread summary.

> Field-naming note (AC-12-11): the consumer envelope uses `mimeType`/`filename`/`size`; the internal FE wire uses `mediaMime`/`mediaFilename`/`mediaSize`. Same data, distinct names by surface.

## `message.status`
A delivery receipt (sent → delivered → read, or failed). One event per transition (`event_id = "{messageId}:{status}"`).

`data`: `{ messageId, externalMessageId, contactId, deliveryStatus (SENT|DELIVERED|READ|FAILED), errorCode?, errorMessage? }`.

## `contact.updated`
Thread metadata changed (assignment, lifecycle status, priority, profile). `data` = the thread summary.

## `message.reaction` (NEW - Slice 3, AC-12-20)
A reaction was added or removed on a message. **Never a message bubble** - it targets an existing message.

`data`: `{ targetMessageId, reactorType (CONTACT|AGENT), emoji, removed }`.
- `targetMessageId` - OUR durable message id (AC-12-21: EMS never handles raw wamids). An inbound reaction whose target we don't have is dropped + logged, never forwarded.
- `emoji` - the reaction emoji (empty string when `removed` is true).
- `removed` - true when the reaction was cleared (empty-emoji reaction from the contact, or the agent removed theirs).

---

## Cross-repo action (AC-12-24)
The EMS integration ticket lives in the sibling repo `dreamz_ems` (`documentation/plans/sprint-4/10-…`). It must be updated to reflect the Slice-1/2/3 additions above - the rich `message.inbound` media+payload fields and the new `message.reaction` event. Tracked as a handoff (this repo cannot edit `dreamz_ems`); see the backlog.

## Deferred (backlog)
- BL-SS-010 WhatsApp Flows · BL-SS-011 commerce/catalog/carousel/OTP templates · BL-SS-012 on-device recall · BL-SS-013 location map-tile embed.
