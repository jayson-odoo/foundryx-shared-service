# SS dashboards contract - SS lane DRAFT (v1)

Status: DRAFT written by the SS lane from the lane brief's 7 points while the CRM lane's
`SS-dashboards-contract.md` is pending. When the CRM file arrives it is committed here byte for byte
as `SS-dashboards-contract.md` and the code is aligned to it; this draft is then deleted.
All names live in one place in code (`modules/dashboards/schemas.py` + `modules/dashboards/contract_fixtures/`)
so an alignment is a rename, not a redesign.

## 1. Auth and isolation

- `Authorization: Bearer fxd_live_<secret>` on every call. One key = one tenant AND one product
  (`sorento_crm` | `ecohub`). Tenant and product come ONLY from the key.
- A body or query that carries `tenant` (id or slug) or `product` that disagrees with the key:
  `403 tenant_mismatch` / `403 product_mismatch`. Never silently overridden. Omitted = fine.
- Default deny: missing / malformed / unknown / revoked key `401 invalid_api_key`; tenant cannot
  sign in or module not ACTIVE `403 service_not_enabled`; too many 401s from an IP or too many
  calls on a key `429 rate_limited` + `Retry-After`.
- The acting person is `userRef` (the product's own user id, opaque string <= 64 chars). SS trusts
  the product for who the user is; SS enforces owner-only writes and shared-read.

Error envelope (house `ApiError`): `{"error": {"code": "...", "message": "...", "details": ...}}`.

| code | status | when |
| --- | --- | --- |
| invalid_api_key | 401 | key missing / bad / revoked |
| service_not_enabled | 403 | tenant suspended or module not active |
| tenant_mismatch | 403 | body/query tenant disagrees with the key |
| product_mismatch | 403 | body/query product disagrees with the key |
| not_owner | 403 | a non-owner tries save / share / rename / delete |
| not_found | 404 | no such dashboard for this tenant+product, or not visible to `userRef` |
| spec_invalid | 422 | `details.problems[] = {path, reason}` plain reasons |
| idempotency_conflict | 409 | same `Idempotency-Key`, different body |
| version_conflict | 409 | `baseVersion` is not the current version |
| ai_not_configured | 409 | no AI connection for the tenant |
| ai_failed | 502 | the model call failed |
| rate_limited | 429 | throttle |

## 2. Spec schema v1 (JSON Schema)

Extra keys are refused at every level.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "foundryx/dashboards/spec/v1",
  "type": "object",
  "additionalProperties": false,
  "required": ["version", "title", "tiles"],
  "properties": {
    "version": {"const": 1},
    "title": {"type": "string", "minLength": 1, "maxLength": 120},
    "period": {"$ref": "#/$defs/period"},
    "tiles": {"type": "array", "maxItems": 24, "items": {"$ref": "#/$defs/tile"}}
  },
  "$defs": {
    "period": {
      "type": "object", "additionalProperties": false,
      "properties": {
        "preset": {"enum": ["today", "yesterday", "last_7_days", "last_30_days", "this_week", "this_month",
                            "last_month", "this_quarter", "last_quarter", "this_year", "last_year", "custom"]},
        "from": {"type": "string", "format": "date"},
        "to": {"type": "string", "format": "date"}
      },
      "required": ["preset"]
    },
    "tile": {
      "type": "object", "additionalProperties": false,
      "required": ["id", "title", "show", "source"],
      "properties": {
        "id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9_-]{0,39}$"},
        "title": {"type": "string", "minLength": 1, "maxLength": 120},
        "show": {"enum": ["number", "line", "bar", "table", "pivot", "widget"]},
        "period": {"$ref": "#/$defs/period"},
        "source": {
          "type": "object", "additionalProperties": false,
          "required": ["kind", "spec"],
          "properties": {"kind": {"enum": ["query", "report", "widget"]}, "spec": {"$ref": "#/$defs/query"}}
        }
      }
    },
    "query": {
      "type": "object", "additionalProperties": false,
      "required": ["entity", "measure"],
      "properties": {
        "entity": {"type": "string", "maxLength": 64},
        "measure": {
          "type": "object", "additionalProperties": false, "required": ["agg"],
          "properties": {"agg": {"enum": ["count", "sum", "avg", "min", "max"]}, "field": {"type": "string", "maxLength": 64}}
        },
        "groupBy": {"type": "string", "maxLength": 64},
        "dateField": {"type": "string", "maxLength": 64},
        "filters": {
          "type": "array", "maxItems": 10,
          "items": {
            "type": "object", "additionalProperties": false, "required": ["field", "op", "value"],
            "properties": {
              "field": {"type": "string", "maxLength": 64},
              "op": {"enum": ["eq", "neq", "in", "gt", "gte", "lt", "lte"]},
              "value": {"oneOf": [{"type": ["string", "number", "boolean"]},
                                  {"type": "array", "maxItems": 50, "items": {"type": ["string", "number"]}}]}
            }
          }
        },
        "columns": {"type": "array", "maxItems": 12, "items": {"type": "string", "maxLength": 64}},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100}
      }
    }
  }
}
```

Caps: 24 tiles, 32 KB serialized spec, titles 120 chars, string filter values 200 chars.
Slice 1: `show` in `number|line|bar|table` (pivot / widget refused "not available yet");
`source.kind` = `query` only (report / widget refused "not available yet").
Text fields (titles, string filter values) refuse HTML tags and URLs. There is no field that can hold
SQL: a query is entity + measure + group + filters only, and unknown keys are refused.

### Catalogue (sent by the product, the viewer's own)

```json
{"entities": [{"key": "sales_order", "label": "Sales orders", "show": ["number", "line", "bar", "table"],
  "fields": [{"key": "amount", "label": "Amount", "type": "number", "aggregates": ["sum", "avg", "min", "max"],
              "groupable": false},
             {"key": "salesperson", "label": "Salesperson", "type": "string", "aggregates": [], "groupable": true},
             {"key": "order_date", "label": "Order date", "type": "date", "aggregates": [], "groupable": true}]}]}
