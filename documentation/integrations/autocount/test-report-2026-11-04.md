# AutoCount write-back test report 2026-11-04

Book: db3 only. Two runs on 4 Nov 2026 with the same suite of 12 cases. Run 1 hit two vendor errors
(findings 5 and 6 below). Run 2 used fixed request bodies (empty dates omitted, complete create body) and
exposes the link and unlink behaviour of the wrapper.

## Run 2 (fixed bodies)

Book: db3. Run tag: 1104b. PASS 6, FAIL 2, SKIPPED 4.

### C01 Create the test PO: PASS

- Expected: test PO created with two SRTKT38SS rows (50 and 10 at HQ)
- Observed: created FXT-1104b-1 with 2 rows

- GET /purchaseorderbydocdate -> 200 (baseline pull docs=3)
- GET /purchaseorderbydocdate -> 200 (FXT-1104b-1 absent)
- POST /NewPurchaseOrder -> 200
  - request: `{"DocNo":"FXT-1104b-1","DocDate":"2026-11-04T00:00:00","CreditorCode":"400-N004","ShippingPO":"F","Details":[{"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","Qty":50,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0},{"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","Qty":10,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0}]}`

### C02 Pull SO then PO into staging: PASS

- Expected: SO days then PO days pulled; the test PO is staged
- Observed: docs_seen=2 staged=2 pushed=2

- GET /purchaseorderbydocdate -> 200 (docs=2 staged=2)

### C03 Link with split: FAIL

- Expected: split: 40 stay at HQ, a new 10 row at BRW-AM linked to SO row 11989
- Observed: mismatch READBACK_MISMATCH
- Action: 5ac8fe02-f2d3-4b8a-ac37-1cfc353978a7

- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12024,"DocNo":"FXT-1104b-1","Details":[{"DtlKey":12025,"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","Qty":40.0,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0},{"DtlKey":0,"ItemCode":"SRTKT38SS","Location":"BRW-AM","UOM":"UNIT","Qty":10.0,"FromDocType":"SO","FromDocNo":"SO389293","FromDocDtlKey":11989}]}`
  - before: `[{"DtlKey":12025,"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","Qty":50.0,"FromSODtlKey":0,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0}]`
  - after: `[{"DtlKey":12025,"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","Qty":40.0,"FromSODtlKey":0,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0},{"DtlKey":12028,"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","Qty":10.0,"FromSODtlKey":11989,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0}]`

### C04 Link same quantity, location moves: SKIPPED

- Expected: same quantity: the row moves to BRW-AM in place, no row added
- Observed: prerequisite C03 did not pass


### C05 Over-link refused: PASS

- Expected: link refused: the SO row is fully covered (QTY_ABOVE_OUTSTANDING)
- Observed: refused QTY_ABOVE_OUTSTANDING
- Action: 65850c17-446f-45af-a0ee-cbd4a6bfd395


### C06 Quantity above the PO row refused: PASS

- Expected: link refused: quantity above the PO row (QTY_ABOVE_FREE)
- Observed: refused QTY_ABOVE_FREE
- Action: 68536086-741c-4269-8288-3498d92b0fe1


### C07 Unlink a linked real row: FAIL

- Expected: unlink of the linked real row 12013 is done
- Observed: mismatch READBACK_MISMATCH
- Action: df5ee6fa-92d4-40d6-ba19-d7fa0abbb237

- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12008,"DocNo":"202602-S0007","Details":[{"DtlKey":12013,"ItemCode":"SRTKS7090","Location":"HQ","UOM":"UNIT","Qty":10.0,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0}]}`
  - before: `[{"DtlKey":12013,"ItemCode":"SRTKS7090","Location":"HQ","UOM":"UNIT","Qty":10.0,"FromSODtlKey":11993,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0}]`
  - after: `[{"DtlKey":12013,"ItemCode":"SRTKS7090","Location":"HQ","UOM":"UNIT","Qty":10.0,"FromSODtlKey":11993,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0}]`

### C08 Relink the real row: SKIPPED

- Expected: relink of row 12013 to SO row 11993 is done and reads back linked
- Observed: prerequisite C07 did not pass


### C09 Stale document refused: PASS

- Expected: stale document refused (DOC_STALE)
- Observed: refused DOC_STALE
- Action: 0baa4f20-6a6e-4fa5-8c39-a6f4e76afc13


### C10 SPO precondition: SKIPPED

- Expected: SPO created pointing at the split row; unlinking that PO row is refused (ROW_ON_SPO)
- Observed: prerequisite C03 did not pass


### C11 SPO unlink then PO unlink: SKIPPED

- Expected: SPO row unlinked, then the PO row unlinked, both done
- Observed: prerequisite C10 did not pass


### C12 Other book refused with no request: PASS

- Expected: a client for another book is refused at construction with no request (WRITE_NOT_ALLOWED)
- Observed: refused WRITE_NOT_ALLOWED, 0 requests

