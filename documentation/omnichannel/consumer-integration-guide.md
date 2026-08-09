# FoundryX Omnichannel — Consumer Integration Guide

**Audience:** the system engineer of a consumer application that wants to send and receive WhatsApp messages through the FoundryX Omnichannel shared service.

**What you get:** a REST API to send WhatsApp messages of every type, a webhook feed of inbound messages / delivery receipts / reactions, and a media endpoint — all against a WhatsApp number that FoundryX hosts and operates on your behalf (FoundryX is the Meta Tech Provider; you never touch the Meta Graph API directly).

> **Base URL.** Everything below is relative to your FoundryX deployment origin. In these examples we use `https://YOUR-FOUNDRYX-HOST` (e.g. `https://icp-demo.foundryx.my/be`). Ask your FoundryX operator for the exact origin; all consumer paths hang off it.

> **Changelog**
>
> | Date | Change |
> |----|----|
> | **2026-08-09** | **§6 / §6a / §9 corrected to the deployed contract.** The read endpoints have returned respond.io-shaped objects since 2026-07-11; this guide still described the pre-2026-07-11 shape. §9 now documents both families and §9.3 is an old→new field map. Same release restored `timestamp` on every message and added `cswExpiresAt`, `message.payload`, `message.size`, `reactions[]` and `replyTo` to the read shapes. Webhooks (§7) are unchanged throughout. |
> | 2026-07-11 | Read endpoints reshaped for respond.io parity (**breaking**; undocumented at the time — see the row above). |


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

* **Outbound (you → FoundryX → user):** you `POST` to the **Consumer Gateway API** (`/api/v1/omnichannel/*`) authenticated with a **workspace API key**. FoundryX queues the message and delivers it to WhatsApp. Delivery is **asynchronous** — the API returns `202 queued` immediately; the real delivery status arrives later as a webhook.
* **Inbound (user → FoundryX → you):** when the end user replies (or a status / reaction changes), FoundryX POSTs a **signed webhook** to a callback URL you registered. Your system must expose an HTTPS endpoint to receive these.

Media (images, documents, voice notes, etc.) is served from a single authed endpoint that accepts your API key.

### Two ways to integrate — pick either or both

|    | **A · Consumer Gateway API** (§2–§11) | **B · Embed the UI** (§12) |
|----|----|----|
| What | You call our REST API + receive webhooks, and **build your own chat UI** | You mount **our conversation UI** in an `<iframe>` on your page — no UI to build |
| Credential | Workspace **API key** (`fxw_live_…`), server-to-server | Short-lived **embed access token**, minted per-agent in the browser from a signed assertion (the API key never touches the browser) |
| Best for | Full control, custom UX, bots/automation | Drop a live WhatsApp thread onto a record page (e.g. a CRM lead) in minutes |
| You build | Outbound client + webhook receiver + your own UI | A server-side **assertion minter** + a small **postMessage** handshake |

The two are independent and combine freely — many consumers automate sends via the API **and** embed the UI for their agents. §2–§11 cover Option A. **§12 covers Option B (the iframe).**

> **Troubleshooting.** Whichever option(s) you use, every consumption is captured in the dashboard **Developers ▸ Logs** console — inbound API calls, embed sessions, outbound Meta calls, and webhook deliveries in one trace-correlated feed. When a send doesn't arrive or a token is rejected, that's where your engineer looks. See **§13**.


---

## 2. Onboarding — what has to happen before you can send

Some of these steps are done by an **operator/admin in the FoundryX dashboard** (session-authenticated UI, not the API). Your engineering only needs the two credentials that come out at the end: an **API key** and a **webhook signing secret**.

