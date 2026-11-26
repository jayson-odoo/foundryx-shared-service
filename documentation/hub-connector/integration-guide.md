# Hub Connector - integration guide

Hub Connector shows a partner platform (a **hub**, e.g. EcoHub) what each of its customer companies may see of our
stock. What a customer sees is decided in the shared service, per hub and per customer company: which locations
count, which brands are visible, and (per hub) whether price is shown. Price is OFF by default. A new customer sees
nothing until its locations and brands are picked.

## 1. Where the facts come from: the CRM connector feed

The shared service PULLS the CRM connector feed (sorento-crm #2801, contract frozen):
`GET <crm>/api/v1/external/connector/v1/{locations,brands,products,availability}?company=<code>` with `X-API-Key`.

Set it up on **Settings -> Integrations -> CRM stock feed**: CRM address, company code, connector key (the key's
user needs the explicit `integration.connector.read` grant and the company). "Test connection" reads `/locations`.

A sync runs every 10 minutes and on **Sync now** (Hub Connector, gear menu). One run reads the locations, the
brands, every `/products` page (limit 200) and `/availability` for those codes in chunks of 200. Products the feed no
longer lists are removed and hubs are told to drop them. A feed error (bad key, missing grant, rate limit,
unreachable) changes nothing and shows its reason; the next run tries again. Each feed request costs the CRM two
rate-limit hits, so size the CRM integration's `rate_limit_per_minute` at twice the calls per run.

## 2. Rules

- `in_stock`: the SUM of `available_qty` (on hand minus reserved) over the customer's chosen locations is above 0.
- `incoming`: any not-yet-arrived line with an outstanding allocation to one of the customer's locations, or a line
  not yet allocated to any location. Yes / no only.
- A product whose brand the customer may not see is absent.
- `list_price` / `currency` appear only while the hub's Show price switch is on.

Row: `{"code": "SR-1001", "name": "Basin mixer", "brand_name": "Brand A", "in_stock": true, "incoming": false}`.

## 3. Hub read API

Base `https://<api host>/api/v1/hub-connector`. Auth `Authorization: Bearer fxh_live_...` - a key created on the hub
(Hub Connector -> hub -> Hub keys), shown once, bound to that hub. Errors: `{"error": {"code", "message"}}`;
`401 invalid_api_key`, `403 service_not_enabled` / `hub_inactive`, `404 customer_not_found` (unknown, paused, or
another hub's customer - all the same), `422 too_many_codes`, `429 rate_limited` with `Retry-After`.

`GET /products?customer=<customer code>&codes=<comma list, max 200>&limit=1..200&offset=0`
-> `{"data": [ROW, ...], "total": N, "limit": 100, "offset": 0}`, ordered by product name.

## 4. Hub webhook

`POST <receiver URL>` (public https only; re-checked before every attempt). Headers:

- `X-Hub-Connector-Event: availability.updated`
- `X-Hub-Connector-Delivery: <delivery id>`
- `X-Hub-Connector-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256(secret, t + "." + raw body)>`

Verify with the hub's signing secret (shown once at create / rotate); reject a `t` more than 5 minutes old.

```json
{
  "id": "<uuid>",
  "type": "availability.updated",
  "occurredAt": "2026-11-26T10:00:00Z",
  "data": {
    "hub": {"code": "ecohub"},
    "customer": {"code": "C-001", "name": "Customer company"},
    "sequence": 7,
    "full": false,
    "items": [{"code": "SR-1001", "name": "Basin mixer", "brand_name": "Brand A", "in_stock": true, "incoming": true}],
    "removed": ["SR-1007"]
  }
}
```

- One webhook per customer whose view changed. `sequence` increases per customer; ignore one older than the last
  you applied. Deliveries to one customer are sent oldest first.
- `full: true` is the customer's COMPLETE view (new customer, policy change, Show price switch, Resync, Send again):
  replace everything you hold for that customer. `full: false` lists only changed items.
- `removed`: items this customer may no longer see, or that left the feed: drop them.
- Answer any 2xx within 10 seconds. Anything else is retried after 1 min, 5 min, 30 min, 2 h, 6 h and 24 h, then
  marked failed and the customer's full view is queued once. "Send again" on the Deliveries tab sends the current
  full view.
