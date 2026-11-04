# AutoCount write-back test report 2026-11-04

Book: db3 only. Two runs on 4 Nov 2026 with the same suite of 12 cases. Run 1 hit two vendor errors
(findings 5 and 6 below). Run 2 used fixed request bodies (empty dates omitted, complete create body) and
exposes the link and unlink behaviour of the wrapper.

## Documents created or edited in db3

Every write request our runs sent to db3, one row per document per request, oldest first. Times are MYT: the
action-log time (`ac_write_action`) where one exists, otherwise approximate, cross-checked against the vendor's
`CreatedTimeStamp` / `LastModified` (all written by user FOUNDRYX). Requests refused locally before any call
(C05, C06, C09, C12 and the earlier refused links) sent nothing and are not listed. Nothing was ever deleted or
cancelled. Every later run appends to this table.

| Doc no | Type | DocKey | Test id | Request time (MYT) | Method + path | Status | Effect | Final state now (DtlKey, item, qty, location, FromSODtlKey) | Mark |
|---|---|---|---|---|---|---|---|---|---|
| FXT-1104a-1 | PO | none | C01 (run 1) | about 15:04 | POST /NewPurchaseOrder | 500 | refused (DisplayTerm null) | not created | FAILED CREATE |
| 202602-S0007 | PO | 12008 | C07 (run 1) | 15:04:19 | PUT /EditPurchaseOrderbydockey | 500 | refused (SqlDateTime overflow) | see last row of this document | EXISTING DOC |
| FXT-1104a-1 | PO | none | probe (3 sends, 15:04 to 15:05) | about 15:05 | POST /NewPurchaseOrder | 500 | refused (DisplayTerm null) | not created | PROBE, FAILED CREATE |
| FXT-PROBE-1 | PO | none | probe (2 sends) | about 15:05 | POST /NewPurchaseOrder | 500 | refused (SQL error 8178) | not created | PROBE, FAILED CREATE |
| FXT-PROBE-1 | PO | 12023 | probe | 15:05:15 (vendor CreatedTimeStamp) | POST /NewPurchaseOrder | 200 | rows dropped (document created with no rows) | no rows; creditor code 400-N004, creditor name blank | PROBE, FAILED CREATE |
| FXT-1104b-1 | PO | 12024 | C01 (run 2) | 15:11:16 | POST /NewPurchaseOrder | 200 | created | see next row | TEST DOC |
| FXT-1104b-1 | PO | 12024 | C03 (run 2) | 15:11:17 | PUT /EditPurchaseOrderbydockey | 200 | applied (split and link; new row kept HQ, not BRW-AM) | | TEST DOC |
| 202602-S0007 | PO | 12008 | C07 (run 2) | 15:11:23 | PUT /EditPurchaseOrderbydockey | 200 | no change (unlink ignored) | | EXISTING DOC |
| 202602-S0007 | PO | 12008 | P1 | about 15:13 | PUT /EditPurchaseOrderbydockey | 200 | no change (unlink ignored) | | EXISTING DOC |
| 202602-S0007 | PO | 12008 | P1b | 15:13:25 (vendor LastModified) | PUT /EditPurchaseOrderbydockey | 200 | no change (unlink ignored) | 12009 SRTKS7090 1 BRW-AM 0; 12011 SRTKS7090 10 HQ 11990; 12013 SRTKS7090 10 HQ 11993; 12015 SRTKS7090 9 HQ 11996 | EXISTING DOC |
| FXT-1104b-1 | PO | 12024 | P2 | about 15:14 | PUT /EditPurchaseOrderbydockey | 200 | applied for location only (row 12026 moved to BRW-AM); link ignored | | TEST DOC |
| FXT-1104b-S1 | SPO | none | P3 | about 15:14 | POST /NewPurchaseOrder | 400 | refused (FromDocType PO not valid) | not created | PROBE, FAILED CREATE |
| FXT-1104b-1 | PO | 12024 | P4 | 15:14:46 (vendor LastModified) | PUT /EditPurchaseOrderbydockey | 200 | applied (row 12028 moved to BRW-AM, link kept) | 12025 SRTKT38SS 40 HQ 0; 12026 SRTKT38SS 10 BRW-AM 0; 12028 SRTKT38SS 10 BRW-AM 11989 | TEST DOC |