| # | Step | Who / where | You receive |
|----|----|----|----|
| 1 | Create a **Workspace** (a container for one team's numbers + inbox) | FoundryX admin, dashboard | — |
| 2 | **Connect a WhatsApp number** to the workspace via Meta **Embedded Signup** (or a manual System-User token for testing) | FoundryX admin, dashboard | An active channel |
| 3 | **Mint an API key** on the workspace | FoundryX admin, dashboard → API keys | `fxw_live_…` **(shown once)** |
| 4 | **Register your webhook callback URL(s)** on the channel | FoundryX admin, dashboard → Webhooks | `whsec_…` signing secret **(shown once)** |

After step 3 + 4 you have everything your system needs:

* **API key** `fxw_live_…` — put it in `Authorization: Bearer …` on every outbound call.
* **Signing secret** `whsec_…` — use it to verify every inbound webhook.

### What you must build on your side


1. An outbound client that calls the Gateway API with the API key.
2. An **HTTPS** webhook receiver (must be a valid public https URL — FoundryX refuses `http://`, `localhost`, `.local`, and private/loopback IPs at registration) that:
   * verifies the `X-Fx-Signature` header (§7),
   * responds `2xx` quickly (do heavy work async — FoundryX times out at 10s and retries),
   * is **idempotent** on the event `id` (retries and at-least-once delivery mean you can see the same event twice).

> A workspace must have **one active channel**. If none is connected, every send returns `409 no_active_channel`.


---

## 3. Authentication (Consumer Gateway API)

Every call to `/api/v1/omnichannel/*` and to the media endpoint uses your workspace API key as a Bearer token:

```
Authorization: Bearer fxw_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

* The key **encodes the tenant + workspace** — you never send a tenant or workspace id in the body or query. All data is scoped to the key.
* Keys are stored hashed; the plaintext is shown **once** at mint time. If lost, revoke and mint a new one.
* Errors are uniform and give away nothing: missing/malformed/unknown/revoked key → `401 invalid_api_key`. If the omnichannel service is not enabled for your tenant → `403 service_not_enabled`.

All errors on `/api/v1/*` use one envelope:

```json
{ "error": { "code": "csw_window_closed", "message": "The 24-hour window has closed — send an approved template to re-engage." } }
```


---

## 4. Sending messages

### `POST /api/v1/omnichannel/messages`

Sends one message. Returns `**202 Accepted**` with your durable message id — the message is *queued*, not yet delivered. Track delivery via the `message.status` webhook.

**Headers**

| Header | Required | Notes |
|----|----|----|
| `Authorization: Bearer fxw_live_…` | yes |    |
| `Content-Type: application/json` **or** `multipart/form-data` | yes | JSON for everything; multipart only to upload a media file directly (see §4.3) |
| `Idempotency-Key: <your-unique-key>` | recommended | Workspace-scoped dedup, 24h TTL. A replay returns the **original** message id, still `202`, with `idempotencyReplay: true`. A duplicate still in flight → `409 idempotency_in_progress`. |

**Response** `202`:

```json
{ "id": "0a0d673d-…", "status": "queued", "idempotencyReplay": false }
```

`id` is **FoundryX's** durable message id (not Meta's `wamid`). Use it to correlate with `message.status` webhooks and as the target for reactions.

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
|----|----|----|----|
| `text` | `text` | free-form (24h) | `{ "body": "Hello" }` |
| `template` | `template` | **exempt** — always allowed | `{ "name": "order_update", "variables": ["Jayson","ORD0001"] }` or `{ "id": "…" }` |
| `image` `video` `audio` `voice` `document` `sticker` | `media` | free-form (24h) | `{ "url": "https://…", "caption": "…", "filename": "…" }` (see §4.2/4.3) |
| `interactive` | `interactive` | free-form (24h) | buttons / list / cta_url / location_request (see §4.4) |
| `location` | `location` | free-form (24h) | `{ "latitude": 3.10, "longitude": 101.73, "name": "…", "address": "…" }` |
| `contacts` | `contacts` | free-form (24h) | `[ { "name": {...}, "phones": [...] } ]` (see §4.4) |
| `reaction` | `reaction` | free-form (24h) | `{ "messageId": "<foundryx id>", "emoji": "❤️" }` (empty emoji removes) |

> **Free-form vs template — the 24-hour window (CSW).** WhatsApp only lets you send *free-form* content within **24 hours of the user's last inbound message**. Outside that window, **only an approved template** may be sent (to re-engage). Every inbound message resets the 24h clock. If you send free-form when the window is closed you get `409 csw_window_closed`. Templates are always allowed.
>
> **Check before you send, don't probe.** `cswExpiresAt` on the contact (§6a / §9.1) is the signal: in the future ⇒ free-form is allowed; past or `null` ⇒ template only. Every inbound webhook also refreshes it. Treating the `409` as your detection mechanism turns a preventable state into a user-visible failure.

#### Text

```bash
curl -X POST https://YOUR-FOUNDRYX-HOST/api/v1/omnichannel/messages \
  -H "Authorization: Bearer fxw_live_…" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: order-4821-confirm" \
  -d '{ "to": "+60123456789", "type": "text", "text": { "body": "Hi Jayson, your order is on the way." } }'
```

#### Template (re-engage outside the 24h window)

`variables` fill the body placeholders `{{1}}, {{2}}, …` in order. List your approved templates with `GET /templates` (§5).

```json
{ "to": "+60123456789", "type": "template",
  "template": { "name": "order_update", "variables": ["Jayson", "ORD0001"] } }
```

#### Reaction

Reactions target **FoundryX's** message id — the `id` from a send response, a `MessageObject.messageId` from history (§9.1), or a `MessageItem.id` from a webhook (§9.2). Never Meta's wamid. Empty `emoji` removes the reaction.

```json
{ "to": "+60123456789", "type": "reaction",
  "reaction": { "messageId": "8dbc5265-…", "emoji": "👍" } }
```

### 4.2 Media by URL

Give a public **https** URL; FoundryX fetches the bytes, validates them, and uploads to WhatsApp (a bare Meta link is never forwarded).

```json
{ "to": "+60123456789", "type": "image",
  "media": { "url": "https://cdn.example.com/receipt.png", "caption": "Your receipt" } }
```

The URL is SSRF-guarded: **https only**, no redirects, no private/loopback/reserved hosts. Fetch problems → `422 invalid_media_url` / `422 media_fetch_failed` / `422 oversize`.

**Size ceilings & accepted MIME types** (Meta's fixed limits):

| Kind | Max size | Accepted types |
|----|----|----|
| image | 5 MB | jpeg, png |
| video | 16 MB | mp4, 3gpp |
| audio | 16 MB | aac, mpeg, mp4, amr, ogg |
| voice | 16 MB | ogg |
| document | 100 MB | pdf, zip, docx, xlsx, pptx, text/plain |
| sticker | 500 KB | webp |

Bad size/type → `422 oversize` / `422 unsupported_media` / `422 transcode_failed`.

### 4.3 Media by direct upload (multipart)

When you have the file itself (not a URL), send `multipart/form-data` with two parts: `file` (the binary) and `payload` (a JSON string).

```bash
curl -X POST https://YOUR-FOUNDRYX-HOST/api/v1/omnichannel/messages \
  -H "Authorization: Bearer fxw_live_…" \
  -F 'file=@/path/receipt.pdf;type=application/pdf' \
  -F 'payload={"to":"+60123456789","type":"document","media":{"filename":"receipt.pdf","caption":"Your receipt"}}'
```

Missing either part → `422 invalid_request`.

### 4.4 Interactive, location, contacts

**Interactive** (`interactive` object) — `kind` is one of `buttons`, `list`, `cta_url`, `location_request`:

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

A `header` is optional: `{ "type":"text", "text":"…" }` (≤60) or a media header `{ "type":"image|video|document", "url":"https://…", "filename":"…" }` (URL is SSRF-fetched like §4.2). Invalid shapes → `422 invalid_request`.

**Location:**

```json
{ "to":"+6012…", "type":"location",
  "location": { "latitude": 3.1026, "longitude": 101.7333, "name":"Office", "address":"…" } }
```

`latitude` ∈ \[-90,90\], `longitude` ∈ \[-180,180\] (`lat`/`lng` accepted too).

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

Use `name` (or `id`) + fill `variableCount` values in `template.variables` when sending (§4.1). Templates are authored + submitted to Meta by the FoundryX admin in the dashboard; you only consume the approved ones.


---

## 6. Fetching a contact's message history

### `GET /api/v1/omnichannel/contacts/{identifier}/messages`

Full-fidelity history for one contact — **every message type** (text, media, interactive, location, contacts, template, replies). Read-only (does **not** mark the thread read).

A **reaction is never its own message** — don't page history looking for one. It appears as `reactions[]` on the message it targets (§9.1).

> **⚠️ Changed 2026-07-11 — read this if you integrated before that date.** These read endpoints return **respond.io-shaped** objects (`MessageObject`, §9), not the `MessageItem`/`ThreadItem` shape earlier revisions of this guide described. The envelope changed from `{contactId, data, nextBefore}` to `{items, pagination}`, and fields were renamed (`id`→`messageId`, `body`→`message.text`, `senderType`→`traffic` + `sender.source`, `createdAt`→`timestamp`). **Webhooks (§7) were NOT changed** — they still carry the shapes in §9.2. See §9.3 for the full old→new field map.

**Query params**

| Param | Default | Notes |
|----|----|----|
| `limit` | 50 | 1–200 |
| `before` | — | a message id; page further **back** into history |
| `after` | — | a message id; page **forward** toward the present |

**Response** — always **oldest → newest**, whichever direction you paged:

```json
{
  "items": [ /* MessageObject — see §9 */ ],
  "pagination": {
    "next":     "https://YOUR-FOUNDRYX-HOST/api/v1/…?limit=50&before=7a3693ed-…",
    "previous": "https://YOUR-FOUNDRYX-HOST/api/v1/…?limit=50&after=99fb3926-…"
  }
}
```

Both cursors are **absolute URLs** — follow them verbatim, don't rebuild them. `next` pages **into older history** and is `null` once a page comes back short (fewer rows than `limit`). `previous` pages **toward newer messages** and is present whenever the page has any rows — poll it to pick up what arrived since.

Contact not in your workspace → `404 contact_not_found`.

`{identifier}` is the polymorphic form from §6a (`phone:+60…`, `id:<uuid>`, or a bare id). You typically discover a contact id from the `message.inbound` webhook (`data.contact.id`).

### Ordering a merged history

Every message carries `timestamp` (epoch seconds), **inbound and outbound alike** — it is the only key that orders a history merged across several of a contact's numbers. Do not order on `status[].timestamp`: that array is populated from delivery receipts, and **inbound messages never receive one**, so it is always empty for them.


---

## 6a. Contacts & conversations

These endpoints let you read and manage contacts (threads) directly, respond.io-style.

### The `{identifier}` convention

Anywhere a contact is addressed you may use a **polymorphic identifier**:

| Form | Example | Meaning |
|----|----|----|
| `phone:<e164>` | `phone:+60123456789` | look up by phone within your workspace |
| `id:<uuid>` | `id:b2ad5218-…` | FoundryX contact id |
| bare id | `b2ad5218-…` | same as `id:` |

A miss (or a contact in another workspace) → `404 contact_not_found`.

### List contacts — `GET /api/v1/omnichannel/contacts`

Query params: `status` (`OPEN|SNOOZED|CLOSED`), `assignee` (`all|unassigned`), `priority` (`LOW|MEDIUM|HIGH|URGENT`), `search` (name / phone / message body), `page` (0-based), `pageSize` (1–200).

Filter values go in **uppercase** (as above); the `status` echoed back in the response is **lowercase** (`"open"`) — respond.io's convention, and the one asymmetry worth remembering.

```json
{
  "items": [ /* ContactObject — see §9 */ ],
  "pagination": { "next": "…&page=1", "previous": null }
}
```

Page cursors are absolute URLs, same as §6. There is no `total` — page until `next` is `null`.

### Get a contact — `GET /api/v1/omnichannel/contacts/{identifier}`

Returns one `ContactObject` (§9). `GET …/contacts/phone:+60123456789` works too.

### Update a contact — `PATCH /api/v1/omnichannel/contacts/{identifier}`

Partial — only fields you send change. Send `assignedUserId`/`customFields` as `null` to clear; omit to leave unchanged.

```json
{ "firstName": "Jayson", "lastName": "Teh",
  "priority": "HIGH", "assignedUserId": "…", "customFields": { "orderId": "ORD0001" } }
