# FoundryX Omnichannel — Consumer Integration Guide

**Audience:** the system engineer of a consumer application that wants to send and
receive WhatsApp messages through the FoundryX Omnichannel shared service.

**What you get:** a REST API to send WhatsApp messages of every type, a webhook
feed of inbound messages / delivery receipts / reactions, and a media endpoint —
all against a WhatsApp number that FoundryX hosts and operates on your behalf
(FoundryX is the Meta Tech Provider; you never touch the Meta Graph API directly).

> **Base URL.** Everything below is relative to your FoundryX deployment origin.
> In these examples we use `https://YOUR-FOUNDRYX-HOST` (e.g.
> `https://icp-demo.foundryx.my/be`). Ask your FoundryX operator for the exact
> origin; all consumer paths hang off it.

---

## 1. The big picture

FoundryX sits **between your system and Meta/WhatsApp**. You talk only to FoundryX.

```
                        ┌───────────────────────────────────────────────┐
                        │                 FoundryX Omnichannel           │
   YOUR SYSTEM          │                                               │
 ┌────────────┐  REST   │  /api/v1/omnichannel/*   ┌──────────────┐     │   Meta
 │            │────────▶│  (send, history)         │ Gateway +    │────▶│  Graph
 │  backend   │  API key│                          │ Celery/Redis │     │  API   ──▶ 📱 end user
 │            │◀────────│  outbound webhooks        │ workers      │◀────│  (WhatsApp)
 │  webhook   │  signed │  (inbound, status,        └──────────────┘     │
 │  receiver  │  POST   │   reaction, contact)            ▲               │
 └────────────┘         │                                 │ Meta webhook  │
                        │  /omnichannel/media/{id} (blobs) │               │
                        └─────────────────────────────────┼───────────────┘
                                                          Meta POSTs inbound here
```

Two directions:

- **Outbound (you → FoundryX → user):** you `POST` to the **Consumer Gateway API**
  (`/api/v1/omnichannel/*`) authenticated with a **workspace API key**. FoundryX
  queues the message and delivers it to WhatsApp. Delivery is **asynchronous** —
  the API returns `202 queued` immediately; the real delivery status arrives later
  as a webhook.
- **Inbound (user → FoundryX → you):** when the end user replies (or a status /
  reaction changes), FoundryX POSTs a **signed webhook** to a callback URL you
  registered. Your system must expose an HTTPS endpoint to receive these.

Media (images, documents, voice notes, etc.) is served from a single authed
endpoint that accepts your API key.

---

## 2. Onboarding — what has to happen before you can send

Some of these steps are done by an **operator/admin in the FoundryX dashboard**
(session-authenticated UI, not the API). Your engineering only needs the two
credentials that come out at the end: an **API key** and a **webhook signing
secret**.

