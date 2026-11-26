# Hub Connector - integration guide

Two parties integrate with the Hub Connector service:

1. **The CRM** pushes availability facts and the customer company list into the shared service.
2. **A hub** (a partner platform, e.g. EcoHub) receives signed webhooks with what each of its customer
   companies may see.

What each hub customer sees is decided in the shared service, per hub and per customer company:
which locations count, which brands are visible, and (per hub) whether price is shown. Price is OFF by default.

## 1. CRM push API

Base: `https://<api host>/api/v1/hub-connector`. Auth: `Authorization: Bearer fxh_live_...` (an admin creates
the key in Hub Connector, gear menu, CRM keys; it is shown once). The key decides the tenant; nothing in the body
does. Errors: `{"error": {"code", "message"}}`; `401 invalid_api_key`, `403 service_not_enabled`, `429 rate_limited`
(with `Retry-After`, after repeated bad keys from one address).

### `PUT /customers`

```json
{"customers": [{"code": "C-001", "name": "Customer company"}]}
```

Upserts by `code`. Reply `{"stored": 1, "skipped": [], "queued": 0}`.

### `PUT /items`

```json
{
  "items": [
    {
      "code": "I-1",
      "name": "Basin mixer",
      "brand": {"code": "BR-A", "name": "Brand A"},
      "price": "120.00",
      "currency": "MYR",
      "locations": [{"code": "WH-N", "name": "North warehouse", "onHand": 10, "reserved": 2}],
      "incoming": [{"ref": "PO-1/3", "locationCode": null, "remaining": 6}]
    }
  ]
}
```

- Each item replaces the last copy of that `code` (send the item's full `locations` and `incoming` each time).
- `incoming` = not-yet-arrived remainders; `locationCode: null` = not yet allocated to a location.
- Up to 1000 items per call. One bad item never fails the batch: the reply names it.

Reply: `{"stored": 1, "skipped": [{"code": "I-9", "reason": "on hand is not a number"}], "queued": 2}`
(`queued` = webhooks queued to hubs because a customer's view changed).

## 2. Hub webhook

`POST <receiver URL>` (public https only; re-checked before every attempt).

Headers:

- `X-Hub-Connector-Event: availability.updated`
- `X-Hub-Connector-Delivery: <delivery id>` (same id on a retry)
- `X-Hub-Connector-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256(secret, t + "." + raw body)>`

Verify with the hub's signing secret (shown once at create / rotate) and reject a `t` more than 5 minutes old.

Body:

```json
{
  "id": "<uuid>",
  "type": "availability.updated",
  "occurredAt": "2026-11-26T10:00:00Z",
  "data": {
    "hub": {"code": "ecohub"},
    "customer": {"code": "C-001", "name": "Customer company"},
    "full": false,
    "items": [
      {"code": "I-1", "name": "Basin mixer", "brand": {"code": "BR-A", "name": "Brand A"},
       "gotStock": true, "gotIncoming": true}
    ],
    "removed": ["I-7"]
  }
}
```

- One webhook per customer whose view changed. `full: true` = the customer's complete view (after a policy change,
  a new customer, the price switch or "Resync"); `false` = only the changed items.
- `removed` = items this customer saw before and may no longer see: drop them.
- `gotStock`: on hand minus reserved > 0 in at least one of the customer's locations.
- `gotIncoming`: a not-yet-arrived remainder in one of the customer's locations or not yet allocated to a location.
- `price` / `currency` appear only when the hub's Show price switch is on.
- Answer any 2xx within 10 seconds. Anything else is retried after 1 min, 5 min, 30 min, 2 h, 6 h and 24 h, then
  marked failed (an admin can send it again from the hub's Deliveries tab).
