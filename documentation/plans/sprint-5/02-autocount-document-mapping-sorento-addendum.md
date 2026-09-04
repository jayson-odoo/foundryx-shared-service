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
Add to every line: `product_code?`, `product_name?`, `warehouse_code?`, `line_number?` (int,
AutoCount `Seq`; see §9).

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

**Sorento correction (2026-09-05):** there is no shipping-order header table; a shipping order is
the set of `spo_allocations` rows keyed `(company_id, spo_number, spo_line_number)`. So
`shipping_orders` ingest is a LINE-SET entity: Sorento adds `spo_allocations.source_ref` (DtlKey)
+ `source_doc_ref` (DocKey), looks the header up by `source_doc_ref`, adopts xlsx-era rows by
`spo_number`, closes absent lines IN PLACE (GRN lines + claims point at them), returns header
`entity_id: null`, and does not use `integration_references` for SPO. Wire shape as proposed:

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

**Sorento correction:** `/deletions` ALREADY exists for `sales_orders` and `purchase_orders`
(`deletion_service.ENTITY_MODELS` includes `DOCUMENT_SPECS`, two-stage line probe, cancel-in-place
when referenced; `tests/test_ingest_deletions.py`). Only `shipping_orders` needs adding.

`POST /api/v1/external/ingest/{sales_orders|purchase_orders|shipping_orders}/deletions` with
`{"companyCode", "source_refs": [header refs]}`: hard-delete the header + lines when nothing
references them; otherwise set header `cancelled` and every line `cancelled` in place (the
masters' hard-delete-with-fallback rule). Line-level deletes already ride re-push (`_sync_lines`).

## 6. Status vocabulary and committed demand

**Sorento answer:** `scm.committed_v` is `so.status='open' AND sol.line_status='open'`. Their
plan maps canonical `partial` -> stored `open` for SALES orders (per-line `qty_delivered` carries
the partial fact; read-back reports `open`). The ESB may emit `partial` once v2 ships; until then
the default formula stays `cancelled|closed|open`.

Original ask kept for the record:

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

## 9. Cutover: ADOPT xlsx-loaded lines in place (revised 2026-09-05, captain's ask)

Today `_sync_lines` deletes (or cancels in place when referenced) every ref-less line of a header
adopted by number, then inserts the pushed lines fresh. The captain's requirement: **ingested
lines must be identical to the xlsx-loaded lines** (same rows, same ids) except where AutoCount
changed them after the upload. So, for a header adopted by `so_number`/`po_number`/`spo_number`
whose lines carry no `source_ref`, please ADOPT before you delete:

1. Match each incoming line to one remaining ref-less line by business key
   `(product_id, warehouse_id-or-NULL, outstanding)` where `outstanding = qty_ordered -
   qty_delivered|qty_received` on BOTH sides (Sorento correction: the upload stored
   `qty_ordered = Remaining Qty` on insert, so raw `qty_ordered` is not comparable; the ESB side
   is `Qty - TransferedQty`); if several remain, take the one whose position equals
   `line_number` (else the first in `(created_at, id)` order).
2. Else match by `(product_id, warehouse_id-or-NULL)` when exactly one remains.
3. Else match by `line_number` position among the remaining ref-less lines when the counts agree.
4. A matched row keeps its id: stamp `source_ref` (DtlKey) + `source_system='autocount'` on
   the line COLUMN (lines are never registered in `integration_references` - A3 rule), then
   update its values (qty/price/dates) from the payload - allocations, claims, GRN links stay
   attached.
5. Only the ref-less lines still unmatched after 1-3 are deleted (or cancelled in place when
   referenced) - the existing rule, now applied to the true remainder.
6. Report per record `lines: {adopted, created, updated, deleted, cancelled}` (dry run too) so
   the cutover playbook BL-SS-050 can be rehearsed.
`line_number` is position-only on the Sorento side (not persisted; `spo_line_number` stays
Sorento's own sequence). Sorento: plan D11, UAC group V7, issue #668, slice S1b.

The ESB sends `line_number` (AutoCount `Seq`) on every line at contract v2 and always sends
`product_ref`/`warehouse_ref` (+ code fallbacks) so step 1 resolves the same masters the upload
linked. Header adoption by number stays automatic. Go-live sequence: masters → SO/PO/SPO with
reconcile disabled until the first full load.

## 10. Tests we will rely on

Per-entity ingest tests for the new fields, back-create paths, `shipping_orders` round-trip,
`/deletions` on documents, `from_so_numbers` claims, and a v1-compat test proving a v1 payload
(no new keys) still ingests identically.

## 11. Agreed answers to Sorento's questions (2026-09-05)

- ESB always sends `*_ref` next to the code/name fallbacks; Sorento registers a back-created row
  under the ref it was given (never mints `{DatabaseName}:{code}` itself).
- Customer back-create only when BOTH `customer_code` and `customer_name` are sent (customers'
  unique index is the pair); code-only -> `debtor_code` written, no link, warning.
- Warnings vocabulary (per record, omitted when empty): `customer_created`,
  `customer_unresolved`, `supplier_created`, `agent_created`, `unclassified_demand`,
  `warehouse_unresolved`. Product stays `retryable`, never a warning.
- `agent_code` on PO/SPO accepted and ignored; `product_name` accepted and never used.
- `from_so_numbers`: claim uses the resolved product's `product_code`; an SO Sorento does not
  hold yet still gets a claim, resolved when it arrives.
- v2 hooks: plan-exception batch, CRM-raised PO supersede, order-inquiry relink run on ingest;
  `planning_change` batches deferred (Sorento-side parity gap); SPO close-by-absence is the ESB's
  via reconcile -> `/ingest/shipping_orders/deletions`.
- `GET /api/v1/external/contract` -> `{"version": 2, "entities": [...]}`, permission
  `integration.contract.read` granted with `scm.sales_orders.edit`. The ESB reads `version` at
  sink construction and gates v2 fields on `>= 2`.
- Sorento UAC/plan: `documentation/plans/autocount/autocount-document-ingest-v2-acceptance-criteria.md`
  (AC-V0..V6) + `PLAN-autocount-document-ingest-v2.md` (D1-D9, S0-S6) on sorento-crm main.

## 12. Change log

- 2026-09-05: §9 rewritten from a note into an ask (adopt ref-less lines in place; `line_number`
  added to §1). Sorento D1-D10 as reported (ladder, customer code+name, SPO line-set, unclassified
  warning, SPO-under-PO failed, `partial`->`open`, hooks, contract endpoint, warnings vocabulary,
  `warehouse_unresolved`) accepted without change.
- 2026-09-05 (Sorento S1 as built): a SENT-but-unresolved `customer_ref`/`supplier_ref`/
  `sales_agent_ref` no longer makes the record retryable when a code/name rides alongside; the
  ladder falls through to code -> name -> back-create and registers the new row under that ref.
  Products stay retryable; warehouses land NULL + `warehouse_unresolved`. Cross-company conflicts
  are filed under the field name (`errors.customer_ref`, `errors.supplier_ref`), not
  `errors.source_ref`. Consequence for the ESB: masters-first sequencing is a hard prerequisite
  only for products + warehouses; the `documentPrerequisites` card and the cutover playbook
  (BL-SS-050) should say so, and the sink's error mapper must read the field-named keys.
- 2026-09-05 (Sorento S1b green): `line_number` accepted; adopt-in-place live (outstanding key ->
  single candidate -> position); verdict carries `lines: {adopted, created, updated, deleted,
  cancelled}` (dry run too). A push is authoritative for the WHOLE document: unnamed lines are
  swept. ESB rule (AC-02-04): always send the full line set per header, never a delta.
- 2026-09-05 (Sorento S3 green): `/ingest/shipping_orders`, `/read/shipping_orders`,
  `/ingest/shipping_orders/deletions` live (slugs `scm.shipping_orders.edit/view/delete`). Rows land
  in `spo_allocations` (`source_ref`/`source_doc_ref`), header `entity_id` null, leftover lines on
  a re-push are ALWAYS closed in place (hard delete only via the deletions call), read-back keyed by
  DocKey; `SPO-` under `purchase_orders` -> `failed` with `errors.po_number`. S4 (`from_so_numbers`)
  and S5 (hooks, `partial`->`open`) pending; v1 payloads until "S5 green".
- 2026-09-05 (Sorento S4 green): `from_so_numbers: list[str]` on PO + SPO lines -> one
  `order_link_claim` per (so_number, po_number, product_code), source `autocount`; blanks dropped;
  a non-list fails the record with `lines.N.from_so_numbers`. ESB: split `FromSODocList` on commas,
  strip, drop blanks, always a list (never a string).
- 2026-09-05 (Sorento "S5 green"): every build slice S0-S5 live on the local lane :8042; the local
  consumer connection may run at `sorento_contract_version = 2`. D6a confirmed: canonical
  `partial` on SALES orders is stored and read back as `open` (PO `partial` unchanged). Sorento S6
  (review + full suite) follows; any wire change will be announced before the proof completes.
  Production flip = BL-SS-049, on their release tag.
