# AI dashboard builder - shared service, slice 1 (PR 1): plan + UAC

Lane AI-DASHBOARD-BUILDER-S1-SS, size L. Pair: AI-DASHBOARD-BUILDER-S1-CRM. Contract:
`SS-dashboards-contract.md` (CRM lane authored, mirrored byte for byte, sha256
6f9260e13f329830fa45976bfb68cee836739f2b7599688f790cbcd1733c9efb). Where this plan and the contract
disagree, THE CONTRACT WINS. Section numbers below (C2, C3.1 ...) point into the contract.
Product plan + UAC: sorento-crm PR #2862 (`PLAN-ai-dashboard-builder.md`, `ai-dashboard-builder-acceptance-criteria.md`).

## UAC (SS part of AC-1..AC-16b)

| SS-AC | Source AC | Given / When / Then | Tag |
| --- | --- | --- | --- |
| S-2 | AC-2 (server) | Given a sorento key and an empty draft, when `builder/turn` "monthly invoiced sales this year and top 10 customers" (model emits two `add_tile`), then 200 with two tiles ids `t1`,`t2` (SS-assigned), `changed_tile_ids` `["t1","t2"]`, a reply, `usage` {tokens_in, tokens_out, model}. | [BE][T] |
| S-3 | AC-3 (server) | Given the F1 draft, when the model emits `change_tile t1` (bucket quarter), then t1 changes in place, t2 is identical, `changed_tile_ids` `["t1"]`; remove/move/set_title/set_period apply in order; title-only and move are not in `changed_tile_ids`. | [BE][T] |
| S-4 | AC-4 (server) | When the model emits `ask` (2-5 options, each <= 60 chars), then `question` {text, options}, draft unchanged, `changed_tile_ids` `[]`; `ask` mixed with another op is not applied. | [BE][T] |
| S-6 | AC-6 | `save` with `dashboard_id` null creates (owner = actor, version 1, row `created`); save again bumps version (`saved` / `renamed` when only the name changed); stale `base_version` = 409 `version_conflict` + `current_version`; same `idempotency_key` (same key + actor, 24 h) returns the first response, one version row. | [BE][T] |
| S-6b | AC-6b | A recipient may get (gets `shared_with: []`, `mine: false`), list, read versions; a recipient's save / share / delete / builder turn on it = 403 `not_owner`; a stranger = 404 `not_found` on every call. | [BE][T] |
| S-7 | AC-7 | Save, turn draft and the model's result refuse (422 `spec_invalid`, `problems[{path, reason}]`, plain reasons): extra key, `<`, `>`, `://`, `;`, `--`, `/*`, control char in ANY string, caps (12 tiles, 32768 bytes, titles 80, tile id `^t[0-9]{1,3}$` unique), pivot/widget/report = "This chart type is not available yet.", number/line/bar/table shape rules, entity / field / group / aggregate / show not in the catalogue. Get of a stored spec that no longer validates returns it with `spec_problems`. | [BE][T] |
| S-7i | AC-7 (security) | Catalogue label text or a user message telling the model to use entity `payroll` (not in catalogue): the validator refuses, SS retries once, then 502 `ai_failed`, nothing saved, draft never contains the outside entity. | [BE][T] |
| S-10 | AC-10 | `list` scope all/mine/shared, `q`, server sort (name / updated_at / owner_ref, asc/desc), page/limit (limit max 100); never lists a dashboard the actor neither owns nor is shared on. | [BE][T] |
| S-15 | AC-15 | Each create / save / rename / share writes one version row; `versions` newest first with `changes` (`charts` counts, `name`, `shared_with`). | [BE][T] |
| S-16 | AC-16 | One turn (even with the one retry) writes exactly one `dash_usage` row (tenant, product, feature `dashboard_builder`, dashboard id, actor_ref, model, tokens summed) before answering; get / list / versions / save / share / delete never call the LLM (call counter). | [BE][T] |
| S-16b | AC-16b | Key tenant A / product X can never read, list, save, share, delete, version-list or build against tenant B or product Y (404, never listed); body/query `tenant` (id or slug) or `product` that disagrees = 403 `tenant_mismatch` / `product_mismatch`; no / unknown / revoked key = 401 `invalid_api_key`; module off for the tenant = 403 `service_not_enabled`. | [BE][T] |
| S-C | C8 | Fixtures F1..F13 in `modules/dashboards/contract_fixtures/` replay against the real service with the contract's status, error code and response keys. | [T] |
| S-19 | AC-19 | No WhatsApp path: omnichannel never imports the dashboards module and the module registers no workflow trigger / action. | [T] |

## Design

Module `service_backend/modules/dashboards/` (schema `app_dashboards`, own alembic `alembic_version_dashboards`),
shape copied from `modules/planner3d` (manifest, db.py, bootstrap, permissions csv, alembic env).
Routers: `gateway` at `/api/v1/dashboards` (public, key auth) and `staff` at `/dashboards-admin` (staff keys).

