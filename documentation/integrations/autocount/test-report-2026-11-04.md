# AutoCount write-back test report 2026-11-04

Book: db3 only. Runs on 4 Nov 2026, newest first: run 3b (self-contained suite, card 2 code, all 13 cases pass),
run 3a (blocked by state), run 2 (fixed bodies), run 1 (first attempt), then the probes P1 to P9 that explain
what the wrapper does not apply. Nothing was ever deleted or cancelled.

## Summary: what works on db3 today and what is gated pending AutoCount

| Area | Works today | Gated, pending AutoCount | Evidence |
|---|---|---|---|
| Create PO / SO | yes, with a complete body (header from an existing document, full rows, valid dates) | | C00, C01 (run 3b); run 1 findings |
| Pull and stage | yes | | C02 |
| Link a PO row to an SO row | yes, as a split through a NEW row, then a second write moves it (vendor forces HQ) | | C03, C08 (run 3b), P2, P4 |
| Link an existing row, whole-row (Q7) | | refused `VENDOR_UNSUPPORTED`; the vendor ignores the link on an existing row | C04, P2, P5, P7a-c |
| Unlink a PO row (Q8) | | refused `VENDOR_UNSUPPORTED`; the vendor ignores every variant | C07, P1, P1b, P8, P8b-d |
| Unlink an SPO row | | refused `VENDOR_UNSUPPORTED` | C10, P3, P9 |
| Replace or remove a row (Q4) | | omitted rows are kept, no removal | P6 |
| Location on a linked row (Q9) | editable afterwards (second write) | forced to HQ on a new linked row | C03, P4 |
| SPO create and link (Q13, Q14a) | | cannot be created: `PO is not valid value to FromDocType`; blank type makes a plain PO | P3, P9a-c |
| Local refusals | yes (over-link, qty above free, stale, other book, relocate at location) | | C05, C06, C09, C12, C11 |

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
| FXT-1104b-1 | PO | 12024 | P7a (not clean: SO row already covered; FromSODtlKey 11992 + FromSODocList, From* keys absent) | 15:43:54 | PUT /EditPurchaseOrderbydockey | 200 | no change (row 12026 stays unlinked) | | TEST DOC |
| FXT-1104b-1 | PO | 12024 | P7b (not clean: SO row already covered; FromDocDtlKey 11992 + FromSODocList, others absent) | 15:43:56 | PUT /EditPurchaseOrderbydockey | 200 | no change (row 12026 stays unlinked) | | TEST DOC |
| FXT-1104b-1 | PO | 12024 | P7c (not clean: SO row already covered; FromSODtlKey 11992 only) | 15:43:58 | PUT /EditPurchaseOrderbydockey | 200 | no change (row 12026 stays unlinked) | | TEST DOC |
| FXT-1104b-1 | PO | 12024 | P8b (unlink: FromDocDtlKey 11989 + FromSODocList + FromSODtlKey 0) | 15:44:33 | PUT /EditPurchaseOrderbydockey | 200 | no change (row 12028 stays linked to 11989) | | TEST DOC |
| FXT-1104b-1 | PO | 12024 | P8c (unlink: as P8b plus FromDocType SO and FromDocNo) | 15:44:34 | PUT /EditPurchaseOrderbydockey | 200 | no change (row 12028 stays linked to 11989) | | TEST DOC |
| FXT-1104b-1 | PO | 12024 | P8d (unlink: FromDocDtlKey 11989 + FromSODocList only) | 15:44:35 | PUT /EditPurchaseOrderbydockey | 200 | no change (row 12028 stays linked to 11989) | | TEST DOC |
| FXT-1104c-1 | PO | 12032 | C01 (run 3a) | about 15:33 | POST /NewPurchaseOrder | 200 | created (the run then stopped at C03, `QTY_ABOVE_OUTSTANDING`) | 12033 SRTKT38SS 50 HQ 0; 12034 SRTKT38SS 10 HQ 0 | TEST DOC |
| FXT-1104b-S2 | SPO | none | P9a (FromDocType key absent) | 15:47:06 | POST /NewPurchaseOrder | 400 | refused (" is not valid value to FromDocType.") | not created | PROBE, FAILED CREATE |
| FXT-1104b-S3 | SPO (read back as PO) | 12036 | P9b (FromDocType "") | 15:47:08 | POST /NewPurchaseOrder | 200 | created, rows dropped, ShippingPO read back "F" | no rows; ShippingPO F; DisplayTerm C.O.D., CurrencyCode CNY | PROBE, FAILED CREATE |
| FXT-1104b-S4 | SPO | none | P9c (no link keys at all) | 15:47:09 | POST /NewPurchaseOrder | 400 | refused (" is not valid value to FromDocType.") | not created | PROBE, FAILED CREATE |
| FXT-1104d-SO | SO | 12038 | C00 (run 3b) | 15:48:24 (vendor CreatedTimeStamp 15:48:24.647) | POST /NewSalesOrder | 200 | created | 12039 SRTKT38SS 10 BRW-AM; 12040 5 BRW-AM; 12041 10 BRW-AM (12039 and 12040 now linked from PO rows) | TEST DOC |
| FXT-1104d-1 | PO | 12042 | C01 (run 3b) | 15:48:34 (vendor CreatedTimeStamp 15:48:34.16) | POST /NewPurchaseOrder | 200 | created | see last row for this document | TEST DOC |
| FXT-1104d-1 | PO | 12042 | C03 write 1 (run 3b) | 15:48:35 | PUT /EditPurchaseOrderbydockey | 200 | applied (split, new row linked to 12039, forced to HQ) | | TEST DOC |
| FXT-1104d-1 | PO | 12042 | C03 write 2 (run 3b) | about 15:48:36 | PUT /EditPurchaseOrderbydockey | 200 | applied (row 12046 moved to BRW-AM, link kept) | | TEST DOC |
| FXT-1104d-1 | PO | 12042 | C08 write 1 (run 3b) | 15:48:44 | PUT /EditPurchaseOrderbydockey | 200 | applied (second split, new row linked to 12040, forced to HQ) | | TEST DOC |
| FXT-1104d-1 | PO | 12042 | C08 write 2 (run 3b) | about 15:48:45 (vendor LastModified 15:48:47.08) | PUT /EditPurchaseOrderbydockey | 200 | applied (row 12048 moved to BRW-AM, link kept) | 12043 SRTKT38SS 35 HQ 0; 12044 SRTKT38SS 10 HQ 0; 12046 SRTKT38SS 10 BRW-AM 12039; 12048 SRTKT38SS 5 BRW-AM 12040 | TEST DOC |
| FXT-1104d-1 | PO | 12042 | P7a-2 (FromSODtlKey + FromSODocList, From* absent; clean pair) | 15:53:57 | PUT /EditPurchaseOrderbydockey | 200 | no change (row 12044 stays unlinked) | | TEST DOC |
| FXT-1104d-1 | PO | 12042 | P7b-2 (FromDocDtlKey + FromSODocList; clean pair) | 15:53:58 | PUT /EditPurchaseOrderbydockey | 200 | no change | | TEST DOC |
| FXT-1104d-1 | PO | 12042 | P7c-2 (FromSODtlKey only; clean pair) | 15:54:01 | PUT /EditPurchaseOrderbydockey | 200 | no change | | TEST DOC |
| FXT-1104d-1 | PO | 12042 | P2-2 (documented shape, control; clean pair) | 15:54:03 | PUT /EditPurchaseOrderbydockey | 200 | no change | 12043 SRTKT38SS 35 HQ 0; 12044 SRTKT38SS 10 HQ 0; 12046 SRTKT38SS 10 BRW-AM 12039; 12048 SRTKT38SS 5 BRW-AM 12040 | TEST DOC |
Notes:

- FXT-PROBE-1 shows a blank creditor name because our probe body sent only `CreditorCode` (400-N004) and no
  `CreditorName`; the vendor did not fill it in from the creditor. The documents created with a header copied
  from an existing PO (FXT-1104b-1) carry the creditor name.
- Vendor cross-check of today's documents: FXT-PROBE-1 created 15:05:15.107; FXT-1104b-1 created 15:11:16.477,
  last modified 15:14:46.297; 202602-S0007 (created by AutoCount earlier, 13:39:22.89) last modified 15:13:25.337.
- Left in place as test evidence: FXT-PROBE-1, FXT-1104b-1, FXT-1104b-S3 (empty), FXT-1104c-1, FXT-1104d-SO and FXT-1104d-1. No SPO exists.

## Run 3b (self-contained suite, card 2 code)

Code: the card-2 capability gate, two-write split and relocate, plus C00 (the suite creates its own test SO).
Run tag 1104d. PASS 13, FAIL 0, SKIPPED 0.

### C00 Create the test SO: PASS

- Expected: test SO FXT-1104d-SO created with three SRTKT38SS rows at BRW-AM (10, 5 and 10)
- Observed: created FXT-1104d-SO with 3 rows

- GET /salesorderbydocdate -> 200 (FXT-1104d-SO absent)
- POST /NewSalesOrder -> 200
  - request: `{"DocNo":"FXT-1104d-SO","DocDate":"2026-11-04T00:00:00","DebtorCode":"300-S057","Details":[{"ItemCode":"SRTKT38SS","Location":"BRW-AM","UOM":"UNIT","Qty":10,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0},{"ItemCode":"SRTKT38SS","Location":"BRW-AM","UOM":"UNIT","Qty":5,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0},{"ItemCode":"SRTKT38SS","Location":"BRW-AM","UOM":"UNIT","Qty":10,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0}]}`
  - after: `[{"DtlKey":12039,"ItemCode":"SRTKT38SS","Location":"BRW-AM","UOM":"UNIT","Qty":10.0,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0},{"DtlKey":12040,"ItemCode":"SRTKT38SS","Location":"BRW-AM","UOM":"UNIT","Qty":5.0,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0},{"DtlKey":12041,"ItemCode":"SRTKT38SS","Location":"BRW-AM","UOM":"UNIT","Qty":10.0,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0}]`