| FXT-1104b-1 | PO | 12024 | P5.1 (FullTransferOption "T") | 15:30:57 | PUT /EditPurchaseOrderbydockey | 200 | no change (link on existing row 12026 ignored) | | TEST DOC |
| FXT-1104b-1 | PO | 12024 | P5.2 ("T" + FullTransferFromDocList "SO389293") | 15:31:01 | PUT /EditPurchaseOrderbydockey | 200 | no change (link ignored) | | TEST DOC |
| FXT-1104b-1 | PO | 12024 | P5.3 ("F") | 15:31:04 | PUT /EditPurchaseOrderbydockey | 200 | no change (link ignored) | | TEST DOC |
| FXT-1104b-1 | PO | 12024 | P6 (replace row) | 15:31:15 | PUT /EditPurchaseOrderbydockey | 200 | applied: new row added and linked at HQ; omitted row 12026 kept | 12025 SRTKT38SS 40 HQ 0; 12026 SRTKT38SS 10 BRW-AM 0; 12028 SRTKT38SS 10 BRW-AM 11989; 12031 SRTKT38SS 10 HQ 11992 (total 70) | TEST DOC |
| FXT-1104b-1 | PO | 12024 | P8 (unlink via FromSODtlKey 0 and FromSODocList empty, From* keys absent) | 15:43:51 | PUT /EditPurchaseOrderbydockey | 200 | no change (row 12031 stays linked to 11992) | | TEST DOC |
| FXT-1104b-1 | PO | 12024 | P7a (FromSODtlKey 11992 + FromSODocList, From* keys absent) | 15:43:54 | PUT /EditPurchaseOrderbydockey | 200 | no change (row 12026 stays unlinked) | | TEST DOC |
| FXT-1104b-1 | PO | 12024 | P7b (FromDocDtlKey 11992 + FromSODocList, others absent) | 15:43:56 | PUT /EditPurchaseOrderbydockey | 200 | no change (row 12026 stays unlinked) | | TEST DOC |
| FXT-1104b-1 | PO | 12024 | P7c (FromSODtlKey 11992 only) | 15:43:58 | PUT /EditPurchaseOrderbydockey | 200 | no change (row 12026 stays unlinked) | | TEST DOC |
| FXT-1104b-1 | PO | 12024 | P8b (unlink: FromDocDtlKey 11989 + FromSODocList + FromSODtlKey 0) | 15:44:33 | PUT /EditPurchaseOrderbydockey | 200 | no change (row 12028 stays linked to 11989) | | TEST DOC |
| FXT-1104b-1 | PO | 12024 | P8c (unlink: as P8b plus FromDocType SO and FromDocNo) | 15:44:34 | PUT /EditPurchaseOrderbydockey | 200 | no change (row 12028 stays linked to 11989) | | TEST DOC |
| FXT-1104b-1 | PO | 12024 | P8d (unlink: FromDocDtlKey 11989 + FromSODocList only) | 15:44:35 | PUT /EditPurchaseOrderbydockey | 200 | no change (row 12028 stays linked to 11989) | | TEST DOC |
Notes:

- FXT-PROBE-1 shows a blank creditor name because our probe body sent only `CreditorCode` (400-N004) and no
  `CreditorName`; the vendor did not fill it in from the creditor. The documents created with a header copied
  from an existing PO (FXT-1104b-1) carry the creditor name.
- Vendor cross-check of today's documents: FXT-PROBE-1 created 15:05:15.107; FXT-1104b-1 created 15:11:16.477,
  last modified 15:14:46.297; 202602-S0007 (created by AutoCount earlier, 13:39:22.89) last modified 15:13:25.337.
- Left in place as test evidence: FXT-PROBE-1 and FXT-1104b-1. No SPO exists.

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

## Run 3 probes (P1-P3)

