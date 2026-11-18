# Lead Capture - consumer integration guide

Contract of record for the Lead Capture gateway (plan 64, AC-64-66). A change to any gateway route, header, body
field or error code ships with a change to this file in the same pull request.

Status: release 1. Sources: Facebook Page Instant Forms. Events sent: `lead.created` and `source.updated` (added
17 Nov 2026). Connect sessions (the hosted wizard) and the Facebook login API for your own wizard: section 7
(added 17 Nov 2026, lane L-C). Instagram, the `lead.updated` event and the duplicate rule arrive in later releases
and will be added here first. Google Ads lead form sources (URL + key the customer pastes into Google Ads): section
8 (added 18 Nov 2026, release 2).

Everything is per product (one Shared Service tenant per consuming CRM): its own key, its own endpoints and signing
secrets, its own lead field list and field maps. Two CRMs reading the same Facebook Page each receive the lead in
their own field names.

## 1. Authentication

Every gateway call carries a Lead Capture key:

```
Authorization: Bearer fxl_live_<secret>
```

- A Shared Service admin creates the key (Lead Capture > Keys, or `POST /lead-capture/keys` while signed in). The
  full key is shown once; afterwards only `fxl_live_****` + its last 4 characters is shown.
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
| 409 | `PAGE_IN_USE` | Connect: the Page is used by another product and sharing is not allowed on both sides |
| 422 | `invalid_page_id` | Connect: `pageId` is not a Facebook Page id (digits only) |
| 422 | `invalid_token` | Connect: send exactly one of `systemUserToken` / `loginId` |
| 409 | `LOGIN_REQUIRED` | Connect with a `loginId` that is unknown, expired (30 minutes), another key's or another tenant's: sign in again |
| 422 | `ORIGIN_NOT_ALLOWED` | Connect session: `returnOrigin` is missing or not on this key's allowed origins |
| 400 | `PERMISSION_DECLINED` | Facebook login: the person did not grant the lead permission (`leads_retrieval`) |
| 400 | `LOGIN_FAILED` | Facebook login: Meta refused the code (used, expired, wrong redirect URI) |
| 409 | `source_exists` | Wizard: the Page is already one of your sources; reconnect it with a session for that `sourceId` |
| 409 | `channel_unavailable` | Facebook login while Facebook is not set up on this server (`GET /channels` lists none) |
| 422 | `invalid_code` | Facebook login: `code` is empty or too long |
| 502 | `subscribe_failed` | Connect: Meta could not be reached, or refused the Page's lead subscription; try again |
| 404 | `delivery_not_found` | Delivery id not found for this tenant |
| 400 | `token_invalid` | Meta no longer accepts the source's Page token (or it has none): reconnect the Page |
| 400 | `meta_refused` | Meta refused the form, form-list or test-lead call; `message` is Meta's reason, cleaned |
| 409 | `endpoint_limit` | Already 5 webhook endpoints |
| 409 | `source_not_connected` | Test lead or backfill for a source that is not receiving leads (`NEEDS_RECONNECT`, `DISCONNECTED`, `DRAFT`): reconnect first |
| 409 | `test_lead_exists` | Meta still holds the form's previous test lead after clearing it; delete it in Meta's Lead Ads Testing Tool, then retry |
| 409 | `lead_purged` | Redeliver of a lead whose personal data was deleted |
| 422 | `invalid_request` | Body or query fails validation (e.g. `limit=500`, no `url`); `details` lists the fields |
| 422 | `invalid_url` | Callback URL is not public `https://` |
| 422 | `invalid_fields` | Field list: bad key, repeated key, unknown type, more than 50 |
| 422 | `invalid_field_map` | Field map: bad form id, target not in your field list |
| 422 | `invalid_events` | No event, or an unknown event |
| 422 | `invalid_form_id` | `formId` / a `formIds` entry is not an Instant Form id (digits only), or more than 200 ids |
| 422 | `invalid_forms_mode` | `formsMode` is not `"all"` or `"pick"` (connect takes `"all"` only; choose forms afterwards with `PUT /sources/{id}/forms`) |
| 422 | `forms_required` | `formsMode: "pick"` with no form id |
| 422 | `invalid_cursor` | `cursor` is not one this API returned |
| 422 | `invalid_since` | `since` is not an ISO-8601 time |
| 429 | `rate_limited` | Throttled; see `Retry-After` |
| 429 | `test_lead_cooldown` | A test lead was asked for the same source and form less than 60 seconds ago, or 10 forms of the source already had one in the last hour; see `Retry-After` |
| 429 | `backfill_cooldown` | `POST /sources/{id}/backfill` less than 60 seconds after the last run, or while a run is still going; see `Retry-After` |
| 502 | `meta_unreachable` | Meta could not be reached for a form, form-list or test-lead call; try again |