### C01 Create the test PO: PASS

- Expected: test PO created with two SRTKT38SS rows (50 and 10 at HQ)
- Observed: created FXT-1104d-1 with 2 rows

- GET /purchaseorderbydocdate -> 200 (baseline pull docs=3)
- GET /purchaseorderbydocdate -> 200 (FXT-1104d-1 absent)
- POST /NewPurchaseOrder -> 200
  - request: `{"DocNo":"FXT-1104d-1","DocDate":"2026-11-04T00:00:00","CreditorCode":"400-N004","ShippingPO":"F","Details":[{"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","Qty":50,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0},{"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","Qty":10,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0}]}`
  - after: `[{"DtlKey":12043,"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","Qty":50.0,"FromSODtlKey":0,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0},{"DtlKey":12044,"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","Qty":10.0,"FromSODtlKey":0,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0}]`

### C02 Pull SO then PO into staging: PASS

- Expected: SO days then PO days pulled; the test PO is staged
- Observed: docs_seen=6 staged=4 pushed=4

- GET /purchaseorderbydocdate -> 200 (docs=6 staged=4)

### C03 Link with split: PASS

- Expected: split in two writes: 40 stay at HQ, a new 10 row linked to SO row 11989 and moved to BRW-AM
- Observed: done
- Action: f93b5c65-c22e-4a4f-8aef-39d49e386ea2

- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12042,"DocNo":"FXT-1104d-1","Details":[{"DtlKey":12043,"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","Qty":40.0,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0},{"DtlKey":0,"ItemCode":"SRTKT38SS","Location":"BRW-AM","UOM":"UNIT","Qty":10.0,"FromDocType":"SO","FromDocNo":"FXT-1104d-SO","FromDocDtlKey":12039}]}`
  - before: `[{"DtlKey":12043,"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","Qty":50.0,"FromSODtlKey":0,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0}]`
  - after: `[{"DtlKey":12043,"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","Qty":40.0,"FromSODtlKey":0,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0},{"DtlKey":12046,"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","Qty":10.0,"FromSODtlKey":12039,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0}]`
- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12042,"DocNo":"FXT-1104d-1","Details":[{"DtlKey":12046,"ItemCode":"SRTKT38SS","Location":"BRW-AM","UOM":"UNIT","Qty":10.0,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0}]}`
  - before: `[{"DtlKey":12046,"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","Qty":10.0,"FromSODtlKey":12039,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0}]`
  - after: `[{"DtlKey":12046,"ItemCode":"SRTKT38SS","Location":"BRW-AM","UOM":"UNIT","Qty":10.0,"FromSODtlKey":12039,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0}]`

### C04 Whole-row link refused by the capability gate: PASS

- Expected: whole-row link refused: the vendor does not apply an edit of an existing row (VENDOR_UNSUPPORTED)
- Observed: refused VENDOR_UNSUPPORTED
- Action: 185f77c3-bb98-4ff6-b9c4-e9f041382788


### C05 Over-link refused: PASS

- Expected: link refused: the SO row is already covered (QTY_ABOVE_OUTSTANDING)
- Observed: refused QTY_ABOVE_OUTSTANDING
- Action: e09825d7-4e8d-42dd-9fd8-944c4e0ce94b


### C06 Quantity above the PO row refused: PASS

- Expected: link refused: quantity above the PO row (QTY_ABOVE_FREE)
- Observed: refused QTY_ABOVE_FREE
- Action: 9e8bc553-98bd-4ecf-a1b9-a4e643321def


### C07 Unlink refused by the capability gate: PASS

- Expected: unlink of 202602-S0007 row 12013 refused: the vendor does not apply it (VENDOR_UNSUPPORTED), nothing sent
- Observed: refused VENDOR_UNSUPPORTED
- Action: 61fb2268-65f0-4cd1-a9ab-ebad80673b94


### C08 Second split of the 40 row: PASS

- Expected: second split of the 40 row: 5 linked to SO row 11992 and moved to BRW-AM
- Observed: done
- Action: 331ce0d1-4740-45ce-a726-18b77c394479

- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12042,"DocNo":"FXT-1104d-1","Details":[{"DtlKey":12043,"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","Qty":35.0,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0},{"DtlKey":0,"ItemCode":"SRTKT38SS","Location":"BRW-AM","UOM":"UNIT","Qty":5.0,"FromDocType":"SO","FromDocNo":"FXT-1104d-SO","FromDocDtlKey":12040}]}`
  - before: `[{"DtlKey":12043,"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","Qty":40.0,"FromSODtlKey":0,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0}]`
  - after: `[{"DtlKey":12043,"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","Qty":35.0,"FromSODtlKey":0,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0},{"DtlKey":12048,"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","Qty":5.0,"FromSODtlKey":12040,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0}]`
- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12042,"DocNo":"FXT-1104d-1","Details":[{"DtlKey":12048,"ItemCode":"SRTKT38SS","Location":"BRW-AM","UOM":"UNIT","Qty":5.0,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0}]}`
  - before: `[{"DtlKey":12048,"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","Qty":5.0,"FromSODtlKey":12040,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0}]`
  - after: `[{"DtlKey":12048,"ItemCode":"SRTKT38SS","Location":"BRW-AM","UOM":"UNIT","Qty":5.0,"FromSODtlKey":12040,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0}]`

### C09 Stale document refused: PASS

- Expected: stale document refused (DOC_STALE)
- Observed: refused DOC_STALE
- Action: 574e3b61-e6e1-4f34-bdb3-00640a8041dc


