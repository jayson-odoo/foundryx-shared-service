# 32 - AutoCount billing documents + AR outstanding feed: acceptance criteria

Lane SS-BILLING-FEED (CRM #1770, contract 2.6 section 12 + 2.10 section 14). Contract copy:
`32-autocount-billing-feed-contract.md`. Plan: `32-autocount-billing-feed.md`.

AutoCount is read-only. No backfill and no push to a live consumer happen in this lane: S4 (backfill, SELECT
grant, tally) is the owner's, after 25 Oct. Every test uses fixture rows, never real data.

Tags: `[BE]` backend behaviour, `[T]` pinned by a pytest, `[FE]` frontend.

## A. Contract versions

- **AC-32-01** `[BE][T]` Given the CRM answers `GET /contract` with `"version": "2.10"`, when any contract gate
  compares it, then it reads as 2.10 (above 2.9), never 2.1; every existing 2.3 - 2.9 gate stays open on 2.10.
- **AC-32-02** `[BE][T]` Given a numeric (`2.7`) or patch (`"2.3.1"`) version body, then it parses as before
  (2.7, 2.3); a blank or non-numeric version is "unprovable" (`None`), as before.

## B. Billing entities and presets (contract 2.6)

- **AC-32-10** `[BE][T]` Four SQL document entities exist: `invoice` (IV/IVDTL), `cash_sale` (CS/CSDTL),
  `credit_note` (CN/CNDTL), `debit_note` (DN/DNDTL). Each has a preset in `DOCUMENT_PRESETS` with
  `key_columns=("DocKey",)`, watermark `LastModified`, `doc_date_column="DocDate"`, `from_date="2023-01-01"`,
  no filter formula, and the header selects `DocStatus` (draft letter decided after REF check 6.2).
- **AC-32-11** `[BE][T]` The header query maps per REF section 2: `TotalExTax` net_total, `Tax` tax_total,
  `NetTotal` total (never `FinalTotal`), `LocalNetTotal - LocalTax` local_net_total, `CurrencyCode`,
  `CurrencyRate`, `SalesAgent`, `Ref`, `Description`, `LastModified`; CN and DN also `OurInvoiceNo`.
- **AC-32-12** `[BE][T]` Billing line cut, in the line query AND the header aggregate AND the fingerprint
  query: a line is kept unless it is a pure text line (`SubTotal` NULL or 0 AND `Qty` NULL). A charge line
  with no `ItemCode` and a non-zero `SubTotal` is kept.
- **AC-32-13** `[BE][T]` Line fingerprint in the header `OUTER APPLY` and the sweep query: `COUNT(*)`,
  `SUM(Qty)`, `SUM(SubTotal)`, `SUM(Tax)`, `MAX(DtlKey)`, `COUNT(FromDocDtlKey)`, plus `SUM(TransferedQty)` on
  IVDTL and CSDTL only.
- **AC-32-14** `[BE][T]` Identity: header `source_ref` = `{database}:{IV|CS|CN|DN}:{DocKey}`; line
  `source_ref` = `{header source_ref}:{DtlKey}`. `SqlDbSource.source_ref` and the mapping engine agree (row
  hash, delete intents and staged records key on one string).
- **AC-32-15** `[BE][T]` Wire record = the contract 2.6 record exactly: every listed key, no other key.
  `document_type` is fixed per entity; `status` is `cancelled` when `Cancelled = 'T'`, else `posted`; money and
  quantities are JSON numbers; `doc_date` is `YYYY-MM-DD`; `source_modified_at` is always sent, as
  AutoCount's MYT wall time with a `+08:00` offset; an optional value with no source value is sent as `null`
  (a push names the whole document); lines go under `lines`.
- **AC-32-16** `[BE][T]` `against_doc_no` (CN, DN) = the first entry of `OurInvoiceNo` when it is a comma
  list, trimmed, `null` when blank; `against_source_ref` is `null` (the CRM resolves by number).
- **AC-32-17** `[BE][T]` Line link refs (`from_line_ref`): `FromDocType 'SO'` -> `{database}:{SO DocKey}:
  {FromDocDtlKey}`; `'DO'` -> `{book}:DO:{DO DocKey}:{FromDocDtlKey}` with the company's DO-feed book (DO
  DocKey from `DODTL`); `'IV'` -> `{database}:IV:{IV DocKey}:{FromDocDtlKey}`. A NULL `FromDocDtlKey`, an
  unresolved source line, or any other type (QT) sends `from_doc_type`/`from_doc_no` and `from_line_ref: null`.