| # | Step | Who / where | You receive |
|---|------|-------------|-------------|
| 1 | Create a **Workspace** (a container for one team's numbers + inbox) | FoundryX admin, dashboard | — |
| 2 | **Connect a WhatsApp number** to the workspace via Meta **Embedded Signup** (or a manual System-User token for testing) | FoundryX admin, dashboard | An active channel |
| 3 | **Mint an API key** on the workspace | FoundryX admin, dashboard → API keys | `fxw_live_…` **(shown once)** |
| 4 | **Register your webhook callback URL(s)** on the channel | FoundryX admin, dashboard → Webhooks | `whsec_…` signing secret **(shown once)** |

After step 3 + 4 you have everything your system needs:

- **API key** `fxw_live_…` — put it in `Authorization: Bearer …` on every outbound call.
- **Signing secret** `whsec_…` — use it to verify every inbound webhook.

### What you must build on your side

1. An outbound client that calls the Gateway API with the API key.
2. An **HTTPS** webhook receiver (must be a valid public https URL — FoundryX
   refuses `http://`, `localhost`, `.local`, and private/loopback IPs at
   registration) that:
   - verifies the `X-Fx-Signature` header (§7),
   - responds `2xx` quickly (do heavy work async — FoundryX times out at 10s and retries),
   - is **idempotent** on the event `id` (retries and at-least-once delivery mean you can see the same event twice).

> A workspace must have **one active channel**. If none is connected, every send
> returns `409 no_active_channel`.

---

## 3. Authentication (Consumer Gateway API)

Every call to `/api/v1/omnichannel/*` and to the media endpoint uses your
workspace API key as a Bearer token:

```
Authorization: Bearer fxw_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

- The key **encodes the tenant + workspace** — you never send a tenant or
  workspace id in the body or query. All data is scoped to the key.
- Keys are stored hashed; the plaintext is shown **once** at mint time. If lost,
  revoke and mint a new one.
- Errors are uniform and give away nothing: missing/malformed/unknown/revoked key
  → `401 invalid_api_key`. If the omnichannel service is not enabled for your
  tenant → `403 service_not_enabled`.

All errors on `/api/v1/*` use one envelope:

```json
{ "error": { "code": "csw_window_closed", "message": "The 24-hour window has closed — send an approved template to re-engage." } }
```

---

## 4. Sending messages

### `POST /api/v1/omnichannel/messages`

Sends one message. Returns **`202 Accepted`** with your durable message id — the
message is *queued*, not yet delivered. Track delivery via the `message.status`
webhook.

**Headers**

| Header | Required | Notes |
|--------|----------|-------|
| `Authorization: Bearer fxw_live_…` | yes | |
| `Content-Type: application/json` **or** `multipart/form-data` | yes | JSON for everything; multipart only to upload a media file directly (see §4.3) |
| `Idempotency-Key: <your-unique-key>` | recommended | Workspace-scoped dedup, 24h TTL. A replay returns the **original** message id, still `202`, with `idempotencyReplay: true`. A duplicate still in flight → `409 idempotency_in_progress`. |

**Response** `202`:

```json
{ "id": "0a0d673d-…", "status": "queued", "idempotencyReplay": false }
```

`id` is **FoundryX's** durable message id (not Meta's `wamid`). Use it to
correlate with `message.status` webhooks and as the target for reactions.

### 4.1 Request body by type

The JSON body always has `to` + `type`, plus one type-specific object:

```jsonc
{
  "to": "+60123456789",     // recipient phone (digits extracted; invalid → 422 invalid_recipient)
  "type": "text",           // see the table below
  "text":        { … },
  "template":    { … },
  "media":       { … },
  "interactive": { … },
  "location":    { … },
  "contacts":    [ … ],
  "reaction":    { … }
}
```

| `type` | Body key | Window rule | Shape |
|--------|----------|-------------|-------|
| `text` | `text` | free-form (24h) | `{ "body": "Hello" }` |
| `template` | `template` | **exempt** — always allowed | `{ "name": "order_update", "variables": ["Jayson","ORD0001"] }` or `{ "id": "…" }` |
| `image` `video` `audio` `voice` `document` `sticker` | `media` | free-form (24h) | `{ "url": "https://…", "caption": "…", "filename": "…" }` (see §4.2/4.3) |
| `interactive` | `interactive` | free-form (24h) | buttons / list / cta_url / location_request (see §4.4) |
| `location` | `location` | free-form (24h) | `{ "latitude": 3.10, "longitude": 101.73, "name": "…", "address": "…" }` |
| `contacts` | `contacts` | free-form (24h) | `[ { "name": {...}, "phones": [...] } ]` (see §4.4) |
| `reaction` | `reaction` | free-form (24h) | `{ "messageId": "<foundryx id>", "emoji": "❤️" }` (empty emoji removes) |

> **Free-form vs template — the 24-hour window (CSW).** WhatsApp only lets you
> send *free-form* content within **24 hours of the user's last inbound message**.
> Outside that window, **only an approved template** may be sent (to re-engage).
> Every inbound message resets the 24h clock. If you send free-form when the window
> is closed you get `409 csw_window_closed`. Templates are always allowed. See §6.

#### Text
```bash
curl -X POST https://YOUR-FOUNDRYX-HOST/api/v1/omnichannel/messages \
  -H "Authorization: Bearer fxw_live_…" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: order-4821-confirm" \
  -d '{ "to": "+60123456789", "type": "text", "text": { "body": "Hi Jayson, your order is on the way." } }'
```

#### Template (re-engage outside the 24h window)
`variables` fill the body placeholders `{{1}}, {{2}}, …` in order. List your
approved templates with `GET /templates` (§5).
```json
{ "to": "+60123456789", "type": "template",
  "template": { "name": "order_update", "variables": ["Jayson", "ORD0001"] } }
```

#### Reaction
Reactions target **FoundryX's** message id (the `id` from a send response or a
`MessageItem.id`), never Meta's wamid. Empty `emoji` removes the reaction.
```json
{ "to": "+60123456789", "type": "reaction",
  "reaction": { "messageId": "8dbc5265-…", "emoji": "👍" } }
```

### 4.2 Media by URL

Give a public **https** URL; FoundryX fetches the bytes, validates them, and
uploads to WhatsApp (a bare Meta link is never forwarded).

```json
{ "to": "+60123456789", "type": "image",
  "media": { "url": "https://cdn.example.com/receipt.png", "caption": "Your receipt" } }
```

The URL is SSRF-guarded: **https only**, no redirects, no private/loopback/reserved
hosts. Fetch problems → `422 invalid_media_url` / `422 media_fetch_failed` /
`422 oversize`.

**Size ceilings & accepted MIME types** (Meta's fixed limits):

| Kind | Max size | Accepted types |
|------|----------|----------------|
| image | 5 MB | jpeg, png |
| video | 16 MB | mp4, 3gpp |
| audio | 16 MB | aac, mpeg, mp4, amr, ogg |
| voice | 16 MB | ogg |
| document | 100 MB | pdf, zip, docx, xlsx, pptx, text/plain |
| sticker | 500 KB | webp |

Bad size/type → `422 oversize` / `422 unsupported_media` / `422 transcode_failed`.

### 4.3 Media by direct upload (multipart)

When you have the file itself (not a URL), send `multipart/form-data` with two
parts: `file` (the binary) and `payload` (a JSON string).

```bash
curl -X POST https://YOUR-FOUNDRYX-HOST/api/v1/omnichannel/messages \
  -H "Authorization: Bearer fxw_live_…" \
  -F 'file=@/path/receipt.pdf;type=application/pdf' \
  -F 'payload={"to":"+60123456789","type":"document","media":{"filename":"receipt.pdf","caption":"Your receipt"}}'
```

Missing either part → `422 invalid_request`.

### 4.4 Interactive, location, contacts

**Interactive** (`interactive` object) — `kind` is one of `buttons`, `list`,
`cta_url`, `location_request`:

```jsonc
// Reply buttons (1–3, titles ≤ 20 chars, unique ids)
{ "to":"+6012…", "type":"interactive", "interactive": {
    "kind": "buttons",
    "body": "Pick a slot",            // required, ≤ 1024
    "footer": "Reply anytime",        // optional, ≤ 60
    "buttons": [ { "id":"am", "title":"Morning" }, { "id":"pm", "title":"Afternoon" } ]
} }

// List (≤ 10 rows total; row title ≤ 24, description ≤ 72)
{ "kind":"list", "body":"Menu", "button":"View",
  "sections":[ { "title":"Mains", "rows":[ { "id":"n1","title":"Nasi Lemak","description":"…" } ] } ] }

// Call-to-action URL
{ "kind":"cta_url", "body":"See details", "cta": { "displayText":"Open", "url":"https://…" } }
```
A `header` is optional: `{ "type":"text", "text":"…" }` (≤60) or a media header
`{ "type":"image|video|document", "url":"https://…", "filename":"…" }` (URL is
SSRF-fetched like §4.2). Invalid shapes → `422 invalid_request`.

**Location:**
```json
{ "to":"+6012…", "type":"location",
  "location": { "latitude": 3.1026, "longitude": 101.7333, "name":"Office", "address":"…" } }
```
`latitude` ∈ [-90,90], `longitude` ∈ [-180,180] (`lat`/`lng` accepted too).

**Contacts:**
```json
{ "to":"+6012…", "type":"contacts",
  "contacts": [ { "name": { "formatted_name":"Kay", "first_name":"Kay" },
                 "phones": [ { "phone":"+60123456789", "type":"CELL" } ] } ] }
```
Each contact needs a name and ≥1 phone. Phone `type` ∈ `CELL|HOME|WORK|MAIN|IPHONE`.

---

## 5. Listing approved templates

### `GET /api/v1/omnichannel/templates`

Only **APPROVED** templates on the workspace's active channel.

```json
{ "data": [
  { "id": "…", "name": "order_update", "language": "en_US",
    "category": "UTILITY", "bodyText": "Hi {{1}}, there is update on your order {{2}}",
    "variableCount": 2 }
] }
```

Use `name` (or `id`) + fill `variableCount` values in `template.variables` when
sending (§4.1). Templates are authored + submitted to Meta by the FoundryX admin
in the dashboard; you only consume the approved ones.

---

## 6. Fetching a contact's message history

### `GET /api/v1/omnichannel/contacts/{contactId}/messages`

Full-fidelity history for one contact — **every message type** (text, media,
interactive, location, contacts, template, reaction, replies), the same shape the
inbox renders. Read-only (does **not** mark the thread read).

**Query params**

| Param | Default | Notes |
|-------|---------|-------|
| `limit` | 50 | 1–200 |
| `before` | — | a message id; page further back in history |

**Response**

```json
{
  "contactId": "b2ad5218-…",
  "data": [ /* MessageItem, oldest → newest — see §9 */ ],
  "nextBefore": "0a0d673d-…"   // pass back as ?before= to page deeper; null at the oldest page
}
```

Contact not in your workspace → `404 contact_not_found`.

You typically discover a `contactId` from the `message.inbound` webhook
(`data.contact.id`).

---

## 7. Receiving events (webhooks: FoundryX → you)

FoundryX POSTs a **signed JSON envelope** to each callback URL you registered for
the channel, for each event type you subscribed to.

### Subscribable event types

| Event | Fires when |
|-------|-----------|
| `message.inbound` | The user sends you a message (any type) |
| `message.status` | A message you sent changes state (SENT/DELIVERED/READ/FAILED) |
| `message.reaction` | A reaction is added/removed on a message |
| `contact.updated` | A thread is assigned / status / priority changes |

### The envelope

```json
{
  "id": "wamid.HBg…",              // dedup key — idempotency handle (see per-event below)
  "type": "message.inbound",
  "workspaceId": "efd70bf3-…",
  "channelId": "31c4900f-…",
  "occurredAt": "2026-07-09T11:02:43Z",
  "data": { /* per-event, below */ }
}
```

**`data` per event**

- **`message.inbound`** — `id` = Meta wamid.
  ```json
  { "message": { /* MessageItem (§9) */ }, "contact": { /* ThreadItem (§9) */ } }
  ```
  For media messages the message object exposes an **absolute, API-key-authed**
  `mediaUrl` (`https://YOUR-FOUNDRYX-HOST/omnichannel/media/{id}`) and renames the
  media fields to `mimeType`, `filename`, `size`.

