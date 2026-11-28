# Contract: shared service dashboards (builder + store), v2

Status: v2, written by lane AI-DASHBOARD-BUILDER-S1-CRM (28 Nov 2026). v2 = owner 28 Nov ~13:45: up to 5 images per
builder message, catalogue lookup on demand (no full dump per turn), the spec shape ready for every chart kind,
formula, layout, drill-down and two-source chart (slice 1 still draws number / line / bar / table only). Committed byte for byte in BOTH repos
(jayson-odoo/sorento-crm and jayson-odoo/foundryx-shared-service) at `documentation/plans/ai-builder/SS-dashboards-contract.md`.
A change goes through a crew-ask to both lanes and changes the sha256 posted on both PRs; never one-sided.
Plan: `PLAN-ai-dashboard-builder.md` sections 3, 4.3-4.5, 6. UAC: AC-1..AC-16b.

Words: the SS and CRM code say spec / tile / catalogue; no screen ever shows those words (Dashboard, Chart, Table).

## 0. Who calls whom

- Only the product backend (CRM) calls SS. The browser never calls SS and SS never calls the CRM.
- SS holds dashboard specs and their version rows, runs the builder LLM turn and logs its tokens. SS holds no data rows.
- The CRM builds the viewer's catalogue, runs every chart as the viewer, and resolves names. Data never leaves the CRM.

## 1. Transport and auth

- Base URL and key: stored in the CRM as one encrypted integration row (`integrations.type = "shared_service_dashboards"`,
  `config_json.base_url`, `credentials_json.api_key`), set on Settings > Integrations. Never env.
- Every call: HTTPS, JSON body (`Content-Type: application/json`), header `X-API-Key: <key>`.
- All paths below are under the prefix `/api/v1/dashboards`.
- One key per product and tenant. SS resolves `tenant` and `product` FROM THE KEY. A body or query `tenant` / `product`
  is optional; when present and different from the key's, SS answers 403 `tenant_mismatch` / `product_mismatch`.
- Default deny: no key, unknown key, revoked key = 401 `invalid_api_key`; a key whose product has the dashboards
  service switched off = 403 `service_not_enabled`. A dashboard of another tenant or product is `not_found` (404),
  never 403, so its existence does not leak.
- `actor_ref`: every call names the product user making it (CRM `users.id`, a string, max 64 chars). The product has
  already authenticated that user and checked its own slugs (`dashboards.view` / `dashboards.build`); SS checks
  ownership and sharing against `actor_ref`. `actor_ref` and `owner_ref` are never shown on a screen.

## 2. Spec schema (spec `version` 1; JSON Schema, draft 2020-12)

