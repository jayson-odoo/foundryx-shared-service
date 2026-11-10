# AutoCount write API on db3: vendor update of 10 Nov 2026 (probes, 10 Nov 2026)

From Foundryx, lane SS-AC-WRITE-V2 (plan 61, `documentation/plans/sprint-5/61-autocount-write-v2.md`). Companion to
`test-report-2026-11-04.md` and `test-report-2026-11-04-qtso.md`. The vendor's 10 Nov update: delete a row with
`FullTransferOption "D"` and add a row (DtlKey 0) in the same PUT; cancel with `DELETE /Cancel<Doc>bydocno?DocNo=`;
read one document with `GET /<Doc>bydocno?DocNo=`.

All calls went to the `db3` test book, on documents we created (DocNo prefixes `FXT-1110a-` .. `FXT-1110e-`), with
unit price 1 so no credit limit is touched. Nothing was deleted. Every request, response and before / after read was
recorded exactly outside the repository; this report shows the sanitised summary (document numbers, row keys, item
codes, quantities, locations, dates). Times are UTC (add 8 h for Malaysia time).

Runs `FXT-1110a-` and `FXT-1110b-` stopped early on our side (a credit-limit refusal on large unit prices, then a script
error); their documents (`FXT-1110a-QT1`, `FXT-1110a-SO2`, `FXT-1110b-QT1`, `FXT-1110b-SO1`, `FXT-1110b-SO3`,
`FXT-1110b-SO4`, `FXT-1110b-PO1`) are left in place. Their results match run `c` below.

## Findings

| # | Finding | Probes |
|---|---|---|
| F1 | GET `/Quotationbydocno`, `/SalesOrderbydocno`, `/PurchaseOrderbydocno`, `/RequestQuotationbydocno` with `?DocNo=` answer a list holding the document; an unknown DocNo answers `[]`. The spelling `Quotaton` / `RequestQuotaton` answers 404. Path case does not matter. | P-RQ, P-CASE, every read below |
| F2 | AutoCount refuses a second transfer of a fully transferred quotation row. | P-T1 |
| F3 | "D" on a sales order row taken from a quotation removes it and gives the quantity back to the quotation. | P-D1, P-T2 |
| F4 | Unlink in one PUT works: the linked row with "D" plus a normal row (DtlKey 0). Location and DeliveryDate sent on the new row are kept, and the sales order row's quantity is freed. | P-U0..P-U4 |
| F5 | Link and relink in one PUT work ("D" on the old row plus a new linked row). The new linked row is still placed at HQ with an empty DeliveryDate and a unit price of 0 whatever was sent; a second PUT moves it and keeps the link. A purchase order row shows its link as `FromSODtlKey`. | P-L1, P-L2, P-R1, P-L4 |
| F6 | Delete line with "D" works on quotation, sales order and purchase order rows, with only `{DtlKey, FullTransferOption}` or the full row. "D" on the last row leaves a document without rows. | P-DL1, P-DL4..P-DL6 |
| F7 | "D" on a row that was transferred onward is refused (sales order row linked from a purchase order; quotation row in a sales order). | P-DL2, P-DL3 |
| F8 | One PUT is all or nothing: when the new row is invalid the "D" does not land either. | P-AT1, P-AT2 |
| F9 | Cancel of a plain quotation, sales order and purchase order works; the document then reads `Cancelled "T"`, `DocStatus "V"`. | P-C1, P-C5, P-C6 |
| F10 | Cancel again, edit after cancel, and cancel of an unknown DocNo are refused with clear text. | P-C1b, P-C1c, P-C7 |
| F11 | Cancel of a quotation already in a sales order, and of a sales order already in a purchase order, is refused. | P-C2, P-C3 |
| F12 | Cancel of a purchase order linked to a sales order frees the sales order quantity; cancel of a sales order taken from a quotation gives the quotation quantity back. | P-C4, P-C8, P-C9, P-C9b |
| F13 | A PUT with no rows and a header change applies the header and keeps every row. | P-CASE |
| F14 | A purchase order posted with `ShippingPO "T"` and a plain row is created as a normal purchase order (`ShippingPO` reads "F"). A shipping purchase order still cannot be made on db3, so no shipping purchase order probe could run. | P-SPO1 |
| F14b | `ShippingPO` "Y", "1", `true`, "t" on create, "T" with a DocNo starting `SPO`, and "T" on an edit all read back "F": the field is not taken on create or edit. | P-SPO2..P-SPO7 |
| F15 | "D" on a partly received purchase order row could not be tested: db3 has no goods received note write door. | none |

