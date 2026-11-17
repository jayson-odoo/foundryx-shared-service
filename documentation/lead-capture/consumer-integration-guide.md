# Lead Capture - consumer integration guide

Contract of record for the Lead Capture gateway (plan 64, AC-64-66). A change to any gateway route, header, body
field or error code ships with a change to this file in the same pull request.

Status: release 1 prototype. Sources: Facebook Page Instant Forms. Instagram, connect sessions, `lead.updated` and
`source.updated` events and the duplicate rule arrive in later releases and will be added here first.

Everything is per product (one Shared Service tenant per consuming CRM): its own key, its own endpoints and signing
secrets, its own lead field list and field maps. Two CRMs reading the same Facebook Page each receive the lead in
their own field names.

## 1. Authentication

Every gateway call carries a Lead Capture key:

```
Authorization: Bearer fxl_live_<secret>
```

- A Shared Service admin creates the first key (Lead Capture > Keys, or `POST /lead-capture/keys` while signed in).
  After that, a key holder can list, create and revoke the product's keys itself (`/keys`, section 3), so the
  product can show a Keys screen in its own app. The full key is shown once; afterwards only `fxl_live_****` + its
  last 4 characters is shown.
- The key decides the tenant. Nothing in a request body or query chooses it.
- A missing, malformed, unknown or revoked key answers `401 invalid_api_key`. Too many `401`s from one IP answer
  `429 rate_limited` with `Retry-After`. Each key has a request budget (600 calls per 5 minutes by default); over it
  answers `429 rate_limited`.
- Lead Capture not installed or switched off for the tenant, or the tenant suspended: `403 service_not_enabled`.

Base URL: `https://<shared-service-host>/api/v1/lead-capture` (behind the frontend proxy the host path is `/be`).

## 2. Errors

Every gateway error has one shape:

```json
{"error": {"code": "invalid_cursor", "message": "The cursor is not valid."}}
```

| HTTP | code | When |
|---|---|---|
| 401 | `invalid_api_key` | Missing, malformed, unknown or revoked key |
| 403 | `service_not_enabled` | Module off for the tenant, or tenant suspended |
| 404 | `endpoint_not_found` | Webhook id not found for this tenant |
| 404 | `source_not_found` | Source id not found for this tenant |
| 404 | `delivery_not_found` | Delivery id not found for this tenant |
| 404 | `key_not_found` | Key id not found for this tenant |
| 400 | `token_invalid` | Meta no longer accepts the source's Page token (or it has none): reconnect the Page |
| 400 | `meta_refused` | Meta refused the form or test-lead call; `message` is Meta's reason, cleaned |
| 409 | `endpoint_limit` | Already 5 webhook endpoints |
| 409 | `source_not_connected` | Test lead for a source that is not receiving leads (`NEEDS_RECONNECT`, `DISCONNECTED`, `DRAFT`): reconnect first |
| 409 | `test_lead_exists` | Meta still holds the form's previous test lead after clearing it; delete it in Meta's Lead Ads Testing Tool, then retry |
| 409 | `lead_purged` | Redeliver of a lead whose personal data was deleted |
| 409 | `key_in_use` | Revoke of the key the request itself uses: revoke it with another key |
| 422 | `invalid_request` | Body or query fails validation (e.g. `limit=500`, no `url`); `details` lists the fields |
| 422 | `invalid_url` | Callback URL is not public `https://` |
| 422 | `invalid_fields` | Field list: bad key, repeated key, unknown type, more than 50 |
| 422 | `invalid_field_map` | Field map: bad form id, target not in your field list |
| 422 | `invalid_events` | No event, or an unknown event |
| 422 | `invalid_form_id` | `formId` is not an Instant Form id (digits only) |
| 422 | `invalid_cursor` | `cursor` is not one this API returned |
| 422 | `invalid_since` | `since` is not an ISO-8601 time |
| 429 | `rate_limited` | Throttled; see `Retry-After` |
| 502 | `meta_unreachable` | Meta could not be reached for a form or test-lead call; try again |

## 3. Routes

