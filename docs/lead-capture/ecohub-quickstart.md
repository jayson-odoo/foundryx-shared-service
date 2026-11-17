# Lead Capture for EcoHub: quickstart

For the EcoHub team, so EcoHub can receive Facebook / Instagram leads from the Foundryx Shared Service (SS). It
covers what is live today (17/11/2026, SS main with Lead Capture lanes P and S0).

**The contract of record is `documentation/lead-capture/consumer-integration-guide.md`.** This page is a short
walk-through of it for EcoHub. If the two ever disagree, the guide wins; report the difference. All data below is
fake.

## 1. What EcoHub gets

- One signed HTTPS `POST` to EcoHub's backend per new lead (`lead.created`), within seconds of the form being
  submitted on Facebook.
- A pull API to catch up on anything missed.
- EcoHub's own field names: EcoHub publishes its lead fields once, and SS maps each form question onto them.

## 2. Setup, once per EcoHub company

| # | Who | What |
|---|---|---|
| 1 | SS admin (Foundryx) | Install Lead Capture for the EcoHub company in SS. Create a key: `POST /lead-capture/keys` (staff), which gives `fxl_live_...` once. The key goes to ecohub-backend's environment only, never the browser |
| 2 | ecohub-backend | `POST /api/v1/lead-capture/webhooks {"url": "https://<ecohub-backend>/hooks/lead-capture", "events": ["lead.created"]}`. Store the returned `secret` (`whsec_...`, shown once) |
| 3 | ecohub-backend | `PUT /api/v1/lead-capture/fields` with EcoHub's lead fields (section 5) |
| 4 | SS admin, today; EcoHub's own "Connect a source" button after lane L-C | Connect the customer's Facebook Page |
| 5 | Both | Send a test lead (Meta Lead Ads Testing Tool) and see it in EcoHub Leads |

Base URL: `https://<shared-service-host>/be/api/v1/lead-capture`. Every call sends `Authorization: Bearer fxl_live_...`.
The key decides the company; nothing in a request chooses it.

## 3. Receiving a lead (the push)

```
POST https://<ecohub-backend>/hooks/lead-capture
Content-Type: application/json
X-Lead-Capture-Event: lead.created
X-Lead-Capture-Delivery: 7b0d0000-0000-0000-0000-000000000001
X-Lead-Capture-Signature: t=1763356800,v1=<hex HMAC-SHA256(secret, t + "." + raw body)>
```

```json
{
  "id": "evt-0001",
  "type": "lead.created",
  "occurredAt": "2026-11-17T03:20:05Z",
  "data": {
    "id": "e3a10000-0000-0000-0000-000000000001",
    "sourceId": "4c1f0000-0000-0000-0000-000000000001",
    "sourceName": "Sample Home Page",
    "platform": "facebook",
    "platformLeadId": "100000000000001",
    "pageId": "300000000000001",
    "formId": "400000000000001",
    "formName": "Year-end promo",
    "receivedAt": "2026-11-17T03:20:05Z",
    "createdAt": "2026-11-17T03:20:00Z",
    "isTest": false,
    "duplicateOf": null,
    "fields": {
      "client_name": "Test Person",
      "phone": "+60120000000",
      "email": "test.person@example.com",
      "property_type": "Condominium",
      "budget_range": null,
      "notes": "preferred_time: Evening"
    },
    "answers": [
      {"key": "full_name", "values": ["Test Person"]},
      {"key": "phone_number", "values": ["+60120000000"]},
      {"key": "email", "values": ["test.person@example.com"]},
      {"key": "property_type", "values": ["Condominium"]},
      {"key": "preferred_time", "values": ["Evening"]}
    ],
    "attribution": {"pageId": "300000000000001", "formId": "400000000000001", "adId": "200000000000001",
                    "adsetId": null, "campaignId": null, "isOrganic": false}
  }
}
```

**What ecohub-backend must do**

