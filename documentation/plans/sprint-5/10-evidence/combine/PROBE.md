# AC-10-84 live-numbers proof - the recorded db1 capture (S4, review round 5)

This file documents the recorded db1 capture `test_s10_s5b_live_numbers.py` replays against
`apply_combine`/`fetch_changes` to prove the stock preset reproduces the live numbers end to end
with no operator configuration. It does not duplicate `README.md` in this directory (owned by the
browser tester, live-click evidence) - this is the backend-only, no-network proof's own record.

## Capture

- **Date:** 2026-09-19 (UTC), against `db1` (`AED_SORENTO`), the real `hapi.sorento.cc.cd`
  open-REST wrapper, paged at 1000 rows/page.
- **Source endpoints recorded:** `/itembatchbalqtybypage` (69 pages, `bal-1.json..bal-69.json`),
  `/itembypage` (12 pages, `itembypage-1.json..itembypage-12.json`), `/itemuombypage` (12 pages,
  `itemuombypage-1.json..itemuombypage-12.json`), plus one `location.json` snapshot of the
  warehouse master (referenced by AC-10-68's own fixture, not by this test).
- **File count:** 93 page files + `location.json` = 94 files, ~19 MB total.
- **Stable path (never committed to the repo):** `~/.foundryx/autocount-probe/db1-2026-09-19/`.
  Copied there from a session scratchpad dir on 2026-09-20 (review round 5, S4) after the
  scratchpad copy was found to still exist but was liable to be reaped at any time - the ORIGINAL
  scratchpad path is no longer referenced anywhere in the test.
- **Override:** the `AUTOCOUNT_PROBE_DIR` env var, read by
  `service_backend/tests/test_s10_s5b_live_numbers.py`, takes priority over the stable path (e.g.
  to replay a fresh capture without overwriting the pinned one).

## Measured funnel (test run, `-q -rs`, `AUTOCOUNT_PROBE_DIR` unset - resolves to the stable path)

| Stage | Count |
|---|---|
| Rows in (raw balance rows walked, `rows_scanned`) | 68,612 |
| Excluded (combine `require` stage - `uom_rate_unresolved` / `computed_error`) | 0 |
| Groups formed (distinct `(item_code, location_code)` pairs, pre-drop) | 68,597 |
| Dropped by the `zero` rule | 56,422 |
| Dropped by the `negative` rule (all 42 listed, `listRows: true`) | 42 |
| Rounded (pre-rounding value changed, `roundedCount`) | 0 |
| Rows out (`len(result.records)`) | 12,133 |

68,597 = 56,422 + 42 + 12,133 (every group is accounted for by exactly one of zero / negative /
delivered). `excludedCount: 0` here means every `(ItemCode, UOM)` pair the balance table names
has a matching `/itemuombypage` rate row in this EXACT capture - the plan's earlier "5 known
rate-unresolved rows" narrative (an earlier/different probe) does not reproduce against this
recorded set; noted, not silently overridden (also called out in the test file's own docstring
and AC-10-84's amended UAC text).

## Runtime

The full pass (loading 93 recorded JSON pages once per module, then one `apply_combine`/
`fetch_changes` walk over 68,612 raw dicts, pure Python, no network) takes on the order of 7-10
seconds - a single gated live-numbers proof, deliberately not a per-case unit test, per the
plan's own "keep the test fast: load pages once per module" instruction.

## Verifying this proof still runs (not skipped)

```
cd service_backend
unset AUTOCOUNT_PROBE_DIR
.venv/bin/python -m pytest tests/test_s10_s5b_live_numbers.py -q -rs
```

A `-rs` summary line naming a skip means the stable path above is missing or incomplete (93 page
files + `location.json`) - restore it from a fresh capture and re-run, never treat a silent skip
as the proof having passed.