```

Field `type` in `string|number|date|boolean`. `count` needs no field. Against a catalogue the
validator refuses: unknown entity, unknown field (measure / groupBy / dateField / filter / columns),
an aggregate the field does not allow, a `show` the entity does not allow, a non-date `dateField`.

## 3. Endpoints (prefix `/api/v1/dashboards`)

All bodies JSON, camelCase. Optional `tenant` / `product` echo fields on every body (GET: query).

### POST `/builder/turn`
Request: `{userRef, dashboardId?, draft (spec|null), message (<=2000), catalogue, refusals?: [{tileId, kind: no_access|restricted|module_disabled, reason}]}`
Response 200: `{draft, reply, question: {text, options: [string]} | null, applied: bool, problems: [{path, reason}],
usage: {tokensIn, tokensOut, model}}`.
One LLM call. The model returns `{reply, operations[]}`; ops are applied in order to the draft; the
result is validated against schema + catalogue. Invalid result: `applied=false`, `draft` = the
request draft unchanged, `problems` say why. `ask` op: `question` set, draft unchanged.
An invalid request draft = `422 spec_invalid`. No AI connection = `409 ai_not_configured`.

Operations (the model's whole vocabulary):
`add_tile {tile, index?}`, `change_tile {tileId, tile}`, `remove_tile {tileId}`, `move_tile {tileId, toIndex}`,
`set_title {title}`, `set_period {period}`, `ask {question, options}`.

### GET `/dashboards?userRef=&scope=all|mine|shared&page=1&pageSize=25`
`{items: [{id, name, ownerRef, access: owner|shared, version, updatedAt}], total, page, pageSize}`; pageSize <= 100.

### GET `/dashboards/{id}?userRef=`
`{id, name, ownerRef, access, version, spec, sharedWith: [{userRef}], createdAt, updatedAt}`. Visible to the owner and
to each `sharedWith` user; anyone else `404 not_found`. The stored spec is re-validated on load.

### POST `/dashboards` (create) and POST `/dashboards/{id}` (save a new version)
Header `Idempotency-Key` (optional, <=128). Body `{userRef, name, spec, baseVersion?, catalogue?}`.
201 (create) / 200 (save) with the dashboard body. Owner only. A name change on save writes a `rename` row.

### POST `/dashboards/{id}/share`
`{userRef, sharedWith: [{userRef}]}` (<= 50, owner excluded, replaces the list). Owner only.

### POST `/dashboards/{id}/delete`
`{userRef}` -> 204. Owner only. Deletes the dashboard, its shares and its history.

### GET `/dashboards/{id}/versions?userRef=&page=&pageSize=`
`{items: [{id, version, action: create|save|rename|share, actorRef, at, old, new}], total, page, pageSize}`.
Owner and shared users may read.

## 4. Usage (AC-16)
Each builder turn writes ONE `dash_usage` row: tenant, product, feature `dashboard_builder`, dashboard id,
user_ref, provider, model, tokens in/out, latency. Not pruned by the AI trace retention sweep.
`get` / `list` / `versions` never call the model.

## 5. Stub
`service_backend/modules/dashboards/contract_fixtures/*.json` = one request/response pair per endpoint and
per error code. The CRM stub serves these; SS contract tests replay them against the real service.
