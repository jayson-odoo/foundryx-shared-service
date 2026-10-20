# 32 - AutoCount billing documents + AR outstanding feed (CRM #1770)

Lane SS-BILLING-FEED. UAC: `32-autocount-billing-feed-acceptance-criteria.md`. Contract copy (masked):
`32-autocount-billing-feed-contract.md` (CRM sections 12 + 14 + REF stay the contract of record).

The shared-service half of CRM #1770: four SQL presets that pull AutoCount billing documents (IV, CS, CN, DN)
into the CRM's `billing_documents` door (contract 2.6), and an AR sweep that pushes one outstanding snapshot
per debtor into `ar_outstanding` (contract 2.10). Built on the regular `sql_db` ETL (entity tasks, mapping
engine, `SorentoSink`), exactly like the Cancel SO / Consignment presets (#122, #125). AutoCount is read-only.
No backfill and no live push here.

## Decisions

- **D1 Four entities, one door.** `invoice`, `cash_sale`, `credit_note`, `debit_note` are separate entity
  tasks (each has its own header/line tables and preset) that all post to `ingest/billing_documents`;
  `document_type` is a per-entity constant on the canonical model, never a mapping row.
- **D2 Canonical wire, not the doc-feed shape.** Contract 2.6 is a snake_case canonical record
  (`CanonicalBillingDocument`), so these are `CanonicalDocument` subclasses with an explicit `SINK_FIELDS`
  list (no contract-v2 fallback split: the whole record is 2.6). The wire emits EVERY listed key (null when
  empty) because a push names the whole document. Decimals are JSON numbers.
- **D3 Identity** `{database}:{IV|CS|CN|DN}:{DocKey}` (company database name, like SO; not the doc-feed
  book). One more branch in `mapping.flat_source_ref` (a `BILLING_DOCUMENT_REF_CODES` map), so the row hash,
  delete intents and the staged record share one string.
- **D4 Status** `if(Cancelled == "T", "cancelled", "posted")`; the billing model has its own two-word
  vocabulary (`posted`, `cancelled`) instead of the order family's five.
- **D5 Datetimes.** AutoCount stores MYT wall time. The engine's `datetime` transform keeps the wall time
  (labelled UTC); the billing wire re-labels it `+08:00` (`source_modified_at`). `as_of` is the mapping time,
  sent in MYT with `+08:00`.
- **D6 Line link refs** minted by the mapping engine beside the PO/SPO linkage minting, from line INPUT
  fields that never reach the wire (`from_so_doc_key`, `from_do_doc_key`, `from_iv_doc_key`,
  `from_doc_line_key`) resolved in SQL by conditional `LEFT JOIN`s on `SODTL` / `DODTL` / `IVDTL`. The DO
  hop needs the company's DO-feed book: the engine takes a `link_book` (the same
  `http_source.book.linked_document_book` the linked documents use); a DO line on a company with no book is a
  named mapping error (owner ruling 20 Oct: exact links only, fail loudly). `DODTL` joins the RUNBOOK 0.1
  grant (owner ruling 20 Oct); without it the line query fails at Preview.
- **D7 Drafts.** No draft letter is guessed (owner ruling 20 Oct): the header selects `DocStatus`, the task's
  `filterFormula` is set after REF check 6.2.
- **D8 AR outstanding = a debtor-keyed document.** Header row = one debtor with any AR row (open or not, so a
  paid-off debtor re-pushes `0` / `[]`, owner ruling 20 Oct); lines = its open AR items that match exactly one
  billing document by `DocNo` + `DebtorCode` (the `SourceType`/`SourceKey` columns are unconfirmed, REF
  [I]); the line's `source_ref` is that billing ref, NOT prefixed with the debtor ref. Watermark and doc-date
  column = the debtor's latest AR `LastModified`; the fingerprint sweep (hourly with the incremental) catches a
  knock-off that bumps no `LastModified`; the daily reconcile is the full pass. No `LineCount` column (open AR
  items not matching a billing document are in the total but not in the lines). `NO_DELETION_ENTITY_TYPES`
  gains `ar_outstanding`.
- **D9 `total_outstanding`** = `SUM(ARInvoice.Outstanding) + SUM(ARDN.Outstanding) - SUM(ARCN.NetTotal -
  ARCN.KnockOffAmt)` in the preset text (owner ruling 20 Oct (a)): REF section 4 lists no rate column on the
  AR tables, so it is correct for MYR debtors only until the REF section 6 check names the debtor figure or a
  rate column; the text is operator-editable. `documents[].outstanding` stays in document currency (CRM
  confirmed it displays it with the document's own currency).
- **D10 Gates.** `billing_documents` at 2.6, `ar_outstanding` at `ContractVersion(2, 10)`; all five in
  `PUSH_REFUSES_LOGGING_FALLBACK`. BL-SS-289 fixed first: versions compare as `(major, minor)` integers.
- **D11 Push order.** Billing entities join the existing entity dependency order: IV and CS before CN and DN.

## Open checks (after access, REF section 6, logged for the RUNBOOK)

Package parent/child lines (`DtlType`, `ParentDtlKey`) are not de-duplicated (no rule yet); charge lines with
NULL `Qty` are sent with `quantity: null` and the CRM requires `quantity` (CRM gap, reported); AR `Cancelled`
on `ARDN`/`ARCN` and an AR rate column are unlisted; `SourceType`/`SourceKey` would replace the DocNo match.
