# Plan 37 - AutoCount ItemClass master push (lane ITEM-CLASS-SS, size S)

Pairs with sorento-crm PR #1988 (ITEM-CLASS-MASTER, contract 2.11, its plan D8). Merge and deploy order:
sorento #1972, then #1988, then this PR. Our partner PR #135 (ITEM-CLASS, `item_class_code` on the product
feed) is independent; whichever merges second rebases (both touch `presets.py` / FE preset copies).

## Wire (the CRM contract, #1988 plan section 1 + `app/schemas/canonical_masters.py:95-104`)

`POST /external/ingest/item_classes`, gated on `GET /external/contract` >= 2.11 with `item_classes` in
`entities`. A class gone from the AutoCount list goes to `/ingest/item_classes/deletions` (the CRM always
deactivates, never hard deletes; #1988 D5).

```json
{"companyCode": "SRT", "records": [
  {"source_ref": "SRT:SERENE", "code": "SERENE", "name": "SORENTO SERENE SERIES",
   "description": "", "is_active": true}
]}
```

## Source (crew GET, 30 Oct, `crew/state/inbox/item-class-master/hapi-itemclass-shape.md`)

`GET /api/db{1,2}/itemclass`: plain array, no paging, no id, no timestamps, no active flag. Rows
`{ItemClass, Description, Desc2, ShortCode}`; db1 DIY + SERENE, db2 DIY. Same shape as `/ItemGroup`
(`presets.py:1525`). No watermark, so every run reads the full list (as brand / item group do).

## Decisions

- **D1 Entity `item_class`**, an HTTP-only master wired exactly like `brand` (`canonical/masters.py:64`).
  `CanonicalItemClass` caps = the CRM's: code 50, name 150 (fails at mapping, never a CRM 422).
- **D2 Preset** `ITEM_CLASS_HTTP_PRESET`, path `/ItemClass`, key `ItemClass`, no watermark. The two formula
  rows read `ItemClass` (always filled) because a formula row with a blank own source short-circuits to None
  (`mapping.py:576-583`):
  - `code` = `ItemClass` (required);
  - `name` = `ItemClass` row with formula `if(trim(default(Description, "")) != "", trim(Description), value)`:
    the Description, falling back to the code when blank (the brand rule, #1988 D8);
  - `description` = `Desc2` (plain row, the ItemGroup shape). Every transform reads a blank as absent
    (`mapping.py` `t_string`), so `CanonicalItemClass.sink_payload` writes `""` when the description is None:
    it clears the CRM placeholder "Auto-created by product import" (#1988 D3). The description is therefore
    always sent; an operator who disables the Desc2 row also clears the CRM description, which matches
    AutoCount being master for it (#1988 D3);
  - `is_active` = `ItemClass` row with formula `true`: AutoCount has no flag, being on the list means active,
    and it reactivates a class an earlier sweep deactivated (#1988 D8).
- **D3 Contract gate** `CONTRACT_GATED_ENTITIES[item_class] = (2.11, "item_classes")`, and `item_class` joins
  `PUSH_REFUSES_LOGGING_FALLBACK`: on a 2.10 CRM a run refuses with `CONTRACT_GATE` and keeps the rows
  STAGED, instead of the logging fallback marking them PUSHED (a full list with changed-only staging would
  then never offer them again, `sinks_sorento.py:388-393`). The task view's generic `contractGate` and an
  Activate-tab warning banner (the branch banner generalised, `lib/autocount-etl.ts:315`) say so.
- **D4 Deletions**: `item_class` is NOT in `NO_DELETION_ENTITY_TYPES` (`canonical/masters.py:526`), so a class
  missing from the full list is staged as a delete and pushed to `/deletions`, like brand.
- **D5 Order "before brands/products"**: there is no dependency order in the SS. A scheduler tick enqueues its
  due tasks with a stable sort on `sweep_order_key` (`scheduler.py:117-123`, `:168`); `item_class` gets the
  lowest key so it is enqueued first in a tick where brand / product are also due. On-demand runs are per
  entity (`routers/companies.py:885`); there is no run-all. Correctness never depends on the order: the CRM
  adopts a product-created class by code (#1988 AC-3, AC-10).
- **D6 Task creation**: an operator adds the entity from "Add entity" like every other HTTP master (no auto
  seeding, `company_service.py:169`). FE: `AC_HTTP_ENTITY_TYPES` (`autocount-meta.ts:152`, parity-pinned by
  `test_autocount_entity_parity.py:124`), the FE `HTTP_PRESETS` copy, the mock fixtures.
- **D7 No backfill / migration / permission**: a brand-new entity has no existing tasks or rows; the push uses
  the existing sync permissions. Manifest version unchanged (no `update_tenant` step).

## Tests (red first)

`service_backend/tests/test_autocount_item_class_master.py`: preset rows + mapping of the recorded db1/db2
fixtures (name fallback, `""` description, `is_active` true, code cap 50 / name cap 150 field error), sink
payload keys, ingest path `item_classes`, contract gate (2.10 shut, 2.11 without `item_classes` shut,
2.11 with it open), refuse-not-log on a shut gate and the held-back classes landing after the upgrade,
vanished class staged as a delete, sweep order puts `item_class` before `brand` / `product`. Pins moved:
`test_autocount_entity_parity.py`, `test_autocount_contract_version_compare.py`,
`test_autocount_document_mapping.py`, FE `autocount-meta.test.ts`, `lib/autocount-etl.test.ts`,
`add-entity-control.test.tsx`, `company-detail-view.test.tsx` (`test_autocount_contract_2_1_masters.py` covers
`item_class` through `CANONICAL_MODELS` unchanged). No live hapi calls.

## Review follow-ups (not in this PR)

- `etl_service.py` "no SQL variant" guard only names `stock_balance`: a direct API save of `item_class` (or
  `branch`) on a DB company with a blank `sourceImpl` makes an unusable `sql_db` draft (the FE always sends
  `autocount_http`).
- `company_service.contract_gate` compares the version only, never the advertised `entities` (existing
  pattern; the CRM's 2.11 always lists `item_classes`).

## Docs

`documentation/engineering/autocount-mapping.md` HTTP entity list.