| Method | Path | Body / query | Answer |
|---|---|---|---|
| GET | `/sources` | - | `{"data": [Source]}` |
| GET | `/settings` | - | `Settings` |
| PUT | `/settings` | `{"allowSharedPages": bool}` | `Settings` |
| GET | `/fields` | - | `{"data": [Field], "isDefault"}` |
| PUT | `/fields` | `[Field]` (replaces the list; `[]` = defaults) | `{"data": [Field], "isDefault"}` |
| GET | `/sources/{id}/forms/{formId}/questions` | - | `{"formId", "formName", "data": [Question]}` |
| POST | `/sources/{id}/test-lead` | `{"formId": "<form id>"}` | `202` `{"formId"}` |
| PUT | `/sources/{id}/field-map` | `{"formId": "<form id>" or "*", "map": {"<question key>": "<field key>"}}` | `Source` |
| GET | `/webhooks` | - | `{"data": [Webhook]}` |
| POST | `/webhooks` | `{"url", "events"}` | `201` `Webhook` + `secret` (shown once) |
| DELETE | `/webhooks/{id}` | - | `204` |
| POST | `/webhooks/{id}/test` | - | `202` `Delivery` (one signed sample lead, `isTest: true`, to that endpoint only) |
| GET | `/keys` | - | `{"data": [Key]}` (newest first, revoked keys included) |
| POST | `/keys` | `{"name"}` | `201` `Key` + `key` (the full key, shown once) |
| DELETE | `/keys/{id}` | - | `204` (revoked at once; `409 key_in_use` for the calling key) |
| GET | `/leads` | `since`, `cursor`, `source`, `limit` (1-100, default 50) | `{"data": [Lead], "nextCursor", "hasMore"}` |
| POST | `/deliveries/{id}/redeliver` | - | `Delivery` |

### Source

```json
{
  "id": "4c1f...",
  "platform": "facebook",
  "name": "Foundryx",
  "status": "LIVE",
  "pageId": "300000000000001",
  "pageName": "Foundryx",
  "formsMode": "all",
  "needsMapping": [{"formId": "400000000000001", "formName": "S-META test 1", "unmappedCount": 1}],
  "fieldMap": {"*": {"interest": "product_interest"}},
  "lastLeadAt": "2026-11-15T05:19:16Z",
  "createdAt": "2026-11-15T05:00:00Z"
}
```

`status` is one of `DRAFT`, `WAITING_FOR_TEST`, `LIVE`, `NEEDS_RECONNECT`, `DISCONNECTED`. A newly connected Page is
`WAITING_FOR_TEST` until its first test lead (`isTest: true`) is received, then `LIVE`. Leads, test or real, are
stored and delivered in both states; only a test lead moves it to `LIVE`. Reconnecting a `WAITING_FOR_TEST` or `LIVE`
source keeps its id and status. On a Page shared by several products, Meta's test lead reaches every product on the
Page, so it moves each product's waiting source to `LIVE`.
`needsMapping` lists forms
whose leads arrived with no field map and had answers that went to notes: those leads were still delivered.
Saving a map for that form (or for `"*"`) clears its entry.

### Field and field map

Your CRM's own lead fields are the targets:

```json
[{"key": "contact_name", "label": "Contact", "type": "name"},
 {"key": "mobile_no", "label": "Mobile", "type": "phone"},
 {"key": "email_address", "label": "Email", "type": "email"},
 {"key": "product_interest", "label": "Interest", "type": "text"},
 {"key": "remarks", "label": "Remarks", "type": "notes"}]
```

- `key`: letters, digits, `_`, starting with a letter, at most 64; unique. `type`: `name`, `phone`, `email`,
  `notes` or `text`. At most 50 fields.
- With no list published, the targets are `name` (name), `phone` (phone), `email` (email), `notes` (notes).
- Saving the field list (`PUT /fields`, `[]` included) removes every field-map line whose field is no longer in the
  list, on every source, in the same call; a form left with no line loses its map.
- A source's field map says which form question fills which field: `"*"` applies to every form, a form's own map
  wins over it. Question keys are the Facebook form's question keys (as in `answers[].key`); a `null` or `""` target
  removes that entry; an empty `map` removes the form's map.
- Per answer: the mapped field; else Facebook's standard questions fill the first field of their type (`full_name`,
  or `first_name` + `last_name` -> `name`; `email` -> `email`; `phone_number` -> `phone`); else one `key: value` line
  in the first `notes`-type field (none: the answer is only in `answers`).

### Form questions

`GET /sources/{id}/forms/{formId}/questions` reads the Instant Form's questions from Meta with the source's Page
token, so your mapping screen can show real labels and your CRM can keep its own lookup of choice answers:

```json
{"formId": "400000000000001", "formName": "Solar enquiry",
 "data": [
   {"key": "full_name", "label": "Full name", "type": "FULL_NAME", "options": []},
   {"key": "interest", "label": "What are you interested in?", "type": "CUSTOM",
    "options": [{"key": "solar", "value": "Solar panels"}, {"key": "battery", "value": "Battery"}]}
 ]}
```

- `key` is the question key used in the field map and in a lead's `answers[].key`. `type` is Meta's question type
  as given (`FULL_NAME`, `EMAIL`, `PHONE`, `CUSTOM`, ...). `options` is empty for a free-text question; for a
  multiple-choice question each option has Meta's option `key` and its display text `value`.
- The source must belong to your key's tenant (`404 source_not_found` otherwise). Meta refusing the read answers
  `400 token_invalid` or `400 meta_refused`; Meta not reachable answers `502 meta_unreachable`.

### Test lead

`POST /sources/{id}/test-lead` with `{"formId": "<form id>"}` asks Meta for a test lead on that form and answers
`202 {"formId"}` at once. The lead then arrives the normal way: a `lead.created` delivery (and in `/leads`) with
`isTest: true`, usually within a minute. That first test lead moves a `WAITING_FOR_TEST` source to `LIVE`.

- Meta keeps one test lead per form, so the previous test lead on the form is deleted first. If Meta still holds
  it afterwards the call answers `409 test_lead_exists`: delete it in Meta's Lead Ads Testing Tool and retry.
- A source that is not receiving leads (not `WAITING_FOR_TEST` or `LIVE`) answers `409 source_not_connected`.
- Other errors as for form questions (`404 source_not_found`, `400 token_invalid`, `400 meta_refused`,
  `502 meta_unreachable`, `422 invalid_form_id`).

### Settings

```json
{"allowSharedPages": false, "updatedAt": "2026-11-15T05:00:00Z"}
```

`allowSharedPages` (default `false`): allow a Facebook Page another product on this Shared Service also uses. A Page
joins only when every product on it allows sharing; otherwise connecting answers `PAGE_IN_USE`. Any holder of a
key can change this setting (owner ruling D13: the consumer shows it in its own settings); every change is audited
with the key id.

### Webhook

```json
{"id": "9a2e...", "url": "https://crm.example.com/hooks/leads", "events": ["lead.created"],
 "createdAt": "2026-11-15T05:00:00Z", "lastSuccessAt": null}
```

`POST /webhooks` also returns `"secret": "whsec_..."` once. Keep it: it signs every delivery. `url` must be public
`https://`; it is checked again before every delivery attempt. At most 5 endpoints. Events: `lead.created` (release
1); `lead.updated` and `source.updated` are accepted now and start being sent in a later release.

### Test push

`POST /webhooks/{id}/test` queues ONE delivery of a sample lead to that endpoint only, signed like any real
delivery and sent through the same retry ladder. The event is `lead.created` when the endpoint subscribes to it,
otherwise its first event. The body is the section 4 lead shape with `"isTest": true`, `sourceId: "test"`,
`platform: "test"` and `fields` holding every key of your field list with a sample value per type (name
`Test Lead`, phone `+60000000000`, email `test.lead@example.com`, notes and text sample text). Answers the
`Delivery` (`404 endpoint_not_found` for an unknown or removed endpoint). Use it to check the receiver and its
signature check before real leads arrive.

### Key

```json
{"id": "5c2b...", "name": "CRM sync", "keyMasked": "fxl_live_****Jk4Q", "createdAt": "2026-11-17T02:00:00Z",
 "lastUsedAt": "2026-11-17T07:40:00Z", "revokedAt": null}
```

`POST /keys` also returns `"key": "fxl_live_..."` once. A revoked key stays listed with `revokedAt` set and answers
`401 invalid_api_key` from then on. To rotate: create the new key, switch your backend to it, then revoke the old
key with the new one (a key cannot revoke itself). Every key call is audited with the calling key id.

### Delivery

```json
{"id": "7b0d...", "leadId": "e3a1...", "event": "lead.created", "status": "PENDING", "attempt": 0,
 "nextAttemptAt": "2026-11-15T05:20:00Z", "lastStatusCode": null, "lastError": null}
```

## 4. The lead