- **`message.status`** — `id` = `{messageId}:{deliveryStatus}` (one per transition).
  ```json
  { "messageId":"0a0d673d-…", "externalMessageId":"wamid…", "contactId":"b2ad5218-…",
    "deliveryStatus":"DELIVERED", "errorCode":null, "errorMessage":null }
  ```

- **`message.reaction`**
  ```json
  { "targetMessageId":"8dbc5265-…", "reactorType":"CONTACT", "emoji":"❤️", "removed":false }
  ```

- **`contact.updated`** — `id` = `{contactId}:{timestamp}`.
  ```json
  { "contact": { /* ThreadItem (§9) */ } }
  ```

### Headers on every webhook POST

| Header | Value |
|--------|-------|
| `Content-Type` | `application/json` |
| `User-Agent` | `FoundryX-Webhooks/1.0` |
| `X-Fx-Event-Id` | the envelope `id` |
| `X-Fx-Event-Type` | the event type |
| `X-Fx-Timestamp` | unix seconds (signed) |
| `X-Fx-Signature` | `sha256=<hex hmac>` |

### Verifying the signature (do this on every request)

The signature is `HMAC-SHA256(signingSecret, "{X-Fx-Timestamp}." + rawRequestBody)`,
hex-encoded, prefixed `sha256=`. **Sign over the raw bytes** — do not re-serialize
the parsed JSON. Reject if the timestamp is more than ~5 minutes old (replay guard).

