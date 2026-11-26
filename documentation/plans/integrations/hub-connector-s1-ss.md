# Hub connector S1 - shared-service side - plan

Fulfils `hub-connector-s1-ss-acceptance-criteria.md`. New App-Store module `hub_connector`
(schema `app_hub_connector`, tables `hc_*`), modelled on `modules/lead_capture` (gateway keys, signed consumer
delivery on core `app/services/webhook_post.py` + `app/services/url_guard.py`).

## Data (all rows carry `tenant_id`, plain indexed, no cross-schema FK)
- `hc_hubs`: name, code (unique per tenant), callback_url, secret_encrypted (Fernet), expose_price (default false),
  active, last_success_at.
- `hc_hub_customers`: hub_id, customer_code, location_codes_json, brand_codes_json, active; unique (hub, customer).
- `hc_customers`: customer company catalogue pushed by the CRM (code, name).
- `hc_items`: latest availability per item pushed by the CRM: code, name, brand code/name, price, currency,
  locations_json `[{code,name,onHand,reserved}]`, incoming_json `[{ref,locationCode|null,remaining}]`.
- `hc_sent_views`: last view hash sent per (hub customer, item) - only changes go out.
- `hc_api_keys`, `hc_deliveries` (body Fernet-encrypted, retry ladder as Lead Capture).

## Rules (single shared function `services/availability.py view_for`)
- got stock = any allowed location with on hand - reserved > 0.
- got incoming = any incoming remainder > 0 whose location is allowed or not yet allocated (null).
- brand filter = the item's brand is in the customer's brand list; price only when the hub's switch is on.

## API
Staff (JWT + `hub_connector.view/manage/keys.manage`), prefix `/hub-connector`:
- `GET/POST /hubs`, `GET/PATCH/DELETE /hubs/{id}`, `POST /hubs/{id}/rotate-secret`, `POST /hubs/{id}/resync`
- `GET/POST /hubs/{id}/customers`, `PATCH/DELETE /hubs/{id}/customers/{cid}`, `GET /hubs/{id}/customers/{cid}/preview`
- `GET /hubs/{id}/deliveries`, `POST /deliveries/{id}/redeliver`
- `GET /options/{customers|locations|brands}?search=`
- `GET/POST /keys`, `DELETE /keys/{id}`
Lists answer `{data,total,page,pageSize}` with server-side `search`, `sort`, `dir`, `page`, `pageSize`.

Inbound (public, `Authorization: Bearer fxh_live_...`), prefix `/api/v1/hub-connector`:
- `PUT /items` `{items:[{code,name,brand:{code,name},price?,currency?,locations:[{code,name,onHand,reserved}],
  incoming:[{ref,locationCode?,remaining}]}]}` -> `{stored, skipped:[{code,reason}], queued}`
- `PUT /customers` `{customers:[{code,name}]}` -> `{stored, skipped}`

Outbound: `availability.updated` envelope `{id,type,occurredAt,data:{hub:{code},customer:{code,name},
items:[{code,name,brand:{code,name},gotStock,gotIncoming,price?,currency?}],removed:[code]}}`, headers
`X-Hub-Connector-Event`, `X-Hub-Connector-Delivery`, `X-Hub-Connector-Signature`. Worker tasks
`hub_connector.deliver` + beat `hub_connector.deliveries_due` (60 s), module-absence safe.

## Frontend
Sidebar "Hub Connector" (module-gated). `/hub-connector` hubs Resource list; `/hub-connector/[id]` Resource form
with tabs Details (name, receiver URL, Show price switch, active) . Customers (embedded list; add/edit policy in a
centred dialog with searchable multi-selects for locations and brands; Preview dialog) . Deliveries (log, Send again).
CRM keys live in the list's gear menu.

## Open (to reconcile with the brief once forwarded)
- Exact AC-12..AC-19 wording and the CRM payload contract from HUB-CONNECTOR-S1-CRM.
- Whether hubs also pull (GET) the view; S1 here pushes webhooks + exposes an admin preview.
