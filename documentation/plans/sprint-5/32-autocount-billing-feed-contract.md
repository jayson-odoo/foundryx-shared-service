# 32 - Contract copy: billing documents (2.6) + ar_outstanding (2.10)

Copied 20 Oct 2026 from the CRM repo (`documentation/plans/autocount/PLAN-autocount-cross-repo-contract.md`
sections 12 and 14, and `documentation/plans/finance/REF-autocount-billing-schema.md`) so the review sits
next to the diff, as plan 16's contract does. **The CRM copy stays the contract of record**: if this copy and
it ever differ, the CRM wins and this file is the bug. Example values are masked (company code, customer,
agent and project names replaced with placeholders; this repo is public).

Owner rulings made in this lane (PR #127, 20 Oct): the DO-line hop joins `DODTL` (DODTL joins the read-only
grant in RUNBOOK section 0.1); no draft `DocStatus` letter is guessed (the task's `filterFormula` is set after
REF check 6.2).

## 12. billing_documents (contract 2.6)

| Call | Slug | Body |
| --- | --- | --- |
| `POST /api/v1/external/ingest/billing_documents` (`?dry_run=true` optional) | `finance.billing_documents.edit` | `{"companyCode": "ABC", "records": [...]}` |
| `POST /api/v1/external/ingest/billing_documents/deletions` (`?dry_run=true` optional) | `.edit` and `finance.billing_documents.delete` | `{"companyCode": "ABC", "source_refs": [...]}` |
| `POST /api/v1/external/read/billing_documents` | `finance.billing_documents.view` | `{"companyCode": "ABC", "source_refs": [...]}` |

`GET /api/v1/external/contract` answers `"version": "2.6"` (2.10 since section 14), lists `billing_documents`
in `entities`. Batch cap 1000 records (413 `BATCH_TOO_LARGE`). A body without `records` / `source_refs` is
422 `INVALID_BODY`. Company anchor unchanged.

**Record** (`CanonicalBillingDocument`, unknown keys refused):

```json
{
  "source_ref": "ABC_DB:IV:88213",
  "document_type": "invoice",
  "doc_no": "IV-2609/0142",
  "doc_date": "2026-09-26",
  "status": "posted",
  "source_modified_at": "2026-09-26T09:14:02",
  "customer_ref": "ABC_DB:300-X001", "customer_code": "300-X001", "customer_name": "...",
  "agent_code": "AGENT1",
  "currency_code": "MYR", "currency_rate": 1,
  "net_total": 1000.00, "tax_total": 100.00, "total": 1100.00, "local_net_total": 1000.00,
  "against_doc_no": null, "against_source_ref": null,
  "ref": "PROJECT X", "description": "...",
  "lines": [
    {
      "source_ref": "ABC_DB:IV:88213:1", "line_number": 1,
      "product_ref": "ABC_DB:ABC-1", "product_code": "ABC-1", "description": "...",
      "uom": "PCS", "quantity": 10, "unit_price": 100.00, "discount_amount": 0,
      "net_amount": 1000.00, "tax_code": "SV-10", "tax_rate": 10, "tax_amount": 100.00,
      "line_total": 1100.00,
      "from_doc_type": "DO", "from_doc_no": "DO-2609/0077", "from_line_ref": "ABC_DB:SO:1234:1"
    }
  ]
}
```

Required: `source_ref`, `document_type` (`invoice`, `cash_sale`, `credit_note`, `debit_note`), `doc_no`,
`doc_date`, `status` (`posted`, `cancelled`), `net_total`, `tax_total`, `total`, `local_net_total`; per line
`source_ref` and `quantity`. `currency_code` defaults to `MYR`, `currency_rate` to 1. Money and quantities
are JSON numbers. A record fails, field named, when: a key is unknown; `total` is not `net_total + tax_total`
within 0.01; a line on an `invoice` or `cash_sale` has a negative quantity; two lines share a `source_ref` or
there are more than 2000; the type or status is outside its list.

**Identity** `(company, document_type, source_ref)`; `source_ref` = `{database}:{IV|CS|CN|DN}:{DocKey}`;
lines keyed by their own `source_ref` (DtlKey) within the document. A ref already naming another type is
refused.

**Resolution.** Customer (`customer_ref`, then `customer_code`), agent (`agent_code`), product
(`product_ref`, then `product_code`) linked only inside the anchor company, never created; unresolved lands
null with a warning. A CN/DN links its document by `against_source_ref`, else `against_doc_no` when exactly
one IV/CS/DN carries that number. `from_line_ref` links to the anchor's sales-order line whose `source_ref`
it is; the three `from_*` values are kept as sent.

**Verdicts** `created`, `updated`, `failed`, `unchanged` (identical, or older by `source_modified_at`:
warning `stale_ignored`). `summary.unchanged` only when non-zero.

**Versions, cancels, deletes.** A push names the whole document: an omitted optional field is stored as null
and a line not sent is deleted. A push WITHOUT `source_modified_at` always applies and switches the guard
off: always send it. An offset timestamp is converted to UTC; a naive one is taken as UTC. `cancelled` is an
update. `/deletions` hard-deletes, or sets `cancelled` (`deactivated`) when a note still points at it;
unknown ref is `not_found`.

**Backfill.** Oldest first; IV and CS before CN and DN of the same day; batches up to 1000; start date is
shared-service configuration (1 Jan 2023).

