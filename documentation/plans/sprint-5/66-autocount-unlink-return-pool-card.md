# 66 - Unlink returns the quantity to the pool (behaviour card, lane UNLINK-RETURN-POOL)

Status: answers settled 17 Nov (owner Q1/Q2/Q3/Q5 + unit price, crew Q4); built. Contract: `55-autocount-write-link-contract.md`
section 4.2 "Return to the pool".

## Owner's ask (17 Nov)
When a PO line is unlinked from an SO line, the unlinked quantity goes back to the pool: merge it into a free pool
line on the same PO when one exists, otherwise keep the line and move it to the pool location.

## Code before this lane (main @ f42d1e17)
- Entry: `routers/pull_v1.py:645` -> `write_back/service.py:430 unlink` -> operation `unlink_row` (`write_back/operations.py:127`).
- `operations.py:798 _merge_target` (plan 62 D7): first free row with the same ItemCode, UOM, **Location**, UnitPrice,
  DeliveryDate; merge = one PUT (`_merge_run`, `primitives.py:314 unlink_merge`).
- Else `_replace_run`: one PUT ["D" + new unlinked row], then the move PUT to `snap["moveTo"]` = the row's CURRENT
  location (`operations.py:892`).

## Answers
- Q1 (owner + crew): the pool is the one the project location is configured to draw from - CRM
  `warehouses.pool_warehouse_id` ("Draws stock from" on the warehouse form; BRW-BB / BRW-NTC / BRW-IB draw from
  BRW). It is NOT stored in SS: the CRM sends it on the unlink call as `poolLocation` (exact code); absent / blank =
  today's behaviour. The CRM slice that sends it is crew's (separate lane).
- Q2 (owner): merge matches ItemCode + UOM only. Unit price ("also can ignore") and delivery date are not compared.
- Q3 (owner): the delivery date is the SO's and irrelevant once unlinked. Merged row keeps the pool row's own price and
  date (only Qty goes up); a moved row keeps the unlinked row's values as today.
- Q4 (crew, CRM traced): "Change to another PO" = unlink + link (CRM `po_link_reserve.py _plan_change`), never relink,
  so it rides the same unlink. Partly received rows: received part stays, the rest goes to the pool.
- Q5 (owner a): "Unlinked. Qty returned to <pool>." / "Unlinked, but the Location could not be changed to <pool>."
  SS answers `detail` (the row now holding the qty) so the CRM can word it.

## Rule (built)
With `poolLocation`:
1. First free row in row order AT `poolLocation` (exact), same ItemCode + UOM, not linked, no SPO row, no known receipt
   > 0, no unresolved link op -> ONE PUT [linked row "D", pool row Qty += freed qty].
2. Else today's replace PUT, then the move PUT sends `Location = poolLocation` (price/date restore as today). A failed
   move = `done` + `LOCATION_NOT_MOVED`.
3. Partly received: cut keeps the received qty in place; the new row with the rest is moved to `poolLocation`.
Without `poolLocation`: plan 62 D7 unchanged, answer body unchanged (no `detail`).
Relink ignores it. Retry rules unchanged (refusal releases the key; unknown outcome -> Resume reads the PO first;
Resume of a pending replace moves to the snapshot's pool `moveTo`).

## Examples (masked)
| # | PO lines before | Unlink (pool BRW) | After |
|---|---|---|---|
| 1 | L1 ITEM-A 10 BRW-BB linked; L2 ITEM-A 4 BRW free @ other price/date | L1 | L1 gone; L2 ITEM-A 14 BRW free, own price/date |
| 2 | L1 ITEM-A 10 HQ linked; no other ITEM-A line | L1 | new L3 ITEM-A 10 BRW free |
| 3 | L1 ITEM-A 10 HQ linked; L2 ITEM-A 4 BRW linked to another SO | L1 | L2 untouched; new L3 ITEM-A 10 BRW free |
| 4 | L1 ITEM-A 10 HQ linked; L2 ITEM-A 4 BRW-BB free | L1 | BRW-BB is not BRW: new L3 ITEM-A 10 BRW free |
| 5 | L1 ITEM-A 10 HQ linked, 3 received | L1 | L1 cut to 3 HQ; new L3 ITEM-A 7 BRW free |

## Tests
`service_backend/tests/test_autocount_write_back_unlink_pool.py` (24). Kill tests: price back in the match, pool
location not required, no move to pool, UOM dropped, `detail` always on, param ignored - each caught.
