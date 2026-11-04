# AutoCount write API on db3: Quotation and Sales Order probes (4 Nov 2026)

From Foundryx, lane AC-WRITE-QTSO (plan 57). Companion to `test-report-2026-11-04.md` (PO links).
All calls went to the `db3` test book through our write client, on documents we created (DocNo prefix
`FXT-1104q-`), except the two numbering probes noted below. Nothing was deleted. Every request,
response and before / after read was recorded exactly (15 writes, every one recorded); this report
shows the sanitised summary. Times are UTC (add 8 h for Malaysia time). Rows read as
`DtlKey item qty location unit price`.

| Probe | Time | Call | Status | Answer text | Rows read back after the call | Observed |
|---|---|---|---|---|---|---|
| P-QT1 | 09:39:47 | POST /NewQuotation FXT-1104q-QT1 | 200 | `DocNo=FXT-1104q-QT1 ,DocKey=12060 ... Created Successful.` | 12061 SRTUB6213-BI 1 HQ 900; 12062 SRTKT38SS 5 BRW-AM 126 | created as sent; header `Cancelled F`, `DocStatus A`, `ToDocType ""` |
| P-QT2 | 09:40:00 | PUT /EditQuotationbydockey 12060 | 200 | `... Done Edit.` | 12061 SRTUB6213-BI 2 HQ 850 (Discount "5%"); 12062 SRTKT38SS 5 HQ 126; 12063 SRTKT38SS 3 HQ 126 | every change applied: Ref, Description, Remark1, qty, unit price, discount, location, new row |
| P-QT3 setup | 09:40:13 | POST /NewQuotation FXT-1104q-QT4 | 200 | `DocNo=FXT-1104q-QT4 ,DocKey=12064 ...` | 12065 SRTUB6213-BI 1 HQ 900; 12066 SRTKT38SS 5 HQ 126 | created |
| P-QT3 | 09:40:14 | PUT /EditQuotationbydockey 12064, only row 12066 with Qty 0 | 200 | `... Done Edit.` | 12065 unchanged; 12066 SRTKT38SS 0 HQ 126 | Qty 0 accepted; the omitted row kept |
| P-DOC1 | 09:40:23 | POST /NewQuotation (our script error: DocNo `SO390188`) | 200 | `DocNo=SO390188 ,DocKey=12067 ...` | 12068 SRTUB6213-BI 1 HQ 900 | a quotation numbered SO390188 was created by mistake (Ref `P-DOC1-FXT1104q`); your sales order SO390188 untouched; clean-up asked in AQ34 |
| P-DOC2 | 09:40:24 | POST /NewQuotation DocNo `"<<New>>"` | 200 | `DocNo=QT-000001 ,DocKey=12069 ...` | 12070 SRTUB6213-BI 1 HQ 900 | AutoCount assigns the next number |
| P-DOC1b | 09:40:38 | POST /NewQuotation without DocNo | 500 | `Column 'DocNo' does not allow nulls` | none | DocNo is required |
| P-SO0 | 09:40:49 | POST /NewSalesOrder FXT-1104q-SO1, row from quotation row 12061 (FromDocType QT, FromDocNo FXT-1104q-QT1, FromDocDtlKey 12061, FullTransferOption " ") | 200 | `DocNo=FXT-1104q-SO1 ,DocKey=12072 ...` | 12073 SRTUB6213-BI 1 HQ 850 (FromDocType QT, FromDocNo FXT-1104q-QT1, FromDocDtlKey 0) | created; `FromDocDtlKey` reads 0 and the quotation shows no `ToDocType` / `ToDocKey` (AQ31) |
| P-SO1 | 09:41:01 | PUT /EditSalesOrderbydockey 12072 | 200 | `... Done Edit.` | 12073 SRTUB6213-BI 2 HQ 800 (Discount ""); 12075 SRTKT38SS 1 HQ 126 | the SO edit door exists; qty, price, discount and the new row applied (AQ33) |
| P-CX1 setup | 09:41:12 | POST /NewQuotation FXT-1104q-QT3 | 200 | `DocNo=FXT-1104q-QT3 ,DocKey=12076 ...` | 12077 SRTUB6213-BI 1 HQ 900 | created |
| P-CX1 | 09:41:13 | PUT /EditQuotationbydockey 12076, header `Cancelled "T"` | 200 | `... Done Edit.` | 12077 unchanged | NOT cancelled: `Cancelled` reads "F" (AQ32) |
| P-CX2 | 09:41:14 | same with `Cancelled "F"` | 200 | `... Done Edit.` | 12077 unchanged | no change |
| P-CX3 setup | 09:41:14 | POST /NewSalesOrder FXT-1104q-SO2 | 200 | `DocNo=FXT-1104q-SO2 ,DocKey=12078 ...` | 12079 SRTUB6213-BI 1 HQ 900 | created |
| P-CX3 | 09:41:15 | PUT /EditSalesOrderbydockey 12078, header `Cancelled "T"` | 200 | `... Done Edit.` | 12079 unchanged | NOT cancelled: `Cancelled` reads "F" (AQ32) |