## 14. ar_outstanding (contract 2.10) and the billing pull

| Call | Slug | Body |
| --- | --- | --- |
| `POST /api/v1/external/ingest/ar_outstanding` (`?dry_run=true` optional) | `finance.billing_documents.edit` | `{"companyCode": "ABC", "records": [...]}` |
| `POST /api/v1/external/read/ar_outstanding` | `finance.billing_documents.view` | `{"companyCode": "ABC", "source_refs": [...]}` |

No deletions door: a debtor with nothing open is pushed with `total_outstanding: 0` and `documents: []`.
`GET /api/v1/external/contract` answers `"version": "2.10"`.

```json
{
  "source_ref": "ABC_DB:debtor:1234",
  "customer_ref": "ABC_DB:1234", "customer_code": "300-X001",
  "as_of": "2026-10-26T09:00:00",
  "total_outstanding": 15230.40,
  "documents": [
    {"source_ref": "ABC_DB:IV:88213", "outstanding": 1100.00, "due_date": "2026-11-25"},
    {"source_ref": "ABC_DB:CN:4410", "outstanding": -200.00, "due_date": null}
  ]
}
```

- `source_ref` `{db}:debtor:{Debtor.AutoKey}`; customer resolved by ref then code; unresolved = `failed`.
- `total_outstanding`: AutoCount's own figure for the debtor in MYR (Q1 (a)); `as_of` -> `customers.ar_as_of`.
- `documents`: every OPEN AR item from an IV, CS, DN (`Outstanding`) or a CN (unapplied
  `NetTotal - KnockOffAmt`, sent negative), keyed by the 2.6 ref. AR entries keyed straight into AR are in
  the total, not in the list. An unlisted stored document with non-zero outstanding is set to 0 (paid); an
  unknown listed ref is skipped (`documents_unknown`).
- Stale guard on `as_of`: older = `unchanged` + `stale_ignored`; identical = `unchanged`.

**14.3 What the shared service adds.** Four SQL presets (IV, CS, CN, DN) on the `_linked_preset` pattern,
`key_columns=("DocKey",)`, watermark `LastModified`, `doc_date_column="DocDate"`, `from_date` 2023-01-01;
billing line cut (keep non-zero `SubTotal`, drop pure text lines); line fingerprint `COUNT(*), SUM(Qty),
SUM(SubTotal), SUM(Tax), MAX(DtlKey), COUNT(FromDocDtlKey)` (+ `SUM(TransferedQty)` on IVDTL / CSDTL) in the
header and the sweep; push IV and CS before CN and DN; reconcile vanishings to `/billing_documents/deletions`.
Line source refs: `FromDocType='SO'` -> `{db}:{SO.DocKey}:{SODTL.DtlKey}`; `'DO'` ->
`{book}:DO:{DocKey}:{DtlKey}` (the DO feed's book); `'IV'` (CN lines) -> `{db}:IV:{DocKey}:{DtlKey}`; NULL
`FromDocDtlKey` -> `from_doc_type` / `from_doc_no`, no ref. AR sweep over `ARInvoice`, `ARDN`, `ARCN` per
`DebtorCode`; per-debtor fingerprint `SUM(Outstanding), COUNT(open), MAX(LastModified)`; hourly plus a daily
full pass. AR row -> billing ref by `SourceType` / `SourceKey` if those columns exist, else `DocNo` +
`DebtorCode` (to confirm on access).

## REF (schema reference, summary of what the presets rely on)

Header -> field: `DocNo` doc_no; `DocDate` doc_date; `Debtor.AutoKey` via `AccNo` customer_ref, `DebtorCode`,
`DebtorName`; `SalesAgent` agent_code; `CurrencyCode`, `CurrencyRate`; `TotalExTax` net_total; `Tax`
tax_total; `NetTotal` total (NOT `FinalTotal`); `LocalNetTotal - LocalTax` local_net_total [?];
`Cancelled='T'` cancelled else posted; `LastModified` source_modified_at (server local time); `Ref`,
`Description`; CN/DN `OurInvoiceNo` (first entry of a comma list) against_doc_no.

Line -> field: `Seq` line_number; `Item.AutoKey` via `ItemCode` product_ref (NULL on charge/discount/text
lines); `Description`, `UOM`, `Qty`, `UnitPrice`; `DiscountAmt` discount_amount; `SubTotalExTax`
net_amount; `TaxCode`, `TaxRate`, `Tax`; `SubTotal` line_total (includes tax); `FromDocType`, `FromDocNo`,
`FromDocDtlKey`. Billing line cut: keep any line whose `SubTotal` is non-zero; drop pure text lines
(`SubTotal` NULL/0 and `Qty` NULL); package parent/child must not double count.

AR: `ARInvoice` (one per IV and CS, plus hand-keyed) `DocKey, DocNo, DebtorCode, DocDate, DueDate,
Outstanding, Cancelled, LastModified, NetTotal, CurrencyCode`; `ARDN` `..., DueDate, NetTotal, Outstanding,
LastModified`; `ARCN` `..., NetTotal, KnockOffAmt, LastModified` (unapplied = `NetTotal - KnockOffAmt`). Most
AR columns are [C-3p]/[I]: nothing was run against the billing or AR tables yet (access after 25 Oct).