Caps: at most 24 tiles per dashboard, spec at most 65536 bytes (UTF-8, compact JSON), `title` 1-80 chars after trim,
tile `title` 1-80 chars, tile `id` matches `^t[0-9]{1,3}$` and is unique within the spec. Every object refuses extra keys.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "dashboard-spec-v1",
  "type": "object",
  "additionalProperties": false,
  "required": ["version", "title", "period", "tiles"],
  "properties": {
    "version": {"const": 1},
    "title": {"type": "string", "minLength": 1, "maxLength": 80},
    "period": {"$ref": "#/$defs/period"},
    "tiles": {"type": "array", "maxItems": 24, "items": {"$ref": "#/$defs/tile"}}
  },
  "$defs": {
    "period": {
      "oneOf": [
        {"enum": ["today", "yesterday", "this_week", "last_week", "this_month", "last_month",
                  "this_quarter", "last_quarter", "this_year", "last_year"]},
        {"type": "object", "additionalProperties": false, "required": ["from", "to"],
         "properties": {"from": {"type": "string", "format": "date"}, "to": {"type": "string", "format": "date"}}}
      ]
    },
    "tile": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "title", "show"],
      "oneOf": [{"required": ["source"]}, {"required": ["series"]}],
      "properties": {
        "id": {"type": "string", "pattern": "^t[0-9]{1,3}$"},
        "title": {"type": "string", "minLength": 1, "maxLength": 80},
        "show": {"enum": ["number", "kpi_target", "gauge", "line", "area", "bar", "stacked_bar", "combo", "pie",
                          "scatter", "heatmap", "table", "pivot", "map", "widget"]},
        "source": {"$ref": "#/$defs/source"},
        "series": {"type": "array", "minItems": 1, "maxItems": 4, "items": {"$ref": "#/$defs/series_item"}},
        "calc": {"type": "array", "maxItems": 4, "items": {"$ref": "#/$defs/calc"}},
        "target": {"$ref": "#/$defs/target"},
        "display": {"$ref": "#/$defs/display"},
        "size": {"type": "object", "additionalProperties": false, "required": ["w", "h"],
                 "properties": {"w": {"type": "integer", "minimum": 1, "maximum": 4},
                                "h": {"type": "integer", "minimum": 1, "maximum": 4}}},
        "position": {"type": "object", "additionalProperties": false, "required": ["x", "y"],
                     "properties": {"x": {"type": "integer", "minimum": 0, "maximum": 3},
                                    "y": {"type": "integer", "minimum": 0, "maximum": 99}}},
        "drill": {"enum": ["list", "none"]}
      }
    },
    "series_item": {
      "type": "object", "additionalProperties": false, "required": ["key", "label", "source"],
      "properties": {
        "key": {"type": "string", "pattern": "^s[0-9]$"},
        "label": {"type": "string", "minLength": 1, "maxLength": 60},
        "source": {"$ref": "#/$defs/source"},
        "as": {"enum": ["bar", "line", "area"]}
      }
    },
    "calc": {
      "type": "object", "additionalProperties": false, "required": ["key", "op", "args"],
      "properties": {
        "key": {"type": "string", "pattern": "^c[0-9]$"},
        "label": {"type": "string", "minLength": 1, "maxLength": 60},
        "op": {"enum": ["difference", "ratio", "percent_of_total", "percent_change", "running_total", "average_of",
                        "sum_of", "percent_of_target"]},
        "args": {"type": "array", "minItems": 1, "maxItems": 2,
                 "items": {"type": "string", "pattern": "^([a-z][a-z0-9_]{0,127}|s[0-9]\\.[a-z][a-z0-9_]{0,127}|target)$"}}
      }
    },
    "target": {
      "oneOf": [
        {"type": "object", "additionalProperties": false, "required": ["value"], "properties": {"value": {"type": "number"}}},
        {"type": "object", "additionalProperties": false, "required": ["source"], "properties": {"source": {"$ref": "#/$defs/source"}}}
      ]
    },
    "display": {
      "type": "object", "additionalProperties": false,
      "properties": {
        "legend": {"type": "boolean"}, "values": {"type": "boolean"}, "stacked": {"type": "boolean"},
        "axis_min": {"type": "number"}, "axis_max": {"type": "number"},
        "top_n": {"type": "integer", "minimum": 1, "maximum": 50},
        "other_bucket": {"type": "boolean"}
      }
    },
    "source": {
      "type": "object",
      "additionalProperties": false,
      "required": ["kind", "spec"],
      "properties": {
        "kind": {"enum": ["query", "report", "widget"]},
        "spec": {"$ref": "#/$defs/query"}
      }
    },
    "query": {
      "type": "object",
      "additionalProperties": false,
      "required": ["entity"],
      "properties": {
        "entity": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,63}$"},
        "filters": {"type": "array", "maxItems": 20, "items": {"$ref": "#/$defs/filter"}},
        "group_by": {"type": "array", "maxItems": 4, "items": {"$ref": "#/$defs/group"}},
        "aggregates": {"type": "array", "maxItems": 8, "items": {"$ref": "#/$defs/aggregate"}},
        "fields": {"type": "array", "maxItems": 8, "items": {"$ref": "#/$defs/path"}},
        "sort": {"type": "array", "maxItems": 4, "items": {"$ref": "#/$defs/sort"}},
        "limit": {"type": "integer", "minimum": 1, "maximum": 200}
      }
    },
    "path": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,63}(\\.[a-z][a-z0-9_]{0,63}){0,2}$"},
    "filter": {
      "type": "object", "additionalProperties": false, "required": ["field", "op"],
      "properties": {
        "field": {"$ref": "#/$defs/path"},
        "op": {"enum": ["eq", "ne", "in", "not_in", "lt", "lte", "gt", "gte", "between", "contains",
                        "starts_with", "is_null", "is_not_null"]},
        "value": {"$ref": "#/$defs/value"}
      }
    },
    "value": {
      "oneOf": [
        {"type": "string", "maxLength": 200}, {"type": "number"}, {"type": "boolean"}, {"type": "null"},
        {"type": "array", "maxItems": 100, "items": {"oneOf": [{"type": "string", "maxLength": 200}, {"type": "number"}]}}
      ]
    },
    "group": {
      "oneOf": [
        {"$ref": "#/$defs/path"},
        {"type": "object", "additionalProperties": false, "required": ["field"],
         "properties": {"field": {"$ref": "#/$defs/path"}, "bucket": {"enum": ["day", "week", "month", "quarter", "year"]}}}
      ]
    },
    "aggregate": {
      "type": "object", "additionalProperties": false, "required": ["fn"],
      "properties": {
        "fn": {"enum": ["count", "count_distinct", "sum", "avg", "min", "max"]},
        "field": {"$ref": "#/$defs/path"}
      }
    },
    "sort": {
      "type": "object", "additionalProperties": false, "required": ["field"],
      "properties": {"field": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,127}$"}, "dir": {"enum": ["asc", "desc"]}}
    }
  }
}
```

Rules on top of the schema (both sides check them; SS on save, builder turn and get; CRM on every load and run):

- The schema is the full vocabulary (owner 28 Nov ~13:45: "as much as we can imagine", always checked options, never
  code). Slice 1 DRAWS: `source.kind = "query"`, `show` in `number | line | bar | table`, a single `source`; `size`
  and `display` are accepted and may be ignored by the renderer. Every other kind / show / `series` / `calc` /
  `target` / `position` / `drill` is valid schema that slice 1 answers per chart with the plain reason "This chart
  type is not available yet." (the CRM shows it in the chart frame; SS never refuses to SAVE it). The builder model
  is told in its prompt which subset the product draws today (`catalogue.draws`, section 4) and offers only those.
- Meaning of the later options (fixed now so later slices add renderers, not schema): `series` = up to 4 sources on
  one chart (combo, two-source over registered relations, each its own `run_query` as the viewer); `as` = how a
  series draws on a combo; `calc` = a computed column over the chart's aggregates or series (`args` name an
  aggregate alias such as `sum_sales_amount`, a series column `s1.sum_sales_amount`, or `target`); `target` = a fixed
  number or a source for KPI-with-target and gauge; `map` needs a group field the catalogue marks `"type": "location"`;
  `heatmap` needs two group fields; `pie` one group field and one aggregate; `scatter` two number aggregates over
  one group field; `size` = grid cells (4 columns); `position` = free layout cell (absent = dashboard order);
  `drill` = clicking a point opens the matching list screen filtered the same way.
- No string anywhere in the spec may contain `<`, `>`, `://`, `;`, `--`, `/*` or a control character (SQL, URL and
  HTML refused, AC-7). Reason: "Only names and values can be used in a chart, not code or links."