```

Assign a conversation to an agent by setting `assignedUserId`; unassign by sending it as `null`. Unknown assignee → `422 invalid_request`.

The **request** body uses the field names above; the **response** is a `ContactObject` (§9), which is a different shape — `priority`, for example, is written server-side but has no respond.io field, so it is not echoed back. Read it from your own record, not from the response.

### Get a single message — `GET /api/v1/omnichannel/contacts/{identifier}/messages/{messageId}`

Returns one `MessageObject` (§9), full fidelity. Not on this contact → `404 message_not_found`.

### Open / close a conversation

* `POST /api/v1/omnichannel/contacts/{identifier}/conversation/open`  → status `OPEN`
* `POST /api/v1/omnichannel/contacts/{identifier}/conversation/close` → status `CLOSED`

Both return the updated `ContactObject`.

### Add an internal comment (note) — `POST /api/v1/omnichannel/contacts/{identifier}/comments`

An internal note on the thread — **never sent to the customer** (visible to your agents / in history).

```json
{ "body": "Customer asked for a refund — escalating." }
```

Returns `201` with the created note.

> **Two shapes on one route family — mind this one.** The comment **response** is a `MessageItem` (§9.2, the webhook/internal shape: `id`, `senderType`, `createdAt`) — *not* the `MessageObject` the read endpoints return. The `id` you get back is the same message that later appears in §6 history as `messageId`. Map it when you correlate.
>
> **And when you read history back, an internal note looks like an outbound message:** it comes through with `traffic: "outgoing"` (it did originate from your side). The discriminator is **`sender.source === "system"`** — check it before rendering anything as "sent to the customer", or your agents will see internal notes presented as delivered WhatsApp messages.


---

## 7. Receiving events (webhooks: FoundryX → you)

FoundryX POSTs a **signed JSON envelope** to each callback URL you registered for the channel, for each event type you subscribed to.

> Webhook payloads use the **§9.2** shapes (`MessageItem`, `ThreadItem`) and were **not** affected by the 2026-07-11 read-endpoint change. They are also the richest surface: `senderName`, `priority`, `unreadCount`, `lastMessagePreview` and `channelType` arrive here and are not on the §9.1 read shapes.

### Subscribable event types

| Event | Fires when |
|----|----|
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

`**data**` **per event**

* `**message.inbound**` — `id` = Meta wamid.

  ```json
  { "message": { /* MessageItem (§9.2) */ }, "contact": { /* ThreadItem (§9.2) */ } }
  ```

  For media messages the message object exposes an **absolute, API-key-authed** `mediaUrl` (`https://YOUR-FOUNDRYX-HOST/omnichannel/media/{id}`) and renames the media fields to `mimeType`, `filename`, `size`.
* `**message.status**` — `id` = `{messageId}:{deliveryStatus}` (one per transition).

  ```json
  { "messageId":"0a0d673d-…", "externalMessageId":"wamid…", "contactId":"b2ad5218-…",
    "deliveryStatus":"DELIVERED", "errorCode":null, "errorMessage":null }
  ```
* `**message.reaction**`

  ```json
  { "targetMessageId":"8dbc5265-…", "reactorType":"CONTACT", "emoji":"❤️", "removed":false }
  ```
* `**contact.updated**` — `id` = `{contactId}:{timestamp}`.

  ```json
  { "contact": { /* ThreadItem (§9.2) */ } }
  ```

### Headers on every webhook POST

| Header | Value |
|----|----|
| `Content-Type` | `application/json` |
| `User-Agent` | `FoundryX-Webhooks/1.0` |
| `X-Fx-Event-Id` | the envelope `id` |
| `X-Fx-Event-Type` | the event type |
| `X-Fx-Timestamp` | unix seconds (signed) |
| `X-Fx-Signature` | `sha256=<hex hmac>` |

### Verifying the signature (do this on every request)