## 3. Routes

| Method | Path | Body / query | Answer |
|---|---|---|---|
| GET | `/sources` | - | `{"data": [Source]}` |
| GET | `/settings` | - | `Settings` |
| PUT | `/settings` | `{"allowSharedPages": bool}` | `Settings` |
| GET | `/fields` | - | `{"data": [Field], "isDefault"}` |
| PUT | `/fields` | `[Field]` (replaces the list; `[]` = defaults) | `{"data": [Field], "isDefault"}` |
| POST | `/sources/facebook` | `{"pageId", "systemUserToken" or "loginId", "formsMode": "all"}` | `201` `Source` (connect, or reconnect: same Page again = same source) |
| POST | `/sources/google` | - | `201` `{"source": Source, "url", "key"}` (section 8; the key is shown only here) |
| POST | `/sources/{id}/rotate-key` | - | `{"url", "key"}` (section 8; the old key stops at once) |
| POST | `/connect-sessions` | `{"returnOrigin", "sourceId"?}` | `201` `{"url", "expiresAt"}` (section 7) |
| GET | `/channels` | - | `{"data": [Channel]}` (section 7) |
| GET | `/facebook/login-config` | - | `LoginConfig` (section 7) |
| POST | `/facebook/login` | `{"code", "redirectUri"?}` | `201` `{"loginId", "pages": [Page], "expiresAt"}` (section 7) |
| GET | `/facebook/logins/{loginId}/pages` | - | `{"data": [Page]}` (section 7) |
| DELETE | `/sources/{id}` | - | `204` (disconnect; again = `204`, nothing changes) |
| GET | `/sources/{id}/forms` | - | `{"formsMode", "formIds", "tosAccepted", "data": [Form]}` |
| PUT | `/sources/{id}/forms` | `{"formsMode": "all"}` or `{"formsMode": "pick", "formIds": ["<form id>", ...]}` | `Source` |
| POST | `/sources/{id}/backfill` | - | `202` `{"sourceId"}` |
| GET | `/sources/{id}/history` | - | `{"data": [HistoryItem]}` (newest first, at most 200) |
| GET | `/sources/{id}/forms/{formId}/questions` | - | `{"formId", "formName", "data": [Question]}` |
| POST | `/sources/{id}/test-lead` | `{"formId": "<form id>"}` | `202` `{"formId"}` |
| PUT | `/sources/{id}/field-map` | `{"formId": "<form id>" or "*", "map": {"<question key>": "<field key>"}}` | `Source` |
| GET | `/webhooks` | - | `{"data": [Webhook]}` |
| POST | `/webhooks` | `{"url", "events"}` | `201` `Webhook` + `secret` (shown once) |
| DELETE | `/webhooks/{id}` | - | `204` |
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
  "formIds": [],
  "needsMapping": [{"formId": "400000000000001", "formName": "S-META test 1", "unmappedCount": 1}],
  "fieldMap": {"*": {"interest": "product_interest"}},
  "lastLeadAt": "2026-11-15T05:19:16Z",
  "backfillLastRunAt": "2026-11-17T08:15:02Z",
  "backfillLastError": null,
  "createdAt": "2026-11-15T05:00:00Z"
}
```

`status` is one of:

| status | Receives leads | Meaning |
|---|---|---|
| `DRAFT` | no | Not connected yet |
| `WAITING_FOR_TEST` | yes | Newly connected; the first test lead (`isTest: true`) moves it to `LIVE` |
| `LIVE` | yes | Connected and tested |
| `NEEDS_RECONNECT` | no | Facebook no longer accepts the Page's access (token expired or revoked, the app removed from the Page, a permission taken away). Reconnect the Page |
| `DISCONNECTED` | no | Disconnected on purpose; its leads are kept |

- Leads, test or real, are stored and delivered in `WAITING_FOR_TEST` and `LIVE`; only a test lead moves a source
  to `LIVE`.
- On a Page shared by several products, Meta's test lead reaches every product on the Page and each stores it
  (`isTest: true`), but only the source whose product asked for it (`POST /sources/{id}/test-lead`, in the last
  hour) moves to `LIVE`. A test lead nobody asked for (sent from Meta's own Lead Ads Testing Tool) moves every
  waiting source on the Page.
- Connect / reconnect over the gateway: `POST /sources/facebook` with `{"pageId": "<digits>", "systemUserToken":
  "<business system user token>", "formsMode": "all"}`. The system user token is used once to read the Page's own
  access and is never stored or echoed. Errors: `422 invalid_page_id` / `invalid_token` / `invalid_forms_mode`,
  `400 token_invalid` / `meta_refused` (Meta refused the Page: add it to the system user's assets),
  `409 PAGE_IN_USE` (the Page is used by another product and sharing is not allowed on both sides),
  `502 subscribe_failed` (Meta could not be reached or refused the lead subscription; try again).
- Reconnect = connect the same Page again (the connect script, the wizard, or `POST /sources/facebook`). It keeps the source `id`, its field
  map, its forms choice and its leads, and only replaces the stored Page access:
  - a `WAITING_FOR_TEST` or `LIVE` source keeps its status;
  - a `NEEDS_RECONNECT` source returns to the status it had before (normally `LIVE`) and a backfill runs at once,
    so leads sent while it was broken arrive (as normal `lead.created` deliveries). If another product connected
    the same Page while it was broken, the sharing rule applies first (`PAGE_IN_USE`);
  - a `DISCONNECTED` source comes back as the same row: `LIVE` if it had passed its test, else
    `WAITING_FOR_TEST`. Leads sent while it was disconnected are not fetched. If another product took the Page
    meanwhile, the sharing rule applies (`PAGE_IN_USE`).
- `backfillLastRunAt` / `backfillLastError`: the last backfill run for this source and its error in plain words
  (`null` = it went fine). See Backfill.

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
- A source's field map says which form question fills which field: `"*"` applies to every form, a form's own map
  wins over it. Question keys are the Facebook form's question keys (as in `answers[].key`); a `null` or `""` target
  removes that entry; an empty `map` removes the form's map.
- Per answer: the mapped field; else Facebook's standard questions fill the first field of their type (`full_name`,
  or `first_name` + `last_name` -> `name`; `email` -> `email`; `phone_number` -> `phone`); else one `key: value` line
  in the first `notes`-type field (none: the answer is only in `answers`).

### Forms

`GET /sources/{id}/forms` reads the Page's Instant Forms from Meta with the source's Page token:

```json
{"formsMode": "pick", "formIds": ["400000000000001"], "tosAccepted": true,
 "data": [
   {"id": "400000000000001", "name": "Solar enquiry", "status": "ACTIVE", "createdAt": "2026-10-01T03:00:00Z"},
   {"id": "400000000000002", "name": "Battery enquiry", "status": "ARCHIVED", "createdAt": "2026-10-20T03:00:00Z"}
 ]}