1. **Verify before parsing.** Split the header into `t` and `v1`. Compute lowercase hex
   `HMAC-SHA256(secret, t + "." + raw_body)` over the RAW bytes. Compare in constant time. Reject when `t` is more
   than 300 s from your clock. On any mismatch answer `401` and store nothing.

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

2. **Create idempotently on `data.id`.** Store it as the lead's external id with a unique constraint. A repeat
   delivery is a no-op that still answers `200`.
3. **Create the Lead:**
   - status New, source = `data.platform`;
   - fields from `data.fields`, which carries exactly EcoHub's published keys, each a string or `null`;
   - keep `answers`, `formName` and `attribution` for display.
4. **Answer `2xx` only after the commit.** Anything else, or no answer within 10 s, is a failed attempt.
5. **`isTest: true`** marks a Meta test lead. Show it, or filter it out, as EcoHub prefers.

**Retries:** SS retries at 1 min, 5 min, 30 min, 2 h, 6 h and 24 h after the previous attempt, then marks the
delivery FAILED. `POST /api/v1/lead-capture/deliveries/{id}/redeliver` (the id is the `X-Lead-Capture-Delivery`
header) resends the same body with a new signature. Redirects are not followed.

## 4. Catching up (the pull)

`GET /api/v1/lead-capture/leads?since=2026-11-17T00:00:00Z` returns `{"data": [Lead], "nextCursor", "hasMore"}`,
oldest first, with the same `Lead` shape as `data` above.

- Keep `nextCursor` and call `GET /leads?cursor=<nextCursor>` next time.
- `hasMore: true` means call again now.
- `limit` is 1-100 (default 50); `source=<sourceId>` filters to one source.
- Suggested: a nightly job pulls from the last cursor and creates anything missing (idempotent on `id`, as in
  section 3).

## 5. EcoHub's fields and the field map

**Publish EcoHub's lead fields once** (this replaces the list; `[]` goes back to the defaults):

```
PUT /api/v1/lead-capture/fields
[{"key": "client_name", "label": "Client Name", "type": "name"},
 {"key": "phone", "label": "Phone", "type": "phone"},
 {"key": "email", "label": "Email", "type": "email"},
 {"key": "property_type", "label": "Property Type", "type": "text"},
 {"key": "budget_range", "label": "Budget Range", "type": "text"},
 {"key": "notes", "label": "Notes", "type": "notes"}]
```

`type` is one of `name`, `phone`, `email`, `notes`, `text`; at most 50 fields.

**How answers are mapped:**

- Facebook's standard questions fill the first field of their type automatically: full name, or first + last name,
  goes to `name`; email to `email`; phone to `phone`.
- Any other answer goes to the first `notes` field as one `key: value` line.
- The lead is never held back for mapping.

**Map a custom question to a field** (`"*"` = every form; a form's own map wins):

```
PUT /api/v1/lead-capture/sources/{sourceId}/field-map
{"formId": "*", "map": {"property_type": "property_type", "budget": "budget_range"}}
```

Question keys are exactly `answers[].key` as received. `GET /sources` lists `needsMapping` for forms whose answers
went to notes; saving a map for that form, or for `"*"`, clears the entry.

## 6. Coming next (additive; the push and pull above stay as they are)

| Lane | Adds |
|---|---|
| **L-A** | The questions of each form, so EcoHub's mapping screen shows real labels. A "Send test lead" call per source. A new source turns Live only after its test lead arrives |
| **L-B** | The form list and an "only these forms" choice. A Reconnect status when Facebook access breaks, a 15-minute catch-up of missed leads, and Disconnect. A `source.updated` event |
| **L-C** | `POST /connect-sessions`, which gives EcoHub's "Connect a source" button a single-use link to the hosted Facebook setup wizard, opened in a popup. EcoHub then needs no SS admin for step 4 |
| **Release 2** | Google Ads lead forms with Google sign-in, website form, WhatsApp click-to-chat ads |

**Start now:** the receiver, the pull and the field list do not change in later lanes. EcoHub can build sections 3-5
today.