The signature is `HMAC-SHA256(signingSecret, "{X-Fx-Timestamp}." + rawRequestBody)`, hex-encoded, prefixed `sha256=`. **Sign over the raw bytes** — do not re-serialize the parsed JSON. Reject if the timestamp is more than \~5 minutes old (replay guard).

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

* **Success** = your endpoint returns HTTP `2xx` within **10 seconds**.
* **At-least-once**: retries mean you may see the same event `id` more than once — **be idempotent**.
* **Retry backoff**: \~1m, 5m, 25m, 1h, 6h (max **6 attempts**) then dead-letter.
* **Auto-disable**: after 10 consecutive dead-lettered events the endpoint flips to `AUTO_DISABLED`; a FoundryX admin must re-enable it (which resets the counter).
* Webhook delivery is fully isolated — a slow/broken consumer never blocks an inbound WhatsApp message.
* A **delivery log** is available in the dashboard (per-attempt status, response code, latency, error) for debugging.

### Registering / rotating (dashboard, per channel)

Webhook endpoints are created in the FoundryX dashboard against a **channel**: you supply `name`, `url` (https), and the `events` list; you receive the `whsec_…` **signing secret once**. You can rotate the secret (returns a new one), enable/disable, and delete. The URL is validated at registration (https-only, no private hosts).


---

## 8. Media

### `GET /omnichannel/media/{messageId}`

Fetch the binary for a media message. **Accepts your API key** (or an agent session). Workspace-scoped; streamed same-origin (no bucket redirect).

```bash
curl -L https://YOUR-FOUNDRYX-HOST/omnichannel/media/8dbc5265-… \
  -H "Authorization: Bearer fxw_live_…" -o file.bin
```

* Response headers: `Content-Security-Policy: sandbox`, `X-Content-Type-Options: nosniff`, `Cache-Control: private, max-age=300`.
* Unknown message / no media → `404`. No/invalid auth → `401`. Service disabled → `403`.
* In a `message.inbound` webhook the media message's `mediaUrl` is already the absolute form of this URL — just add your `Authorization` header when you fetch it.

### Two ways in: Bearer, or a signed link

| | `message.mediaUrl` (webhook, §9.2) | `message.url` (read endpoints, §9.1) |
|----|----|----|
| Form | `…/omnichannel/media/{id}` | `…/omnichannel/media/{id}?exp=…&sig=…` |
| Auth | your API key in `Authorization` | **the signature IS the auth** — no header |
| Lifetime | as long as the key is valid | **expires** (`media_signed_url_ttl_seconds`, default **1 hour**) |

The signed form exists so a media link is clickable — it opens in a plain browser tab with no header, which a Bearer URL cannot do. The HMAC binds the exact message id, so a link can't be re-pointed at another message.

> **⚠️ Never persist `message.url`.** It is a **capability URL with an expiry**, not a stable address. Store the `messageId` and re-read the message when you need a fresh link. A consumer that saves the URL into its own record will render a working image today and a wall of `401 "Invalid or expired media link."` tomorrow. Anyone holding an unexpired link can fetch that one blob without a key — treat it as a short-lived secret and keep it out of logs and client-side caches.


---

## 9. Reference — object shapes

**There are two families, and which one you get depends on the route:**

| Family | Where it appears | Style |
|----|----|----|
| **§9.1 `MessageObject` / `ContactObject`** | the `/api/v1/*` **read** endpoints (§6, §6a) | respond.io-shaped — `messageId`, `traffic`, nested `message{}`, epoch ints, a few snake_case keys |
| **§9.2 `MessageItem` / `ThreadItem`** | **webhook** payloads (§7) and the comment-create response (§6a) | FoundryX-shaped — `id`, `senderType`, flat fields, ISO-8601 `Z` datetimes |

This split is historical, not by design (§9.1 was introduced 2026-07-11 for respond.io parity). Both are stable and neither is going away without notice. If you consume both surfaces, normalise to one internal type at your boundary — §9.3 is the map.

---

### 9.1 Read-endpoint shapes (`/api/v1/*`)

#### `MessageObject`

Returned by `GET /contacts/{identifier}/messages` (inside `items[]`) and `GET …/messages/{messageId}`.

```jsonc
{
  "messageId": "099e061a-…",            // FoundryX durable id (use for reactions / correlation)
  "channelMessageId": "wamid.HBg…",     // Meta's wamid, null until the send lands
  "contactId": "fd5d6b58-…",
  "channelId": "31c4900f-…",
  "traffic": "incoming",                // incoming | outgoing  (see sender.source for notes)
  "timestamp": 1783172100,              // epoch SECONDS — present on EVERY message, in + out
  "message": {
    "type": "image",                    // text|image|video|audio|voice|document|sticker|
                                        //   interactive|interactive_reply|location|
                                        //   contacts|template|unsupported
    "text": null,                       // body of a TEXT-family message; null for media
    "url": "https://…/omnichannel/media/85c3fd9e-…?exp=…&sig=…",  // signed, see §8
    "caption": "Your receipt",          // a media message's body lives HERE, not in text
    "filename": "receipt.png",
    "mimeType": "image/png",
    "size": 39934,
    "payload": { … },                   // structured def — see below
    "messageTag": null
  },
  "status": [                           // delivery state; EMPTY for inbound
    { "value": "delivered", "timestamp": 1783172100, "message": null, "code": null }
  ],
  "sender": {
    "source": "user",                   // user (agent) | contact | system (internal note)
    "userId": "a533e094-…",             // set when source=user
    "teamId": null
  },
  "reactions": [ { "emoji": "👍", "reactorType": "AGENT", "reactor": "agent-1" } ],
  "replyTo": { "messageId": "…", "text": "…", "senderType": "CONTACT", "senderName": null }
}
```

Notes that bite if you miss them:

* **`timestamp` is the time key.** `status[]` is populated only once a delivery receipt exists and is **always empty for inbound** — never order on it.
* **`status[].value`** ∈ `pending | sent | delivered | read | failed`. On `failed`, `status[].message` is the free-text reason and **`status[].code` is Meta's numeric code** (e.g. `131047` re-engagement required, `131026` undeliverable) — branch on `code`, not on the message text, which is localised and unstable.
* **`status[].timestamp` is NOT the receipt time.** We don't record per-receipt times, so it equals the item's top-level `timestamp` (the message's creation time). Computing send→delivered latency from the two will always give `0`.
* **`message.type`** is lowercase. Two easily-missed values: `voice` is distinct from `audio` (a WhatsApp voice note is `"voice"`, so no separate boolean is needed), and **`interactive_reply`** is what you receive when a customer taps a quick-reply button or picks a list row — a different type from the `interactive` message you sent. Handle it explicitly; after plain text it's the most common inbound event.
* **`message.payload`** carries what cannot survive flattening into text, by type:
  * `interactive` → `{ kind, body, header?, footer?, buttons[] | sections[] | cta }`
  * `location` → `{ lat, lng, name, address }`
  * `contacts` → the contact-card array
  * `template` → the template binding
  * `null` for plain text/media. **`text` on an interactive/location message is a lossy human-readable summary — read `payload` for the real structure.**
* **`sender.source: "system"`** = an internal note (§6a), never delivered to the customer, even though `traffic` reads `"outgoing"`.
* Ids are **UUID strings**, not respond.io's int64 — the one unavoidable deviation from parity.

#### `ContactObject`

Returned by `GET /contacts` (inside `items[]`), `GET`/`PATCH /contacts/{identifier}`, and the conversation open/close routes. "The contact IS the thread."

```jsonc
{
  "id": "b2ad5218-…",                  // this is the contactId
  "firstName": "Jayson", "lastName": "Teh",
  "phone": "+60166753328",
  "email": null,
  "profilePic": null,
  "status": "open",                    // open | snoozed | closed  (LOWERCASE on read)
  "assignee": { "id": "…", "firstName": "…", "lastName": null, "email": "…" },
  "custom_fields": [ { "name": "orderId", "value": "ORD0001" } ],   // snake_case, respond.io parity
  "created_at": 1783173900,            // epoch SECONDS, snake_case — respond.io parity
  "cswExpiresAt": "2026-07-10T11:02:43Z",  // FoundryX extension — ISO-8601 Z, or null
  "language": null, "countryCode": null, "tags": [], "lifecycle": null, "isBlocked": false
}
```

* **`cswExpiresAt` decides free-form vs template** — if it is in the past or `null`, a free-form send will be refused with `409 csw_window_closed` and only an approved template re-engages. This is a FoundryX field with no respond.io equivalent, so it follows the house ISO-8601 `Z` convention rather than the epoch ints beside it.
* `custom_fields` and `created_at` are **snake_case on purpose** — respond.io spells them that way and this object mirrors respond.io exactly. Everything else is camelCase.
* `language`, `countryCode`, `tags`, `lifecycle`, `isBlocked` are parity placeholders we do not model — always `null`/`[]`/`false`.
* Not carried here: `priority`, `channelId`, `unreadCount`, `lastMessageAt`, `lastMessagePreview`. They exist on `ThreadItem` (§9.2), so **webhooks give you them** — `contact.updated` fires on assignment/status/priority changes.

---

### 9.2 Webhook shapes (§7) — unchanged

#### `MessageItem`

Embedded in `message.inbound` as `data.message`, and returned by the comment-create route (§6a).

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

#### `ThreadItem` (the `contact` in webhooks; "the contact IS the thread")

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

`cswExpiresAt` tells you whether free-form is currently allowed — if it's in the past, you must send a template to re-engage. It is on the read shape too (§9.1 `ContactObject`).

---

### 9.3 Migration map — §9.2 (webhook) ⇄ §9.1 (read)

If you built against an earlier revision of this guide, your wire types are §9.2. This is what to change to read `/api/v1` history and contacts.

**Message**

| §9.2 `MessageItem` | §9.1 `MessageObject` |
|----|----|
| `id` | `messageId` |
| `createdAt` (ISO) | `timestamp` (epoch **seconds**) |
| `senderType` `AGENT`/`CONTACT`/`SYSTEM` | `traffic` (`outgoing`/`incoming`/`outgoing`) + `sender.source` (`user`/`contact`/`system`) — **`sender.source` is the faithful one** |
| `senderId` | `sender.userId` |
| `senderName` | — (resolve from your own user directory, or read the webhook) |
| `messageType` (UPPER) | `message.type` (lower) |
| `body` (text) | `message.text` |
| `body` (media caption) | `message.caption` |
| `mediaUrl` | `message.url` — now absolute + signed (§8), no `Authorization` header needed |
| `mediaMime` / `mediaFilename` / `mediaSize` | `message.mimeType` / `message.filename` / `message.size` |
| `voice: true` | `message.type === "voice"` |
| `payload` | `message.payload` |
| `reactions[]` | `reactions[]` (identical) |
| `replyTo.id` / `.body` | `replyTo.messageId` / `.text` |
| `externalMessageId` | `channelMessageId` |
| `deliveryStatus` (single, UPPER) | `status[]` (array, lower) — take the last element's `value` |
| `errorCode` / `errorMessage` | `status[].code` / `status[].message` |

**Contact**

| §9.2 `ThreadItem` | §9.1 `ContactObject` |
|----|----|
| `id`, `phone` | same |
| `name` | `firstName` + `lastName` |
| `avatarUrl` | `profilePic` |
| `status` (UPPER) | `status` (lower) |
| `assignedUserId` / `assignedUserName` | `assignee.id` / `assignee.firstName` |
| `cswExpiresAt` | `cswExpiresAt` (same, ISO `Z`) |
| `createdAt` (ISO) | `created_at` (epoch seconds, snake_case) |
| `channelId`, `channelType`, `priority`, `unreadCount`, `lastMessageAt`, `lastIncomingMessageAt`, `lastMessagePreview` | not carried — read them from `contact.updated` / `message.inbound` webhooks |

**Envelopes**

| Before | Now |
|----|----|
| `{ contactId, data[], nextBefore }` | `{ items[], pagination: { next, previous } }` |
| `{ data[], total, page, pageSize }` | `{ items[], pagination: { next, previous } }` |
| `?before=<id>` only | `?before=<id>` (older) **and** `?after=<id>` (newer) |


---

## 10. Error reference (Consumer Gateway API)

All errors: `{ "error": { "code": "...", "message": "...", "details"?: ... } }`.

| Code | HTTP | Meaning / fix |
|----|----|----|
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
| `contact_not_found` | 404 | Contact not found / not in your workspace. |
| `message_not_found` | 404 | Message id not on that contact's thread. |
| `idempotency_in_progress` | 409 | A duplicate `Idempotency-Key` is still processing. |
| `invalid_media_url` / `media_fetch_failed` / `oversize` / `unsupported_media` / `transcode_failed` | 422 | Media fetch/validation failed (see §4.2). |


---

## 11. End-to-end quickstart


1. **Get credentials** from your FoundryX admin: an API key `fxw_live_…` and a webhook signing secret `whsec_…` (the admin registers your https callback URL and subscribes it to `message.inbound`, `message.status`, `message.reaction`).
2. **Stand up your webhook receiver** (§7) — verify signature, ack `2xx` fast, dedup on `id`, process async.
3. **Wait for an inbound message** (the user must message your WhatsApp number first to open the 24h window). You'll get a `message.inbound` webhook with `data.contact.id`.
4. **Reply free-form** within 24h:

   ```bash
   curl -X POST https://YOUR-FOUNDRYX-HOST/api/v1/omnichannel/messages \
     -H "Authorization: Bearer fxw_live_…" -H "Content-Type: application/json" \
     -d '{"to":"+60166753328","type":"text","text":{"body":"Thanks, on it!"}}'
   ```

   → `202 {"id":"…","status":"queued"}`. Watch for the `message.status` webhook.
5. **Outside 24h?** Check `cswExpiresAt` on the contact (§6a); if it's past or `null`, list templates (`GET /templates`) and send `type:"template"`.
6. **Pull history** any time: `GET /contacts/{contactId}/messages` → `{items, pagination}` of `MessageObject` (§9.1). Order on `timestamp`.
7. **Fetch media** from `message.url` — it's absolute and pre-signed, so it opens on a plain click (§8).


---

## 12. Embedding the conversation UI (iframe widget)

Instead of building your own chat UI (Option A), you can embed **our** conversation UI as a **chromeless, token-authed** `**<iframe>**` on any page of your app — e.g. the right-hand column of a CRM lead page. The iframe is the SAME inbox UI FoundryX runs internally (rich message types, media, templates, quick replies, live updates), with no app shell (no sidebar/header/login).

**Security model in one line:** the browser never holds the API key. Your **server** signs a short-lived **assertion** naming exactly one workspace + one contact (or the whole inbox) + a set of capabilities; FoundryX verifies it, mints a 15-minute access token scoped to that, and **re-checks the scope + caps on every API/WS call server-side** — the widget can never widen beyond what you signed. (Full rationale: §12.7.)

### 12.1 One-time setup — FoundryX side (operator)

Ask your FoundryX operator to create an **embed connection** for you on the workspace. It is a `connections` row with provider `**omnichannel_shared**` carrying two fields:

| Field | Meaning | Stored |
|----|----|----|
| `embedSecret` | the HMAC secret you sign assertions with (per connection) | **Fernet-encrypted, write-only** — set once, never echoed back |
| `allowedOrigins` | the exact parent origins allowed to embed + postMessage (e.g. `https://crm.acme.com`) | plain (drives `frame-ancestors` + the origin check) |

This is all done in the FoundryX dashboard at **Omnichannel ▸ Settings ▸ Embed access** (a shared-service login with `workspaces.manage` — e.g. your system admin):

* **Connection id** — copy it; it's the non-secret `?c=` / `iss` value (§12.2–12.3).
* **Embed secret** — click **Generate / Rotate**; the plaintext is shown **once** — copy it into your backend's secret store. Rotating instantly invalidates outstanding assertions.
* **Allowed origins** — add each parent origin permitted to embed (e.g. `https://crm.acme.com`).
* **Iframe snippet** — pick a workspace + thread/inbox and copy the ready-to-paste `<iframe>`.

That's it — no per-agent accounts on FoundryX; your *agents* never log in here (only the admin who configures this once). Your agents are federated via the assertion's `sub` (§12.2).

> **One embed connection = one consumer.** The `embedSecret` is per connection; a leak forges agents for that one connection only. Rotating `embedSecret` instantly invalidates every outstanding assertion.

### 12.2 The assertion (what your server mints)

A short-lived **JWT,** `**HS256**`**, signed with** `**embedSecret**` — minted **server-side only, never in the browser**.

| Claim | Type | Meaning |
|----|----|----|
| `iss` | string | the **connection id** from §12.1 |
| `aud` | string | `**"omnichannel-embed"**` (exact; anything else is rejected) |
| `sub` | string | your agent's stable user id — `(iss, sub)` is the federated identity FoundryX attributes replies to |
| `workspaceId` | string | the target workspace |
| `scope` | string | `**"inbox"**` (whole workspace) or `**"thread:<contactId>"**` (one thread) |
| `name` | string | agent display name (shown as "sent by") |
| `email` / `avatarUrl` | string? | optional agent profile |
| `caps` | string\[\] | subset of `["reply","assign","close","note","send_template"]`, or `["read_only"]` |
| `allowedOrigins` | string\[\] | your parent origins (mirrors the connection's `allowedOrigins`) |
| `iat` | number | issued-at (epoch seconds) |
| `exp` | number | `iat + 900` (15 min) |
| `jti` | string | unique id — **single-use**; mint a FRESH one for every handshake (see §12.4) |

`contactId` = the FoundryX contact id you already store per record (from the `message.inbound` webhook's `data.contact.id`, or a `GET /contacts` lookup). This is the only mapping you own: "this lead ↔ this FoundryX contact." FoundryX enforces the rest.

**Server-side mint (Node example):**

```js
import jwt from 'jsonwebtoken';
import { randomUUID } from 'crypto';

// Called by YOUR backend when the browser asks for an assertion (never in the browser).
function mintEmbedAssertion({ contactId, agent }) {
  const now = Math.floor(Date.now() / 1000);
  return jwt.sign({
    iss: process.env.FX_EMBED_CONNECTION_ID,      // the connection id
    aud: 'omnichannel-embed',
    sub: agent.id,
    workspaceId: process.env.FX_WORKSPACE_ID,
    scope: `thread:${contactId}`,                 // or 'inbox'
    name: agent.name,
    email: agent.email,
    caps: agent.canReply ? ['reply','send_template','note'] : ['read_only'],
    allowedOrigins: ['https://crm.acme.com'],
    iat: now,
    exp: now + 900,
    jti: randomUUID(),
  }, process.env.FX_EMBED_SECRET, { algorithm: 'HS256' });
}
```

Expose it as an endpoint on **your** app (e.g. `GET /internal/fx-embed-assertion?leadId=…`) that maps the lead → contactId, checks the agent's own RBAC to decide `caps`, and returns `{ assertion }`. **Never ship** `**embedSecret**` **to the browser.**

### 12.3 Mount the iframe

```html
<iframe
  src="https://YOUR-FOUNDRYX-HOST/embed/omnichannel/thread?c=<connectionId>"
  style="width:100%; height:100%; border:0;"
  allow="clipboard-write">
</iframe>
```

* `?c=<connectionId>` — the **non-secret connection id** (= `iss`). It drives the `frame-ancestors` CSP (§12.7). The **assertion is NEVER in the URL** — it arrives via postMessage.
* **Sizing (your box, our fill):** the widget fills 100% of the iframe and reflows with no horizontal scroll down to \~375px. The message list **scrolls internally** and the composer pins to the bottom, so a long thread never stretches the iframe — just give the `<iframe>` an explicit height (your column's height, or `100vh`).
* **Routes:** `/embed/omnichannel/thread` (scope `thread:<contactId>`, messages-only side-panel by default) · `/embed/omnichannel/inbox` (scope `inbox`, full workspace inbox — this one also posts `resize {height}` so you can auto-size it).

### 12.4 The postMessage handshake

Envelope for every message: `{ v: 1, type, payload }`. **Validate** `**event.origin**` **on every message** (accept only the FoundryX embed origin) — never `*`.

```js
const FX_ORIGIN = 'https://YOUR-FOUNDRYX-HOST';
const iframe = document.getElementById('fx');

window.addEventListener('message', async (e) => {
  if (e.origin !== FX_ORIGIN) return;                 // trust only the widget origin
  const msg = e.data;
  if (!msg || msg.v !== 1) return;

  if (msg.type === 'ready' || msg.type === 'needToken') {
    // Mint a FRESH assertion from YOUR server for EACH ready/needToken (single-use).
    const { assertion } = await fetch(`/internal/fx-embed-assertion?leadId=${leadId}`).then(r => r.json());
    iframe.contentWindow.postMessage(
      { v: 1, type: msg.type === 'ready' ? 'init' : 'token',
        payload: { assertion, theme: { primary: '#7c3aed' }, colorScheme: 'light' } },
      FX_ORIGIN,                                       // origin-pinned, never '*'
    );
  }
  if (msg.type === 'activity') { /* {kind, contactId} — refresh "last contacted", NO content */ }
  if (msg.type === 'resize')   { /* {height} — inbox mode: size the iframe */ }
});
```

Message types:

| Direction | type | payload | when |
|----|----|----|----|
| widget → you | `ready` | `{}` | mounted; asking for `init` |
| widget → you | `needToken` | `{}` | token near expiry; mint a fresh assertion |
| widget → you | `resize` | `{ height }` | content height changed (inbox mode) |
| widget → you | `activity` | `{ kind, contactId }` | coarse "message sent/received/assigned" — refresh your record's last-contacted. **No message content crosses the boundary.** |
| you → widget | `init` | `{ assertion, theme, colorScheme }` | reply to `ready` — starts the session + first paint |
| you → widget | `token` | `{ assertion }` | reply to `needToken` — silent refresh |
| you → widget | `theme` | `{ theme, colorScheme }` | live re-skin (dark toggle / rebrand) |

> **MUST — one fresh assertion per handshake.** Assertions are single-use (`jti`). Mint a new one for **every** `ready` and **every** `needToken`; never cache/reuse. Reusing one → `401 replayed` on the second use. (The widget minimises re-`ready`, but correctness rests on you minting fresh.)

`theme` = whitelisted brand primitives (`{ primary, surface, text, bubbleIn, bubbleOut, radius, … }`); `colorScheme` = `"light" | "dark"`.

### 12.5 Scopes — the widget only ever sees what you signed

* `**thread:<contactId>**` — the widget can read/act on **only that contact**. Any attempt (via the UI or a hand-crafted API call with the token) to read another contact's thread, or to list the workspace, returns `**403**`. The live WebSocket is filtered server-side too — it only receives that contact's events.
* `**inbox**` — the token can list + open every thread in the workspace.
* **Cross-workspace is impossible:** the token is bound to one `workspaceId`; a query for another workspace's data is refused. A token minted by connection A can never touch connection B's data.

### 12.6 Capabilities — writes are enforced server-side

Put the agent's real permissions in `caps`. FoundryX rejects (`403`) any write whose cap is absent, **regardless of what the widget shows** (hiding a button is UX only):

| cap | unlocks |
|----|----|
| `reply` | send free-form / media / interactive / location / contacts |
| `send_template` | send an approved template (outside the 24h window) |
| `assign` | assign / reassign the thread |
| `close` | snooze / close / reopen |
| `note` | add an internal note |
| `read_only` | read only — every write `403`s |

### 12.7 Security recap (all enforced by FoundryX, not the widget)


1. **Replay** — `jti` single-use, 15-min assertion TTL.
2. **Scope** — thread-scoped tokens cannot widen (server-checked every request, incl. WS).
3. **Caps** — every write cap re-checked server-side.
4. **Blast radius = one connection** — `embedSecret` per connection, rotatable.
5. **Clickjacking** — the embed page emits `Content-Security-Policy: frame-ancestors <your allowedOrigins>` (resolved from `?c=<connectionId>`), so no other site can frame it. Absent/unknown `?c=` → `frame-ancestors 'none'`.
6. **postMessage** — origin-validated both directions; never `*`.
7. **Throttled** — `/embed/session` rides the platform IP throttle.

### 12.8 Endpoints (embed)

| Method | Path | Auth | Purpose |
|----|----|----|----|
| GET | `/embed/omnichannel/thread?c=<connectionId>` | none (boots bare) | chromeless single-thread widget page |
| GET | `/embed/omnichannel/inbox?c=<connectionId>` | none (boots bare) | chromeless full-inbox widget page |
| POST | `/embed/session` | the assertion IS the credential | widget exchanges assertion → access token (called by the widget, not you) |
| GET | `/embed/frame-policy?c=<connectionId>` | none | `frame-ancestors` source (used by the platform middleware) |

Everything else (conversation reads/sends, templates, quick-replies, members, WebSocket) is the **same** omnichannel API the internal inbox uses — the widget calls it with the embed access token as `Authorization: Bearer …`; you don't call those directly in Option B.

### 12.9 Troubleshooting

| Symptom | Cause / fix |
|----|----|
| Widget spins forever | It never got `init`. Your parent must reply to `ready` with `init { assertion }`. Opening the embed URL directly (no parent) always spins — by design. |
| `401 invalid_assertion` | Bad signature (wrong `embedSecret`), wrong `aud`, malformed JWT, or unknown `iss`. |
| `401 replayed` | You reused an assertion. Mint a fresh one per `ready`/`needToken` (§12.4). |
| `401 expired` | Assertion older than 15 min, or clocks skewed >60s. |
| `403 origin_not_allowed` | The parent origin you're embedding from isn't in the connection's `allowedOrigins`. |
| Browser refuses to frame it ("refused to display / frame-ancestors") | Your origin isn't in `allowedOrigins`, or you didn't pass `?c=<connectionId>`. |
| `403` on a reply/assign | The token's `caps` don't include that action (or it's `read_only`). |
| Empty / wrong thread | Wrong `contactId` in the `scope`, or wrong `workspaceId`. |


---

## 13. Developer Logs Console — troubleshooting your integration

Both integration paths (the API in §2–§11 and the embed in §12) used to be fire-and-forget: if a send didn't arrive or an embed token was rejected, there was nowhere to look. The **Developers ▸ Logs** console fixes that — it's a single, source-tagged activity feed of **everything your integration does**, with **trace-id correlation** so one consumption is visible end-to-end.

> **Where it lives.** In the FoundryX **dashboard** (session login), under **Developers ▸ Logs**. It is **not** a consumer API — your engineer views it in the UI. Access needs a shared-service login with the `integration_logs.read` permission (your system admin, or ask your FoundryX operator to open it for you). Data is **tenant-scoped** — you see only your own tenant's activity.

### 13.1 What gets logged (four sources, one feed)

| Source | Captures | Example `operation` |
|----|----|----|
| `**inbound_api**` | Every call you make to `/api/v1/omnichannel/*` (§2–§11) — latency + status, incl. failures | `POST /messages`, `GET /contacts` |
| `**outbound_meta**` | FoundryX's resulting call to the Meta/WhatsApp Graph API (send, template submit, sync) | `graph:send` |
| `**webhook_delivery**` | Each attempt to POST an event to **your** callback URL (§7) — merged in from the per-channel delivery log | `webhook:message.status` |
| `**embed_session**` | Each embed assertion → access-token exchange (§12) — success or the typed rejection | `embed:session` |

Each row carries: **source**, **operation**, **status** (`success` / `error` / `pending`), the **HTTP / Meta status code**, an **error code** (e.g. `csw_window_closed`, `invalid_api_key`, `expired`), **latency (ms)**, the **workspace**, which **API key** made the call, an **external ref** (the Meta `wamid` or webhook event id), and the **timestamp**.

### 13.2 Trace correlation — one consumption, end-to-end

The console mints a **trace id** on each inbound gateway call and threads it through the work that call triggers. So a single "send a message" fans out to correlated legs:

```
trace 7f3c…  ┌─ inbound_api      POST /messages            202  18ms
             ├─ outbound_meta    graph:send                200  240ms   wamid=wamid.HBg…
             └─ webhook_delivery  webhook:message.status    200  95ms    (DELIVERED → your URL)
```

Open any row → the **trace timeline** shows every leg with its status and latency. The async `message.status` delivery (which only knows the `wamid`) is joined back to the originating trace by that external ref — so you can follow **your API call → the Meta send → the delivery receipt back to you** in one view. This is the fastest way to answer "where did my message stop?":

* error on the `**inbound_api**` leg → your request was rejected (bad body, closed 24h window, unknown template) — the `error_code` says which (cross-ref §10).
* `inbound_api` OK but `**outbound_meta**` errored → Meta rejected the send (the leg carries the Graph status + reason).
* both OK but the `**webhook_delivery**` leg is failing/retrying → your callback URL is down or slow (see the response code + §7 retry/auto-disable rules).

### 13.3 Redaction & retention

* **Redaction.** Request/response bodies are stored **redacted** — any `Authorization`, API key, token, secret, `assertion`, `embedSecret`, or password field is masked to `***`. WhatsApp **message text is preserved** (it's content, not a credential), so you can still see what was sent.
* **Retention.** Rows are pruned per tenant — default **30 days**. An admin with `integration_logs.manage` can change the window in **Developers ▸ Logs ▸ Settings**.

### 13.4 Finding things

Filter by **source**, **status**, **time**, or **workspace**; search by request **path**, **trace id**, or **external ref** (paste a `wamid` or a webhook event id to jump straight to the consumption it belongs to). The console is generic and core — as FoundryX adds more consumable services, they log to this **same** feed.

> This complements, and now unifies, the older per-channel **webhook Deliveries** dialog (§7) — webhook attempts appear here too, correlated to the send that caused them.


---

## Appendix — quick endpoint index

**Consumer Gateway (API key):**

| Method | Path | Purpose | Returns |
|----|----|----|----|
| POST | `/api/v1/omnichannel/messages` | Send a message (all types) | `202 {id, status, idempotencyReplay}` |
| GET | `/api/v1/omnichannel/templates` | List approved templates | `{data[]}` |
| GET | `/api/v1/omnichannel/contacts` | List contacts (filters + paging) | `{items[], pagination}` of `ContactObject` §9.1 |
| GET | `/api/v1/omnichannel/contacts/{identifier}` | Get a contact | `ContactObject` §9.1 |
| PATCH | `/api/v1/omnichannel/contacts/{identifier}` | Update contact (name/priority/assignee/fields) | `ContactObject` §9.1 |
| GET | `/api/v1/omnichannel/contacts/{identifier}/messages` | Message history | `{items[], pagination}` of `MessageObject` §9.1 |
| GET | `/api/v1/omnichannel/contacts/{identifier}/messages/{messageId}` | Get one message | `MessageObject` §9.1 |
| POST | `/api/v1/omnichannel/contacts/{identifier}/conversation/open` | Open conversation | `ContactObject` §9.1 |
| POST | `/api/v1/omnichannel/contacts/{identifier}/conversation/close` | Close conversation | `ContactObject` §9.1 |
| POST | `/api/v1/omnichannel/contacts/{identifier}/comments` | Add internal note | `201` `MessageItem` **§9.2** |
| GET | `/omnichannel/media/{messageId}` | Fetch media bytes | binary |

`{identifier}` = `phone:+60…` | `id:<uuid>` | bare `<uuid>`.

Note the odd one out: **comment-create returns the §9.2 shape**, every other row returns §9.1.

**Managed for you in the FoundryX dashboard (session-authed):** workspace + channel onboarding (Embedded Signup), API-key mint/revoke, webhook register/rotate/enable/disable + delivery log, template authoring/submission.

**Troubleshooting in the FoundryX dashboard (session-authed,** `**integration_logs.read**`**):** **Developers ▸ Logs** — one trace-correlated activity feed across inbound API calls, outbound Meta calls, webhook deliveries, and embed sessions; redacted bodies; per-tenant retention (default 30 days). See §13.

**Webhooks (FoundryX → your https URL):** `message.inbound`, `message.status`, `message.reaction`, `contact.updated` — signed with `X-Fx-Signature`.

**Embed the UI (Option B, §12) — assertion signed with** `**embedSecret**`**:**

| Method | Path | Purpose |
|----|----|----|
| GET | `/embed/omnichannel/thread?c=<connectionId>` | chromeless single-thread widget |
| GET | `/embed/omnichannel/inbox?c=<connectionId>` | chromeless full-inbox widget |
| POST | `/embed/session` | widget exchanges assertion → 15-min access token (widget-called) |
| GET | `/embed/frame-policy?c=<connectionId>` | `frame-ancestors` origin source |

**Managed for you in the FoundryX dashboard (session-authed) for embedding:** the operator creates the `**omnichannel_shared**` **connection** carrying your `embedSecret` (write-only) + `allowedOrigins`, and gives you the **connection id**. You mint assertions server-side (§12.2) and run the postMessage handshake (§12.4).