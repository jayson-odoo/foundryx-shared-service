# AutoCount PO link batch: db3 runner report 2026-11-12 (plan 62)

Suite `--suite batch` of `write_back/runner.py`, run 12 Nov 2026 (tag `1112A`, code at f17fab62) against book db3 only (documents `FXT-1112A-*`),
through `OperationService.run` with the operations `link_batch`, `link_row` and `unlink_row` (the code the
gateway runs). Every vendor request is also a row in `ac_api_call_log`. All quantities are small; every unit
price is 1.0.

Reading the timings: the same suite run the evening before (tag `1111B`) took 3.2 s, 4.7 s and
3.5 s for the batches of 1, 3 and 5, and 16.8 s for the three single calls; db3 latency varies by a factor of
two to three between runs. What does not vary is the request count: a batch is always 2 PUTs (PUT 1 plus one
restore PUT) whatever its size, today's flow is 2 PUTs per SO line.

Findings:
- A batch of 1, 3 or 5 SO lines is exactly one PUT 1 and one restore PUT. The restore PUT covers every new row.
- Whole row (sum equals the quantity): the row is deleted in PUT 1 (B02). Part of the row: the row stays as the
  free row with the rest (B01, B03).
- The unlink merge (B05) is one PUT and raises the first matching free row in row order (the B01 free row).
  It only fires when the batch rows and the free row sit at the same location: the suite puts the SO rows at HQ
  for that reason.
- AutoCount's receipt state is not readable from the GET, so every batch and unlink answers with the warning
  `TRANSFER_STATE_UNKNOWN` (the same rule as the existing operations).
- AutoCount does not refuse linking more than an SO row's quantity (seen in an earlier run of this suite, which
  linked 8 against an SO row of 5 and was accepted). The over-link guard lives in SS (`ac_po_so_link`).
