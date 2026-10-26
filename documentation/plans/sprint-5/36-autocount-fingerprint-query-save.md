# Plan 36 - a document task's fingerprint query survives Save (lane SS-BILLING-PRESET-FIX, F-B, size S)

Found while preparing the prod billing task setup (27 Oct). The Save body `EtlSourceConfigIn`
(`modules/autocount/schemas.py`) has no `fingerprintQuery`; the router passes `model_dump()`; the validator
(`etl_service.validate_source_config`) then stores `fingerprintQuery = None` on every save. A task set up in the
UI never gets a line-fingerprint sweep, and any later Source-tab Save wipes the one
`backfill_document_fingerprint_queries` set. Effect: line-only edits and AR knock-offs (no `LastModified` bump)
wait for the daily reconcile instead of the incremental tick. Delay, not loss.

## Rule
- `fingerprintQuery` is an optional field of the Save body.
- Sent (non-blank): stored as sent (normalised, SELECT-only guarded, unchanged).
- Not sent / null / blank: keep the stored one; none stored -> the entity preset's sweep query with the
  company's database substituted (the same policy as `backfill_document_fingerprint_queries`).
- SQL document tasks only; masters and HTTP tasks unchanged.

## Tests (red first)
`tests/test_autocount_fingerprint_query_save.py`: first save takes the preset's; a save without one keeps the
stored one (incl. explicit null); an explicit one replaces; the wire model carries the key; the PUT route keeps it.

No frontend change needed (the FE never sends the key, so it is always "keep"). No migration: existing tasks
already lacking one are filled by `update_tenant`'s backfill (App Store Update) or by their next Save.