- `entity`, every field path and every group / aggregate field must be in the catalogue given with the turn
  (builder turn) or, on CRM load, in the viewer's own catalogue (else the chart is "No access", not a refusal of the
  whole dashboard).
- `number` needs exactly one aggregate and no `group_by`; `line` and `bar` need one `group_by` and at least one
  aggregate; `table` takes either rows (`fields`) or groups.

Refusal shape (`spec_invalid`, 422): `{"error": "spec_invalid", "problems": [{"path": "tiles[1].source.spec.entity", "reason": "..."}]}`.
`path` is for logs and tests; only `reason` is ever shown, and it is plain words.

## 3. Endpoints (SS)

Every response is JSON. Times are ISO 8601 UTC (`2026-11-28T04:30:00Z`); the CRM formats them dd/mm/yyyy, h:mm am/pm.

### 3.1 `POST /api/v1/dashboards/builder/turn`

Request:
```json
{
  "actor_ref": "u-owner-1",
  "dashboard_id": "d_01J0000000000000000000000",
  "draft": {"version": 1, "title": "New dashboard", "period": "this_year", "tiles": []},
  "message": "monthly invoiced sales this year and top 10 customers",
  "images": [{"name": "mockup.png", "media_type": "image/png", "data_base64": "<base64>"}],
  "turn_id": "9b1c7e2a-0000-4000-8000-0000000000a1",
  "catalogue": {"version": 2, "index": [ "... section 4 ..." ], "entities": [ "... section 4 ..." ], "draws": ["number", "line", "bar", "table"]},
  "refusals": [{"tile_id": "t2", "code": "no_access", "reason": "Billing documents are outside this user's access."}],
  "history": [{"role": "user", "text": "..."}, {"role": "assistant", "text": "..."}]
}
```
- `images`: 0-5 per message (owner: "5 screenshot ... dont limit"); `media_type` `image/png | image/jpeg |
  image/webp`; each at most 5 MB decoded, all together at most 15 MB. Screenshots or mockups the user wants the
  dashboard to look like or read numbers from; the model reads them, SS never stores them (logged as a count only).
  Over the caps = 422 `images_invalid` with a plain reason. The CRM sends them through the existing assistant attach
  button of the composer.
