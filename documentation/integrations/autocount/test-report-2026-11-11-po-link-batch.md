# AutoCount PO link batch: db3 runner report 2026-11-11 (plan 62)

Suite `--suite batch` of `write_back/runner.py`, run 11 Nov 2026 against book db3 only (documents `FXT-1111D-*`),
through `OperationService.run` with the operations `link_batch`, `link_row` and `unlink_row` (the code the
gateway runs). Every vendor request is also a row in `ac_api_call_log`. All quantities are small; every unit
price is 1.0.

Reading the timings: the same suite run earlier the same evening (tag `1111B`, same code) took 3.2 s, 4.7 s and
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

Book: db3. Run tag: 1111C. PASS 7, FAIL 0, SKIPPED 0.
- Cases B07 to B10 (added after review): B07 proves `QTY_ABOVE_OUTSTANDING` (a quantity within the PO row's free
  quantity but above the SO row's outstanding) with 0 PUTs; B08 to B10 prove the create resend lookup on db3: a QT
  create whose POST landed and whose answer was lost (a `<<New>>` body and a numbered body) is found on the resend
  with 0 second POST, and a create that never left is POSTed once.


Book: db3. Run tag: 1111D. PASS 11, FAIL 0, SKIPPED 0.

## Timings

| Case | Calls | SO lines | Wall ms | PUTs | ac_api_call_log rows |
|---|---|---|---|---|---|
| B01 batch of 1 | 1 | 1 | 8758 | 2 | 8 |
| B02 batch of 3 | 1 | 3 | 11452 | 2 | 9 |
| B03 batch of 5 | 1 | 5 | 10611 | 2 | 9 |
| B04 today: 3 calls | 3 | 3 | 29205 | 6 | 21 |
| B05 unlink merge | 1 | 1 | 4703 | 1 | 4 |
| B06 retry: refused batch | 1 | 1 | 1286 | 0 | 1 |
| B06 retry: fixed batch, same key | 1 | 1 | 10362 | 2 | 8 |
| B07 refused above outstanding | 1 | 1 | 2227 | 0 | 2 |

## B00 Create the test documents (3 sales orders, 1 purchase order): PASS

- Expected: SO1 (3 rows qty 10), SO2 (2 rows qty 10), SO3 (1 row qty 5), PO with rows A10 B12 C10 D6 E4
- Observed: created SO1 FXT-1111D-SO1, SO2 FXT-1111D-SO2, SO3 FXT-1111D-SO3 and FXT-1111D-PO

- POST /NewSalesOrder -> 200
  - request: `{"DocNo":"FXT-1111D-SO1","DocDate":"2026-11-11T00:00:00","DisplayTerm":"C.B.D.","CurrencyCode":"MYR","CurrencyRate":1.0,"DebtorCode":"300-S057","Details":[{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":10,"UnitPrice":1.0,"DeliveryDate":"2026-11-11T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","YourPONo":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":10,"UnitPrice":1.0,"DeliveryDate":"2026-11-11T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","YourPONo":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":10,"UnitPrice":1.0,"DeliveryDate":"2026-11-11T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","YourPONo":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""}]}`
  - answer: `"DocNo=FXT-1111D-SO1 ,DocKey=12526 ... Created Successful."`
- POST /NewSalesOrder -> 200
  - request: `{"DocNo":"FXT-1111D-SO2","DocDate":"2026-11-11T00:00:00","DisplayTerm":"C.B.D.","CurrencyCode":"MYR","CurrencyRate":1.0,"DebtorCode":"300-S057","Details":[{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":10,"UnitPrice":1.0,"DeliveryDate":"2026-11-11T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","YourPONo":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":10,"UnitPrice":1.0,"DeliveryDate":"2026-11-11T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","YourPONo":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""}]}`
  - answer: `"DocNo=FXT-1111D-SO2 ,DocKey=12530 ... Created Successful."`
- POST /NewSalesOrder -> 200
  - request: `{"DocNo":"FXT-1111D-SO3","DocDate":"2026-11-11T00:00:00","DisplayTerm":"C.B.D.","CurrencyCode":"MYR","CurrencyRate":1.0,"DebtorCode":"300-S057","Details":[{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":5,"UnitPrice":1.0,"DeliveryDate":"2026-11-11T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","YourPONo":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""}]}`
  - answer: `"DocNo=FXT-1111D-SO3 ,DocKey=12533 ... Created Successful."`
- POST /NewPurchaseOrder -> 200
  - request: `{"DocNo":"FXT-1111D-PO","DocDate":"2026-11-11T00:00:00","CreditorCode":"400-N004","DisplayTerm":"C.B.D.","CurrencyCode":"MYR","CurrencyRate":1.0,"ShippingPO":"F","Details":[{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":10,"UnitPrice":1.0,"DeliveryDate":"2026-11-11T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","YourPONo":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":12,"UnitPrice":1.0,"DeliveryDate":"2026-11-11T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","YourPONo":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":10,"UnitPrice":1.0,"DeliveryDate":"2026-11-11T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","YourPONo":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":6,"UnitPrice":1.0,"DeliveryDate":"2026-11-11T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","YourPONo":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":4,"UnitPrice":1.0,"DeliveryDate":"2026-11-11T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","YourPONo":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""}]}`
  - answer: `"DocNo=FXT-1111D-PO ,DocKey=12535 ... Created Successful."`

## B01 Batch of 1 SO line (sum below the row quantity: a free row stays): PASS

- Expected: one PUT 1 (+ at most one PUT 2), 1 linked row at the SO row's location, price and date kept, free row 7
- Observed: done; 1 linked rows, free line 7.0, warnings TRANSFER_STATE_UNKNOWN; 8758 ms, 2 PUT

- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12535,"DocNo":"FXT-1111D-PO","DocDate":"2026-11-11T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12536,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":7.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-11T00:00:00","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":3.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-11T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1111D-SO1","FromDocDtlKey":12527,"FullTransferOption":" ","FullTransferFromDocList":"","YourPONo":"","DtlKey":0}]}`
  - answer: `"DocNo=FXT-1111D-PO ,DocKey=12535 ... Done Edit."`
- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12535,"DocNo":"FXT-1111D-PO","DocDate":"2026-11-11T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12542,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":3.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-11T00:00:00"}]}`
  - answer: `"DocNo=FXT-1111D-PO ,DocKey=12535 ... Done Edit."`

