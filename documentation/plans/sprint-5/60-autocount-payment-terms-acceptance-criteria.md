# Plan 60 - AutoCount Terms master + debtor term on the customer feed - Acceptance Criteria

Lane SS-PAYMENT-TERMS (size M, backend only). Pairs with sorento-crm #2305 (QUOTE-TERMS-SELECT, contract 2.14,
as revised 10 Nov: `payment_terms` = `code` + `rule` + `is_active`; customers accept `payment_terms_code`).
Plan: `60-autocount-payment-terms.md`.

## Slice A - `payment_term` master (AutoCount `/terms` -> CRM `payment_terms`)

| ID | Tag | Given / When / Then |
|---|---|---|
| AC-60-01 | [BE][T] | Given the recorded hapi `/terms` rows (db1 17, db2 21, each `{DisplayTerm, Terms}`), when a run maps them with the preset, then each row yields one record keyed `{DatabaseName}:{DisplayTerm}`. |
| AC-60-02 | [BE][T] | The record is `{source_ref, code = DisplayTerm, rule = Terms, is_active: true}`; the label is sent as AutoCount spells it; a blank rule is sent as `""`; no other key (no description, no term_days, no `Terms` key). |
| AC-60-03 | [BE][T] | A code over 100 chars or a rule over 200 fails that term at mapping (never a CRM 422); the others still push. |
| AC-60-05 | [BE][T] | The push goes to `POST /api/v1/external/ingest/payment_terms` with `companyCode`, through `SorentoSink` (X-API-Key, chunking, 429, per-record verdicts). |
| AC-60-06 | [BE][T] | A CRM below 2.14, or 2.14 without `payment_terms` in `entities`, refuses the push and keeps every term STAGED; the next run after the CRM upgrade delivers them. |
| AC-60-07 | [BE][T] | An unchanged rerun pushes nothing; a changed rule re-pushes only that term. |
| AC-60-08 | [BE][T] | A term gone from the list is staged as a delete and sent to `/ingest/payment_terms/deletions` (the CRM deactivates, never deletes). |
| AC-60-09 | [BE][T] | Read only: every vendor call is a GET; no write path to AutoCount exists. |
| AC-60-10 | [BE][T] | A scheduler tick enqueues `item_class`, then `payment_term`, before `customer`. |
| AC-60-11 | [BE][T] | Entity parity pins (FE `AC_HTTP_ENTITY_TYPES`, `HTTP_PRESETS` copy, mock, entity counts) include `payment_term`. |
| AC-60-12 | [BE][T] | Neither recorded book has two DisplayTerms differing only by case (the CRM's first-push adoption is case-insensitive). |

## Slice B - debtor term on the customer feed

| ID | Tag | Given / When / Then |
|---|---|---|
| AC-60-20 | [BE][T] | A `/debtorbypage` (or vendor Debtor) row's `DisplayTerm` maps to `payment_terms_code`, trimmed; blank or absent is omitted, never null. |
| AC-60-21 | [BE][T] | The vendor default customer mapping, the `/debtorbypage` preset and the customer source catalog carry `DisplayTerm`; suppliers never carry `payment_terms_code`. |
| AC-60-22 | [BE][T] | Existing customer tasks get the row via `backfill_customer_display_term` (module Alembic 0043 + `update_tenant` from < 0.23.0), tenant-scoped, idempotent, tasks without rows skipped. |
| AC-60-23 | [BE][T] | The push sends `payment_terms_code` only to a CRM that advertises >= 2.14; below 2.14 or on an unprovable contract it is stripped. The contract is probed at most once per sink and only for a batch that carries the field. |

## Security

| ID | Tag | Given / When / Then |
|---|---|---|
| AC-60-30 | [T] | No new credential, permission, route or write path; existing connections and sync permissions are reused. |