### C10 SPO unlink refused by the capability gate: PASS

- Expected: SPO unlink refused: the vendor does not apply it (VENDOR_UNSUPPORTED), nothing sent
- Observed: refused VENDOR_UNSUPPORTED
- Action: 2695e93c-9a48-4db7-bc73-1af9edcdff9a


### C11 Relocate of a row already at its location: PASS

- Expected: relocate of the C08 row, already at its SO location, is refused (ROW_ALREADY_AT_LOCATION)
- Observed: refused ROW_ALREADY_AT_LOCATION
- Action: 7b8fa9d4-d280-4efb-9de0-71db18310abc


### C12 Other book refused with no request: PASS

- Expected: a client for another book is refused at construction with no request (WRITE_NOT_ALLOWED)
- Observed: refused WRITE_NOT_ALLOWED, 0 requests

Read-only cross-check after the run: FXT-1104d-SO (DocKey 12038, created 15:48:24.647) holds rows 12039
(10), 12040 (5), 12041 (10), all BRW-AM. FXT-1104d-1 (DocKey 12042, created 15:48:34.16, last modified
15:48:47.08) holds 12043 (35 HQ, unlinked), 12044 (10 HQ, unlinked), 12046 (10 BRW-AM, `FromSODtlKey 12039`)
and 12048 (5 BRW-AM, `FromSODtlKey 12040`). This matches the C03 and C08 after rows. No vendor surprise in this
run: every new linked row came back at HQ (as known) and the second write moved it.

## Run 3a (blocked by state, guard refused correctly)

Run tag 1104c, same code, before C00 existed. C00 did not exist yet, so C03 targeted SO389293 row 11989, which
FXT-1104b-1 row 12028 already covered (SO qty 10, linked 10); C08 would have targeted row 11992, covered by
row 12031 (P6). C03 was refused `QTY_ABOVE_OUTSTANDING`, so C04, C05, C08 and C11 were SKIPPED. C01 created
FXT-1104c-1 (DocKey 12032, rows 12033 50 HQ and 12034 10 HQ); C06, C07, C09, C10 and C12 passed. The guard was
right: earlier probe rows already covered the real SO rows. Run 3b made the suite self-contained.

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

### P8 and P7a-c: write the read-back link fields, From* keys absent (Q7, Q8): no change (P7a-c not clean: SO row already covered)

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

### P9 SPO create variants (Q13, Q14a): an SPO cannot be created

Every body as C01 builds it: header from 202602-S0007's read-back, `ShippingPO "T"`, today's DocDate, one full
row (SRTKT38SS, qty 5, BRW-AM, UOM and Description from the SO row, DeliveryDate today). Link target
FXT-1104b-1 row 12025 (40 HQ, `FromSODtlKey 0`, read first). Row 12025 (qty 40, location HQ, unlinked) was
re-read after each probe and never changed.

- P9a (15:47:06) DocNo FXT-1104b-S2: row with `FromDocNo "FXT-1104b-1"`, `FromDocDtlKey 12025`, the
  `FromDocType` key ABSENT. POST -> status 400 `{"Message": " is not valid value to FromDocType."}` (the
  value named is empty). Document does not exist.
- P9b (15:47:08) DocNo FXT-1104b-S3: same row with `FromDocType ""`. POST -> status 200 `DocNo=FXT-1104b-S3
  ,DocKey=12036 ... Created Successful.` Read back by DocDate: DocKey 12036, `ShippingPO "F"` (not "T"),
  no rows (the row was dropped). So the vendor created an ordinary PO header without the SPO flag and
  without rows.
- P9c (15:47:09) DocNo FXT-1104b-S4: a plain SPO, `ShippingPO "T"` and no link keys at all. POST -> status 400
  `" is not valid value to FromDocType."`. Not created. So an SPO row needs a valid `FromDocType`, and we have
  no value that works: "" and absent are refused or dropped (P9a, P9b, P9c), and "PO" was refused earlier
  (P3: `PO is not valid value to FromDocType.`).
