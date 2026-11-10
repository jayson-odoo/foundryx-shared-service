# Plan 60 - AutoCount Terms master + debtor term on the customer feed - Acceptance Criteria

Lane SS-PAYMENT-TERMS (size M, backend only). Pairs with sorento-crm #2305 (QUOTE-TERMS-SELECT, contract 2.14).
Wire names marked PENDING are filled from the #2305 contract comments (6760050217, 6760472309) before the
build; until then they are not guessed.

## Slice A - `payment_term` master (AutoCount Terms -> CRM `payment_terms`)

| ID | Tag | Given / When / Then |
|---|---|---|
| AC-60-01 | [BE][T] | Given recorded hapi `/terms` rows for db1 and db2, when mapped with the preset, then each row yields one `payment_term` record keyed `{DatabaseName}:{DisplayTerm}` (company-qualified, DisplayTerm trimmed). |
| AC-60-02 | [BE][T] | The record carries the term code (`DisplayTerm`), description and term days exactly as the contract names them (PENDING keys); a blank description and a missing day count follow the contract's blank rule. |
| AC-60-03 | [BE][T] | A value longer than the CRM column cap fails at mapping (field error), never a CRM 422. |
| AC-60-04 | [BE][T] | `sink_payload` carries only the contract's keys; no provenance, no `extras`. |
| AC-60-05 | [BE][T] | The push goes to `POST /external/ingest/payment_terms` with `X-API-Key` + `companyCode`, reusing `SorentoSink` (chunking, 429 `Retry-After`, per-record verdicts). |
| AC-60-06 | [BE][T] | Contract gate: a CRM below 2.14, or 2.14 without `payment_terms` in `entities`, refuses the push with `CONTRACT_GATE` and keeps the rows STAGED (never the logging fallback marking them PUSHED). |
| AC-60-07 | [BE][T] | Re-running with unchanged rows stages nothing (row-hash change detection); a changed TermDays stages one update. Idempotent per DisplayTerm per database. |
| AC-60-08 | [BE][T] | A term gone from a database's `/terms` list is staged as a delete and sent to the CRM's inactive path (PENDING: `/deletions` door or `is_active: false`); it is never hard-deleted. |
| AC-60-09 | [BE][T] | Read only: the source performs GETs only; no write path to AutoCount is added (no POST/PUT/DELETE against the vendor). |
| AC-60-10 | [BE][T] | `payment_term` is enqueued before `customer` in a scheduler tick (terms reach the CRM before the debtors that name them). |
| AC-60-11 | [BE][T] | Entity parity pins (FE `AC_HTTP_ENTITY_TYPES`, contract-version compare, entity counts) move to include `payment_term`. |

## Slice B - debtor term on the customer feed

| ID | Tag | Given / When / Then |
|---|---|---|
| AC-60-20 | [BE][T] | Given a recorded `/debtorbypage` row with `DisplayTerm`, the customer record carries it under the contract key (PENDING), trimmed; blank is omitted, never null. |
| AC-60-21 | [BE][T] | The vendor default customer mapping and the `/debtorbypage` preset map `DisplayTerm`; `DisplayTerm` joins the customer source catalog. |
| AC-60-22 | [BE][T] | Backfill: existing mapped customer tasks get the row (module Alembic + `update_tenant`), tenant-scoped; tasks with no rows are skipped. |
| AC-60-23 | [BE][T] | If the contract gates the key on 2.14, a lower CRM never receives it (no per-record reject on an older CRM). |

## Security

| ID | Tag | Given / When / Then |
|---|---|---|
| AC-60-30 | [T] | No new credential, permission, route or write path; the existing sync permissions and the company's existing hapi + CRM connections are reused. |