## Run 1 (first attempt, summary)

Run tag 1104a. PASS 4 (C05, C06, C09, C12), FAIL 2 (C01, C07), SKIPPED 6.

- C07, `PUT /EditPurchaseOrderbydockey` echoing PO 202602-S0007 row 12013 exactly as read back
  (`DeliveryDate "0001-01-01T00:00:00"`): status 500, `SqlDateTime overflow. Must be between 1/1/1753
  12:00:00 AM and 12/31/9999 11:59:59 PM.` Nothing changed.
- C01, `POST /NewPurchaseOrder` with DocNo, CreditorCode, DocDate, ShippingPO and two rows
  (ItemCode, Location, UOM, Qty): status 500 `Column 'DisplayTerm' does not allow nulls`. With DisplayTerm
  added: status 500 SQL error 8178 (parameterized query expects `@p1`). With CurrencyCode and CurrencyRate
  added as well: status 200 `Created Successful` (DocNo FXT-PROBE-1, DocKey 12023) but the document reads
  back with `Details []`: both rows were dropped with no error. FXT-PROBE-1 is an empty leftover.

## Observations for AutoCount

Questions refer to the numbering in `write-api-questions-2026-11-04.md`.

1. **Location on transfer (Q9): the vendor overrides the row location.** C03 sent the new split row with
   `Location "BRW-AM"` (the SO row's location) and `FromDocType "SO"`, `FromDocNo "SO389293"`,
   `FromDocDtlKey 11989`. The PUT answered 200 and the row read back `Location "HQ"` with
   `FromSODtlKey 11989`. The edited row kept `HQ`. So the link was accepted but the location we sent was
   not kept. We need rows to keep the location we send, or a documented way to set it.
2. **Unlink is not honoured (Q8): C07 PUT answered 200 but nothing changed.** Row 12013 was sent with
   `FromDocType ""`, `FromDocNo ""`, `FromDocDtlKey 0` and read back unchanged: `FromSODtlKey 11993`,
   `FromSODocList "SO389293"`. Note that linked rows read back `FromDocType ""`, `FromDocNo ""`,
   `FromDocDtlKey 0` already, so those three fields never carry the link on a PO row; the link lives in
   `FromSODtlKey` / `FromSODocList`. How is a PO row unlinked from its SO row on edit (send
   `FromSODtlKey 0`? remove and re-add the row)?
3. **Link on edit of an existing row (Q7): not exercised cleanly.** C03 linked through a NEW row
   (`DtlKey 0`): accepted, read back `FromSODtlKey 11989`, `FromSODocList "SO389293"`, but with the
   location overridden (item 1) and `DeliveryDate "0001-01-01T00:00:00"` although we had sent a valid
   date (the edited row kept 2026-11-04). C04 (link an existing row in place) was SKIPPED because C03
   failed, so Q7 for `DtlKey > 0` is still open.
4. **ShippingPO on create and the SPO link (Q13, Q14a): not observed.** C10 and C11 were SKIPPED (their
   prerequisite C03 failed), so we do not yet know whether `ShippingPO "T"` is honoured on create or how
   an SPO row links to a PO row.
5. **Empty dates (Q21):** run 1, C07, see the summary above. In run 2 omitting the empty date made the
   PUT succeed (status 200). Is omitting the field the right way to leave a date empty?
6. **Create body requirements (Q22):** run 1, C01, see the summary above. In run 2 a body built from the
   creditor's existing PO header (DisplayTerm, CurrencyCode, CurrencyRate) plus complete rows created
   FXT-1104b-1 with both rows (status 200, 2 rows read back). A POST that silently drops rows should return
   an error instead.
7. Vendor remark in the SO GET about `YourPODate` ("need to change to valid date") fits finding 5.
8. Refusals C05, C06 and C09 and the guard C12 are local and sent no write.

## Cross-check of the final book state (read-only GETs)

- PO 202602-S0007 (DocKey 12008) is unchanged: rows 12011, 12013 and 12015 still linked to SO rows
  11990, 11993 and 11996 (`FromSODtlKey`), as before run 1. This matches C07 (unlink had no effect).
- PO FXT-1104b-1 (DocKey 12024, DisplayTerm C.O.D., CurrencyCode CNY): row 12025 qty 40 HQ unlinked;
  row 12026 qty 10 HQ unlinked; row 12028 qty 10 `Location HQ`, `FromSODtlKey 11989`,
  `FromSODocList "SO389293"`, `DeliveryDate "0001-01-01T00:00:00"`. This matches the C03 after rows.
  The PO total of 60 is conserved.
- SO389293 rows 11989 and 11993 are unchanged (qty 10, BRW-AM).
- FXT-PROBE-1 (DocKey 12023) exists with no rows. No SPO was created.
- Test documents left in db3: FXT-PROBE-1 (empty) and FXT-1104b-1 (three rows). They can be deleted.