```

- `formsMode` / `formIds`: this source's current choice. `"all"` (the default) takes leads from every form on the
  Page, including forms made later; `"pick"` takes leads only from the forms in `formIds`.
- `data`: every form on the Page as Meta lists it; `status` is Meta's (`ACTIVE`, `ARCHIVED`, ...). An empty list =
  the Page has no Instant Form yet.
- `tosAccepted`: the Page's acceptance of Meta's Lead Ads Terms. `false` = leads from real ads are not sent until
  the Page accepts them (test leads still work); `null` = it could not be read.
- Errors as for form questions below.

`PUT /sources/{id}/forms` changes the choice: `{"formsMode": "all"}`, or `{"formsMode": "pick", "formIds": [...]}`
with at least one id (`422 forms_required` otherwise; repeated ids are kept once). It answers the `Source`. When the
choice actually changed it also sends `source.updated` (`change: "forms_changed"`) and is recorded in the source's
history. It applies from the next lead on: a lead of a form that is not ticked is not stored for this source.

### Backfill

Lead Capture re-reads each `WAITING_FOR_TEST` / `LIVE` source's forms every 15 minutes for leads it did not receive
by webhook (for example while Meta could not reach us), and stores them exactly like a webhook lead: the same
`lead.created` delivery, and never twice (a lead already stored is skipped). `POST /sources/{id}/backfill` runs it
now for one source and answers `202 {"sourceId"}`; the leads it finds arrive as deliveries. One run at a time per
source, and "run now" at most once a minute (`429 backfill_cooldown` with `Retry-After`).

- Each form is read from where its previous read stopped (at most 90 days back). In `"all"` mode the Page's form
  list is read again each run, so a form made after the source was connected is included from its own creation;
  in `"pick"` mode only the ticked forms are read.
- A very busy form, or more waiting leads than one run reads, simply continues in the next run; it never holds
  back the other forms.
- One form Facebook refuses (for example a ticked form that was deleted) is named in `backfillLastError` and the
  other forms are still read. Only a Page whose access Facebook no longer accepts stops the run, and the source
  moves to `NEEDS_RECONNECT`.
- The outcome is on the source: `backfillLastRunAt`, `backfillLastError` (`null` = every form was read in full).
- A source that is not receiving leads answers `409 source_not_connected`.

### Disconnect

`DELETE /sources/{id}` stops the source: status `DISCONNECTED`, the stored Page access is deleted, leads already
captured stay (in `/leads` and redeliverable). It sends `source.updated` (`change: "disconnected"`). The Page's lead
subscription on Facebook is removed only when no other source (of any product) still receives that Page's leads;
other Facebook features on the Page are never touched. A second `DELETE` answers `204` and changes nothing.
Connecting the Page again revives the same source (see Source).

### History

`GET /sources/{id}/history`, newest first:

```json
{"data": [
  {"id": "b71c...", "action": "disconnected", "actor": {"type": "key", "name": "EcoHub"}, "onBehalfOf": null,
   "from": "LIVE", "to": "DISCONNECTED", "createdAt": "2026-11-17T09:00:00Z"},
  {"id": "5e02...", "action": "forms_changed", "actor": {"type": "user", "name": "Sales Admin"}, "onBehalfOf": null,
   "from": "All forms", "to": "Only Solar enquiry", "createdAt": "2026-11-17T08:00:00Z"}
]}
```

- `action`: `connected`, `reconnected`, `forms_changed`, `needs_reconnect`, `disconnected`.
- `actor.type`: `user` (signed in to the Shared Service; `name` is the person's name, never an email:
  `"Team member"` when the user has no name, `"Removed user"` when the user is gone), `key` (a gateway key;
  `name` is the key's name) or `system` (Lead Capture itself, e.g. `needs_reconnect`; `name` is `"System"`).
  `onBehalfOf` is the user's name when an admin acted while viewing as that user, else `null`.
- `from` / `to`: the status before and after, or for `forms_changed` the forms choice before and after
  (`"All forms"`, `"Only <form name or id>, ..."`). `from` is `null` on `connected`.

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

- One request per source and form per 60 seconds: a second one sooner answers `429 test_lead_cooldown` with
  `Retry-After` (seconds). Another form is not held back, up to 10 different forms per source per hour.

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
`https://`; it is checked again before every delivery attempt. At most 5 endpoints. Events: `lead.created`,
`source.updated` (sent since 17 Nov 2026); `lead.updated` is accepted now and starts being sent in a later release.
An endpoint registered with only `lead.created` receives no `source.updated`: add it to `events` (delete the
endpoint and register it again with both) to be told about reconnects and disconnects.

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