- P9d skipped. The only `FromDocType` spellings anywhere we hold are `""`, `"PO"` (63 rows, all db1 GET
  rows, e.g. SPO-2026/11-0001 row 46179075), `"SO"` and `"QT"` (vendor test-records file and db3 GETs; `ToDocType`
  also shows `"GR"` and `"SO"`). No other spelling of the PO type exists, and "PO" is the one P3 refused.

### P7a-2, P7b-2, P7c-2 and P2-2: clean re-run of the link on an existing row (Q7): no change

The first P7 targeted SO389293 row 11992, which row 12031 (P6) already covered, so AutoCount may have ignored it as
an over-link. This re-run uses a clean pair: PO FXT-1104d-1 (DocKey 12042) row 12044 (10 HQ, unlinked) and the
third row of SO FXT-1104d-SO (DocKey 12038), DtlKey 12041 (SRTKT38SS 10 BRW-AM). Confirmed by GET before the
first try: no PO row in today's list has `FromSODtlKey 12041`, so the SO row's linked qty was 0 before every
try and 0 after every try. Before each try row 12044 was read: `Qty 10, Location HQ, FromSODtlKey 0,
FromSODocList "", FromDocType ""`. Body as before: header as read back, only row 12044, dates before 1753
omitted. Each PUT answered status 200, `DocNo=FXT-1104d-1 ,DocKey=12042 ... Done Edit.`; Qty and Location never
changed, and the row read back unlinked after each try. Stopped nowhere: no try linked.

- P7a-2 (15:53:57): `FromSODtlKey 12041`, `FromSODocList "FXT-1104d-SO"`; `FromDocType`, `FromDocNo`, `FromDocDtlKey`
  absent. Linked qty before 0, after 0. Not linked.
- P7b-2 (15:53:58): `FromDocDtlKey 12041`, `FromSODocList "FXT-1104d-SO"`; the other link keys absent. Linked qty 0
  before, 0 after. Not linked.
- P7c-2 (15:54:01): `FromSODtlKey 12041` only. Linked qty 0 before, 0 after. Not linked.
- P2-2 control (15:54:03): the documented shape, `FromDocType "SO"`, `FromDocNo "FXT-1104d-SO"`,
  `FromDocDtlKey 12041`, `FullTransferOption " "`. Linked qty 0 before, 0 after. Not linked. So the original P2
  conclusion holds on a clean pair: a link on an existing row is ignored even when the SO row is uncovered.

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
   GET sample shows a non-blank `FullTransferOption`, so what it means is still unknown. P7a-c (not clean: the SO row was already covered) wrote the read-back
   fields directly with the From* keys absent (`FromSODtlKey` + `FromSODocList`, `FromDocDtlKey` +
   `FromSODocList`, `FromSODtlKey` alone): all status 200, none linked. Is a link on an existing row supported
   at all, and with which values? The clean re-run (P7a-2, P7b-2, P7c-2 and the documented shape P2-2, on an uncovered
   SO row) changed nothing either, so over-coverage was not the reason.
4. **ShippingPO on create (Q13, Q14a).** `POST /NewPurchaseOrder` with `ShippingPO "T"` and a row
   `FromDocType "PO"` is refused: status 400 `PO is not valid value to FromDocType.` (P3). What
   `FromDocType` value links an SPO row to a PO row, and is `ShippingPO "T"` accepted on create? Run 2
   C10/C11 were SKIPPED so the SPO flow is still unobserved. P9a-c (key absent, `""`, no link keys)
   confirm that creating an SPO fails with `<value> is not valid value to FromDocType` for a blank or absent
   type, and a blank type with `ShippingPO "T"` creates a plain PO header with no rows (P9b: `ShippingPO`
   read back "F"). db1 reads SPO rows with `FromDocType "PO"`, which db3 refuses on create. What value (and
   what header) creates an SPO on db3?
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