## What this means for us

- Quotation create and edit, and Sales Order create and edit, work as documented (plus the SO edit door).
- Create answers carry the new DocNo and DocKey; we read the document back by that DocKey.
- Cancel is not possible through the API today; our cancel stays switched off until you add a door (AQ2).
- A Sales Order row taken from a quotation row keeps `FromDocType` / `FromDocNo` but not the row key, and
  the quotation shows no transfer (AQ31); we report that as a warning, never as a failure.

## Sales order line linked to a purchase order line (4 Nov 2026, db3, UTC)

Question: what happens when a sales order line that a purchase order line is linked to is cut or changed?
A true delete can only be tested once your delete API ships; these are the edits possible today. Test
documents FXT-1104r-SO1 (DocKey 12085: row A 12086 qty 10, row B 12087 qty 5, both BRW-AM) and
FXT-1104r-PO1 (DocKey 12083: row 12084 cut to 10 HQ unlinked, row 12089 qty 10 linked to SO row 12086).
Nine writes, every one recorded exactly.

| Probe | Time | Call | Status | AutoCount answer | Observed |
|---|---|---|---|---|---|
| P-SL0a | 10:18:32 | POST /NewSalesOrder, debtor 301-B018 | 500 | `This account had violated the credit limit. You are not allow to save.` | not created; a clear business error (retried with debtor 300-S057: 200, DocKey 12085) |
| P-SL0b | 10:18:35 | POST /NewPurchaseOrder FXT-1104r-PO1 | 200 | `DocNo=FXT-1104r-PO1 ,DocKey=12083 ... Created Successful.` | row 12084 20 HQ |
| P-SL0c | 10:18:57 | PUT /EditPurchaseOrderbydockey: row 12084 to 10, new row 10 linked to SO row 12086 | 200 | `... Done Edit.` | new row 12089 reads `FromSODtlKey 12086`; the sales order shows no change (no transferred or to-document field) |
| P-SL1 | 10:19:13 | PUT /EditSalesOrderbydockey: row 12086 Qty 0 | 500 | `The quantity of the item code SRTKT38SS is less than the quantity it was partially transferred to Purchase Order, save aborted.` | refused; sales order unchanged; PO link kept |
| P-SL2 | 10:19:14 | same, Qty 4 (below the 10 linked) | 500 | same message | refused; unchanged |
| P-SL3 | 10:19:16 | same row, ItemCode changed to SRTKS7090 | 200 | `... Done Edit.` | ACCEPTED: the SO row now reads SRTKS7090 while the PO row stays linked to it (AQ36) |
| P-SL4 | 10:19:17 | restore Qty 10, ItemCode SRTKT38SS | 200 | `... Done Edit.` | restored; link intact |
| P-SL5 | 10:19:18 | control: unlinked row 12087 Qty 0 | 200 | `... Done Edit.` | row reads 0; totals fall |

So today AutoCount refuses, with a clear message, any cut of a sales order line below what purchase order
lines have taken from it. We expect a delete of such a line to be refused the same way (AQ35).

## Runner suite through our write layer (4 Nov 2026, db3, tag 1104v)

Our db3 runner (`write_back/runner.py`, `--suite qtso`) ran these cases through the shared service's own
primitives and operations, debtor 300-S057; every vendor write was recorded exactly (private evidence file).

| Case | What | Result | Documents |
|---|---|---|---|
| Q01 | Create a quotation, once with `"<<New>>"` and once with our number | PASS | QT-000005 (DocKey 12112), FXT-1104v-QT (12114) |
| Q02 | Edit the quotation: header, qty, unit price, discount, location | PASS | 12114 |
| Q03 | Add a quotation line, then move a line's location | PASS | new row 12116 |
| Q04 | Sales order from the quotation row | PASS with warning `QT_ROW_LINK_UNCONFIRMED` | FXT-1104v-SO (12117) |
| Q05 | Edit the sales order and add a line | PASS | 12117 |
| Q06 / Q07 | Cancel quotation / sales order | refused by us before any call (`VENDOR_UNSUPPORTED`, AQ2) | none |
| Q08 | Delete a sales order line | refused by us before any call (waiting for your delete door) | none |
| Q09 | Link / unlink / relink a PO line | refused by us before any call (needs the delete door) | none |

Two findings from the earlier attempts (tags 1104s, 1104t, 1104u, also on db3):
- A sales order line sent without the full row shape of your sample (`FullTransferOption " "`,
  `FullTransferFromDocList ""`, `YourPONo`, `ProjNo`, `FOCQty`, `Discount`, `TaxCode`, `Desc2`) is answered 200
  `Created Successful.` / `Done Edit.` but reads back with no row. Is that intended? (AQ38)
- A sales order line taken from a quotation line takes that line's unit price and location, whatever we send.
  Is that intended, and can a different price be sent on the transfer? (AQ39)
