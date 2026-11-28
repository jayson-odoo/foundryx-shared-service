# AI dashboard builder - shared service, slice 1 (PR 1): plan + UAC

Lane AI-DASHBOARD-BUILDER-S1-SS, size L. Pair: AI-DASHBOARD-BUILDER-S1-CRM. Contract:
`SS-dashboards-contract.md` (CRM lane authors; until it arrives the SS draft
`SS-dashboards-contract.DRAFT-SS.md` is what code follows).

## UAC (SS part of AC-1..AC-16b)

| SS-AC | Source AC | Given / When / Then | Tag |
| --- | --- | --- | --- |
| S-2 | AC-2 (server) | Given a key for tenant A / sorento_crm and an empty draft, when `builder/turn` "show total sales this month", then the response has a draft with one tile from the catalogue, a reply, `applied=true`, usage tokens + model. | [BE][T] |
| S-3 | AC-3 (server) | Given a draft with 2 tiles, when the model emits change/remove/move/set_title/set_period, then the returned draft reflects exactly those ops in order. | [BE][T] |
| S-4 | AC-4 (server) | When the model emits `ask`, then `question.text` + `question.options` (real options) return and the draft is unchanged. | [BE][T] |
| S-6 | AC-6 | Save create -> 201, owner = userRef; save again -> version+1; same Idempotency-Key + same body -> same response, different body -> 409. | [BE][T] |
| S-6b | AC-6b | A non-owner (shared or not) save / share / rename / delete -> 403 not_owner; a shared user get/list -> read-only access=shared; a stranger get -> 404. | [BE][T] |
| S-7 | AC-7 | A spec (save, load, or a model-produced draft) with an unknown entity / field, extra key, URL, HTML tag, pivot/widget show, report/widget kind, over the caps -> refused with a plain reason per problem (422 on save; `applied=false` + problems on turn). | [BE][T] |
| S-7i | AC-7 (security) | Catalogue text or a user message that tells the model to use another entity cannot get a tile outside the catalogue into the draft: the validator refuses it regardless of the prompt. | [BE][T] |
| S-10 | AC-10 | `list` returns mine and shared-with-me with an `access` flag, paginated, tenant+product scoped. | [BE][T] |
| S-15 | AC-15 | Each create / save / rename / share writes a version row (who, when, action, old -> new); `versions` lists them newest first. | [BE][T] |
| S-16 | AC-16 | One turn writes exactly one `dash_usage` row (tenant, product, feature `dashboard_builder`, dashboard id, user_ref, model, tokens); get/list/versions/save never call the LLM (proved by a stub call counter). | [BE][T] |
| S-16b | AC-16b | Key for tenant A/product X can never read, list, save, share, delete, version-list or build against tenant B or product Y; a body/query naming another tenant or product -> 403 tenant_mismatch / product_mismatch; no key/bad key -> 401; module inactive -> 403 service_not_enabled. | [BE][T] |
| S-C | contract | Every fixture in `contract_fixtures/` replays against the real service with the same status and the same response shape. | [T] |
| S-19 | AC-19 | No omnichannel / WhatsApp workflow node or trigger can build or show a dashboard (guard test: the dashboards module registers no workflow node and omnichannel never imports it). | [T] |

## Design

Module `service_backend/modules/dashboards/` (schema `app_dashboards`, own alembic `alembic_version_dashboards`),
copied from `modules/planner3d` shape (manifest, db.py, bootstrap, permissions csv, alembic env).

Tables (all UUID string ids, `tenant_id` + `product` on every row, `UTCDateTime`):
- `dash_api_key` (tenant_id, product, name, key_prefix, key_hash, key_last4, created_by, last_used_at, revoked_at) - copy of `planner3d/services/key_service.py:28-90`, scheme `fxd_live_`, plus `product`.
- `dash_api_audit` (tenant_id, product, key_id, method, route, status_code) - copy of `planner3d/gateway_auth.py` AuditedRoute.
- `dash_dashboard` (tenant_id, product, owner_ref, name, spec_json, version int, created_at, updated_at).
- `dash_share` (dashboard_id FK cascade, tenant_id, product, user_ref; unique dashboard+user) - queryable "shared with me".
- `dash_version` (dashboard_id FK cascade, tenant_id, product, version, action, actor_ref, old_json, new_json, created_at).
- `dash_idempotency` (tenant_id, product, idempotency_ref, request_hash, dashboard_id, status_code, response_json; unique tenant+product+ref).
- `dash_usage` (tenant_id, product, feature, dashboard_id, user_ref, provider, model, tokens_in, tokens_out, latency_ms, trace_id, created_at) - not touched by `app/ai/retention.py`.

Auth (`gateway_auth.py`): planner3d order (IP throttle on 401s -> key -> tenant signin + module ACTIVE ->
per-key budget -> audit). Core `ThrottleService` gains `dashboards_gateway` + `dashboards_gateway_key` scopes
(additive, like planner3d's, `app/services/throttle.py:558-572`). `check_echo(key, tenant, product)` raises
`tenant_mismatch` / `product_mismatch`; the tenant echo matches the key's tenant id OR slug.

LLM: reuse `AiClient.complete` (`app/ai/client.py:148`). The builder is a seeded SYSTEM AGENT per tenant,
key `dashboard-builder` (ideation grill precedent, `modules/ideation/services/grill.py:56,75`), ensured lazily at the
first turn (so existing tenants need no backfill); its `connection_id` is set from `any_llm_connection`
(`ai/client.py:70`) when empty. No connection anywhere -> 409 `ai_not_configured` (dev = stub). One call with
`output_schema` = `{reply, operations[]}`. Operations applied by a pure function; result validated. The catalogue
and the draft go to the model as JSON data in the user message; the validator is the gate, not the prompt.

Validator (`spec.py`): Pydantic v2 models with `extra="forbid"`, closed Literals, caps, text checks; plus
`validate_against_catalogue(spec, catalogue)`; problems as `{path, reason}` in plain words. Run on save, on load,
on the request draft and on the model's result.

Keys are issued by staff (no UI in slice 1): `POST /dashboards-admin/keys` gated `dashboards.keys.manage`
(module CSV, granted to tenant Admin by the App Store on install/update). The owner's "Build dashboards"
permission (`dashboards.build`) is a CRM permission checked by the CRM before it calls SS (the SS call is made by
the CRM backend with the key, never by a browser), so SS has no `dashboards.build` row.

Migration: `0001_dashboards_baseline` creates the schema + tables (`CREATE ... IF NOT EXISTS` via
`create_all(checkfirst)`); new tables only, nothing altered. Timing on empty tables is O(ms); posted as
`crew-note: migration-timing`.

Conftest: map `app_dashboards` onto the attached `connector` db in every schema_translate_map
(`tests/conftest.py` 4 places), else the module lands in ERRORED_MODULES.

Tests: `tests/test_dashboards_*.py`, stub provider via `stub_fixtures(StubResponse(structured=...))`.

## Reuse list
- `app/ai/client.py:148` AiClient.complete; `app/ai/stub.py` stub_fixtures; `ai/client.py:70` any_llm_connection.
- `modules/planner3d/gateway_auth.py:57-87`, `services/key_service.py` (repeated - cross-module imports are forbidden, BL-SS-210).
- `app/api_errors.py:23` ApiError envelope; `app/services/throttle.py` ThrottleService.
- AgentRepository.get_by_key (ideation grill precedent).

## Out of scope (slice 1)
SS UI; usage view; pivot / widget / report sources (refused); WhatsApp (AC-19 guarded); AC-17/18.