`source.updated` (`X-Lead-Capture-Event: source.updated`, no `leadId` on its delivery): `data` is the `Source`
exactly as `GET /sources` shows it, plus `change`:

```json
{"id": "<event id>", "type": "source.updated", "occurredAt": "2026-11-17T09:00:00Z",
 "data": {"id": "4c1f...", "platform": "facebook", "name": "Foundryx", "status": "NEEDS_RECONNECT", "...": "...",
          "change": "needs_reconnect"}}
```

| `change` | When |
|---|---|
| `connected` | A source was connected for the first time |
| `reconnected` | The Page was connected again (same source id) |
| `forms_changed` | The forms choice changed (`PUT /sources/{id}/forms`) |
| `needs_reconnect` | Facebook stopped accepting the Page's access; sent once per break, together with one email to the Shared Service users who manage Lead Capture. Reading a lead (webhook or backfill) or the backfill's read of the Page's form list decides this; a refusal of one form, a screen opening the form list, or a made-up form id on the test lead never does on its own (only an access token Facebook rejects outright does) |
| `disconnected` | `DELETE /sources/{id}` |

Use it to refresh the source shown in your CRM (e.g. a "Reconnect" badge). It carries no lead data.

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

## 7. Connect a source: the hosted wizard, or your own

Two ways, same functions behind both (owner, 17 Nov 2026: the Shared Service provides the API and the middleware;
the hosted wizard is the reference UI).