## B02 Batch of 3 SO lines across 2 sales orders (sum equals the row quantity: the row is deleted): PASS

- Expected: one PUT 1 (+ at most one PUT 2), 3 linked rows, the row deleted (sum equals its quantity)
- Observed: done; 3 linked rows, free line none, warnings TRANSFER_STATE_UNKNOWN; 11452 ms, 2 PUT

- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12535,"DocNo":"FXT-1111D-PO","DocDate":"2026-11-11T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12537,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":12.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-11T00:00:00","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":"D","FullTransferFromDocList":""},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":4.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-11T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1111D-SO1","FromDocDtlKey":12528,"FullTransferOption":" ","FullTransferFromDocList":"","YourPONo":"","DtlKey":0},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":4.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-11T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1111D-SO1","FromDocDtlKey":12529,"FullTransferOption":" ","FullTransferFromDocList":"","YourPONo":"","DtlKey":0},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":4.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-11T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1111D-SO2","FromDocDtlKey":12531,"FullTransferOption":" ","FullTransferFromDocList":"","YourPONo":"","DtlKey":0}]}`
  - answer: `"DocNo=FXT-1111D-PO ,DocKey=12535 ... Done Edit."`
- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12535,"DocNo":"FXT-1111D-PO","DocDate":"2026-11-11T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12544,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":4.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-11T00:00:00"},{"DtlKey":12546,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":4.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-11T00:00:00"},{"DtlKey":12548,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":4.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-11T00:00:00"}]}`
  - answer: `"DocNo=FXT-1111D-PO ,DocKey=12535 ... Done Edit."`

## B03 Batch of 5 SO lines across 2 sales orders (sum below the row quantity): PASS

- Expected: one PUT 1 (+ at most one PUT 2), 5 linked rows, free row 5
- Observed: done; 5 linked rows, free line 5.0, warnings TRANSFER_STATE_UNKNOWN; 10611 ms, 2 PUT

- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12535,"DocNo":"FXT-1111D-PO","DocDate":"2026-11-11T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12538,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":5.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-11T00:00:00","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":1.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-11T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1111D-SO1","FromDocDtlKey":12527,"FullTransferOption":" ","FullTransferFromDocList":"","YourPONo":"","DtlKey":0},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":1.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-11T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1111D-SO1","FromDocDtlKey":12528,"FullTransferOption":" ","FullTransferFromDocList":"","YourPONo":"","DtlKey":0},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":1.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-11T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1111D-SO1","FromDocDtlKey":12529,"FullTransferOption":" ","FullTransferFromDocList":"","YourPONo":"","DtlKey":0},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":1.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-11T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1111D-SO2","FromDocDtlKey":12531,"FullTransferOption":" ","FullTransferFromDocList":"","YourPONo":"","DtlKey":0},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":1.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-11T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1111D-SO2","FromDocDtlKey":12532,"FullTransferOption":" ","FullTransferFromDocList":"","YourPONo":"","DtlKey":0}]}`
  - answer: `"DocNo=FXT-1111D-PO ,DocKey=12535 ... Done Edit."`
- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12535,"DocNo":"FXT-1111D-PO","DocDate":"2026-11-11T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12550,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":1.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-11T00:00:00"},{"DtlKey":12552,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":1.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-11T00:00:00"},{"DtlKey":12554,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":1.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-11T00:00:00"},{"DtlKey":12556,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":1.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-11T00:00:00"},{"DtlKey":12558,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":1.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-11T00:00:00"}]}`
  - answer: `"DocNo=FXT-1111D-PO ,DocKey=12535 ... Done Edit."`

