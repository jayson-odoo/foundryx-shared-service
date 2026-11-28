# Hub connector S1 - shared-service side - plan

Fulfils `hub-connector-s1-ss-acceptance-criteria.md`. App-Store module `hub_connector` (schema `app_hub_connector`,
tables `hc_*`), modelled on `modules/lead_capture` (keys, signed consumer delivery on core
`app/services/webhook_post.py` + `app/services/url_guard.py`). Facts come from the frozen CRM connector feed
(sorento-crm #2801) which this module PULLS. Contract of record for hubs: `documentation/hub-connector/integration-guide.md`.

## Data (all rows carry `tenant_id`, plain indexed, no cross-schema FK)
- `hc_hubs` (name, code, receiver URL, Fernet signing secret, `expose_price` default false, active).
- `hc_hub_customers` (hub, customer code + name typed by the admin, location codes, brand codes, active).
- `hc_locations`, `hc_brands`, `hc_items` (feed mirror; items hold `[{code, available}]` and incoming lines),
  `hc_sync_state` (last run / success / error per tenant).
- `hc_sent_views` (last view hash per customer + item), `hc_deliveries` (sequence, full flag, Fernet body),
  `hc_api_keys` (hub read keys, one hub each).

## Feed connection
Core `connections` row, provider `crm_connector_feed`, type `hub_source` (one per tenant), registered from the
module's boot hook; configured on Settings, Integrations (no bespoke screen). Guarded transport outside development.

## Rules
`services/availability.py view_for` is the one function behind preview, the hub read API and the webhook.

## Jobs
Beat `hub_connector.sync_due` (10 min) and `hub_connector.deliveries_due` (60 s); `hub_connector.deliver` per delivery.

## Open
- Delta sync via `updated_since` (S1 reads all products each run; fine at current catalogue size).
- CRM push (S2) will only name changed codes; the sync then reads just those.