- Cases B07 to B10 (added after review): B07 proves `QTY_ABOVE_OUTSTANDING` (a quantity within the PO row's free
  quantity but above the SO row's outstanding) with 0 PUTs; B08 to B10 prove the create resend lookup on db3: a QT
  create whose POST landed and whose answer was lost (a `<<New>>` body and a numbered body) is found on the resend
  with 0 second POST, and a create that never left is POSTed once.
- SO row lock (Postgres only, so no unit test drives it): this run had the lock live. Every case passed with no
  `DOC_BUSY` for a single caller; after the run `pg_locks` held 0 advisory locks, and the lock connections showed in
  `pg_stat_activity` as `foundryx-runner-lock` (idle, pooled, nothing held).
- The plan 55 suite (`--suite db3`, tag `1112C`, run after the runner followed the unlink merge) passed C00 to C17.
  The no-key link path takes the same lock (0 advisory locks left). C13's unlink now merges into the C07 row, so
  C14 links the row C13 left for the quantity the first SO row still has outstanding, and C15 relinks that row.

Book: db3. Run tag: 1112A. PASS 11, FAIL 0, SKIPPED 0.

## Timings

| Case | Calls | SO lines | Wall ms | PUTs | ac_api_call_log rows |
|---|---|---|---|---|---|
| B01 batch of 1 | 1 | 1 | 8778 | 2 | 8 |
| B02 batch of 3 | 1 | 3 | 5717 | 2 | 9 |
| B03 batch of 5 | 1 | 5 | 5001 | 2 | 9 |
| B04 today: 3 calls | 3 | 3 | 18783 | 6 | 21 |
| B05 unlink merge | 1 | 1 | 2950 | 1 | 4 |
| B06 retry: refused batch | 1 | 1 | 754 | 0 | 1 |
| B06 retry: fixed batch, same key | 1 | 1 | 7360 | 2 | 8 |
| B07 refused above outstanding | 1 | 1 | 1775 | 0 | 2 |

## B00 Create the test documents (3 sales orders, 1 purchase order): PASS

- Expected: SO1 (3 rows qty 10), SO2 (2 rows qty 10), SO3 (1 row qty 5), PO with rows A10 B12 C10 D6 E4
- Observed: created SO1 FXT-1112A-SO1, SO2 FXT-1112A-SO2, SO3 FXT-1112A-SO3 and FXT-1112A-PO

- POST /NewSalesOrder -> 200
  - request: `{"DocNo":"FXT-1112A-SO1","DocDate":"2026-11-12T00:00:00","DisplayTerm":"C.B.D.","CurrencyCode":"MYR","CurrencyRate":1.0,"DebtorCode":"300-S057","Details":[{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":10,"UnitPrice":1.0,"DeliveryDate":"2026-11-12T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","YourPONo":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":10,"UnitPrice":1.0,"DeliveryDate":"2026-11-12T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","YourPONo":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":10,"UnitPrice":1.0,"DeliveryDate":"2026-11-12T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","YourPONo":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""}]}`
  - answer: `"DocNo=FXT-1112A-SO1 ,DocKey=12573 ... Created Successful."`
- POST /NewSalesOrder -> 200
  - request: `{"DocNo":"FXT-1112A-SO2","DocDate":"2026-11-12T00:00:00","DisplayTerm":"C.B.D.","CurrencyCode":"MYR","CurrencyRate":1.0,"DebtorCode":"300-S057","Details":[{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":10,"UnitPrice":1.0,"DeliveryDate":"2026-11-12T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","YourPONo":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":10,"UnitPrice":1.0,"DeliveryDate":"2026-11-12T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","YourPONo":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""}]}`
  - answer: `"DocNo=FXT-1112A-SO2 ,DocKey=12577 ... Created Successful."`
- POST /NewSalesOrder -> 200
  - request: `{"DocNo":"FXT-1112A-SO3","DocDate":"2026-11-12T00:00:00","DisplayTerm":"C.B.D.","CurrencyCode":"MYR","CurrencyRate":1.0,"DebtorCode":"300-S057","Details":[{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":5,"UnitPrice":1.0,"DeliveryDate":"2026-11-12T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","YourPONo":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""}]}`
  - answer: `"DocNo=FXT-1112A-SO3 ,DocKey=12580 ... Created Successful."`
- POST /NewPurchaseOrder -> 200
  - request: `{"DocNo":"FXT-1112A-PO","DocDate":"2026-11-12T00:00:00","CreditorCode":"400-N004","DisplayTerm":"C.B.D.","CurrencyCode":"MYR","CurrencyRate":1.0,"ShippingPO":"F","Details":[{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":10,"UnitPrice":1.0,"DeliveryDate":"2026-11-12T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","YourPONo":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":12,"UnitPrice":1.0,"DeliveryDate":"2026-11-12T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","YourPONo":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":10,"UnitPrice":1.0,"DeliveryDate":"2026-11-12T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","YourPONo":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":6,"UnitPrice":1.0,"DeliveryDate":"2026-11-12T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","YourPONo":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":4,"UnitPrice":1.0,"DeliveryDate":"2026-11-12T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","YourPONo":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""}]}`
  - answer: `"DocNo=FXT-1112A-PO ,DocKey=12582 ... Created Successful."`

## B01 Batch of 1 SO line (sum below the row quantity: a free row stays): PASS

- Expected: one PUT 1 (+ at most one PUT 2), 1 linked row at the SO row's location, price and date kept, free row 7
- Observed: done; 1 linked rows, free line 7.0, warnings TRANSFER_STATE_UNKNOWN; 8778 ms, 2 PUT

- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12582,"DocNo":"FXT-1112A-PO","DocDate":"2026-11-12T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12583,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":7.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-12T00:00:00","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":3.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-12T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1112A-SO1","FromDocDtlKey":12574,"FullTransferOption":" ","FullTransferFromDocList":"","YourPONo":"","DtlKey":0}]}`
  - answer: `"DocNo=FXT-1112A-PO ,DocKey=12582 ... Done Edit."`
- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12582,"DocNo":"FXT-1112A-PO","DocDate":"2026-11-12T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12589,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":3.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-12T00:00:00"}]}`
  - answer: `"DocNo=FXT-1112A-PO ,DocKey=12582 ... Done Edit."`

## B02 Batch of 3 SO lines across 2 sales orders (sum equals the row quantity: the row is deleted): PASS

- Expected: one PUT 1 (+ at most one PUT 2), 3 linked rows, the row deleted (sum equals its quantity)
- Observed: done; 3 linked rows, free line none, warnings TRANSFER_STATE_UNKNOWN; 5717 ms, 2 PUT

- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12582,"DocNo":"FXT-1112A-PO","DocDate":"2026-11-12T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12584,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":12.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-12T00:00:00","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":"D","FullTransferFromDocList":""},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":4.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-12T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1112A-SO1","FromDocDtlKey":12575,"FullTransferOption":" ","FullTransferFromDocList":"","YourPONo":"","DtlKey":0},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":4.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-12T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1112A-SO1","FromDocDtlKey":12576,"FullTransferOption":" ","FullTransferFromDocList":"","YourPONo":"","DtlKey":0},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":4.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-12T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1112A-SO2","FromDocDtlKey":12578,"FullTransferOption":" ","FullTransferFromDocList":"","YourPONo":"","DtlKey":0}]}`
  - answer: `"DocNo=FXT-1112A-PO ,DocKey=12582 ... Done Edit."`
- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12582,"DocNo":"FXT-1112A-PO","DocDate":"2026-11-12T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12591,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":4.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-12T00:00:00"},{"DtlKey":12593,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":4.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-12T00:00:00"},{"DtlKey":12595,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":4.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-12T00:00:00"}]}`
  - answer: `"DocNo=FXT-1112A-PO ,DocKey=12582 ... Done Edit."`

## B03 Batch of 5 SO lines across 2 sales orders (sum below the row quantity): PASS

- Expected: one PUT 1 (+ at most one PUT 2), 5 linked rows, free row 5
- Observed: done; 5 linked rows, free line 5.0, warnings TRANSFER_STATE_UNKNOWN; 5001 ms, 2 PUT

- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12582,"DocNo":"FXT-1112A-PO","DocDate":"2026-11-12T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12585,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":5.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-12T00:00:00","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":1.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-12T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1112A-SO1","FromDocDtlKey":12574,"FullTransferOption":" ","FullTransferFromDocList":"","YourPONo":"","DtlKey":0},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":1.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-12T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1112A-SO1","FromDocDtlKey":12575,"FullTransferOption":" ","FullTransferFromDocList":"","YourPONo":"","DtlKey":0},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":1.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-12T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1112A-SO1","FromDocDtlKey":12576,"FullTransferOption":" ","FullTransferFromDocList":"","YourPONo":"","DtlKey":0},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":1.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-12T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1112A-SO2","FromDocDtlKey":12578,"FullTransferOption":" ","FullTransferFromDocList":"","YourPONo":"","DtlKey":0},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":1.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-12T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1112A-SO2","FromDocDtlKey":12579,"FullTransferOption":" ","FullTransferFromDocList":"","YourPONo":"","DtlKey":0}]}`
  - answer: `"DocNo=FXT-1112A-PO ,DocKey=12582 ... Done Edit."`
- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12582,"DocNo":"FXT-1112A-PO","DocDate":"2026-11-12T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12597,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":1.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-12T00:00:00"},{"DtlKey":12599,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":1.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-12T00:00:00"},{"DtlKey":12601,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":1.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-12T00:00:00"},{"DtlKey":12603,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":1.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-12T00:00:00"},{"DtlKey":12605,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":1.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-12T00:00:00"}]}`
  - answer: `"DocNo=FXT-1112A-PO ,DocKey=12582 ... Done Edit."`

## B04 Today's flow: the same 3 SO lines linked one call at a time (timing baseline): PASS

- Expected: three link_row calls, each its own split (PUT 1 + restore PUT)
- Observed: done, done, done; 18783 ms, 6 PUT

- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12582,"DocNo":"FXT-1112A-PO","DocDate":"2026-11-12T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12586,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":5.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-12T00:00:00","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"DtlKey":0,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":1.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-12T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1112A-SO1","FromDocDtlKey":12574,"FullTransferOption":" ","FullTransferFromDocList":""}]}`
  - answer: `"DocNo=FXT-1112A-PO ,DocKey=12582 ... Done Edit."`
- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12582,"DocNo":"FXT-1112A-PO","DocDate":"2026-11-12T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12607,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":1.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-12T00:00:00"}]}`
  - answer: `"DocNo=FXT-1112A-PO ,DocKey=12582 ... Done Edit."`
- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12582,"DocNo":"FXT-1112A-PO","DocDate":"2026-11-12T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12586,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":4.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-12T00:00:00","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"DtlKey":0,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":1.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-12T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1112A-SO1","FromDocDtlKey":12575,"FullTransferOption":" ","FullTransferFromDocList":""}]}`
  - answer: `"DocNo=FXT-1112A-PO ,DocKey=12582 ... Done Edit."`
- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12582,"DocNo":"FXT-1112A-PO","DocDate":"2026-11-12T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12609,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":1.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-12T00:00:00"}]}`
  - answer: `"DocNo=FXT-1112A-PO ,DocKey=12582 ... Done Edit."`
- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12582,"DocNo":"FXT-1112A-PO","DocDate":"2026-11-12T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12586,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":3.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-12T00:00:00","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"DtlKey":0,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":1.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-12T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1112A-SO2","FromDocDtlKey":12579,"FullTransferOption":" ","FullTransferFromDocList":""}]}`
  - answer: `"DocNo=FXT-1112A-PO ,DocKey=12582 ... Done Edit."`
- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12582,"DocNo":"FXT-1112A-PO","DocDate":"2026-11-12T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12611,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":1.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-12T00:00:00"}]}`
  - answer: `"DocNo=FXT-1112A-PO ,DocKey=12582 ... Done Edit."`

## B05 Unlink one batch row: it merges into the free row in one PUT: PASS