Direct calls to db3 only, outside the suite, with the same body builders as the suite (header fields as
read back, only the touched row, no date below 1753). Header fields not shown are the creditor's header
as read back (DocKey, DocNo, DocDate, CreditorCode, DisplayTerm C.O.D., CurrencyCode CNY, CurrencyRate 0.6,
blank remarks).

### P1 Unlink with the link's own fields (Q8): not honoured

- Before, PO 202602-S0007 row 12013: `Qty 10, Location HQ, FromSODtlKey 11993, FromSODocList "SO389293",
  FromDocType "", FromDocNo "", FromDocDtlKey 0, DeliveryDate "0001-01-01T00:00:00"`.
- PUT `/EditPurchaseOrderbydockey` -> status 200, `DocNo=202602-S0007 ,DocKey=12008 ... Done Edit.`
  - request row: `{"DtlKey":12013,"ItemCode":"SRTKS7090","Location":"HQ","UOM":"UNIT","UserUOM":"UNIT","Qty":10.0,"FOCQty":0.0,"UnitPrice":0.0,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FromSODtlKey":0,"FromSODocList":"","FullTransferOption":" ","FullTransferFromDocList":""}`
- After: unchanged, `FromSODtlKey 11993, FromSODocList "SO389293"`.
- P1b, the same row with `FromDocType "SO"`, `FromDocNo ""`, `FromDocDtlKey 0` (and `FromSODtlKey 0`,
  `FromSODocList ""`): status 200 `Done Edit.`; After: unchanged, `FromSODtlKey 11993`.

### P2 Link on edit of an existing row (Q7): accepted, link ignored, location kept

- Before, FXT-1104b-1 (DocKey 12024) row 12026: `Qty 10, Location HQ, FromSODtlKey 0, FromDocType ""`.
- PUT `/EditPurchaseOrderbydockey` -> status 200, `DocNo=FXT-1104b-1 ,DocKey=12024 ... Done Edit.`
  - request row: `{"DtlKey":12026,"ItemCode":"SRTKT38SS","Location":"BRW-AM","UOM":"UNIT","UserUOM":"UNIT","Qty":10.0,"FOCQty":0.0,"UnitPrice":1.0,"DeliveryDate":"2026-11-04T00:00:00","FromDocType":"SO","FromDocNo":"SO389293","FromDocDtlKey":11992,"FullTransferOption":" ","FullTransferFromDocList":""}`
- After: row 12026 `Location BRW-AM` (kept), `FromSODtlKey 0`, `FromSODocList ""`, `FromDocType ""`: NOT linked.
  Rows 12025 (40 HQ, unlinked) and 12028 (10 HQ, linked to 11989) unchanged.

### P3 SPO create (Q13, Q14a): refused

- POST `/NewPurchaseOrder` with `ShippingPO "T"`, DocNo FXT-1104b-S1, one row
  `{"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","UserUOM":"UNIT","Qty":10,"FOCQty":0,"UnitPrice":1.0,"DeliveryDate":"2026-11-04T00:00:00","FromDocType":"PO","FromDocNo":"FXT-1104b-1","FromDocDtlKey":12028,"FullTransferOption":" ","FullTransferFromDocList":""}`
  -> status 400, `{"Message": "PO is not valid value to FromDocType."}`.
- After: FXT-1104b-S1 does not exist; FXT-1104b-1 unchanged. Not retried with another value, as agreed.

### P4 Location of an already-linked row: moves, link kept

- Before, FXT-1104b-1 (DocKey 12024) row 12028 (created by the C03 split): `Qty 10, Location HQ,
  FromSODtlKey 11989, FromSODocList "SO389293", FromDocType "", FromDocNo "", FromDocDtlKey 0`.
- PUT `/EditPurchaseOrderbydockey` -> status 200, `DocNo=FXT-1104b-1 ,DocKey=12024 ... Done Edit.`
  - request row (the row as read back, only `Location` changed, the 0001 date omitted):
    `{"DtlKey":12028,"ItemCode":"SRTKT38SS","Location":"BRW-AM","UOM":"UNIT","UserUOM":"UNIT","Qty":10.0,"FOCQty":0.0,"UnitPrice":0.0,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""}`