## Calls (runs `FXT-1110c-`, `FXT-1110d-`, `FXT-1110e-`)

Rows read as `DtlKey item qty location`, then the link (`link SO row <DtlKey>` for a purchase order row, `from QT <DocNo>`
for a sales order row) and the DeliveryDate. `0001-01-01` is AutoCount's empty date.

| Probe | Time (UTC) | Call | Status | Answer text | Read back after the call |
|---|---|---|---|---|---|
| S1 | 14:40:24 | POST /NewQuotation (new QT, 2 rows) | 200 | `DocNo=FXT-1110c-QT1 ,DocKey=12207 ... Created Successful.` | FXT-1110c-QT1 Cancelled F DocStatus A: 12208 SRTUB6213-BI 5 HQ date 2026-11-10; 12209 SRTKT38SS 5 HQ date 2026-11-10 |
| S2 | 14:40:25 | POST /NewSalesOrder (new SO: row from QT row A full qty 5 + normal row) | 200 | `DocNo=FXT-1110c-SO1 ,DocKey=12210 ... Created Successful.` | FXT-1110c-QT1 Cancelled F DocStatus A: 12208 SRTUB6213-BI 5 HQ date 2026-11-10; 12209 SRTKT38SS 5 HQ date 2026-11-10<br>FXT-1110c-SO1 Cancelled F DocStatus A: 12211 SRTUB6213-BI 5 HQ from QT FXT-1110c-QT1 date 2026-11-10; 12213 SRTKT38SS 10 HQ date 2026-11-10 |
| P-T1 | 14:40:25 | POST /NewSalesOrder (over-transfer: SO from QT row A again (qty 1) while A is fully transferred) | 500 | `Either no item found or item already full transferred at DocNo FXT-1110c-QT1.` | FXT-1110c-QT1 Cancelled F DocStatus A: 12208 SRTUB6213-BI 5 HQ date 2026-11-10; 12209 SRTKT38SS 5 HQ date 2026-11-10<br>none |
| P-D1 | 14:40:26 | PUT /EditSalesOrderbydockey ("D" on the SO row transferred from QT row A (only that row sent)) | 200 | `DocNo=FXT-1110c-SO1 ,DocKey=12210 ... Done Edit.` | FXT-1110c-QT1 Cancelled F DocStatus A: 12208 SRTUB6213-BI 5 HQ date 2026-11-10; 12209 SRTKT38SS 5 HQ date 2026-11-10<br>FXT-1110c-SO1 Cancelled F DocStatus A: 12213 SRTKT38SS 10 HQ date 2026-11-10 |
| P-T2 | 14:40:27 | POST /NewSalesOrder (after the D: SO from QT row A full qty 5 again (qty returned?)) | 200 | `DocNo=FXT-1110c-SO3 ,DocKey=12215 ... Created Successful.` | FXT-1110c-QT1 Cancelled F DocStatus A: 12208 SRTUB6213-BI 5 HQ date 2026-11-10; 12209 SRTKT38SS 5 HQ date 2026-11-10<br>FXT-1110c-SO3 Cancelled F DocStatus A: 12216 SRTUB6213-BI 5 HQ from QT FXT-1110c-QT1 date 2026-11-10 |
| S4 | 14:40:28 | POST /NewSalesOrder (new SO4 normal row (relink target)) | 200 | `DocNo=FXT-1110c-SO4 ,DocKey=12218 ... Created Successful.` | FXT-1110c-SO4 Cancelled F DocStatus A: 12219 SRTKT38SS 10 BRW-AM date 2026-11-10 |
| S3 | 14:40:28 | POST /NewPurchaseOrder (new PO1: normal row 10 + row linked to SO1 row N qty 4) | 200 | `DocNo=FXT-1110c-PO1 ,DocKey=12220 ... Created Successful.` | FXT-1110c-SO1 Cancelled F DocStatus A: 12213 SRTKT38SS 10 HQ date 2026-11-10<br>FXT-1110c-PO1 Cancelled F DocStatus A: 12221 SRTKT38SS 10 HQ date 2026-11-10; 12223 SRTKT38SS 4 HQ link SO row 12213 date 0001-01-01 |
| P-U0 | 14:40:29 | PUT /EditSalesOrderbydockey (control: cut SO1 row N to 3 (< linked 4) before unlink) | 500 | `The quantity of the item code SRTKT38SS is less than the quantity it was partially transferred to Purchase Ord` | FXT-1110c-SO1 Cancelled F DocStatus A: 12213 SRTKT38SS 10 HQ date 2026-11-10 |
| P-U1 | 14:40:30 | PUT /EditPurchaseOrderbydockey (unlink: linked row D + new normal row DtlKey 0 (one PUT)) | 200 | `DocNo=FXT-1110c-PO1 ,DocKey=12220 ... Done Edit.` | FXT-1110c-SO1 Cancelled F DocStatus A: 12213 SRTKT38SS 10 HQ date 2026-11-10<br>FXT-1110c-PO1 Cancelled F DocStatus A: 12221 SRTKT38SS 10 HQ date 2026-11-10; 12224 SRTKT38SS 4 HQ date 2026-11-20 |
| P-U2 | 14:40:31 | PUT /EditSalesOrderbydockey (after unlink: cut SO1 row N to 3 (freed?)) | 200 | `DocNo=FXT-1110c-SO1 ,DocKey=12210 ... Done Edit.` | FXT-1110c-SO1 Cancelled F DocStatus A: 12213 SRTKT38SS 3 HQ date 2026-11-10 |
| P-U3 | 14:40:32 | PUT /EditSalesOrderbydockey (restore SO1 row N to 10) | 200 | `DocNo=FXT-1110c-SO1 ,DocKey=12210 ... Done Edit.` | FXT-1110c-SO1 Cancelled F DocStatus A: 12213 SRTKT38SS 10 HQ date 2026-11-10 |
| P-L1 | 14:40:33 | PUT /EditPurchaseOrderbydockey (link whole normal row: D + new linked row DtlKey 0, Location BRW-AM, DeliveryDate 21 Nov) | 200 | `DocNo=FXT-1110c-PO1 ,DocKey=12220 ... Done Edit.` | FXT-1110c-SO1 Cancelled F DocStatus A: 12213 SRTKT38SS 10 HQ date 2026-11-10<br>FXT-1110c-PO1 Cancelled F DocStatus A: 12224 SRTKT38SS 4 HQ date 2026-11-20; 12226 SRTKT38SS 10 HQ link SO row 12213 date 0001-01-01 |
| P-L2 | 14:40:33 | PUT /EditPurchaseOrderbydockey (move: Location BRW-AM + DeliveryDate on the new linked row (second PUT)) | 200 | `DocNo=FXT-1110c-PO1 ,DocKey=12220 ... Done Edit.` | FXT-1110c-SO1 Cancelled F DocStatus A: 12213 SRTKT38SS 10 HQ date 2026-11-10<br>FXT-1110c-PO1 Cancelled F DocStatus A: 12224 SRTKT38SS 4 HQ date 2026-11-20; 12226 SRTKT38SS 10 BRW-AM link SO row 12213 date 2026-11-21 |
| P-R1 | 14:40:34 | PUT /EditPurchaseOrderbydockey (relink: row linked to SO1 N -> D + new row linked to SO4 M) | 200 | `DocNo=FXT-1110c-PO1 ,DocKey=12220 ... Done Edit.` | FXT-1110c-SO1 Cancelled F DocStatus A: 12213 SRTKT38SS 10 HQ date 2026-11-10<br>FXT-1110c-SO4 Cancelled F DocStatus A: 12219 SRTKT38SS 10 BRW-AM date 2026-11-10<br>FXT-1110c-PO1 Cancelled F DocStatus A: 12224 SRTKT38SS 4 HQ date 2026-11-20; 12228 SRTKT38SS 10 HQ link SO row 12219 date 0001-01-01 |
| P-DL1 | 14:40:35 | PUT /EditPurchaseOrderbydockey (delete line, minimal row {DtlKey, FullTransferOption D}) | 200 | `DocNo=FXT-1110c-PO1 ,DocKey=12220 ... Done Edit.` | FXT-1110c-PO1 Cancelled F DocStatus A: 12228 SRTKT38SS 10 HQ link SO row 12219 date 0001-01-01 |
| P-AT0 | 14:40:35 | PUT /EditPurchaseOrderbydockey (add a normal row (setup for atomicity)) | 200 | `DocNo=FXT-1110c-PO1 ,DocKey=12220 ... Done Edit.` | FXT-1110c-PO1 Cancelled F DocStatus A: 12228 SRTKT38SS 10 HQ link SO row 12219 date 0001-01-01; 12229 SRTKT38SS 2 HQ date 2026-11-10 |
| P-AT1 | 14:40:36 | PUT /EditPurchaseOrderbydockey (atomic? D on row + invalid new row (unknown item)) | 500 | `The following item codes are not exist, save aborted. (Not Exist Item Code: FXT-NO-SUCH-ITEM)` | FXT-1110c-PO1 Cancelled F DocStatus A: 12228 SRTKT38SS 10 HQ link SO row 12219 date 0001-01-01; 12229 SRTKT38SS 2 HQ date 2026-11-10 |
| P-AT2 | 14:40:37 | PUT /EditPurchaseOrderbydockey (atomic? D on row + new row linked to a missing SO row) | 500 | `Invalid transfer item.` | FXT-1110c-PO1 Cancelled F DocStatus A: 12228 SRTKT38SS 10 HQ link SO row 12219 date 0001-01-01; 12229 SRTKT38SS 2 HQ date 2026-11-10 |
| P-DL2 | 14:40:37 | PUT /EditSalesOrderbydockey (D on an SO row a PO row links to (SO4 M <- PO1)) | 500 | `This item has been transferred to Purchase Order, you are not allow to delete it!` | FXT-1110c-PO1 Cancelled F DocStatus A: 12228 SRTKT38SS 10 HQ link SO row 12219 date 0001-01-01; 12229 SRTKT38SS 2 HQ date 2026-11-10<br>FXT-1110c-SO4 Cancelled F DocStatus A: 12219 SRTKT38SS 10 BRW-AM date 2026-11-10 |
| P-DL3 | 14:40:38 | PUT /EditQuotationbydockey (D on a QT row that is transferred into SO3) | 500 | `This item has been partial transferred to Sales Order, you are not allow to delete it!` | FXT-1110c-SO3 Cancelled F DocStatus A: 12216 SRTUB6213-BI 5 HQ from QT FXT-1110c-QT1 date 2026-11-10<br>FXT-1110c-QT1 Cancelled F DocStatus A: 12208 SRTUB6213-BI 5 HQ date 2026-11-10; 12209 SRTKT38SS 5 HQ date 2026-11-10 |
| P-CASE | 14:40:38 | PUT /EditPurchaseOrderByDocKey (path case: /EditPurchaseOrderByDocKey, header Remark1 only, no rows) | 200 | `DocNo=FXT-1110c-PO1 ,DocKey=12220 ... Done Edit.` | FXT-1110c-PO1 Cancelled F DocStatus A: 12228 SRTKT38SS 10 HQ link SO row 12219 date 0001-01-01; 12229 SRTKT38SS 2 HQ date 2026-11-10 |
| S5 | 14:40:39 | POST /NewQuotation (new QT5 plain) | 200 | `DocNo=FXT-1110c-QT5 ,DocKey=12233 ... Created Successful.` | FXT-1110c-QT5 Cancelled F DocStatus A: 12234 SRTKT38SS 1 HQ date 2026-11-10 |
| P-C1 | 14:40:40 | DELETE /CancelQuotationbydocno?DocNo=FXT-1110c-QT5 (DELETE cancel plain QT) | 200 | `DocNo=FXT-1110c-QT5 ... was cancelled.` | FXT-1110c-QT5 Cancelled T DocStatus V: 12234 SRTKT38SS 1 HQ date 2026-11-10 |
| P-C1b | 14:40:40 | DELETE /CancelQuotationbydocno?DocNo=FXT-1110c-QT5 (DELETE cancel again (already cancelled)) | 400 | `Unable to (Cancel Document) for this document, due to current document status (Void).` | FXT-1110c-QT5 Cancelled T DocStatus V: 12234 SRTKT38SS 1 HQ date 2026-11-10 |
| P-C1c | 14:40:41 | PUT /EditQuotationbydockey (edit a cancelled QT (Remark1)) | 500 | `You are not allowed to edit expired or void document.` | FXT-1110c-QT5 Cancelled T DocStatus V: 12234 SRTKT38SS 1 HQ date 2026-11-10 |
| P-C2 | 14:40:41 | DELETE /CancelQuotationbydocno?DocNo=FXT-1110c-QT1 (DELETE cancel QT1 whose row A is transferred into SO3) | 400 | `The document was transfered to other document, so it is not allow to cancel.` | FXT-1110c-SO3 Cancelled F DocStatus A: 12216 SRTUB6213-BI 5 HQ from QT FXT-1110c-QT1 date 2026-11-10<br>FXT-1110c-QT1 Cancelled F DocStatus A: 12208 SRTUB6213-BI 5 HQ date 2026-11-10; 12209 SRTKT38SS 5 HQ date 2026-11-10 |
| P-C3 | 14:40:41 | DELETE /CancelSalesOrderbydocno?DocNo=FXT-1110c-SO4 (DELETE cancel SO4 whose row M is linked from PO1) | 400 | `The Sales Order was transfered to Purchase Order, so it is not allow to cancel.` | FXT-1110c-PO1 Cancelled F DocStatus A: 12228 SRTKT38SS 10 HQ link SO row 12219 date 0001-01-01; 12229 SRTKT38SS 2 HQ date 2026-11-10<br>FXT-1110c-SO4 Cancelled F DocStatus A: 12219 SRTKT38SS 10 BRW-AM date 2026-11-10 |
| P-C4 | 14:40:42 | DELETE /CancelPurchaseOrderbydocno?DocNo=FXT-1110c-PO1 (DELETE cancel PO1 (rows linked to SO4)) | 200 | `DocNo=FXT-1110c-PO1 ... was cancelled.` | FXT-1110c-SO4 Cancelled F DocStatus A: 12219 SRTKT38SS 10 BRW-AM date 2026-11-10<br>FXT-1110c-PO1 Cancelled T DocStatus V: 12228 SRTKT38SS 10 HQ link SO row 12219 date 0001-01-01; 12229 SRTKT38SS 2 HQ date 2026-11-10 |
| S6 | 14:40:42 | POST /NewSalesOrder (new SO6 plain) | 200 | `DocNo=FXT-1110c-SO6 ,DocKey=12235 ... Created Successful.` | FXT-1110c-SO6 Cancelled F DocStatus A: 12236 SRTKT38SS 1 HQ date 2026-11-10 |
| P-C5 | 14:40:43 | DELETE /CancelSalesOrderbydocno?DocNo=FXT-1110c-SO6 (DELETE cancel plain SO) | 200 | `DocNo=FXT-1110c-SO6 ... was cancelled.` | FXT-1110c-SO6 Cancelled T DocStatus V: 12236 SRTKT38SS 1 HQ date 2026-11-10 |
| S7 | 14:40:43 | POST /NewPurchaseOrder (new PO7 plain) | 200 | `DocNo=FXT-1110c-PO7 ,DocKey=12237 ... Created Successful.` | FXT-1110c-PO7 Cancelled F DocStatus A: 12238 SRTKT38SS 1 HQ date 2026-11-10 |
| P-C6 | 14:40:44 | DELETE /CancelPurchaseOrderbydocno?DocNo=FXT-1110c-PO7 (DELETE cancel plain PO) | 200 | `DocNo=FXT-1110c-PO7 ... was cancelled.` | FXT-1110c-PO7 Cancelled T DocStatus V: 12238 SRTKT38SS 1 HQ date 2026-11-10 |
| P-C7 | 14:40:45 | DELETE /CancelSalesOrderbydocno?DocNo=FXT-1110c-NOPE (DELETE cancel a DocNo that does not exist) | 400 | `DocNo=FXT-1110c-NOPE ... failed to cancel.` | none |
| P-SPO1 | 14:40:45 | POST /NewPurchaseOrder (SPO create: NewPurchaseOrder ShippingPO T, full body) | 200 | `DocNo=FXT-1110c-SPO1 ,DocKey=12239 ... Created Successful.` | FXT-1110c-SPO1 Cancelled F DocStatus A: 12240 SRTKT38SS 3 HQ date 2026-11-10 |
| P-RQ | 14:40:45 | GET /RequestQuotationbydocno?DocNo=FXT-1110c-X (RQ GET path exists?) | 200 | `[]` |  |
| P-RQ | 14:40:45 | GET /RequestQuotatonbydocno?DocNo=FXT-1110c-X (RQ GET path exists?) | 404 | `{'Message': "No HTTP resource was found that matches the request URI 'http://hapi.sorento.cc.cd/api/db3/Reques` |  |
| P-C8 | 14:41:38 | PUT /EditSalesOrderbydockey (after PO1 cancel: cut SO4 row (was PO-linked 10) to 3 (freed?)) | 200 | `DocNo=FXT-1110c-SO4 ,DocKey=12218 ... Done Edit.` | FXT-1110c-SO4 Cancelled F DocStatus A: 12219 SRTKT38SS 3 BRW-AM date 2026-11-10 |
| P-C9 | 14:41:39 | DELETE /CancelSalesOrderbydocno?DocNo=FXT-1110c-SO3 (DELETE cancel SO3 (its row came from QT1 row A)) | 200 | `DocNo=FXT-1110c-SO3 ... was cancelled.` | FXT-1110c-QT1 Cancelled F DocStatus A: 12208 SRTUB6213-BI 5 HQ date 2026-11-10; 12209 SRTKT38SS 5 HQ date 2026-11-10<br>FXT-1110c-SO3 Cancelled T DocStatus V: 12216 SRTUB6213-BI 5 HQ from QT FXT-1110c-QT1 date 2026-11-10 |
| P-C9b | 14:41:40 | POST /NewSalesOrder (after SO3 cancel: SO from QT1 row A full qty 5 (qty returned by cancel?)) | 200 | `DocNo=FXT-1110d-SO1 ,DocKey=12241 ... Created Successful.` | FXT-1110c-QT1 Cancelled F DocStatus A: 12208 SRTUB6213-BI 5 HQ date 2026-11-10; 12209 SRTKT38SS 5 HQ date 2026-11-10<br>FXT-1110d-SO1 Cancelled F DocStatus A: 12242 SRTUB6213-BI 5 HQ from QT FXT-1110c-QT1 date 2026-11-10 |
| S8 | 14:41:41 | POST /NewPurchaseOrder (new PO linked to SO1 row N qty 4) | 200 | `DocNo=FXT-1110d-PO1 ,DocKey=12244 ... Created Successful.` | FXT-1110c-SO1 Cancelled F DocStatus A: 12213 SRTKT38SS 10 HQ date 2026-11-10<br>FXT-1110d-PO1 Cancelled F DocStatus A: 12246 SRTKT38SS 4 HQ link SO row 12213 date 0001-01-01 |
| P-U4 | 14:41:42 | PUT /EditPurchaseOrderbydockey (unlink with Location BRW-AM + DeliveryDate 23 Nov on the new normal row, same PUT) | 200 | `DocNo=FXT-1110d-PO1 ,DocKey=12244 ... Done Edit.` | FXT-1110c-SO1 Cancelled F DocStatus A: 12213 SRTKT38SS 10 HQ date 2026-11-10<br>FXT-1110d-PO1 Cancelled F DocStatus A: 12247 SRTKT38SS 4 BRW-AM date 2026-11-23 |
| P-L4 | 14:41:43 | PUT /EditPurchaseOrderbydockey (add a linked row only (DtlKey 0), Location BRW-AM: still forced HQ?) | 200 | `DocNo=FXT-1110d-PO1 ,DocKey=12244 ... Done Edit.` | FXT-1110c-SO1 Cancelled F DocStatus A: 12213 SRTKT38SS 10 HQ date 2026-11-10<br>FXT-1110d-PO1 Cancelled F DocStatus A: 12247 SRTKT38SS 4 BRW-AM date 2026-11-23; 12249 SRTKT38SS 1 HQ link SO row 12213 date 0001-01-01 |
| S9 | 14:42:16 | POST /NewQuotation (new QT, 2 plain rows) | 200 | `DocNo=FXT-1110e-QT1 ,DocKey=12250 ... Created Successful.` | FXT-1110e-QT1 Cancelled F DocStatus A: 12251 SRTUB6213-BI 2 HQ date 2026-11-10; 12252 SRTKT38SS 3 HQ date 2026-11-10 |
| P-DL4 | 14:42:17 | PUT /EditQuotationbydockey (D on a plain QT row (full row shape)) | 200 | `DocNo=FXT-1110e-QT1 ,DocKey=12250 ... Done Edit.` | FXT-1110e-QT1 Cancelled F DocStatus A: 12251 SRTUB6213-BI 2 HQ date 2026-11-10 |
| S10 | 14:42:18 | POST /NewSalesOrder (new SO, 2 plain rows) | 200 | `DocNo=FXT-1110e-SO1 ,DocKey=12253 ... Created Successful.` | FXT-1110e-SO1 Cancelled F DocStatus A: 12254 SRTUB6213-BI 2 HQ date 2026-11-10; 12255 SRTKT38SS 3 HQ date 2026-11-10 |
| P-DL5 | 14:42:18 | PUT /EditSalesOrderbydockey (D on a plain SO row (full row shape)) | 200 | `DocNo=FXT-1110e-SO1 ,DocKey=12253 ... Done Edit.` | FXT-1110e-SO1 Cancelled F DocStatus A: 12254 SRTUB6213-BI 2 HQ date 2026-11-10 |
| P-DL6 | 14:42:19 | PUT /EditSalesOrderbydockey (D on the last remaining SO row (doc with no rows?)) | 200 | `DocNo=FXT-1110e-SO1 ,DocKey=12253 ... Done Edit.` | FXT-1110e-SO1 Cancelled F DocStatus A: no rows |

