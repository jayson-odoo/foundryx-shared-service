# Plan 10 S0 - Sorento mock-build fixtures

Recorded sample payloads for the Sorento `autocount` peer session's mock build (AC-10-67), shaped
to plan `10-autocount-pull-review.md` Appendix A1/A3/A4/A6/A9/A10. **The lane backend
(`:8009`) has not shipped any application code for this plan yet** (S0 is lane infra + fixtures
only), so these are hand-built from the plan's FINAL agreed shapes (post AC-10-04 enrich,
AC-10-59 clamp, AC-10-73 description join, AC-10-74 `uom_code` withheld) plus REAL AutoCount rows
read from the read-only probe capture at
`.../scratchpad/probe/` (db1, company `SRT`) and `.../scratchpad/probe2/itembypage-4.json`
(db2, company `MCH`) - not committed to the repo. They are re-verified against the real gateway in
S6 (AC-10-67); any drift found there is fixed here in the same commit.

Wire casing throughout: camelCase envelope/metadata keys, snake_case row keys (Appendix A1).

## Files

- **`products-header-ready.json`** - `GET /snapshots/{id}` header for a `ready` PRODUCT snapshot
  (Appendix A3), companyCode `SRT`, matched to the 10 rows in `products-rows-page1.json`
  (`recordCount: 10`, `totalPages: 1`). Pins AC-10-32 (product-specific header fields),
  AC-10-63 (`zeroListPriceCount`/`negativeListPriceCount`/`enrichMissCount` definitions),
  AC-10-07/AC-10-59 (wire value of a clamped/zero `list_price`).
- **`products-header-building.json`** - the `building` header shape (AC-10-32, AC-10-87) with the
  OPTIONAL `progress` hint, `companyCode` `MCH` (illustrating the long-Mocha-build case from
  AC-10-86/A7).
- **`products-rows-page1.json`** - `GET /snapshots/{id}/rows` page envelope (Appendix A3) carrying
  the 10 awkward/real rows AC-10-67 and A10 require (see "Product rows" below). Every row is
  `CanonicalProduct.sink_payload()` run for real through
  `modules/autocount/canonical/masters.py` in this lane's venv (pydantic 2.13.4), so the key set,
  key order and Decimal-as-JSON-string rendering are exactly what the real gateway will emit -
  never hand-typed.
- **`stock-header-ready.json`** - the STOCK header shape (Appendix A3, AC-10-42/AC-10-43/AC-10-66)
  matched to `stock-rows-page1.json`'s `snapshotId`. Counts (`recordCount`, `zeroPairs`,
  `negativePairs`, `fractionalPairs`) are the REAL db1 aggregate reproduced from the full probed
  balance walk (see "Stock header counts" below) - NOT scaled down to the 10 sample rows, per the
  coder brief ("header counts should be the real db1 numbers from the plan where the plan states
  them"). `negativePairList` carries the FULL real list of 42 negative pairs (the contract is
  uncapped, AC-10-66, so this is the true set, not a truncated excerpt).
- **`stock-rows-page1.json`** - a 10-row SAMPLE of the real positive-pair set (of the true 12,133),
  for shape-testing only - `page`/`pageSize`/`totalPages`/`recordCount` describe the REAL full
  snapshot (`recordCount: 12133`, `totalPages: 13` at `pageSize: 1000`), while the `rows` array
  itself is a hand-picked, real, 10-row excerpt (see "Stock rows" below). This mirrors the header
  fixture's real-numbers rule; do not assume `rows.length == recordCount`.
- **`error-409-pull-not-enabled.json`** / **`error-409-push-active.json`** - AC-10-31 error ladder
  bodies `{code, message, companyCode, entity}`.