### 7a. Hosted wizard (a "Connect a source" button)

1. A Shared Service admin lists your CRM's origin on the key: Lead Capture > Keys, or `POST /lead-capture/keys`
   `{"name", "allowedOrigins": ["https://crm.example.com"]}` / `PUT /lead-capture/keys/{id}/origins`
   `{"allowedOrigins": [...]}` (staff, `lead_capture.keys.manage`). An origin is `https://host[:port]` only (no path);
   `http` only for `localhost`. At most 10. A key with no origin cannot open connect sessions.
2. Your server asks for a session (the key never reaches a browser):

   ```
   POST /api/v1/lead-capture/connect-sessions
   {"returnOrigin": "https://crm.example.com", "sourceId": null}
   -> 201 {"url": "https://<shared-service-host>/public/lead-capture/connect#s=<secret>", "expiresAt": "2026-11-17T09:10:00Z"}
   ```

   - `returnOrigin` must be on the key's allowed origins, else `422 ORIGIN_NOT_ALLOWED`.
   - `sourceId` (optional) reopens the wizard for one of your sources: Reconnect (`NEEDS_RECONNECT`,
     `DISCONNECTED`) or Map fields (`needsMapping` not empty). Another tenant's id = `404 source_not_found`.
   - Revoking the key, or taking `returnOrigin` off its allowed origins, ends its unused links and running
     wizards at once.
   - The page cannot be framed (`frame-ancestors 'none'`): open it as a popup or a new tab.
   - The URL works ONCE and for 10 minutes. The secret is in the `#` fragment, so it never reaches a server log or a
     `Referer`. A used or expired URL shows "This link has expired" and nothing of the account.
3. Your page opens `url` in a popup on the user's click:

   ```js
   const popup = window.open(url, 'lead_capture', 'popup,width=720,height=860');
   window.addEventListener('message', (event) => {
     if (event.origin !== '<shared-service-origin>') return;   // check the sender
     if (event.data?.type === 'lead-capture:done') refreshSources(event.data.sourceId);
     if (event.data?.type === 'lead-capture:closed') refreshSources();
   });
   ```

4. The wizard runs on its own scoped token (30 minutes; it can do the wizard's steps for this session's source and
   nothing else; every other route answers 401). It shows your tenant's name and logo (Shared Service > Settings >
   Branding), never the platform's. Steps: Channel (Facebook) -> Sign in -> Page -> Forms -> Fields -> Test -> Done;
   Channel (Google Ads) -> Copy (URL + key) -> Test -> Fields -> Done (section 8).
5. When the person finishes or closes it, the wizard posts ONE message to `window.opener` with `targetOrigin` =
   your `returnOrigin` (never `*`), then closes:

   | `type` | `sourceId` | When |
   |---|---|---|
   | `lead-capture:done` | always | Finished; the source passed its test lead (`LIVE`) |
   | `lead-capture:closed` | when a Page was connected | Closed before the end (the source may be `WAITING_FOR_TEST`) |

   Treat the message as a hint to refresh `GET /sources`; the list is the truth.

### 7b. Your own wizard (every step is an API)

| Step | Call |
|---|---|
| Channel | `GET /channels` -> `{"data": [{"key": "facebook", "label": "Facebook", "setup": "automatic"}, {"key": "google", "label": "Google Ads", "setup": "guided"}]}`; Facebook is listed only when it is set up on this server; Google Ads (guided, section 8) always |
| Sign in | `GET /facebook/login-config` -> `{"available", "simulated", "appId", "configId", "graphVersion", "scopes"}`. Open Facebook Login for Business with `appId` + `configId` (`response_type=code`, your registered redirect URI). Then `POST /facebook/login {"code", "redirectUri"}` -> `{"loginId", "pages": [{"id", "name"}], "expiresAt"}`. The Facebook token stays on the server; `loginId` is opaque, works for 30 minutes, for this key only. `simulated: true` = no Meta app on this server (development): any non-empty `code` works and two sample Pages come back |
| Page | Pick from `pages` (one Page = choose it for the person). `GET /facebook/logins/{loginId}/pages` lists them again |
| Connect | `POST /sources/facebook {"pageId", "loginId", "formsMode": "all"}` -> `201 Source` (`WAITING_FOR_TEST`). `409 PAGE_IN_USE`: the Page belongs to another product |
| Forms | `GET /sources/{id}/forms`, `PUT /sources/{id}/forms` |
| Fields | `GET /fields`, `GET /sources/{id}/forms/{formId}/questions`, `PUT /sources/{id}/field-map` |
| Test | `POST /sources/{id}/test-lead {"formId"}`, then poll `GET /sources` until the source is `LIVE` (or wait for `source.updated`) |

