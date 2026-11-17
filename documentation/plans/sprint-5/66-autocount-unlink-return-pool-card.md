# 66 - Unlink returns the quantity to the pool (behaviour card, lane UNLINK-RETURN-POOL)

Status: card filed as a crew ask; no code until the owner's answers come back.

## Owner's ask (17 Nov)
When a PO line is unlinked from an SO line, the unlinked quantity goes back to the pool:
merge it into a free pool line on the same PO when one exists, otherwise keep the line and move it to the pool location.

## Today's code (main @ f42d1e17)
- Entry: `write_back/service.py:430 unlink` -> operation `unlink_row` (`write_back/operations.py:127`).
- Plan: `operations.py:767 _guards` -> `operations.py:798 _merge_target` (plan 62 D7) picks the FIRST free row with the
  same ItemCode, UOM, **Location**, UnitPrice and DeliveryDate (not linked, no SPO row, no known receipt > 0, no
  unresolved link op).
- Found: `operations.py:978 _merge_run` = ONE PUT [linked row "D", free row Qty += unlinked qty] (`primitives.py:314 unlink_merge`).
- Not found: `operations.py:996 _replace_run` = ONE PUT [row "D", new unlinked row], then `_link_move` / `_move`
  (`operations.py:1045`) puts the new row back at `snap["moveTo"]`, which for an unlink is the row's CURRENT location
  (`operations.py:892`: "unlink / SPO: the line stays where it was"). AutoCount forces HQ on the new row, so this move
  PUT is what lands the location.
- Relink (`relink_row`, PO row moves to another SO row) never frees quantity: unchanged.

## Proposed rule
1. Merge: the free-row search drops "same Location" and instead requires the free row to sit at a pool location.
   Every other D7 condition stays (same ItemCode + UOM + UnitPrice + DeliveryDate, not linked, no SPO, no receipt,
   no unresolved op). First match in row order wins.
2. No pool row to merge into: today's replace PUT, then the move PUT sends `Location = <pool location>` instead of the
   old location (price and delivery date restored as today).
3. Partial-receipt unlink (row partly received, split): the cut row keeps the received qty at its current location;
   the new unlinked row of the remaining qty goes to the pool location (merge not applied, as today).
4. Pool location = a per-company setting on the AutoCount company screen ("Pool location", one exact Location code,
   empty = today's behaviour). Writes stay behind the existing write switch.

## Examples (masked)
| # | PO lines before | Unlink | After |
|---|---|---|---|
| 1 | L1 ITEM-A 10 HQ linked SO-1/r1 @ 5.00 dd 20/11; L2 ITEM-A 4 BRW free @ 5.00 dd 20/11 | L1 | L1 gone; L2 ITEM-A 14 BRW free |
| 2 | L1 ITEM-A 10 HQ linked; no other ITEM-A line | L1 | L1 replaced by L3 ITEM-A 10 **BRW** free (price/date kept) |
| 3 | L1 ITEM-A 10 HQ linked; L2 ITEM-A 4 BRW **linked to SO-2** | L1 | L2 untouched; L1 -> L3 ITEM-A 10 BRW free |
| 4 | L1 ITEM-A 10 HQ linked @ 5.00; L2 ITEM-A 4 BRW free @ **5.50** | L1 | price differs: no merge; L3 ITEM-A 10 BRW free @ 5.00 (two BRW lines) |
| 5 | L1 ITEM-A 10 HQ linked, 3 received | L1 | L1 cut to 3 HQ (received part stays); new L3 ITEM-A 7 BRW free (see Q4) |

## Edge cases
- The linked row already sits at the pool location: no move needed (move PUT skipped when nothing drifted, as today).
- Free pool row has FOC, or a known receipt > 0: skipped as a merge target (today's rule), falls to rule 2.
- Pool row on an SPO: skipped (today's rule).
- Move PUT fails after the replace landed: unlink stays done with warning `LOCATION_NOT_MOVED` (today's rule); the
  screen says the line was unlinked but its Location could not be changed.
- AutoCount refuses: key released, Try again (unchanged retry rule). Unknown outcome: Resume reads the PO first.

## Questions
1. What is a pool location? (a) one exact Location code per company set on the company screen, empty = off;
   (b) a list of codes; (c) hard-coded BRW. Recommendation (a), because the owner wants settings on a screen and BRW
   does not cover BRW-BB / BRW-NTC unless the owner says so.
2. Match rule for "the same line": (a) item + UOM + unit price + delivery date (today's D7, minus location);
   (b) item + UOM only (merged line takes the pool line's price/date). Recommendation (a): merging two prices or two
   dates would silently change a PO value; when they differ the line still goes to the pool location (rule 2).
3. Delivery date of the moved line (rule 2): (a) keep the unlinked line's own date (today's restore);
   (b) the PO header date. Recommendation (a).
4. Partial-receipt unlink and "Change to another PO": (a) partial: received part stays, remaining part goes to pool;
   Change-to-another-PO = unlink on the old PO + link on the new, so the old PO's line returns to the pool by this rule;
   (b) pool rule only for whole-row unlinks. Recommendation (a).
5. What the CRM screen / toast says: (a) "Unlinked. Qty returned to BRW." (merge or move alike), with the
   `LOCATION_NOT_MOVED` case reading "Unlinked, but the Location could not be changed to BRW."; (b) no wording change.
   Recommendation (a); SS returns `detail` (the free row) + `mergedInto` so CRM can word it (CRM text is the CRM lane's).