**Node.js (Express):**
```js
const crypto = require('crypto');

// Mount with the RAW body so you hash the exact bytes FoundryX signed:
app.post('/webhooks/foundryx', express.raw({ type: 'application/json' }), (req, res) => {
  const ts  = req.get('X-Fx-Timestamp');
  const sig = req.get('X-Fx-Signature') || '';
  const expected = 'sha256=' + crypto
    .createHmac('sha256', process.env.FX_WEBHOOK_SECRET)   // whsec_…
    .update(ts + '.' + req.body)                           // req.body is a Buffer
    .digest('hex');

  const ok = sig.length === expected.length &&
             crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected));
  if (!ok) return res.sendStatus(401);
  if (Math.abs(Date.now() / 1000 - Number(ts)) > 300) return res.sendStatus(401);

  const event = JSON.parse(req.body.toString());
  // TODO: dedup on event.id, then enqueue for async processing
  res.sendStatus(200);   // ack fast — heavy work goes on a queue
});
```

**Python (FastAPI):**
```python
import hmac, hashlib, time
from fastapi import FastAPI, Request, HTTPException

SECRET = b"whsec_…"

@app.post("/webhooks/foundryx")
async def receive(request: Request):
    raw = await request.body()
    ts  = request.headers.get("X-Fx-Timestamp", "")
    sig = request.headers.get("X-Fx-Signature", "")
    expected = "sha256=" + hmac.new(SECRET, f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(401)
    if abs(time.time() - float(ts or 0)) > 300:
        raise HTTPException(401)
    # dedup on the JSON "id", enqueue, then:
    return {"ok": True}
```

