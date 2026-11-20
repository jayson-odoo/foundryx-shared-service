# 71 - Unlink returns the quantity to its source PO row (behaviour card, lane UNLINK-RETURN-TO-SOURCE-SS)

Status: built. SS half of the CRM lane UNLINK-RETURN-TO-SOURCE (sorento-crm#2607). Contract:
`55-autocount-write-link-contract.md` section 4.2 "Return to the source row". UAC:
`71-unlink-return-to-source-acceptance-criteria.md`. Field and warning names are provisional until the CRM's
"SS contract" (sorento-crm#2607) is read from this lane; a rename is a one-place change per name.

## Owner's ask (20 Nov ~10:20)
"the unlink ... should return to whatever line it linked from, for example this case is HQ". Plan 66 sends the
freed qty to the pool location; the owner wants it back on the PO row it was linked FROM (here an HQ row).

## Code before this lane (main @ 7b85164a)
- `routers/pull_v1.py unlink_po_row` -> `write_back/service.py unlink` -> operation `unlink_row`.
- `operations.py _merge_target` picks the merge row (plan 62 D7 same location + price + date; plan 66 pool row on
  item + unit); `_merge_run` = ONE PUT [tied row "D", merge row Qty += n] via `primitives.unlink_merge`, read back
  by `payloads.verify_unlink_merge` (merge row Qty exactly old + n, tied row gone, no new row, no drift elsewhere).
- No merge row: `_replace_run` (replace PUT, then the move PUT to the pool).

## Rule (built)
`po-links/unlink` takes optional `returnToDtlKey` (`return_to_dtl_key` on `unlink_row`). When the row is usable,
it IS the merge row (`_return_refusal`, then the existing `_merge_run`, no new PUT shape):
- on this PO (it is in the fresh read), same ItemCode + UOM;
- not tied to an SO row (and not the tied row itself), no other `FromDocType`;
- no SPO row points at it, no unresolved link operation covers it (plan 65 R1);
- open = not fully received. A partly received or unknown receipt still takes the qty (only its Qty goes up).
  This differs from the pool rule (pool rows need no receipt): the source row is the one the stock came from and
  the owner asked for it by name; raising Qty on a partly received row is an ordinary AutoCount edit.
The source row keeps its own Location, UnitPrice and DeliveryDate (location is NOT matched: that is the point).
Not usable: the plan 66 pool path (or plan 62 D7 without `poolLocation`) runs exactly as before and `warnings`
carries the CRM SS contract's ONE code `RETURN_SOURCE_NOT_OPEN` (sorento-crm#2607; the precise reason - not found,
tied, other item/unit, SPO row, busy, fully received, or the TIED row partly received (today's cut + add) - is
logged, not answered). Merged back: `replacedLines` [] and `returnedTo` {fromDtlKey, toDtlKey, qty, location}
(stored, so a replay and a Resume answer it too). With `returnToDtlKey` the answer carries `detail` (the row now
holding the qty). Absent / null = today's request, idempotency hash and answer body. Relink ignores it.

## Read-back (coordination with PO-LINK-STUCK-RECONCILE)
Contract (exact): `verify_unlink_merge` now also compares the raised row's Location / DeliveryDate / UnitPrice /
Discount / Description / link to ITS OWN before-image (`payloads.merge_row_drift`, every unlink merge: only Qty may
change), and `_resume_merge` does the same against the snapshot's `returnBefore`. Drift = needs attention. This
closes the review round 1 open risk below. The tied-row read-back fix (#2603) stays with PO-LINK-STUCK-RECONCILE.

## Retry
Unchanged from plan 62 / 66: AutoCount refusal = nothing landed, key released; timeout / 5xx = pending, Resume reads
the PO first (`_resume_merge` keys on the snapshot's `mergeInto`, which is the source row).

## Examples (masked)
| # | PO lines before | Unlink L1, returnTo L2, pool BRW | After | warnings |
|---|---|---|---|---|
| 1 | L1 ITEM-A 4 BR1 tied; L2 ITEM-A 4 HQ free | | L1 gone; L2 ITEM-A 8 HQ, own price/date | - |
| 2 | L1 tied; L2 tied to another SO | | L1 gone; new ITEM-A 4 BRW free | RETURN_SOURCE_NOT_OPEN |
| 3 | L1 tied; L2 ITEM-B | | new ITEM-A 4 BRW free | RETURN_SOURCE_NOT_OPEN |
| 4 | L1 tied; L2 ITEM-A 4 HQ, 4 received | | new ITEM-A 4 BRW free | RETURN_SOURCE_NOT_OPEN |
| 5 | L1 tied, 1 received; L2 free | | L1 cut to 1; new ITEM-A 3 BRW | RETURN_SOURCE_NOT_OPEN |

## Review round 1 (reviewer seat, kill test)
- Fixed: tests now pin the busy-row rule (`RETURN_ROW_BUSY`), an unknown receipt still taking the qty, and relink
  never picking up a `RETURN_*` warning. The `RETURN_*` warning is kept in the snapshot (`returnWarnings`) so a
  Resume answer still says why the source row was not used.
- Open risk for the db3 check: `verify_unlink_merge` checks the merged row's Qty, not its Location / price / date
  (it is a skip row for the drift check), so AutoCount re-deriving price or date on a partly received source row
  would still read `done`. Before the CRM turns the field on, on db3: merge into (a) a free source row at another
  price and date, (b) a partly received source row at another price and date; both keep Location, price, date.
- Backlog candidate (pre-existing, pool merges have it too): `row_needs_attention` does not count another pending
  operation's `mergeInto` row as covered, so a second unlink growing that row makes the first one's Resume read
  "needs attention" (a false alarm, nothing lost).

## Tests
`service_backend/tests/test_autocount_write_back_unlink_return_to_source.py` (28). Red at 159ecaaf (23 failed),
green at 4865315e. Live db3 (AutoCount TEST book) check: not runnable from the cloud sandbox (no db3 access);
recommended before the CRM turns it on: merge into an HQ source row at another price keeps its own price/date.
