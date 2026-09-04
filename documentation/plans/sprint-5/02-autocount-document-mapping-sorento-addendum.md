# 02 - Sorento addendum: document ingest reaches xlsx-import parity (contract v2)

> **Audience:** the Sorento CRM session (repo `sorento-crm`, `origin/main` b9150f49+).
> **Requested by:** shared-service plan `sprint-5/02-autocount-document-mapping.md` (ESB side).
> **Baseline contract:** `documentation/plans/autocount/PLAN-autocount-cross-repo-contract.md`
> §3 (A3 document ingest) on Sorento origin/main; `app/schemas/canonical_documents.py`;
> `app/services/document_ingest_service.py`.
> **Goal:** `POST /api/v1/external/ingest/{sales_orders|purchase_orders|shipping_orders}` from
> the ESB (AutoCount DB source of truth) produces the SAME Sorento state as
> `POST /api/v1/scm/outstanding/{sales-orders|purchase-orders}/apply` does from the xlsx book,
> then keeps it current (create / update / delete, header and line).
> **Versioning:** the ESB gates every new field behind `sorento_contract_version = 2` on its
> consumer connection, so v1 Sorento never receives an unknown key (`extra="forbid"` stays).
> Please expose the version you implement (e.g. `GET /api/v1/external/contract` →
> `{"version": 2}`) or tell us the release tag so we can flip the gate.

## 1. Accept code+name fallbacks and back-create masters (parity with the upload)

The customer's SQL login may expose only the document tables. The ESB therefore ALWAYS sends the
codes/names the documents carry; refs are sent too whenever the master task exists.

Add to `CanonicalSalesOrder`: `customer_code?`, `customer_name?`, `agent_code?`.
Add to `CanonicalPurchaseOrder` (+ `CanonicalShippingOrder`): `supplier_code?`,
`supplier_name?`, `agent_code?`.
Add to every line: `product_code?`, `product_name?`, `warehouse_code?`.

Resolution order per FK, mirroring `outstanding_import_service`:
1. `*_ref` via `integration_references` (existing behaviour).
2. else `*_code` against the master's code column (UPPER/TRIM, company-scoped).
3. else (supplier only) `supplier_name` after stripping the `(RMB)`-style suffix
   (`_CURRENCY_SUFFIX_RE`), as today.
4. else back-create: supplier (`back_create_supplier`, slug code), sales agent
   (`resolve_or_create`), customer (NEW - by code+name; today the upload keeps the raw code and
   links nothing; please back-create instead so `customer_id` resolves), and **register the new
   row in `integration_references` under the ref the ESB will send next time**
   (`{DatabaseName}:{AutoKey}` when a ref was sent, else `{DatabaseName}:{code}`), so the next
   push resolves by ref.
   Product / warehouse: NOT back-created (a typo must never become a SKU) - a miss stays
   `retryable` with the line error naming the code.
Also write `sales_orders.debtor_code` = `customer_code` always (the upload does).

## 2. Demand classification on ingest

Run the upload's 4-step `_classify_demand` at ingest for sales orders: stored `order_type` →
payload `order_type?` (new optional header field, fill-only) → agent `demand_class` → customer
`market_segment_code`. Unclassifiable documents must NOT be refused (the ESB cannot fix them);
land them and report `warnings: ["unclassified_demand"]` on the record. Keep `demand_class`
itself non-writable from the payload.

## 3. Shipping orders as an ingest entity

New `shipping_orders` entity → `spo_allocations` (never `purchase_orders`). Proposed schema,
mirroring what `_write_spo_lines` writes today:

```
CanonicalShippingOrder: source_ref* (DocKey), spo_number* (DocNo), supplier_ref?, supplier_code?,
  supplier_name?, agent_code?, issue_date?, expected_date?, currency?, status*
  (open|partial|fulfilled|closed|cancelled), lines[]
CanonicalShippingOrderLine: source_ref* (DtlKey), product_ref*, product_code?, product_name?,
  warehouse_ref?, warehouse_code?, qty_ordered* → allocated_quantity, qty_received →
  quantity_received, unit_cost?, uom?, expected_date?, from_so_numbers?: list[str]
```
Line identity = `source_ref` (DtlKey) via `integration_references` (entity `spo_allocations`),
replacing the upload's `(spo, item, location, occurrence)` → `spo_line_number` plan; keep
writing `spo_line_number` for display. `receipt_status`/`line_status` derived as today
(`pending|fully_received`, `open|closed`). `source_system='autocount'`.
Family is the ESB's job (each task filters by your `doc_family` rule, `SPO-` prefix); Sorento
should still refuse an `SPO-` number arriving under `purchase_orders` (per-record `failed`) as a
guard.

## 4. SO↔PO dedication from `FromSODocList`

`CanonicalPurchaseOrderLine.from_so_numbers?: list[str]` (+ on SPO lines). On write, call
`order_link_service.claim_book_pairing(so_number, po_number, item_code, source="autocount")` per
value, then `resolve()` - the same as `_claim_stated_so_links`. The ESB splits AutoCount's
comma-separated `FromSODocList` into the list (the upload ignores multi-value cells; we send them
all).

## 5. Document deletions

`POST /api/v1/external/ingest/{sales_orders|purchase_orders|shipping_orders}/deletions` with
`{"companyCode", "source_refs": [header refs]}`: hard-delete the header + lines when nothing
references them; otherwise set header `cancelled` and every line `cancelled` in place (the
masters' hard-delete-with-fallback rule). Line-level deletes already ride re-push (`_sync_lines`).

## 6. Status vocabulary and committed demand

Confirm (or widen) `scm.committed_v` / the SO binding's `live_statuses=("open",)`: an SO ingested
as `partial` → `partially_delivered` currently drops out of committed demand and out of
`_existing_lines`, so a later xlsx upload would re-add its lines. The ESB will NOT emit `partial`
by default until you confirm `partially_delivered` counts as committed.

## 7. Post-write hooks

`document_ingest_service` emits no lifecycle events. For parity, after a successful ingest
batch run the same hooks `outstanding_import_service.apply` runs:
- SO: `plan_exception_service.snapshot/generate_batch` for touched products;
  `planning_change_service.build_batch` when the diff is material.
- PO: `_supersede_crm_raised_pos` (close CRM-raised `scm_recommendation` POs the book supersedes),
  `ProjectOrderInquiryService.relink_to_matching_lines(trigger="autocount_ingest")`, the
  `FromSODocList` claims (§4).
- SPO: close-by-absence of upload/ingest-owned SPO lines within the pushed documents' scope.

## 8. Currency default

PO/SPO header + line `currency` absent → `CNY` (`DEFAULT_PO_CURRENCY`), as the upload does. The
ESB also defaults it in its mapping, so this is belt-and-braces.

## 9. Cutover note (for your awareness, ESB owns the playbook - BL-SS-050)

The first AutoCount push of a document previously loaded by xlsx deletes (or cancels in place)
its ref-less lines via `_sync_lines`. Header adoption by `so_number`/`po_number` is automatic.
We will sequence masters → SO/PO/SPO with reconcile disabled until the first full load.

## 10. Tests we will rely on

Per-entity ingest tests for the new fields, back-create paths, `shipping_orders` round-trip,
`/deletions` on documents, `from_so_numbers` claims, and a v1-compat test proving a v1 payload
(no new keys) still ingests identically.
