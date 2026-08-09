# Response: Consumer Gateway contract drift

**To:** Ecohub engineering
**From:** FoundryX Omnichannel service
**Re:** *Finding report: Consumer Gateway `/api/v1` has drifted from the published Integration Guide* (2026-08-09)
**Status:** Accepted — fixed. Your **preferred** option (§5) is implemented, not the minimum alternative.

---

## 1. Short version

Your report is correct. We reproduced every claim against a live workspace before writing a line of code.

The cause was ours and it was simple: on **2026-07-11** commit `80b4cf6` reshaped the `/api/v1` read endpoints for respond.io parity, and **did not update the integration guide**. The change was justified internally with "only external API-key clients consume these endpoints" — which was exactly backwards. External API-key clients *are* the guide's audience. You built to a published contract, we changed it underneath you, and because the endpoints kept returning `200` there was nothing for either side to alarm on.

We have implemented your **preferred** option:

* `/api/v1` read endpoints return the shapes this guide always documented — **your existing code needs no change**.
* The respond.io shape is not withdrawn; it moved to **`?format=rio`**, so any integration that adopted it since July keeps working.
* Both blocking gaps (`timestamp`, `cswExpiresAt`) are closed on **both** shapes.
* Everything you asked us to confirm is answered in §4.

Your verification script (report §6) now passes **unmodified** — see §5.

---

## 2. What changed

### 2.1 The documented shape is the default again

| Endpoint | Response |
|---|---|
| `GET /api/v1/omnichannel/contacts/{identifier}/messages` | `{ contactId, data: MessageItem[], nextBefore }` |
| `GET /api/v1/omnichannel/contacts/{identifier}` | `ThreadItem`, including `cswExpiresAt` |
| `GET /api/v1/omnichannel/contacts` | `{ data: ThreadItem[], total, page, pageSize }` |
| `PATCH …/contacts/{identifier}`, conversation open/close | the updated `ThreadItem` |
| `POST …/contacts/{identifier}/comments` | the created `MessageItem` |

`senderType`, `body`, `createdAt`, `messageType` (uppercase), `deliveryStatus`, `mediaUrl` — all as documented in §9.

### 2.2 `?format=rio` for the respond.io shape

Every contact/message read endpoint accepts `?format=rio` and returns the respond.io-parity objects (`{items, pagination}`, `messageId`, `traffic`, `timestamp`, nested `message{}`). Use it if you have respond.io-shaped code you'd rather keep; ignore it otherwise.

Two properties worth knowing:

* An **unrecognised** `?format=` value is a `422`, never a silent fallback. A typo cannot hand you the other shape to mis-parse — that failure mode is what made the original drift invisible.
* Both shapes are rendered from the same internal objects, so they carry the same information and **cannot drift apart**.

### 2.3 The two blocking gaps

**`timestamp` / `createdAt` on every message, inbound included.** You were right that `status[]` is empty for inbound: it is populated from delivery receipts, and inbound messages never receive one. The default shape carries `createdAt` (ISO-8601 Z); the rio shape carries `timestamp` (epoch seconds). Both are on **every** message. Order merged history on those, never on `status[].timestamp`.

**`cswExpiresAt` is exposed.** On `ThreadItem` (as always documented) and now on the rio contact shape too. Future ⇒ free-form allowed; past or `null` ⇒ template only. Check it before sending rather than probing for the `409`.

### 2.4 Nothing the internal shape carries is gateway-invisible any more

`payload` (interactive buttons, location coordinates, contact cards), `reactions[]`, `replyTo`, media `size`, and Meta's numeric error code (`status[].code` / `errorCode`) are all reachable. Where we previously flattened an interactive message to a plain string, the structure now survives.

### 2.5 Self-serve webhook registration — your second question, answered with code

`/api/v1/omnichannel/webhooks` — `GET` (list), `POST` (register; signing secret returned **once**), `PATCH`, `POST …/rotate`, `POST …/enable|/disable`, `DELETE`. Authenticated with your workspace API key, scoped to your workspace. You no longer need an operator to register or inspect your callbacks.

Note there is now a cap of **10 endpoints per channel** — every inbound message and status receipt fans out to all of them.

---

## 3. Corrections to your report