- `turn_id`: one id per user message, the same on every lookup round of that message (below).
- `dashboard_id` is null for an unsaved draft. `history` is at most the last 10 turns, each text at most 2000 chars;
  `message` at most 2000 chars. `refusals` carries the last dry run's refused charts (codes `no_access`,
  `restricted`, `module_disabled`, `unknown_entity`, `unknown_field`, `invalid`, `timeout`, `no_match`) so the model
  corrects them. `no_match` carries `"candidates": ["<name>", ...]` (0-5 real names the CRM resolver found for a
  name the user typed); with 2+ candidates the model asks one question offering them, with 0 it replies "Couldn't find <name>".

Response 200:
```json
{
  "draft": {"version": 1, "title": "Sales overview", "period": "this_year", "tiles": ["..."]},
  "operations": [{"op": "add_tile", "tile": {"...": "..."}}, {"op": "add_tile", "tile": {"...": "..."}}],
  "changed_tile_ids": ["t1", "t2"],
  "reply": "Added two charts: invoiced sales by month and the top 10 customers.",
  "question": null,
  "usage": {"tokens_in": 2140, "tokens_out": 310, "model": "<provider model id>"}
}
```
- Catalogue lookup (no full dump per turn): the CRM sends `catalogue.index` (every entity the viewer may read: key,
  label, module, one line) and in `catalogue.entities` the full entry only for the entities the current draft uses
  and those SS asked for. When the model needs another entity's fields, SS answers 200 with
  `{"need_entities": ["sales_order"], "draft": <unchanged>, "changed_tile_ids": [], "reply": null, "question": null,
  "usage": {...}}`; the CRM repeats the SAME request (same `turn_id`, message, images) with those entries added. At
  most 2 lookup rounds per `turn_id`; a third `need_entities` is answered by the CRM with 502 `ai_failed`. An entity
  in `need_entities` that is not in `index` is dropped by the CRM (the viewer cannot read it). Each round's tokens
  are logged under the same `turn_id`.
- `question` is null or ONE clarifying question: `{"text": "Invoiced or delivered sales?", "options": ["Invoiced sales", "Delivered orders"]}`
  (2-5 options, each at most 60 chars, real names only). When `question` is set, `draft` is unchanged and
  `changed_tile_ids` is empty (AC-4: nothing is guessed).
- `changed_tile_ids` lists tiles added or whose `source` or `show` changed; a title-only or move change is not a
  data change and is not re-run. A removed tile is not listed.