## B04 Today's flow: the same 3 SO lines linked one call at a time (timing baseline): PASS

- Expected: three link_row calls, each its own split (PUT 1 + restore PUT)
- Observed: done, done, done; 29205 ms, 6 PUT

- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12535,"DocNo":"FXT-1111D-PO","DocDate":"2026-11-11T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12539,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":5.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-11T00:00:00","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"DtlKey":0,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":1.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-11T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1111D-SO1","FromDocDtlKey":12527,"FullTransferOption":" ","FullTransferFromDocList":""}]}`
  - answer: `"DocNo=FXT-1111D-PO ,DocKey=12535 ... Done Edit."`
- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12535,"DocNo":"FXT-1111D-PO","DocDate":"2026-11-11T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12560,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":1.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-11T00:00:00"}]}`
  - answer: `"DocNo=FXT-1111D-PO ,DocKey=12535 ... Done Edit."`
- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12535,"DocNo":"FXT-1111D-PO","DocDate":"2026-11-11T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12539,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":4.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-11T00:00:00","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"DtlKey":0,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":1.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-11T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1111D-SO1","FromDocDtlKey":12528,"FullTransferOption":" ","FullTransferFromDocList":""}]}`
  - answer: `"DocNo=FXT-1111D-PO ,DocKey=12535 ... Done Edit."`
- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12535,"DocNo":"FXT-1111D-PO","DocDate":"2026-11-11T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12562,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":1.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-11T00:00:00"}]}`
  - answer: `"DocNo=FXT-1111D-PO ,DocKey=12535 ... Done Edit."`
- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12535,"DocNo":"FXT-1111D-PO","DocDate":"2026-11-11T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12539,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":3.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-11T00:00:00","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"DtlKey":0,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":1.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-11T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1111D-SO2","FromDocDtlKey":12532,"FullTransferOption":" ","FullTransferFromDocList":""}]}`
  - answer: `"DocNo=FXT-1111D-PO ,DocKey=12535 ... Done Edit."`
- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12535,"DocNo":"FXT-1111D-PO","DocDate":"2026-11-11T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12564,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":1.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-11T00:00:00"}]}`
  - answer: `"DocNo=FXT-1111D-PO ,DocKey=12535 ... Done Edit."`

## B05 Unlink one batch row: it merges into the free row in one PUT: PASS

- Expected: unlink of a B03 batch row: ONE PUT, the row deleted, the FIRST matching free row (the B01 free row, row order) raised by its quantity, the answer names it
- Observed: done, replaced [(12550, 12536)], free row 8.0, 4703 ms, 1 PUT

- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12535,"DocNo":"FXT-1111D-PO","DocDate":"2026-11-11T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12550,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":1.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-11T00:00:00","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":"D","FullTransferFromDocList":""},{"DtlKey":12536,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":8.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-11T00:00:00","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""}]}`
  - answer: `"DocNo=FXT-1111D-PO ,DocKey=12535 ... Done Edit."`

## B06 Retry rule: a refused batch, the body fixed, the SAME key resent: PASS

- Expected: a batch with one quantity above the SO row's outstanding is refused before any PUT; the body fixed and the SAME key resent runs fresh and is done (plan 62 D6)
- Observed: first refused QTY_ABOVE_FREE (0 PUT); resend with the same key done

- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12535,"DocNo":"FXT-1111D-PO","DocDate":"2026-11-11T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12540,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":3.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-11T00:00:00","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":""},{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"","Qty":1.0,"FOCQty":0,"UnitPrice":1.0,"Discount":"","TaxCode":"","DeliveryDate":"2026-11-11T00:00:00","Desc2":"","FromDocType":"SO","FromDocNo":"FXT-1111D-SO2","FromDocDtlKey":12532,"FullTransferOption":" ","FullTransferFromDocList":"","YourPONo":"","DtlKey":0}]}`
  - answer: `"DocNo=FXT-1111D-PO ,DocKey=12535 ... Done Edit."`
