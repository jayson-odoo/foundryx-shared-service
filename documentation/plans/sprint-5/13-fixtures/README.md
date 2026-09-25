# Plan 13 S0 - SR5 fixtures (Appendix A7)

Recorded for the Sorento peer session's SR5 build and for this lane's own
`test_s13_stock_sink_payload_parity.py` / `test_s13_stock_push_contract_gate.py`
parity assertions. Companion to plan `13-autocount-stock-push.md` Appendix A
(the SR5 brief) - Appendix A7 lists these seven files.

**No live network was used.** Every request-side row is built by running the
REAL `modules.autocount.canonical.masters.CanonicalStockBalance.sink_payload()`
in this lane's venv (never hand-typed), over `item_code`/`item_description`
values taken from the plan 10 fixture
`documentation/plans/sprint-5/10-fixtures/stock-rows-page1.json` (itself a
real db1 probe-capture excerpt, see that fixture's own README for provenance).
Response-side verdicts (`created`/`updated`/`retryable`/`not_found`/warnings)
are constructed to the shape Appendix A3/A4 specifies - Sorento has not built
SR5 yet, so no real gateway response exists to capture. `source_ref` uses the
`AED_SORENTO` company-database prefix, matching the plan 10 stock fixtures
for company `SRT`.

Generation script (not committed - ad hoc, run from `service_backend/`):

```python
from modules.autocount.canonical.masters import CanonicalStockBalance

DB = "AED_SORENTO"

def row(item_code, item_description, location_code, uom_code, qty):
    rec = CanonicalStockBalance(
        source_ref=f"{DB}:{item_code}|{location_code}",
        item_code=item_code, item_description=item_description,
        location_code=location_code, uom_code=uom_code, qty=qty,
    )
    return rec.sink_payload()
```

## Files

- **`contract-2.5.json`** - `GET /external/contract` answer Foundryx expects
  once SR5 ships: `version: "2.5"`, `stock_balances` in `entities`,
  `warehouse_inactive` joins `warnings` beside the existing
  `warehouse_unresolved`/`ref_mismatch`. Pins AC-13-01/02/30 (the contract
  probe `CompanyService.stock_push_gate_error` / `sorento_supports_entity`
  read).

- **`stock_balances-ingest-request.json`** - `POST
  /api/v1/external/ingest/stock_balances` body, 10 records, exactly the six
  `CanonicalStockBalance.SINK_FIELDS` per row (`source_ref`, `item_code`,
  `item_description`, `location_code`, `uom_code`, `qty` - `qty` a JSON
  integer, never a string). Pins AC-13-03 (`SorentoSink._to_records` parity).
  The 10 rows, by index:

  | # | `item_code` \| `location_code` | Case (A7) |
  |---|---|---|
  | 1 | `1/2" ULTRA CIRCULAR` \| `BRW-BB` | Real db1 pair (plan 10 stock-rows-page1.json row 1); item code carries an embedded quote AND a space - the "item code with spaces and quotes" case |
  | 2 | `32MM TAIL PIECE COUPLING` \| `BRW` | Real db1 pair (plan 10 row 2), plain |
  | 3 | `ACC-CB8001` \| `MWH` | Real db1 pair (plan 10 row 4), plain |
  | 4 | `ACC-KS7001-YG` \| `WH3` | Real db1 pair (plan 10 row 5), plain |
  | 5 | `ACC-SRT1024` \| `CON` | Real item code (plan 10 row 6), CONSTRUCTED pairing at `CON` - the INACTIVE-warehouse case (plan 10's own "before CON/HQ/DISPLAY are activated" consignment note); the probe capture holds no real `CON` balance to reuse |
  | 6 | `ACC-SRT6010` \| `BRW-VAR` | Real item code (plan 10 row 7), CONSTRUCTED pairing at an UNKNOWN location Sorento has no warehouse row for |
  | 7 | `ACC-SRT8003` \| `MBS` | Real item code (plan 10 row 8); illustrates the "trailing-space location already trimmed" case (AC-10-60(d)) - the wire value is the TRIMMED `"MBS"` (what the combine step's `trim(Location)` formula delivers), never the raw `"MBS "`; qty is a CONSTRUCTED representative value since every real `(item, MBS)` pair in the probe capture nets to zero (documented, not faked, exactly as the plan 10 stock fixture README does for the same location) |
  | 8 | `ACC-SRT9013` \| `PJ-SR` | Real db1 pair (plan 10 row 9); the SAME item as the plan 10 products fixture's clamped `-1.0`-price row (cross-reference kept) |
  | 9 | `SRT-NOTSYNCED-9001` \| `MWH` | CONSTRUCTED - a synthetic item code, deliberately never a real AutoCount code, to stand for "an item Sorento lacks" (`retryable`) |
  | 10 | `B2154-NL` \| `MAINTANC` | Real db1 pair (plan 10 row 10), plain filler |

- **`stock_balances-ingest-response.json`** - the expected per-record verdict
  for the request above: `created` (rows 1, 3, 8), `updated` (rows 2, 4, 7,
  10), `updated` + `warnings: ["warehouse_inactive"]` (row 5 - Appendix A3
  resolution step 1: "write nothing"), `updated` + `warnings:
  ["warehouse_unresolved"]` (row 6, same reason), `retryable` (row 9 - item
  not yet synced as a product). `summary` is EXACTLY `{total, created,
  updated, failed, retryable}` - Sorento's gateway summary carries no
  `warningCounts` key at all (that is Foundryx's OWN synthesized run
  summary, built by `SyncService` from each record's `warnings` array - a
  DIFFERENT object, never this one; see the Sorento correction note below).

- **`stock_balances-ingest-dry-run-response.json`** - the SAME batch under
  `?dry_run=true`, corrected per Sorento's 2026-09-25 review: a `created`
  row carries NO `diff` key at all (there is no "current" value to diff
  against); an `updated` row with no change carries `diff: {}`; an `updated`
  row with a genuine change carries `diff: {"qty": {"current": N, "incoming":
  M}}` (rows 4 and 7, the WH3 and MBS pairs); a `retryable` row carries no
  `diff` either. Nothing is written either way. `entity_id` follows the same
  present/null rule as the real-run response.

- **`stock_balances-deletions-request.json`** - `POST
  .../stock_balances/deletions` body: 5 `source_refs` with a `pairs` map
  keyed by ref (`{item_code, location_code}`, mirroring the 2.4 `codes`
  shape) - row 1 (real, active) and row 10 (real, active) each carry a
  `pairs` entry and resolve; row 5 (`CON`, inactive) carries a `pairs` entry
  but resolves `not_found` (Appendix A4: an inactive-warehouse delete never
  writes); row 9 (the item Sorento lacks) carries a `pairs` entry but has no
  stock row to zero; the 4th ref (`GHOST-ITEM|MWH`) is deliberately OMITTED
  from `pairs` - the "one ref without a pairs entry" A7 asks for.

- **`stock_balances-deletions-response.json`** - `deleted` (rows 1, 10),
  `not_found` with `warnings: ["warehouse_inactive"]` (row 5 - Appendix A4:
  "no `pairs` entry, product/warehouse/stock row missing, or warehouse
  inactive... add `warnings: [\"warehouse_inactive\"]` in that case"),
  `not_found` (row 9 - no stock row for an unsynced item), `not_found` (the
  ref with no `pairs` entry). `summary` is EXACTLY `{total, deleted,
  deactivated, not_found, failed}` - no `retryable` key (corrected per
  Sorento's review; a delete's own SinkUnknownEntity->retryable posture is
  Foundryx's own client-side handling of a 404 `UNKNOWN_ENTITY`, never a
  value Sorento's summary itself carries). Pins AC-13-05.

- **`stock_balances-deletions-error-422-invalid-body.json`** - the
  BODY-LEVEL failure shape when `pairs` itself is malformed (not an object,
  or over 1000 entries): `422 {code: "INVALID_BODY", message, detail: null}`
  for the WHOLE batch - distinct from a single malformed `pairs` ENTRY
  (below), which fails only that one ref.

- **`stock_balances-deletions-malformed-entry-request.json`` /
  `-response.json`** - one clean ref (deletes) beside one ref whose `pairs`
  entry is missing `location_code` - the malformed entry alone comes back
  `failed` with `errors`, the clean ref still `deleted`.

- **`stock_balances-ingest-duplicate-pair-request.json`` /
  `-response.json`** - the SAME `source_ref` (same item_code + location_code
  pair) submitted twice in ONE ingest batch, with different `qty` - Sorento
  processes IN ORDER and the LAST value wins: the first occurrence verdicts
  `created`, the second `updated`, both echoing the SAME `entity_id`.

## Corrections from Sorento's 2026-09-25 review

Sorento checked this brief against their code and returned six corrections,
applied to the fixtures above (git history on this file shows the
before/after):

1. `entity_id` is ALWAYS present on every verdict record (never omitted);
   it is `null` on a warning, `retryable` or `failed` row and a real id
   otherwise. The ids here are placeholders
   (`00000000-0000-0000-0000-0000000000NN`) - tests assert PRESENCE and
   null-vs-non-null only, never a specific value/format.
2. Dry-run diffs: `created` -> no `diff` key; `updated` no-change -> `diff:
   {}`; `updated` with a change -> `diff: {"qty": {current, incoming}}`.
   The original draft had row 1 (`created`) also carrying a contradictory
   `diff.current` - fixed by moving the "genuine change" examples onto two
   `updated` rows (WH3, MBS) instead.
3. `diff` appears ONLY on the dry-run response; the real-run response never
   carries it (confirmed unchanged from the original draft).
4. Both gateway summaries are narrower than first drafted: ingest summary is
   exactly `{total, created, updated, failed, retryable}` (no
   `warningCounts`); deletions summary is exactly `{total, deleted,
   deactivated, not_found, failed}` (no `retryable`).
5. A malformed `pairs` BODY (not an object / over 1000 entries) is a
   batch-level `422 INVALID_BODY`, never a per-record outcome - see the new
   `-error-422-invalid-body.json` fixture. A single malformed `pairs` ENTRY
   fails only that ref (`outcome: "failed"`) - see the new
   `-malformed-entry-*.json` pair.
6. A duplicate pair (same `source_ref`) submitted twice in one ingest batch
   is processed in request order, last value wins - see the new
   `-duplicate-pair-*.json` pair.

## Known gaps

- Every response-side verdict is CONSTRUCTED to Appendix A3/A4's stated
  shape (as corrected by Sorento's review above), not captured from a live
  SR5 gateway - Sorento has not built it yet (the whole point of this
  brief). Re-verified against the real gateway once their SR5a lands (plan
  section 4, slice S4's joint run), same discipline as plan 10's own
  fixtures.