### Delivery guarantees, retries, auto-disable

- **Success** = your endpoint returns HTTP `2xx` within **10 seconds**.
- **At-least-once**: retries mean you may see the same event `id` more than once —
  **be idempotent**.
- **Retry backoff**: ~1m, 5m, 25m, 1h, 6h (max **6 attempts**) then dead-letter.
- **Auto-disable**: after 10 consecutive dead-lettered events the endpoint flips to
  `AUTO_DISABLED`; a FoundryX admin must re-enable it (which resets the counter).
- Webhook delivery is fully isolated — a slow/broken consumer never blocks an
  inbound WhatsApp message.
- A **delivery log** is available in the dashboard (per-attempt status, response
  code, latency, error) for debugging.

### Registering / rotating (dashboard, per channel)

Webhook endpoints are created in the FoundryX dashboard against a **channel**:
you supply `name`, `url` (https), and the `events` list; you receive the
`whsec_…` **signing secret once**. You can rotate the secret (returns a new one),
enable/disable, and delete. The URL is validated at registration (https-only, no
private hosts).

---

## 8. Media

### `GET /omnichannel/media/{messageId}`

Fetch the binary for a media message. **Accepts your API key** (or an agent
session). Workspace-scoped; streamed same-origin (no bucket redirect).

```bash
curl -L https://YOUR-FOUNDRYX-HOST/omnichannel/media/8dbc5265-… \
  -H "Authorization: Bearer fxw_live_…" -o file.bin
```

- Response headers: `Content-Security-Policy: sandbox`, `X-Content-Type-Options: nosniff`,
  `Cache-Control: private, max-age=300`.
- Unknown message / no media → `404`. No/invalid auth → `401`. Service disabled → `403`.
- In a `message.inbound` webhook the media message's `mediaUrl` is already the
  absolute form of this URL — just add your `Authorization` header when you fetch it.

---

## 9. Reference — object shapes

### `MessageItem`

Returned by `GET /contacts/{id}/messages` and embedded in `message.inbound`.

```jsonc
{
  "id": "…",                    // FoundryX durable id (use for reactions / correlation)
  "contactId": "…",
  "channelId": "…",
  "senderType": "CONTACT",      // AGENT | CONTACT | SYSTEM
  "senderId": null,
  "senderName": null,
  "messageType": "IMAGE",       // TEXT|TEMPLATE|IMAGE|VIDEO|AUDIO|VOICE|DOCUMENT|
                                //   STICKER|INTERACTIVE|LOCATION|CONTACTS|UNSUPPORTED
  "body": "caption or text",
  "mediaUrl": "/omnichannel/media/…",  // absolute + authed in the inbound webhook
  "mediaMime": "image/png",     // webhook renames → mimeType
  "mediaFilename": "receipt.png", // webhook renames → filename
  "mediaSize": 20345,           // webhook renames → size
  "voice": false,
  "payload": { … },             // structured def for interactive/location/contacts/template
  "reactions": [ { "emoji":"❤️", "reactorType":"CONTACT", "reactor":"+6012…" } ],
  "externalMessageId": "wamid…",// Meta wamid
  "deliveryStatus": "DELIVERED",// QUEUED|SENT|DELIVERED|READ|FAILED
  "errorCode": null,
  "errorMessage": null,
  "replyTo": { "id":"…", "body":"…", "senderType":"…", "senderName":"…" },
  "createdAt": "2026-07-09T11:02:43Z"
}
```