- **AC-32-18** `[BE][T]` A `'DO'`-sourced line on a company with no DO-feed book is a named mapping error on
  that document (never pushed silently unlinked). A missing `DODTL` grant fails the line query loudly
  (Preview / run error), never an unlinked push.
- **AC-32-19** `[BE][T]` Sink: all four post to `ingest/billing_documents` with body
  `{companyCode, records}` (no `book` key); deletions post `{companyCode, source_refs}` to
  `ingest/billing_documents/deletions`; contract gate = version >= 2.6 AND `billing_documents` advertised;
  below the gate the push refuses with `CONTRACT_GATE` and rows stay STAGED (never the logging fallback).
- **AC-32-20** `[BE][T]` Push order (best effort): within one beat tick the sweep enqueues a company's
  `invoice` / `cash_sale` tasks before its `credit_note` / `debit_note` tasks. Jobs then run independently;
  the order is not load-bearing because the CRM fills a note's link when its invoice lands later (contract
  12, Resolution). The platform has no cross-task dependency mechanism (none exists for masters either).

## C. AR outstanding (contract 2.10)

- **AC-32-30** `[BE][T]` An `ar_outstanding` SQL document entity exists, keyed on the debtor (`Debtor.AutoKey`),
  whose header row is one debtor with ANY AR row (open or not) and whose lines are its OPEN AR items that come
  from an IV, CS, DN or CN. Preset: watermark and doc-date column `LastModified` (the debtor's latest AR
  `LastModified`), a per-debtor fingerprint (`SUM` of outstanding, open `COUNT`, `MAX(LastModified)`) in the
  header and the sweep query.
- **AC-32-31** `[BE][T]` Wire record = section 14.2 exactly: `source_ref` `{database}:debtor:{AutoKey}`,
  `customer_ref` `{database}:{AutoKey}`, `customer_code`, `as_of`, `total_outstanding`, `documents`
  (`[{source_ref, outstanding, due_date}]`); nothing else.
- **AC-32-32** `[BE][T]` Document refs = the billing 2.6 ref `{database}:{IV|CS|CN|DN}:{DocKey}` of the
  billing document the AR row belongs to (matched by `DocNo` + `DebtorCode`, exactly one match); a CN's
  outstanding is negative (`-(NetTotal - KnockOffAmt)`); an AR row with no single billing match is in the total,
  not in `documents`.
- **AC-32-33** `[BE][T]` `as_of` = the time the extract was mapped, sent with `+08:00`; it is NOT in the change
  hash (an unchanged debtor is not re-staged on the next run).
- **AC-32-34** `[BE][T]` A debtor whose last open item was paid is re-staged and pushed with
  `total_outstanding: 0` and `documents: []`; a debtor that vanishes from the extract is never sent as a
  deletion (no deletions door) and counts as `vanished`.
- **AC-32-35** `[BE][T]` Sink: posts `{companyCode, records}` to `ingest/ar_outstanding`; gate = version >= 2.10
  AND `ar_outstanding` advertised; a 2.9 consumer refuses with `CONTRACT_GATE`, rows stay STAGED.

## D. Product surface

- **AC-32-40** `[FE][T]` The five entities appear in the Add-entity list of a `sql_database` company with
  readable labels (Invoice, Cash sale, Credit note, Debit note, AR outstanding), not on an HTTP company. An
  invoice / cash sale task on a company with no Delivery Orders feed book shows `delivery_orders` on the
  document prerequisite card. **DEFERRED:** the generic contract-gate banner for these five (the Activate
  tab renders only the brand / branch banners today, and the float `requiredVersion` would read 2.10 as
  2.1, BL-SS-307).
- **AC-32-41** `[BE][T]` Existing entities (SO, PO, SPO, the linked documents, masters) are byte-identical on
  the wire; the existing autocount suites stay green.

## Out of scope (owner, after 25 Oct)

S4 backfill, the SELECT grant (now including `DODTL`), the REF section 6 checks, the draft `filterFormula`,
the tally. Live verification against a real AutoCount book is impossible until the grant lands; it is the
first item of the RUNBOOK run.