- After: row 12028 `Location BRW-AM`, `FromSODtlKey 11989`, `FromSODocList "SO389293"`: the location moved
  and the link was kept. Rows 12025 and 12026 unchanged.

### P5 Link on edit of an existing row, varying FullTransferOption (Q7): still not linked

What the vendor material shows for `FullTransferOption` / `FullTransferFromDocList`: the vendor test-records
file (about 400 rows across QT, SO, PO samples) shows only `FullTransferOption " "` and
`FullTransferFromDocList ""`, also on the transferred rows (QT-to-SO and SO-to-PO samples); the PO sample is
a POST of new rows with `FromDocType`, `FromDocNo`, `FromDocDtlKey` amended ("just amend the From* fields for
triggering transfer"). Every GET we hold (db3 and db1 PO, SO, QT) carries only `" "` / `""` (400 rows
`" "`, 327 `""`). No non-blank value is documented anywhere, and no sample transfers on an existing row.
So the three values below are the AutoCount-typical candidates, each with its reason.

- Before: SO389293 row 11992 unlinked (no PO row has `FromSODtlKey 11992`; PO 202602-S0007 holds 11990,
  11993, 11996 and FXT-1104b-1 holds 11989). Row 12026 of FXT-1104b-1: `Qty 10, Location BRW-AM,
  FromSODtlKey 0, FromSODocList "", FromDocType ""`.
- Request row (all three tries): row 12026 as read back with `FromDocType "SO"`, `FromDocNo "SO389293"`,
  `FromDocDtlKey 11992`; only these two fields varied:
  - P5.1 (15:30:57) `FullTransferOption "T"`, `FullTransferFromDocList ""`. Reason: the qty (10) equals the
    whole SO row, so "T" (full transfer) is the typical value.
  - P5.2 (15:31:01) `FullTransferOption "T"`, `FullTransferFromDocList "SO389293"`. Reason: the list field
    has the same shape as `FromSODocList`, which reads back as the SO doc number.
  - P5.3 (15:31:04) `FullTransferOption "F"`, `FullTransferFromDocList ""`. Reason: the other typical
    flag value named by the owner.
- Each PUT: status 200, `DocNo=FXT-1104b-1 ,DocKey=12024 ... Done Edit.`
- After each try: row 12026 unchanged, `FromSODtlKey 0`, `FromSODocList ""`, `FromDocType ""`. Not linked.
  Stopped after three tries, as agreed.

### P6 Replace a row (Q4): the omitted row is kept, nothing is removed

- Before, FXT-1104b-1 rows: `12025 qty 40 HQ unlinked; 12026 qty 10 BRW-AM unlinked; 12028 qty 10 BRW-AM
  FromSODtlKey 11989`; total qty 60. SO row 11992 unlinked (P5 changed nothing).
- PUT `/EditPurchaseOrderbydockey` (15:31:15) with a Details list that leaves out row 12026 and adds one
  `DtlKey 0` row: `{"DtlKey":0,"ItemCode":"SRTKT38SS","Location":"BRW-AM","UOM":"UNIT","UserUOM":"UNIT","Qty":10,"FOCQty":0.0,"UnitPrice":1.0,"DeliveryDate":"2026-11-04T00:00:00","FromDocType":"SO","FromDocNo":"SO389293","FromDocDtlKey":11992,"FullTransferOption":" ","FullTransferFromDocList":""}`
  -> status 200, `DocNo=FXT-1104b-1 ,DocKey=12024 ... Done Edit.`
- After: `12025 40 HQ 0; 12026 10 BRW-AM 0; 12028 10 BRW-AM 11989; 12031 10 HQ 11992`; total qty 70.
  - the omitted row 12026 is kept, unchanged (not deleted, not set to zero);
  - the new row 12031 is linked to 11992 but forced to `HQ` (same as C03) with an empty `DeliveryDate`.
- So a whole-row link by replacing the row does not work: it leaves the original row and doubles the qty.

### P8 and P7a-c: write the read-back link fields, From* keys absent (Q7, Q8): no change