### `ThreadItem` (the `contact` in webhooks; "the contact IS the thread")

```jsonc
{
  "id": "b2ad5218-…",           // this is the contactId
  "workspaceId": "…", "tenantId": "…",
  "name": "Jayson", "phone": "+60166753328", "avatarUrl": null,
  "assignedUserId": null, "assignedUserName": null,
  "status": "OPEN",             // OPEN | SNOOZED | CLOSED
  "priority": "MEDIUM",
  "channelId": "…", "channelType": "WHATSAPP",
  "cswExpiresAt": "2026-07-10T11:02:43Z",   // when the 24h free-form window closes
  "lastIncomingMessageAt": "…", "lastMessageAt": "…", "lastMessagePreview": "yeah",
  "unreadCount": 2,
  "createdAt": "…"
}
```

`cswExpiresAt` tells you whether free-form is currently allowed — if it's in the
past, you must send a template to re-engage.

---

## 10. Error reference (Consumer Gateway API)

All errors: `{ "error": { "code": "...", "message": "...", "details"?: ... } }`.

| Code | HTTP | Meaning / fix |
|------|------|---------------|
| `invalid_api_key` | 401 | Missing/bad/revoked key. |
| `service_not_enabled` | 403 | Omnichannel not active for your tenant — contact the operator. |
| `invalid_request` | 422 | Malformed body / failed validation (`details` has specifics). |
| `invalid_recipient` | 422 | `to` isn't a usable phone number. |
| `no_active_channel` | 409 | The workspace has no connected number. |
| `template_not_found` | 422 | No APPROVED template matches `name`/`id`. |
| `csw_window_closed` | 409 | 24h window closed — send an approved template instead. |
| `send_rejected` | 422 | WhatsApp/Meta rejected the send (message has the reason). |
| `unsupported_type` | 400 | Unknown `type`. |
| `not_found` | 404 | Reaction target message not found / not in your workspace. |
| `contact_not_found` | 404 | Contact not in your workspace (history endpoint). |
| `idempotency_in_progress` | 409 | A duplicate `Idempotency-Key` is still processing. |
| `invalid_media_url` / `media_fetch_failed` / `oversize` / `unsupported_media` / `transcode_failed` | 422 | Media fetch/validation failed (see §4.2). |

---

## 11. End-to-end quickstart

1. **Get credentials** from your FoundryX admin: an API key `fxw_live_…` and a
   webhook signing secret `whsec_…` (the admin registers your https callback URL
   and subscribes it to `message.inbound`, `message.status`, `message.reaction`).
2. **Stand up your webhook receiver** (§7) — verify signature, ack `2xx` fast,
   dedup on `id`, process async.
3. **Wait for an inbound message** (the user must message your WhatsApp number
   first to open the 24h window). You'll get a `message.inbound` webhook with
   `data.contact.id`.
4. **Reply free-form** within 24h:
   ```bash
   curl -X POST https://YOUR-FOUNDRYX-HOST/api/v1/omnichannel/messages \
     -H "Authorization: Bearer fxw_live_…" -H "Content-Type: application/json" \
     -d '{"to":"+60166753328","type":"text","text":{"body":"Thanks, on it!"}}'
   ```
   → `202 {"id":"…","status":"queued"}`. Watch for the `message.status` webhook.
5. **Outside 24h?** List templates (`GET /templates`), then send `type:"template"`.
6. **Pull history** any time: `GET /contacts/{contactId}/messages`.
7. **Fetch media** from `message.mediaUrl` with your API key (§8).

---

## Appendix — quick endpoint index

**Consumer Gateway (API key):**

| Method | Path |
|--------|------|
| POST | `/api/v1/omnichannel/messages` |
| GET | `/api/v1/omnichannel/templates` |
| GET | `/api/v1/omnichannel/contacts/{contactId}/messages` |
| GET | `/omnichannel/media/{messageId}` |

**Managed for you in the FoundryX dashboard (session-authed):** workspace +
channel onboarding (Embedded Signup), API-key mint/revoke, webhook
register/rotate/enable/disable + delivery log, template authoring/submission.

**Webhooks (FoundryX → your https URL):** `message.inbound`, `message.status`,
`message.reaction`, `contact.updated` — signed with `X-Fx-Signature`.