## Shipping purchase order flag (10 Nov 2026, about 15:55 UTC)

| Probe | Call | Status | Read back |
|---|---|---|---|
| P-SPO2 | POST /NewPurchaseOrder FXT-1110f-SPO1, `ShippingPO "Y"` | 200 created | `ShippingPO "F"` |
| P-SPO3 | POST /NewPurchaseOrder FXT-1110f-SPO2, `ShippingPO "1"` | 200 created | `ShippingPO "F"` |
| P-SPO4 | POST /NewPurchaseOrder FXT-1110f-SPO3, `ShippingPO true` | 200 created | `ShippingPO "F"` |
| P-SPO5 | POST /NewPurchaseOrder FXT-1110f-SPO4, `ShippingPO "t"` | 200 created | `ShippingPO "F"` |
| P-SPO6 | PUT /EditPurchaseOrderbydockey FXT-1110f-SPO1, header `ShippingPO "T"`, no rows | 200 `Done Edit.` | `ShippingPO "F"` |
| P-SPO7 | POST /NewPurchaseOrder SPO-FXT-1110f-1 (DocNo starting SPO), `ShippingPO "T"` | 200 created | `ShippingPO "F"` |

Each document has one plain row (SRTKT38SS qty 1). The wrapper does not take `ShippingPO` on create or edit today.

## Link follow-up (11 Nov 2026, db3, UTC)

| Probe | Call | Status | Read back |
|---|---|---|---|
| P-L5 | PUT /EditPurchaseOrderbydockey FXT-1110d-PO1, the linked row 12249 (read: UnitPrice 0, HQ, empty date) sent with UnitPrice 1, Location BRW-AM, DeliveryDate 2026-11-24 | 200 `Done Edit.` | row 12249 UnitPrice 1, BRW-AM, 2026-11-24, still linked to SO row 12213 |
| P-R2 | PUT /EditSalesOrderbydockey FXT-1110c-SO1, row 12213 qty 10 -> 2 (after P-R1 moved the 10-qty link to FXT-1110c-SO4 row 12219; 1 still linked from FXT-1110d-PO1) | 200 `Done Edit.` | row 12213 qty 2: the change link freed the old sales order row |

A second PUT restores the price, location and date a new linked row loses (F5), and a change of link frees the old
sales order row's quantity.