Idea: a link reads back as `FromSODtlKey` + `FromSODocList`, so write those directly on an existing row with
`FromDocType`, `FromDocNo` and `FromDocDtlKey` ABSENT from the row object (not sent empty). Each body: header
as read back, only the touched row as read back, dates before 1753 omitted. Each PUT answered status 200,
`DocNo=FXT-1104b-1 ,DocKey=12024 ... Done Edit.`; row Qty and Location did not change in any probe, and the
PO total stayed 70.

- P8 (15:43:51) unlink, row 12031 (10 HQ, `FromSODtlKey 11992`): row sent with `FromSODtlKey 0` and
  `FromSODocList ""`. After: still `FromSODtlKey 11992`, `FromSODocList "SO389293"`. No change. So 11992
  stayed covered by 12031 for the P7 probes.
- Before each P7 try, row 12026 (10 BRW-AM) read `FromSODtlKey 0`.
  - P7a (15:43:54): `FromSODtlKey 11992`, `FromSODocList "SO389293"`. After: `FromSODtlKey 0`. Not linked.
  - P7b (15:43:56): `FromDocDtlKey 11992`, `FromSODocList "SO389293"`. After: `FromSODtlKey 0`. Not linked.
  - P7c (15:43:58): `FromSODtlKey 11992` only. After: `FromSODtlKey 0`. Not linked.
  A successful P7 link would have over-covered 11992 (SO qty 10, linked 20), so a link would have needed
  checking that; none took effect.

### P8b-d: unlink with the CURRENT link values (Q8): no change

Row 12028 (10 BRW-AM, `FromSODtlKey 11989`, `FromSODocList "SO389293"`), read first before each try, always
still linked. Each PUT answered status 200 `Done Edit.`; Qty and Location unchanged.

- P8b (15:44:33): `FromDocDtlKey 11989`, `FromSODocList "SO389293"`, `FromSODtlKey 0`; `FromDocType` and
  `FromDocNo` absent. After: `FromSODtlKey 11989`, still linked.
- P8c (15:44:34): as P8b plus `FromDocType "SO"` and `FromDocNo "SO389293"`. After: still linked to 11989.
- P8d (15:44:35): only `FromDocDtlKey 11989` and `FromSODocList "SO389293"`. After: still linked to 11989.

Stopped after P8d (no try unlinked). The final FXT-1104b-1 rows are unchanged by these probes: 12025 (40 HQ,
0), 12026 (10 BRW-AM, 0), 12028 (10 BRW-AM, 11989), 12031 (10 HQ, 11992).

## Observations for AutoCount

Questions refer to the numbering in `write-api-questions-2026-11-04.md`.

1. **Location on transfer (Q9).** A NEW row sent with `Location "BRW-AM"` and `FromDocType "SO"` links
   (status 200, `FromSODtlKey 11989`) but reads back `HQ` (run 2, C03). An EXISTING row edited with a new
   location keeps it (P2: row 12026 became `BRW-AM`), but then the link is not applied (item 3). P4 shows
   the location of an already-linked row can be edited afterwards and the link survives (row 12028 moved
   HQ to BRW-AM, `FromSODtlKey` still 11989). So a link to an SO row at another location is two PUTs:
   link on a new row, then edit its location. Can the transfer keep the location we send in one PUT?
2. **Unlink (Q8): no way found.** C07 and P1 both answer status 200 `Done Edit.` and change nothing, also
   when `FromSODtlKey 0` and `FromSODocList ""` are sent (P1) and with `FromDocType "SO"` and a blank
   `FromDocNo` (P1b). Linked PO rows read back `FromDocType ""`, `FromDocNo ""`, `FromDocDtlKey 0`, so
   the link is kept only in `FromSODtlKey` / `FromSODocList`. How is a PO row unlinked from its SO row
   (a different field or endpoint)? P8 (`FromSODtlKey 0` and `FromSODocList ""`
   with the From* keys absent) and P8b-d (the current link values, with or without `FromDocType`/`FromDocNo`,
   `FromSODtlKey 0` or absent) also changed nothing (status 200, still linked). Please also return an error
   instead of 200 when an edit changes nothing.
