# Lane P (META-P-PROTOTYPE) build notes

Backend spine of plan 64 lanes L1 / L3 / L4 for the first live lead (Foundryx Page -> EcoHub). Brief:
`briefs/lane-P-prototype-lead-to-ecohub.md`. Built on PR #237 (core Meta plumbing).

## What this slice ships

| Part | ACs (partial where noted) | Where |
|---|---|---|
| Module skeleton, schema `app_lead_capture`, Alembic `0001_lead_capture_init`, perms + install grant | 01, 02, 03 | `modules/lead_capture/` |
| Tables `lc_source`, `lc_settings`, `lc_lead`, `lc_webhook_endpoint`, `lc_delivery`, `lc_api_key`, `lc_api_audit` | 50, 55, 72 | `models.py` |
| Staff connect `POST /lead-capture/sources/facebook` (system-user token -> Page token, subscribe union, sharing rule under a lock) | 25, 36, 71 | `services/connect_service.py` |
| `page`/`leadgen` handler (enqueue only) + task: resolve all live sources, fetch, store, map, queue delivery | 24 (default map), 26, 27, 35 (notice data), 37 | `services/leadgen_service.py` |
| Gateway key `fxl_live_`, throttle + audit, webhooks register, signed push + retry ladder, pull | 60, 62, 63, 64, 65, 72 | `gateway_auth.py`, `services/delivery_service.py`, `routers/gateway.py` |
| Consumer guide | 66 | `documentation/lead-capture/consumer-integration-guide.md` |

## Decisions taken in this slice

- `isTest`: Meta's lead object carries no test flag. A lead with no `ad_id` is checked against
  `GET /{form_id}/test_leads`; a lead id listed there is a test lead. Any read error = not a test lead.
- Shared POST (R5): the deadline-bounded, connect-guarded POST moved from omnichannel's
  `webhook_delivery.py` to core `app/services/webhook_post.py`; omnichannel and Lead Capture both call it.
- Staff key management (`lead_capture.keys.manage`) is a small staff API in this slice so a key can be minted
  without UI.

## Out of scope (later lanes)

Wizard and every UI, backfill + token health + Reconnect, purge task, connect sessions, settings API beyond the
stored flag, `lead.updated` / `source.updated` events, duplicate rule, E.164 normalisation beyond the plain value Meta
sends.