Error screens your wizard should have (the hosted one's wording, plain words only):

| Code | Screen |
|---|---|
| `PERMISSION_DECLINED` | "Facebook did not give permission to read leads. Leave every permission ticked on the Facebook screen." + Try again |
| `pages: []` | "No Page was shared. You need to be an admin of the Page that runs the ads." + Try again |
| `meta_refused` on forms (Leads Access) | The Page only lets chosen apps read its leads: add the app under Business settings > Integrations > Leads Access + Check again |
| `PAGE_IN_USE` | "<Page> is already connected to another account." + Choose another Page |
| `token_invalid` / `LOGIN_REQUIRED` | Facebook stopped sharing leads for the Page / the sign-in expired: sign in again |

### Hosted wizard API (for reference)

The hosted page calls `/public/lead-capture/*` with its scoped token; you never call these with a key:
`POST /connect/redeem {"token": "<secret>"}` (once; `410 SESSION_EXPIRED` after), `GET /wizard/context`,
`POST /wizard/facebook/login`, `GET /wizard/facebook/pages`, `POST /wizard/facebook/connect {"pageId"}`,
`POST /wizard/google/source` (`201 {"source", "url", "key"}`; again in the same session = same source, new key),
`GET /wizard/sources/{id}`, `GET|PUT /wizard/sources/{id}/forms`, `GET /wizard/fields`,
`GET /wizard/sources/{id}/forms/{formId}/questions`, `PUT /wizard/sources/{id}/field-map`,
`POST /wizard/sources/{id}/test-lead`, `GET /wizard/sources/{id}/test-lead` (newest test lead: the Test step passes on a NEW one), `POST /wizard/finish`.

## 8. Google Ads lead form sources (guided)

Google Ads sends each lead form submission to a webhook URL with a key the advertiser types into the form
("Lead delivery option" > webhook integration; Google's guide:
https://support.google.com/google-ads/answer/9423234, body format:
https://developers.google.com/google-ads/webhook/docs/implementation).

1. `POST /sources/google` answers `{"source", "url", "key"}`. Show the `url` and `key` to your customer with copy
   buttons. The key is shown only in this answer; lost = rotate it.
2. The customer pastes both into the Google Ads lead form and presses "Send test data".
3. Google POSTs to the `url`. A test lead (`is_test: true`) arrives as a normal `lead.created` with
   `isTest: true` and `platform: "google"`; the source moves to `LIVE`. A real lead before any test lead also moves
   it to `LIVE`.
4. Field map, `needsMapping`, the pull and the push work exactly as for Facebook. Google's standard columns
   (`FULL_NAME`, `FIRST_NAME`, `LAST_NAME`, `EMAIL`, `WORK_EMAIL`, `PHONE_NUMBER`, `WORK_PHONE`) fill your name /
   email / phone fields; any other column goes to notes until mapped. A question's key is Google's `column_id`, or
   its `column_name` when Google sends none.
5. `POST /sources/{id}/rotate-key` gives a new key; the old one is refused from that moment and the `url` stays.
   Your customer pastes the new key into Google Ads. History shows `key_rotated`.
6. The Fields step for a Google form: `GET /sources/{id}/forms/{formId}/questions` lists the columns of the newest
   lead Google sent for that form, with Google's labels (`[]` until the first lead). The `formId` comes from the
   lead (`GET /leads` or the push).

A Google lead's `pageId` is `null`; `formId` is Google's form id; `attribution` holds `formId`, `campaignId`,
`adgroupId`, `creativeId` and `gclid` (each `null` when Google sends none). Google re-sending the same `lead_id`
stores nothing new. `DELETE /sources/{id}` disconnects it: Google's next POST is refused (`410`) and nothing is
stored.

What the inbound URL answers Google (for reference; Google is the only caller):

| Case | Answer |
|---|---|
| Right key | `200 {}` |
| Wrong or missing key, or an unknown URL | `403 invalid_key` (same either way); repeated from one IP: `429 rate_limited` |
| Disconnected source | `410 source_disconnected` |
| Lead Capture off for the tenant | `403 service_not_enabled` |
| Not JSON, no `lead_id` | `400 invalid_body`; over 64 KB: `413 invalid_body` |
