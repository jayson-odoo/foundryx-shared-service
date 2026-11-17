# EcoHub: build the Lead Capture screens in your app

Part of the product quickstart (`docs/lead-capture/ecohub-quickstart.md`). Shared
Service (SS) provides the API and the middleware; EcoHub can show the same three setup screens SS has (Keys,
Delivery, Fields) inside its own app. Every action on those screens has a gateway call, so no SS sign-in, no
script and no SQL is needed.

The contract of record is `documentation/lead-capture/consumer-integration-guide.md`. If this page and the guide
ever disagree, the guide wins; report the difference. All data below is fake.

## Before you start

- Every call goes from **ecohub-backend** to `https://<shared-service-host>/be/api/v1/lead-capture` with
  `Authorization: Bearer fxl_live_...`. The browser never holds the key: EcoHub's screens call ecohub-backend, and
  ecohub-backend calls SS.
- The key decides the company. Nothing in a request chooses it.
- Every error has one shape: `{"error": {"code": "...", "message": "..."}}`. `message` is plain text you can show
  as-is. The table in guide section 2 lists every `code`.
- Answers that apply to every screen:
  - `401 invalid_api_key`: the key was revoked or is wrong. Show "Lead Capture is not connected" to the EcoHub
    admin and stop calling.
  - `403 service_not_enabled`: Lead Capture is off for this company. Same message.
  - `429 rate_limited`: wait `Retry-After` seconds, then retry once.
  - No answer or a 5xx: show the error with a "Try again" button. Never leave a spinner running.

## Screen 1: Keys

Lets the EcoHub admin rotate the key ecohub-backend uses.

| Action | Call | Answer |
|---|---|---|
| Load the list | `GET /keys` | `{"data": [Key]}`, newest first, revoked keys included |
| Create | `POST /keys` `{"name": "CRM sync"}` | `201` Key + `"key": "fxl_live_..."` (shown once) |
| Revoke | `DELETE /keys/{id}` | `204` |

```json
{"id": "5c2b0000-0000-0000-0000-000000000001", "name": "CRM sync", "keyMasked": "fxl_live_****Jk4Q",
 "createdAt": "2026-11-17T02:00:00Z", "lastUsedAt": "2026-11-17T07:40:00Z", "revokedAt": null}
```

Show:

- List columns: Name, Key (`keyMasked`), Created, Last used (`-` when `null`), Status (Revoked when `revokedAt` is
  set, else Active).
- After Create: the full `key` once, with Copy, then never again. Store it in ecohub-backend's environment, not in a
  database column the browser can read.
- Rotate = Create the new key, switch ecohub-backend to it, then Revoke the old key **using the new key**.

Errors:

- `409 key_in_use`: you tried to revoke the key this request used. Show the message.
- `404 key_not_found`: the key is gone. Reload the list.

## Screen 2: Delivery

The admin picks ONE way to get leads: **Push to my system** (SS calls EcoHub) or **Pull only** (EcoHub asks SS).

| Action | Call | Answer |
|---|---|---|
| Load the receivers | `GET /webhooks` | `{"data": [Webhook]}` |
| Add a receiver | `POST /webhooks` `{"url": "https://<ecohub-backend>/hooks/lead-capture", "events": ["lead.created"]}` | `201` Webhook + `"secret": "whsec_..."` (shown once) |
| Send test push | `POST /webhooks/{id}/test` | `202` Delivery |
| Remove a receiver | `DELETE /webhooks/{id}` | `204` |
| Pull leads | `GET /leads?cursor=...` | see the simple quickstart |

```json
{"id": "9a2e0000-0000-0000-0000-000000000001", "url": "https://ecohub.example.com/hooks/lead-capture",
 "events": ["lead.created"], "createdAt": "2026-11-17T02:05:00Z", "lastSuccessAt": null}
```

Show:

- First view: receivers exist = Push; none = Pull only.
- Push: list columns URL, Events (`lead.created` = New lead, `lead.updated` = Lead updated, `source.updated` =
  Source updated), Added, Last delivered (`lastSuccessAt`, `-` when `null`). Row actions: Send test push, Remove.
- After Add: the `secret` once, with Copy. ecohub-backend needs it to check every delivery's signature (quickstart
  section 3).
- Send test push: one signed sample lead (`isTest: true`) goes to that receiver only. Show "Test push sent." Check
  that ecohub-backend received it and its signature check passed.
- Pull only: choosing it while receivers exist removes them (`DELETE` each). Ask first: "1 receiver will be
  removed. New leads will no longer be pushed to it."

Errors:

- `422 invalid_url`: the URL is not public `https://`. Show the message under the URL field.
- `422 invalid_events`: no event chosen, or an unknown one.
- `409 endpoint_limit`: already 5 receivers ("At most 5 receivers.").
- `404 endpoint_not_found` (test push, remove): the receiver is gone. Reload the list.

## Screen 3: Fields and the field map

EcoHub publishes its own lead fields; the admin then maps each form question to one of them.

| Action | Call | Answer |
|---|---|---|
| Load the fields | `GET /fields` | `{"data": [Field], "isDefault"}` |
| Save the fields | `PUT /fields` `[Field]` (replaces the list) | same shape |
| Use defaults | `PUT /fields` `[]` | the four defaults, `isDefault: true` |
| Load the mapped forms | `GET /sources` | `{"data": [Source]}` |
| Load a Page's form names | `GET /sources/{sourceId}/forms` | `{"formsMode", "formIds", "tosAccepted", "data": [Form]}` |
| Load a form's questions | `GET /sources/{sourceId}/forms/{formId}/questions` | `{"formId", "formName", "data": [Question]}` |
| Save a form's map | `PUT /sources/{sourceId}/field-map` `{"formId": "400000000000001", "map": {...}}` | Source |

```
PUT /fields
[{"key": "client_name", "label": "Client Name", "type": "name"},
 {"key": "phone", "label": "Phone", "type": "phone"},
 {"key": "email", "label": "Email", "type": "email"},
 {"key": "budget_range", "label": "Budget Range", "type": "text"},
 {"key": "notes", "label": "Notes", "type": "notes"}]
```

```
PUT /sources/4c1f0000-0000-0000-0000-000000000001/field-map
{"formId": "400000000000001",
 "map": {"full_name": null, "what_is_your_budget": "budget_range", "best_time_to_call": null}}
```

Show:

- Fields: an editable list of Key, Label, Type (Name, Phone, Email, Lead notes, Text). "Use defaults" only when
  `isDefault` is false. It replaces the list, so give the admin a way back: Shared Service shows a 10-second
  countdown with Cancel and only then sends `PUT /fields` `[]`.
- Saving the field list (including Use defaults) also removes every map line that points at a field no longer in
  the list, in the same call; a form left with no line loses its map. Reload the sources afterwards so the Form
  maps list matches.
- Form maps list: one row per (Page, form) from `GET /sources`:
  - every form id in a source's `fieldMap` (`"*"` = All forms);
  - every form in its `needsMapping` (Status: Needs mapping, plus `unmappedCount` answers that went to notes);
  - Page = `pageName`; Form = the form's `name` from `GET /sources/{sourceId}/forms`, else the notice's
    `formName`, else "Instant Form <id>" (e.g. when Meta cannot be read right now).
- Map popup: one line per question from the questions call (`label`), each with a searchable picker of EcoHub's
  fields. Start each picker from the form's own map, else the `"*"` map. With no map:
  - a standard question (`full_name`, `first_name`, `last_name`, `email`, `phone_number`) fills its field by
    itself; label it e.g. "Client Name (automatic)";
  - any other answer goes to the notes field; label it "Leave in notes".
  Keep the automatic field in the picker too: a stored map may name it, and the picker must show what is stored.
  Send every question on Save, `null` for the automatic / notes choice. Saving clears the form's "Needs mapping".
- All forms (`"*"`): there is no single form to read questions from, so do NOT call the questions route for it
  (it answers `422 invalid_form_id`). Its lines are the question keys its stored map already names, labelled by key.
- Add form: Page picker, then a Form picker filled from `GET /sources/{sourceId}/forms`; then open the map popup.

Errors:

- `422 invalid_fields`: bad or repeated key, unknown type, more than 50 fields. Show the message next to the list.
- `422 invalid_field_map`: a target that is not one of your fields (e.g. after removing a field). Reload the fields
  and the popup.
- `422 invalid_form_id` (questions call): the form id is not digits only (e.g. `"*"`). Pick forms from the form
  list instead of typing ids; the field-map call itself only refuses an id with characters other than letters,
  digits, `_` and `-` (`422 invalid_field_map`).
- Form list call: `400 token_invalid`, `400 meta_refused`, `502 meta_unreachable`, as for the questions call.
- Questions call: `400 token_invalid` (the Page must be reconnected), `400 meta_refused` (Meta's reason, e.g. the
  Page has not given Leads Access), `502 meta_unreachable` (try again). Show the message with "Try again".
- `404 source_not_found`: the Page was disconnected. Reload the list.

## Not on these screens yet

- Connecting a Facebook Page, choosing forms, backfill, history and disconnect: see the product quickstart
  sections 1-8.
- The leads log with delivery status and Redeliver: lane L-C. Redeliver already works:
  `POST /deliveries/{id}/redeliver`.
