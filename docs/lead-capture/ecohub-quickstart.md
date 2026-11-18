# Lead Capture - product quickstart (EcoHub, Sorento, any consuming product)

The Shared Service provides the Lead Capture API and middleware; each product builds its own screens on top of it
(owner, 17 Nov 2026). Everything a product's admin needs to run a Facebook lead source is on the product-scoped API
below, authenticated by the product's own key. No Shared Service screen, SQL or server setting is needed.

The full contract (every field, error and event) is `documentation/lead-capture/consumer-integration-guide.md`. This
page is the short path: which call backs which screen, with real payloads.

## 0. Basics

- Base URL: `https://<shared-service-host>/api/v1/lead-capture`
- Every call: `Authorization: Bearer fxl_live_<secret>` (the product's key). The key decides the product (tenant);
  nothing in a body or query can choose another one.
- Errors always look like `{"error": {"code": "<code>", "message": "<plain words>"}}`. Show `message` to the admin;
  branch on `code`. A `429` carries `Retry-After` (seconds).
- Times are UTC ISO 8601 with `Z`. Ids are strings.

| Screen in the product | Call |
|---|---|
| Lead sources list (with status badge) | `GET /sources` |
| Connect a Facebook Page / Reconnect | `POST /sources/facebook` |
| Forms step (which forms feed this product) | `GET /sources/{id}/forms`, `PUT /sources/{id}/forms` |
| Fields step (map form questions to CRM fields) | `GET /fields`, `PUT /fields`, `GET /sources/{id}/forms/{formId}/questions`, `PUT /sources/{id}/field-map` |
| Test step | `POST /sources/{id}/test-lead` |
| "Fetch missed leads now" | `POST /sources/{id}/backfill` |
| Source History tab | `GET /sources/{id}/history` |
| Disconnect | `DELETE /sources/{id}` |
| Live refresh of the list | webhook event `source.updated` |
| Keys (create, list, revoke) | `GET /keys`, `POST /keys`, `DELETE /keys/{id}` |
| Delivery (receivers, test push, pull only) | `GET /webhooks`, `POST /webhooks`, `POST /webhooks/{id}/test`, `DELETE /webhooks/{id}` |

Keys, Delivery and the Fields screen (field list + per-form map) are written up screen by screen, with the states to
show, in `docs/lead-capture/ecohub-quickstart-screens.md`.

## 1. Sources list and health

`GET /sources`

```json
{"data": [{
  "id": "4c1f0b6e-...",
  "platform": "facebook",
  "name": "Solar Page",
  "status": "LIVE",
  "pageId": "300000000000001",
  "pageName": "Solar Page",
  "formsMode": "pick",
  "formIds": ["400000000000001"],
  "needsMapping": [],
  "fieldMap": {"*": {"interest": "remarks"}},
  "lastLeadAt": "2026-11-17T08:01:12Z",
  "backfillLastRunAt": "2026-11-17T08:15:02Z",
  "backfillLastError": null,
  "createdAt": "2026-11-15T05:00:00Z"
}]}
```

Badge by `status`:

| `status` | Show | Main action |
|---|---|---|
| `WAITING_FOR_TEST` | Waiting for a test lead | Send a test lead (section 4) |
| `LIVE` | Live | - |
| `NEEDS_RECONNECT` | Reconnect needed | Reconnect (section 2) |
| `DISCONNECTED` | Disconnected | Connect again (section 2) |

`backfillLastError` not `null` = show it next to the source (plain words, e.g. a ticked form that Facebook no longer
has). `needsMapping` not empty = show a "Map fields" notice per form.

When Facebook stops accepting the Page's access (token expired or revoked, the app removed from the Page), the
source moves to `NEEDS_RECONNECT` by itself, the Shared Service emails the product's Lead Capture managers once, and
the product's webhook receives `source.updated` with `change: "needs_reconnect"`.

## 2. Connect and reconnect

Easiest: the hosted wizard. Your server calls `POST /connect-sessions {"returnOrigin": "<your origin>",
"sourceId": null | "<source id to reconnect / map>"}` and opens the returned `url` in a popup; on the
`lead-capture:done` / `lead-capture:closed` postMessage (from the Shared Service origin) refresh the list. Your
origin must first be on the key's allowed origins (Shared Service admin, Lead Capture > Keys). Building your own
wizard instead: every step is an API, see the consumer guide section 7b (`GET /channels`,
`GET /facebook/login-config`, `POST /facebook/login` -> `loginId`, then the call below with `loginId`).

`POST /sources/facebook` (with a system user token, or with `"loginId"` from `POST /facebook/login`)

```json
{"pageId": "300000000000001", "systemUserToken": "<business system user token>", "formsMode": "all"}
```

`201` answers the source (shape above). A new Page starts `WAITING_FOR_TEST`.

Reconnect is the same call for the same Page: it keeps the source `id`, its field map, its forms choice and its
leads, and only replaces the Page access.
- From `NEEDS_RECONNECT`: back to `LIVE` (or `WAITING_FOR_TEST` if it never passed its test), and leads sent while
  it was broken are fetched at once and delivered as normal `lead.created` events.
- From `DISCONNECTED`: the same source comes back; leads from the disconnected period are not fetched.

The system user token is used once and never stored or echoed.

| HTTP | `code` | Show |
|---|---|---|
| 422 | `invalid_page_id` | Page id is digits only |
| 422 | `invalid_token` | Paste the system user token |
| 400 | `token_invalid` / `meta_refused` | `message` (e.g. add the Page to the system user's assets) |
| 409 | `PAGE_IN_USE` | This Facebook Page is already connected to another account |
| 502 | `subscribe_failed` | Facebook could not be reached; try again |

## 3. Forms

`GET /sources/{id}/forms`

```json
{"formsMode": "all", "formIds": [], "tosAccepted": true,
 "data": [
   {"id": "400000000000001", "name": "Solar enquiry", "status": "ACTIVE", "createdAt": "2026-10-01T03:00:00Z"},
   {"id": "400000000000002", "name": "Battery enquiry", "status": "ARCHIVED", "createdAt": "2026-10-20T03:00:00Z"}
 ]}
```

- `data` empty = the Page has no Instant Form yet: show the "Create an Instant Form" guide and a "Check again"
  button that repeats this call.
- `tosAccepted: false` = warn that leads from real ads need the Page to accept Meta's Lead Ads Terms (test leads
  still work).

`PUT /sources/{id}/forms`

```json
{"formsMode": "all"}
```
or
```json
{"formsMode": "pick", "formIds": ["400000000000001"]}
```

`200` answers the source. "All forms, including new ones" = `"all"` (default). "Only the forms I tick" = `"pick"`
with at least one id; with none it answers `422 forms_required` (disable the Save button until one is ticked).
Other errors: `422 invalid_form_id`, `422 invalid_forms_mode`, `404 source_not_found`. (The `GET` reads Facebook
and can also answer `400 token_invalid` / `meta_refused` or `502 meta_unreachable`.)

## 4. Test lead

`POST /sources/{id}/test-lead` with `{"formId": "400000000000001"}` answers `202 {"formId"}`; the test lead arrives
within about a minute as `lead.created` with `isTest: true`, and the source turns `LIVE`. On a Page shared with
another product, only the product that asked turns `LIVE`.

| HTTP | `code` | Show |
|---|---|---|
| 429 | `test_lead_cooldown` | Wait `Retry-After` seconds (one per form per minute, 10 forms per hour) |
| 409 | `source_not_connected` | Reconnect first |
| 409 | `test_lead_exists` | Delete the old test lead in Meta's Lead Ads Testing Tool, then retry |

## 5. Fetch missed leads now

The Shared Service already re-reads every live source every 15 minutes. A "Fetch now" button calls
`POST /sources/{id}/backfill` -> `202 {"sourceId"}`. Leads found arrive as normal `lead.created` events (never
twice). Afterwards `GET /sources` shows `backfillLastRunAt` / `backfillLastError`.

| HTTP | `code` | Show |
|---|---|---|
| 429 | `backfill_cooldown` | Ran a moment ago; wait `Retry-After` seconds |
| 409 | `source_not_connected` | Reconnect first |

## 6. History tab

`GET /sources/{id}/history` (newest first, at most 200)

```json
{"data": [
  {"id": "b71c...", "action": "reconnected", "actor": {"type": "key", "name": "EcoHub"}, "onBehalfOf": null,
   "from": "NEEDS_RECONNECT", "to": "LIVE", "createdAt": "2026-11-17T09:00:00Z"},
  {"id": "a903...", "action": "needs_reconnect", "actor": {"type": "system", "name": "System"}, "onBehalfOf": null,
   "from": "LIVE", "to": "NEEDS_RECONNECT", "createdAt": "2026-11-17T08:30:00Z"},
  {"id": "5e02...", "action": "forms_changed", "actor": {"type": "user", "name": "Sales Admin"}, "onBehalfOf": null,
   "from": "All forms", "to": "Only Solar enquiry", "createdAt": "2026-11-17T08:00:00Z"}
]}
```

Columns: When (`createdAt`), Who (`actor.name`, plus "on behalf of `onBehalfOf`" when set), Action (`action`
as words: connected, reconnected, forms changed, needs reconnect, disconnected), Old -> New (`from` -> `to`).

Changes made through the product's key show the key's name as `actor.name`. To show the product user's own name,
give each product its key name accordingly, or record the user on the product side as well.

## 7. Disconnect

`DELETE /sources/{id}` -> `204`. The source becomes `DISCONNECTED`, its stored Page access is deleted, its leads stay
(still in `GET /leads`). Facebook's lead subscription on the Page is removed only when no other product still uses
the Page. Calling it again also answers `204`. `404 source_not_found` for an id that is not the product's.

## 8. Keep the list fresh: `source.updated`

Register the webhook with both events:

```json
POST /webhooks
{"url": "https://crm.example.com/hooks/leads", "events": ["lead.created", "source.updated"]}
```

Each source change sends:

```json
{"id": "<event id>", "type": "source.updated", "occurredAt": "2026-11-17T08:30:00Z",
 "data": {"id": "4c1f0b6e-...", "status": "NEEDS_RECONNECT", "...": "every field of the source",
          "change": "needs_reconnect"}}
```

`change` is one of `connected`, `reconnected`, `forms_changed`, `needs_reconnect`, `disconnected`. Verify the
`X-Lead-Capture-Signature` header exactly as for `lead.created` (guide section 5), then replace the source row in the
product's list with `data`.
