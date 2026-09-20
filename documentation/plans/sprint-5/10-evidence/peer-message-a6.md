# Message for the Sorento `autocount` peer session - Appendix A additive changes since 2026-09-19

Everything below is ADDITIVE to the contract you already implemented against. Nothing here changes
a field you have already coded - these are things the contract text omitted or under-specified
that a fresh read of the live gateway code turned up during the Foundryx-side S6 docs pass
(2026-09-20). Full detail lives in `documentation/plans/sprint-5/10-autocount-pull-review.md`
Appendix A (A6/A7/A5) on the `sprint-5/10-autocount-pull-review` branch.

## 1. Six more error codes on the gateway (Appendix A6)

The error-ladder table only listed the "business" codes (`INVALID_API_KEY`, `SERVICE_NOT_ENABLED`,
`COMPANY_NOT_ALLOWED`, `UNKNOWN_COMPANY`, `PULL_NOT_ENABLED`, `PUSH_ACTIVE`, `SNAPSHOT_EXPIRED`,
`UNKNOWN_SNAPSHOT`, `TOO_MANY_BUILDS`) plus the six `status: "failed"` codes. The S4 security
review round added six more codes to the SAME flat `{code,message,companyCode,entity}` envelope
that were never folded back into the table:

| Status | code | When |
|---|---|---|
| 429 | `TOO_MANY_REQUESTS` | Per-IP throttle (before your key even resolves - same bucket a bad key trips) OR a per-key request budget counted on every authenticated call. Honour `Retry-After` on both, same as `TOO_MANY_BUILDS` |
| 409 | `AMBIGUOUS_COMPANY` | More than one company in the tenant shares the `companyCode` you sent - we refuse rather than guessing which one you meant |
| 422 | `INVALID_REQUEST` | Malformed request: `companyCode`/`entity` missing on `POST /snapshots`, or `page` outside `1..1000000` on the rows route |
| 422 | `UNKNOWN_ENTITY` | `entity` is not `products` or `stock_balances` |
| 413 | `PAYLOAD_TOO_LARGE` | Request body over 16 KB |
| 500 | `INTERNAL` | Last-resort net for an unanticipated exception; body never carries exception text/class/stack |

If your error switch is not exhaustive on the `code` field, these six will currently fall into
whatever your default branch does - worth checking now rather than in production.

## 2. `Cache-Control: no-store` on every gateway response

Success or error, every response from `/api/v1/autocount/*` carries `Cache-Control: no-store`.
Not a behaviour change on our side (it shipped with S4), just previously undocumented in the
contract - relevant only if anything on your side (a CDN, a caching HTTP client) might otherwise
cache this surface.

## 3. `page` has a hard upper bound: 1,000,000

`GET /snapshots/{id}/rows?page=N` REJECTS `N` above 1,000,000 with 422 `INVALID_REQUEST` rather
than clamping it. `pageSize` is the only paging field that clamps (to 1000, silently, as already
documented) - `page` past a legitimate `totalPages` still returns an empty `rows` array as before;
this bound only matters if you ever construct a page number outside a normal walk.

## 4. Stock `excludedRows` shape - confirm you read the CORRECTED example

The contract's worked example for a stock snapshot's `excludedRows` entry was wrong when first
written (it showed a `"uom": "ctn"` key and `"qty"` instead of `"measure"`, with no mechanism to
produce either). The corrected, code-verified shape is exactly:

```json
{"item_code": "SRT-99", "location_code": "HQ", "measure": 0, "reason": "uom_rate_unresolved"}
```

i.e. `{<groupBy columns>, measure, reason}` - the row's group-by columns (`item_code`/
`location_code` for stock) plus the raw value of the combine step's ONE designated measure column,
plus the exclusion reason. There is no mechanism today for a third, entity-specific diagnostic
column (e.g. `uom`) to ride along - if that turns out to matter for your review page, tell us and
we'll size adding it.

One more wrinkle: a stock snapshot's `excludedRows` mixes two STAGES today, but they read
IDENTICALLY on the wire. A combine-stage exclusion (`uom_rate_unresolved`, the require-rule
example above) and a mapping-stage exclusion (a row that survived combine intact but then failed a
canonical constraint, e.g. `qty >= 0`) both normalise to the SAME `{<groupBy cols>, measure,
reason: "mapping_failed", message}` shape - never the generic per-record `{source_ref, code,
reason, message}` shape a non-combine task (i.e. every product task) uses. So your
`excludedNonzeroCount` guard can read every stock exclusion uniformly without branching on which
stage produced it. `sourcePageSize` is also confirmed present on every entity's header (products
included), not stock-only as an earlier contract draft implied by omission.

## 5. Nothing else changed

Row shapes (A4), immutability/TTL/completeness rules (A5), sizing guidance (A7), and the
manual-upload parity matrix (A10) are all unchanged from what you already implemented against.
This message is scoped to the error ladder + two small header/paging facts above.

Let us know if any of the six new codes need special handling on your side, or if the corrected
stock `excludedRows` shape changes anything about your review-page rendering.