- PUT /EditPurchaseOrderbydockey -> 200
  - request: `{"DocKey":12535,"DocNo":"FXT-1111D-PO","DocDate":"2026-11-11T00:00:00","CreditorCode":"400-N004","CreditorName":"","Ref":"","Description":"PURCHASE ORDER","DisplayTerm":"C.B.D.","InvAddr1":"","InvAddr2":"","InvAddr3":"","InvAddr4":"","Phone1":"","Fax1":"","Attention":"","DeliverAddr1":"","DeliverAddr2":"","DeliverAddr3":"","DeliverAddr4":"","DeliverPhone1":"","DeliverFax1":"","DeliverContact":"","CurrencyCode":"MYR","CurrencyRate":1.0,"Remark1":"","Remark2":"","Remark3":"","Remark4":"","RefDocNo":"","ShipInfo":"","InclusiveTax":"F","Details":[{"DtlKey":12566,"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SORENTO 304 KITCHEN COLD TAP (SOLID BODY)  SRTKT38SS","ProjNo":"","UOM":"UNIT","UserUOM":"UNIT","Qty":1.0,"FOCQty":0.0,"UnitPrice":1.0,"Discount":"","TaxCode":"","Desc2":"","FromDocType":"","FromDocNo":"","FromDocDtlKey":0,"FullTransferOption":" ","FullTransferFromDocList":"","DeliveryDate":"2026-11-11T00:00:00"}]}`
  - answer: `"DocNo=FXT-1111D-PO ,DocKey=12535 ... Done Edit."`

## B07 A batch above the SO row's outstanding (within the PO row's free quantity) is refused with no PUT: PASS

- Expected: a batch whose quantity is within the PO row's free quantity but above the SO row's outstanding: refused QTY_ABOVE_OUTSTANDING, naming the SO row, 0 PUTs
- Observed: refused QTY_ABOVE_OUTSTANDING (qty 8.0, outstanding 7.0, free 8.0, 0 PUT)


## B08 Create resend: the POST landed, the answer was lost; the resend finds the document (<<New>> body): PASS

- Expected: the POST lands, then times out; the resend of the SAME key looks the document up (<<New>> body: day list, debtor, time window, lines), answers done with its DocNo, 0 second POST
- Observed: first pending_verification WRITE_TIMEOUT; resend done QT-000012; 1 POST in ac_api_call_log

- POST /NewQuotation -> 200
  - request: `{"DocDate":"2026-11-11T00:00:00","DisplayTerm":"C.B.D.","CurrencyCode":"MYR","CurrencyRate":1.0,"DebtorCode":"300-S057","DocNo":"<<New>>","Details":[{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":3,"UnitPrice":1.0,"DeliveryDate":"2026-11-11T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","FullTransferOption":" ","FullTransferFromDocList":""}]}`
  - answer: `"DocNo=QT-000012 ,DocKey=12567 ... Created Successful."`

## B09 Create resend: nothing was sent; the resend finds nothing and POSTs once (<<New>> body): PASS

- Expected: the call times out before anything is sent; the resend finds no document, releases the key and POSTs once: 1 POST in total
- Observed: first pending_verification WRITE_TIMEOUT; resend done QT-000013; 1 POST in ac_api_call_log

- POST /NewQuotation -> 200
  - request: `{"DocDate":"2026-11-11T00:00:00","DisplayTerm":"C.B.D.","CurrencyCode":"MYR","CurrencyRate":1.0,"DebtorCode":"300-S057","DocNo":"<<New>>","Details":[{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":4,"UnitPrice":1.0,"DeliveryDate":"2026-11-11T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","FullTransferOption":" ","FullTransferFromDocList":""}]}`
  - answer: `"DocNo=QT-000013 ,DocKey=12569 ... Created Successful."`

## B10 Create resend: the POST landed, the answer was lost; the resend finds the document (numbered body): PASS

- Expected: numbered body: the POST lands, then times out; the resend finds the document by DocNo, answers done, 0 second POST
- Observed: first pending_verification WRITE_TIMEOUT; resend done FXT-1111D-QTN; 1 POST in ac_api_call_log

- POST /NewQuotation -> 200
  - request: `{"DocNo":"FXT-1111D-QTN","DocDate":"2026-11-11T00:00:00","DisplayTerm":"C.B.D.","CurrencyCode":"MYR","CurrencyRate":1.0,"DebtorCode":"300-S057","Details":[{"ItemCode":"SRTKT38SS","Location":"HQ","Description":"SRTKT38SS","UOM":"UNIT","Qty":5,"UnitPrice":1.0,"DeliveryDate":"2026-11-11T00:00:00","ProjNo":"","FOCQty":0,"Discount":"","TaxCode":"","Desc2":"","FullTransferOption":" ","FullTransferFromDocList":""}]}`
  - answer: `"DocNo=FXT-1111D-QTN ,DocKey=12571 ... Created Successful."`