- Expected: unlink of a B03 batch row: ONE PUT, the row deleted, the FIRST matching free row (the B01 free row, row order) raised by its quantity, the answer names it
- Observed: done, replaced [(12597, 12583)], free row 8.0, 2950 ms, 1 PUT

- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12582,"DocNo":"FXT-1112A-PO","DocDate":"2026-11-12T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12597,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":1.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-12T00:00:00","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":"D","FullTransferFromDocList":""},{"DtlKey":12583,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":8.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-12T00:00:00","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""}]}`
  - answer: `"DocNo=FXT-1112A-PO ,DocKey=12582 ... Done Edit."`

## B06 Retry rule: a refused batch, the body fixed, the SAME key resent: PASS

- Expected: a batch with one quantity above the SO row's outstanding is refused before any PUT; the body fixed and the SAME key resent runs fresh and is done (plan 62 D6)
- Observed: first refused QTY_ABOVE_FREE (0 PUT); resend with the same key done

- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12582,"DocNo":"FXT-1112A-PO","DocDate":"2026-11-12T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12587,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":3.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-12T00:00:00","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":1.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-12T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1112A-SO2","FromDocDtlKey":12579,"FullTransferOption":" ","FullTransferFromDocList":"","YourPONo":"","DtlKey":0}]}`
  - answer: `"DocNo=FXT-1112A-PO ,DocKey=12582 ... Done Edit."`
- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12582,"DocNo":"FXT-1112A-PO","DocDate":"2026-11-12T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12613,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":1.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-12T00:00:00"}]}`
  - answer: `"DocNo=FXT-1112A-PO ,DocKey=12582 ... Done Edit."`

## B07 A batch above the SO row's outstanding (within the PO row's free quantity) is refused with no PUT: PASS

- Expected: a batch whose quantity is within the PO row's free quantity but above the SO row's outstanding: refused QTY_ABOVE_OUTSTANDING, naming the SO row, 0 PUTs
- Observed: refused QTY_ABOVE_OUTSTANDING (qty 8.0, outstanding 7.0, free 8.0, 0 PUT)


## B08 Create resend: the POST landed, the answer was lost; the resend finds the document (<<New>> body): PASS

- Expected: the POST lands, then times out; the resend of the SAME key looks the document up (<<New>> body: day list, debtor, time window, lines), answers done with its DocNo, 0 second POST
- Observed: first pending_verification WRITE_TIMEOUT; resend done QT-000014; 1 POST in ac_api_call_log

- POST /NewQuotation -> 200
  - request: `{"DocDate":"2026-11-12T00:00:00","DisplayTerm":"C.B.D.","CurrencyCode":"MYR","CurrencyRate":1.0,"DebtorCode":"300-S057","DocNo":"<<New>>","Details":[{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":3,"UnitPrice":1.0,"DeliveryDate":"2026-11-12T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","FullTransferOption":" ","FullTransferFromDocList":""}]}`
  - answer: `"DocNo=QT-000014 ,DocKey=12614 ... Created Successful."`

## B09 Create resend: nothing was sent; the resend finds nothing and POSTs once (<<New>> body): PASS

- Expected: the call times out before anything is sent; the resend finds no document, releases the key and POSTs once: 1 POST in total
- Observed: first pending_verification WRITE_TIMEOUT; resend done QT-000015; 1 POST in ac_api_call_log

- POST /NewQuotation -> 200
  - request: `{"DocDate":"2026-11-12T00:00:00","DisplayTerm":"C.B.D.","CurrencyCode":"MYR","CurrencyRate":1.0,"DebtorCode":"300-S057","DocNo":"<<New>>","Details":[{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":4,"UnitPrice":1.0,"DeliveryDate":"2026-11-12T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","FullTransferOption":" ","FullTransferFromDocList":""}]}`
  - answer: `"DocNo=QT-000015 ,DocKey=12616 ... Created Successful."`

## B10 Create resend: the POST landed, the answer was lost; the resend finds the document (numbered body): PASS

- Expected: numbered body: the POST lands, then times out; the resend finds the document by DocNo, answers done, 0 second POST
- Observed: first pending_verification WRITE_TIMEOUT; resend done FXT-1112A-QTN; 1 POST in ac_api_call_log

- POST /NewQuotation -> 200
  - request: `{"DocNo":"FXT-1112A-QTN","DocDate":"2026-11-12T00:00:00","DisplayTerm":"C.B.D.","CurrencyCode":"MYR","CurrencyRate":1.0,"DebtorCode":"300-S057","Details":[{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":5,"UnitPrice":1.0,"DeliveryDate":"2026-11-12T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","FullTransferOption":" ","FullTransferFromDocList":""}]}`
  - answer: `"DocNo=FXT-1112A-QTN ,DocKey=12618 ... Created Successful."`
