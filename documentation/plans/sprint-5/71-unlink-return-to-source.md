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
carries one code: `RETURN_ROW_NOT_FOUND`, `RETURN_ROW_LINKED`, `RETURN_ROW_ITEM_MISMATCH`, `RETURN_ROW_CLOSED`,
`RETURN_ROW_ON_SPO`, `RETURN_ROW_BUSY`; a partly received TIED row gives `RETURN_PARTLY_RECEIVED` (today's cut +
add, the received part stays; folding the rest into the source row is a different PUT shape, not built).
With `returnToDtlKey` the answer carries `detail` (the row now holding the qty). Absent / null = today's request,
idempotency hash and answer body. Relink ignores it.

## Read-back (coordination with PO-LINK-STUCK-RECONCILE)
The merged source row is an UNTIED row, so AutoCount does not derive its location / delivery date / note from an
SO line (the sorento-crm#2603 READBACK_MISMATCH case is a newly TIED row). The existing exact verifier applies
unchanged; no read-back rule is added or relaxed here. The tied-row read-back fix stays with that lane.

## Retry
Unchanged from plan 62 / 66: AutoCount refusal = nothing landed, key released; timeout / 5xx = pending, Resume reads
the PO first (`_resume_merge` keys on the snapshot's `mergeInto`, which is the source row).

## Examples (masked)
| # | PO lines before | Unlink L1, returnTo L2, pool BRW | After | warnings |
|---|---|---|---|---|
| 1 | L1 ITEM-A 4 BR1 tied; L2 ITEM-A 4 HQ free | | L1 gone; L2 ITEM-A 8 HQ, own price/date | - |
| 2 | L1 tied; L2 tied to another SO | | L1 gone; new ITEM-A 4 BRW free | RETURN_ROW_LINKED |
| 3 | L1 tied; L2 ITEM-B | | new ITEM-A 4 BRW free | RETURN_ROW_ITEM_MISMATCH |
| 4 | L1 tied; L2 ITEM-A 4 HQ, 4 received | | new ITEM-A 4 BRW free | RETURN_ROW_CLOSED |
| 5 | L1 tied, 1 received; L2 free | | L1 cut to 1; new ITEM-A 3 BRW | RETURN_PARTLY_RECEIVED |

## Tests
`service_backend/tests/test_autocount_write_back_unlink_return_to_source.py` (25). Red at 159ecaaf (23 failed),
green at 4865315e. Live db3 (AutoCount TEST book) check: not runnable from the cloud sandbox (no db3 access);
recommended before the CRM turns it on: merge into an HQ source row at another price keeps its own price/date.