The same object is the webhook `data` and every `/leads` item.

```json
{
  "id": "e3a1...",
  "sourceId": "4c1f...",
  "sourceName": "Foundryx",
  "platform": "facebook",
  "platformLeadId": "100000000000001",
  "pageId": "300000000000001",
  "formId": "400000000000001",
  "formName": "S-META test 1",
  "receivedAt": "2026-11-15T05:19:16Z",
  "createdAt": "2026-11-15T05:19:11Z",
  "isTest": true,
  "duplicateOf": null,
  "fields": {
    "name": "Test Lead",
    "phone": "+60120000000",
    "email": "lead.test@example.com",
    "notes": "interest: test answer"
  },
  "answers": [
    {"key": "full_name", "values": ["Test Lead"]},
    {"key": "email", "values": ["lead.test@example.com"]},
    {"key": "phone_number", "values": ["+60120000000"]},
    {"key": "interest", "values": ["test answer"]}
  ],
  "attribution": {
    "pageId": "300000000000001",
    "formId": "400000000000001",
    "adId": null,
    "adsetId": null,
    "campaignId": null,
    "isOrganic": true
  }
}
```

- `id` is the Lead Capture lead id: use it to make your create idempotent.
- `fields` has exactly your field keys (section 3, Field), each a string or `null`. The example uses the defaults.
- `answers` are the form's questions exactly as Facebook sent them.
- `isTest` is `true` for a Meta test lead (Lead Ads Testing Tool or the test-lead API).
- `formName` is the Instant Form's name as Facebook shows it (added 15 Nov 2026, additive). It is `null` when
  Facebook did not give it (the lead is never held back for it); a later lead of the same form may then carry it.
  Leads stored before 15 Nov 2026 have `null`. Treat it as display text; `formId` stays the stable key.
- `createdAt` is when the person submitted the form; `receivedAt` is when Lead Capture stored it. Both are UTC, ISO
  8601, `Z`-suffixed. `createdAt` may be `null`.
- `duplicateOf` is always `null` in release 1.

## 5. Webhook delivery

Each event is one `POST` to every endpoint subscribed to it:

```
POST <your url>
Content-Type: application/json
User-Agent: Foundryx-LeadCapture/1.0
X-Lead-Capture-Event: lead.created
X-Lead-Capture-Delivery: <delivery id>
X-Lead-Capture-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256(secret, t + "." + raw body)>
```

Body:

```json
{"id": "<event id>", "type": "lead.created", "occurredAt": "2026-11-15T05:19:16Z", "data": <Lead>}
```

### Verify the signature

1. Split the header on `,` into `t` and `v1`.
2. Compute `HMAC-SHA256(secret, t + "." + raw_body)` as lowercase hex over the RAW request bytes (before any JSON
   parsing).
3. Compare with `v1` in constant time. Reject when `t` is more than 5 minutes from your clock.

```python
import hashlib, hmac, time

def verify(secret: str, header: str, raw_body: bytes) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    t, v1 = parts.get("t", ""), parts.get("v1", "")
    if not t.isdigit() or abs(time.time() - int(t)) > 300:
        return False
    expected = hmac.new(secret.encode(), t.encode() + b"." + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)
```

### Answer and retries

- Answer any `2xx` once the lead is committed in your CRM. Anything else, or no answer within 10 seconds, is a
  failed attempt.
- Retries: 1 minute, 5 minutes, 30 minutes, 2 hours, 6 hours, 24 hours after the previous attempt; then the delivery
  is `FAILED`. `POST /deliveries/{id}/redeliver` sends the same body again with a new signature.
- A delivery can arrive more than once (a retry after your commit but before your answer reached us): create
  idempotently on `data.id`.
- Redirects are not followed.

## 6. Pulling leads

`GET /leads?since=2026-11-15T00:00:00Z` returns leads in `receivedAt`, then `id`, order. Keep `nextCursor` and call
`GET /leads?cursor=<nextCursor>` next time: it resumes right after the last lead you received. An empty page keeps
the cursor you sent; an empty first `since` page has `nextCursor: null`, so call with the same `since` again.
`hasMore: true` means call again now. `source=<sourceId>` limits to one source. `cursor` wins over `since`. A lead
appears in the pull about 5 seconds after it is stored (so a cursor never passes a lead that is still being saved);
the webhook is sent at once.