- **`snapshot-failed.json`** - a `status: "failed"` snapshot header (AC-10-22/AC-10-64),
  `error.code = SOURCE_PAGE_FAILED` (one of the pinned exhaustive set: `SOURCE_PAGE_FAILED`,
  `ENRICH_FAILED`, `ROW_LIMIT`, `EMPTY_EXTRACT`, `BUILD_ABANDONED`, `COMBINE_RULE_FAILED`).
  `error.message` is the FIXED operator-safe sentence for that code (AC-10-58 M1,
  `pull_gateway_service.GATEWAY_FAILED_MESSAGES`) - a consumer branches on `code`, never on the
  prose, and the stored internal text (which names this deployment's own source host/port) stays
  on the operator header and in `integration_activity`.
- **`error-401-invalid-api-key.json`**, **`error-404-unknown-company.json`**,
  **`error-410-snapshot-expired.json`**, **`error-429-too-many-builds.json`** - the remaining A6
  error-ladder codes with a body shape (A6 defines one uniform shape for every code, so these
  reuse `error-409-*.json`'s shape). Two codes share 404 (`UNKNOWN_COMPANY` / `UNKNOWN_SNAPSHOT`);
  `UNKNOWN_COMPANY` was chosen because it is the one 404 whose `companyCode`/`entity` are always
  known from the request body, avoiding a guess about what a snapshot-scoped 404 would echo for a
  truly-unknown id.

## Product rows - which row is which

| # | `code` | Awkward case | AC |
|---|---|---|---|
| 1 | `ACC-SRT8001` | `Description` starts `****` (real, live db1) | AC-10-67, A10 |
| 2 | `AP4842` | Dimensions in `Description` (`480x420x160MM`) | AC-10-67, A10 |
| 3 | `SRTW1000` | Has `Desc2`, clean single-space raw join | AC-10-67, AC-10-73 |
| 4 | `SRTSH9112-GM` | Has `Desc2`, raw join yields an inner DOUBLE space (`Description` ends with a trailing space before the join) | AC-10-67, AC-10-73 |
| 5 | `ACC-SRT9013` | Base-UOM `ItemUOM` `Price` is `-1.0` -> delivered `list_price: "0.0"` (clamped, R5) | AC-10-67, AC-10-59 |
| 6 | `1/2" ULTRA CIRCULAR` | `Price` is `0.0` (base UOM `PC`, not `UNIT`) -> delivered `"0.0"` | AC-10-67, AC-10-07 |
| 7 | `B2155-BLUE-DIY ` | `ItemCode` has a trailing space -> delivered `code`/`source_ref` TRIMMED | AC-10-67, AC-10-60 |
| 8 | `A611` | Plain row (filler, no quirks) | - |
| 9 | `ACC-SRT1001` | Plain row (filler, no quirks); same `ItemCode` family as row 5, exercising the stock cross-reference below | - |
| 10 | `MWT2800-N/H` | MOCHA-shaped (db2, prefix `MCH`): `ItemBrand` is blank -> `brand_code` key ABSENT; has `Desc2`, clean join | AC-10-67 (Mocha carries no brands) |

All 10 are real `ItemCode`/`Description`/`Desc2`/`ItemGroup`/`ItemBrand`/`BaseUOM` values read
from the probe capture (`itembypage-*.json` for db1, `itembypage-4.json` for db2) and real base-UOM
`ItemUOM` prices from `itemuombypage-*.json` (db1 only - db2's `ItemUOM` page was never probed, see
"Known gap" below).

**Row construction, run through the real model, not hand-typed** (`code`/`source_ref` via
`str(value).strip()`, `description` via the AC-10-73 formula
`trim(if(default(Desc2, "") != "", concat(Description, " ", Desc2), Description))` with `concat`
NOT trimming its args, `list_price` via the AC-10-59 clamp
`if(number(value) <= 0, 0, number(value))` applied to the raw FLOAT source price before the
Decimal field coerces it - which is why a clamped/zero price renders `"0.0"`, never bare `"0"`,
matching AC-10-59's own pinned examples):

```python
from decimal import Decimal
from modules.autocount.canonical.masters import CanonicalProduct

def t_string(v):
    return None if v is None or (isinstance(v, str) and not v.strip()) else str(v).strip()

def join_description(description, desc2):
    joined = description + " " + desc2 if desc2 != "" else description
    return joined.strip()

def clamp(price_float):
    return Decimal(str(0.0 if price_float <= 0 else price_float))

product = CanonicalProduct(
    source_ref=f"{prefix}:{t_string(item_code)}",
    code=t_string(item_code),
    name=t_string(description_raw),
    description=join_description(description_raw, desc2_raw),
    category_code=t_string(item_group),
    brand_code=t_string(item_brand),
    list_price=clamp(raw_price),
    is_active=True,
)
row = product.sink_payload()
```

`uom_code`, `cost_price`, `remark`, `is_discontinued` and `source_doc_no` are never populated, so
`sink_payload()` (which omits any `None` value) drops all five keys from every row - matching
AC-10-74 (uom_code withheld during the check period), the "cost_price/remark never sent" note in
A10, and the fact `CanonicalProduct` declares no `remark`.

**Mocha prefix - resolved.** The coder brief flagged this prefix as needing a plan check: plan
Appendix A9 pins `MCH:BRACD7455C` (not `MOCHA:...`) as the worked example, and AC-10-71 pins the
same literal `MCH:BRACD7455C`. **The Mocha `source_ref` prefix is `MCH`**, used here.

## Stock header counts - reproduced from the full probe capture

The probe directory holds the COMPLETE db1 walk (69 `bal-*.json` pages = all 68,612 balance rows,
12 `itembypage-*.json` pages = all 11,840 items, 12 `itemuombypage-*.json` pages = all 11,852 UOM
rows), so the plan's stock preset (AC-10-40/AC-10-41: group by trimmed `(ItemCode, Location)`,
`base_qty` via base-UOM passthrough or `x UomRate`, `round half_up` to 0 dp, drop `zero`/`negative`)
was reproduced in full against real data:

```
68,612 raw rows -> 68,597 (item, location) groups (multiple raw rows can share a group; BatchNo is
always empty) -> 12,133 positive pairs delivered, 42 negative (listed), 56,422 zero (dropped),
0 fractional (roundedCount 0), 0 rate-unresolved exclusions once UOM matching is casefold+trim
(AC-10-60) - the plan's noted "5 casing-dirt rows" resolve cleanly once matched this way, which is
exactly what AC-10-60 exists to fix.
```

This matches AC-10-84's own pinned expectation (68,612 in -> 12,133 out, 42 negative, 0 fractional)
almost exactly (`roughly 56,400` vs the reproduced 56,422), so `stock-header-ready.json` carries
these REAL numbers rather than numbers scaled to the 10 sample rows, per the coder brief.
`excludedCount`/`excludedRows` are `0`/`[]` here because no rate-unresolved row survived
casefold+trim matching in this reproduction - a genuinely different result set would need its own
fixture; this one documents what "real and clean" looks like.

The **`'MBS '` trailing-space location** the plan calls out as live dirt (AC-10-60(d)) DOES appear
in the raw balance data, but every `(item, MBS)` pair in this probe capture nets to zero after
aggregation - so the trim behaviour is real (verified: raw location field is `"MBS "` with a
trailing space; grouped key is `"MBS"`) but does not surface as a DELIVERED row in this particular
capture. Documented here rather than faked with an invented nonzero balance.

## Stock rows - which row is which

10 real positive `(ItemCode, Location)` pairs, chosen to skip AutoCount's non-physical bucket codes
(`**NEW`, `TRANSPORT`, `HANDLING CHARGES`, etc. - all present in the negative-pair list above, never
useful as a "real row" sample) and to cross-reference the products fixture: row 9
(`ACC-SRT9013` at `PJ-SR`) is the SAME item as product row 5's clamped `-1.0`-price item, and row 1
(`1/2" ULTRA CIRCULAR` at `BRW-BB`, base UOM `PC`, qty 672) is the same item as product row 6.

## `contentHash` - how it was computed (A5's rule)

`sha256` over the concatenation, in row order, of
`json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"` for the EXACT rows shipped in the
matching `*-rows-page1.json` file:

```python
import hashlib, json

def content_hash(rows):
    h = hashlib.sha256()
    for row in rows:
        h.update(json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()
```

`products-header-ready.json`'s `contentHash` is over the 10 rows in `products-rows-page1.json`;
`stock-header-ready.json`'s `contentHash` is over the 10 rows in `stock-rows-page1.json`. Both are
best-effort integrity checks (A5) - the hard guards remain `recordCount`, `complete` and the
`companyCode` echo, and (per the note above) the stock `recordCount` in the header describes the
REAL full snapshot, not the 10 sample rows, so a consumer must not try to recompute the stock hash
against `recordCount` - only against the exact rows served on a given page.

## Known gaps / things NOT fully resolved here

- **Mocha `list_price` is a placeholder, not a probed value.** `probe2/` contains only
  `itembypage-*.json` (db2 item master) - no `itemuombypage` page for db2 was captured, so there is
  no REAL base-UOM price for `MWT2800-N/H`. `"45.0"` is a representative, clearly-round placeholder
  chosen to look like a plausible price, not a measured one. Everything else about that row
  (`ItemCode`, `Description`, `Desc2`, `ItemGroup`, blank `ItemBrand`) is real db2 data.
  `sourcePageSize`/build-duration figures for Mocha in `products-header-building.json` are
  illustrative (A7), not measured for this exact run.
- **`snapshotId`/timestamps are invented UUIDs/ISO strings** (there is no real snapshot yet - S0
  ships no application code), internally consistent within each header/rows pair.
