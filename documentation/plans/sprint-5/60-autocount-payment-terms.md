# Plan 60 - AutoCount Terms master push + debtor term on the customer feed (lane SS-PAYMENT-TERMS, size M)

Pairs with sorento-crm #2305 (QUOTE-TERMS-SELECT, contract 2.14). Deploy order is free: the payment terms entity
is contract-gated and the customer field is field-gated, so either side can land first. UAC:
`60-autocount-payment-terms-acceptance-criteria.md`.

## Wire (CRM #2305 crew-notes, contract 2.14 as revised 10 Nov)

`POST /api/v1/external/ingest/payment_terms` (+ `/deletions`, deactivate only), advertised from 2.14 with
`payment_terms` in `entities`:

```json
{"companyCode": "SRT", "records": [
  {"source_ref": "AED_SORENTO:NET 30 DAYS UPON LOADING DATE", "code": "NET 30 DAYS UPON LOADING DATE",
   "rule": "C.O.D.", "is_active": true}
]}
```

`code` 1..100 (case kept), `rule` <= 200 (`""` clears), `is_active`. Customers: `payment_terms_code` (<= 100, raised from 50 to equal the term code cap, from
`Debtor.DisplayTerm`), accepted from 2.14 only (earlier contracts list it in `fields_removed.customers`).

## Source (crew GET, 10 Nov)

`GET /api/db{1,2}/terms`: plain array, no paging, no timestamps, no active flag; rows `{DisplayTerm, Terms}` only
(db1 17, db2 21; fixtures `tests/fixtures/autocount_http/terms-db{1,2}.json`). Read only, GET only.

## Decisions

- **D1 Entity `payment_term`**, an HTTP-only master wired exactly like `item_class` (plan 37): canonical model with
  the CRM caps, `/terms` preset keyed `DisplayTerm`, no watermark, `CONTRACT_GATED_ENTITIES` at 2.14,
  `PUSH_REFUSES_LOGGING_FALLBACK` (a full list with changed-only staging would otherwise never be offered again),
  not in `NO_DELETION_ENTITY_TYPES` (a vanished term goes to `/deletions`).
- **D2 Preset rows**: `DisplayTerm -> code` (required), `Terms -> rule`, `DisplayTerm -> is_active` with formula
  `true` (listed = active; reactivates a term an earlier sweep deactivated). A blank rule is written as `""` by
  `CanonicalPaymentTerm.sink_payload` (AutoCount is master for it, the item class description precedent).
- **D3 Identity**: `{DatabaseName}:{DisplayTerm}` (company-qualified, like every master). No case-only pair exists
  in the recorded books (pinned), so the CRM's case-insensitive first-push adoption cannot conflict.
- **D4 Order**: `sweep_order_key` puts `item_class` (-2), then `payment_term` (-1), before every other entity, so
  terms reach the CRM before the customers naming them. The CRM matches by code at quotation time, so correctness
  never depends on it.
- **D5 Customer field gate**: `CanonicalCustomer.payment_terms_code` is in `SINK_FIELDS`; `sink_payload(
  advertised_contract=...)` strips it unless the consumer is provably >= 2.14. Non-push callers (preview, row
  projection) pass nothing and keep it. `SorentoSink._customer_contract` probes `/contract` lazily, at most once
  per sink, only when a batch holds a customer carrying the field (no extra call for deletes or term-less batches;
  a failed probe strips).
- **D6 Backfill**: `backfill_customer_display_term` (the DebtorType rules) via module Alembic 0043 and
  `update_tenant` from < 0.23.0; manifest and `USER_AGENT` 0.23.0. Data only, no column.
- **D7 No new permission, route or credential.**

## Review follow-ups

- The pull gateway and preview show `payment_terms_code` regardless of the consumer's contract (they are not
  pushes); customers are not pull-capable today.
