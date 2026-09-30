# 17 - AutoCount Customer (open REST API) entity: identity key vs the CRM's AutoKey references

Lane `crew/customer-key-autokey` (worktree `foundryx-shared-service-customer-key-autokey`, base `origin/main`
cb4766e3). Status: **scout complete, blocked on an owner decision** (see "Decision needed").

## Symptom (owner, 2026-09-30)

Sorento > Customer (Open API, Draft) dry-run preview: 4245 extracted, 2264 would fail with
`source_ref - customer_code='300-1003' is already linked to another source` (`AED_SORENTO:300-1003`, ...).

## Root cause (both repos read at `origin/main`)

- The ss HTTP Customer preset keys the row on `AccNo`
  (`service_backend/modules/autocount/presets.py` `CUSTOMER_HTTP_PRESET`, `key_fields=("AccNo",)`), copied into
  the task's stored `source_config.keyFields` on first save (`presets.py` `preset_defaults_for`, `keyFields`
  entry) and minted as `{database}:{AccNo}` by `http_source/source.py` `HttpApiSource.source_ref` ->
  `mapping.flat_source_ref`.
- The SO / PO document presets mint `customer_ref` / `supplier_ref` from the Debtor / Creditor **`AutoKey`**
  (`presets.py` SO header query `c.AutoKey AS DebtorAutoKey`, PO `s.AutoKey AS CreditorAutoKey`), per the
  documented rule in `documentation/plans/sprint-4/22-autocount-db-etl-autocount-sql.md` ("`value` MUST equal
  the master task's key. Customers/suppliers already in Sorento are keyed on `AutoKey`").
- Sorento CRM (`sorento_crm_backend/app/services/master_ingest_service.py` at origin/main 950785de2):
  `_apply_scoped` resolves the incoming `source_ref` first (`_resolve_ref`, ~L1203); on a miss it adopts a
  customer by the `(code, name)` pair (`_adopt_customer`, L640) and, when that row already carries a
  DIFFERENT integration reference, raises `ReferenceConflict(... is already linked to another source)`
  (~L1277). Only `products` get the code-wins bypass (`is_unclaimed_or_same_source`,
  `integration_reference_service.py` ~L98) - added for exactly this reason: "the FoundryX AutoCount HTTP
  source exposes no numeric item key".
- So every debtor that already appears on an ingested SO carries `AED_SORENTO:<AutoKey>` in the CRM, and the
  Customer entity's `AED_SORENTO:<AccNo>` ref conflicts with it. 2264 of 4245 = the debtors with at least one
  synced SO.

## Vendor door probe (2026-09-30, read-only GET, identity columns only)

`GET https://hapi.sorento.cc.cd/api/db1/debtorbypage?page=1&pageSize=2` returns per row:
`AccNo, Address1..4, AreaCode, CompanyName, CreatedTimeStamp, CreatedUserID, CreditLimit, CurrencyCode,
DebtorType, DisplayTerm, IsActive, IsTaxRegistered, LastModified, LastModifiedUserID, MultiPrice, Phone1,
PostCode, SalesAgent, TaxEntityID`. **No `AutoKey`.** `GET /debtor` (bare array) has the same shape.
`/debtorautokey`, `/debtorbykey` -> 404. `GET /itembypage` likewise carries no `AutoKey`.

Consequence: the briefed fix (flip `CUSTOMER_HTTP_PRESET.key_fields` to `AutoKey`, migrate stored
`keyFields`) is **not possible** on the ss side - the wrapper never exposes the value the ref would need.

## Decision needed (owner)

(a) **CRM code-wins for customers** (recommended): in `master_ingest_service._apply_scoped`'s adopt branch,
    treat `customers` like `products` - when the `(code, name)`-adopted row is claimed by the SAME source
    system (`is_unclaimed_or_same_source`), update it, keep the STORED `AED_SORENTO:<AutoKey>` reference,
    append `WARN_REF_MISMATCH`, never `_link` the incoming `AccNo` ref. One sorento_crm PR + a test; no ss
    code change (this doc + the sprint-4/22 rule row get a note); no data migration; no double-create
    (adoption updates the SO-linked row). Rows claimed by a DIFFERENT source system still conflict.
(b) **Ask the wrapper owner to add `AutoKey` to `/debtorbypage`**, then do the briefed ss fix (key flip +
    stored-`keyFields` data migration + lock). Blocked on the vendor, unknown timeline; every debtor without
    an SO would then be re-linked on the CRM side from `AccNo` to `AutoKey` only if they were never pushed.
(c) **Flip the SO/PO presets to mint `customer_ref` from `DebtorCode` (AccNo)** and migrate the CRM's
    existing customer `integration_references` from `AutoKey` to `AccNo`. Breaks the documented rule,
    cross-repo data migration on prod, highest risk.