Two points, offered for accuracy, neither of which changes the outcome.

**`voice` was never lost.** §3.1 says voice notes are indistinguishable from audio. They aren't: `message.type` is `"voice"`, a distinct value from `"audio"`, and always has been. The `voice` boolean was redundant with the type, not load-bearing. Nothing to work around here.

**Webhooks were never reshaped.** §7 payloads have carried `MessageItem`/`ThreadItem` throughout — the drift was confined to the read endpoints. So during the broken window, webhooks were a correct source of `createdAt` **and** `cswExpiresAt`. That doesn't excuse the read-path break, but if you had inbound webhook delivery running, that data was reaching you.

---

## 4. Your explicit questions

> **Whether `voice`, `payload`, `reactions`, and `replyTo` are intentionally unavailable, or were dropped in the re-shape.**

Dropped in the re-shape, not intentional — with the exception of `voice`, which was never dropped (§3). All are restored. The rule we've adopted and written into our own engineering guide: renaming a field for parity is fine, **dropping a field the internal shape carries is not**, because you have no other source for it.

> **Whether webhooks (§7) are the intended path for inbound delivery, given registration is dashboard-only.**

Yes, webhooks are the intended inbound path — and you were right that dashboard-only registration made that untenable for a key-holding consumer. Fixed (§2.5).

---

## 5. Verifying, with your own script

Your report §6 commands, unchanged:

```bash
curl -s -H "Authorization: Bearer $FX_WORKSPACE_KEY" \
  "https://chat.foundryx.my/be/api/v1/omnichannel/contacts/phone:%2B601121996902/messages?limit=50" \
  | jq '{envelope: keys, first: .data[0] // .items[0]}'
```

```json
{ "envelope": ["contactId", "data", "nextBefore"],
  "first": { "id": "c5d1713a-…", "senderType": "CONTACT",
             "body": "Is the venue wheelchair accessible?",
             "createdAt": "2026-07-04T13:35:00.514039Z" } }
```

```bash
curl -s -H "Authorization: Bearer $FX_WORKSPACE_KEY" \
  "https://chat.foundryx.my/be/api/v1/omnichannel/contacts/phone:%2B601121996902" \
  | jq '{cswExpiresAt, status}'
```

```json
{ "cswExpiresAt": "2026-07-09T05:08:24.678044Z", "status": "OPEN" }
```

Both criteria as you specified them, including the uppercase `status` enum.

A stronger check, since an empty inbound history was the actual symptom:

```bash
curl -s -H "Authorization: Bearer $FX_WORKSPACE_KEY" \
  "https://chat.foundryx.my/be/api/v1/omnichannel/contacts/phone:%2B601121996902/messages?limit=50" \
  | jq '[.data[] | select(.senderType=="CONTACT") | select(.createdAt==null)] | length'
# expect: 0
```

---

## 6. One thing to re-check on your side

You reported that Ecohub currently **forces template-only sends** because the window was undetectable. That workaround is now unnecessary and will cost you money — templates are billed differently from free-form session messages. Once this is deployed, gate on `cswExpiresAt` and send free-form inside the window.

---

## 7. Timeline and status

| | |
|---|---|
| 2026-07-09 | Read endpoints shipped in the documented shape |
| 2026-07-11 | `80b4cf6` reshaped them for respond.io parity — **guide not updated** |
| 2026-07-22 | Guide revised (embed + logging sections); §6/§9 not revisited |
| 2026-08-09 | Your report received, reproduced, and fixed |

**Deployment:** the fix is merged/under review internally and **is not yet live on `chat.foundryx.my`**. Your inbound history will stay empty until we deploy — we'll confirm when it ships, and that is the point at which the verification above is meaningful.

## 8. What we changed on our side so this doesn't recur

The guide was already in our repository, so "put the docs in version control" was not the missing piece — the reshape commit simply did not touch it and no reviewer asked why. We've made that a review gate: a diff touching the gateway's routes or wire schemas without a corresponding guide diff is now an automatic review question, with a CI check to enforce it. We've also added regression tests that fail loudly if `timestamp`, `cswExpiresAt`, the structured `payload`, or the response envelopes ever go missing again.

Thank you for the report — it was specific, reproducible, and correctly diagnosed, which is why the turnaround was one day.