Tables (UUID string ids, `tenant_id` + `product` on every row, `UTCDateTime`):
- `dash_api_key` (tenant_id, product, name, key_prefix, key_hash, key_last4, created_by, last_used_at, revoked_at) -
  repeat of `planner3d/services/key_service.py` (cross-module imports forbidden, BL-SS-210), scheme `fxd_live_`, plus `product`.
- `dash_api_audit` (tenant_id, product, key_id, method, route, status_code) - planner3d AuditedRoute pattern.
- `dash_dashboard` (tenant_id, product, owner_ref, name, spec_json, version, created_at, updated_at).
- `dash_share` (dashboard_id FK cascade, tenant_id, product, user_ref; unique dashboard+user) - "shared with me" is a query.
- `dash_version` (dashboard_id FK cascade, tenant_id, product, version, action, actor_ref, changes_json, created_at).
- `dash_idempotency` (tenant_id, product, key_id, actor_ref, idempotency_key, request_hash, response_json, created_at;
  unique key_id+actor_ref+idempotency_key; older than 24 h ignored).
- `dash_usage` (tenant_id, product, feature, dashboard_id, actor_ref, provider, model, tokens_in, tokens_out,
  latency_ms, llm_calls, trace_id, created_at) - not touched by `app/ai/retention.py` (AC-16 needs it kept).

Auth (`gateway_auth.py`): header `X-API-Key` (C1). planner3d order (`planner3d/gateway_auth.py:57-87`): IP throttle on
401s -> key -> tenant may sign in + module ACTIVE (else `service_not_enabled`) -> per-key budget -> audit. Core
`ThrottleService` gains `dashboards_gateway` + `dashboards_gateway_key` scopes (additive, like planner3d's,
`app/services/throttle.py:558-572`). Echo check: a body/query `tenant` equal to neither the key's tenant id nor its slug
= `tenant_mismatch`; `product` not equal = `product_mismatch`. Errors render as the contract's flat body
`{"error", "message", (+problems | current_version)}` (C3.8) from the module's own route class, so the core
`ApiError` envelope is untouched; request-body validation failures render as 422 `spec_invalid` with problems.

LLM: reuse `AiClient.complete` (`app/ai/client.py:148`) - no second client. The builder is a seeded SYSTEM AGENT per
tenant, key `dashboard-builder` (precedent `modules/ideation/services/grill.py:56,75`), ensured lazily on the first turn
(existing tenants need no backfill); empty `connection_id` is filled from `any_llm_connection` (`ai/client.py:70`).
No connection: 409 `ai_not_configured` (development = stub). Call with `output_schema` = `{reply, operations[]}`.
The catalogue, the draft, refusals and history go in as JSON data; the operations are applied by a pure function
(C5: add_tile assigns the next free id; ask stands alone); the result is validated (schema + rules + catalogue). On
problems SS calls the model ONCE more with the problems, then 502 `ai_failed` (C5). The validator is the gate, not
the prompt. One `dash_usage` row per turn, tokens summed over the calls, written before answering.

Validator (`spec.py`): Pydantic v2 models, `extra="forbid"`, closed Literals, caps + a recursive string scan for the
C2 forbidden sequences + the C2 shape rules; `validate_against_catalogue(spec, catalogue)` (entity, field paths
incl. one relation hop `relation.field`, group / aggregate / filter / fields paths, `show` per entity,
`totals_allowed` false = table only, bucket only on date fields, sort field = a known path or an aggregate alias
`<fn>_<field>` / `count`). Problems are `{path, reason}` in plain words. Run on save, on the turn's incoming draft,
on the model's result, and on get (C3.3 -> `spec_problems`).

Staff keys: `POST /dashboards-admin/keys {name, product}` (201, key shown once), list, revoke; gated
`dashboards.keys.manage` (module CSV; App Store grants module keys to the tenant Admin on install/update). No SS UI
in slice 1. Products: `sorento_crm`, `ecohub`. `dashboards.view` / `dashboards.build` are CRM slugs (C1), not SS rows.

Migration: `0001_dashboards_baseline` - `CREATE SCHEMA IF NOT EXISTS` + `create_all(checkfirst)`; new tables only, no
ALTER / DROP of anything existing. Timing posted as `crew-note: migration-timing`.

Conftest: `app_dashboards` mapped onto the attached `connector` db in all 4 schema_translate_maps.

Tests (`tests/test_dashboards_*.py`) use `stub_fixtures(StubResponse(structured=...))` (`app/ai/stub.py`); no paid call.

## Reuse list
- `app/ai/client.py:148` AiClient.complete, `:70` any_llm_connection; `app/ai/stub.py` stub_fixtures.
- AgentRepository.get_by_key + system-agent seeding (ideation grill precedent).
- `modules/planner3d/gateway_auth.py:57-87` + `services/key_service.py` (repeated, BL-SS-210).
- `app/services/throttle.py` ThrottleService; `app/repositories/module_repository.py` is_active.

## Out of scope (slice 1)
SS UI; usage view; report / widget / pivot (refused); per-product on/off switch beyond the module switch;
WhatsApp (AC-19 guarded); AC-17 / AC-18.