- SS logs the turn (tenant, product, actor_ref, tokens in/out, model, feature `dashboard_builder`) BEFORE answering (AC-16).
- Errors: 401 `invalid_api_key`, 403 `service_not_enabled` / `tenant_mismatch` / `product_mismatch`, 404 `not_found`
  (dashboard_id given and not the actor's own), 403 `not_owner` (dashboard shared with the actor, not owned),
  422 `spec_invalid` (the incoming draft or catalogue is malformed), 422 `images_invalid`, 409 `ai_not_configured` (no LLM configured for
  the tenant), 502 `ai_failed` (the LLM call failed or produced a draft that failed validation twice; nothing saved).

### 3.2 `GET /api/v1/dashboards?actor_ref=<ref>&scope=all|mine|shared&q=<text>&sort=name|updated_at|owner_ref&dir=asc|desc&page=1&limit=25`

Response 200:
```json
{
  "items": [
    {"id": "d_01J0000000000000000000001", "name": "Sales overview", "owner_ref": "u-owner-1", "mine": true,
     "shared": true, "shared_count": 1, "updated_at": "2026-11-28T04:30:00Z", "version": 3}
  ],
  "total": 1, "page": 1, "limit": 25
}
```
- `scope=all` (default) = mine plus shared with me. `mine` is true when `owner_ref == actor_ref`. `shared` is true
  when `shared_with` is not empty. `limit` max 100. `q` matches the name, case-insensitive substring. Sort is on the
  server. The CRM resolves `owner_ref` to a person's name; sort by owner is by `owner_ref` in slice 1 and the CRM
  sorts the page it shows only when the user asks for Owner sort (noted in the CRM UAC).
- Never lists a dashboard the actor neither owns nor is shared on.

### 3.3 `GET /api/v1/dashboards/{id}?actor_ref=<ref>`

Response 200:
```json
{
  "id": "d_01J0000000000000000000001", "name": "Sales overview", "owner_ref": "u-owner-1", "mine": true,
  "shared_with": [{"user_ref": "u-viewer-1"}], "spec": {"version": 1, "...": "..."},
  "version": 3, "created_at": "2026-11-27T02:00:00Z", "updated_at": "2026-11-28T04:30:00Z"
}
```
- `shared_with` is returned to the owner only; a recipient gets `"shared_with": []` and `"mine": false`.
- SS re-validates the stored spec on get; a stored spec that no longer validates is returned with
  `"spec_problems": [{"path": "...", "reason": "..."}]` so the CRM shows the plain reason (AC-7 on load).
- 404 `not_found` when the actor neither owns nor is shared on it.

### 3.4 `POST /api/v1/dashboards/save`

Request:
```json
{"actor_ref": "u-owner-1", "dashboard_id": null, "name": "Sales overview", "spec": {"version": 1, "...": "..."},
 "base_version": null, "idempotency_key": "9b1c7e2a-0000-4000-8000-000000000001"}
```
- `dashboard_id` null = create (owner = actor). Otherwise a new version of that dashboard; only the owner (else 403
  `not_owner`). `base_version` must equal the current version on update (else 409 `version_conflict` with
  `current_version`). `name` 1-80 chars after trim; a rename is a save with a new name.
- Idempotency: the same `idempotency_key` from the same key + actor within 24 h returns the first response and
  writes nothing again.
- Response 200: the same body as get (3.3).
- Writes one version row: `action = "created" | "saved" | "renamed"` (renamed when only the name changed).
- 422 `spec_invalid` per section 2.

### 3.5 `POST /api/v1/dashboards/{id}/share`

Request: `{"actor_ref": "u-owner-1", "shared_with": [{"user_ref": "u-viewer-1"}, {"user_ref": "u-viewer-2"}]}`
- Replaces the whole list (max 50; the owner's own ref is dropped). Owner only (403 `not_owner`).
- Response 200: the get body. Writes one version row `action = "shared"` with old -> new user refs.

### 3.6 `POST /api/v1/dashboards/{id}/delete`

Request: `{"actor_ref": "u-owner-1"}`. Owner only. Hard delete of the dashboard and its version rows.
Response 200 `{"deleted": true}`. The CRM runs its deferred-delete countdown first and calls this only when the window
lapses (server-deferred pending action, CRM side).

### 3.7 `GET /api/v1/dashboards/{id}/versions?actor_ref=<ref>&page=1&limit=50`

Response 200:
```json
{"items": [
  {"version": 3, "action": "shared", "actor_ref": "u-owner-1", "at": "2026-11-28T04:30:00Z",
   "changes": [{"field": "shared_with", "old": [], "new": ["u-viewer-1"]}]},
  {"version": 2, "action": "renamed", "actor_ref": "u-owner-1", "at": "2026-11-28T04:10:00Z",
   "changes": [{"field": "name", "old": "New dashboard", "new": "Sales overview"}]},
  {"version": 1, "action": "created", "actor_ref": "u-owner-1", "at": "2026-11-27T02:00:00Z", "changes": []}
], "total": 3, "page": 1, "limit": 50}
```
- `action` in `created | saved | renamed | shared`. A `saved` row's `changes` lists `{"field": "charts", "old": <n>,
  "new": <n>}` (chart counts) and the name change when there was one. Owner and recipients may read it.

### 3.8 Errors (every endpoint)

Body: `{"error": "<code>", "message": "<plain sentence>"}` (+ `problems` for `spec_invalid`, `current_version` for
`version_conflict`).

| HTTP | code | when |
| --- | --- | --- |
| 401 | `invalid_api_key` | no, unknown or revoked key |
| 403 | `service_not_enabled` | the key's product has dashboards off |
| 403 | `tenant_mismatch` / `product_mismatch` | a body/query value disagrees with the key |
| 403 | `not_owner` | save / share / delete / builder turn on a dashboard the actor does not own |
| 404 | `not_found` | no such dashboard for this tenant + product + actor |
| 409 | `version_conflict` | `base_version` is stale |
| 409 | `ai_not_configured` | builder turn with no LLM configured |
| 422 | `spec_invalid` | schema or rule failure, with `problems` |
| 502 | `ai_failed` | the LLM call failed or its draft failed validation twice |

## 4. The catalogue (CRM -> SS on every builder turn: index always, full entries on demand)

Built by the CRM from `assistant_registry` (never hand-copied), already filtered to what the viewer may read: the
entity's view slug or its "only mine" slug with an own rule, module switch on, field slugs held. A restricted field
is left OUT, not flagged.

```json
{
  "version": 2,
  "draws": ["number", "line", "bar", "table"],
  "index": [
    {"entity": "billing_document", "label": "Billing documents (invoices, cash sales, debit and credit notes)", "module": "finance"},
    {"entity": "retail_quotation", "label": "Quotations", "module": "sales"}
  ],
  "entities": [
    {"entity": "billing_document", "label": "Billing documents (invoices, cash sales, debit and credit notes)",
     "only_own_rows": false, "totals_allowed": true, "period_field": "doc_date",
     "show": ["number", "line", "bar", "table"],
     "fields": [
       {"field": "doc_date", "label": "Document date", "type": "date", "note": "The date sales are counted by; ..."},
       {"field": "customer_name", "label": "Customer", "type": "text"},
       {"field": "sales_amount", "label": "Sales (RM)", "type": "number", "note": "THE sales figure: ..."}
     ],
     "relations": [{"name": "customer", "entity": "customer", "fields": [{"field": "name", "label": "Name", "type": "text"}]}],
     "default_note": "Cancelled documents excluded."}
  ],
  "buckets": ["day", "week", "month", "quarter", "year"],
  "aggregates": ["count", "count_distinct", "sum", "avg", "min", "max"],
  "limits": {"tiles": 12, "rows": 50, "groups": 200}
}
```
- `draws` = the `show` values this product renders today; `index` = every entity the viewer may read (always sent,
  small); `entities` = full entries for the draft's entities plus those SS asked for (section 3.1 lookup).
- A field of `"type": "location"` (a place the map can draw) is marked so; none exist in slice 1.
- `period_field` is the date field the dashboard period filters on (the CRM keeps one per entity), or null.
- `totals_allowed` false (no `aggregate_permission`) = `show` is `["table"]` only.
- Size: `index` at most 20 kB, each full entry at most 20 kB; the CRM drops `note`s first, then lookup-only relations, to fit.

## 5. Operations the model may emit (SS internal, echoed in `operations`)

| op | body | effect |
| --- | --- | --- |
| `add_tile` | `{"tile": <tile>}` | append; SS assigns the next free `id` (the model's id is ignored) |
| `change_tile` | `{"tile_id": "t1", "tile": <tile without id>}` | replace that tile in place, same position and id |
| `remove_tile` | `{"tile_id": "t2"}` | remove |
| `move_tile` | `{"tile_id": "t2", "to": 0}` | move to index |
| `set_title` | `{"title": "..."}` | dashboard title |
| `set_period` | `{"period": <period>}` | dashboard period |
| `set_layout` | `{"tile_id": "t1", "size": {...}, "position": {...}}` | size / free position of a chart |
| `ask` | `{"text": "...", "options": ["...", "..."]}` | becomes `question`; no other op in the same turn |

SS validates the resulting draft against section 2 AND the catalogue it was given. A tile naming an entity, field
or `show` not in the catalogue is refused; SS retries the model once with the problems, then answers `ai_failed`.

## 6. Sharing and ownership

- `shared_with` = list of `{user_ref}` of the same tenant + product. Only the owner saves, renames, shares, deletes
  or runs a builder turn on a saved dashboard. A recipient may get, list and read versions.
- `list` returns mine and shared with me, flagged by `mine`.
- Each save and share writes a version row (who, when, action, old -> new) for the CRM History tab.
- A spec holds no data and no author permissions. Each chart is read as the viewer at view time in the CRM.

## 7. CRM routes (browser -> CRM, for reference; SS does not implement these)

All under `/api/v1/dashboards`, staff bearer token, `dashboards.view` unless marked `build`:
`GET /` list (proxy 3.2), `GET /{id}` (proxy 3.3), `POST /` create/save (build, proxy 3.4), `POST /{id}/share`
(build, proxy 3.5), `DELETE /{id}` (build, deferred, proxy 3.6), `GET /{id}/history` (proxy 3.7, refs resolved to
names), `POST /{id}/build` and `POST /draft/build` (build, proxy 3.1 + dry run of `changed_tile_ids` as the user),
`POST /tiles/run` (run charts as the caller, no SS call, no LLM), `GET /status` (is the integration on).
With the integration off or missing, every route except `GET /status` answers 409 `dashboards_off` and the sidebar
entry shows a plain notice.

## 8. Stub fixtures (CRM tests use them; SS ships the same as contract tests)

Keys of the stub (fake): `ss-test-key-sorento` = tenant `t-default`, product `sorento_crm`; `ss-test-key-ecohub` =
tenant `t-default`, product `ecohub`; `ss-test-key-off` = product with dashboards off. Users: `u-owner-1` (owner),
`u-viewer-1` (recipient), `u-other-1` (neither).

| # | call | input | output |
| --- | --- | --- | --- |
| F1 | builder/turn | empty draft, "monthly invoiced sales this year and top 10 customers" | 200, two tiles below, `changed_tile_ids` `["t1","t2"]` |
| F2 | builder/turn | F1 draft, "make the first one by quarter" | 200, t1 bucket `quarter`, t2 unchanged, `changed_tile_ids` `["t1"]` |
| F3 | builder/turn | empty draft, "sales by month" | 200, `question` {"text": "Invoiced or delivered sales?", "options": ["Invoiced sales", "Delivered orders"]}, draft unchanged |
| F4 | builder/turn | catalogue without `billing_document` | 502 `ai_failed` |
| F5 | any | no key / `bad-key` | 401 `invalid_api_key` |
| F6 | any | `ss-test-key-off` | 403 `service_not_enabled` |
| F7 | any | body `product: "ecohub"` with the sorento key | 403 `product_mismatch` |
| F8 | get | `u-other-1` on the owner's dashboard | 404 `not_found` |
| F9 | save / share / delete | `u-viewer-1` on the owner's dashboard | 403 `not_owner` |
| F10 | save | spec with `"entity": "x; drop table"` or a URL or `<b>` or an extra key | 422 `spec_invalid` |
| F11 | save | stale `base_version` | 409 `version_conflict` |
| F12 | builder/turn | tenant with no LLM | 409 `ai_not_configured` |
| F13 | save twice | same `idempotency_key` | same response, one version row |
| F14 | builder/turn | message "add sales orders by month", `catalogue.entities` without `sales_order` (in `index`) | 200 `need_entities: ["sales_order"]`, draft unchanged; repeated with it: 200, one tile added |
| F15 | builder/turn | 6 images, or one over 5 MB, or `image/gif` | 422 `images_invalid` |
| F16 | builder/turn | message "make it look like this" + 1 image | 200, the stub ignores the image bytes and returns F1's tiles (image count logged) |
| F17 | save | a tile with `show: "pie"` / `series` / `calc` | 200 (valid schema; the CRM draws it as "This chart type is not available yet.") |

F1 tiles:
```json
[
  {"id": "t1", "title": "Invoiced sales by month", "show": "line",
   "source": {"kind": "query", "spec": {"entity": "billing_document",
     "group_by": [{"field": "doc_date", "bucket": "month"}],
     "aggregates": [{"fn": "sum", "field": "sales_amount"}]}}},
  {"id": "t2", "title": "Top 10 customers", "show": "table",
   "source": {"kind": "query", "spec": {"entity": "billing_document",
     "group_by": ["customer_name"], "aggregates": [{"fn": "sum", "field": "sales_amount"}],
     "sort": [{"field": "sum_sales_amount", "dir": "desc"}], "limit": 10}}}
]
```
The dashboard period (`this_year`) applies to every query tile as a filter on that entity's `period_field` (given in
the catalogue; null = the period does not apply to that chart); a tile's own filter on that field wins over the
dashboard period. The CRM applies the period at run time; the spec never copies the dates into each tile.