3. **Link on edit of an existing row (Q7): not applied.** P2 answered status 200 `Done Edit.`, applied the
   location, and ignored `FromDocType "SO"`, `FromDocNo`, `FromDocDtlKey` (row stayed `FromSODtlKey 0`).
   Linking worked only on a new row (`DtlKey 0`, run 2 C03). P5 repeated P2 with `FullTransferOption "T"`,
   `"T"` plus `FullTransferFromDocList "SO389293"`, and `"F"`: all status 200, none linked. No document or
   GET sample shows a non-blank `FullTransferOption`, so what it means is still unknown. P7a-c wrote the read-back
   fields directly with the From* keys absent (`FromSODtlKey` + `FromSODocList`, `FromDocDtlKey` +
   `FromSODocList`, `FromSODtlKey` alone): all status 200, none linked. Is a link on an existing row supported
   at all, and with which values?
4. **ShippingPO on create (Q13, Q14a).** `POST /NewPurchaseOrder` with `ShippingPO "T"` and a row
   `FromDocType "PO"` is refused: status 400 `PO is not valid value to FromDocType.` (P3). What
   `FromDocType` value links an SPO row to a PO row, and is `ShippingPO "T"` accepted on create? Run 2
   C10/C11 were SKIPPED so the SPO flow is still unobserved.
5. **Empty dates (Q21).** In run 1 an echoed `DeliveryDate "0001-01-01T00:00:00"` gave status 500
   `SqlDateTime overflow`; omitting it works (run 2, P1, P2). The split row created through the SO link
   reads back `DeliveryDate "0001-01-01T00:00:00"` although we sent no empty date (C03).
6. **Replacing a row (Q4).** P6 omitted row 12026 and added a new linked row: status 200, the omitted row
   was kept unchanged and the new row was forced to HQ, so no whole-row link by replacement (the qty
   doubled, 60 to 70). Omitted rows are never removed. How is a detail row removed (we never delete
   documents, but we may need to zero or remove a row)?
7. **Create body requirements (Q22).** A complete header (DisplayTerm, CurrencyCode, CurrencyRate) and
   complete rows are needed; a POST that silently drops incomplete rows (run 1) should return an error.
8. Vendor remark in the SO GET about `YourPODate` ("need to change to valid date") fits finding 5.
9. Refusals C05, C06 and C09 and the guard C12 are local and sent no write.

## Cross-check of the final book state (read-only GETs)

- PO 202602-S0007 (DocKey 12008) is unchanged: rows 12011, 12013 and 12015 still linked to SO rows
  11990, 11993 and 11996 (`FromSODtlKey`), as before run 1. This matches C07 (unlink had no effect).
- PO FXT-1104b-1 (DocKey 12024, DisplayTerm C.O.D., CurrencyCode CNY): row 12025 qty 40 HQ unlinked;
  row 12026 qty 10 HQ unlinked; row 12028 qty 10 `Location HQ`, `FromSODtlKey 11989`,
  `FromSODocList "SO389293"`, `DeliveryDate "0001-01-01T00:00:00"`. This matches the C03 after rows.
  The PO total of 60 is conserved.
- SO389293 rows 11989 and 11993 are unchanged (qty 10, BRW-AM).
- FXT-PROBE-1 (DocKey 12023) exists with no rows. No SPO was created.
- After run 3: PO 202602-S0007 is still unchanged (P1 and P1b had no effect). FXT-1104b-1 row 12026 now
  reads `Location BRW-AM` (P2), still unlinked. FXT-1104b-S1 does not exist.
- After P4: FXT-1104b-1 row 12028 reads `Location BRW-AM`, `FromSODtlKey 11989`.
- After P5 and P6: FXT-1104b-1 holds rows 12025 (40 HQ), 12026 (10 BRW-AM, unlinked), 12028 (10 BRW-AM, 11989)
  and 12031 (10 HQ, 11992), total 70. SO389293 row 11992 is now linked by row 12031.
- Test documents left in place as test evidence: FXT-PROBE-1 (empty) and FXT-1104b-1 (four rows). Nothing is deleted or cancelled.
